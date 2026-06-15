"""
EKI认知优化器 - 核心编排器

功能:
1. 编排所有EKI组件
2. 管理记忆强化决策
3. 提供统一的任务价值评估接口
4. 支持批量处理和异步更新
"""

import datetime
import logging
import math
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# E-1: 正确检查 numpy 是否可用
try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


# ────── Enums ──────


class TaskValue(Enum):
    """任务价值级别"""

    TRIVIAL = "trivial"  # 微不足道
    LOW = "low"  # 低价值
    MEDIUM = "medium"  # 中等价值
    HIGH = "high"  # 高价值
    CRITICAL = "critical"  # 关键价值


class ReinforcementAction(Enum):
    """强化动作"""

    NONE = "none"  # 不强化
    REVIEW = "review"  # 复习
    CONSOLIDATE = "consolidate"  # 巩固
    COMPRESS = "compress"  # 压缩
    DISCARD = "discard"  # 丢弃


# ────── Data Models ──────


@dataclass
class TaskResult:
    """任务处理结果"""

    task_id: str = ""
    value: TaskValue = TaskValue.MEDIUM
    score: float = 0.5
    confidence: float = 0.5
    information_gain: float = 0.0
    reinforcement: ReinforcementAction = ReinforcementAction.NONE
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))


@dataclass
class MemoryState:
    """记忆状态追踪"""

    memory_id: str = ""
    importance: float = 50.0
    access_count: int = 0
    last_access: Optional[datetime.datetime] = None
    decay_rate: float = 1.0
    reinforcement_count: int = 0
    predicted_retention: float = 1.0


# ────── 主类 ──────


