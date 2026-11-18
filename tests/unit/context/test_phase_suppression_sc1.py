# -*- coding: utf-8 -*-
"""SC-1 任务相位抑制（软抑制 + 边界锚点）。

契约（docs/08-research/reference_f_vs_neurova_context_compression_comparison_2026-11-17.md §9.4 SC-1、§9.5）：
1. 信号源 = run 生命周期（agent_run_ledger，**只读**）：本会话存在进行中的
   子任务（未到终态、租约未过期）即命中相位抑制；
2. 软抑制不是一刀切：增长门折叠照常发生（摘要行在场、老增量照常入池），
   但推导边界锚点（最后一条消息 / 当前工具调用对）**整体**保留在视图；
3. 相位未命中时行为与改前逐字一致（同场景对照：无保护时当前工具调用对
   的前段会被折掉，产生孤儿 tool 行）；
4. 预算击穿（硬水位）不受相位抑制管辖——容量优先，击穿必折；
5. 严格变小守卫照常（assertCompactionShrinks）。
"""
import os
import sys
from unittest.mock import MagicMock, patch

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
    mock_agent.config.agent_id = "a-sc1-iso"
    mock_agent.memory_manager = MagicMock()
    mock_agent.context_builder = MagicMock()
    mock_agent.tool_router = None
    mock_agent._skill_registry = None
    mock_agent.soul = "你是测试助手"
    mock_agent.personality = ""
    mock_agent.conversation_history = []
    mock_agent.growth_log_manager = MagicMock()
    mock_agent.user_id = "u-sc1-iso"
    mock_agent.agent_id = "a-sc1-iso"
    return mock_agent


def _long_msg(i: int, chars: int = 900) -> dict:
    return {"role": "user", "content": f"长消息{i}: " + "测" * chars}


def _summary_rows(view):
    return [m for m in view if m.get("role") == "system" and "早期对话摘要" in str(m.get("content", ""))]


def _hasMsg(view, tag: str) -> bool:
    return any(tag in str(m.get("content", "")) for m in view)


def _toolBlock(rows: int = 14, tool: str = "search") -> list:
    """当前（未闭合）工具调用对：1 条 assistant.tool_calls + N 条 tool 结果行。

    结果行带大载荷（与普通消息同量级）：保证"增长门按预算保留的尾区"
    小于整个调用对——无相位抑制时调用对前段会被折掉（改前基线），有相位
    抑制时整体保留。
    """
    block = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": f"call_sc1_{j}", "function": {"name": tool, "arguments": "{}"}}
                for j in range(rows)
            ],
        }
    ]
    block += [
        {
            "role": "tool",
            "tool_call_id": f"call_sc1_{j}",
            "name": tool,
            "content": f"工具结果{j}原文：" + "数" * 800,
        }
        for j in range(rows)
    ]
    return block


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    # 折叠目标比固定 0.5（不受账单画像影响），场景数字可推
    monkeypatch.setenv("NEUROVA_CACHE_ADAPTIVE_FOLD", "0")
    from neurova.cognitive_layers.meta_cognition_layer.ledger import reset_meta_ledger
    from neurova.cognitive_layers.meta_cognition_layer.self_model import reset_self_model_engine
    from neurova.core import agent_run_store as ars

    ars.reset_agent_run_store()
    reset_meta_ledger()
    reset_self_model_engine()
    yield
    ars.reset_agent_run_store()
    reset_meta_ledger()
    reset_self_model_engine()


def _mk_orchestrator() -> ContextOrchestrator:
    orch = ContextOrchestrator(_mk_agent(), use_pool=True, auto_tag=False)
    orch._window_hard_limit = 10**9  # 摘除硬顶钳（焦点在增长门，不在硬顶）
    return orch


def _gateScenario(orch: ContextOrchestrator, key: str, plain: int = 20):
    """增长门场景：占用 0.8（不击穿）＋ 增量过门槛 ＋ 尾部当前工具调用对（15 行）。"""
    msgs = [_long_msg(i) for i in range(plain)] + _toolBlock()
    total = estimate_window_tokens(msgs)
    budget = orch._effectiveWindowBudget(int(total * 1.25))
    assert total <= budget, "场景预朞性质错误：不应处于预算击穿区"
    cache = orch._window_cache_slot(key)
    cache["last_fold_tokens"] = int(total * 0.5)
    cache["last_fold_msgs"] = 0
    return msgs, budget, total


def _phase(active: bool) -> dict:
    return {"active": active, "subtaskRuns": 1 if active else 0, "selfRun": False}


