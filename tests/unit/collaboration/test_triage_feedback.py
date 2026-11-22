# -*- coding: utf-8 -*-
"""SB-5 分诊 skip 样本回流：存储面 + Layer 6 接线 + admin 复核端点。

出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md
§5.3 训练数据三级来源第 2 级（人工标注回流）/ §5.5 / §8-SB-5。

覆盖面：
- 存储面（triage_feedback）：record 契约字段 / list 最新在前 + limit /
  relabel 原子重写 / 坏行跳过不炸 / IO 失败 fail-soft（返回 False 不外抛）；
- 接线面（glance_yield_rules）：enforce 规则拦截与模型拦截后样本落盘、
  shadow 档同样落盘（mode=shadow）、放行路径不落样本、存储失败计
  triage_feedback_errors 且不影响闸决策；
- 端点面（coordination_api）：GET /triage/skip-samples 与 POST
  /triage/skip-samples/{id}/relabel 的 admin 门、响应包络与 422/404。

事件种子一律用真实 SessionSyncManager 公开 API 灌入（沿
test_triage_gate_wiring.py 惯例），不用 MagicMock 顶替业务对象。
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.collaboration import glance_yield_rules as gyr  # noqa: E402
from neurova.collaboration import triage_feedback  # noqa: E402
from neurova.collaboration.glance_yield_rules import GlanceYieldChecker  # noqa: E402
from neurova.collaboration.neu_judge import SKIP_P, NeuJudge  # noqa: E402
from neurova.collaboration.triage_feedback import (  # noqa: E402
    listSkipSamples,
    recordSkipSample,
    relabelSample,
)
from neurova.collaboration.triage_rules import extractTriageFeatures  # noqa: E402
from neurova.sync import session_sync_manager as ssm  # noqa: E402
from neurova.sync.session_sync_manager import (  # noqa: E402
    EventType,
    SessionEvent,
    SessionSyncManager,
)

ENV_MODE = "NEUROVA_TRIAGE_GATE_MODE"
CONV = "feedback-conv"


# ---------------------------------------------------------------------------
# 隔离与种子
# ---------------------------------------------------------------------------

@pytest.fixture()
def dataRoot(tmp_path, monkeypatch) -> Path:
    """独立数据根：回流样本的落盘判定全部限定在临时目录内。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def syncManager(monkeypatch):
    """独立 SessionSyncManager 顶到单例位——分诊门的进料口读它。"""
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
    session = manager.register_or_create_session(
        sessionId, user_id="seed-user", agent_id="seed-agent")
    base = datetime.now(timezone.utc) - timedelta(minutes=30)
    for i in range(count):
        session.add_event(SessionEvent(
            event_type=EventType.AGENT_REPLY,
            payload={"content": f"{prefix} {i} with distinct content"},
            timestamp=base + timedelta(seconds=i * stepSeconds),
        ))


def _readAllLines(dataRoot: Path) -> list:
    path = dataRoot / "triage_skips.jsonl"
    return path.read_text(encoding="utf-8").splitlines()


# ---------------------------------------------------------------------------
# 存储面：record
# ---------------------------------------------------------------------------

