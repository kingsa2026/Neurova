"""
冲突检测引擎 - 检测新记忆与已有记忆的冲突
"""

import datetime
import logging
from typing import Any, Dict, List, Optional

from .models import Memory

logger = logging.getLogger(__name__)


class ConflictDetector:
    """
    冲突检测引擎

    检测新记忆与已有记忆的冲突。
    """

    def __init__(self):
        """初始化冲突检测器"""
        self._conflict_history: List[Dict[str, Any]] = []
        logger.info("ConflictDetector 初始化完成")

    def detect_conflict(self, new_memory: Memory, existing_memories: List[Memory]) -> List[Dict[str, Any]]:
        """
        检测新记忆与已有记忆的冲突

        Args:
            new_memory: 新记忆
            existing_memories: 已有记忆列表

        Returns:
            冲突列表
        """
        conflicts = []

        for existing_memory in existing_memories:
            conflict = self._check_pair_conflict(new_memory, existing_memory)
            if conflict:
                conflicts.append(conflict)
                self._conflict_history.append(conflict)

        return conflicts

    def _check_pair_conflict(self, memory1: Memory, memory2: Memory) -> Optional[Dict[str, Any]]:
        """检查两个记忆之间的冲突"""
        # 简单实现：检查内容相似度和否定词
        content1 = memory1.content.lower()
        content2 = memory2.content.lower()

        # 计算简单相似度
        similarity = self._calculate_similarity(content1, content2)

        if similarity < 0.3:
            return None

        # 检查否定词
        negations1 = self._has_negation(content1)
        negations2 = self._has_negation(content2)

        # 如果一个有否定词，另一个没有，可能是冲突
        if (negations1 and not negations2) or (negations2 and not negations1):
            return {
                "type": "negation_conflict",
                "memory1_id": memory1.id,
                "memory2_id": memory2.id,
                "similarity": similarity,
                "description": "一个记忆包含否定词，另一个不包含",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }

        return None

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度（简化版）"""
        if not text1 or not text2:
            return 0.0

        # 使用字符集合重叠率
        set1 = set(text1)
        set2 = set(text2)

        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))

        return intersection / union if union > 0 else 0.0

    def _has_negation(self, text: str) -> bool:
        """检查文本是否包含否定词"""
        negation_words = [
            "不",
            "没",
            "非",
            "无",
            "未",
            "别",
            "否认",
            "否定",
            "错误",
            "虚假",
            "not",
            "no",
            "never",
            "neither",
            "nor",
            "none",
            "nobody",
            "nothing",
            "nowhere",
            "cannot",
            "can't",
            "don't",
            "doesn't",
            "didn't",
            "won't",
            "wouldn't",
            "shouldn't",
            "isn't",
            "aren't",
            "wasn't",
            "weren't",
        ]

        text_lower = text.lower()
        return any(word in text_lower for word in negation_words)

    def get_conflict_history(self) -> List[Dict[str, Any]]:
        """获取冲突历史"""
        return self._conflict_history.copy()

    def clear_history(self) -> None:
        """清空冲突历史"""
        self._conflict_history.clear()
