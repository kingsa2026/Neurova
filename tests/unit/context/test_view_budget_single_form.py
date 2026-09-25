# -*- coding: utf-8 -*-
"""B6-9：抽屉额度形态收口——构造期值与每轮值的关系单一可解释（Issue #90 · P2-6）。

红灯依据（改前实证，审计 §2.1 P2-6）：

- 抽屉的构造期额度（池预算）**每轮被就地改写**：
  `orchestrator.build_context` 里 `drawer.max_tokens = self._retrievalBudget(...)`。
  于是同一个字段在不同时刻含义不同：装配期是"池预算"，之后是"本轮窗口剩余"，
  而调用方无法分辨手里这个值是哪一个（审计实测 `76800 → 24575`）。
- `_retrievalBudget` 用的 `window_budget` 未经 90% 硬顶钳制，而 `_apply_window_budget`
  内部会钳——同一轮里两处对"窗口预算"理解不一致（钳制口径分裂）。

契约（修复后）：

1. 每轮额度是**入参**，不是对构造期字段的就地改写：建完上下文后
   `drawer.max_tokens` 仍是构造期值（不再被覆写）；
2. 生效额度只有一处解释：本轮入参优先，缺省才回落构造期默认；
3. 参与召回额度计算与窗口裁剪的"窗口预算"是**同一个**（都过 90% 硬顶）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.semantic_drawer import SemanticMatchDrawer


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


async def _build(orch, **kwargs):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
        return await orch.build_context(
            user_input=kwargs.pop("user_input", "问题"),
            session_context=kwargs.pop("session_context", [{"role": "user", "content": "短历史"}]),
            **kwargs,
        )


class TestNoInPlaceOverwrite:
    @pytest.mark.asyncio
    async def test_construction_budget_not_overwritten(self):
        """每轮额度不得就地改写构造期字段（改前 `drawer.max_tokens` 每轮被覆盖）。"""
        orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
        drawer = orch.context_pool._drawer
        constructionBudget = drawer.max_tokens

        await _build(orch)

        assert drawer.max_tokens == constructionBudget, (
            f"构造期额度 {constructionBudget} 被就地改写为 {drawer.max_tokens} —— "
            "同一个字段在不同时刻含义不同，调用方无从分辨"
        )

    @pytest.mark.asyncio
    async def test_turn_budget_is_readable_and_effective(self):
        """本轮额度必须可读，且等于本轮真用的那个值（不是"写过就丢"）。"""
        orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
        drawer = orch.context_pool._drawer
        seen = {"values": []}
        original = orch._retrievalBudget

        def spy(*args, **kwargs):
            value = original(*args, **kwargs)
            seen["values"].append(value)
            return value

        with patch.object(orch, "_retrievalBudget", spy):
            await _build(orch)

        assert seen["values"], "本轮没有走召回额度计算"
        assert drawer.effective_view_budget() in seen["values"], (
            f"本轮生效额度 {drawer.effective_view_budget()} 不在额度方法的取值集 {seen['values']} 里"
        )


class TestSingleExplanation:
    def test_default_when_no_turn_budget(self):
        """缺省解释：没有本轮入参时生效额度就是构造期默认（单一解释，不是两个值并存）。"""
        drawer = SemanticMatchDrawer(max_tokens=12345)

        assert drawer.effective_view_budget() == 12345

    def test_turn_budget_wins_over_construction(self):
        """有本轮入参时以入参为准；构造期值不再参与本轮计算。"""
        drawer = SemanticMatchDrawer(max_tokens=12345)

        drawer.draw(
            [ContextInput(source=ContextSource.MEMORY, content="条目", priority=60, tokens=5)],
            need="",
            budget_tokens=999,
        )

        assert drawer.effective_view_budget() == 999

    def test_pool_threads_turn_budget_to_drawer(self):
        """池的额度入参透传到抽屉（唯一通道，不在池侧另存一份）。"""
        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u1", agent_id="a1", session_id=None, ttl_seconds=0)
        pool.add_context(ContextInput(source=ContextSource.MEMORY, content="条目", priority=60, tokens=5))

        pool.draw(need="", budget_tokens=777)

        assert pool._drawer.effective_view_budget() == 777

    def test_budget_change_takes_effect_on_selection(self):
        """额度是真生效的：同一批条目录入不同额度，入选内容不同（不是只记账）。"""
        entries = [
            ContextInput(source=ContextSource.MEMORY, content="甲" * 4000, priority=60, tokens=900)
        ]

        whole = SemanticMatchDrawer(max_tokens=10 ** 6).draw(entries, need="", budget_tokens=10 ** 6)
        limited = SemanticMatchDrawer(max_tokens=10 ** 6).draw(entries, need="", budget_tokens=500)

        assert whole[0].content == "甲" * 4000, "宽额度下不该截断"
        assert limited[0].content != whole[0].content, (
            f"窄额度（500）与宽额度（10^6）选出同一条内容 —— 本轮额度没有参与选取"
        )
        assert limited[0].tokens < whole[0].tokens or whole[0].tokens == 0


class TestWindowBudgetClampShared:
    @pytest.mark.asyncio
    async def test_retrieval_budget_uses_clamped_window(self):
        """召回额度用的窗口预算必须与窗口裁剪同一个（都过 90% 硬顶）。"""
        orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
        orch._window_token_budget = 20000
        orch._window_hard_limit = 5000

        await _build(orch)

        effective = orch.context_pool._drawer.effective_view_budget()
        assert effective <= 5000, (
            f"召回额度 {effective} 超过了硬顶后的窗口预算 5000 —— "
            "召回侧用的是未钳制的 20000，两处对'窗口预算'理解不一致"
        )

    def test_helper_matches_apply_window_budget_clamp(self):
        """钳制只有一处实现：helper 与 `_apply_window_budget` 内部取同一个硬顶。"""
        orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
        orch._window_hard_limit = 4000

        assert orch._effectiveWindowBudget(9000) == 4000
        assert orch._effectiveWindowBudget(3000) == 3000
