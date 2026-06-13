"""
UnifiedResultProcessor — 统一结果处理管道

功能：
1. 去重（memory_id）
2. 权重融合（channel_weight × base_score × activation_score）
3. 时序衰减（时间戳）
4. 冲突检测（语义矛盾）
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .base import ChannelResult
from .conflict import ConflictDetector
from .temporal import TemporalDecay

logger = logging.getLogger(__name__)


@dataclass
class ProcessOutput:
    """处理输出"""

    results: List[ChannelResult] = field(default_factory=list)
    total_count: int = 0
    deduped_count: int = 0
    conflicts: List[Any] = field(default_factory=list)


class UnifiedResultProcessor:
    """统一结果处理器"""

    def __init__(
        self,
        conflict_detector: Optional[ConflictDetector] = None,
        temporal_decay: Optional[TemporalDecay] = None,
    ):
        self.conflict_detector = conflict_detector or ConflictDetector()
        self.temporal_decay = temporal_decay or TemporalDecay()

    def deduplicate(self, results: List[ChannelResult]) -> List[ChannelResult]:
        """按 memory_id 去重，保留分数更高的"""
        seen: Dict[str, ChannelResult] = {}
        for r in results:
            if r.memory_id in seen:
                if r.score > seen[r.memory_id].score:
                    seen[r.memory_id] = r
            else:
                seen[r.memory_id] = r
        return list(seen.values())

    def apply_weights(
        self,
        results: List[ChannelResult],
        channel_weights: Dict[str, float],
        activations: Optional[Dict[str, float]] = None,
    ) -> List[ChannelResult]:
        """应用权重融合：score × channel_weight × activation"""
        for r in results:
            cw = channel_weights.get(r.channel, 1.0)
            act = activations.get(r.channel, 1.0) if activations else 1.0
            r.score = r.score * cw * act
        return results

    def apply_temporal_decay(self, results: List[ChannelResult]) -> List[ChannelResult]:
        """应用时序衰减"""
        for r in results:
            decay = self.temporal_decay.compute(r.timestamp)
            r.score = r.score * decay
        return results

    def process(
        self,
        results: List[ChannelResult],
        channel_weights: Dict[str, float],
        activations: Optional[Dict[str, float]] = None,
    ) -> ProcessOutput:
        """完整处理管道"""
        total_count = len(results)

        if not results:
            return ProcessOutput(total_count=0, deduped_count=0)

        # 1. 去重
        deduped = self.deduplicate(results)
        deduped_count = len(deduped)

        # 2. 权重融合
        deduped = self.apply_weights(deduped, channel_weights, activations)

        # 3. 时序衰减
        deduped = self.apply_temporal_decay(deduped)

        # 4. 排序
        deduped.sort(key=lambda r: r.score, reverse=True)

        # 5. 冲突检测
        conflicts = self.conflict_detector.detect(deduped)

        return ProcessOutput(
            results=deduped,
            total_count=total_count,
            deduped_count=deduped_count,
            conflicts=conflicts,
        )
