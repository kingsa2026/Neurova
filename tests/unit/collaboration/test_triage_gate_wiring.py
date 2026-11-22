# -*- coding: utf-8 -*-
"""SB-4 小脑分诊门接线测试：Layer 6 真实现 + skip 语义 + 三档开关。

出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md
§3 级联 / §6 skip 语义 / §7 治理开关 / §8-SB-4 拆卡。

覆盖面：
- 三档开关解析：env 最优先、非法值按 off、设置键 fallback、默认 off；
- Layer 6：off 档与旧行为逐字节一致（零副作用）、shadow 只计数、
  enforce 规则命中真拦截（details 带 source/rule/features）；
- 灰区级联：按 NeuJudge（真实 neu_judge_default.json）的档位走；
  模型产物损坏 → 诚实降级仅规则（失败标记只加载一次）；
- skip 语义：requestYieldGate 遇 triage_gate 立即返回（attempts=1、不等待）、
  requestTurnAdmission 把 running 行收成 failed/triage_gate_skip、不产生 parked；
- 调用点：/v1/chat 非流式与流式、channel_router 的 skip 分支；
- 旧缓存面（_triage_cache / cache_triage_result / triage_cache_size）全仓退役。

事件种子一律用真实 SessionSyncManager 公开 API 灌入（register_or_create_session
+ add_event），不用 MagicMock 顶替；env 用 monkeypatch 隔离。
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.collaboration import glance_yield_rules as gyr  # noqa: E402
from neurova.collaboration.glance_yield_rules import (  # noqa: E402
    GlanceYieldChecker,
    YieldReason,
    triageGateMode,
)
from neurova.collaboration.neu_judge import (  # noqa: E402
    NeuJudge,
    NeuJudgeUnavailable,
    SKIP_P,
)
from neurova.collaboration.triage_rules import extractTriageFeatures  # noqa: E402
from neurova.sync import session_sync_manager as ssm  # noqa: E402
from neurova.sync.session_sync_manager import (  # noqa: E402
    EventType,
    SessionEvent,
    SessionSyncManager,
)

ENV_MODE = "NEUROVA_TRIAGE_GATE_MODE"
CONV = "triage-conv"
AGENT_ID = "api-agent"
OWNER = "triage-owner"

_MISSING = object()


# ---------------------------------------------------------------------------
# 隔离与种子
# ---------------------------------------------------------------------------

def _isolateChecker(monkeypatch) -> GlanceYieldChecker:
    """把进程级单例换成本用例独占的 checker（沿 test_yieldGateWaitPolicy 惯例）。"""
    checker = GlanceYieldChecker()
    monkeypatch.setattr(gyr, "_glance_checker_instance", checker, raising=False)
    return checker


@pytest.fixture()
def syncManager(monkeypatch):
    """独立的 SessionSyncManager 实例顶到单例位——分诊门的进料口读它。"""
    ssm.reset_session_sync_manager()
    manager = SessionSyncManager(
        config={"max_sessions": 200, "session_timeout": 3600, "max_history_size": 5000}
    )
    monkeypatch.setattr(ssm, "_manager_instance", manager)
    yield manager
    ssm.reset_session_sync_manager()


def _seedSoloLoop(manager: SessionSyncManager, sessionId: str, count: int,
                  stepSeconds: float = 5.0, prefix: str = "solo loop message") -> None:
    """灌 count 条互不相同的 assistant 消息（无人类）——独走环窗口。"""
    session = manager.register_or_create_session(sessionId, user_id="seed-user", agent_id="seed-agent")
    base = datetime.now(timezone.utc) - timedelta(minutes=30)
    for i in range(count):
        session.add_event(SessionEvent(
            event_type=EventType.AGENT_REPLY,
            payload={"content": f"{prefix} {i} with distinct content"},
            timestamp=base + timedelta(seconds=i * stepSeconds),
        ))


def _seedHumanLast(manager: SessionSyncManager, sessionId: str) -> None:
    session = manager.get_session(sessionId)
    assert session is not None
    session.add_event(SessionEvent(
        event_type=EventType.USER_MESSAGE,
        payload={"content": "我在，请继续"},
        timestamp=datetime.now(timezone.utc),
    ))


@pytest.fixture()
def runStore(tmp_path, monkeypatch):
    """真实 agent_run_store（临时库），沿 test_v1ChatRunLedger 的装配惯例。"""
    from neurova.core import agent_run_store as ars

    db = tmp_path / "triage-gate.db"
    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(db))
    monkeypatch.setenv("NEUROVA_RUN_GATE", "on")
    monkeypatch.setenv("NEUROVA_YIELD_MAX_ATTEMPTS", "10")
    monkeypatch.setenv("NEUROVA_YIELD_WAIT_CAP_SECONDS", "0.05")
    ars.reset_agent_run_store()
    store = ars.AgentRunStore(db)
    monkeypatch.setattr(ars, "_store", store)
    yield store
    ars.reset_agent_run_store()


class _FakeAgent:
    """最小 agent 替身（沿用 test_v1ChatRunLedger 的 _FakeAgent 形态）：
    只记录 chat 是否被调用；被 skip 的回合绝不允许打到它。"""

    def __init__(self):
        self.calls = []
        self.config = SimpleNamespace(owner_user_id=OWNER, attachment_dir="")

    async def chat(self, user_input=None, stream=False, session_id=None,
                   metadata=None, model=None, **kw):
        self.calls.append({"user_input": user_input, "session_id": session_id})
        emit = (metadata or {}).get("event_emitter")
        if emit:
            emit("content", "should-not-run")
        return {"text": "should-not-run", "tool_messages": [], "reasoning": ""}


@pytest.fixture()
def chatClient(request, monkeypatch):
    """真 app + 身份覆盖 + _get_agent 替身（沿 test_v1ChatRunLedger.makeClient）。"""
    from fastapi.testclient import TestClient

    import neurova.api.auth as api_auth
    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user as depsUser
    from neurova.api.endpoints import chat as chat_mod

    agent = _FakeAgent()
    monkeypatch.setattr(chat_mod, "_get_agent", lambda agent_id="": agent)
    app = create_app(enable_memory=False, enable_channels=False)
    identity = {"user_id": OWNER, "username": OWNER, "role": "user"}
    keys = [api_auth.get_current_user, depsUser]
    previous = {key: app.dependency_overrides.get(key, _MISSING) for key in keys}
    for key in keys:
        app.dependency_overrides[key] = lambda: dict(identity)

    def _restore() -> None:
        for key in keys:
            if previous[key] is _MISSING:
                app.dependency_overrides.pop(key, None)
            else:
                app.dependency_overrides[key] = previous[key]

    request.addfinalizer(_restore)
    return TestClient(app), agent


def _dataEvents(text: str):
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            import json
            try:
                events.append(json.loads(line[6:]))
            except Exception:
                pass
    return events


# ---------------------------------------------------------------------------
# 三档开关解析
# ---------------------------------------------------------------------------

class TestTriageGateMode:
    def test_envExplicitValuesWin(self, monkeypatch):
        for mode in ("off", "shadow", "enforce"):
            monkeypatch.setenv(ENV_MODE, mode)
            assert triageGateMode() == mode

    def test_envCaseAndWhitespaceNormalized(self, monkeypatch):
        monkeypatch.setenv(ENV_MODE, "  ENFORCE ")
        assert triageGateMode() == "enforce"

    def test_envIllegalValueFallsBackToOff(self, monkeypatch):
        monkeypatch.setenv(ENV_MODE, "yes-please")
        assert triageGateMode() == "off"

    def test_settingsKeyUsedWhenEnvUnset(self, monkeypatch):
        monkeypatch.delenv(ENV_MODE, raising=False)
        monkeypatch.setattr(gyr, "get_advanced_settings",
                            lambda: {"triage_gate_enabled": "shadow"})
        assert triageGateMode() == "shadow"

    def test_settingsIllegalValueFallsBackToOff(self, monkeypatch):
        monkeypatch.delenv(ENV_MODE, raising=False)
        monkeypatch.setattr(gyr, "get_advanced_settings",
                            lambda: {"triage_gate_enabled": "maybe"})
        assert triageGateMode() == "off"

    def test_defaultOffWhenNothingConfigured(self, monkeypatch):
        monkeypatch.delenv(ENV_MODE, raising=False)
        monkeypatch.setattr(gyr, "get_advanced_settings", lambda: {})
        assert triageGateMode() == "off"

    def test_appSettingsDefaultIsOff(self):
        from neurova.core.app_settings import ADVANCED_DEFAULTS

        assert ADVANCED_DEFAULTS.get("triage_gate_enabled") == "off", (
            "DEFAULTS 必须登记 triage_gate_enabled=off（默认零行为漂移）"
        )


# ---------------------------------------------------------------------------
# Layer 6：三档行为
# ---------------------------------------------------------------------------

class TestLayer6Wiring:
    def test_offModeKeepsLegacyBehavior(self, monkeypatch, syncManager):
        """off 档：25 条纯 assistant 窗口恒放行，且零分诊副作用（与旧行为一致）。"""
        monkeypatch.setenv(ENV_MODE, "off")
        checker = GlanceYieldChecker()
        _seedSoloLoop(syncManager, CONV, 25)

        decision = checker.check_yield_rules("a1", "m1", ["op"], conversation_id=CONV)

        assert decision.should_yield is False
        stats = checker.get_stats()
        assert stats["triage_checks"] == 0
        assert stats["triage_rule_skips"] == 0
        assert stats["triage_shadow_would_skip"] == 0

    def test_shadowCountsButAllows(self, monkeypatch, syncManager):
        monkeypatch.setenv(ENV_MODE, "shadow")
        checker = GlanceYieldChecker()
        _seedSoloLoop(syncManager, CONV, 25)

        decision = checker.check_yield_rules("a1", "m1", ["op"], conversation_id=CONV)

        assert decision.should_yield is False, "shadow 档只观察不拦截"
        stats = checker.get_stats()
        assert stats["triage_checks"] == 1
        assert stats["triage_shadow_would_skip"] == 1
        assert stats["triage_rule_skips"] == 0

    def test_enforceBlocksRuleHitWithDetails(self, monkeypatch, syncManager):
        monkeypatch.setenv(ENV_MODE, "enforce")
        checker = GlanceYieldChecker()
        _seedSoloLoop(syncManager, CONV, 25)

        decision = checker.check_yield_rules(
            "a1", "m1", ["op"], conversation_id=CONV, userInput="继续推进")

        assert decision.should_yield is True
        assert decision.reason == YieldReason.TRIAGE_GATE
        assert decision.details["source"] == "rules"
        assert decision.details["rule"] == "agent_loop_no_human"
        assert decision.details["features"]["agentStreakLength"] == 25.0
        stats = checker.get_stats()
        assert stats["triage_rule_skips"] == 1

    def test_humanLastAllowsEvenInEnforce(self, monkeypatch, syncManager):
        """人类消息是窗口最后一条 → R0 高置信放行，enforce 也不拦。"""
        monkeypatch.setenv(ENV_MODE, "enforce")
        checker = GlanceYieldChecker()
        _seedSoloLoop(syncManager, CONV, 25)
        _seedHumanLast(syncManager, CONV)

        decision = checker.check_yield_rules("a1", "m1", ["op"], conversation_id=CONV)

        assert decision.should_yield is False

    def test_missingSessionCountsUnavailableAndAllows(self, monkeypatch, syncManager):
        """无会话 → 放行 + triage_events_unavailable（不吞成拦截）。"""
        monkeypatch.setenv(ENV_MODE, "enforce")
        checker = GlanceYieldChecker()

        decision = checker.check_yield_rules(
            "a1", "m1", ["op"], conversation_id="no-such-conv")

        assert decision.should_yield is False
        assert checker.get_stats()["triage_events_unavailable"] == 1

    def test_eventSourceCrashDegradesToAllow(self, monkeypatch, syncManager):
        """事件源抛异常 → 放行 + 计数 + 不外抛（调用方降级契约）。"""
        monkeypatch.setenv(ENV_MODE, "enforce")
        checker = GlanceYieldChecker()

        def boom(*args, **kwargs):
            raise RuntimeError("sync source down")

        monkeypatch.setattr(ssm, "_manager_instance", SimpleNamespace(
            get_session=boom, get_messages=boom))
        decision = checker.check_yield_rules("a1", "m1", ["op"], conversation_id=CONV)

        assert decision.should_yield is False
        assert checker.get_stats()["triage_events_unavailable"] == 1


# ---------------------------------------------------------------------------
# 灰区：NeuJudge 级联
# ---------------------------------------------------------------------------

class TestGrayZoneModelCascade:
    def test_grayZoneFollowsLiveModelDecision(self, monkeypatch, syncManager):
        """12 条独走（规则灰区）→ 闸行为必须与 NeuJudge 对该特征向量的
        真实档位一致（用仓内默认权重产物现算，不臆造档位）。"""
        monkeypatch.setenv(ENV_MODE, "enforce")
        checker = GlanceYieldChecker()
        _seedSoloLoop(syncManager, CONV, 12)

        events = syncManager.get_messages(CONV, 50)
        features = extractTriageFeatures(events, "")
        model = NeuJudge.loadDefault()
        p = model.score(features)
        verdict = model.decide(p)

        decision = checker.check_yield_rules("a1", "m1", ["op"], conversation_id=CONV)

        if verdict == "skip":
            assert decision.should_yield is True
            assert decision.details["source"] == "model"
            assert decision.details["p"] == pytest.approx(p)
        else:
            assert decision.should_yield is False, (
                f"模型档位 {verdict}(p={p:.4f}) 却被闸拦截——级联未按模型档位走"
            )

    def test_nineteenSoloModelSkipBlocksInEnforce(self, monkeypatch, syncManager):
        """19 条独走 < 规则阈值 20（灰区），种子模型 p<0.25 → enforce 档拦截。"""
        monkeypatch.setenv(ENV_MODE, "enforce")
        checker = GlanceYieldChecker()
        _seedSoloLoop(syncManager, CONV, 19)

        events = syncManager.get_messages(CONV, 50)
        p = NeuJudge.loadDefault().score(extractTriageFeatures(events, ""))
        assert p < SKIP_P, (
            f"种子模型对 19 独走的 p={p:.4f} 未落入 skip 档——权重产物变更后请同步本用例"
        )

        decision = checker.check_yield_rules("a1", "m1", ["op"], conversation_id=CONV)

        assert decision.should_yield is True
        assert decision.reason == YieldReason.TRIAGE_GATE
        assert decision.details["source"] == "model"
        stats = checker.get_stats()
        assert stats["triage_model_skips"] == 1
        assert stats["triage_rule_skips"] == 0

    def test_modelUnavailableDegradesToRulesOnlyOnce(self, monkeypatch, syncManager):
        """权重产物损坏 → 放行 + triage_model_unavailable，失败标记后不再重试加载。"""
        monkeypatch.setenv(ENV_MODE, "enforce")
        checker = GlanceYieldChecker()
        _seedSoloLoop(syncManager, CONV, 12)

        loadCalls = {"n": 0}

        def brokenLoad():
            loadCalls["n"] += 1
            raise NeuJudgeUnavailable("权重产物损坏（测试注入）")

        monkeypatch.setattr(NeuJudge, "loadDefault", staticmethod(brokenLoad))

        first = checker.check_yield_rules("a1", "m1", ["op"], conversation_id=CONV)
        second = checker.check_yield_rules("a1", "m1", ["op"], conversation_id=CONV)

        assert first.should_yield is False and second.should_yield is False
        stats = checker.get_stats()
        assert stats["triage_model_unavailable"] >= 1
        assert loadCalls["n"] == 1, "失败标记应生效：只允许加载失败一次，此后恒走仅规则"


# ---------------------------------------------------------------------------
# skip 语义：turn_coordinator + agent_run_ledger
# ---------------------------------------------------------------------------

class TestSkipYieldReason:
    @pytest.mark.asyncio
    async def test_triageGateSkipsImmediatelyWithoutWaiting(self, monkeypatch, syncManager):
        """triage_gate 是 skip 不是 park：立即返回 triage_gate_skip，不等不重试。"""
        from neurova.agent.turn_coordinator import requestYieldGate

        monkeypatch.setenv(ENV_MODE, "enforce")
        checker = _isolateChecker(monkeypatch)
        _seedSoloLoop(syncManager, CONV, 25)
        sleeps = []

        async def fakeSleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fakeSleep)

        outcome = await requestYieldGate(
            agentId="agent-skip", modelName="gpt-test", sessionId=CONV, userInput="继续")

        assert outcome.proceeded is False
        assert outcome.parkReason == "triage_gate_skip"
        assert outcome.attempts == 1, "空转拦截不随等待自愈：一次判定即返回"
        assert outcome.waitedSeconds == 0.0
        assert sleeps == [], f"skip 语义不许等待（实际睡了 {sleeps}）"
        assert outcome.details.get("source") == "rules"

    def test_reasonSetsPinned(self):
        from neurova.agent.turn_coordinator import (
            NON_RETRYABLE_YIELD_REASONS,
            SKIP_YIELD_REASONS,
        )

        assert SKIP_YIELD_REASONS == frozenset({"triage_gate"})
        assert NON_RETRYABLE_YIELD_REASONS == frozenset({"model_pin_violation"}), (
            "NON_RETRYABLE_YIELD_REASONS 保持不变（挂起等人工语义不动）"
        )


def _waitForTerminal(store, sessionId: str, timeout: float = 5.0) -> Dict[str, Any]:
    """_finishAs 走独立线程写库——轮询到行进终态为止。"""
    deadline = time.time() + timeout
    rows = []
    while time.time() < deadline:
        rows = store.list_runs(sessionId)
        if rows and rows[0]["status"] in ("completed", "failed", "cancelled"):
            return rows[0]
        time.sleep(0.05)
    return rows[0] if rows else {}


class TestTurnAdmissionSkip:
    @pytest.mark.asyncio
    async def test_skipTurnFinishesRunAsFailedWithoutPark(self, monkeypatch, syncManager, runStore):
        """skip 回合：running 行收成 failed/triage_gate_skip，不调 parkTurn、无 parked 行。"""
        from neurova.core.agent_run_ledger import AgentRunLedger, requestTurnAdmission

        monkeypatch.setenv(ENV_MODE, "enforce")
        _isolateChecker(monkeypatch)
        _seedSoloLoop(syncManager, CONV, 25)

        ledger = AgentRunLedger(CONV, OWNER, AGENT_ID, "继续推进")
        await ledger.acquire()
        assert ledger.run_id, "run 行应在进闸前创建"

        admission = await requestTurnAdmission(
            ledger=ledger, agentId=AGENT_ID, modelName="gpt-test",
            sessionId=CONV, userInput="继续推进", payload={"entry": "channel"},
        )

        assert admission.allowed is False
        assert admission.skipped is True
        assert admission.parked is False, "skip 不是 park：不得进入等人工续跑队列"
        assert admission.parkReason == "triage_gate_skip"
        assert admission.runId == ledger.run_id
        assert admission.ledgerFailed is False

        row = _waitForTerminal(runStore, CONV)
        assert row.get("status") == "failed", f"skip 后 run 行未收终态：{row}"
        assert row.get("error_type") == "triage_gate_skip"
        rows = runStore.list_runs(CONV)
        assert all(r["status"] != "parked" for r in rows), "skip 不得产生 parked 幽灵行"

    @pytest.mark.asyncio
    async def test_skipTurnMethodDirectlyFinishesRunningRow(self, monkeypatch, runStore):
        from neurova.core.agent_run_ledger import AgentRunLedger

        ledger = AgentRunLedger("skip-direct", OWNER, AGENT_ID, "任意输入")
        await ledger.acquire()
        assert ledger.run_id

        assert ledger.skipTurn("triage_gate_skip") is True

        row = _waitForTerminal(runStore, "skip-direct")
        assert row.get("status") == "failed"
        assert row.get("error_type") == "triage_gate_skip"

    def test_turnAdmissionParkedPropertyExcludesSkipped(self):
        from neurova.core.agent_run_ledger import TurnAdmission

        assert TurnAdmission(allowed=False, parkReason="x").parked is True
        assert TurnAdmission(allowed=False, parkReason="x", ledgerFailed=True).parked is False
        assert TurnAdmission(
            allowed=False, parkReason="triage_gate_skip", skipped=True).parked is False


# ---------------------------------------------------------------------------
# 调用点 skip 分支
# ---------------------------------------------------------------------------

class TestCallSiteSkipBranches:
    def test_v1ChatNonStreamReturnsSkippedEnvelope(
            self, monkeypatch, syncManager, runStore, chatClient):
        """/v1/chat 非流式：skip 回空回复 + triage_skipped/skip_reason/run_id，不打 LLM。"""
        monkeypatch.setenv(ENV_MODE, "enforce")
        _isolateChecker(monkeypatch)
        _seedSoloLoop(syncManager, "v1-skip", 25)
        client, agent = chatClient

        resp = client.post(
            "/api/v1/chat",
            json={"message": "继续", "agent_id": AGENT_ID, "session_id": "v1-skip"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0, f"skip 不是错误形态：{body}"
        data = body["data"]
        assert data["text"] == ""
        assert data["triage_skipped"] is True
        assert data["skip_reason"] == "triage_gate_skip"
        assert data["run_id"], "skip 回执必须带 run_id（台账凭据）"
        assert agent.calls == [], "被跳过的回合不得打到 LLM"

    def test_v1ChatStreamEmitsSkippedEventThenDone(
            self, monkeypatch, syncManager, runStore, chatClient):
        """/v1/chat/stream：skip 以 skipped 事件收尾 + done，无 message 内容。"""
        monkeypatch.setenv(ENV_MODE, "enforce")
        _isolateChecker(monkeypatch)
        _seedSoloLoop(syncManager, "v1-skip-stream", 25)
        client, agent = chatClient

        resp = client.post(
            "/api/v1/chat/stream",
            json={"message": "继续", "agent_id": AGENT_ID, "session_id": "v1-skip-stream"},
        )

        assert resp.status_code == 200
        events = _dataEvents(resp.text)
        kinds = [e.get("type") for e in events if e.get("type")]
        assert "skipped" in kinds, f"流式面没有 skipped 事件：{kinds}"
        assert kinds[-1] == "done", "skip 后流必须收尾"
        assert "message" not in kinds, "skip 后不该有任何模型内容"
        assert agent.calls == []

    @pytest.mark.asyncio
    async def test_channelRouterSkipReturnsNoReply(self, monkeypatch, syncManager, runStore):
        """渠道面 skip：返回空列表（渠道不回复），agent.chat 不被调用。"""
        from neurova.channels import channel_router
        from neurova.channels.base import ChannelMessage
        from neurova.channels.manager import ChannelManager

        monkeypatch.setenv(ENV_MODE, "enforce")
        _isolateChecker(monkeypatch)
        ChannelManager._instance = None
        manager = ChannelManager()
        try:
            agent = _FakeAgent()
            handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
            message = ChannelMessage(
                channel_type="feishu", message_id="m1", sender_id="ou_9",
                sender_name="ou_9", content="继续", chat_id="oc_1", chat_type="p2p",
                metadata={"agent_id": AGENT_ID},
            )
            scope = manager.resolve_session_scope_id(message)
            _seedSoloLoop(syncManager, scope, 25)

            reply = await handler(message)

            assert reply == [], f"skip 的渠道回合不得回回复：{reply!r}"
            assert agent.calls == [], "被跳过的渠道回合不得打到 LLM"
        finally:
            ChannelManager._instance = None


# ---------------------------------------------------------------------------
# 旧缓存面退役
# ---------------------------------------------------------------------------

class TestTriageCacheRetired:
    def test_cacheSurfaceGoneFromChecker(self):
        assert not hasattr(GlanceYieldChecker, "cache_triage_result"), (
            "cache_triage_result 已退役（单一事实源=窗口现算）"
        )

    def test_cacheSymbolsGoneFromWholeTree(self):
        """旧缓存符号在 neurova/ 生产树与 tests/ 里零残留（打包副本不算）。

        本测试文件自身含这些符号的字面量（判据本体），扫描时排除；
        词边界匹配——`clear_triage_cache` 这类仅含子串的无关命名不算命中。
        """
        import re

        leftovers = []
        for symbol in ("_triage_cache", "cache_triage_result", "triage_cache_size"):
            pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
            for root in ("neurova", "tests"):
                for path in (PROJECT_ROOT / root).rglob("*.py"):
                    if "__pycache__" in path.parts or path == Path(__file__).resolve():
                        continue
                    if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                        leftovers.append(f"{symbol} @ {path}")
        assert not leftovers, "旧缓存面残留：\n  " + "\n  ".join(leftovers)
