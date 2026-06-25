"""
记忆体渲染器 (Volume Rendering for Memory Fusion)

将 NeRF 的体渲染思想应用于多通道记忆融合：
- 每个检索通道是一个"视角"
- 沿语义空间"射线"积分采样
- 加权融合得到最终结果

理论来源：
- NeRF Volume Rendering: C(r) = ∫ T(t)·σ(r(t))·c(r(t),d) dt
- 记忆版本: Score(m) = Σ T_i · σ_i(m) · relevance_i(m, query)

核心收益：
- 不再是简单加权求和
- 考虑通道间的"遮挡"关系（高置信度通道遮挡低置信度通道）
- 支持通道间交互和协同
"""

from neurova.core.logger import get_logger
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = get_logger(__name__)


# ────── 数据模型 ──────


@dataclass
class ChannelSample:
    """单通道采样结果（类比 NeRF 的采样点）"""

    memory_id: str
    content: str
    raw_score: float  # 原始分数
    channel: str  # 来源通道
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 体渲染参数（类比 NeRF 的颜色和密度）
    density: float = 0.0  # 密度 σ：记忆的"存在感"
    color: float = 0.0  # 颜色 c：与查询的相关度
    transmission: float = 1.0  # 透射率 T：未被"遮挡"的程度


@dataclass
class RenderedMemory:
    """渲染后的记忆（最终输出）"""

    memory_id: str
    content: str
    score: float  # 最终融合分数
    channel_scores: Dict[str, float] = field(default_factory=dict)  # 各通道贡献
    metadata: Dict[str, Any] = field(default_factory=dict)


# ────── 通道权重策略 ──────


class ChannelWeightStrategy(Enum):
    """通道权重策略"""

    UNIFORM = "uniform"  # 均匀权重
    INTENT_BASED = "intent"  # 基于查询意图
    ADAPTIVE = "adaptive"  # 自适应（根据历史表现）
    MOE = "moe"  # MoE 路由


# ────── 体渲染器 ──────


