"""
检索器适配器 - 将现有检索器适配到 Retriever 协议

提供以下适配器：
1. UnifiedRetrieverAdapter - 适配 UnifiedRetriever
2. MoERetrieverAdapter - 适配 MoEMemoryRouter
3. CacheRetrieverAdapter - 适配缓存检索
4. FallbackRetrieverAdapter - 适配降级检索
"""

import asyncio
import time
from neurova.core.logger import get_logger
from typing import Any, Dict, List

logger = get_logger(__name__)


class UnifiedRetrieverAdapter:
    """适配 UnifiedRetriever"""

    def __init__(self, unified_retriever):
        """
        参数:
            unified_retriever: UnifiedRetriever 实例
        """
        self._retriever = unified_retriever
        self._name = "UnifiedRetriever"
        self._priority = 10  # 高优先级

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    async def retrieve(self, context) -> Any:
        """执行检索"""
        from neurova.agent.memory_retrieval_chain import RetrievalResult

        start_time = time.monotonic()

        try:
            # 调用 UnifiedRetriever（兼容同步 / async 两种实现）
            result = self._retriever.retrieve(
                query=context.query,
                limit=context.limit,
            )
            if asyncio.iscoroutine(result):
                memories = await result
            else:
                memories = result

            elapsed = time.monotonic() - start_time

            # 评估质量
            quality = self.get_quality_score(memories, context.query)
            quality_level = self._quality_from_score(quality)

            return RetrievalResult(
                memories=memories,
                source=self._name,
                quality=quality,
                quality_level=quality_level,
                retrieval_time=elapsed,
                metadata={"retriever_type": "unified"},
            )

        except Exception as e:
            logger.error("UnifiedRetriever failed: %s", e)
            raise

    def get_quality_score(self, memories: List[Dict[str, Any]], query: str) -> float:
        """评估检索结果质量"""
        if not memories:
            return 0.0

        # 基础分数：结果数量
        count_score = min(len(memories) / 10, 1.0)  # 10条结果为满分

        # 相关性分数：查询关键词匹配
        query_keywords = set(query.lower().split())
        relevance_score = 0.0

        for memory in memories:
            content = memory.get("content", "").lower()
            content_keywords = set(content.split())
            overlap = len(query_keywords.intersection(content_keywords))
            if query_keywords:
                relevance_score += overlap / len(query_keywords)

        if memories:
            relevance_score /= len(memories)

        # 综合分数
        quality = 0.6 * count_score + 0.4 * relevance_score
        return min(max(quality, 0.0), 1.0)

    def _quality_from_score(self, score: float) -> Any:
        """从分数转换为质量等级"""
        from neurova.agent.memory_retrieval_chain import RetrievalQuality

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


class MoERetrieverAdapter:
    """适配 MoEMemoryRouter"""

    # BUG#7: 路由质量经验常量
    # 经验来源:MoE 路由在专家激活权重稳定时,平均路由置信度约为 0.8
    # (基于 gating_network.route 的 softmax 输出统计经验值)
    DEFAULT_ROUTING_SCORE = 0.8

    def __init__(self, moe_router):
        """
        参数:
            moe_router: MoEMemoryRouter 实例
        """
        self._router = moe_router
        self._name = "MoERetriever"
        self._priority = 20  # 中等优先级

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    async def retrieve(self, context) -> Any:
        """执行检索"""
        from neurova.agent.memory_retrieval_chain import RetrievalResult

        start_time = time.monotonic()

        try:
            # 调用 MoEMemoryRouter
            # BUG#1: MoEMemoryRouter.retrieve 是 async,必须 await(否则返回 coroutine,len() 抛 TypeError)
            memories = await self._router.retrieve(
                query=context.query,
                limit=context.limit,
            )

            elapsed = time.monotonic() - start_time

            # 评估质量
            quality = self.get_quality_score(memories, context.query)
            quality_level = self._quality_from_score(quality)

            return RetrievalResult(
                memories=memories,
                source=self._name,
                quality=quality,
                quality_level=quality_level,
                retrieval_time=elapsed,
                metadata={"retriever_type": "moe"},
            )

        except Exception as e:
            logger.error("MoERetriever failed: %s", e)
            raise

    def get_quality_score(self, memories: List[Dict[str, Any]], query: str) -> float:
        """评估检索结果质量"""
        if not memories:
            return 0.0

        # 基础分数：结果数量
        count_score = min(len(memories) / 5, 1.0)  # 5条结果为满分

        # 路由分数：MoE 路由质量(使用类常量,便于统一调参与回归)
        routing_score = self.DEFAULT_ROUTING_SCORE

        # 综合分数
        quality = 0.7 * count_score + 0.3 * routing_score
        return min(max(quality, 0.0), 1.0)

    def _quality_from_score(self, score: float) -> Any:
        """从分数转换为质量等级"""
        from neurova.agent.memory_retrieval_chain import RetrievalQuality

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


