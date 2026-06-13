"""
ConflictDetector — 冲突检测器

检测语义矛盾的记忆对。
"""

import logging
from dataclasses import dataclass
from typing import List

from .base import ChannelResult

logger = logging.getLogger(__name__)


@dataclass
class ConflictPair:
    """冲突对"""

    result_a: ChannelResult
    result_b: ChannelResult
    reason: str = ""


class ConflictDetector:
    """冲突检测器

    基于关键词重叠 + 否定词检测来发现语义矛盾。
    """

    NEGATION_WORDS = {
        "不",
        "没",
        "无",
        "非",
        "未",
        "别",
        "莫",
        "勿",
        "not",
        "no",
        "never",
        "neither",
        "nor",
        "without",
        "isn't",
        "aren't",
        "wasn't",
        "weren't",
        "don't",
        "doesn't",
        "didn't",
        "won't",
        "wouldn't",
        "can't",
        "cannot",
    }

    def __init__(self, min_overlap: int = 2):
        self.min_overlap = min_overlap

    def detect(self, results: List[ChannelResult]) -> List[ConflictPair]:
        """检测冲突"""
        if len(results) < 2:
            return []

        conflicts = []
        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                pair = self._check_pair(results[i], results[j])
                if pair:
                    conflicts.append(pair)

        return conflicts

    def _check_pair(self, a: ChannelResult, b: ChannelResult) -> Optional[ConflictPair]:
        """检查一对结果是否冲突"""
        words_a = set(a.content.lower().split())
        words_b = set(b.content.lower().split())

        overlap = words_a & words_b
        if len(overlap) < self.min_overlap:
            return None

        # 检查否定词差异
        neg_a = words_a & self.NEGATION_WORDS
        neg_b = words_b & self.NEGATION_WORDS

        if bool(neg_a) != bool(neg_b):
            return ConflictPair(
                result_a=a,
                result_b=b,
                reason=f"否定词差异: {neg_a} vs {neg_b}",
            )

        return None


# 用于类型提示
from typing import Optional
