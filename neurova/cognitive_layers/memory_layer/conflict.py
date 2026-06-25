"""
冲突检测引擎 - 检测新记忆与已有记忆的冲突

支持两种检测模式：
1. 语义模式：使用语义相似度检测（需要SemanticSearch）
2. 规则模式：基于字符重叠和否定词检测（无需模型）
"""

import datetime
from neurova.core.logger import get_logger
from typing import Any, Dict, List, Optional

from .models import Memory

logger = get_logger(__name__)


class ConflictDetector:
    """
    冲突检测引擎

    检测新记忆与已有记忆的冲突。
    """

    def __init__(self, use_semantic: bool = True):
        """
        初始化冲突检测器
        
        Args:
            use_semantic: 是否使用语义相似度检测
        """
        self._conflict_history: List[Dict[str, Any]] = []
        self._use_semantic = use_semantic
        self._semantic_search = None
        
        # 延迟初始化语义搜索
        if use_semantic:
            try:
                from .semantic_search import get_semantic_search
                self._semantic_search = get_semantic_search()
            except Exception as e:
                logger.warning("语义搜索初始化失败，降级到规则模式: %s", e)
        
        logger.info("ConflictDetector 初始化完成 (semantic=%s)", use_semantic)

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
        content1 = memory1.content.lower()
        content2 = memory2.content.lower()

        # 计算相似度
        if self._use_semantic and self._semantic_search:
            similarity = self._semantic_search.compute_similarity(content1, content2)
        else:
            similarity = self._calculate_similarity(content1, content2)

        # 检查矛盾词（即使相似度低，如果有矛盾词也可能是冲突）
        contradiction_score = self._check_contradiction(content1, content2)
        
        # 综合判断
        is_conflict = similarity >= 0.3 or contradiction_score >= 0.5
        
        if not is_conflict:
            return None

        # 检查否定词
        negations1 = self._has_negation(content1)
        negations2 = self._has_negation(content2)

        # 确定冲突类型
        conflict_type = "negation_conflict"
        description = "一个记忆包含否定词，另一个不包含"
        
        if contradiction_score >= 0.5:
            conflict_type = "semantic_contradiction"
            description = "两个记忆存在语义矛盾"

        # 如果一个有否定词，另一个没有，可能是冲突
        if (negations1 and not negations2) or (negations2 and not negations1):
            conflict_type = "negation_conflict"
            description = "一个记忆包含否定词，另一个不包含"

        return {
            "type": conflict_type,
            "memory1_id": memory1.id,
            "memory2_id": memory2.id,
            "similarity": similarity,
            "contradiction_score": contradiction_score,
            "detection_mode": "semantic" if self._semantic_search else "rule",
            "description": description,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    
    def _check_contradiction(self, text1: str, text2: str) -> float:
        """检查两个文本是否存在矛盾"""
        # 矛盾词对
        contradiction_pairs = [
            ("正常", "挂了"), ("正常", "故障"), ("正常", "失败"),
            ("成功", "失败"), ("开启", "关闭"), ("增加", "减少"),
            ("快", "慢"), ("好", "差"), ("多", "少"),
            ("是", "不是"), ("有", "没有"), ("能", "不能"),
        ]
        
        score = 0.0
        
        for word1, word2 in contradiction_pairs:
            if word1 in text1 and word2 in text2:
                score += 0.5
            elif word2 in text1 and word1 in text2:
                score += 0.5
        
        return min(1.0, score)

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
                "detection_mode": "semantic" if self._semantic_search else "rule",
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
