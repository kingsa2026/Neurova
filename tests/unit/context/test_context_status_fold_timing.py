# -*- coding: utf-8 -*-
"""SC-3：context_status 回执的「折叠时机判读」块。

契约：
1. 判定**直接复用** `fold_trigger.decideFoldTrigger`（单一事实源）——回执里的
   should_fold / reason / 三现场量必须与同输入的单源判定逐字一致；
2. 增长门四判据（占用 / 增量 token / 增量消息 / 可折质量）各自带 value/threshold/met；
3. 元认知读数（未编译事件数、距上次反思、活跃教训数）在场，取自
   MetaLedger / SelfModelEngine 既有读数面（不新造状态）；
4. 判读块有界（具名常量上限），不把大段状态塞进回执。
"""
import json
import os
import sys
import uuid
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.fold_trigger import (
    REASON_BELOW_FLOOR,
    REASON_BUDGET_BREACH,
    REASON_GROWTH_GATE,
    decideFoldTrigger,
    growthBudgetShare,
    growthGateParams,
)
from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.window_compactor import estimate_window_tokens
from neurova.tool_executor import ToolExecutor


@pytest.fixture(autouse=True)
def _resetEngines():
    """SelfModelEngine 单例是进程级的（_last_reflect_at 内存态）——测试间重置。"""
    from neurova.cognitive_layers.meta_cognition_layer.self_model import (
        reset_self_model_engine,
    )

    reset_self_model_engine()
    yield
    reset_self_model_engine()


def _mk_agent():
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u-sc3"
    agent.agent_id = f"a-sc3-{uuid.uuid4().hex[:8]}"
    return agent


def _long_msg(i: int, chars: int = 900) -> dict:
    return {"role": "user", "content": f"长消息{i}: " + "测" * chars}


def _mk_orchestrator(agent, budget: int) -> ContextOrchestrator:
    orch = ContextOrchestrator(agent, use_pool=True, auto_tag=False)
    orch._window_token_budget = budget
    agent.context_orchestrator = orch
    return orch


def _slotBaseline(orch: ContextOrchestrator) -> dict:
    """与执行体同槽读折叠基线（不依赖本批新增接口，红/绿两态都可用）。"""
    slot = orch._window_compaction_cache.get(orch._resolve_window_cache_key()) or {}
    return {
        "last_fold_tokens": int(slot.get("last_fold_tokens") or 0),
        "last_fold_msgs": int(slot.get("last_fold_msgs") or 0),
    }


def _expectedDecision(history, budget_tokens: int, baseline: dict):
    """同输入重放单源判定——回执判读块必须与它一致。"""
    return decideFoldTrigger(
        total_tokens=estimate_window_tokens(history),
        budget_tokens=budget_tokens,
        last_fold_tokens=baseline["last_fold_tokens"],
        last_fold_msgs=baseline["last_fold_msgs"],
        total_msgs=len(history),
        foldable_msgs=max(0, len(history) - 6),
    )


def _effectiveBudget(orch: ContextOrchestrator) -> int:
    return orch._effectiveWindowBudget(orch._resolve_window_token_budget())


def _msgsForTarget(orch: ContextOrchestrator, targetRatio: float, minMsgs: int = 2) -> list:
    """按**有效预算**构造同构消息池，使占用落在 targetRatio 附近。

    预算会被生产侧硬顶钳制（`_effectiveWindowBudget`），故条数按实测有效预算
    反推（每条同构，窗口计量逐条线性），不假设测试能任意设定预算。
    """
    budget = _effectiveBudget(orch)
    perMsg = estimate_window_tokens([_long_msg(0)])
    n = max(minMsgs, int(round(targetRatio * budget / perMsg)))
    return [_long_msg(i) for i in range(n)]


