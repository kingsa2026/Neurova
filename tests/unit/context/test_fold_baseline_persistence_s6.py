# -*- coding: utf-8 -*-
"""S6' 增长门折叠基线跨重启持久化。

契约（docs/08-research/reference_f_vs_neurova_context_compression_comparison_2026-11-17.md；S6 压缩纪律延伸）：
1. 折叠基线（last_fold_tokens/msgs、covered 集、last_count、fold_seq、摘要）随
   会话时间线持久化（fold_baseline 事件，与 CompressionEvent 同一落盘面）；
2. 进程重启（新编排器实例、同会话盘）后重放恢复——复用冷却重建
   （rebuildCompactionCooldown）的时间线重放模式；
3. 重启后增长门**不因基线丢失而立即重复折叠**（增量判据以恢复的基线为准）；
4. 无基线时间线（老会话/新会话）行为与改前一致（基线为 0，门照常判定）；
5. 重启后再次折叠仍过严格变小守卫（assertCompactionShrinks）；
6. 重放是**纯函数**（fold_trigger.rebuildFoldBaseline），时间线为事实源。
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.window_compactor import estimate_window_tokens

AGENT_ID = "a-s6-iso"
SESSION_KEY = "s6-session"


def _mk_agent(sessionManager, model: str = "test-model"):
    mock_agent = MagicMock()
    mock_agent.config = MagicMock()
    mock_agent.config.name = "test_agent"
    mock_agent.config.constitution = ""
    mock_agent.config.behavior_rules = []
    mock_agent.config.llm_model = model
    mock_agent.config.agent_id = AGENT_ID
    mock_agent.memory_manager = MagicMock()
    mock_agent.context_builder = MagicMock()
    mock_agent.tool_router = None
    mock_agent._skill_registry = None
    mock_agent.soul = "你是测试助手"
    mock_agent.personality = ""
    mock_agent.conversation_history = []
    mock_agent.growth_log_manager = MagicMock()
    mock_agent.user_id = "u-s6-iso"
    mock_agent.agent_id = AGENT_ID
    mock_agent.session_manager = sessionManager
    return mock_agent


def _long_msg(i: int, chars: int = 900) -> dict:
    return {"role": "user", "content": f"长消息{i}: " + "测" * chars}


def _summary_rows(view):
    return [m for m in view if m.get("role") == "system" and "早期对话摘要" in str(m.get("content", ""))]


def _hasMsg(view, tag: str) -> bool:
    return any(tag in str(m.get("content", "")) for m in view)


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEUROVA_CACHE_ADAPTIVE_FOLD", "0")
    from neurova.cognitive_layers.meta_cognition_layer.ledger import reset_meta_ledger
    from neurova.cognitive_layers.meta_cognition_layer.self_model import reset_self_model_engine

    reset_meta_ledger()
    reset_self_model_engine()
    yield
    reset_meta_ledger()
    reset_self_model_engine()


@pytest.fixture()
def sessionManager(tmp_path):
    from neurova.session_manager import SessionManager

    return SessionManager(sessions_dir=str(tmp_path / "sessions"))


def _mk_orchestrator(sessionManager) -> ContextOrchestrator:
    orch = ContextOrchestrator(_mk_agent(sessionManager), use_pool=True, auto_tag=False)
    orch._window_hard_limit = 10**9
    return orch


class TestFoldBaselinePersistence:
    """折叠 → 重建（新编排器实例）→ 不因基线丢失立即重复折叠。"""

    @pytest.mark.asyncio
    async def test_baseline_survives_restart(self, sessionManager):
        from neurova.context.fold_trigger import FOLD_BASELINE_TIMELINE_KIND

        orch1 = _mk_orchestrator(sessionManager)

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch1._window_summarizer = fake_summarize
        msgs = [_long_msg(i) for i in range(24)]
        total = estimate_window_tokens(msgs)
        budget = orch1._effectiveWindowBudget(int(total * 1.25))

        # 预置增长基线并触发一次折叠
        cache1 = orch1._window_cache_slot(SESSION_KEY)
        cache1["last_fold_tokens"] = int(total * 0.5)
        cache1["last_fold_msgs"] = 0
        view1 = await orch1._apply_window_budget(msgs, budget, cache_key=SESSION_KEY)
        assert _summary_rows(view1), "场景预朞性质错误：首次折叠应发生"
        slot1 = orch1._window_compaction_cache[SESSION_KEY]
        assert slot1["last_fold_tokens"] == total
        assert slot1["covered"], "折叠后覆盖账应推进"

        # 基线已随会话时间线落盘
        events = sessionManager.read_timeline(AGENT_ID, SESSION_KEY)
        baselineEvents = [e for e in events if e.get("kind") == FOLD_BASELINE_TIMELINE_KIND]
        assert baselineEvents, "折叠基线应落会话时间线"
        payload = baselineEvents[-1]["event"]
        assert payload["lastFoldTokens"] == total
        assert payload["covered"], "覆盖集随基线事件落盘"

        # ── 重启：新编排器实例（内存槽全空），同一会话盘 ──
        orch2 = _mk_orchestrator(sessionManager)
        assert orch2._window_compaction_cache.get(SESSION_KEY) is None
        msgs2 = msgs + [_long_msg(24)]
        view2 = await orch2._apply_window_budget(msgs2, budget, cache_key=SESSION_KEY)

        # 基线恢复：增长门不因基线丢失立即重复折叠
        slot2 = orch2._window_compaction_cache[SESSION_KEY]
        assert slot2["last_fold_tokens"] == total, "折叠基线应从时间线恢复"
        assert slot2["last_fold_msgs"] == len(msgs)
        assert slot2["covered"] == slot1["covered"], "覆盖集应重放恢复"
        readout = orch2._context_health["fold_trigger"]
        assert readout["should_fold"] is False, "增量未过门槛：不得立即重复折叠"
        assert readout["last_reason"] == "insufficient_growth"
        # 恢复的冻结头在位：折叠前缀不以裸原文重现，尾部原样保留
        assert _summary_rows(view2), "恢复的摘要头应在场"
        assert _hasMsg(view2, "长消息23") and _hasMsg(view2, "长消息24")

    @pytest.mark.asyncio
    async def test_refold_after_restart_passes_strict_shrink(self, sessionManager):
        """重启后若增量真的过门：折叠照常，且严格变小守卫照常。"""
        from neurova.context_pool import assertCompactionShrinks

        orch1 = _mk_orchestrator(sessionManager)

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch1._window_summarizer = fake_summarize
        msgs = [_long_msg(i) for i in range(24)]
        total = estimate_window_tokens(msgs)
        budget = orch1._effectiveWindowBudget(int(total * 1.25))
        cache1 = orch1._window_cache_slot(SESSION_KEY)
        cache1["last_fold_tokens"] = int(total * 0.5)
        cache1["last_fold_msgs"] = 0
        view1 = await orch1._apply_window_budget(msgs, budget, cache_key=SESSION_KEY)
        assert _summary_rows(view1)

        # 重启后追加一大截增量（过增长门）→ 应折叠，且严格变小
        orch2 = _mk_orchestrator(sessionManager)
        msgs2 = msgs + [_long_msg(i + 100, chars=4000) for i in range(12)]
        total2 = estimate_window_tokens(msgs2)
        view2 = await orch2._apply_window_budget(msgs2, budget, cache_key=SESSION_KEY)
        assert _summary_rows(view2), "重启后增量过门：折叠照常"
        assert orch2._context_health["fold_trigger"]["should_fold"] is True
        assertCompactionShrinks(total2, estimate_window_tokens(view2)), "严格变小守卫照常"

    @pytest.mark.asyncio
    async def test_no_baseline_timeline_behaves_as_before(self, sessionManager):
        """无基线时间线（新会话）：基线为 0，增长门照常判定（行为与改前一致）。"""
        orch = _mk_orchestrator(sessionManager)

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs = [_long_msg(i) for i in range(24)]
        total = estimate_window_tokens(msgs)
        budget = orch._effectiveWindowBudget(int(total * 1.25))

        view = await orch._apply_window_budget(msgs, budget, cache_key="fresh-session")

        assert _summary_rows(view), "无基线：增长门照常触发（对照臂）"
        slot = orch._window_compaction_cache["fresh-session"]
        assert slot["last_fold_tokens"] == total

    @pytest.mark.asyncio
    async def test_baseline_restore_is_failopen(self, sessionManager, monkeypatch):
        """时间线不可读：重放失败按无基线处理，不阻断折叠主链路。"""
        orch = _mk_orchestrator(sessionManager)

        def boom(*args, **kwargs):
            raise RuntimeError("timeline io error")

        monkeypatch.setattr(sessionManager, "read_timeline", boom)

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs = [_long_msg(i) for i in range(24)]
        total = estimate_window_tokens(msgs)
        budget = orch._effectiveWindowBudget(int(total * 1.25))

        view = await orch._apply_window_budget(msgs, budget, cache_key=SESSION_KEY)
        assert _summary_rows(view), "重放失败不阻断折叠"


class TestRebuildFoldBaseline:
    """纯判据：时间线重放（冷却重建同模式）。"""

    def test_replay_unions_covered_and_latest_counters_win(self):
        from neurova.context.fold_trigger import rebuildFoldBaseline

        events = [
            {"kind": "context_compacted", "event": {"cutoffIndex": 3}},
            {
                "kind": "fold_baseline",
                "ts": "2026-11-18T10:00:00",
                "event": {
                    "lastFoldTokens": 100,
                    "lastFoldMsgs": 5,
                    "lastCount": 5,
                    "foldSeq": 1,
                    "summary": "第一代",
                    "covered": ["h1", "h2"],
                },
            },
            {"kind": "compaction_cooldown", "event": {"consecutiveFailures": 2}},
            {
                "kind": "fold_baseline",
                "ts": "2026-11-18T11:00:00",
                "event": {
                    "lastFoldTokens": 200,
                    "lastFoldMsgs": 9,
                    "lastCount": 9,
                    "foldSeq": 2,
                    "summary": "第二代",
                    "covered": ["h2", "h3"],
                },
            },
        ]
        baseline = rebuildFoldBaseline(events)
        assert baseline["last_fold_tokens"] == 200, "计数器取最新一条"
        assert baseline["last_fold_msgs"] == 9
        assert baseline["last_count"] == 9
        assert baseline["fold_seq"] == 2
        assert baseline["summary"] == "第二代"
        assert baseline["covered"] == {"h1", "h2", "h3"}, "covered 取并集（增量落账）"

    def test_ignores_unrelated_kinds_and_empty(self):
        from neurova.context.fold_trigger import rebuildFoldBaseline

        assert rebuildFoldBaseline([]) == {}
        assert rebuildFoldBaseline(None) == {}
        assert (
            rebuildFoldBaseline(
                [
                    {"kind": "context_compacted", "event": {}},
                    {"kind": "compaction_cooldown", "event": {}},
                ]
            )
            == {}
        ), "无 fold_baseline 事件 = 无基线"

    def test_bad_rows_skipped(self):
        from neurova.context.fold_trigger import rebuildFoldBaseline

        events = [
            "not-a-dict",
            {"kind": "fold_baseline", "event": "not-a-dict"},
            {"kind": "fold_baseline", "event": {"lastFoldTokens": "7", "covered": ["h1", None, ""]}},
        ]
        baseline = rebuildFoldBaseline(events)
        assert baseline["last_fold_tokens"] == 7
        assert baseline["covered"] == {"h1"}, "坏 hash 与空值剔除"
