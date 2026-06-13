"""
ThresholdConfig — 通道激活阈值配置

支持 per-channel 阈值和默认阈值，可从 dict 加载。
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class ThresholdConfig:
    """通道激活阈值配置"""

    def __init__(self, default_threshold: float = 0.3):
        self.default_threshold = default_threshold
        self._thresholds: Dict[str, float] = {}

    def get_threshold(self, channel_name: str) -> float:
        """获取通道的激活阈值"""
        return self._thresholds.get(channel_name, self.default_threshold)

    def set_threshold(self, channel_name: str, threshold: float) -> None:
        """设置通道的激活阈值"""
        self._thresholds[channel_name] = threshold

    def update_default(self, threshold: float) -> None:
        """更新默认阈值"""
        self.default_threshold = threshold

    def to_dict(self) -> Dict:
        """导出配置"""
        result = {"default": self.default_threshold}
        result.update(self._thresholds)
        return result

    @classmethod
    def from_dict(cls, data: Dict) -> "ThresholdConfig":
        """从字典加载配置"""
        default = data.get("default", 0.3)
        config = cls(default_threshold=default)
        for key, value in data.items():
            if key != "default":
                config.set_threshold(key, value)
        return config
