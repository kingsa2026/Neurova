"""
上下文功能 Bug 修复 RED 测试 — C-2（chat_pipeline 模块）

C-2: chat_pipeline.py:596 user_id 永远 None
    根本原因：ChatContext dataclass 无 user_id 字段，getattr(ctx, "user_id", None) 永远返回 None
    对比正确写法：同文件 line 283 用 (ctx.metadata or {}).get("user_id", "anonymous")
    影响：多用户场景下记忆检索无法按 user_id 隔离
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestC2RetrieveMemoriesUserIdFromMetadata:
    """C-2: _retrieve_memories 应从 ctx.metadata 取 user_id，而非 getattr(ctx, "user_id", None)"""

    @pytest.mark.asyncio
    async def test_c2_user_id_from_metadata(self):
        """RED: metadata 含 user_id 时，RetrievalContext.user_id 应为该值

        Bug C-2: chat_pipeline.py:596
        实际代码: user_id=getattr(ctx, "user_id", None)  # 永远 None
        正确写法: user_id=(ctx.metadata or {}).get("user_id", "anonymous")
        """
        from neurova.agent.chat_pipeline import ChatContext, ChatPipeline

        # 构造 mock agent
        mock_agent = MagicMock()
        # ChatPipeline.__init__ 会访问多个属性，用 MagicMock 自动生成
        mock_agent.unified_retriever = None
        mock_agent.memory_agent = None
        mock_agent.crystallizer = None

        pipeline = ChatPipeline(mock_agent)

        # 构造含 user_id 的 ChatContext
        ctx = ChatContext(
            user_input="测试查询",
            metadata={"user_id": "alice"},
        )

        # mock memory_retrieval_chain 捕获 RetrievalContext
        captured_contexts = []

        async def mock_retrieve(retrieval_context):
            captured_contexts.append(retrieval_context)
            mock_result = MagicMock()
            mock_result.memories = []
            mock_result.source = "mock"
            mock_result.quality_level = MagicMock()
            mock_result.quality_level.value = "high"
            return mock_result

        pipeline._memory_retrieval_chain = MagicMock()
        pipeline._memory_retrieval_chain.retrieve = mock_retrieve
        # trace_manager 是 property，通过 mock_agent 设置
        mock_agent.trace_manager = None

        await pipeline._retrieve_memories(ctx)

        # 验证 RetrievalContext.user_id
        assert len(captured_contexts) == 1, "应调用 retrieve 一次"
        actual_user_id = captured_contexts[0].user_id
        assert actual_user_id == "alice", (
            f"RED C-2: user_id 应从 metadata 取 'alice'，实际 '{actual_user_id}'（bug: getattr 永远返回 None）"
        )

    @pytest.mark.asyncio
    async def test_c2_user_id_default_when_metadata_missing(self):
        """RED: metadata 缺失时 user_id 应有合理默认值"""
        from neurova.agent.chat_pipeline import ChatContext, ChatPipeline

        mock_agent = MagicMock()
        mock_agent.unified_retriever = None
        mock_agent.memory_agent = None
        mock_agent.crystallizer = None

        pipeline = ChatPipeline(mock_agent)

        ctx = ChatContext(user_input="测试", metadata=None)

        captured_contexts = []

        async def mock_retrieve(retrieval_context):
            captured_contexts.append(retrieval_context)
            mock_result = MagicMock()
            mock_result.memories = []
            mock_result.source = "mock"
            mock_result.quality_level = MagicMock()
            mock_result.quality_level.value = "high"
            return mock_result

        pipeline._memory_retrieval_chain = MagicMock()
        pipeline._memory_retrieval_chain.retrieve = mock_retrieve
        mock_agent.trace_manager = None

        await pipeline._retrieve_memories(ctx)

        actual_user_id = captured_contexts[0].user_id
        # 不应是 None（应有默认值），也不应抛异常
        assert actual_user_id is not None, (
            f"RED C-2: metadata 缺失时 user_id 应有默认值，实际 None"
        )