class VolumeRenderer:
    """
    记忆体渲染器

    核心公式（NeRF → 记忆系统映射）：

    NeRF:    C(r) = ∫ T(t)·σ(r(t))·c(r(t),d) dt
    记忆:    Score(m) = Σ_i T_i · σ_i · c_i(m)

    其中：
    - T_i = exp(-Σ_{j<i} σ_j)  透射率（前面通道的"遮挡"效应）
    - σ_i = channel_confidence  密度（通道置信度）
    - c_i = relevance_score     颜色（相关度分数）

    用法:
        renderer = VolumeRenderer()
        result = renderer.render(query, channel_results, intent="factual")
    """

    # 默认通道密度（置信度）权重
    DEFAULT_CHANNEL_DENSITY = {
        "temperature": 0.7,  # 温度通道：高置信度
        "text": 0.9,  # 文本通道：最高置信度
        "category": 0.5,  # 分类通道：中等
        "graph": 0.6,  # 图通道：中等偏上
        "emotion": 0.8,  # 情感通道：较高
        "voice": 0.4,  # 语音通道：较低
    }

    # 意图 → 通道权重映射
    INTENT_CHANNEL_WEIGHTS = {
        "factual": {"text": 1.0, "category": 0.8, "temperature": 0.3, "graph": 0.5, "emotion": 0.1, "voice": 0.2},
        "temporal": {"temperature": 1.0, "text": 0.6, "category": 0.3, "graph": 0.4, "emotion": 0.3, "voice": 0.5},
        "causal": {"graph": 1.0, "text": 0.8, "category": 0.5, "temperature": 0.4, "emotion": 0.3, "voice": 0.2},
        "comparative": {"text": 0.9, "category": 1.0, "graph": 0.7, "temperature": 0.3, "emotion": 0.4, "voice": 0.3},
        "exploratory": {"text": 0.7, "graph": 0.8, "temperature": 0.6, "category": 0.5, "emotion": 0.6, "voice": 0.4},
    }

    def __init__(self, channel_densities: Optional[Dict[str, float]] = None, density_scale: float = 1.0):
        """
        Args:
            channel_densities: 自定义通道密度
            density_scale: 密度缩放因子（控制"遮挡"强度）
        """
        self.channel_densities = channel_densities or self.DEFAULT_CHANNEL_DENSITY
        self.density_scale = density_scale

    def render(
        self, channel_results: Dict[str, List[Dict]], intent: str = "exploratory", limit: int = 10
    ) -> List[RenderedMemory]:
        """
        体渲染：融合多通道结果

        Args:
            channel_results: {通道名: [记忆列表]}
            intent: 查询意图
            limit: 返回数量

        Returns:
            渲染后的记忆列表（按分数降序）
        """
        # 1. 收集所有采样点
        all_samples = self._collect_samples(channel_results)
        if not all_samples:
            return []

        # 2. 按 memory_id 分组
        memory_groups = self._group_by_memory(all_samples)

        # 3. 获取意图权重
        weights = self.INTENT_CHANNEL_WEIGHTS.get(intent, {})

        # 4. 对每个记忆执行体渲染
        rendered = []
        for mem_id, samples in memory_groups.items():
            score, channel_scores = self._render_single_memory(samples, weights)
            rendered.append(
                RenderedMemory(
                    memory_id=mem_id,
                    content=samples[0].content,
                    score=score,
                    channel_scores=channel_scores,
                    metadata=samples[0].metadata,
                )
            )

        # 5. 排序返回
        rendered.sort(key=lambda m: m.score, reverse=True)
        return rendered[:limit]

    def _collect_samples(self, channel_results: Dict[str, List[Dict]]) -> List[ChannelSample]:
        """收集所有通道的采样结果"""
        samples = []
        for channel, memories in channel_results.items():
            for mem in memories:
                # V-3: 跳过无 memory_id 的项,避免空串作为分组键
                mid = mem.get("memory_id", mem.get("id", ""))
                if not mid:
                    continue
                samples.append(
                    ChannelSample(
                        memory_id=mid,
                        content=mem.get("content", ""),
                        raw_score=mem.get("score", 0.0),
                        channel=channel,
                        metadata=mem.get("metadata", {}),
                        density=self.channel_densities.get(channel, 0.5),
                        color=mem.get("score", 0.0),
                    )
                )
        return samples

    def _group_by_memory(self, samples: List[ChannelSample]) -> Dict[str, List[ChannelSample]]:
        """按 memory_id 分组"""
        groups: Dict[str, List[ChannelSample]] = {}
        for s in samples:
            if s.memory_id not in groups:
                groups[s.memory_id] = []
            groups[s.memory_id].append(s)
        return groups

    def _render_single_memory(
        self, samples: List[ChannelSample], intent_weights: Dict[str, float]
    ) -> Tuple[float, Dict[str, float]]:
        """
        对单个记忆执行体渲染

        核心算法：
        1. 按通道密度降序排列（高置信度通道优先）
        2. 计算累积透射率 T = exp(-累积密度)
        3. 最终分数 = Σ T_i · σ_i · c_i · w_i
        """
        # 按密度降序排列
        samples.sort(key=lambda s: s.density, reverse=True)

        total_score = 0.0
        cumulative_density = 0.0
        channel_scores = {}

        for sample in samples:
            # V-1: 透射率：T = exp(-累积密度), clamp 防止溢出
            exponent = -min(cumulative_density * self.density_scale, 50.0)
            transmission = math.exp(exponent)

            # 意图权重
            intent_weight = intent_weights.get(sample.channel, 0.5)

            # 该通道贡献：T · σ · c · w
            contribution = transmission * sample.density * sample.color * intent_weight

            total_score += contribution
            channel_scores[sample.channel] = contribution

            # 更新累积密度
            cumulative_density += sample.density

        return total_score, channel_scores

    def render_with_attention(
        self, channel_results: Dict[str, List[Dict]], intent: str = "exploratory", limit: int = 10
    ) -> List[RenderedMemory]:
        """
        带注意力机制的体渲染

        额外计算通道间的注意力权重，捕捉通道间的协同关系。
        纯 Python 实现，不依赖 numpy。
        """
        # 基础渲染
        rendered = self.render(channel_results, intent, limit)

        if len(rendered) < 2:
            return rendered

        # V-2: 使用固定通道序列对齐向量维度,确保余弦相似度计算正确
        all_channels = list(self.DEFAULT_CHANNEL_DENSITY.keys())

        # 计算结果间的注意力（基于 channel_scores 的余弦相似度）
        for i, mem_i in enumerate(rendered):
            attention_boost = 0.0
            scores_i = [mem_i.channel_scores.get(ch, 0.0) for ch in all_channels]

            for j, mem_j in enumerate(rendered):
                if i == j:
                    continue
                scores_j = [mem_j.channel_scores.get(ch, 0.0) for ch in all_channels]

                # 纯 Python 余弦相似度
                dot = sum(a * b for a, b in zip(scores_i, scores_j))
                norm_i = math.sqrt(sum(a * a for a in scores_i))
                norm_j = math.sqrt(sum(b * b for b in scores_j))

                if norm_i > 0 and norm_j > 0:
                    similarity = dot / (norm_i * norm_j)
                    attention_boost += similarity * mem_j.score * 0.1

            mem_i.score += attention_boost

        # 重新排序
        rendered.sort(key=lambda m: m.score, reverse=True)
        return rendered[:limit]


# ────── 工厂函数 ──────


def create_volume_renderer(density_scale: float = 1.0) -> VolumeRenderer:
    """创建体渲染器"""
    return VolumeRenderer(density_scale=density_scale)


def get_volume_renderer() -> VolumeRenderer:
    """获取单例体渲染器"""
    if not hasattr(get_volume_renderer, "_instance"):
        get_volume_renderer._instance = VolumeRenderer()
    return get_volume_renderer._instance
