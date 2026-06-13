"""
MemoryRetrievalChain 深度模块 - 记忆检索责任链

提供统一的记忆检索管理接口，包括：
1. 责任链模式：支持多级降级
2. 质量评估：每个检索器返回质量分数
3. 缓存降级：完全不可用时返回缓存结果
4. 智能选择：基于质量分数选择最佳检索器

设计原则：
- 深度模块：小接口，深实现
- 责任链：一个接口，多个实现
- 质量监控：每个检索器都有质量评估
- 优雅降级：有状态的降级策略
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class RetrievalQuality(Enum):
    """检索质量等级"""

    EXCELLENT = "excellent"  # 优秀 (0.9-1.0)
    GOOD = "good"  # 良好 (0.7-0.9)
    FAIR = "fair"  # 一般 (0.5-0.7)
    POOR = "poor"  # 较差 (0.3-0.5)
    FAILED = "failed"  # 失败 (0.0-0.3)


class RetrievalStrategy(Enum):
    """检索策略"""

    CHAIN = "chain"  # 责任链（按优先级尝试）
    PARALLEL = "parallel"  # 并行（同时尝试所有检索器）
    BEST = "best"  # 最佳（选择质量最高的结果）
    FALLBACK = "fallback"  # 降级（主检索器失败时降级）


@dataclass
class RetrievalResult:
    """检索结果"""

    memories: List[Dict[str, Any]]
    source: str
    quality: float
    quality_level: RetrievalQuality
    retrieval_time: float  # 检索耗时（秒）
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "memories": self.memories,
            "source": self.source,
            "quality": self.quality,
            "quality_level": self.quality_level.value,
            "retrieval_time": self.retrieval_time,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class RetrievalContext:
    """检索上下文"""

    query: str
    limit: int = 10
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    strategy: RetrievalStrategy = RetrievalStrategy.CHAIN
    min_quality: float = 0.3  # 最低质量要求
    metadata: Optional[Dict[str, Any]] = None


@runtime_checkable
class Retriever(Protocol):
    """检索器协议"""

    @property
    def name(self) -> str:
        """检索器名称"""
        ...

    @property
    def priority(self) -> int:
        """优先级（数字越小优先级越高）"""
        ...

    async def retrieve(self, context: RetrievalContext) -> RetrievalResult:
        """执行检索"""
        ...

    def get_quality_score(self, results: List[Dict[str, Any]], query: str) -> float:
        """评估检索结果质量"""
        ...


class MemoryRetrievalChain:
    """
    记忆检索责任链

    提供统一的记忆检索管理接口，支持：
    1. 多级降级：按优先级尝试不同检索器
    2. 质量评估：每个检索器返回质量分数
    3. 缓存降级：完全不可用时返回缓存结果
    4. 智能选择：基于质量分数选择最佳检索器

    使用示例：
        chain = MemoryRetrievalChain()

        # 添加检索器
        chain.add_retriever(UnifiedRetrieverAdapter())
        chain.add_retriever(MoERetrieverAdapter())
        chain.add_retriever(CacheRetrieverAdapter())

        # 执行检索
        result = await chain.retrieve(RetrievalContext(
            query="用户输入",
            limit=10,
        ))

        print(f"检索质量: {result.quality_level.value}")
        print(f"检索源: {result.source}")
        print(f"结果数量: {len(result.memories)}")
    """

    def __init__(self):
        """初始化 MemoryRetrievalChain"""
        self._retrievers: List[Retriever] = []
        self._cache: Dict[str, RetrievalResult] = {}
        self._statistics: Dict[str, Any] = {
            "total_retrievals": 0,
            "successful_retrievals": 0,
            "failed_retrievals": 0,
            "cache_hits": 0,
            "average_quality": 0.0,
        }

        logger.debug("MemoryRetrievalChain initialized")

    def add_retriever(self, retriever: Retriever) -> None:
        """
        添加检索器

        参数:
            retriever: 检索器实例（需实现 Retriever 协议）
        """
        if not isinstance(retriever, Retriever):
            raise TypeError(f"Retriever must implement Retriever protocol, got {type(retriever)}")

        # 按优先级插入（数字越小优先级越高）
        inserted = False
        for i, existing in enumerate(self._retrievers):
            if retriever.priority < existing.priority:
                self._retrievers.insert(i, retriever)
                inserted = True
                break

        if not inserted:
            self._retrievers.append(retriever)

        logger.debug("Added retriever: %s (priority: %s)", retriever.name, retriever.priority)

    def remove_retriever(self, name: str) -> bool:
        """
        移除检索器

        参数:
            name: 检索器名称

        返回:
            True 表示移除成功，False 表示未找到
        """
        for i, retriever in enumerate(self._retrievers):
            if retriever.name == name:
                del self._retrievers[i]
                logger.debug("Removed retriever: %s", name)
                return True

        logger.warning("Retriever not found: %s", name)
        return False

    def get_retrievers(self) -> List[Retriever]:
        """获取所有检索器"""
        return self._retrievers.copy()

    async def retrieve(self, context: RetrievalContext) -> RetrievalResult:
        """
        执行检索（统一入口）

        参数:
            context: 检索上下文

        返回:
            RetrievalResult 实例
        """
        self._statistics["total_retrievals"] += 1

        logger.info("Starting retrieval: query='%s...', strategy=%s", context.query[:50], context.strategy.value)

        try:
            if context.strategy == RetrievalStrategy.CHAIN:
                result = await self._retrieve_chain(context)
            elif context.strategy == RetrievalStrategy.PARALLEL:
                result = await self._retrieve_parallel(context)
            elif context.strategy == RetrievalStrategy.BEST:
                result = await self._retrieve_best(context)
            elif context.strategy == RetrievalStrategy.FALLBACK:
                result = await self._retrieve_fallback(context)
            else:
                raise ValueError(f"Unknown retrieval strategy: {context.strategy}")

            # 检查质量是否满足要求
            if result.quality < context.min_quality:
                logger.warning("Retrieval quality %.2f < min_quality %.2f", result.quality, context.min_quality)
                # 尝试缓存降级
                cache_result = await self._retrieve_from_cache(context)
                if cache_result and cache_result.quality >= context.min_quality:
                    result = cache_result

            # 更新缓存
            self._update_cache(context.query, result)

            # 更新统计
            self._statistics["successful_retrievals"] += 1
            self._update_average_quality(result.quality)

            logger.info(
                f"Retrieval completed: source={result.source}, quality={result.quality_level.value}, memories={len(result.memories)}"
            )

            return result

        except Exception as e:
            logger.error("Retrieval failed: %s", e)
            self._statistics["failed_retrievals"] += 1

            # 尝试缓存降级
            cache_result = await self._retrieve_from_cache(context)
            if cache_result:
                self._statistics["cache_hits"] += 1
                return cache_result

            # 返回空结果
            return RetrievalResult(
                memories=[],
                source="error",
                quality=0.0,
                quality_level=RetrievalQuality.FAILED,
                retrieval_time=0.0,
                metadata={"error": str(e)},
            )

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._statistics.copy()

    def clear_cache(self) -> int:
        """清空缓存"""
        count = len(self._cache)
        self._cache.clear()
        logger.debug("Cleared cache: %s entries", count)
        return count

    # ================================================================
    # 内部方法
    # ================================================================

    async def _retrieve_chain(self, context: RetrievalContext) -> RetrievalResult:
        """
        责任链检索：按优先级尝试，第一个成功即返回

        参数:
            context: 检索上下文

        返回:
            RetrievalResult 实例
        """
        for retriever in self._retrievers:
            try:
                logger.debug("Trying retriever: %s", retriever.name)
                start_time = asyncio.get_event_loop().time()

                result = await retriever.retrieve(context)

                elapsed = asyncio.get_event_loop().time() - start_time
                result.retrieval_time = elapsed

                if result.memories and result.quality >= context.min_quality:
                    return result
                else:
                    logger.debug("Retriever %s returned insufficient results", retriever.name)

            except Exception as e:
                logger.warning("Retriever %s failed: %s", retriever.name, e)
                continue

        # 所有检索器都失败，返回空结果
        return RetrievalResult(
            memories=[],
            source="chain_exhausted",
            quality=0.0,
            quality_level=RetrievalQuality.FAILED,
            retrieval_time=0.0,
        )

    async def _retrieve_parallel(self, context: RetrievalContext) -> RetrievalResult:
        """
        并行检索：同时尝试所有检索器，选择最佳结果

        参数:
            context: 检索上下文

        返回:
            RetrievalResult 实例
        """
        if not self._retrievers:
            return RetrievalResult(
                memories=[],
                source="no_retrievers",
                quality=0.0,
                quality_level=RetrievalQuality.FAILED,
                retrieval_time=0.0,
            )

        start_time = asyncio.get_event_loop().time()

        # 并行执行所有检索器
        tasks = []
        for retriever in self._retrievers:
            tasks.append(self._safe_retrieve(retriever, context))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 过滤有效结果
        valid_results = []
        for result in results:
            if isinstance(result, RetrievalResult) and result.memories:
                valid_results.append(result)

        if not valid_results:
            return RetrievalResult(
                memories=[],
                source="parallel_all_failed",
                quality=0.0,
                quality_level=RetrievalQuality.FAILED,
                retrieval_time=asyncio.get_event_loop().time() - start_time,
            )

        # 选择质量最高的结果
        best_result = max(valid_results, key=lambda r: r.quality)
        best_result.retrieval_time = asyncio.get_event_loop().time() - start_time

        return best_result

    async def _retrieve_best(self, context: RetrievalContext) -> RetrievalResult:
        """
        最佳检索：尝试所有检索器，返回质量最高的结果（即使低于 min_quality）

        参数:
            context: 检索上下文

        返回:
            RetrievalResult 实例
        """
        all_results = []
        start_time = asyncio.get_event_loop().time()

        for retriever in self._retrievers:
            try:
                result = await retriever.retrieve(context)
                result.retrieval_time = asyncio.get_event_loop().time() - start_time
                all_results.append(result)
            except Exception as e:
                logger.warning("Retriever %s failed: %s", retriever.name, e)
                continue

        if not all_results:
            return RetrievalResult(
                memories=[],
                source="best_all_failed",
                quality=0.0,
                quality_level=RetrievalQuality.FAILED,
                retrieval_time=asyncio.get_event_loop().time() - start_time,
            )

        # 选择质量最高的结果
        best_result = max(all_results, key=lambda r: r.quality)
        return best_result

    async def _retrieve_fallback(self, context: RetrievalContext) -> RetrievalResult:
        """
        降级检索：主检索器失败时降级到备用检索器

        参数:
            context: 检索上下文

        返回:
            RetrievalResult 实例
        """
        if not self._retrievers:
            return RetrievalResult(
                memories=[],
                source="no_retrievers",
                quality=0.0,
                quality_level=RetrievalQuality.FAILED,
                retrieval_time=0.0,
            )

        start_time = asyncio.get_event_loop().time()

        # 尝试主检索器（第一个）
        primary_retriever = self._retrievers[0]
        try:
            logger.debug("Trying primary retriever: %s", primary_retriever.name)
            result = await primary_retriever.retrieve(context)
            result.retrieval_time = asyncio.get_event_loop().time() - start_time

            if result.memories and result.quality >= context.min_quality:
                return result
            else:
                logger.debug("Primary retriever %s failed quality check", primary_retriever.name)

        except Exception as e:
            logger.warning("Primary retriever %s failed: %s", primary_retriever.name, e)

        # 降级到备用检索器
        for retriever in self._retrievers[1:]:
            try:
                logger.debug("Falling back to retriever: %s", retriever.name)
                result = await retriever.retrieve(context)
                result.retrieval_time = asyncio.get_event_loop().time() - start_time

                if result.memories:
                    return result

            except Exception as e:
                logger.warning("Fallback retriever %s failed: %s", retriever.name, e)
                continue

        # 所有检索器都失败
        return RetrievalResult(
            memories=[],
            source="fallback_exhausted",
            quality=0.0,
            quality_level=RetrievalQuality.FAILED,
            retrieval_time=asyncio.get_event_loop().time() - start_time,
        )

    async def _safe_retrieve(self, retriever: Retriever, context: RetrievalContext) -> Optional[RetrievalResult]:
        """安全执行检索（捕获异常）"""
        try:
            result = await retriever.retrieve(context)
            return result
        except Exception as e:
            logger.warning("Retriever %s failed: %s", retriever.name, e)
            return None

    async def _retrieve_from_cache(self, context: RetrievalContext) -> Optional[RetrievalResult]:
        """从缓存检索"""
        cache_key = self._get_cache_key(context.query)
        cached = self._cache.get(cache_key)

        if cached:
            logger.debug("Cache hit for query: %s...", context.query[:50])
            return cached

        return None

    def _update_cache(self, query: str, result: RetrievalResult) -> None:
        """更新缓存"""
        if result.memories and result.quality > 0.5:  # 只缓存高质量结果
            cache_key = self._get_cache_key(query)
            self._cache[cache_key] = result

            # 限制缓存大小（最多1000条）
            if len(self._cache) > 1000:
                # 移除最早缓存的10%
                keys_to_remove = list(self._cache.keys())[:100]
                for key in keys_to_remove:
                    del self._cache[key]

    def _get_cache_key(self, query: str) -> str:
        """生成缓存键"""
        # 简化实现：使用查询的前100个字符作为缓存键
        return query[:100].strip().lower()

    def _update_average_quality(self, quality: float) -> None:
        """更新平均质量"""
        total = self._statistics["total_retrievals"]
        current_avg = self._statistics["average_quality"]

        # 增量平均公式
        new_avg = current_avg + (quality - current_avg) / total
        self._statistics["average_quality"] = new_avg

    def __repr__(self) -> str:
        """字符串表示"""
        return f"MemoryRetrievalChain(retrievers={len(self._retrievers)})"