class EKICognitiveOptimizer:
    """
    EKI认知优化器

    使用集合卡尔曼反演（EKI）方法进行无梯度贝叶斯推断，
    优化记忆强化决策和任务价值评估。
    """

    def __init__(self, ensemble_size: int = 50, learning_rate: float = 0.1):
        """
        初始化EKI优化器

        参数:
            ensemble_size: 集合大小（粒子数）
            learning_rate: 学习率
        """
        # E-2: 校验 ensemble_size
        if not isinstance(ensemble_size, int) or ensemble_size <= 0:
            raise ValueError(f"ensemble_size must be a positive integer, got {ensemble_size}")
        if not isinstance(learning_rate, (int, float)) or learning_rate <= 0:
            raise ValueError(f"learning_rate must be a positive number, got {learning_rate}")
        self._ensemble_size = ensemble_size
        self._learning_rate = learning_rate
        self._lock = threading.RLock()

        # 记忆状态
        self._memory_states: Dict[str, MemoryState] = {}

        # EKI 集合（参数粒子）
        self._ensemble: List[Dict[str, float]] = []
        self._init_ensemble()

        # 任务历史
        self._task_history: List[TaskResult] = []
        self._max_history = 1000

        # 统计
        self._total_tasks = 0
        self._total_reinforcements = 0

        logger.info("EKICognitiveOptimizer initialized (ensemble_size=%s)", ensemble_size)

    def _init_ensemble(self):
        """初始化参数集合"""
        self._ensemble = []
        for _ in range(self._ensemble_size):
            particle = {
                "importance_weight": 0.5 + (hash(str(_)) % 100) / 200.0,
                "decay_factor": 0.8 + (hash(str(_ * 7)) % 40) / 200.0,
                "novelty_bonus": 0.1 + (hash(str(_ * 13)) % 20) / 200.0,
                "frequency_penalty": 0.05 + (hash(str(_ * 17)) % 10) / 200.0,
            }
            self._ensemble.append(particle)

    def register_memory(self, memory_id: str, importance: float = 50.0, access_count: int = 0) -> MemoryState:
        """
        注册记忆到优化器

        参数:
            memory_id: 记忆ID
            importance: 初始重要性
            access_count: 访问次数

        返回:
            MemoryState: 记忆状态对象
        """
        with self._lock:
            state = MemoryState(
                memory_id=memory_id,
                importance=importance,
                access_count=access_count,
                last_access=datetime.datetime.now(datetime.timezone.utc),
            )
            self._memory_states[memory_id] = state
            return state

    def process_task(self, task_id: str, content: str, context: Optional[Dict[str, Any]] = None) -> TaskResult:
        """
        处理任务并评估价值

        参数:
            task_id: 任务ID
            content: 任务内容
            context: 上下文信息

        返回:
            TaskResult: 任务处理结果
        """
        with self._lock:
            self._total_tasks += 1

        # 计算任务价值
        value, score, confidence = self._compute_task_value(content, context)

        # 计算信息增益
        info_gain = self._compute_information_gain(content, context)

        # 决定强化动作
        reinforcement = self.recommend_reinforcement(score, info_gain)

        result = TaskResult(
            task_id=task_id,
            value=value,
            score=score,
            confidence=confidence,
            information_gain=info_gain,
            reinforcement=reinforcement,
            metadata=context or {},
        )

        # 记录历史
        with self._lock:
            self._task_history.append(result)
            if len(self._task_history) > self._max_history:
                self._task_history = self._task_history[-self._max_history :]

        return result

    def _compute_task_value(
        self, content: str, context: Optional[Dict[str, Any]] = None
    ) -> Tuple[TaskValue, float, float]:
        """
        计算任务价值

        返回:
            Tuple[TaskValue, float, float]: (价值级别, 分数, 置信度)
        """
        # 基础分数
        base_score = 0.5

        # 内容长度因子
        length_factor = min(1.0, len(content) / 500.0) * 0.2

        # 关键词因子
        keywords = {"重要", "关键", "紧急", "critical", "important", "urgent", "核心"}
        keyword_factor = sum(1 for kw in keywords if kw in content.lower()) * 0.1

        # 上下文因子
        context_factor = 0.0
        if context:
            if context.get("priority", 0) > 5:
                context_factor += 0.2
            if context.get("user_initiated", False):
                context_factor += 0.1

        # 集成平均
        ensemble_scores = []
        for particle in self._ensemble:
            particle_score = (
                base_score * particle["importance_weight"]
                + length_factor
                + keyword_factor
                + context_factor
                + particle["novelty_bonus"]
            )
            ensemble_scores.append(particle_score)

        score = sum(ensemble_scores) / len(ensemble_scores) if ensemble_scores else 0.5
        score = max(0.0, min(1.0, score))

        # 置信度 = 1 - 集合方差
        if len(ensemble_scores) > 1:
            variance = sum((s - score) ** 2 for s in ensemble_scores) / len(ensemble_scores)
            confidence = max(0.1, 1.0 - math.sqrt(variance))
        else:
            confidence = 0.5

        # 映射到价值级别
        if score >= 0.8:
            value = TaskValue.CRITICAL
        elif score >= 0.6:
            value = TaskValue.HIGH
        elif score >= 0.4:
            value = TaskValue.MEDIUM
        elif score >= 0.2:
            value = TaskValue.LOW
        else:
            value = TaskValue.TRIVIAL

        return value, score, confidence

    def _compute_information_gain(self, content: str, context: Optional[Dict[str, Any]] = None) -> float:
        """计算信息增益"""
        # 简化实现：基于内容的新颖性和复杂度
        words = content.split()
        unique_words = len(set(words))
        total_words = len(words) if words else 1

        # 词汇丰富度
        lexical_diversity = unique_words / total_words

        # 长度因子
        length_factor = min(1.0, total_words / 200.0)

        # 信息增益 = 词汇丰富度 * 长度因子
        return lexical_diversity * length_factor

    def _update_with_feedback(self, memory_id: str, success: bool, feedback_score: float = 0.5):
        """
        使用反馈更新EKI集合

        参数:
            memory_id: 记忆ID
            success: 是否成功
            feedback_score: 反馈分数
        """
        with self._lock:
            state = self._memory_states.get(memory_id)
            if not state:
                return

            state.access_count += 1
            state.last_access = datetime.datetime.now(datetime.timezone.utc)

            # 更新集合粒子（简化版EKI更新）
            observation = feedback_score if success else 0.0
            for particle in self._ensemble:
                # 计算预测
                prediction = particle["importance_weight"] * state.importance / 100.0 + particle["novelty_bonus"]

                # 计算创新
                innovation = observation - prediction

                # 卡尔曼增益
                kalman_gain = particle["importance_weight"] / (particle["importance_weight"] + 1.0)

                # 更新参数
                particle["importance_weight"] += self._learning_rate * kalman_gain * innovation
                particle["importance_weight"] = max(0.01, min(1.0, particle["importance_weight"]))

            # E-4: 粒子多样性监测 — 防止 ensemble collapse
            self._check_and_restore_diversity()

    def _check_and_restore_diversity(self):
        """E-4: 检查粒子多样性,方差过低时加抖动防止 ensemble collapse"""
        if len(self._ensemble) < 2:
            return

        weights = [p["importance_weight"] for p in self._ensemble]
        mean_w = sum(weights) / len(weights)
        variance = sum((w - mean_w) ** 2 for w in weights) / len(weights)

        # 多样性阈值: 方差低于 0.001 视为塌缩
        if variance < 0.001:
            logger.warning("EKI ensemble collapse detected (variance=%.6f), adding jitter", variance)
            import random

            for i, particle in enumerate(self._ensemble):
                jitter = random.uniform(-0.05, 0.05)
                particle["importance_weight"] = max(0.01, min(1.0, mean_w + jitter))
                particle["novelty_bonus"] = max(0.01, min(0.5, particle["novelty_bonus"] + jitter * 0.5))

    def recommend_reinforcement(self, score: float, information_gain: float) -> ReinforcementAction:
        """
        推荐强化动作

        参数:
            score: 任务价值分数
            information_gain: 信息增益

        返回:
            ReinforcementAction: 推荐的强化动作
        """
        if score >= 0.8:
            return ReinforcementAction.CONSOLIDATE
        elif score >= 0.6:
            return ReinforcementAction.REVIEW
        elif score >= 0.4 and information_gain > 0.3:
            return ReinforcementAction.REVIEW
        elif score < 0.2:
            return ReinforcementAction.DISCARD
        else:
            return ReinforcementAction.NONE

    def predict_memory_decay(self, memory_id: str, hours_ahead: float = 24.0) -> float:
        """
        预测记忆衰减

        参数:
            memory_id: 记忆ID
            hours_ahead: 预测时间（小时）

        返回:
            float: 预测保留率 (0.0-1.0)
        """
        with self._lock:
            state = self._memory_states.get(memory_id)
            if not state:
                return 0.0

            # 使用集合平均的衰减因子
            avg_decay = sum(p["decay_factor"] for p in self._ensemble) / len(self._ensemble)

            # 艾宾浩斯遗忘曲线
            retention = math.exp(-state.decay_rate * hours_ahead / (24.0 * avg_decay))

            # 访问次数提升保留率
            access_bonus = min(0.3, state.access_count * 0.05)
            retention = min(1.0, retention + access_bonus)

            state.predicted_retention = retention
            return retention

    def batch_update(self, updates: List[Tuple[str, bool, float]]):
        """
        批量更新

        参数:
            updates: List of (memory_id, success, feedback_score)
        """
        for memory_id, success, score in updates:
            self._update_with_feedback(memory_id, success, score)

        with self._lock:
            self._total_reinforcements += len(updates)

    def _flush_updates(self):
        """刷新所有待处理的更新"""
        # 当前实现实时更新，此方法用于未来扩展

    def train_surrogate(self, training_data: List[Tuple[str, float]]):
        """
        训练代理模型

        参数:
            training_data: List of (content, target_score)
        """
        # 简化实现：使用训练数据调整集合参数
        for content, target in training_data:
            words = content.split()
            complexity = len(set(words)) / max(1, len(words))

            for particle in self._ensemble:
                # 调整参数以匹配目标
                error = target - complexity
                particle["novelty_bonus"] += self._learning_rate * error * 0.1
                particle["novelty_bonus"] = max(0.0, min(0.5, particle["novelty_bonus"]))

        logger.info("Surrogate model trained on %s samples", len(training_data))

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            avg_importance = 0.0
            avg_decay = 0.0
            if self._ensemble:
                avg_importance = sum(p["importance_weight"] for p in self._ensemble) / len(self._ensemble)
                avg_decay = sum(p["decay_factor"] for p in self._ensemble) / len(self._ensemble)

            return {
                "total_tasks": self._total_tasks,
                "total_reinforcements": self._total_reinforcements,
                "registered_memories": len(self._memory_states),
                "ensemble_size": self._ensemble_size,
                "avg_importance_weight": round(avg_importance, 4),
                "avg_decay_factor": round(avg_decay, 4),
                "history_size": len(self._task_history),
            }

    def reset(self):
        """重置优化器"""
        with self._lock:
            self._memory_states.clear()
            self._task_history.clear()
            self._total_tasks = 0
            self._total_reinforcements = 0
            self._init_ensemble()


# ────── 单例管理 ──────

_optimizer_instance: Optional[EKICognitiveOptimizer] = None
_instance_lock = threading.Lock()


def get_cognitive_optimizer(**kwargs) -> EKICognitiveOptimizer:
    """获取认知优化器单例"""
    global _optimizer_instance
    if _optimizer_instance is None:
        with _instance_lock:
            if _optimizer_instance is None:
                _optimizer_instance = EKICognitiveOptimizer(**kwargs)
    return _optimizer_instance


def reset_cognitive_optimizer():
    """重置认知优化器单例"""
    global _optimizer_instance
    with _instance_lock:
        _optimizer_instance = None
