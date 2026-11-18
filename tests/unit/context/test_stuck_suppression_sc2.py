# -*- coding: utf-8 -*-
"""SC-2 卡住抑制（接现成元认知信号，不新造卡住检测器）。

契约（docs/08-research/reference_f_vs_neurova_context_compression_comparison_2026-11-17.md §9.4 SC-2、§9.5）：
1. 命中条件 = 活跃 avoid_tool 教训（SelfModelEngine.check_tool_advisory 同源）∨
   工具失败率超阈（MetaLedger.tool_success_rates 现成读数）；
2. 命中时该轮**不主动**折叠（增长门被抑制）；预算击穿（被动兜底）不受理——容量优先；
3. 未命中时行为与改前逐字一致（增长门照常折）；
4. 过期教训不算活跃（不抑制）；
5. 命中进读数面（fold_suppression 槽 + fold_trigger 归因改判），不留静默抑制；
6. 信号源全部只读（MetaLedger SELECT / SelfModelEngine 查询），不写反思账。
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.window_compactor import estimate_window_tokens


def _mk_agent(model: str = "test-model"):
    mock_agent = MagicMock()
    mock_agent.config = MagicMock()
    mock_agent.config.name = "test_agent"
    mock_agent.config.constitution = ""
    mock_agent.config.behavior_rules = []
    mock_agent.config.llm_model = model
    mock_agent.config.agent_id = "a-sc2-iso"
    mock_agent.memory_manager = MagicMock()
    mock_agent.context_builder = MagicMock()
    mock_agent.tool_router = None
    mock_agent._skill_registry = None
    mock_agent.soul = "你是测试助手"
    mock_agent.personality = ""
    mock_agent.conversation_history = []
    mock_agent.growth_log_manager = MagicMock()
    mock_agent.user_id = "u-sc2-iso"
    mock_agent.agent_id = "a-sc2-iso"
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


def _mk_orchestrator() -> ContextOrchestrator:
    orch = ContextOrchestrator(_mk_agent(), use_pool=True, auto_tag=False)
    orch._window_hard_limit = 10**9
    return orch


def _gateScenario(orch: ContextOrchestrator, key: str):
    """增长门场景：占用 0.8（不击穿）＋ 增量过门槛。"""
    msgs = [_long_msg(i) for i in range(24)]
    total = estimate_window_tokens(msgs)
    budget = orch._effectiveWindowBudget(int(total * 1.25))
    assert total <= budget
    cache = orch._window_cache_slot(key)
    cache["last_fold_tokens"] = int(total * 0.5)
    cache["last_fold_msgs"] = 0
    return msgs, budget, total


def _writeAvoidToolLesson(agentId: str, tool: str = "search", *, expired: bool = False):
    from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger

    expires = datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 1)
    get_meta_ledger().create_record(
        agent_id=agentId,
        kind="lesson",
        type="monitoring",
        content=f"近期 {tool} 连续失败，暂停使用",
        confidence=0.9,
        metadata={
            "subject": tool,
            "operator": "sequence",
            "recommendation": "avoid_tool",
            "expires_at": expires.isoformat(),
            "text": f"近期 {tool} 连续失败，暂停使用",
        },
    )


def _writeToolEvents(agentId: str, tool: str, failures: int, successes: int = 0):
    from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger

    ledger = get_meta_ledger()
    for _ in range(failures):
        ledger.write_event(agentId, "tool", tool, 10.0, False, {})
    for _ in range(successes):
        ledger.write_event(agentId, "tool", tool, 10.0, True, {})


class TestStuckSuppressionFold:
    """卡住命中：该轮不主动折叠（被动兜底仍在）。"""

    @pytest.mark.asyncio
    async def test_active_avoid_tool_lesson_skips_proactive_fold(self):
        orch = _mk_orchestrator()

        async def fail_summarize(chunks, previous_summary=""):
            raise AssertionError("卡住命中时不得发起主动折叠摘要")

        orch._window_summarizer = fail_summarize
        msgs, budget, total = _gateScenario(orch, "sc2-session")
        _writeAvoidToolLesson(orch._agent.config.agent_id, "search")

        view = await orch._apply_window_budget(msgs, budget, cache_key="sc2-session")

        assert _summary_rows(view) == [], "卡住命中：该轮不得主动折叠"
        assert len(view) == len(msgs), "未折叠时视图原样返回"
        assert _hasMsg(view, "长消息23"), "完整历史保留（卡住时最需要历史自我修正）"

    @pytest.mark.asyncio
    async def test_tool_failure_rate_skips_proactive_fold(self):
        """工具失败率超阈（tool_success_rates 现成读数）同样命中。"""
        orch = _mk_orchestrator()

        async def fail_summarize(chunks, previous_summary=""):
            raise AssertionError("卡住命中时不得发起主动折叠摘要")

        orch._window_summarizer = fail_summarize
        msgs, budget, total = _gateScenario(orch, "sc2-session")
        _writeToolEvents(orch._agent.config.agent_id, "browser", failures=6)

        view = await orch._apply_window_budget(msgs, budget, cache_key="sc2-session")

        assert _summary_rows(view) == [], "失败率超阈：该轮不得主动折叠"
        assert len(view) == len(msgs)

    @pytest.mark.asyncio
    async def test_healthy_signals_fold_normally(self):
        """未命中：增长门照常折（行为与改前一致）。"""
        orch = _mk_orchestrator()

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs, budget, total = _gateScenario(orch, "sc2-session")
        _writeToolEvents(orch._agent.config.agent_id, "browser", failures=1, successes=9)

        view = await orch._apply_window_budget(msgs, budget, cache_key="sc2-session")

        assert _summary_rows(view), "未命中卡住：增长门照常折叠"
        assert not _hasMsg(view, "长消息0"), "老增量照常入池"

    @pytest.mark.asyncio
    async def test_budget_breach_still_folds_when_stuck(self):
        """被动兜底：预算击穿时即便卡住也必折（容量优先，§9.5 第 1 条）。"""
        orch = _mk_orchestrator()

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs = [_long_msg(i) for i in range(24)]
        total = estimate_window_tokens(msgs)
        budget = orch._effectiveWindowBudget(int(total * 0.9))
        assert total > budget
        _writeAvoidToolLesson(orch._agent.config.agent_id, "search")

        view = await orch._apply_window_budget(msgs, budget, cache_key="sc2-session")

        assert _summary_rows(view), "击穿必折：卡住抑制不作用于硬水位路径"

    @pytest.mark.asyncio
    async def test_expired_lesson_does_not_suppress(self):
        """过期教训不活跃：不抑制折叠。"""
        orch = _mk_orchestrator()

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs, budget, total = _gateScenario(orch, "sc2-session")
        _writeAvoidToolLesson(orch._agent.config.agent_id, "search", expired=True)

        view = await orch._apply_window_budget(msgs, budget, cache_key="sc2-session")

        assert _summary_rows(view), "过期教训不抑制折叠"

    @pytest.mark.asyncio
    async def test_stuck_hit_visible_in_readout(self):
        """命中必须可见：fold_trigger 归因改判 + fold_suppression 计数。"""
        orch = _mk_orchestrator()

        async def fail_summarize(chunks, previous_summary=""):
            raise AssertionError("不得折叠")

        orch._window_summarizer = fail_summarize
        msgs, budget, total = _gateScenario(orch, "sc2-session")
        _writeAvoidToolLesson(orch._agent.config.agent_id, "search")

        await orch._apply_window_budget(msgs, budget, cache_key="sc2-session")

        assert orch._context_health["fold_trigger"]["last_reason"] == "stuck_suppressed", (
            "归因要如实改判为 stuck_suppressed，不谎报 growth_gate"
        )
        assert orch._context_health["fold_trigger"]["should_fold"] is False
        slot = orch._context_health["fold_suppression"]
        assert slot["stuck_hits"] >= 1
        assert slot["last_stuck_reason"] == "avoid_tool"


class TestStuckSuppressionPure:
    """纯判据：stuckSuppressionHit。"""

    def test_avoid_tool_alone_hits(self):
        from neurova.context.fold_trigger import stuckSuppressionHit

        assert stuckSuppressionHit(avoidToolActive=True, toolSuccessRates={}) is True

    def test_low_success_rate_hits(self):
        from neurova.context.fold_trigger import stuckSuppressionHit

        assert (
            stuckSuppressionHit(avoidToolActive=False, toolSuccessRates={"a": 0.4}) is True
        ), "成功率 0.4 = 失败率 0.6 ≥ 0.5 阈值"

    def test_healthy_rates_do_not_hit(self):
        from neurova.context.fold_trigger import stuckSuppressionHit

        assert (
            stuckSuppressionHit(avoidToolActive=False, toolSuccessRates={"a": 0.9, "b": 1.0})
            is False
        )

    def test_threshold_boundary_and_override(self):
        from neurova.context.fold_trigger import stuckSuppressionHit

        # 失败率恰在阈值：不判卡住（"超阈"取严格大于）
        assert (
            stuckSuppressionHit(avoidToolActive=False, toolSuccessRates={"a": 0.5}) is False
        )
        assert (
            stuckSuppressionHit(
                avoidToolActive=False, toolSuccessRates={"a": 0.5}, failureRateThreshold=0.4
            )
            is True
        )

    def test_empty_rates_do_not_hit(self):
        from neurova.context.fold_trigger import stuckSuppressionHit

        assert stuckSuppressionHit(avoidToolActive=False, toolSuccessRates={}) is False


class TestActiveToolAdvisories:
    """SelfModelEngine.active_tool_advisories：与 check_tool_advisory 同一活跃性判据。"""

    def test_returns_only_active_avoid_tool_lessons(self):
        from neurova.cognitive_layers.meta_cognition_layer.self_model import (
            get_self_model_engine,
            reset_self_model_engine,
        )

        reset_self_model_engine()
        try:
            engine = get_self_model_engine("a-adv")
            _writeAvoidToolLesson("a-adv", "search")
            _writeAvoidToolLesson("a-adv", "browser", expired=True)
            # 非 avoid_tool 教训不进 advisories
            from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger

            get_meta_ledger().create_record(
                agent_id="a-adv",
                kind="lesson",
                type="monitoring",
                content="改用 X",
                metadata={"subject": "search", "recommendation": "use_instead", "expires_at": ""},
            )
            advisories = engine.active_tool_advisories()
            assert set(advisories) == {"search"}, "只有活跃 avoid_tool 教训入选"
            assert advisories["search"]["recommendation"] == "avoid_tool"
            # 与单工具查询同口径
            assert engine.check_tool_advisory("search") is not None
            assert engine.check_tool_advisory("browser") is None
        finally:
            reset_self_model_engine()
