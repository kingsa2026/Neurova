"""
NeRF 位置编码模块

将低维输入(时间、情感、重要性)通过正弦/余弦函数映射到高维空间，
捕捉高频细节，提升连续值区分度。

理论来源：
- NeRF (Mildenhall et al., 2020)
- Fourier Features (Tancik et al., 2020)

核心公式：
γ(p) = (sin(2⁰πp), cos(2⁰πp), ..., sin(2^(L-1)πp), cos(2^(L-1)πp))

纯 Python 实现，不依赖 numpy/torch。
"""

from neurova.core.logger import get_logger
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

logger = get_logger(__name__)


# ────── 基础编码器 ──────


@dataclass
class PositionalEncodingConfig:
    """位置编码配置"""

    num_frequencies: int = 10  # 频率数量 L
    include_input: bool = True  # 是否包含原始输入

    @property
    def output_dim(self) -> int:
        dim = self.num_frequencies * 2  # sin + cos
        if self.include_input:
            dim += 1
        return dim


class PositionalEncoder:
    """
    基础位置编码器

    将标量 → 高维向量，让神经网络能学习高频细节。

    用法:
        enc = PositionalEncoder()
        vec = enc.encode(0.5)  # 标量 → 21维 list
    """

    def __init__(self, config: Optional[PositionalEncodingConfig] = None):
        self.config = config or PositionalEncodingConfig()
        # 预计算频率 [2⁰, 2¹, ..., 2^(L-1)]
        self._freqs = [2.0**i for i in range(self.config.num_frequencies)]

    def encode(self, x: float) -> List[float]:
        """编码单个标量 → List[float]"""
        result = []
        if self.config.include_input:
            result.append(x)
        for f in self._freqs:
            angle = f * math.pi * x
            result.append(math.sin(angle))
            result.append(math.cos(angle))
        return result

    def encode_batch(self, x_batch: List[float]) -> List[List[float]]:
        """批量编码 → List[List[float]]"""
        return [self.encode(x) for x in x_batch]


# ────── 辅助函数 ──────


def _concat_vecs(*vecs: List[float]) -> List[float]:
    """拼接多个向量"""
    result = []
    for v in vecs:
        result.extend(v)
    return result


def _vec_sub(a: List[float], b: List[float]) -> List[float]:
    """向量减法"""
    return [x - y for x, y in zip(a, b)]


def _vec_norm(v: List[float]) -> float:
    """向量模长"""
    return math.sqrt(sum(x * x for x in v))


# ────── 时间位置编码器 ──────


class TemporalPositionalEncoder:
    """
    时间位置编码器

    编码时间特征：绝对时间 + 相对时间 + 周期性(小时/星期)
    替代原有的分段衰减函数，提供连续时间表示。

    输出维度 = 21 + 13 + 9 + 9 = 52
    """

    def __init__(self, num_frequencies: int = 10):
        self.absolute_encoder = PositionalEncoder(PositionalEncodingConfig(num_frequencies=num_frequencies))
        self.relative_encoder = PositionalEncoder(PositionalEncodingConfig(num_frequencies=6))
        self.periodic_encoder = PositionalEncoder(PositionalEncodingConfig(num_frequencies=4))

    def encode_timestamp(self, timestamp: float, reference_time: Optional[float] = None) -> List[float]:
        """
        编码时间戳 → 52维向量

        Args:
            timestamp: Unix 时间戳
            reference_time: 参考时间(默认当前)

        Returns:
            时间编码向量 (52,)
        """
        if reference_time is None:
            reference_time = datetime.now(timezone.utc).timestamp()

        # 1. 绝对时间 (归一化到 [0,1])
        epoch_2020 = 1577836800
        thirty_years = 30 * 365.25 * 24 * 3600
        normalized = max(0.0, min(1.0, (timestamp - epoch_2020) / thirty_years))
        absolute_enc = self.absolute_encoder.encode(normalized)

        # 2. 相对时间 (距今天数，log压缩)
        days_ago = max(0, (reference_time - timestamp) / 86400)
        relative_norm = min(1.0, math.log(1 + days_ago) / 10)
        relative_enc = self.relative_encoder.encode(relative_norm)

        # 3. 周期性 (小时 + 星期)
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        hour_enc = self.periodic_encoder.encode(dt.hour / 24)
        weekday_enc = self.periodic_encoder.encode(dt.weekday() / 7)

        return _concat_vecs(absolute_enc, relative_enc, hour_enc, weekday_enc)

    @property
    def output_dim(self) -> int:
        return (
            self.absolute_encoder.config.output_dim
            + self.relative_encoder.config.output_dim
            + self.periodic_encoder.config.output_dim * 2
        )


# ────── 情感位置编码器 ──────


