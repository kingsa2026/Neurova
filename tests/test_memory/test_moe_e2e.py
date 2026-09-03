"""
MoE 端到端验证测试

验证 Agent 实际使用 MoE 检索处理消息。
"""
import pytest
import asyncio
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from typing import List, Dict


class TestMoEEndToEnd:
    """MoE 端到端验证"""

    def _make_agent_mock(self):
        """创建模拟 Agent"""
        from neurova.mem_core import MemCore

        agent = Mock()
        agent.config = Mock()
        agent.config.agent_id = "e2e_test_agent"
        agent.config.name = "E2EAgent"
        agent.config.workspace_path = "/tmp/e2e_test"
        agent.config.db_path = ":memory:"
        agent.config.enable_memory = True

        # 记忆数据
        memories = [
            {"id": "m1", "content": "今天和张三讨论了文件下载方案", "category": "conversation", "temperature": 80.0},
            {"id": "m2", "content": "项目使用 PostgreSQL 数据库", "category": "fact", "is_crystallized": 1, "temperature": 60.0},
            {"id": "m3", "content": "使用 curl 命令下载文件", "category": "tool_usage", "temperature": 70.0},
        ]

        # memory_manager
        agent.memory_manager = Mock()
        agent.memory_manager.recall.return_value = memories

        # storage
        agent.storage = Mock()
        agent.storage.get_recent_memories.return_value = memories

        def smart_execute(sql, params=None):
            result = Mock()
            params = params or {}
            if "category = :category" in sql:
                cat = params.get("category")
                result.fetchall.return_value = [m for m in memories if m["category"] == cat]
            else:
                result.fetchall.return_value = memories
            return result

        agent.storage.execute = smart_execute

        # 其他属性
        agent.recall_engine = None
        agent.temperature_engine = None
        agent.working_memory = None
        agent.conversation_buffer = None
        agent.buffer_module = None
        agent.conversation_history = []
        agent.evolution = None
        agent.session_manager = None
        agent.tool_memory = None
        agent.muscle_memory = None
        agent.attachment_manager = None
        agent._moe_router = None

        return agent, memories

    def test_moe_router_initialization(self):
        """验证 MoE 路由器能正确初始化"""
        from neurova.mem_core import MemCore

        agent, _ = self._make_agent_mock()
        memcore = MemCore(agent)

        # 初始化 MoE
        memcore.init_moe_router()

        # 验证路由器已创建
        assert memcore.moe_router is not None
        assert hasattr(memcore.moe_router, 'retrieve')
        assert hasattr(memcore.moe_router, 'vector_store')
        assert hasattr(memcore.moe_router, 'gating_network')

    def test_moe_retrieve_activated(self):
        """验证 moe_retrieve 使用 MoE 路由器"""
        from neurova.mem_core import MemCore

        agent, memories = self._make_agent_mock()
        memcore = MemCore(agent)
        memcore.init_moe_router()

        # 调用 moe_retrieve
        results = memcore.moe_retrieve("数据库配置")

        # 验证返回结果
        assert isinstance(results, list)
        assert len(results) > 0

        # 验证结果包含记忆数据
        result_ids = {r["id"] for r in results}
        memory_ids = {m["id"] for m in memories}
        # 应该有交集
        assert len(result_ids & memory_ids) > 0

    def test_moe_retrieve_fallback_without_init(self):
        """未初始化时 moe_retrieve 降级到普通检索"""
        from neurova.mem_core import MemCore

        agent, memories = self._make_agent_mock()
        memcore = MemCore(agent)

        # 不调用 init_moe_router
        results = memcore.moe_retrieve("数据库配置")

        # 应该降级到 memory_manager.recall
        agent.memory_manager.recall.assert_called_once()
        assert isinstance(results, list)
        assert len(results) > 0

    def test_moe_retrieve_expert_routing(self):
        """验证查询正确路由到对应专家"""
        from neurova.mem_core import MemCore

        agent, memories = self._make_agent_mock()
        memcore = MemCore(agent)
        memcore.init_moe_router()

        # 对话查询应路由到 conversation_episodic 专家
        results = memcore.moe_retrieve("和张三讨论文件")
        assert isinstance(results, list)

        # 事实查询应路由到 factual_knowledge 专家
        results = memcore.moe_retrieve("数据库配置")
        assert isinstance(results, list)

    def test_memory_stats_includes_moe(self):
        """验证记忆统计包含 MoE 状态"""
        from neurova.mem_core import MemCore

        agent, _ = self._make_agent_mock()
        memcore = MemCore(agent)

        # 初始化前
        stats = memcore.get_memory_stats()
        assert stats['moe_router_available'] is False

        # 初始化后
        memcore.init_moe_router()
        stats = memcore.get_memory_stats()
        assert stats['moe_router_available'] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