class CacheRetrieverAdapter:
    """适配缓存检索"""

    def __init__(self, cache_manager=None):
        """
        参数:
            cache_manager: 缓存管理器（可选）
        """
        self._cache = cache_manager
        self._name = "CacheRetriever"
        self._priority = 30  # 低优先级
        # BUG#4: _simple_cache 必须在 __init__ 初始化,否则 getattr 永远返回临时 {}
        self._simple_cache: Dict[str, List[Dict[str, Any]]] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    async def retrieve(self, context) -> Any:
        """执行检索"""
        from neurova.agent.memory_retrieval_chain import RetrievalResult

        start_time = time.monotonic()

        try:
            # 从缓存检索
            memories = []
            # BUG#4: cache_key 始终基于 query 计算(无 cache_manager 时用作 _simple_cache 的键)
            cache_key = context.query[:100].strip().lower()

            if self._cache:
                # 使用缓存管理器
                memories = self._cache.get(context.query, [])
            else:
                # 简单内存缓存(BUG#4: 直接用 self._simple_cache,不再用 getattr 死代码)
                memories = self._simple_cache.get(cache_key, [])

            elapsed = time.monotonic() - start_time

            # 评估质量
            quality = self.get_quality_score(memories, context.query)
            quality_level = self._quality_from_score(quality)

            # BUG#4: retrieve 成功后写入 _simple_cache(无 cache_manager 时作为本地缓存)
            if not self._cache:
                self._simple_cache[cache_key] = memories

            return RetrievalResult(
                memories=memories,
                source=self._name,
                quality=quality,
                quality_level=quality_level,
                retrieval_time=elapsed,
                metadata={"retriever_type": "cache"},
            )

        except Exception as e:
            logger.error("CacheRetriever failed: %s", e)
            raise

    def get_quality_score(self, memories: List[Dict[str, Any]], query: str) -> float:
        """评估检索结果质量"""
        if not memories:
            return 0.0

        # 缓存结果质量较低（可能是过时数据）
        return 0.4

    def _quality_from_score(self, score: float) -> Any:
        """从分数转换为质量等级"""
        from neurova.agent.memory_retrieval_chain import RetrievalQuality

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


class FallbackRetrieverAdapter:
    """适配降级检索"""

    def __init__(self, memory_agent):
        """
        参数:
            memory_agent: MemoryAgent 实例
        """
        self._memory_agent = memory_agent
        self._name = "FallbackRetriever"
        self._priority = 40  # 最低优先级

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    async def retrieve(self, context) -> Any:
        """执行检索"""
        from neurova.agent.memory_retrieval_chain import RetrievalResult

        start_time = time.monotonic()

        try:
            # 使用 MemoryAgent 的基础检索
            memories = self._memory_agent.moe_retrieve(
                query=context.query,
                limit=context.limit,
            )

            elapsed = time.monotonic() - start_time

            # 评估质量
            quality = self.get_quality_score(memories, context.query)
            quality_level = self._quality_from_score(quality)

            return RetrievalResult(
                memories=memories,
                source=self._name,
                quality=quality,
                quality_level=quality_level,
                retrieval_time=elapsed,
                metadata={"retriever_type": "fallback"},
            )

        except Exception as e:
            logger.error("FallbackRetriever failed: %s", e)
            raise

    def get_quality_score(self, memories: List[Dict[str, Any]], query: str) -> float:
        """评估检索结果质量"""
        if not memories:
            return 0.0

        # 降级检索质量较低
        return 0.3

    def _quality_from_score(self, score: float) -> Any:
        """从分数转换为质量等级"""
        from neurova.agent.memory_retrieval_chain import RetrievalQuality

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
