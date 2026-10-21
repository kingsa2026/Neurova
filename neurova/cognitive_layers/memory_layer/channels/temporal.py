"""
TemporalDecay — 时序衰减函数

支持多种衰减曲线：指数、线性、对数。
"""

from neurova.core.logger import get_logger
import math
from datetime import datetime, timezone
from typing import Optional

logger = get_logger(__name__)


class TemporalDecay:
    """时序衰减计算器"""

    def __init__(
        self,
        curve: str = "exponential",
        half_life_days: float = 30.0,
        min_score: float = 0.1,
    ):
        """
        Args:
            curve: 衰减曲线类型 ("exponential", "linear", "logarithmic")
            half_life_days: 半衰期（天）
            min_score: 最低分数
        """
        self.curve = curve
        self.half_life_days = half_life_days
        self.min_score = min_score
        # 衰减率 λ = ln(2) / half_life
        self._decay_rate = math.log(2) / half_life_days

    def compute(self, timestamp: Optional[str]) -> float:
        """计算时序衰减分数

        Args:
            timestamp: ISO 格式时间戳，None 或空字符串返回 1.0

        Returns:
            衰减分数 (min_score ~ 1.0)
        """
        if not timestamp:
            return 1.0

        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return 1.0

        now = datetime.now(timezone.utc)
        age_days = (now - dt).total_seconds() / 86400

        if age_days <= 0:
            return 1.0

        if self.curve == "exponential":
            score = math.exp(-self._decay_rate * age_days)
        elif self.curve == "linear":
            score = max(0.0, 1.0 - age_days / (self.half_life_days * 2))
        elif self.curve == "logarithmic":
            score = 1.0 / (1.0 + math.log1p(age_days / self.half_life_days))
        else:
            score = math.exp(-self._decay_rate * age_days)

        return max(self.min_score, score)
