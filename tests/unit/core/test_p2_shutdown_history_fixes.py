"""
P2 修复测试（2026-08 代码审计）

覆盖 bug:
1. agent_shutdown.shutdown_agent 对同步方法执行 `await conversation_buffer.flush()`:
   flush() 返回 List[MemoryItem]，await list 抛 TypeError 被 except 吞掉，
   且已刷出的记忆项被丢弃 → 关闭时对话缓冲数据丢失。
   修复: 同步 flush + enqueue 到 memory_manager._write_queue + flush_to_storage() 持久化。
2. Agent.clear_history() 只清空 conversation_history 列表，不清空 _conversation_context;
   MemCore.update_history 的同步步骤 `if current_list and ...` 在列表为空时 falsy 跳过,
   旧上下文在下次 update 时复活已清空的历史。
   修复: 同步条件不再依赖 truthiness; clear_history 同时清空 context。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from neurova.agent_shutdown import shutdown_agent
from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationBuffer
from neurova.conversation_context import ConversationContext
from neurova.mem_core import MemCore


def _make_shutdown_agent(buffer, queue):
    return SimpleNamespace(
        config=SimpleNamespace(name="test-agent"),
        conversation_buffer=buffer,
        memory_manager=SimpleNamespace(_write_queue=queue) if queue is not None else None,
    )


class TestShutdownBufferFlush:
    @pytest.mark.asyncio
    async def test_shutdown_persists_buffered_items(self):
        buf = ConversationBuffer()
        buf.add_user_message("hello")
        buf.add_agent_message("hi there")
        queue = MagicMock()

        await shutdown_agent(_make_shutdown_agent(buf, queue))

        queue.enqueue_batch.assert_called_once()
        items = queue.enqueue_batch.call_args[0][0]
        assert len(items) == 2, "缓冲的 2 条消息必须入队持久化，不能丢弃"
        queue.flush_to_storage.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_empty_buffer_no_enqueue(self):
        buf = ConversationBuffer()
        queue = MagicMock()

        await shutdown_agent(_make_shutdown_agent(buf, queue))

        queue.enqueue_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_shutdown_without_write_queue_does_not_raise(self):
        buf = ConversationBuffer()
        buf.add_user_message("hello")

        await shutdown_agent(_make_shutdown_agent(buf, None))

        assert buf.flush() == [], "无写入队列时缓冲也应被排空且不抛异常"


class TestClearHistoryNoResurrection:
    def _make_mem_core(self):
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        mock_agent.conversation_history = []
        mock_agent._conversation_context = ConversationContext(max_messages=100)
        return MemCore(mock_agent), mock_agent

    def test_update_after_external_clear_does_not_resurrect(self):
        mc, mock_agent = self._make_mem_core()
        mc.update_history("old q", "old a")
        assert len(mc.conversation_history) == 2

        mock_agent.conversation_history = []
        mc.update_history("new q", "new a")

        assert len(mc.conversation_history) == 2, "清空后旧历史不得复活"
        assert mc.conversation_history[0]["content"] == "new q"

    def test_agent_clear_history_clears_context(self):
        from neurova.agent_core import Agent

        mc, mock_agent = self._make_mem_core()
        mc.update_history("old q", "old a")

        Agent.clear_history(mock_agent)

        assert mock_agent.conversation_history == []
        assert len(mock_agent._conversation_context) == 0, (
            "clear_history 必须同时清空 _conversation_context，"
            "否则下次 update_history 时旧上下文复活"
        )

        mc.update_history("new q", "new a")
        assert len(mc.conversation_history) == 2
