# -*- coding: utf-8 -*-
"""B6-5：视图归一化必须保留工具寻址字段（P2-4 根因侧）。

红灯依据（改前实证）：

- 视图重建循环 `context.append({"role": …, "content": msg["content"]})` 只搬
  两个字段，`tool_call_id` / `name` 就地丢掉 → `_tool_placeholder` 生成的
  "硬地址指针"里 `call=` 恒为空，`recall_history(session_id, tool_call_id)`
  这条号称的直取路径在 pool 分支**不可能成立**（模型看到的是个残指针）；
- 归档侧却把 `tool_call_id` 写进了元数据（`_archive_conversation_to_pool`）
  ——写入有、读取无，正是断链形态。

契约（修复后）：

1. 视图重建保留 `tool_call_id` / `name`（emit 的消息带着它们）；
2. `_tool_placeholder` 因此能产出**非空**的 `call=` 硬地址；
3. 极短工具结果不占位（既有语义不变）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _agent():
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a-tool"
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
    agent.agent_id = "a-tool"
    agent.question_queue_manager = None
    return agent


async def _build(orch, **kwargs):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
        return await orch.build_context(**kwargs)


class TestPlaceholderCarriesHardAddress:
    def test_placeholder_contains_call_id(self):
        """占位串必须带上 call_id——它是 recall_history 的唯一寻址键。"""
        from neurova.context.orchestrator import ContextOrchestrator

        text = ContextOrchestrator._tool_placeholder(
            {"role": "tool", "tool_call_id": "call_abc123", "name": "read_file", "content": "x"}
        )
        assert "call=call_abc123" in text, f"占位串丢了硬地址（P2-4）：{text}"
        assert "tool=read_file" in text


class TestViewKeepsAddressingFields:
    @pytest.mark.asyncio
    async def test_built_view_keeps_tool_call_id_and_name(self):
        """端点/管线看到的工具消息必须带 tool_call_id 与 name。"""
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(_agent(), use_pool=True)
        session = [
            {"role": "user", "content": "读文件"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_abc123", "type": "function",
                     "function": {"name": "read_file", "arguments": "{}"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_abc123",
                "name": "read_file",
                "content": "长内容" * 200,
            },
        ]
        result = await _build(orch, user_input="继续", session_context=session)
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert tool_msgs, "工具消息被整体丢掉——本用例没打到视图重建路径"
        assert any(m.get("tool_call_id") for m in tool_msgs), (
            "视图重建剥掉了 tool_call_id：模型拿不到寻址键，"
            f"recall_history 直取不成立（P2-4）。实得：{tool_msgs[0].keys()}"
        )

    @pytest.mark.asyncio
    async def test_cleared_tool_result_keeps_hard_address(self):
        """占位清除后的工具消息仍带 call_id（寻址链闭合）。"""
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(_agent(), use_pool=True)
        # 窗口预算放大：本用例要打的是 microcompact（工具结果占位），不是
        # 整窗折叠——两者都会处理老工具结果，只有前者产占位指针。
        orch._window_token_budget = 400000
        orch._window_hard_limit = 400000
        session = [{"role": "user", "content": "读文件"}]
        for i in range(6):
            session.append(
                {"role": "assistant", "content": "",
                 "tool_calls": [{"id": f"call_{i}", "type": "function",
                                 "function": {"name": "read_file", "arguments": "{}"}}]}
            )
            session.append(
                {"role": "tool", "tool_call_id": f"call_{i}", "name": "read_file",
                 "content": f"第{i}段" + "长内容" * 1200}
            )
        result = await _build(orch, user_input="继续", session_context=session)
        placeholders = [m for m in result if "工具输出已移出上下文" in str(m.get("content", ""))]
        assert placeholders, "窗口未超阈值/未占位——本用例没打到 microcompact 路径"
        assert all("call=" in m["content"] and "call= " not in m["content"] for m in placeholders), (
            f"占位指针的硬地址为空（P2-4）：{[m['content'] for m in placeholders][:2]}"
        )