class TestRecordSkipSample:
    def test_writesJsonlWithContractFields(self, dataRoot):
        ok = recordSkipSample(
            conversationId=CONV, source="rules", rule="agent_loop_no_human",
            p=None, features={"agentStreakLength": 25.0}, mode="enforce",
        )
        assert ok is True
        lines = _readAllLines(dataRoot)
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["conversation_id"] == CONV
        assert record["mode"] == "enforce"
        assert record["source"] == "rules"
        assert record["rule"] == "agent_loop_no_human"
        assert record["p"] is None
        assert record["features"] == {"agentStreakLength": 25.0}
        assert record["label"] == "not_actionable", "回流样本初始标签＝分诊门先验"
        assert record["relabeled"] is False
        assert record["relabel_note"] == ""
        assert isinstance(record["sample_id"], str) and len(record["sample_id"]) == 32
        datetime.fromisoformat(record["recorded_at"])  # recorded_at 必须是可解析 ISO

    def test_modelSourceRecordKeepsProbability(self, dataRoot):
        ok = recordSkipSample(
            conversationId=CONV, source="model", rule="default_allow",
            p=0.12, features={"agentStreakLength": 12.0}, mode="shadow",
        )
        assert ok is True
        record = listSkipSamples(limit=1)[0]
        assert record["source"] == "model"
        assert record["p"] == pytest.approx(0.12)
        assert record["mode"] == "shadow"

    def test_ioFailureFailSoftReturnsFalse(self, dataRoot, monkeypatch):
        """落盘失败（父路径是文件）→ warning + False，绝不外抛。"""
        blocker = dataRoot / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(
            triage_feedback, "_samplesPath",
            lambda: blocker / "nested" / "triage_skips.jsonl",
        )
        ok = recordSkipSample(
            conversationId=CONV, source="rules", rule="verbatim_loop", mode="enforce")
        assert ok is False


# ---------------------------------------------------------------------------
# 存储面：list
# ---------------------------------------------------------------------------

class TestListSkipSamples:
    def test_newestFirstAndLimit(self, dataRoot):
        for i in range(5):
            recordSkipSample(conversationId=f"c{i}", source="rules",
                             rule="agent_loop_no_human", mode="enforce")
        samples = listSkipSamples(limit=3)
        assert [s["conversation_id"] for s in samples] == ["c4", "c3", "c2"]
        full = listSkipSamples()
        assert len(full) == 5
        assert full[0]["conversation_id"] == "c4"

    def test_emptyWhenNoFile(self, dataRoot):
        assert listSkipSamples() == []

    def test_corruptLinesSkippedNotRaised(self, dataRoot):
        """坏行（非 JSON）跳过不炸：前后好行照常读出。"""
        recordSkipSample(conversationId="good-1", source="rules",
                         rule="verbatim_loop", mode="enforce")
        path = dataRoot / "triage_skips.jsonl"
        path.write_text(
            path.read_text(encoding="utf-8")
            + "this is not json at all\n"
            + "{broken json\n",
            encoding="utf-8",
        )
        recordSkipSample(conversationId="good-2", source="rules",
                         rule="verbatim_loop", mode="enforce")
        samples = listSkipSamples(limit=100)
        assert [s["conversation_id"] for s in samples] == ["good-2", "good-1"]


# ---------------------------------------------------------------------------
# 存储面：relabel（原子重写）
# ---------------------------------------------------------------------------

class TestRelabelSample:
    def test_relabelUpdatesTargetAndKeepsOthers(self, dataRoot):
        recordSkipSample(conversationId="r1", source="rules",
                         rule="agent_loop_no_human", mode="enforce")
        recordSkipSample(conversationId="r2", source="rules",
                         rule="verbatim_loop", mode="shadow")
        target = next(s for s in listSkipSamples(limit=10)
                      if s["conversation_id"] == "r1")

        assert relabelSample(target["sample_id"], "actionable",
                             note="人工复核：确实空转") is True

        after = {s["conversation_id"]: s for s in listSkipSamples(limit=10)}
        assert after["r1"]["label"] == "actionable"
        assert after["r1"]["relabeled"] is True
        assert after["r1"]["relabel_note"] == "人工复核：确实空转"
        assert after["r2"]["label"] == "not_actionable", "未命中的样本逐字节不动"
        assert after["r2"]["relabeled"] is False

    def test_relabelInvalidLabelRaisesValueError(self, dataRoot):
        recordSkipSample(conversationId="r1", source="rules",
                         rule="verbatim_loop", mode="enforce")
        target = listSkipSamples(limit=1)[0]
        with pytest.raises(ValueError):
            relabelSample(target["sample_id"], "maybe")

    def test_relabelUnknownSampleReturnsFalse(self, dataRoot):
        assert relabelSample("deadbeef" * 4, "actionable") is False

    def test_relabelRewriteLeavesNoTempFile(self, dataRoot):
        """原子重写（临时文件 + os.replace）不得残留临时文件。"""
        recordSkipSample(conversationId="r1", source="rules",
                         rule="verbatim_loop", mode="enforce")
        target = listSkipSamples(limit=1)[0]
        assert relabelSample(target["sample_id"], "not_actionable",
                             note="维持原判") is True
        leftovers = [p.name for p in dataRoot.iterdir()
                     if p.name != "triage_skips.jsonl"]
        assert leftovers == [], f"原子重写残留临时文件：{leftovers}"
        records = listSkipSamples(limit=10)
        assert len(records) == 1
        assert records[0]["relabel_note"] == "维持原判"

    def test_concurrentRecordsAllPersist(self, dataRoot):
        """线程安全：并发追加不丢行。"""
        def worker(i: int) -> None:
            recordSkipSample(conversationId=f"t{i}", source="rules",
                             rule="verbatim_loop", mode="enforce")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(listSkipSamples(limit=100)) == 8


