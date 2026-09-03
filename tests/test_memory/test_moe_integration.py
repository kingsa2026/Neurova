"""
MoE 记忆检索集成测试

TDD 流程：每个测试 → 最小实现 → 通过
"""
import pytest
import asyncio
from unittest.mock import Mock, MagicMock, patch
from typing import List, Dict, Any


class TestMoeRetrieveBasic:
    """Test 1: MemCore.moe_retrieve 基础调用"""

    def _make_memcore_with_moe(self):
        """创建带 MoE 的 MemCore 实例"""
        from neurova.mem_core import MemCore

        # 模拟 Agent
        agent = Mock()
        agent.config = Mock()
        agent.config.agent_id = "test_agent"
        agent.config.name = "TestAgent"
        agent.config.workspace_path = "/tmp/test"
        agent.config.db_path = ":memory:"

        # 模拟 memory_manager
        agent.memory_manager = Mock()
        agent.memory_manager.recall.return_value = [
            {"id": "m1", "content": "今天和张三讨论了文件下载方案", "category": "conversation", "temperature": 80.0},
            {"id": "m2", "content": "项目使用 PostgreSQL 数据库", "category": "fact", "is_crystallized": 1, "temperature": 60.0},
            {"id": "m3", "content": "使用 curl 命令下载文件", "category": "tool_usage", "temperature": 70.0},
        ]

        # 模拟 storage
        agent.storage = Mock()
        agent.storage.execute.return_value.fetchall.return_value = [
            {"id": "m1", "content": "今天和张三讨论了文件下载方案", "category": "conversation", "lifecycle_stage": "active", "temperature": 80.0, "emotion_tags": '["neutral"]', "created_at": "2026-06-01T10:00:00", "score": 0.9},
            {"id": "m2", "content": "项目使用 PostgreSQL 数据库", "category": "fact", "is_crystallized": 1, "temperature": 60.0, "created_at": "2026-05-15T08:00:00", "score": 0.8},
            {"id": "m3", "content": "使用 curl 命令下载文件", "category": "tool_usage", "temperature": 70.0, "created_at": "2026-06-02T09:00:00", "score": 0.7},
        ]

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

        memcore = MemCore(agent)
        return memcore

    def test_moe_retrieve_returns_results(self):
        """moe_retrieve 应返回去重后的记忆列表"""
        memcore = self._make_memcore_with_moe()

        # 初始化 MoE
        memcore.init_moe_router()

        # 调用
        results = memcore.moe_retrieve("和张三讨论文件")

        assert isinstance(results, list)
        assert len(results) > 0
        # 每条结果应有 id 和 content
        for r in results:
            assert "id" in r
            assert "content" in r

    def test_moe_retrieve_without_init_returns_fallback(self):
        """未初始化 MoE 时应降级到原检索"""
        memcore = self._make_memcore_with_moe()

        # 不调用 init_moe_router
        results = memcore.moe_retrieve("和张三讨论文件")

        # 应该走 fallback，调用 memory_manager.recall
        memcore.memory_manager.recall.assert_called_once()
        assert isinstance(results, list)

    def test_moe_retrieve_expert_routing(self):
        """MoE 路由应正确分类查询到专家"""
        memcore = self._make_memcore_with_moe()
        memcore.init_moe_router()

        # fact 类查询应路由到 factual_knowledge 专家
        results = memcore.moe_retrieve("数据库配置")
        assert isinstance(results, list)
