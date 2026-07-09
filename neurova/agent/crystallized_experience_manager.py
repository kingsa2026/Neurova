"""
CrystallizedExperienceManager — 结晶经验检索管理器

深度模块设计：小接口（retrieve/observe/get_health），深实现（重试/降级/缓存）。

解决风险点4：结晶经验检索失败时的容错处理。
"""

from __future__ import annotations

import asyncio
from neurova.core.logger import get_logger
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol

logger = get_logger(__name__)


class RetrievalStatus(Enum):
    """检索状态"""

    SUCCESS = "success"
    FAILED = "failed"
    DEGRADED = "degraded"
    CACHED = "cached"


class HealthStatus(Enum):
    """健康状态"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class RetrievalMetrics:
    """检索指标"""

    total_attempts: int = 0
    successful_attempts: int = 0
    failed_attempts: int = 0
    cached_attempts: int = 0
    degraded_attempts: int = 0
    average_latency_ms: float = 0.0
    last_retrieval_time: Optional[float] = None
    consecutive_failures: int = 0
    health_status: HealthStatus = HealthStatus.HEALTHY


@dataclass
class CrystallizedExperience:
    """结晶经验数据结构"""

    id: str
    content: str
    method: str
    confidence: float
    score: float
    source: str = "crystallized"
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class RetrievalResult:
    """检索结果"""

    status: RetrievalStatus
    experiences: List[CrystallizedExperience] = field(default_factory=list)
    source: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class CrystallizerProtocol(Protocol):
    """结晶器协议"""

    def retrieve(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """检索结晶经验"""
        ...


class CrystallizedExperienceManager:
    """
    结晶经验检索管理器

    深度模块设计：
    - 小接口：retrieve(), observe(), get_health()
    - 深实现：重试策略、降级策略、缓存机制、健康监控

    核心功能：
    1. 容错检索：支持重试、降级、缓存多级容错
    2. 质量监控：监控检索质量，异常时通知用户
    3. 降级策略：降级时返回相关记忆，而非空结果
    """

    def __init__(
        self,
        crystallizer: Optional[CrystallizerProtocol] = None,
        memory_manager: Optional[Any] = None,
        max_retries: int = 2,
        retry_delay_ms: float = 100.0,
        cache_ttl_seconds: float = 300.0,  # 5分钟缓存
        health_check_interval: float = 60.0,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """
        初始化结晶经验管理器

        Args:
            crystallizer: PatternCrystallizer 实例
            memory_manager: MemoryManager 实例（用于降级检索）
            max_retries: 最大重试次数
            retry_delay_ms: 重试延迟（毫秒）
            cache_ttl_seconds: 缓存过期时间（秒）
            health_check_interval: 健康检查间隔（秒）
            agent_id: Agent ID（用于缓存键隔离，防止跨用户污染）
            user_id: User ID（用于缓存键隔离，防止跨用户污染）
        """
        self._crystallizer = crystallizer
        self._memory_manager = memory_manager
        self._max_retries = max_retries
        self._retry_delay_ms = retry_delay_ms
        self._cache_ttl_seconds = cache_ttl_seconds
        self._health_check_interval = health_check_interval
        # Bug 5 修复: 缓存键需包含 agent_id/user_id,防止跨用户污染
        self._agent_id = agent_id
        self._user_id = user_id

        # 缓存：{query_hash: (result, timestamp)}
        self._cache: Dict[str, tuple] = {}

        # 指标
        self._metrics = RetrievalMetrics()

        # 失败回调
        self._failure_callbacks: List[Callable[[str, Exception], None]] = []

        logger.info("CrystallizedExperienceManager 初始化完成")

    @property
    def metrics(self) -> RetrievalMetrics:
        """获取检索指标"""
        return self._metrics

    def add_failure_callback(self, callback: Callable[[str, Exception], None]) -> None:
        """
        添加失败回调

        Args:
            callback: 回调函数，参数为 (query, error)
        """
        self._failure_callbacks.append(callback)

    async def retrieve(
        self,
        query: str,
        limit: int = 5,
        use_cache: bool = True,
        fallback_to_memory: bool = True,
    ) -> RetrievalResult:
        """
        统一检索入口（容错检索）

        Args:
            query: 查询文本
            limit: 返回数量限制
            use_cache: 是否使用缓存
            fallback_to_memory: 是否降级到记忆检索

        Returns:
            检索结果
        """
        start_time = time.time()
        self._metrics.total_attempts += 1
        self._metrics.last_retrieval_time = start_time

        # 1. 检查缓存
        if use_cache:
            cached_result = self._get_from_cache(query)
            if cached_result:
                self._metrics.cached_attempts += 1
                logger.debug("结晶经验缓存命中: query=%s...", query[:30])
                return cached_result

        # 2. 尝试检索（带重试）
        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                result = await self._retrieve_with_crystallizer(query, limit)
                latency_ms = (time.time() - start_time) * 1000
                result.latency_ms = latency_ms

                # 成功
                self._metrics.successful_attempts += 1
                self._metrics.consecutive_failures = 0
                self._update_health_status()

                # 缓存结果
                if use_cache and result.experiences:
                    self._put_to_cache(query, result)

                logger.info(
                    f"结晶经验检索成功: query={query[:30]}..., "
                    f"experiences={len(result.experiences)}, "
                    f"latency={latency_ms:.1f}ms"
                )
                return result

            except Exception as e:
                last_error = e
                logger.warning("结晶经验检索失败 (attempt %s/%s): %s", attempt + 1, self._max_retries + 1, e)

                # 重试延迟
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay_ms / 1000)

        # 3. 所有重试失败，尝试降级
        self._metrics.failed_attempts += 1
        self._metrics.consecutive_failures += 1
        self._update_health_status()

        # 触发失败回调
        for callback in self._failure_callbacks:
            try:
                callback(query, last_error)
            except Exception as cb_error:
                logger.warning("失败回调执行错误: %s", cb_error)

        # 降级到记忆检索
        if fallback_to_memory and self._memory_manager:
            logger.info("结晶经验检索降级到记忆检索: query=%s...", query[:30])
            result = await self._fallback_to_memory(query, limit)
            latency_ms = (time.time() - start_time) * 1000
            result.latency_ms = latency_ms
            self._metrics.degraded_attempts += 1
            return result

        # 完全失败
        latency_ms = (time.time() - start_time) * 1000
        logger.error("结晶经验检索完全失败: query=%s..., error=%s", query[:30], last_error)
        return RetrievalResult(
            status=RetrievalStatus.FAILED,
            source="crystallized_experience_manager",
            latency_ms=latency_ms,
            error=str(last_error),
        )

    async def _retrieve_with_crystallizer(self, query: str, limit: int) -> RetrievalResult:
        """
        使用结晶器检索

        Args:
            query: 查询文本
            limit: 返回数量限制

        Returns:
            检索结果
        """
        if not self._crystallizer:
            raise ValueError("结晶器未初始化")

        # 调用结晶器检索
        raw_results = self._crystallizer.retrieve(query, limit=limit)

        # 转换为 CrystallizedExperience
        experiences = []
        for item in raw_results:
            experience = CrystallizedExperience(
                id=item.get("id", ""),
                content=item.get("content", ""),
                method=item.get("method", ""),
                confidence=item.get("confidence", 0.0),
                score=item.get("score", 0.0),
                source=item.get("source", "crystallized"),
                metadata=item.get("metadata"),
            )
            experiences.append(experience)

        return RetrievalResult(
            status=RetrievalStatus.SUCCESS,
            experiences=experiences,
            source="pattern_crystallizer",
        )

    async def _fallback_to_memory(self, query: str, limit: int) -> RetrievalResult:
        """
        降级到记忆检索

        Args:
            query: 查询文本
            limit: 返回数量限制

        Returns:
            降级检索结果
        """
        if not self._memory_manager:
            return RetrievalResult(
                status=RetrievalStatus.FAILED,
                source="memory_fallback",
                error="记忆管理器未初始化",
            )

        try:
            # 使用记忆管理器检索
            memories = self._memory_manager.recall(query, limit=limit)

            # 转换为 CrystallizedExperience（模拟格式）
            experiences = []
            for mem in memories:
                experience = CrystallizedExperience(
                    id=mem.get("id", ""),
                    content=mem.get("content", ""),
                    method="memory_fallback",
                    confidence=mem.get("importance", 0.5),
                    score=mem.get("temperature", 50.0),
                    source="memory_fallback",
                    metadata={"original_source": mem.get("source", "memory")},
                )
                experiences.append(experience)

            return RetrievalResult(
                status=RetrievalStatus.DEGRADED,
                experiences=experiences,
                source="memory_fallback",
                metadata={"fallback_reason": "crystallizer_unavailable"},
            )

        except Exception as e:
            logger.error("记忆检索降级失败: %s", e)
            return RetrievalResult(
                status=RetrievalStatus.FAILED,
                source="memory_fallback",
                error=str(e),
            )

    def observe(
        self,
        tool_name: str,
        context: str,
        success: bool,
        result: Any = None,
    ) -> None:
        """
        观察工具使用（转发给结晶器）

        Args:
            tool_name: 工具名称
            context: 使用上下文
            success: 是否成功
            result: 工具结果（可选）
        """
        if self._crystallizer:
            try:
                self._crystallizer.observe(tool_name, context, success, result)
            except Exception as e:
                logger.warning("观察工具使用失败: %s", e)

    def get_health(self) -> HealthStatus:
        """
        获取健康状态

        Returns:
            健康状态
        """
        return self._metrics.health_status

    def clear_cache(self, query: Optional[str] = None) -> int:
        """
        清空缓存

        Args:
            query: 指定查询（可选，为空则清空全部）

        Returns:
            清空的缓存数量
        """
        if query:
            query_hash = self._hash_query(query)
            if query_hash in self._cache:
                del self._cache[query_hash]
                return 1
            return 0
        else:
            count = len(self._cache)
            self._cache.clear()
            return count

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            统计字典
        """
        total = self._metrics.total_attempts
        success_rate = self._metrics.successful_attempts / total if total > 0 else 0.0
        return {
            "total_attempts": total,
            "successful_attempts": self._metrics.successful_attempts,
            "failed_attempts": self._metrics.failed_attempts,
            "cached_attempts": self._metrics.cached_attempts,
            "degraded_attempts": self._metrics.degraded_attempts,
            "success_rate": success_rate,
            "average_latency_ms": self._metrics.average_latency_ms,
            "consecutive_failures": self._metrics.consecutive_failures,
            "health_status": self._metrics.health_status.value,
            "cache_size": len(self._cache),
        }

    # ══════════════════════════════════════════════════════════════
    # 私有方法
    # ══════════════════════════════════════════════════════════════

    def _hash_query(self, query: str) -> str:
        """计算查询哈希

        Bug 5 修复: 缓存键包含 agent_id/user_id,防止跨用户污染。
        不同 agent/user 的相同查询应产生不同缓存键。
        """
        return f"{hash(query)}_{len(query)}_{self._agent_id}_{self._user_id}"

    def _get_from_cache(self, query: str) -> Optional[RetrievalResult]:
        """从缓存获取结果"""
        query_hash = self._hash_query(query)
        if query_hash in self._cache:
            result, timestamp = self._cache[query_hash]
            if time.time() - timestamp < self._cache_ttl_seconds:
                return result
            else:
                # 缓存过期
                del self._cache[query_hash]
        return None

    def _put_to_cache(self, query: str, result: RetrievalResult) -> None:
        """存入缓存"""
        query_hash = self._hash_query(query)
        self._cache[query_hash] = (result, time.time())

        # 限制缓存大小（LRU 简单实现）
        if len(self._cache) > 1000:
            # 移除最旧的缓存
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

    def _update_health_status(self) -> None:
        """更新健康状态"""
        # 连续失败 >= 5 次：不健康
        if self._metrics.consecutive_failures >= 5:
            self._metrics.health_status = HealthStatus.UNHEALTHY
        # 连续失败 >= 2 次：降级
        elif self._metrics.consecutive_failures >= 2:
            self._metrics.health_status = HealthStatus.DEGRADED
        # 恢复正常
        else:
            self._metrics.health_status = HealthStatus.HEALTHY


# ══════════════════════════════════════════════════════════════
# 工厂函数
# ══════════════════════════════════════════════════════════════

_default_manager: Optional[CrystallizedExperienceManager] = None


def get_crystallized_experience_manager(
    crystallizer: Optional[CrystallizerProtocol] = None,
    memory_manager: Optional[Any] = None,
) -> CrystallizedExperienceManager:
    """
    获取 CrystallizedExperienceManager 单例

    Args:
        crystallizer: 结晶器实例
        memory_manager: 记忆管理器实例

    Returns:
        单例实例
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = CrystallizedExperienceManager(
            crystallizer=crystallizer,
            memory_manager=memory_manager,
        )
    return _default_manager


def reset_crystallized_experience_manager() -> None:
    """重置单例（测试用）"""
    global _default_manager
    _default_manager = None
