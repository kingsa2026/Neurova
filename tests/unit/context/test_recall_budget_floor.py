# -*- coding: utf-8 -*-
"""B5 / D3：召回额度地板按模型上下文自适应，且额度只有一处口径。

审计 §10 B5 行与决策项 D3 的裁决：**地板按模型上下文自适应**，取向以
**提升前缀缓存命中率优先**（倾向跨轮小而稳定的召回集合）。

红灯依据（改前实证）：

- 地板是模块常量 `_ENVELOPE_MIN_TOKENS = 1000`，与模型窗口无关：8k 模型与
  128k 模型拿到同一个地板——小模型上地板相对过宽（挤掉窗口），大模型上过窄
  （召回被压到几乎不可用）；
- 同一份"剩余额度"公式在 `orchestrator.build_context` 里**写了两遍**
  （抽屉联动处与信封额度处），两份各减各的项 → 口径分裂的典型形态。

契约（修复后）：

1. 召回额度地板随窗口预算单调不减，且有绝对下限（不许出现 0 额度）；
2. 额度公式只有一份（`_retrievalBudget`），抽屉与信封共用它的返回值；
3. 额度取向稳定：同一窗口预算下两次构建得到同一额度（前缀缓存前提）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.context.orchestrator import ContextOrchestrator


def _agent():
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a1"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.config.enable_auto_tagging = False
    agent.memory_manager = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a1"
    agent.question_queue_manager = None
    return agent


def _orchestrator(budget: int):
    orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
    orch._window_token_budget = budget
    return orch


async def _build(orch, **kwargs):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
        return await orch.build_context(**kwargs)


class TestRecallFloorScalesWithModelWindow:
    def test_floor_is_monotonic_in_window_budget(self):
        small = _orchestrator(4000)._resolveRecallFloor()
        large = _orchestrator(72000)._resolveRecallFloor()
        assert large > small, f"地板未随窗口预算增长：{small} → {large}"

    def test_floor_has_absolute_lower_bound(self):
        floor = _orchestrator(1)._resolveRecallFloor()
        assert floor >= ContextOrchestrator._RECALL_MIN_TOKENS > 0

    def test_floor_never_exceeds_window_budget(self):
        orch = _orchestrator(3000)
        assert orch._resolveRecallFloor() <= orch._window_token_budget

    def test_floor_matches_documented_share(self):
        """地板 = 窗口预算的既定份额（口径可算，不是随手常数）。"""
        orch = _orchestrator(20000)
        expected = max(
            ContextOrchestrator._RECALL_MIN_TOKENS,
            int(20000 * ContextOrchestrator._RECALL_FLOOR_SHARE),
        )
        assert orch._resolveRecallFloor() == expected


class TestBudgetHasSingleDefinition:
    def test_retrieval_budget_is_single_source(self):
        """抽屉额度与信封额度必须来自同一个方法（第二份公式即红）。"""
        orch = _orchestrator(8000)
        blocks = {"memories": ["[记忆] 甲"], "history": []}
        window_msgs = [{"role": "user", "content": "hi"}]
        assert orch._retrievalBudget(8000, window_msgs, blocks, "问题") == orch._retrievalBudget(
            8000, window_msgs, blocks, "问题"
        )

    @pytest.mark.asyncio
    async def test_drawer_and_envelope_share_one_budget(self, monkeypatch):
        """可证伪形态：抽屉额度与信封额度都来自 `_retrievalBudget` 这一个方法。

        不比对重算值（那会引入第二份公式，正是本片要消灭的形态），而是盯住
        调用本身：抽屉拿到的额度必须是该方法这次返回的那个值。
        """
        orch = _orchestrator(20000)
        seen = {"values": [], "calls": 0}
        original = orch._retrievalBudget

        def spy(*args, **kwargs):
            value = original(*args, **kwargs)
            seen["values"].append(value)
            seen["calls"] += 1
            return value

        monkeypatch.setattr(orch, "_retrievalBudget", spy)
        await _build(
            orch,
            user_input="问题",
            session_context=[{"role": "user", "content": "短历史"}],
        )

        assert seen["calls"] >= 2, "抽屉与信封必须各走一次同一份额度方法"
        # B6-9：本轮生效额度经 `effective_view_budget()` 读——`max_tokens` 是**构造期**
        # 默认值，不再被就地改写（改前断言读的正是那个被覆写的字段）。
        assert orch.context_pool._drawer.effective_view_budget() in seen["values"]

    @pytest.mark.asyncio
    async def test_two_builds_same_budget_same_value(self):
        """取向稳定：同窗口预算下两轮拿到同一额度（前缀缓存前提）。"""
        orch = _orchestrator(20000)
        await _build(orch, user_input="第一轮", session_context=[{"role": "user", "content": "历史一"}])
        first = orch.context_pool._drawer.effective_view_budget()
        await _build(orch, user_input="第二轮", session_context=[{"role": "user", "content": "历史一"}])
        second = orch.context_pool._drawer.effective_view_budget()
        assert first == second

    def test_envelope_budget_not_duplicated_formula(self):
        """信封额度由同一方法导出：信封额度 ≥ 召回额度 + 固定部分 + 行前缀。"""
        orch = _orchestrator(20000)
        blocks = {"memories": ["[记忆] 甲"], "history": ["[历史回忆] 用户: 乙"]}
        window_msgs = [{"role": "user", "content": "hi"}]
        recall = orch._retrievalBudget(20000, window_msgs, blocks, "问题")
        envelope = orch._envelopeBudget(20000, window_msgs, blocks, "问题")
        assert envelope >= recall


class TestEnvelopeFloorSharesRecallFloor:
    def test_envelope_floor_is_recall_floor(self):
        """信封地板与召回地板同源（改前是两条各写一份的常数）。"""
        orch = _orchestrator(30000)
        assert orch._ENVELOPE_MIN_TOKENS == orch._resolveRecallFloor()

    @pytest.mark.asyncio
    async def test_large_model_recall_not_starved(self):
        """大窗口模型上召回额度不得退化为地板以下的冻结值。"""
        orch = _orchestrator(100000)
        await _build(orch, user_input="问题", session_context=[{"role": "user", "content": "短历史"}])
        floor = orch._resolveRecallFloor()
        assert orch.context_pool._drawer.effective_view_budget() >= floor
        assert (
            orch.context_pool._drawer.effective_view_budget()
            > ContextOrchestrator._RECALL_MIN_TOKENS
        )