# ---------------------------------------------------------------------------
# 接线面：Layer 6 拦截 → 样本落盘
# ---------------------------------------------------------------------------

class TestGateFeedbackWiring:
    def test_enforceRuleBlockWritesSample(self, dataRoot, syncManager, monkeypatch):
        monkeypatch.setenv(ENV_MODE, "enforce")
        checker = GlanceYieldChecker()
        _seedSoloLoop(syncManager, CONV, 25)

        decision = checker.check_yield_rules(
            "a1", "m1", ["op"], conversation_id=CONV, userInput="继续")

        assert decision.should_yield is True
        samples = listSkipSamples(limit=10)
        assert len(samples) == 1
        record = samples[0]
        assert record["conversation_id"] == CONV
        assert record["mode"] == "enforce"
        assert record["source"] == "rules"
        assert record["rule"] == "agent_loop_no_human"
        assert record["features"]["agentStreakLength"] == 25.0
        assert checker.get_stats()["triage_feedback_errors"] == 0

    def test_shadowBlockAlsoWritesSampleWithShadowMode(self, dataRoot, syncManager, monkeypatch):
        """shadow 也入样本（mode=shadow 区分），但闸仍恒放行。"""
        monkeypatch.setenv(ENV_MODE, "shadow")
        checker = GlanceYieldChecker()
        _seedSoloLoop(syncManager, CONV, 25)

        decision = checker.check_yield_rules("a1", "m1", ["op"], conversation_id=CONV)

        assert decision.should_yield is False
        samples = listSkipSamples(limit=10)
        assert len(samples) == 1
        assert samples[0]["mode"] == "shadow"
        assert samples[0]["source"] == "rules"

    def test_modelSkipWritesSampleWithProbability(self, dataRoot, syncManager, monkeypatch):
        """模型拦截（19 独走灰区，种子模型 p<SKIP_P）→ source=model 样本带 p。"""
        monkeypatch.setenv(ENV_MODE, "enforce")
        checker = GlanceYieldChecker()
        _seedSoloLoop(syncManager, CONV, 19)

        events = syncManager.get_messages(CONV, 50)
        p = NeuJudge.loadDefault().score(extractTriageFeatures(events, ""))
        assert p < SKIP_P, "种子模型对 19 独走应为 skip 档（权重产物变更请同步本用例）"

        decision = checker.check_yield_rules("a1", "m1", ["op"], conversation_id=CONV)

        assert decision.should_yield is True
        samples = listSkipSamples(limit=10)
        assert len(samples) == 1
        assert samples[0]["source"] == "model"
        assert samples[0]["p"] == pytest.approx(p)

    def test_allowPathWritesNoSample(self, dataRoot, syncManager, monkeypatch):
        """放行路径不落样本：回流只收 skip 样本。"""
        monkeypatch.setenv(ENV_MODE, "enforce")
        checker = GlanceYieldChecker()
        _seedSoloLoop(syncManager, CONV, 25)
        session = syncManager.get_session(CONV)
        session.add_event(SessionEvent(
            event_type=EventType.USER_MESSAGE,
            payload={"content": "我在，请继续"},
            timestamp=datetime.now(timezone.utc),
        ))

        decision = checker.check_yield_rules("a1", "m1", ["op"], conversation_id=CONV)

        assert decision.should_yield is False
        assert listSkipSamples(limit=10) == []

    def test_feedbackFailureCountedAndDoesNotAffectGate(self, dataRoot, syncManager, monkeypatch):
        """存储失败 → triage_feedback_errors +1，闸决策不受影响。"""
        monkeypatch.setenv(ENV_MODE, "enforce")
        checker = GlanceYieldChecker()
        _seedSoloLoop(syncManager, CONV, 25)
        monkeypatch.setattr(triage_feedback, "recordSkipSample", lambda **kwargs: False)

        decision = checker.check_yield_rules(
            "a1", "m1", ["op"], conversation_id=CONV, userInput="继续")

        assert decision.should_yield is True, "回流失败不得影响闸决策"
        assert checker.get_stats()["triage_feedback_errors"] == 1


