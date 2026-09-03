"""MemoryRetrievalChain 单元测试"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from datetime import datetime, timezone

from neurova.agent.memory_retrieval_chain import (
    MemoryRetrievalChain,
    RetrievalResult,
    RetrievalContext,
    RetrievalQuality,
    RetrievalStrategy,
)


class TestRetrievalQuality:
    """测试 RetrievalQuality 枚举"""
    
    def test_retrieval_quality_values(self):
        """测试枚举值"""
        assert RetrievalQuality.EXCELLENT.value == "excellent"
        assert RetrievalQuality.GOOD.value == "good"
        assert RetrievalQuality.FAIR.value == "fair"
        assert RetrievalQuality.POOR.value == "poor"
        assert RetrievalQuality.FAILED.value == "failed"
    
    def test_retrieval_quality_is_enum(self):
        """测试是否为枚举"""
        from enum import Enum
        assert issubclass(RetrievalQuality, Enum)


class TestRetrievalStrategy:
    """测试 RetrievalStrategy 枚举"""
    
    def test_retrieval_strategy_values(self):
        """测试枚举值"""
        assert RetrievalStrategy.CHAIN.value == "chain"
        assert RetrievalStrategy.PARALLEL.value == "parallel"
        assert RetrievalStrategy.BEST.value == "best"
        assert RetrievalStrategy.FALLBACK.value == "fallback"


class TestRetrievalResult:
    """测试 RetrievalResult 数据类"""
    
    def test_result_creation(self):
        """测试创建结果"""
        result = RetrievalResult(
            memories=[{"content": "test"}],
            source="test_source",
            quality=0.8,
            quality_level=RetrievalQuality.GOOD,
            retrieval_time=0.1,
        )
        
        assert len(result.memories) == 1
        assert result.source == "test_source"
        assert result.quality == 0.8
        assert result.quality_level == RetrievalQuality.GOOD
        assert result.retrieval_time == 0.1
    
    def test_result_to_dict(self):
        """测试转换为字典"""
        result = RetrievalResult(
            memories=[{"content": "test"}],
            source="test_source",
            quality=0.8,
            quality_level=RetrievalQuality.GOOD,
            retrieval_time=0.1,
            metadata={"key": "value"},
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["memories"] == [{"content": "test"}]
        assert result_dict["source"] == "test_source"
        assert result_dict["quality"] == 0.8
        assert result_dict["quality_level"] == "good"
        assert result_dict["retrieval_time"] == 0.1
        assert result_dict["metadata"] == {"key": "value"}
        assert "timestamp" in result_dict


class TestRetrievalContext:
    """测试 RetrievalContext 数据类"""
    
    def test_context_creation(self):
        """测试创建上下文"""
        context = RetrievalContext(query="test query")
        
        assert context.query == "test query"
        assert context.limit == 10
        assert context.user_id is None
        assert context.session_id is None
        assert context.strategy == RetrievalStrategy.CHAIN
        assert context.min_quality == 0.3
    
    def test_context_custom_values(self):
        """测试自定义值"""
        context = RetrievalContext(
            query="custom query",
            limit=5,
            user_id="user123",
            session_id="session456",
            strategy=RetrievalStrategy.PARALLEL,
            min_quality=0.5,
            metadata={"key": "value"},
        )
        
        assert context.query == "custom query"
        assert context.limit == 5
        assert context.user_id == "user123"
        assert context.session_id == "session456"
        assert context.strategy == RetrievalStrategy.PARALLEL
        assert context.min_quality == 0.5
        assert context.metadata == {"key": "value"}


class MockRetriever:
    """模拟检索器"""
    
    def __init__(self, name, priority, memories=None, quality=0.8, should_fail=False):
        self._name = name
        self._priority = priority
        self._memories = memories or []
        self._quality = quality
        self._should_fail = should_fail
    
    @property
    def name(self):
        return self._name
    
    @property
    def priority(self):
        return self._priority
    
    async def retrieve(self, context):
        if self._should_fail:
            raise Exception(f"Retriever {self._name} failed")
        
        return RetrievalResult(
            memories=self._memories,
            source=self._name,
            quality=self._quality,
            quality_level=self._quality_from_score(self._quality),
            retrieval_time=0.1,
        )
    
    def get_quality_score(self, memories, query):
        return self._quality
    
    def _quality_from_score(self, score):
        if score >= 0.9:
            return RetrievalQuality.EXCELLENT
        elif score >= 0.7:
            return RetrievalQuality.GOOD
        elif score >= 0.5:
            return RetrievalQuality.FAIR
        elif score >= 0.3:
            return RetrievalQuality.POOR
        else:
            return RetrievalQuality.FAILED


class TestMemoryRetrievalChain:
    """测试 MemoryRetrievalChain"""
    
    def setup_method(self):
        """每个测试方法前重置"""
        self.chain = MemoryRetrievalChain()
    
    def test_initialization(self):
        """测试初始化"""
        chain = MemoryRetrievalChain()
        
        assert chain._retrievers == []
        assert chain._cache == {}
        assert chain._statistics["total_retrievals"] == 0
        assert chain._statistics["successful_retrievals"] == 0
        assert chain._statistics["failed_retrievals"] == 0
        assert chain._statistics["cache_hits"] == 0
        assert chain._statistics["average_quality"] == 0.0
    
    def test_add_retriever(self):
        """测试添加检索器"""
        retriever = MockRetriever("test_retriever", 10)
        
        self.chain.add_retriever(retriever)
        
        assert len(self.chain._retrievers) == 1
        assert self.chain._retrievers[0].name == "test_retriever"
    
    def test_add_retriever_priority_order(self):
        """测试按优先级添加检索器"""
        retriever1 = MockRetriever("low_priority", 30)
        retriever2 = MockRetriever("high_priority", 10)
        retriever3 = MockRetriever("medium_priority", 20)
        
        self.chain.add_retriever(retriever1)
        self.chain.add_retriever(retriever2)
        self.chain.add_retriever(retriever3)
        
        assert len(self.chain._retrievers) == 3
        assert self.chain._retrievers[0].name == "high_priority"
        assert self.chain._retrievers[1].name == "medium_priority"
        assert self.chain._retrievers[2].name == "low_priority"
    
    def test_remove_retriever(self):
        """测试移除检索器"""
        retriever = MockRetriever("test_retriever", 10)
        self.chain.add_retriever(retriever)
        
        result = self.chain.remove_retriever("test_retriever")
        
        assert result is True
        assert len(self.chain._retrievers) == 0
    
    def test_remove_retriever_not_found(self):
        """测试移除不存在的检索器"""
        result = self.chain.remove_retriever("nonexistent")
        
        assert result is False
    
    def test_get_retrievers(self):
        """测试获取检索器列表"""
        retriever1 = MockRetriever("retriever1", 10)
        retriever2 = MockRetriever("retriever2", 20)
        
        self.chain.add_retriever(retriever1)
        self.chain.add_retriever(retriever2)
        
        retrievers = self.chain.get_retrievers()
        
        assert len(retrievers) == 2
        assert retrievers[0].name == "retriever1"
        assert retrievers[1].name == "retriever2"
    
    @pytest.mark.asyncio
    async def test_retrieve_chain_success(self):
        """测试责任链检索成功"""
        retriever = MockRetriever(
            "test_retriever",
            10,
            memories=[{"content": "test memory"}],
            quality=0.8,
        )
        self.chain.add_retriever(retriever)
        
        context = RetrievalContext(query="test query")
        result = await self.chain.retrieve(context)
        
        assert len(result.memories) == 1
        assert result.source == "test_retriever"
        assert result.quality == 0.8
        assert result.quality_level == RetrievalQuality.GOOD
    
    @pytest.mark.asyncio
    async def test_retrieve_chain_fallback(self):
        """测试责任链降级"""
        retriever1 = MockRetriever("failing_retriever", 10, should_fail=True)
        retriever2 = MockRetriever(
            "fallback_retriever",
            20,
            memories=[{"content": "fallback memory"}],
            quality=0.6,
        )
        self.chain.add_retriever(retriever1)
        self.chain.add_retriever(retriever2)
        
        context = RetrievalContext(query="test query")
        result = await self.chain.retrieve(context)
        
        assert len(result.memories) == 1
        assert result.source == "fallback_retriever"
        assert result.quality == 0.6
    
    @pytest.mark.asyncio
    async def test_retrieve_parallel(self):
        """测试并行检索"""
        retriever1 = MockRetriever(
            "retriever1",
            10,
            memories=[{"content": "memory1"}],
            quality=0.7,
        )
        retriever2 = MockRetriever(
            "retriever2",
            20,
            memories=[{"content": "memory2"}],
            quality=0.9,
        )
        self.chain.add_retriever(retriever1)
        self.chain.add_retriever(retriever2)
        
        context = RetrievalContext(
            query="test query",
            strategy=RetrievalStrategy.PARALLEL,
        )
        result = await self.chain.retrieve(context)
        
        # 应该选择质量最高的结果
        assert result.source == "retriever2"
        assert result.quality == 0.9
    
    @pytest.mark.asyncio
    async def test_retrieve_best(self):
        """测试最佳检索"""
        retriever1 = MockRetriever(
            "retriever1",
            10,
            memories=[{"content": "memory1"}],
            quality=0.6,
        )
        retriever2 = MockRetriever(
            "retriever2",
            20,
            memories=[{"content": "memory2"}],
            quality=0.8,
        )
        self.chain.add_retriever(retriever1)
        self.chain.add_retriever(retriever2)
        
        context = RetrievalContext(
            query="test query",
            strategy=RetrievalStrategy.BEST,
            min_quality=0.5,
        )
        result = await self.chain.retrieve(context)
        
        assert result.source == "retriever2"
        assert result.quality == 0.8
    
    @pytest.mark.asyncio
    async def test_retrieve_fallback(self):
        """测试降级检索"""
        retriever1 = MockRetriever(
            "primary_retriever",
            10,
            memories=[{"content": "primary memory"}],
            quality=0.4,  # 低于 min_quality
        )
        retriever2 = MockRetriever(
            "fallback_retriever",
            20,
            memories=[{"content": "fallback memory"}],
            quality=0.7,
        )
        self.chain.add_retriever(retriever1)
        self.chain.add_retriever(retriever2)
        
        context = RetrievalContext(
            query="test query",
            strategy=RetrievalStrategy.FALLBACK,
            min_quality=0.5,
        )
        result = await self.chain.retrieve(context)
        
        # 应该降级到备用检索器
        assert result.source == "fallback_retriever"
        assert result.quality == 0.7
    
    @pytest.mark.asyncio
    async def test_retrieve_all_failed(self):
        """测试所有检索器失败"""
        retriever1 = MockRetriever("failing_retriever1", 10, should_fail=True)
        retriever2 = MockRetriever("failing_retriever2", 20, should_fail=True)
        self.chain.add_retriever(retriever1)
        self.chain.add_retriever(retriever2)
        
        context = RetrievalContext(query="test query")
        result = await self.chain.retrieve(context)
        
        assert len(result.memories) == 0
        assert result.source == "chain_exhausted"
        assert result.quality == 0.0
        assert result.quality_level == RetrievalQuality.FAILED
    
    @pytest.mark.asyncio
    async def test_statistics_update(self):
        """测试统计信息更新"""
        retriever = MockRetriever(
            "test_retriever",
            10,
            memories=[{"content": "test"}],
            quality=0.8,
        )
        self.chain.add_retriever(retriever)
        
        context = RetrievalContext(query="test query")
        await self.chain.retrieve(context)
        
        stats = self.chain.get_statistics()
        
        assert stats["total_retrievals"] == 1
        assert stats["successful_retrievals"] == 1
        assert stats["failed_retrievals"] == 0
        assert stats["average_quality"] == 0.8
    
    def test_clear_cache(self):
        """测试清空缓存"""
        self.chain._cache["key1"] = Mock()
        self.chain._cache["key2"] = Mock()
        
        count = self.chain.clear_cache()
        
        assert count == 2
        assert len(self.chain._cache) == 0
    
    def test_repr(self):
        """测试字符串表示"""
        chain = MemoryRetrievalChain()
        assert repr(chain) == "MemoryRetrievalChain(retrievers=0)"
        
        retriever = MockRetriever("test", 10)
        chain.add_retriever(retriever)
        assert repr(chain) == "MemoryRetrievalChain(retrievers=1)"


class TestMemoryRetrievalChainEdgeCases:
    """测试边界情况"""
    
    def test_empty_retrievers(self):
        """测试空检索器列表"""
        chain = MemoryRetrievalChain()
        assert chain._retrievers == []
    
    @pytest.mark.asyncio
    async def test_retrieve_empty_retrievers(self):
        """测试无检索器时检索"""
        chain = MemoryRetrievalChain()
        context = RetrievalContext(query="test query")
        result = await chain.retrieve(context)
        
        assert len(result.memories) == 0
        assert result.source == "chain_exhausted"
        assert result.quality == 0.0
    
    @pytest.mark.asyncio
    async def test_retrieve_with_min_quality(self):
        """测试最低质量要求"""
        retriever = MockRetriever(
            "low_quality_retriever",
            10,
            memories=[{"content": "test"}],
            quality=0.2,  # 低于 min_quality
        )
        chain = MemoryRetrievalChain()
        chain.add_retriever(retriever)
        
        context = RetrievalContext(
            query="test query",
            min_quality=0.5,
        )
        result = await chain.retrieve(context)
        
        # 质量低于要求，应该返回空结果
        assert len(result.memories) == 0
        assert result.quality == 0.0
    
    def test_statistics_initial_values(self):
        """测试统计信息初始值"""
        chain = MemoryRetrievalChain()
        stats = chain.get_statistics()
        
        assert stats["total_retrievals"] == 0
        assert stats["successful_retrievals"] == 0
        assert stats["failed_retrievals"] == 0
        assert stats["cache_hits"] == 0
        assert stats["average_quality"] == 0.0