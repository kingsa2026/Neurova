#!/usr/bin/env python3
"""测试 MemoryRetrievalChain 集成"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock

# 模拟 Agent 类
class MockAgent:
    def __init__(self):
        self.config = Mock()
        self.memory_agent = Mock()
        self.context_orchestrator = Mock()
        self.tool_memory = Mock()
        self.skill_manager = Mock()
        self.tool_synthesizer = Mock()
        self.unified_retriever = Mock()
        self.crystallizer = Mock()
        self.trace_manager = Mock()
        self.neuHebb_manager = Mock()
        self.loop = Mock()
        self.llm_client = Mock()
        self.tool_executor = Mock()
        self.post_chat_pipeline = Mock()
        self.idle_tracker = Mock()
        
        # 模拟 UnifiedRetriever
        self.unified_retriever.retrieve = Mock(return_value=[
            {"content": "test memory 1", "score": 0.8},
            {"content": "test memory 2", "score": 0.6},
        ])
        
        # 模拟 memory_agent
        self.memory_agent.moe_router = Mock()
        self.memory_agent.moe_router.retrieve = Mock(return_value=[
            {"content": "moe memory 1", "score": 0.7},
        ])
        
        self.memory_agent.moe_retrieve = Mock(return_value=[
            {"content": "fallback memory 1", "score": 0.5},
        ])

async def test_memory_retrieval_chain_integration():
    """测试 MemoryRetrievalChain 集成"""
    from neurova.agent.chat_pipeline import ChatPipeline, ChatContext
    from neurova.agent.memory_retrieval_chain import MemoryRetrievalChain, RetrievalResult, RetrievalQuality
    
    # 创建模拟 Agent
    mock_agent = MockAgent()
    
    # 创建 ChatPipeline
    pipeline = ChatPipeline(mock_agent)
    
    # 验证 MemoryRetrievalChain 已初始化
    assert hasattr(pipeline, '_memory_retrieval_chain')
    assert isinstance(pipeline._memory_retrieval_chain, MemoryRetrievalChain)
    assert pipeline.memory_retrieval_chain is pipeline._memory_retrieval_chain
    
    print("✓ MemoryRetrievalChain 已正确初始化")
    
    # 验证检索器已添加
    retrievers = pipeline.memory_retrieval_chain.get_retrievers()
    assert len(retrievers) >= 2  # 至少有 UnifiedRetriever 和 CacheRetriever
    
    retriever_names = [r.name for r in retrievers]
    assert "UnifiedRetriever" in retriever_names
    assert "CacheRetriever" in retriever_names
    
    print(f"✓ 已添加 {len(retrievers)} 个检索器: {retriever_names}")
    
    # 创建测试上下文
    ctx = ChatContext(
        user_input="测试用户输入",
        session_id="test_session",
    )
    
    # 测试检索功能
    await pipeline._retrieve_memories(ctx)
    
    # 验证检索结果
    assert ctx.relevant_memories is not None
    assert len(ctx.relevant_memories) > 0
    
    print(f"✓ 检索成功，找到 {len(ctx.relevant_memories)} 条记忆")
    
    # 测试低质量场景（模拟 UnifiedRetriever 失败）
    mock_agent.unified_retriever.retrieve.side_effect = Exception("UnifiedRetriever failed")
    
    ctx2 = ChatContext(
        user_input="测试降级检索",
        session_id="test_session_2",
    )
    
    await pipeline._retrieve_memories(ctx2)
    
    # 应该降级到其他检索器
    assert ctx2.relevant_memories is not None
    print(f"✓ 降级检索成功，找到 {len(ctx2.relevant_memories)} 条记忆")
    
    # 测试统计信息
    stats = pipeline.memory_retrieval_chain.get_statistics()
    assert stats["total_retrievals"] >= 2
    assert stats["successful_retrievals"] >= 2
    
    print(f"✓ 统计信息正常: {stats}")
    
    print("\n🎉 MemoryRetrievalChain 集成测试通过！")

if __name__ == "__main__":
    asyncio.run(test_memory_retrieval_chain_integration())