# ---------------------------------------------------------------------------
# 端点面：admin 复核端点
# ---------------------------------------------------------------------------

def _makeClient(role: str = "admin"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import neurova.api.auth as api_auth
    from neurova.api.endpoints import coordination_api

    app = FastAPI()
    app.include_router(coordination_api.router, prefix="/api")
    app.dependency_overrides[api_auth.get_current_user] = lambda: {
        "user_id": "u-1", "username": "u-1", "role": role,
    }
    return TestClient(app)


class TestAdminSkipSampleEndpoints:
    @pytest.fixture()
    def client(self, dataRoot):
        return _makeClient("admin")

    def test_listSkipSamplesEnvelope(self, client):
        recordSkipSample(conversationId="e1", source="rules",
                         rule="verbatim_loop", mode="enforce")
        resp = client.get("/api/coordination/triage/skip-samples", params={"limit": 10})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["count"] == 1
        assert body["data"]["samples"][0]["conversation_id"] == "e1"

    def test_relabelRoundTrip(self, client):
        recordSkipSample(conversationId="e2", source="model",
                         rule="default_allow", p=0.1, mode="enforce")
        target = listSkipSamples(limit=1)[0]

        resp = client.post(
            f"/api/coordination/triage/skip-samples/{target['sample_id']}/relabel",
            json={"label": "actionable", "note": "复核为可行动"},
        )

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        after = listSkipSamples(limit=1)[0]
        assert after["label"] == "actionable"
        assert after["relabeled"] is True
        assert after["relabel_note"] == "复核为可行动"

    def test_relabelInvalidLabel422(self, client):
        recordSkipSample(conversationId="e3", source="rules",
                         rule="verbatim_loop", mode="enforce")
        target = listSkipSamples(limit=1)[0]

        resp = client.post(
            f"/api/coordination/triage/skip-samples/{target['sample_id']}/relabel",
            json={"label": "nonsense"},
        )

        assert resp.status_code == 422

    def test_relabelUnknownSample404(self, client):
        resp = client.post(
            "/api/coordination/triage/skip-samples/deadbeef/relabel",
            json={"label": "actionable"},
        )
        assert resp.status_code == 404

    def test_nonAdminForbidden403(self, dataRoot):
        """复核面是治理动作：非 admin 角色 403。"""
        client = _makeClient("user")
        resp = client.get("/api/coordination/triage/skip-samples")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# SB-7 误杀率统计（计划 §7 晋升判据：skip 后 5 分钟内人类发言 = 误杀）
# ---------------------------------------------------------------------------

class TestFalseRescueStats:
    def testFalseRescueEmptyState(self, dataRoot):
        from neurova.collaboration.triage_feedback import falseRescueStats

        stats = falseRescueStats()
        assert stats["samples"] == 0
        assert stats["falseKills"] == 0
        assert stats["falseRescueRate"] == 0.0

    def testFalseRescueDetectsHumanWithinWindow(self, dataRoot, syncManager):
        from neurova.collaboration.triage_feedback import falseRescueStats

        assert recordSkipSample(
            conversationId="fr-hit", source="rules", rule="agent_loop_no_human",
            p=None, features={}, mode="shadow",
        ) is True
        # 样本落盘后 60 秒处人类发言（5 分钟窗口内）= 误杀
        session = syncManager.register_or_create_session(
            "fr-hit", user_id="seed-user", agent_id="seed-agent")
        session.add_event(SessionEvent(
            event_type=EventType.USER_MESSAGE,
            payload={"content": "我在，为什么不回？"},
            timestamp=datetime.now(timezone.utc) + timedelta(seconds=60),
        ))

        stats = falseRescueStats()
        assert stats["samples"] == 1
        assert stats["falseKills"] == 1
        assert stats["falseRescueRate"] == 1.0

    def testFalseRescueIgnoresHumanBeforeSample(self, dataRoot, syncManager):
        from neurova.collaboration.triage_feedback import falseRescueStats

        # 人类发言在样本之前（过去 60 秒）——不是误杀
        session = syncManager.register_or_create_session(
            "fr-before", user_id="seed-user", agent_id="seed-agent")
        session.add_event(SessionEvent(
            event_type=EventType.USER_MESSAGE,
            payload={"content": "先说话后跳过"},
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=60),
        ))
        assert recordSkipSample(
            conversationId="fr-before", source="rules", rule="agent_loop_no_human",
            p=None, features={}, mode="shadow",
        ) is True

        stats = falseRescueStats()
        assert stats["samples"] == 1
        assert stats["falseKills"] == 0

    def testFalseRescueOutsideWindowNotCounted(self, dataRoot, syncManager):
        from neurova.collaboration.triage_feedback import falseRescueStats

        assert recordSkipSample(
            conversationId="fr-late", source="rules", rule="agent_loop_no_human",
            p=None, features={}, mode="shadow",
        ) is True
        session = syncManager.register_or_create_session(
            "fr-late", user_id="seed-user", agent_id="seed-agent")
        session.add_event(SessionEvent(
            event_type=EventType.USER_MESSAGE,
            payload={"content": "六分钟后才回来"},
            timestamp=datetime.now(timezone.utc) + timedelta(seconds=400),
        ))

        stats = falseRescueStats()
        assert stats["falseKills"] == 0
        assert stats["falseRescueRate"] == 0.0

    def testFalseRescueIgnoresAssistantMessages(self, dataRoot, syncManager):
        from neurova.collaboration.triage_feedback import falseRescueStats

        assert recordSkipSample(
            conversationId="fr-assistant", source="rules", rule="agent_loop_no_human",
            p=None, features={}, mode="shadow",
        ) is True
        session = syncManager.register_or_create_session(
            "fr-assistant", user_id="seed-user", agent_id="seed-agent")
        session.add_event(SessionEvent(
            event_type=EventType.AGENT_REPLY,
            payload={"content": "assistant 后续消息不算人类救援"},
            timestamp=datetime.now(timezone.utc) + timedelta(seconds=30),
        ))

        stats = falseRescueStats()
        assert stats["falseKills"] == 0

    def testStatsEndpointExposesFalseRescue(self, dataRoot, syncManager):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.auth import create_access_token
        from neurova.api.endpoints.coordination_api import router

        assert recordSkipSample(
            conversationId="fr-endpoint", source="rules", rule="agent_loop_no_human",
            p=None, features={}, mode="shadow",
        ) is True

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        token = create_access_token({"sub": "livetest", "role": "admin", "type": "access"})
        resp = client.get(
            "/coordination/triage/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["false_rescue"]["samples"] == 1
        assert "falseRescueRate" in body["false_rescue"]
