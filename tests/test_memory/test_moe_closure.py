"""
MoE 闭环验证测试

验证记忆系统的写入→检索闭环：
1. 缓冲区 flush 后记忆可被 MoE 检索
2. 向量索引刷新后新记忆可见
3. 完整对话流程闭环
"""
import pytest
import asyncio
from unittest.mock import Mock, MagicMock
from typing import List, Dict


class TestMoEClosure:
    """MoE 闭环验证"""

    def _make_memcore(self):
        """创建带完整记忆系统的 MemCore"""
        from neurova.mem_core import MemCore

        agent = Mock()
        agent.config = Mock()
        agent.config.agent_id = "closure_test"
        agent.config.name = "ClosureAgent"
        agent.config.workspace_path = "/tmp/closure"
        agent.config.db_path = ":memory:"

        # 初始记忆
        initial_memories = [
            {"id": "m1", "content": "初始记忆", "category": "conversation", "temperature": 80.0},
        ]

        # storage 模拟
        agent.storage = Mock()
        agent.storage.get_recent_memories.return_value = initial_memories

        def smart_execute(sql, params=None):
            result = Mock()
            params = params or {}
            if "category = :category" in sql:
                cat = params.get("category")
                result.fetchall.return_value = [m for m in initial_memories if m["category"] == cat]
            else:
                result.fetchall.return_value = initial_memories
            return result

        agent.storage.execute = smart_execute

        # conversation_buffer 模拟
        agent.conversation_buffer = Mock()
        agent.conversation_buffer.is_full.return_value = True
        agent.conversation_buffer.flush_to_long_term_memory = Mock()

        # buffer_module 模拟
        agent.buffer_module = Mock()
        agent.buffer_module._write_queue = Mock()
        agent.buffer_module._write_queue.flush_to_storage.return_value = {"written": 1}

        # memory_manager
        agent.memory_manager = Mock()
        agent.memory_manager.recall.return_value = initial_memories

        # 其他属性
        agent.recall_engine = None
        agent.temperature_engine = None
        agent.working_memory = None
        agent.conversation_history = []
        agent.evolution = None
        agent.session_manager = None
        agent.tool_memory = None
        agent.muscle_memory = None
        agent.attachment_manager = None
        agent._moe_router = None

        return MemCore(agent), agent

    def test_flush_before_retrieve_calls_buffer(self):
        """flush_before_retrieve 应调用缓冲区 flush"""
        memcore, agent = self._make_memcore()

        memcore.flush_before_retrieve()

        # 验证缓冲区 flush 被调用
        agent.conversation_buffer.flush_to_long_term_memory.assert_called_once()
        # 验证写入队列 flush 被调用
        agent.buffer_module._write_queue.flush_to_storage.assert_called_once()

    def test_moe_retrieve_flushes_first(self):
        """moe_retrieve 应先 flush 缓冲区"""
        memcore, agent = self._make_memcore()
        memcore.init_moe_router()

        # 调用 moe_retrieve
        results = memcore.moe_retrieve("测试查询")

        # 验证 flush 被调用
        agent.conversation_buffer.flush_to_long_term_memory.assert_called_once()

    def test_refresh_moe_index_updates_vector_store(self):
        """refresh_moe_index 应更新向量存储"""
        memcore, agent = self._make_memcore()
        memcore.init_moe_router()

        # 添加新记忆
        new_memories = [
            {"id": "m1", "content": "旧记忆", "category": "conversation"},
            {"id": "m2", "content": "新记忆", "category": "fact"},
        ]
        agent.storage.get_recent_memories.return_value = new_memories

        # 刷新索引
        memcore.refresh_moe_index()

        # 验证向量存储被更新
        moe = memcore.moe_router
        assert moe is not None
        # 向量存储应该被重新索引
        assert len(moe.vector_store.memory_ids) == 2

    def test_full_conversation_loop(self):
        """完整对话流程闭环测试"""
        memcore, agent = self._make_memcore()
        memcore.init_moe_router()

        # 1. 保存对话记忆
        memcore.save_conversation_memory("用户问题", "AI回答")

        # 2. 检索（应先 flush）
        results = memcore.moe_retrieve("用户问题")

        # 验证闭环
        assert isinstance(results, list)
        agent.conversation_buffer.flush_to_long_term_memory.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