class TestFoldTimingVerdict:
    """近阈 / 越阈两种池状态下，回执判读块与 decideFoldTrigger 判定一致。"""

    @pytest.mark.asyncio
    async def test_below_gate_state_reports_no_fold(self):
        agent = _mk_agent()
        orch = _mk_orchestrator(agent, budget=10**9)  # 有效预算落生产硬顶
        history = _msgsForTarget(orch, 0.3)  # 占用≈0.3 < 0.6 下限：门不触发
        agent.conversation_history = history
        executor = ToolExecutor(agent)

        status = await executor.execute_tool("context_status", {})

        ft = status.get("fold_timing")
        assert ft, "回执缺「折叠时机判读」块"
        expected = _expectedDecision(history, _effectiveBudget(orch), _slotBaseline(orch))
        assert not expected.should_fold and expected.reason == REASON_BELOW_FLOOR, (
            "池状态预朞性质错误（应处于下限之下）"
        )
        assert ft["should_fold"] == expected.should_fold
        assert ft["reason"] == expected.reason
        assert ft["criteria"]["occupancy"]["value"] == pytest.approx(expected.occupancy, abs=1e-4)
        assert ft["criteria"]["growth_tokens"]["value"] == expected.growth_tokens
        assert ft["criteria"]["growth_msgs"]["value"] == expected.growth_msgs

    @pytest.mark.asyncio
    async def test_over_gate_state_reports_growth_gate_fold(self):
        agent = _mk_agent()
        orch = _mk_orchestrator(agent, budget=10**9)
        history = _msgsForTarget(orch, 0.7, minMsgs=12)
        agent.conversation_history = history
        total = estimate_window_tokens(history)
        assert total >= 2000, "测试池 token 预期不足，增量门槛判据会失真"
        executor = ToolExecutor(agent)

        status = await executor.execute_tool("context_status", {})

        ft = status.get("fold_timing")
        assert ft, "回执缺「折叠时机判读」块"
        expected = _expectedDecision(history, _effectiveBudget(orch), _slotBaseline(orch))
        assert expected.should_fold and expected.reason == REASON_GROWTH_GATE, (
            f"池状态预朞性质错误（应处于增长门触发区）: occupancy="
            f"{expected.occupancy}, growth_tokens={expected.growth_tokens}"
        )
        assert ft["should_fold"] == expected.should_fold
        assert ft["reason"] == expected.reason
        assert ft["criteria"]["occupancy"]["value"] == pytest.approx(expected.occupancy, abs=1e-4)
        assert ft["criteria"]["growth_tokens"]["value"] == expected.growth_tokens
        assert ft["criteria"]["growth_msgs"]["value"] == expected.growth_msgs

    @pytest.mark.asyncio
    async def test_budget_breach_state_reports_breach_fold(self):
        agent = _mk_agent()
        orch = _mk_orchestrator(agent, budget=10**9)
        history = _msgsForTarget(orch, 1.2)  # 超有效预算：安全线直接折
        agent.conversation_history = history
        executor = ToolExecutor(agent)

        status = await executor.execute_tool("context_status", {})

        ft = status.get("fold_timing")
        assert ft, "回执缺「折叠时机判读」块"
        expected = _expectedDecision(history, _effectiveBudget(orch), _slotBaseline(orch))
        assert expected.should_fold and expected.reason == REASON_BUDGET_BREACH
        assert ft["should_fold"] == expected.should_fold
        assert ft["reason"] == expected.reason

    @pytest.mark.asyncio
    async def test_criteria_fields_complete_and_thresholds_from_single_source(self):
        """四判据各自读数齐备，阈值取自 fold_trigger 单源（不另抄一份）。"""
        agent = _mk_agent()
        orch = _mk_orchestrator(agent, budget=8000)
        history = [_long_msg(i) for i in range(14)]
        agent.conversation_history = history
        executor = ToolExecutor(agent)

        status = await executor.execute_tool("context_status", {})

        ft = status.get("fold_timing")
        assert ft, "回执缺「折叠时机判读」块"
        criteria = ft.get("criteria") or {}
        for key in ("occupancy", "growth_tokens", "growth_msgs", "foldable_msgs"):
            face = criteria.get(key)
            assert isinstance(face, dict), f"判据 {key} 缺读数面"
            assert {"value", "threshold", "met"} <= set(face), f"判据 {key} 字段不齐"
            assert isinstance(face["met"], bool)
        params = growthGateParams()
        budget = _effectiveBudget(orch)
        assert criteria["occupancy"]["threshold"] == params["floor"]
        assert criteria["growth_msgs"]["threshold"] == params["growth_min_msgs"]
        assert criteria["growth_tokens"]["threshold"] == max(
            params["growth_min_tokens"], int(budget * growthBudgetShare())
        )
        assert criteria["foldable_msgs"]["threshold"] == 6
        assert ft["criteria"]["foldable_msgs"]["value"] == max(0, len(history) - 6)
        assert "gate_enabled" in ft

    @pytest.mark.asyncio
    async def test_fold_baseline_from_session_slot_feeds_verdict(self):
        """有折叠基线时，增量按（当前-基线）计——回执与单源判定仍逐字一致。"""
        agent = _mk_agent()
        orch = _mk_orchestrator(agent, budget=10**9)
        history = _msgsForTarget(orch, 0.7, minMsgs=12)
        agent.conversation_history = history
        total = estimate_window_tokens(history)
        slot = orch._window_cache_slot(orch._resolve_window_cache_key())
        slot["last_fold_tokens"] = int(total * 0.5)
        slot["last_fold_msgs"] = 7
        executor = ToolExecutor(agent)

        status = await executor.execute_tool("context_status", {})

        ft = status.get("fold_timing")
        assert ft, "回执缺「折叠时机判读」块"
        expected = _expectedDecision(history, _effectiveBudget(orch), _slotBaseline(orch))
        assert ft["should_fold"] == expected.should_fold
        assert ft["reason"] == expected.reason
        assert ft["criteria"]["growth_tokens"]["value"] == expected.growth_tokens
        assert expected.growth_tokens == total - int(total * 0.5)


