"""
BE-CORE-001 (P0) 修复测试: asyncio.run() 在异步上下文中崩溃

问题: neurova/mem_core.py:582 `asyncio.run(moe.retrieve(...))` 在运行中的
事件循环内调用会抛 RuntimeError: asyncio.run() cannot be called from a
running event loop，导致 MoE 记忆检索完全失效。

TDD RED 阶段: 本测试在 buggy 代码下应失败（抛 RuntimeError）。
TDD GREEN 阶段: 修复后应通过。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.mem_core import MemCore


def _make_mem_core_with_moe(moe_retrieve_return=None):
    """构造一个带 mock MoE 路由器的 MemCore 实例。

    MoE 路由器的 retrieve 是 async 方法，返回指定结果。
    """
    mock_agent = MagicMock()
    mock_agent._moe_router = MagicMock()
    mock_agent._moe_router.retrieve = AsyncMock(
        return_value=moe_retrieve_return if moe_retrieve_return is not None else [
            {"id": "m1", "content": "hello"}
        ]
    )
    # flush_before_retrieve 依赖项置空，避免触发其他逻辑
    mock_agent.conversation_buffer = None
    mock_agent.buffer_module = None
    return MemCore(mock_agent), mock_agent


def test_moe_retrieve_in_async_context_does_not_crash():
    """moe_retrieve 在运行中的事件循环内调用不应抛 RuntimeError。

    复现: 在 async 函数（运行中的事件循环）内调用同步方法 moe_retrieve，
    其内部 asyncio.run() 应当安全处理，而不是崩溃。
    """
    mem_core, _ = _make_mem_core_with_moe(
        moe_retrieve_return=[{"id": "m1", "content": "hello"}]
    )

    async def call_inside_running_loop():
        # 此处处于运行中的事件循环内
        return mem_core.moe_retrieve("query", limit=5)

    # asyncio.run() 建立一个运行中的事件循环；
    # 内层 moe_retrieve 的 asyncio.run() 在 buggy 代码下会抛 RuntimeError
    results = asyncio.run(call_inside_running_loop())

    assert results == [{"id": "m1", "content": "hello"}]


def test_moe_retrieve_in_sync_context_still_works():
    """moe_retrieve 在无事件循环的同步上下文中应保留原有行为。"""
    mem_core, _ = _make_mem_core_with_moe(
        moe_retrieve_return=[{"id": "m2", "content": "sync-call"}]
    )

    # 直接同步调用，无运行中的事件循环
    results = mem_core.moe_retrieve("query", limit=3)

    assert results == [{"id": "m2", "content": "sync-call"}]


def test_moe_retrieve_returns_empty_list_when_moe_returns_empty():
    """MoE 返回空列表时应降级到普通检索（不崩溃）。"""
    mock_agent = MagicMock()
    mock_agent._moe_router = MagicMock()
    mock_agent._moe_router.retrieve = AsyncMock(return_value=[])
    mock_agent.conversation_buffer = None
    mock_agent.buffer_module = None
    # 降级路径: retrieve_memories 返回空
    mock_agent.recall_engine = None
    mock_agent.memory_manager = None
    mem_core = MemCore(mock_agent)

    async def call_inside_running_loop():
        return mem_core.moe_retrieve("query", limit=5)

    results = asyncio.run(call_inside_running_loop())
    assert isinstance(results, list)
