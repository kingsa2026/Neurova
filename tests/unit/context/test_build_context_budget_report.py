"""N6 接线：build_context 装配时记录常驻分段预算。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.context.budget_report import getContextBudget, resetContextBudget
from neurova.context.orchestrator import ContextOrchestrator


@pytest.mark.asyncio
async def test_build_context_records_always_on_budget_report():
    resetContextBudget()
    mock_agent = MagicMock()
    mock_agent.config = MagicMock()
    mock_agent.config.name = "test_agent"
    mock_agent.config.agent_id = "test_agent"
    mock_agent.config.constitution = "宪法"
    mock_agent.config.behavior_rules = ["规则1", "规则2"]
    mock_agent.config.workspace_path = ""
    mock_agent.memory_manager = MagicMock()
    mock_agent.context_builder = MagicMock()
    mock_agent.tool_router = MagicMock()
    mock_agent._skill_registry = MagicMock()
    mock_agent.soul = "你是一个AI助手"
    mock_agent.personality = "友好、耐心"
    mock_agent.conversation_history = []
    mock_agent.growth_log_manager = MagicMock()
    mock_agent.user_id = "test_user"
    mock_agent.agent_id = "test_agent"

    orchestrator = ContextOrchestrator(mock_agent, use_pool=True, auto_tag=True)
    with patch.object(
        orchestrator, "get_tools_description", new_callable=AsyncMock
    ) as tools_desc:
        tools_desc.return_value = "可用工具：file_read"
        mock_context_builder = MagicMock()
        mock_context_builder.build_from_pool.return_value = [
            {"role": "system", "content": "系统指令"},
            {"role": "user", "content": "用户输入"},
        ]
        orchestrator._agent.context_builder = mock_context_builder
        await orchestrator.build_context(
            user_input="你好",
            tool_memory_result=None,
            auto_execute_result=None,
            tool_decision="do_not_execute",
            experience_items=[],
            relevant_memories=[],
            session_context=None,
        )

    report = getContextBudget("test_agent")
    assert report is not None
    names = {item["segment"] for item in report["segments"]}
    assert {"soul", "personality", "constitution", "rules", "tools"} <= names
    assert report["total_chars"] > 0
    resetContextBudget()