class TestFoldTimingMetacognition:
    @pytest.mark.asyncio
    async def test_meta_fields_present_populated_and_bounded(self):
        agent = _mk_agent()
        orch = _mk_orchestrator(agent, budget=8000)
        agent.conversation_history = [_long_msg(i) for i in range(3)]
        executor = ToolExecutor(agent)

        from neurova.cognitive_layers.meta_cognition_layer.self_model import (
            get_self_model_engine,
        )

        aid = agent.agent_id
        engine = get_self_model_engine(aid)
        ledger = engine.ledger
        # 反思在前（事件游标 0），事件在后 → 三条未编译；活跃/过期教训各一条。
        ledger.create_record(
            agent_id=aid, kind="reflection", type="monitoring", content="反思报告",
            metadata={"trigger": "manual", "last_event_id": 0},
        )
        for i in range(3):
            ledger.write_event(
                agent_id=aid, process_type="tool", description=f"tool_{i}", success=True
            )
        ledger.create_record(
            agent_id=aid, kind="lesson", type="monitoring", content="活跃教训",
            metadata={"subject": "x", "recommendation": "avoid_tool",
                      "expires_at": "2999-01-01T00:00:00+00:00"},
        )
        ledger.create_record(
            agent_id=aid, kind="lesson", type="monitoring", content="过期教训",
            metadata={"subject": "y", "recommendation": "avoid_tool",
                      "expires_at": "2000-01-01T00:00:00+00:00"},
        )

        status = await executor.execute_tool("context_status", {})

        ft = status.get("fold_timing")
        assert ft, "回执缺「折叠时机判读」块"
        meta = ft.get("metacognition")
        assert isinstance(meta, dict), "判读块缺元认知面"
        for key in (
            "uncompiled_events",
            "last_reflect_at",
            "seconds_since_last_reflect",
            "turn_count",
            "reflect_due",
            "active_lessons",
        ):
            assert key in meta, f"元认知字段缺失: {key}"
        assert meta["uncompiled_events"] == 3
        assert meta["active_lessons"] == 1, "过期教训不得计入活跃数"
        assert meta["last_reflect_at"]
        assert meta["seconds_since_last_reflect"] is not None
        assert isinstance(meta["reflect_due"], bool)

    @pytest.mark.asyncio
    async def test_block_bounded_by_named_constants(self):
        """长度纪律：判读块整体与文本字段均受具名常量约束。"""
        from neurova.tool_executor import (
            FOLD_TIMING_BLOCK_MAX_CHARS,
            FOLD_TIMING_TEXT_BOUND,
        )

        agent = _mk_agent()
        orch = _mk_orchestrator(agent, budget=8000)
        agent.conversation_history = [_long_msg(i) for i in range(5)]
        executor = ToolExecutor(agent)

        status = await executor.execute_tool("context_status", {})

        ft = status.get("fold_timing")
        assert ft, "回执缺「折叠时机判读」块"
        assert len(json.dumps(ft, ensure_ascii=False)) <= FOLD_TIMING_BLOCK_MAX_CHARS
        meta = ft.get("metacognition") or {}
        if meta.get("last_reflect_at"):
            assert len(str(meta["last_reflect_at"])) <= FOLD_TIMING_TEXT_BOUND
        assert len(str(ft.get("reason") or "")) <= FOLD_TIMING_TEXT_BOUND


class TestSchemaDescription:
    def test_context_status_schema_mentions_fold_timing(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        desc = _BUILTIN_SCHEMAS["context_status"]["description"]
        assert "折叠时机" in desc, "工具描述未同步折叠时机判读能力"
        assert "fold_timing" in desc
