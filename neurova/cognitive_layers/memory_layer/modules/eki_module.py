"""
EKIModule — 集合卡尔曼反演模块

使用 EKI 方法优化记忆检索和更新
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import math
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = get_logger(__name__)


class EKIModule:
    """
    集合卡尔曼反演模块

    使用集合卡尔曼方法进行记忆优化：
    - 记忆重要性评估
    - 记忆衰减预测
    - 批量更新
    """

    def __init__(
        self,
        ensemble_size: int = 10,
        inflation_factor: float = 1.01,
    ):
        """
        Args:
            ensemble_size: 集合大小
            inflation_factor: 膨胀因子
        """
        self._ensemble_size = ensemble_size
        self._inflation_factor = inflation_factor

        self._lock = threading.RLock()
        self._initialized = False

        # 记忆状态向量
        self._memory_states: Dict[str, List[float]] = {}  # memory_id -> state vector

        # 观测数据
        self._observations: Dict[str, List[float]] = {}  # memory_id -> observations

    @property
    def name(self) -> str:
        """模块名称"""
        return "eki_module"

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("EKIModule initialized")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("EKIModule shutdown")

    def initialize_state(
        self,
        memory_id: str,
        importance: float,
        access_count: int = 0,
        age_hours: float = 0.0,
    ) -> None:
        """
        初始化记忆状态向量

        Args:
            memory_id: 记忆ID
            importance: 重要性 [0, 1]
            access_count: 访问次数
            age_hours: 年龄（小时）
        """
        with self._lock:
            # 状态向量: [importance, access_rate, decay_rate]
            state = [
                importance,
                min(1.0, access_count / 100),  # 归一化访问率
                math.exp(-0.1 * age_hours),  # 衰减因子
            ]

            # 生成集合
            ensemble = self._generate_ensemble(state)
            self._memory_states[memory_id] = ensemble

    def update_with_observation(
        self,
        memory_id: str,
        observation: float,
    ) -> None:
        """
        使用观测数据更新状态

        Args:
            memory_id: 记忆ID
            observation: 观测值 (e.g., 实际访问频率)
        """
        with self._lock:
            if memory_id not in self._memory_states:
                return

            ensemble = self._memory_states[memory_id]

            # EKI 更新步骤
            # 1. 计算集合均值
            mean_state = self._compute_mean(ensemble)

            # 2. 计算协方差
            covariance = self._compute_covariance(ensemble, mean_state)

            # 3. 计算卡尔曼增益
            kalman_gain = self._compute_kalman_gain(covariance, observation)

            # 4. 更新集合
            updated_ensemble = self._update_ensemble(ensemble, mean_state, observation, kalman_gain)

            # 5. 应用膨胀
            inflated_ensemble = self._inflate(updated_ensemble, mean_state)

            self._memory_states[memory_id] = inflated_ensemble

    def predict_importance(self, memory_id: str) -> float:
        """
        预测记忆重要性

        Args:
            memory_id: 记忆ID

        Returns:
            预测的重要性分数
        """
        with self._lock:
            ensemble = self._memory_states.get(memory_id)
            if not ensemble:
                return 0.5  # 默认值

            # 计算集合均值的第一个分量（重要性）
            mean_state = self._compute_mean(ensemble)
            return max(0.0, min(1.0, mean_state[0]))

    def predict_decay(self, memory_id: str, hours_ahead: float = 24.0) -> float:
        """
        预测记忆衰减

        Args:
            memory_id: 记忆ID
            hours_ahead: 预测未来小时数

        Returns:
            预测的保留率
        """
        with self._lock:
            ensemble = self._memory_states.get(memory_id)
            if not ensemble:
                return 1.0

            mean_state = self._compute_mean(ensemble)
            decay_rate = mean_state[2]

            # 指数衰减预测
            retention = math.exp(-decay_rate * hours_ahead / 24)
            return max(0.0, min(1.0, retention))

    def batch_update(self, updates: List[Tuple[str, float]]) -> Dict[str, float]:
        """
        批量更新

        Args:
            updates: [(memory_id, observation), ...]

        Returns:
            更新后的重要性预测
        """
        results = {}
        for memory_id, observation in updates:
            self.update_with_observation(memory_id, observation)
            results[memory_id] = self.predict_importance(memory_id)
        return results

    def get_memory_state(self, memory_id: str) -> Optional[Dict[str, float]]:
        """获取记忆状态"""
        with self._lock:
            ensemble = self._memory_states.get(memory_id)
            if not ensemble:
                return None

            mean_state = self._compute_mean(ensemble)

            return {
                "importance": mean_state[0],
                "access_rate": mean_state[1],
                "decay_rate": mean_state[2],
                "ensemble_size": len(ensemble),
            }

    def remove_memory(self, memory_id: str) -> None:
        """移除记忆状态"""
        with self._lock:
            self._memory_states.pop(memory_id, None)
            self._observations.pop(memory_id, None)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "total_memories": len(self._memory_states),
                "ensemble_size": self._ensemble_size,
                "inflation_factor": self._inflation_factor,
            }

    def _generate_ensemble(self, mean_state: List[float]) -> List[List[float]]:
        """生成集合"""
        import random

        ensemble = []
        for _ in range(self._ensemble_size):
            perturbed = [max(0.0, min(1.0, v + random.gauss(0, 0.05))) for v in mean_state]
            ensemble.append(perturbed)

        return ensemble

    def _compute_mean(self, ensemble: List[List[float]]) -> List[float]:
        """计算集合均值"""
        if not ensemble:
            return [0.0, 0.0, 0.0]

        n = len(ensemble[0])
        mean = [0.0] * n

        for state in ensemble:
            for i in range(n):
                mean[i] += state[i]

        return [v / len(ensemble) for v in mean]

    def _compute_covariance(
        self,
        ensemble: List[List[float]],
        mean: List[float],
    ) -> List[List[float]]:
        """计算协方差矩阵"""
        n = len(mean)
        cov = [[0.0] * n for _ in range(n)]

        for state in ensemble:
            for i in range(n):
                for j in range(n):
                    cov[i][j] += (state[i] - mean[i]) * (state[j] - mean[j])

        k = len(ensemble) - 1
        if k > 0:
            for i in range(n):
                for j in range(n):
                    cov[i][j] /= k

        return cov

    def _compute_kalman_gain(
        self,
        covariance: List[List[float]],
        observation: float,
    ) -> List[float]:
        """计算卡尔曼增益"""
        # 简化实现
        n = len(covariance)
        gain = [covariance[0][i] / (covariance[0][0] + 0.1) for i in range(n)]
        return gain

    def _update_ensemble(
        self,
        ensemble: List[List[float]],
        mean: List[float],
        observation: float,
        kalman_gain: List[float],
    ) -> List[List[float]]:
        """更新集合"""
        innovation = observation - mean[0]

        updated = []
        for state in ensemble:
            new_state = [state[i] + kalman_gain[i] * innovation for i in range(len(state))]
            updated.append(new_state)

        return updated

    def _inflate(
        self,
        ensemble: List[List[float]],
        mean: List[float],
    ) -> List[List[float]]:
        """应用膨胀"""
        inflated = []
        for state in ensemble:
            new_state = [mean[i] + self._inflation_factor * (state[i] - mean[i]) for i in range(len(state))]
            inflated.append(new_state)

        return inflated
