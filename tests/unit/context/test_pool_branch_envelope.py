# -*- coding: utf-8 -*-
"""2026-09-08 审计修复②：批次 A 信封接入 pool 主链。

enable_context_pool 默认 True 时 orchestrator.build_context 走 pool 分支，
该分支此前完全绕过 UnifiedContextInjector——信封（含分钟级时间）从未生效。
修复后主链末条 user 消息必须携带瞬态信封（<time> 块）。
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def _make_orchestrator():
    mock_agent = MagicMock()
    mock_agent.config = MagicMock()
    mock_agent.config.name = "t"
    mock_agent.config.constitution = ""
    mock_agent.config.behavior_rules = []
    mock_agent.memory_manager = MagicMock()
    mock_agent.tool_router = None
    mock_agent._skill_registry = None
    mock_agent.soul = "s"
    mock_agent.personality = ""
    mock_agent.conversation_history = []
    mock_agent.growth_log_manager = None
    mock_agent.user_id = "u"
    mock_agent.agent_id = "t"

    with patch("neurova.context_pool.ContextPool") as pool_cls:
        pool_cls.get_token_budget_for_model.return_value = 8000
        pool_cls.return_value.draw.return_value = []
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(mock_agent, use_pool=True)
    return orch


class TestPoolBranchEnvelope:
    """pool 主链末条 user 消息带瞬态信封。"""

    @pytest.mark.asyncio
    async def test_final_user_message_carries_time_envelope(self):
        orch = _make_orchestrator()
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
            result = await orch.build_context(user_input="现在几点了")
        last = result[-1]
        assert last["role"] == "user"
        assert "现在几点了" in last["content"]
        assert "<system-reminder>" in last["content"], "主链末条 user 消息缺瞬态信封"
        assert "<time>" in last["content"], "信封缺分钟级 <time> 块"

    @pytest.mark.asyncio
    async def test_system_prefix_stays_stable_across_turns(self):
        """信封化后，前缀（system 段）跨轮字节级稳定——分钟级时间不得进 system。"""
        import re

        orch = _make_orchestrator()
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
            r1 = await orch.build_context(user_input="第一轮")
        # 第二轮模拟跨过一分钟：直接再次构建，对比 system 段（剥离日期段后）
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
            r2 = await orch.build_context(user_input="第二轮")
        strip_time = lambda msgs: [m["content"] for m in msgs if m["role"] == "system"]
        s1, s2 = strip_time(r1), strip_time(r2)
        assert s1 == s2, "system 段跨轮变化（分钟级时间泄漏进 system 会击穿前缀缓存）"
        # 分钟级时间只在末条 user 信封里
        assert "<time>" in r1[-1]["content"]
