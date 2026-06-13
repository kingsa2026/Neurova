"""
WeightAdjuster — 通道权重动态调整

基于用户反馈动态调整通道权重，保持权重归一化。
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class WeightAdjuster:
    """通道权重动态调整器"""

    DEFAULT_WEIGHTS = {
        "temperature": 0.25,
        "text": 0.30,
        "category": 0.15,
        "graph": 0.10,
        "emotion": 0.10,
        "voice": 0.10,
    }

    def __init__(
        self,
        initial_weights: Dict[str, float] = None,
        learning_rate: float = 0.05,
        min_weight: float = 0.05,
        max_weight: float = 0.80,
    ):
        self._weights = dict(initial_weights or self.DEFAULT_WEIGHTS)
        self.learning_rate = learning_rate
        self.min_weight = min_weight
        self.max_weight = max_weight

    def get_weights(self) -> Dict[str, float]:
        """获取当前权重（归一化后）"""
        return self._normalize(dict(self._weights))

    def adjust(self, channel: str, positive: bool) -> None:
        """根据反馈调整权重

        Args:
            channel: 通道名称
            positive: True=正反馈（增加权重），False=负反馈（减少权重）
        """
        if channel not in self._weights:
            self._weights[channel] = 0.1

        delta = self.learning_rate if positive else -self.learning_rate
        self._weights[channel] += delta

        # 边界限制
        self._weights[channel] = max(self.min_weight, min(self.max_weight, self._weights[channel]))

    def _normalize(self, weights: Dict[str, float]) -> Dict[str, float]:
        """归一化权重使总和为 1.0"""
        total = sum(weights.values())
        if total <= 0:
            return weights
        return {k: v / total for k, v in weights.items()}
