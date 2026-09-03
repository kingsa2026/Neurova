"""
BE-CORE-008 (P0) 修复测试: 工具消息属性名错误

问题: neurova/tool_executor.py:198 将工具消息写入 `self._messages_list`
（ToolExecutor 实例的本地列表），但消费者（chat_pipeline.py:1054、
agent_core.py:1378、agent/loops/base.py）读取 `agent._tool_messages_list`，
属性名不匹配导致 LLM 上下文中看不到工具结果（数据丢失）。

TDD RED 阶段: 本测试在 buggy 代码下应失败（agent._tool_messages_list 为空）。
TDD GREEN 阶段: 修复后应通过。
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.tool_executor import ToolExecutor


def _make_executor_with_mock_agent():
    """构造一个 ToolExecutor，其 _execute_single_tool 被 mock 为返回固定结果。"""
    mock_agent = MagicMock()
    # 消费者在 chat_pipeline._init_agent_state 中会初始化 _tool_messages_list = []
    mock_agent._tool_messages_list = []
    executor = ToolExecutor(mock_agent)
    # mock _execute_single_tool 避免真实工具执行
    executor._execute_single_tool = AsyncMock(return_value={"status": "ok"})
    return executor, mock_agent


def test_tool_message_written_to_agent_tool_messages_list():
    """execute_text_tool_calls 应将 {role: tool} 消息写入 agent._tool_messages_list。

    消费者（chat_pipeline._collect_tool_messages）读取 agent._tool_messages_list，
    因此工具消息必须写入此属性，否则 LLM 上下文中看不到工具结果。
    """
    executor, mock_agent = _make_executor_with_mock_agent()

    tool_calls = [
        {
            "id": "call_001",
            "function": {
                "name": "search",
                "arguments": json.dumps({"query": "hello"}),
            },
        }
    ]

    # execute_text_tool_calls 是 async 方法
    asyncio.run(executor.execute_text_tool_calls(tool_calls))

    # 消费者读取 agent._tool_messages_list
    tool_msgs = mock_agent._tool_messages_list
    assert len(tool_msgs) == 1, f"期望 1 条工具消息，实际 {len(tool_msgs)} 条"
    msg = tool_msgs[0]
    assert msg["role"] == "tool"
    assert msg["tool_call_id"] == "call_001"
    # content 应包含工具结果
    assert "ok" in msg["content"] or "status" in msg["content"]


def test_tool_message_not_lost_in_executor_local_list_only():
    """工具消息不应只存在于 ToolExecutor._messages_list 中。

    buggy 行为: 消息写入 self._messages_list，消费者读取 agent._tool_messages_list，
    导致数据丢失。修复后消息应出现在 agent._tool_messages_list。
    """
    executor, mock_agent = _make_executor_with_mock_agent()

    tool_calls = [
        {
            "id": "call_002",
            "function": {
                "name": "weather",
                "arguments": json.dumps({"city": "北京"}),
            },
        }
    ]

    asyncio.run(executor.execute_text_tool_calls(tool_calls))

    # 消费者读取的属性必须有数据
    assert len(mock_agent._tool_messages_list) == 1


def test_multiple_tool_calls_all_recorded_in_agent_list():
    """多次工具调用的消息都应写入 agent._tool_messages_list。"""
    executor, mock_agent = _make_executor_with_mock_agent()

    tool_calls = [
        {
            "id": "call_a",
            "function": {"name": "search", "arguments": "{}"},
        },
        {
            "id": "call_b",
            "function": {"name": "weather", "arguments": "{}"},
        },
    ]

    asyncio.run(executor.execute_text_tool_calls(tool_calls))

    assert len(mock_agent._tool_messages_list) == 2
    ids = [m["tool_call_id"] for m in mock_agent._tool_messages_list]
    assert "call_a" in ids
    assert "call_b" in ids


def test_agent_tool_messages_list_lazy_initialized():
    """若 agent 未预初始化 _tool_messages_list，应懒初始化而非崩溃。"""
    mock_agent = MagicMock()
    # 不预初始化 _tool_messages_list，模拟 loops/base.py 的懒初始化场景
    del mock_agent._tool_messages_list
    executor = ToolExecutor(mock_agent)
    executor._execute_single_tool = AsyncMock(return_value={"status": "ok"})

    tool_calls = [
        {
            "id": "call_lazy",
            "function": {"name": "search", "arguments": "{}"},
        }
    ]

    asyncio.run(executor.execute_text_tool_calls(tool_calls))

    # 修复应懒初始化并写入消息
    assert hasattr(mock_agent, "_tool_messages_list")
    assert len(mock_agent._tool_messages_list) == 1
