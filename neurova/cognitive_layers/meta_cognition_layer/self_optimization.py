"""
自我优化模块

优化温度参数、修剪低价值记忆、重构关联
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class OptimizationType(str, Enum):
    """优化类型"""

    TEMPERATURE = "temperature"  # 温度优化
    PRUNING = "pruning"  # 记忆修剪
    RESTRUCTURING = "restructuring"  # 关联重构
    CONSOLIDATION = "consolidation"  # 记忆整合


@dataclass
class OptimizationResult:
    """优化结果"""

    optimization_id: str
    optimization_type: OptimizationType
    timestamp: datetime.datetime
    success: bool
    description: str
    metrics_before: Dict[str, float] = field(default_factory=dict)
    metrics_after: Dict[str, float] = field(default_factory=dict)
    improvements: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "optimization_id": self.optimization_id,
            "optimization_type": self.optimization_type.value,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "description": self.description,
            "metrics_before": self.metrics_before,
            "metrics_after": self.metrics_after,
            "improvements": self.improvements,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


class SelfOptimization:
    """自我优化模块

    提供记忆系统的自动优化能力。
    """

    def __init__(
        self,
        memory_manager: Any = None,
        temperature_engine: Any = None,
        max_optimization_history: int = 100,
    ):
        """初始化自我优化模块

        Args:
            memory_manager: 记忆管理器
            temperature_engine: 温度引擎
            max_optimization_history: 最大优化历史数
        """
        self._memory_manager = memory_manager
        self._temperature_engine = temperature_engine
        self._max_optimization_history = max_optimization_history

        # 优化历史
        self._optimization_history: List[OptimizationResult] = []

        # 统计信息
        self._stats = {
            "total_optimizations": 0,
            "successful_optimizations": 0,
            "failed_optimizations": 0,
            "memories_pruned": 0,
            "temperature_adjustments": 0,
        }

        # 线程安全
        self._lock = threading.RLock()

        logger.info("SelfOptimization 初始化完成")

    def optimize_temperature(
        self,
        memories: List[Any],
        target_distribution: Optional[Dict[str, float]] = None,
    ) -> OptimizationResult:
        """优化温度参数

        Args:
            memories: 记忆列表
            target_distribution: 目标温度分布

        Returns:
            优化结果
        """
        start_time = time.time()

        with self._lock:
            try:
                # 默认目标分布
                if target_distribution is None:
                    target_distribution = {
                        "hot": 0.2,  # 20% 高温记忆
                        "warm": 0.5,  # 50% 中温记忆
                        "cold": 0.3,  # 30% 低温记忆
                    }

                # 计算当前温度分布
                current_distribution = self._calculate_temperature_distribution(memories)

                # 计算差异
                distribution_diff = {}
                for temp_level in ["hot", "warm", "cold"]:
                    current = current_distribution.get(temp_level, 0.0)
                    target = target_distribution.get(temp_level, 0.0)
                    distribution_diff[temp_level] = abs(current - target)

                # 计算需要调整的记忆数量
                adjustments = self._calculate_temperature_adjustments(
                    memories, current_distribution, target_distribution
                )

                # 应用调整
                adjusted_count = 0
                if self._temperature_engine:
                    for memory_id, new_temp in adjustments:
                        try:
                            self._temperature_engine.set_temperature(memory_id, new_temp)
                            adjusted_count += 1
                        except Exception as e:
                            logger.warning("调整温度失败: %s - %s", memory_id, e)

                # 创建结果
                result = OptimizationResult(
                    optimization_id=f"temp_opt_{int(time.time() * 1000)}",
                    optimization_type=OptimizationType.TEMPERATURE,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                    success=True,
                    description=f"温度优化完成，调整了 {adjusted_count} 条记忆",
                    metrics_before=current_distribution,
                    metrics_after=target_distribution,
                    improvements=[
                        f"调整了 {adjusted_count} 条记忆的温度",
                        f"温度分布更接近目标",
                    ],
                    duration_ms=(time.time() - start_time) * 1000,
                    metadata={
                        "adjustments_count": adjusted_count,
                        "distribution_diff": distribution_diff,
                    },
                )

                # 更新历史和统计
                self._optimization_history.append(result)
                if len(self._optimization_history) > self._max_optimization_history:
                    self._optimization_history = self._optimization_history[-self._max_optimization_history :]

                self._stats["total_optimizations"] += 1
                self._stats["successful_optimizations"] += 1
                self._stats["temperature_adjustments"] += adjusted_count

                logger.info("温度优化完成: 调整了 %s 条记忆", adjusted_count)
                return result
            except Exception as e:
                logger.error("温度优化失败: %s", e)

                result = OptimizationResult(
                    optimization_id=f"temp_opt_fail_{int(time.time() * 1000)}",
                    optimization_type=OptimizationType.TEMPERATURE,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                    success=False,
                    description=f"温度优化失败: {str(e)}",
                    duration_ms=(time.time() - start_time) * 1000,
                    metadata={"error": str(e)},
                )

                self._optimization_history.append(result)
                self._stats["total_optimizations"] += 1
                self._stats["failed_optimizations"] += 1

                return result

    def _calculate_temperature_distribution(self, memories: List[Any]) -> Dict[str, float]:
        """计算温度分布

        Args:
            memories: 记忆列表

        Returns:
            温度分布字典
        """
        if not memories:
            return {"hot": 0.0, "warm": 0.0, "cold": 0.0}

        hot_count = 0
        warm_count = 0
        cold_count = 0

        for memory in memories:
            temperature = getattr(memory, "temperature", None)
            if temperature is None:
                # 尝试从温度引擎获取
                if self._temperature_engine and hasattr(memory, "id"):
                    temperature = self._temperature_engine.get_temperature(memory.id)

                if temperature is None:
                    temperature = 0.5  # 默认中温

            if temperature > 0.7:
                hot_count += 1
            elif temperature > 0.3:
                warm_count += 1
            else:
                cold_count += 1

        total = len(memories)
        return {
            "hot": hot_count / total,
            "warm": warm_count / total,
            "cold": cold_count / total,
        }

    def _calculate_temperature_adjustments(
        self,
        memories: List[Any],
        current_distribution: Dict[str, float],
        target_distribution: Dict[str, float],
    ) -> List[Tuple[str, float]]:
        """计算温度调整

        Args:
            memories: 记忆列表
            current_distribution: 当前分布
            target_distribution: 目标分布

        Returns:
            [(memory_id, new_temperature), ...]
        """
        adjustments = []

        # 计算需要调整的数量
        total_memories = len(memories)
        if total_memories == 0:
            return adjustments

        # 计算每个温度级别的目标数量
        target_counts = {
            "hot": int(total_memories * target_distribution.get("hot", 0.2)),
            "warm": int(total_memories * target_distribution.get("warm", 0.5)),
            "cold": int(total_memories * target_distribution.get("cold", 0.3)),
        }

        # 计算当前数量
        current_counts = {
            "hot": int(total_memories * current_distribution.get("hot", 0.0)),
            "warm": int(total_memories * current_distribution.get("warm", 0.0)),
            "cold": int(total_memories * current_distribution.get("cold", 0.0)),
        }

        # 计算差异
        diff_counts = {
            "hot": target_counts["hot"] - current_counts["hot"],
            "warm": target_counts["warm"] - current_counts["warm"],
            "cold": target_counts["cold"] - current_counts["cold"],
        }

        # 按温度排序记忆
        memory_temperatures = []
        for memory in memories:
            memory_id = getattr(memory, "id", str(id(memory)))
            temperature = getattr(memory, "temperature", None)

            if temperature is None and self._temperature_engine:
                temperature = self._temperature_engine.get_temperature(memory_id)

            if temperature is None:
                temperature = 0.5

            memory_temperatures.append((memory_id, temperature))

        # 按温度排序
        memory_temperatures.sort(key=lambda x: x[1])

        # 调整低温记忆（如果需要增加高温）
        if diff_counts["hot"] > 0:
            # 从最低温的记忆中选择一些提升为高温
            for i in range(min(diff_counts["hot"], len(memory_temperatures))):
                memory_id, current_temp = memory_temperatures[i]
                new_temp = min(1.0, current_temp + 0.3)
                adjustments.append((memory_id, new_temp))

        # 调整高温记忆（如果需要降低）
        if diff_counts["hot"] < 0:
            # 从最高温的记忆中选择一些降低
            high_temp_memories = memory_temperatures[-abs(diff_counts["hot"]) :]
            for memory_id, current_temp in high_temp_memories:
                new_temp = max(0.0, current_temp - 0.3)
                adjustments.append((memory_id, new_temp))

        return adjustments

    def prune_memories(
        self,
        memories: List[Any],
        importance_threshold: float = 0.2,
        age_threshold_days: int = 90,
        max_prune_ratio: float = 0.1,
    ) -> OptimizationResult:
        """修剪低价值记忆

        Args:
            memories: 记忆列表
            importance_threshold: 重要性阈值
            age_threshold_days: 年龄阈值（天）
            max_prune_ratio: 最大修剪比例

        Returns:
            优化结果
        """
        start_time = time.time()

        with self._lock:
            try:
                current_time = datetime.datetime.now(datetime.timezone.utc)

                # 筛选需要修剪的记忆
                candidates = []
                for memory in memories:
                    importance = getattr(memory, "importance", 0.5)
                    timestamp = getattr(memory, "timestamp", None)

                    if timestamp is None:
                        continue

                    # 计算年龄
                    age_days = (current_time - timestamp).total_seconds() / 86400

                    # 检查是否满足修剪条件
                    if importance < importance_threshold and age_days > age_threshold_days:
                        candidates.append((memory, importance, age_days))

                # 限制修剪数量
                max_prune_count = int(len(memories) * max_prune_ratio)
                candidates.sort(key=lambda x: x[1])  # 按重要性排序
                candidates = candidates[:max_prune_count]

                # 执行修剪
                pruned_count = 0
                if self._memory_manager:
                    for memory, importance, age_days in candidates:
                        try:
                            memory_id = getattr(memory, "id", str(id(memory)))
                            self._memory_manager.delete(memory_id)
                            pruned_count += 1
                        except Exception as e:
                            logger.warning("修剪记忆失败: %s", e)

                # 创建结果
                result = OptimizationResult(
                    optimization_id=f"prune_{int(time.time() * 1000)}",
                    optimization_type=OptimizationType.PRUNING,
                    timestamp=current_time,
                    success=True,
                    description=f"记忆修剪完成，删除了 {pruned_count} 条低价值记忆",
                    metrics_before={
                        "total_memories": len(memories),
                        "candidates": len(candidates),
                    },
                    metrics_after={
                        "pruned_count": pruned_count,
                        "remaining": len(memories) - pruned_count,
                    },
                    improvements=[
                        f"删除了 {pruned_count} 条低价值记忆",
                        f"释放了存储空间",
                    ],
                    duration_ms=(time.time() - start_time) * 1000,
                    metadata={
                        "importance_threshold": importance_threshold,
                        "age_threshold_days": age_threshold_days,
                        "max_prune_ratio": max_prune_ratio,
                    },
                )

                # 更新历史和统计
                self._optimization_history.append(result)
                if len(self._optimization_history) > self._max_optimization_history:
                    self._optimization_history = self._optimization_history[-self._max_optimization_history :]

                self._stats["total_optimizations"] += 1
                self._stats["successful_optimizations"] += 1
                self._stats["memories_pruned"] += pruned_count

                logger.info("记忆修剪完成: 删除了 %s 条记忆", pruned_count)
                return result
            except Exception as e:
                logger.error("记忆修剪失败: %s", e)

                result = OptimizationResult(
                    optimization_id=f"prune_fail_{int(time.time() * 1000)}",
                    optimization_type=OptimizationType.PRUNING,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                    success=False,
                    description=f"记忆修剪失败: {str(e)}",
                    duration_ms=(time.time() - start_time) * 1000,
                    metadata={"error": str(e)},
                )

                self._optimization_history.append(result)
                self._stats["total_optimizations"] += 1
                self._stats["failed_optimizations"] += 1

                return result

    def restructure_associations(
        self,
        memories: List[Any],
        similarity_threshold: float = 0.6,
        max_associations_per_memory: int = 10,
    ) -> OptimizationResult:
        """重构关联

        Args:
            memories: 记忆列表
            similarity_threshold: 相似度阈值
            max_associations_per_memory: 每个记忆的最大关联数

        Returns:
            优化结果
        """
        start_time = time.time()

        with self._lock:
            try:
                # 计算记忆之间的相似度
                associations = self._calculate_associations(memories, similarity_threshold, max_associations_per_memory)

                # 应用关联
                applied_count = 0
                if self._memory_manager:
                    for memory_id, related_ids in associations.items():
                        try:
                            # 更新记忆的关联
                            if hasattr(self._memory_manager, "update_associations"):
                                self._memory_manager.update_associations(memory_id, related_ids)
                                applied_count += 1
                        except Exception as e:
                            logger.warning("更新关联失败: %s - %s", memory_id, e)

                # 创建结果
                result = OptimizationResult(
                    optimization_id=f"restructure_{int(time.time() * 1000)}",
                    optimization_type=OptimizationType.RESTRUCTURING,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                    success=True,
                    description=f"关联重构完成，更新了 {applied_count} 个记忆的关联",
                    metrics_before={
                        "total_memories": len(memories),
                        "associations_found": len(associations),
                    },
                    metrics_after={
                        "applied_count": applied_count,
                    },
                    improvements=[
                        f"更新了 {applied_count} 个记忆的关联",
                        f"建立了 {sum(len(ids) for ids in associations.values())} 个新关联",
                    ],
                    duration_ms=(time.time() - start_time) * 1000,
                    metadata={
                        "similarity_threshold": similarity_threshold,
                        "max_associations_per_memory": max_associations_per_memory,
                    },
                )

                # 更新历史和统计
                self._optimization_history.append(result)
                if len(self._optimization_history) > self._max_optimization_history:
                    self._optimization_history = self._optimization_history[-self._max_optimization_history :]

                self._stats["total_optimizations"] += 1
                self._stats["successful_optimizations"] += 1

                logger.info("关联重构完成: 更新了 %s 个记忆", applied_count)
                return result
            except Exception as e:
                logger.error("关联重构失败: %s", e)

                result = OptimizationResult(
                    optimization_id=f"restructure_fail_{int(time.time() * 1000)}",
                    optimization_type=OptimizationType.RESTRUCTURING,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                    success=False,
                    description=f"关联重构失败: {str(e)}",
                    duration_ms=(time.time() - start_time) * 1000,
                    metadata={"error": str(e)},
                )

                self._optimization_history.append(result)
                self._stats["total_optimizations"] += 1
                self._stats["failed_optimizations"] += 1

                return result

    def _calculate_associations(
        self,
        memories: List[Any],
        similarity_threshold: float,
        max_associations: int,
    ) -> Dict[str, List[str]]:
        """计算记忆关联

        Args:
            memories: 记忆列表
            similarity_threshold: 相似度阈值
            max_associations: 最大关联数

        Returns:
            {memory_id: [related_memory_ids]}
        """
        associations: Dict[str, List[str]] = defaultdict(list)

        # 提取记忆特征
        memory_features = []
        for memory in memories:
            memory_id = getattr(memory, "id", str(id(memory)))
            content = getattr(memory, "content", "")
            tags = getattr(memory, "tags", [])

            # 简单的特征提取
            features = {
                "id": memory_id,
                "content": content.lower(),
                "tags": set(tags),
            }
            memory_features.append(features)

        # 计算两两相似度
        for i in range(len(memory_features)):
            for j in range(i + 1, len(memory_features)):
                feature_i = memory_features[i]
                feature_j = memory_features[j]

                # 计算相似度
                similarity = self._calculate_similarity(feature_i, feature_j)

                if similarity >= similarity_threshold:
                    # 添加双向关联
                    if len(associations[feature_i["id"]]) < max_associations:
                        associations[feature_i["id"]].append(feature_j["id"])

                    if len(associations[feature_j["id"]]) < max_associations:
                        associations[feature_j["id"]].append(feature_i["id"])

        return dict(associations)

    def _calculate_similarity(self, feature_i: Dict[str, Any], feature_j: Dict[str, Any]) -> float:
        """计算特征相似度

        Args:
            feature_i: 特征i
            feature_j: 特征j

        Returns:
            相似度 (0-1)
        """
        # 标签相似度
        tags_i = feature_i.get("tags", set())
        tags_j = feature_j.get("tags", set())

        if tags_i and tags_j:
            intersection = len(tags_i & tags_j)
            union = len(tags_i | tags_j)
            tag_similarity = intersection / union if union > 0 else 0.0
        else:
            tag_similarity = 0.0

        # 内容相似度（简单的字符重叠）
        content_i = feature_i.get("content", "")
        content_j = feature_j.get("content", "")

        if content_i and content_j:
            # 简单的字符级Jaccard相似度
            set_i = set(content_i[:100])  # 只取前100字符
            set_j = set(content_j[:100])

            intersection = len(set_i & set_j)
            union = len(set_i | set_j)
            content_similarity = intersection / union if union > 0 else 0.0
        else:
            content_similarity = 0.0

        # 加权平均
        return tag_similarity * 0.6 + content_similarity * 0.4

    def get_optimization_history(
        self,
        limit: int = 50,
        optimization_type: Optional[OptimizationType] = None,
    ) -> List[OptimizationResult]:
        """获取优化历史

        Args:
            limit: 返回数量限制
            optimization_type: 优化类型过滤

        Returns:
            优化结果列表
        """
        with self._lock:
            history = self._optimization_history.copy()

            if optimization_type:
                history = [r for r in history if r.optimization_type == optimization_type]

            return history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                **self._stats,
                "optimization_history_size": len(self._optimization_history),
                "success_rate": (
                    self._stats["successful_optimizations"] / self._stats["total_optimizations"]
                    if self._stats["total_optimizations"] > 0
                    else 0.0
                ),
            }

    def clear(self) -> None:
        """清空优化历史"""
        with self._lock:
            self._optimization_history.clear()

            self._stats = {
                "total_optimizations": 0,
                "successful_optimizations": 0,
                "failed_optimizations": 0,
                "memories_pruned": 0,
                "temperature_adjustments": 0,
            }

            logger.info("SelfOptimization 历史已清空")


# 全局实例管理
_self_optimization_instances: Dict[str, SelfOptimization] = {}
_self_optimization_lock = threading.Lock()


def get_self_optimization(
    memory_manager: Any = None,
    temperature_engine: Any = None,
    instance_id: str = "default",
) -> SelfOptimization:
    """获取自我优化模块单例

    Args:
        memory_manager: 记忆管理器
        temperature_engine: 温度引擎
        instance_id: 实例ID

    Returns:
        自我优化模块实例
    """
    global _self_optimization_instances

    with _self_optimization_lock:
        if instance_id not in _self_optimization_instances:
            _self_optimization_instances[instance_id] = SelfOptimization(
                memory_manager=memory_manager,
                temperature_engine=temperature_engine,
            )
        return _self_optimization_instances[instance_id]


def reset_self_optimization(instance_id: Optional[str] = None) -> None:
    """重置自我优化模块单例

    Args:
        instance_id: 实例ID，为None时重置所有
    """
    global _self_optimization_instances

    with _self_optimization_lock:
        if instance_id is None:
            _self_optimization_instances.clear()
        elif instance_id in _self_optimization_instances:
            _self_optimization_instances[instance_id].clear()
            del _self_optimization_instances[instance_id]


def reset_all_self_optimization() -> None:
    """重置所有自我优化模块单例"""
    reset_self_optimization(None)