class TestPhaseSuppressionFold:
    """相位命中：折叠照常（软抑制），但边界锚点整体留在视图。"""

    @pytest.mark.asyncio
    async def test_phase_hit_keeps_boundary_anchors_in_view(self):
        from neurova.context_pool import assertCompactionShrinks

        orch = _mk_orchestrator()

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs, budget, total = _gateScenario(orch, "sc1-session")

        with patch(
            "neurova.core.agent_run_ledger.activeRunPhaseSignal", return_value=_phase(True)
        ):
            view = await orch._apply_window_budget(msgs, budget, cache_key="sc1-session")

        # 软抑制：折叠仍发生
        assert _summary_rows(view), "相位命中是软抑制：增长门折叠仍应发生"
        # 边界锚点：当前工具调用对（assistant.tool_calls 行 + 全部 tool 结果行）整体在视图
        assert any(
            m.get("role") == "assistant" and m.get("tool_calls") for m in view
        ), "当前工具调用对（assistant.tool_calls 声明行）不得被折"
        for j in range(14):
            assert _hasMsg(view, f"工具结果{j}原文"), f"工具结果行 {j} 是边界锚点，不得被折"
        # 其余照常入池：最老消息被折
        assert not _hasMsg(view, "长消息0"), "锚点之外的老增量应照常折叠"
        # 严格变小守卫照常
        assertCompactionShrinks(total, estimate_window_tokens(view))

    @pytest.mark.asyncio
    async def test_phase_inactive_behaves_as_before(self):
        """对照：相位未命中时行为与改前一致——工具调用对前段被折（孤儿行由既有链路处置）。"""
        orch = _mk_orchestrator()

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs, budget, total = _gateScenario(orch, "sc1-session")

        with patch(
            "neurova.core.agent_run_ledger.activeRunPhaseSignal", return_value=_phase(False)
        ):
            view = await orch._apply_window_budget(msgs, budget, cache_key="sc1-session")

        assert _summary_rows(view), "无相位抑制：增长门照常折叠"
        assert not any(
            m.get("role") == "assistant" and m.get("tool_calls") for m in view
        ), "无相位抑制：改前行为 = 工具调用对声明行可被折（本用例钉住改前基线）"
        assert _hasMsg(view, "工具结果13原文"), "尾保护内的结果行照旧保留"
        assert not _hasMsg(view, "工具结果0原文"), "改前行为：调用对前段被折"

    @pytest.mark.asyncio
    async def test_budget_breach_not_blocked_by_phase(self):
        """硬水位优先：击穿时相位抑制不拦截折叠（容量安全优先于时机最优）。"""
        orch = _mk_orchestrator()

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs = [_long_msg(i) for i in range(24)]
        total = estimate_window_tokens(msgs)
        budget = orch._effectiveWindowBudget(int(total * 0.9))
        assert total > budget, "场景预朞性质错误：应处于预算击穿区"

        with patch(
            "neurova.core.agent_run_ledger.activeRunPhaseSignal", return_value=_phase(True)
        ) as sig:
            view = await orch._apply_window_budget(msgs, budget, cache_key="sc1-session")
        assert _summary_rows(view), "击穿必折：相位抑制不作用于硬水位路径"
        # 击穿路径不应查询相位信号（抑制只作用于增长门主动路径）
        sig.assert_not_called()

    @pytest.mark.asyncio
    async def test_phase_signal_readonly_on_gate_path_only(self):
        """增长门路径才查相位信号；门未触发（below floor）不查。"""
        orch = _mk_orchestrator()

        async def fail_summarize(chunks, previous_summary=""):
            raise AssertionError("门未触发时不得发起摘要")

        orch._window_summarizer = fail_summarize
        msgs = [_long_msg(i) for i in range(6)]
        budget = orch._effectiveWindowBudget(10**9)

        with patch(
            "neurova.core.agent_run_ledger.activeRunPhaseSignal", return_value=_phase(True)
        ) as sig:
            view = await orch._apply_window_budget(msgs, budget, cache_key="sc1-session")
        sig.assert_not_called(), "门未触发时不得查询相位信号"
        assert _summary_rows(view) == []
        assert len(view) == len(msgs)

    @pytest.mark.asyncio
    async def test_phase_hit_recorded_in_health(self):
        """命中必须可见：fold_suppression 读数槽记录相位命中。"""
        orch = _mk_orchestrator()

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs, budget, _ = _gateScenario(orch, "sc1-session")

        with patch(
            "neurova.core.agent_run_ledger.activeRunPhaseSignal", return_value=_phase(True)
        ):
            await orch._apply_window_budget(msgs, budget, cache_key="sc1-session")

        slot = orch._context_health["fold_suppression"]
        assert slot["phase_hits"] >= 1, "相位命中要进读数面，不留静默抑制"


