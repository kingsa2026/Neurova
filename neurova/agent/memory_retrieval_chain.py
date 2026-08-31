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
import hashlib
import time
from neurova.core.logger import get_logger
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

logger = get_logger(__name__)


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
    timeout: float = 15.0  # C-2: 单次检索超时(秒)
    # 实时检索进度回调（UI 聊天界面显示检索过程用；不落盘不记录）
    # 回调签名: (event: Dict[str, Any]) -> None，异常由发射方吞掉
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None


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


def should_need_more_context(
    result: Optional["RetrievalResult"],
    min_quality: float = 0.5,
) -> bool:
    """判断检索结果是否不足以支撑回答（批次 4 / Adaptive Retrieval）。

    判定为"需要更多上下文"：
    - result 为 None，或
    - memories 为空，或
    - quality_level 为 POOR / FAILED，或
    - quality 分数低于 min_quality 阈值

    任何属性缺失按"需要"处理（宁可多查一次，不做静默假设）。
    """
    if result is None:
        return True
    memories = getattr(result, "memories", None) or []
    if not memories:
        return True
    level = str(getattr(result, "quality_level", ""))
    if level in (RetrievalQuality.POOR.value, RetrievalQuality.FAILED.value):
        return True
    quality = getattr(result, "quality", None)
    if not isinstance(quality, (int, float)):
        return True
    return float(quality) < min_quality


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
        self._cache: OrderedDict[str, RetrievalResult] = OrderedDict()  # C-3: LRU 缓存
        self._cache_max_size: int = 200
        self._statistics: Dict[str, Any] = {
            "total_retrievals": 0,
            "successful_retrievals": 0,
            "failed_retrievals": 0,
            "cache_hits": 0,
            "average_quality": 0.0,
            "_quality_sum": 0.0,  # C-4: 用单独计数做分母
            "_success_quality_count": 0,
        }
        self._stats_lock = threading.Lock()  # C-4: 统计更新加锁

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
        with self._stats_lock:
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
                    # BUG#3: 质量不达标路径采用 cache_result 后补齐 cache_hits 统计
                    with self._stats_lock:
                        self._statistics["cache_hits"] += 1

            # 更新缓存
            self._update_cache(context.query, result)

            # C-1: 根据 result.source 判定成功/失败
            is_exhausted = result.source.endswith(("_exhausted", "_failed", "_all_failed")) or result.source == "no_retrievers"

            with self._stats_lock:
                if is_exhausted:
                    self._statistics["failed_retrievals"] += 1
                else:
                    self._statistics["successful_retrievals"] += 1
                    self._statistics["_quality_sum"] += result.quality
                    self._statistics["_success_quality_count"] += 1
                    # C-4: 用成功计数做分母
                    count = self._statistics["_success_quality_count"]
                    self._statistics["average_quality"] = self._statistics["_quality_sum"] / count if count > 0 else 0.0

            logger.info(
                f"Retrieval completed: source={result.source}, quality={result.quality_level.value}, memories={len(result.memories)}"
            )

            return result

        except Exception as e:
            logger.error("Retrieval failed: %s", e)
            with self._stats_lock:
                self._statistics["failed_retrievals"] += 1

            # 尝试缓存降级
            cache_result = await self._retrieve_from_cache(context)
            if cache_result:
                with self._stats_lock:
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
                start_time = time.monotonic()

                # 实时进度：检索器开始（UI 聊天界面显示检索过程，不落盘）
                progress_cb = getattr(context, "progress_callback", None)
                if progress_cb:
                    try:
                        progress_cb({"stage": "retriever_start", "retriever": retriever.name})
                    except Exception:  # noqa: BLE001 - 进度回调失败不阻断检索
                        pass

                # C-2: 添加超时控制
                try:
                    result = await asyncio.wait_for(
                        retriever.retrieve(context), timeout=context.timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning("Retriever %s timed out after %.1fs", retriever.name, context.timeout)
                    if progress_cb:
                        try:
                            progress_cb({"stage": "retriever_timeout", "retriever": retriever.name})
                        except Exception:  # noqa: BLE001
                            pass
                    continue

                elapsed = time.monotonic() - start_time
                result.retrieval_time = elapsed

                # 实时进度：检索器完成（命中数/耗时）
                if progress_cb:
                    try:
                        progress_cb(
                            {
                                "stage": "retriever_done",
                                "retriever": retriever.name,
                                "count": len(result.memories),
                                "ms": round(elapsed * 1000, 1),
                                "accepted": bool(result.memories and result.quality >= context.min_quality),
                            }
                        )
                    except Exception:  # noqa: BLE001
                        pass

                if result.memories and result.quality >= context.min_quality:
                    return result
                else:
                    logger.debug("Retriever %s returned insufficient results", retriever.name)

            except Exception as e:
                logger.warning("Retriever %s failed: %s", retriever.name, e)
                if getattr(context, "progress_callback", None):
                    try:
                        context.progress_callback({"stage": "retriever_error", "retriever": retriever.name})
                    except Exception:  # noqa: BLE001
                        pass
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

        start_time = time.monotonic()

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
                retrieval_time=time.monotonic() - start_time,
            )

        # 选择质量最高的结果
        best_result = max(valid_results, key=lambda r: r.quality)
        best_result.retrieval_time = time.monotonic() - start_time

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
        start_time = time.monotonic()

        for retriever in self._retrievers:
            try:
                # BUG#2: _retrieve_best 同样需要尊重 context.timeout
                try:
                    result = await asyncio.wait_for(
                        retriever.retrieve(context), timeout=context.timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Retriever %s timed out after %.1fs (best)",
                        retriever.name,
                        context.timeout,
                    )
                    continue
                result.retrieval_time = time.monotonic() - start_time
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
                retrieval_time=time.monotonic() - start_time,
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

        start_time = time.monotonic()

        # 尝试主检索器（第一个）
        primary_retriever = self._retrievers[0]
        try:
            logger.debug("Trying primary retriever: %s", primary_retriever.name)
            # BUG#2: 主检索器同样需要尊重 context.timeout
            try:
                result = await asyncio.wait_for(
                    primary_retriever.retrieve(context), timeout=context.timeout
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Primary retriever %s timed out after %.1fs",
                    primary_retriever.name,
                    context.timeout,
                )
                result = None
            if result is not None:
                result.retrieval_time = time.monotonic() - start_time

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
                # BUG#2: 备用检索器同样需要尊重 context.timeout
                try:
                    result = await asyncio.wait_for(
                        retriever.retrieve(context), timeout=context.timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Fallback retriever %s timed out after %.1fs",
                        retriever.name,
                        context.timeout,
                    )
                    continue
                result.retrieval_time = time.monotonic() - start_time

                # BUG#5: 备用检索器也要检查 quality >= min_quality(与 _retrieve_chain:326 对齐)
                if result.memories and result.quality >= context.min_quality:
                    return result
                else:
                    logger.debug("Fallback retriever %s failed quality check", retriever.name)

            except Exception as e:
                logger.warning("Fallback retriever %s failed: %s", retriever.name, e)
                continue

        # 所有检索器都失败
        return RetrievalResult(
            memories=[],
            source="fallback_exhausted",
            quality=0.0,
            quality_level=RetrievalQuality.FAILED,
            retrieval_time=time.monotonic() - start_time,
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
        """从缓存检索(LRU: 命中时移到末尾)"""
        cache_key = self._get_cache_key(context.query)
        if cache_key in self._cache:
            # C-3: LRU — 命中时移到末尾
            self._cache.move_to_end(cache_key)
            cached = self._cache[cache_key]
            logger.debug("Cache hit for query: %s...", context.query[:50])
            return cached

        return None

    def _update_cache(self, query: str, result: RetrievalResult) -> None:
        """更新缓存(LRU: 超限时淘汰最旧条目)"""
        if result.memories and result.quality > 0.5:  # 只缓存高质量结果
            cache_key = self._get_cache_key(query)
            self._cache[cache_key] = result
            # C-3: 新条目移到末尾
            self._cache.move_to_end(cache_key)

            # 限制缓存大小
            while len(self._cache) > self._cache_max_size:
                # C-3: LRU — 淘汰最旧(第一个)条目
                self._cache.popitem(last=False)

    def _get_cache_key(self, query: str) -> str:
        """C-3: 生成缓存键(用 hash 避免长查询截断冲突)"""
        normalized = query.strip().lower()
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()

    def __repr__(self) -> str:
        """字符串表示"""
        return f"MemoryRetrievalChain(retrievers={len(self._retrievers)})"