class EmotionPositionalEncoder:
    """
    情感位置编码器

    将离散情感类型 + 连续强度编码为高维向量。
    原来只有9种枚举，现在支持连续值(0.73 vs 0.74)。

    输出维度 = 9 + 21 + 9 + 9 = 48 (默认参数)
    """

    # 情感类型 → 基向量 (9维 one-hot)
    EMOTION_BASE = {
        "neutral": [1, 0, 0, 0, 0, 0, 0, 0, 0],
        "joy": [0, 1, 0, 0, 0, 0, 0, 0, 0],
        "sadness": [0, 0, 1, 0, 0, 0, 0, 0, 0],
        "anger": [0, 0, 0, 1, 0, 0, 0, 0, 0],
        "fear": [0, 0, 0, 0, 1, 0, 0, 0, 0],
        "surprise": [0, 0, 0, 0, 0, 1, 0, 0, 0],
        "disgust": [0, 0, 0, 0, 0, 0, 1, 0, 0],
        "trust": [0, 0, 0, 0, 0, 0, 0, 1, 0],
        "anticipation": [0, 0, 0, 0, 0, 0, 0, 0, 1],
    }

    # 情感类型 → 默认效价和唤醒度
    DEFAULT_VALENCE = {
        "joy": 0.8,
        "trust": 0.7,
        "anticipation": 0.6,
        "surprise": 0.5,
        "neutral": 0.5,
        "sadness": 0.2,
        "anger": 0.2,
        "fear": 0.2,
        "disgust": 0.1,
    }
    DEFAULT_AROUSAL = {
        "anger": 0.9,
        "fear": 0.8,
        "surprise": 0.8,
        "joy": 0.7,
        "anticipation": 0.6,
        "disgust": 0.5,
        "sadness": 0.3,
        "trust": 0.3,
        "neutral": 0.2,
    }

    def __init__(self, num_frequencies: int = 6):
        self.intensity_enc = PositionalEncoder(PositionalEncodingConfig(num_frequencies=num_frequencies))
        self.valence_enc = PositionalEncoder(PositionalEncodingConfig(num_frequencies=4))
        self.arousal_enc = PositionalEncoder(PositionalEncodingConfig(num_frequencies=4))

    def encode_emotion(
        self, emotion_type: str, intensity: float, valence: Optional[float] = None, arousal: Optional[float] = None
    ) -> List[float]:
        """
        编码情感状态 → 48维向量 (默认参数)

        Args:
            emotion_type: 情感类型 ("joy", "sadness" 等)
            intensity: 强度 [0, 1]
            valence: 效价 [-1, 1]，可选
            arousal: 唤醒度 [0, 1]，可选
        """
        base = list(self.EMOTION_BASE.get(emotion_type, self.EMOTION_BASE["neutral"]))
        intensity_vec = self.intensity_enc.encode(intensity)

        v = self.DEFAULT_VALENCE.get(emotion_type, 0.5) if valence is None else (valence + 1) / 2
        valence_vec = self.valence_enc.encode(max(0.0, min(1.0, v)))

        a = self.DEFAULT_AROUSAL.get(emotion_type, 0.5) if arousal is None else arousal
        arousal_vec = self.arousal_enc.encode(max(0.0, min(1.0, a)))

        return _concat_vecs(base, intensity_vec, valence_vec, arousal_vec)

    @property
    def output_dim(self) -> int:
        return (
            9
            + self.intensity_enc.config.output_dim
            + self.valence_enc.config.output_dim
            + self.arousal_enc.config.output_dim
        )


# ────── 重要性位置编码器 ──────


class ImportancePositionalEncoder:
    """
    重要性位置编码器

    编码温度/重要性值，替代原来的分段衰减。
    """

    def __init__(self, num_frequencies: int = 4):
        self.value_enc = PositionalEncoder(PositionalEncodingConfig(num_frequencies=num_frequencies))
        self.rank_enc = PositionalEncoder(PositionalEncodingConfig(num_frequencies=3))
        self.stage_enc = PositionalEncoder(PositionalEncodingConfig(num_frequencies=2))

    def encode_importance(
        self, value: float, rank_percentile: Optional[float] = None, lifecycle_stage: Optional[str] = None
    ) -> List[float]:
        """
        编码重要性 → 向量

        Args:
            value: 重要性值 [0, 1]
            rank_percentile: 排名百分位 [0, 1]
            lifecycle_stage: 生命周期阶段
        """
        value_vec = self.value_enc.encode(value)
        rank_vec = self.rank_enc.encode(rank_percentile if rank_percentile is not None else value)

        stage_map = {"active": 1.0, "consolidated": 0.75, "archived": 0.5, "forgotten": 0.25, "crystallized": 0.9}
        stage_val = stage_map.get(lifecycle_stage, 0.5) if lifecycle_stage else 0.5
        stage_vec = self.stage_enc.encode(stage_val)

        return _concat_vecs(value_vec, rank_vec, stage_vec)

    @property
    def output_dim(self) -> int:
        return self.value_enc.config.output_dim + self.rank_enc.config.output_dim + self.stage_enc.config.output_dim


# ────── 便捷工厂 ──────


def create_temporal_encoder(num_frequencies: int = 10) -> TemporalPositionalEncoder:
    return TemporalPositionalEncoder(num_frequencies=num_frequencies)


def create_emotion_encoder(num_frequencies: int = 6) -> EmotionPositionalEncoder:
    return EmotionPositionalEncoder(num_frequencies=num_frequencies)


def create_importance_encoder(num_frequencies: int = 4) -> ImportancePositionalEncoder:
    return ImportancePositionalEncoder(num_frequencies=num_frequencies)