class TestDerivationAnchorCount:
    """纯判据：边界锚点 = 最后一条消息 + 当前未闭合工具调用对。"""

    def test_empty_and_single(self):
        from neurova.context.fold_trigger import derivationAnchorCount

        assert derivationAnchorCount([]) == 0
        assert derivationAnchorCount([{"role": "user", "content": "hi"}]) == 1

    def test_plain_tail_is_one_anchor(self):
        from neurova.context.fold_trigger import derivationAnchorCount

        msgs = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
        assert derivationAnchorCount(msgs) == 1

    def test_tool_pair_is_anchors(self):
        from neurova.context.fold_trigger import derivationAnchorCount

        msgs = [
            {"role": "user", "content": "a"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "function": {"name": "t", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "t", "content": "r1"},
        ]
        assert derivationAnchorCount(msgs) == 2, "assistant 调用行 + tool 结果行都是锚点"

    def test_parallel_tool_rows_all_anchors(self):
        from neurova.context.fold_trigger import derivationAnchorCount

        msgs = [
            {"role": "user", "content": "a"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "function": {"name": "t", "arguments": "{}"}},
                    {"id": "c2", "function": {"name": "t", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "t", "content": "r1"},
            {"role": "tool", "tool_call_id": "c2", "name": "t", "content": "r2"},
        ]
        assert derivationAnchorCount(msgs) == 3, "一次并行多工具调用是一个调用对整体"

    def test_pending_call_row_is_anchor(self):
        from neurova.context.fold_trigger import derivationAnchorCount

        msgs = [
            {"role": "user", "content": "a"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "function": {"name": "t", "arguments": "{}"}}],
            },
        ]
        assert derivationAnchorCount(msgs) == 1, "已发出未拿结果的调用行本身是锚点"

    def test_orphan_tool_row_still_anchored(self):
        from neurova.context.fold_trigger import derivationAnchorCount

        msgs = [
            {"role": "user", "content": "a"},
            {"role": "tool", "tool_call_id": "c1", "name": "t", "content": "r1"},
        ]
        assert derivationAnchorCount(msgs) == 1


class TestActiveRunPhaseSignal:
    """run 生命周期读数（只读）：子任务未到终态 = 相位命中。"""

    def test_active_subtask_detected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
        from neurova.core import agent_run_store as ars
        from neurova.core.agent_run_ledger import activeRunPhaseSignal

        ars.reset_agent_run_store()
        try:
            store = ars.get_agent_run_store()
            run_id = store.intake(
                "member-s1", "u1", "a1", "子任务", "sub-1", "parent-s1", ""
            )
            assert store.claim_next("member-s1") == run_id
            sig = activeRunPhaseSignal("parent-s1")
            assert sig["active"] is True and sig["subtaskRuns"] == 1
            # 终态后相位消失
            assert store.finish(run_id, ars.OWNER_IDENTITY, "completed", None)
            sig2 = activeRunPhaseSignal("parent-s1")
            assert sig2["active"] is False and sig2["subtaskRuns"] == 0
        finally:
            ars.reset_agent_run_store()

    def test_parked_and_stalled_not_active(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
        from neurova.core import agent_run_store as ars
        from neurova.core.agent_run_ledger import activeRunPhaseSignal

        ars.reset_agent_run_store()
        try:
            store = ars.get_agent_run_store()
            run_id = store.intake(
                "member-s2", "u1", "a1", "子任务", "sub-2", "parent-s2", ""
            )
            store.claim_next("member-s2")
            # 挂起（等人续跑）不算"进行中"
            assert store.park(run_id, ars.OWNER_IDENTITY, "quota", {})
            sig = activeRunPhaseSignal("parent-s2")
            assert sig["active"] is False, "parked = 等人，不是执行中的子任务"
            # 租约过期的 running 是 stalled，也不是"进行中"
            stale = store.intake(
                "member-s3", "u1", "a1", "子任务", "sub-3", "parent-s2", ""
            )
            store.claim_next("member-s3")
            store._conn.execute(
                "UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?",
                (1.0, stale),
            )
            store._conn.commit()
            sig2 = activeRunPhaseSignal("parent-s2")
            assert sig2["active"] is False, "stalled（租约过期）不是进行中的子任务"
        finally:
            ars.reset_agent_run_store()

    def test_ledger_failure_is_failopen(self, monkeypatch):
        """台账不可读按无相位处理（抑制信号缺席 = 行为与改前一致）。"""
        from neurova.core import agent_run_ledger as arl

        def boom(_sid):
            raise RuntimeError("ledger down")

        monkeypatch.setattr(
            "neurova.core.agent_run_store.get_agent_run_store", boom
        )
        sig = arl.activeRunPhaseSignal("any-session")
        assert sig["active"] is False
