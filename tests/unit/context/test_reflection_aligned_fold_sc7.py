# -*- coding: utf-8 -*-
"""SC-7 反思节律对齐折叠 —— 候选排序信号（不绕触发门）。

契约（docs/08-research/selfcompact_vs_neurova_context_compression_comparison_2026-11-17.md §9.4 SC-7、§9.5）：
1. 反思编译完成后（MetaLedger 有 reflection 游标），下一轮折叠的候选区
   延伸到「最近反思时刻之前的更早消息」——未被反思时，这些消息按既有
   预算规则保留在尾区（同一场景逐字对比）；
2. 信号是**候选排序**，不是触发门：增长门/击穿判定（decideFoldTrigger）
   不变——门不触发时即便已反思也不折；
3. 边界锚点保留：keep_min 尾保护（推导链最后一条消息/当前工具调用对）
   不因本机制被折（与既有冻结头/前缀保护合流）；
4. 严格变小守卫：折叠后窗口 token 必须严格小于折叠前（assertCompactionShrinks）；
5. 信号源走 MetaLedger **只读**（lastReflectionCursor 只 SELECT）。
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

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
    # 游标查询读 config.agent_id（与 metacog 注入同纪律：只认真串）
    mock_agent.config.agent_id = "a-sc7-iso"
    mock_agent.memory_manager = MagicMock()
    mock_agent.context_builder = MagicMock()
    mock_agent.tool_router = None
    mock_agent._skill_registry = None
    mock_agent.soul = "你是测试助手"
    mock_agent.personality = ""
    mock_agent.conversation_history = []
    mock_agent.growth_log_manager = MagicMock()
    mock_agent.user_id = "u-sc7-iso"
    mock_agent.agent_id = "a-sc7-iso"
    return mock_agent


def _long_msg(i: int, chars: int = 900) -> dict:
    return {"role": "user", "content": f"长消息{i}: " + "测" * chars}


def _summary_rows(view):
    return [m for m in view if m.get("role") == "system" and "早期对话摘要" in str(m.get("content", ""))]


def _viewContents(view) -> set:
    return {str(m.get("content", "")) for m in view}


def _hasMsg(view, tag: str) -> bool:
    return any(tag in str(m.get("content", "")) for m in view)


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    from neurova.cognitive_layers.meta_cognition_layer.ledger import reset_meta_ledger
    from neurova.cognitive_layers.meta_cognition_layer.self_model import reset_self_model_engine

    reset_meta_ledger()
    reset_self_model_engine()
    yield
    reset_meta_ledger()
    reset_self_model_engine()


def _writeReflection(agentId: str, marker: str, lastEventId: int = 7) -> None:
    """在 MetaLedger 落一条反思记录（游标）——只写反思侧自己的账。"""
    from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger

    get_meta_ledger().create_record(
        agent_id=agentId,
        kind="reflection",
        type="monitoring",
        content=f"反思报告：{marker}",
        confidence=0.9,
        metadata={"trigger": "periodic_turn", "lesson_count": 2, "last_event_id": lastEventId},
    )


def _mk_orchestrator(budget: int) -> ContextOrchestrator:
    orch = ContextOrchestrator(_mk_agent(), use_pool=True, auto_tag=False)
    orch._window_token_budget = budget
    orch._window_hard_limit = 10**9  # 摘除硬顶钳（焦点在折叠候选，不在硬顶）
    return orch


async def _apply(orch: ContextOrchestrator, msgs: list, budget: int) -> list:
    return await orch._apply_window_budget(msgs, budget, cache_key="sc7-session")


class TestReflectionAlignedFold:
    """「反思已编译 + 一批更早消息」：下一轮折叠候选含该区间。"""

    def _scenario(self, orch: ContextOrchestrator, n: int = 30):
        """等长消息 + 预算取 0.9×总占（必击穿）。返回 (msgs, 有效预算)。"""
        msgs = [_long_msg(i) for i in range(n)]
        total = estimate_window_tokens(msgs)
        budget = orch._effectiveWindowBudget(int(total * 0.9))
        assert total > budget, "场景预朞性质错误：应处于预算击穿区"
        return msgs, budget

    @pytest.mark.asyncio
    async def test_reflected_earlier_messages_enter_next_fold(self):
        """反思已编译：更早消息（含既有规则会保留的那段）进折叠候选。"""
        orch = _mk_orchestrator(budget=10**9)
        agentId = orch._agent.config.agent_id
        _writeReflection(agentId, marker="编译完毕", lastEventId=42)

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs, budget = self._scenario(orch)

        view = await _apply(orch, msgs, budget)

        assert _summary_rows(view), "击穿必折：摘要行应在场"
        # 反思边界之后的尾区 + keep_min 锚点必须存活
        assert _hasMsg(view, "长消息29"), "最后一条消息（边界锚点）不得被折"
        assert _hasMsg(view, "长消息24"), "反思对齐切点之后的消息应保留"
        # 切点之前的更早消息全部入折叠候选（含既有规则原会保留的 M17..M23）
        assert not _hasMsg(view, "长消息23"), "反思已提炼的更早消息应进折叠候选"
        assert not _hasMsg(view, "长消息17"), "反思已提炼的更早消息应进折叠候选"
        assert not _hasMsg(view, "长消息0"), "最老消息应被折"

    @pytest.mark.asyncio
    async def test_without_reflection_earlier_messages_stay(self):
        """未被反思：同一场景按既有规则折叠——更早消息不整体入候选。"""
        orch = _mk_orchestrator(budget=10**9)

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：主题X。"

        orch._window_summarizer = fake_summarize
        msgs, budget = self._scenario(orch)

        view = await _apply(orch, msgs, budget)

        assert _summary_rows(view), "击穿必折：摘要行应在场"
        # 既有规则：从尾部按预算保留——切点之下的消息仍在视图
        assert _hasMsg(view, "长消息17"), "未被反思时，既有预算规则应保留该消息"
        assert not _hasMsg(view, "长消息16"), "既有预算规则的切点应在其下"
        # 与反思臂的对比锚：M17 在无反思时保留、有反思时被折（另一用例）
        assert not _hasMsg(view, "长消息0")

    @pytest.mark.asyncio
    async def test_reflection_does_not_bypass_gate(self):
        """信号不绕门：占用远低于下限时，即便已反思也不折。"""
        orch = _mk_orchestrator(budget=10**9)
        agentId = orch._agent.config.agent_id
        _writeReflection(agentId, marker="编译完毕")

        async def fail_summarize(chunks, previous_summary=""):
            raise AssertionError("门未触发时不得发起摘要")

        orch._window_summarizer = fail_summarize
        msgs = [_long_msg(i) for i in range(6)]
        budget = orch._effectiveWindowBudget(10**9)

        view = await _apply(orch, msgs, budget)

        assert _summary_rows(view) == [], "门未触发：不得折叠"
        assert len(view) == len(msgs), "门未触发：视图原样返回"

    @pytest.mark.asyncio
    async def test_boundary_tool_pair_survives(self):
        """边界锚点：尾部工具调用对不因反思对齐被折。"""
        orch = _mk_orchestrator(budget=10**9)
        agentId = orch._agent.config.agent_id
        _writeReflection(agentId, marker="编译完毕")

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs = [_long_msg(i) for i in range(24)]
        msgs.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_sc7_1", "function": {"name": "search", "arguments": "{}"}}],
            }
        )
        msgs.append({"role": "tool", "tool_call_id": "call_sc7_1", "name": "search", "content": "工具结果原文"})
        total = estimate_window_tokens(msgs)
        budget = orch._effectiveWindowBudget(int(total * 0.9))
        assert total > budget

        view = await _apply(orch, msgs, budget)

        assert _hasMsg(view, "工具结果原文"), "当前工具调用对（结果行）不得被折"
        assert any("call_sc7_1" in str(m.get("content", "")) or m.get("tool_call_id") == "call_sc7_1" for m in view), (
            "工具寻址指针不得因折叠丢失"
        )
        assert not _hasMsg(view, "长消息0")

    @pytest.mark.asyncio
    async def test_strict_shrink_guard_holds(self):
        """严格变小守卫：反思对齐折叠后窗口 token 严格变小。"""
        from neurova.context_pool import assertCompactionShrinks

        orch = _mk_orchestrator(budget=10**9)
        agentId = orch._agent.config.agent_id
        _writeReflection(agentId, marker="编译完毕")

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs, budget = self._scenario(orch)

        view = await _apply(orch, msgs, budget)

        assertCompactionShrinks(estimate_window_tokens(msgs), estimate_window_tokens(view))


class TestReflectionFoldCutIndex:
    """纯判据：切点 = min(已提炼条数, 尾段-keep_min)，钳非负。"""

    def test_cut_respects_keep_min(self):
        from neurova.context.fold_trigger import reflectionFoldCutIndex

        assert reflectionFoldCutIndex(rest_len=30, distilled_len=30) == 24
        assert reflectionFoldCutIndex(rest_len=30, distilled_len=10) == 10
        assert reflectionFoldCutIndex(rest_len=8, distilled_len=8) == 2

    def test_cut_never_negative_and_zero_without_distilled(self):
        from neurova.context.fold_trigger import reflectionFoldCutIndex

        assert reflectionFoldCutIndex(rest_len=4, distilled_len=4) == 0
        assert reflectionFoldCutIndex(rest_len=30, distilled_len=0) == 0
        assert reflectionFoldCutIndex(rest_len=0, distilled_len=5) == 0
        assert reflectionFoldCutIndex(rest_len=10, distilled_len=99) == 4


class TestReflectionAlignedFoldBudget:
    """纯判据：对齐预算 = min(原预算, 保留区/份额)，只加深不放宽。"""

    def test_caps_to_kept_region_and_never_expands(self):
        from neurova.context.fold_trigger import reflectionAlignedFoldBudget

        assert reflectionAlignedFoldBudget(plain_fold_budget=27000, kept_tokens=6000, target_ratio=0.5) == 12000
        # 保留区更大时取原预算（不放宽折叠）
        assert reflectionAlignedFoldBudget(plain_fold_budget=8000, kept_tokens=60000, target_ratio=0.5) == 8000
        # 下限 1000
        assert reflectionAlignedFoldBudget(plain_fold_budget=500, kept_tokens=10, target_ratio=0.5) == 1000


class TestLedgerLastReflectionCursor:
    """MetaLedger 只读游标：取最近一条 reflection 记录的编译点。"""

    def test_returns_latest_reflection_cursor(self):
        from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger

        ledger = get_meta_ledger()
        ledger.create_record(
            agent_id="a-cursor", kind="reflection", type="monitoring",
            content="第一次反思", metadata={"trigger": "manual", "lesson_count": 1, "last_event_id": 3},
        )
        ledger.create_record(
            agent_id="a-cursor", kind="reflection", type="monitoring",
            content="第二次反思", metadata={"trigger": "periodic_turn", "lesson_count": 2, "last_event_id": 9},
        )
        # 他类记录不干扰
        ledger.create_record(agent_id="a-cursor", kind="thought", type="monitoring", content="条目")

        cursor = ledger.lastReflectionCursor("a-cursor")
        assert cursor is not None
        assert cursor["last_event_id"] == 9
        assert cursor["lesson_count"] == 2
        assert cursor["created_at"]

        assert ledger.lastReflectionCursor("a-nobody") is None

    def test_cursor_without_events_is_none_valued(self):
        from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger

        ledger = get_meta_ledger()
        ledger.create_record(
            agent_id="a-empty", kind="reflection", type="monitoring",
            content="空反思", metadata={"trigger": "manual"},
        )
        cursor = ledger.lastReflectionCursor("a-empty")
        assert cursor is not None
        assert cursor["last_event_id"] is None
