"""
ConflictDetector V2 — 基于向量的冲突检测

检测类型:
1. 矛盾 (Contradiction): 相同实体 + 相反属性
2. 演进 (Evolution): 相似内容 + 时间先后
3. 版本 (Version): 同一记忆的不同表述
"""

import logging
import re
from typing import Dict, List, Tuple, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class ConflictGroup:
    """冲突记忆组"""
    group_id: int
    options: List[Dict[str, Any]] = field(default_factory=list)
    conflict_type: str = "contradiction"  # "contradiction" | "evolution" | "version"
    entity_overlap: float = 0.0
    semantic_similarity: float = 0.0

class ConflictDetector:
    """
    冲突检测器

    检测规则:
      矛盾: 相同实体 + 不同属性
      演进: 相似内容 + 时间先后
    """

    def __init__(self, sim_threshold: float = 0.8, entity_threshold: float = 0.5):
        """
        初始化冲突检测器

        Args:
            sim_threshold: 语义相似度阈值
            entity_threshold: 实体重叠度阈值
        """
        self.sim_threshold = sim_threshold
        self.entity_threshold = entity_threshold

    def detect(self, results: List[Dict[str, Any]]) -> Tuple[
        List[ConflictGroup],      # 冲突组
        List[Dict[str, Any]],     # 独立记忆
        List[List[Dict[str, Any]]]  # 演进链
    ]:
        """
        检测结果中的冲突 — 杏仁核的威胁检测功能

        检测记忆中的冲突和演进关系，模拟杏仁核的威胁检测功能。

        神经隐喻:
        - 记忆列表: 像神经元集群的激活模式
        - 矛盾检测: 像前额叶的认知冲突监控
        - 演进检测: 像海马体的时间序列记忆
        - 独立记忆: 像未参与冲突的神经元集群

        Args:
            results: 记忆列表（神经元集群的激活模式）

        Returns:
            (冲突组, 独立记忆, 演进链) — (冲突信号, 正常信号, 时间序列)
        """
        conflict_groups: List[ConflictGroup] = []
        evolution_chains: List[List[Dict]] = []
        processed: Set[str] = set()
        group_id_counter = 0

        for i, mem_a in enumerate(results):
            mem_a_id = mem_a.get("id", "")
            if mem_a_id in processed:
                continue

            for j, mem_b in enumerate(results[i+1:], i+1):
                mem_b_id = mem_b.get("id", "")
                if mem_b_id in processed:
                    continue

                # 计算相似度
                sim = self._compute_similarity(mem_a, mem_b)
                entity_overlap = self._compute_entity_overlap(mem_a, mem_b)

                # 如果不相关，跳过
                if sim < self.sim_threshold or entity_overlap < self.entity_threshold:
                    continue

                # 判断类型
                if self._is_contradictory(mem_a, mem_b):
                    # 矛盾
                    group = self._find_or_create_group(
                        conflict_groups, mem_a, mem_b, group_id_counter
                    )
                    if group.group_id == group_id_counter:
                        group_id_counter += 1
                    group.options.append(mem_b)
                    group.entity_overlap = entity_overlap
                    group.semantic_similarity = sim
                    processed.add(mem_b_id)
                elif self._is_evolution(mem_a, mem_b):
                    # 演进
                    chain = self._find_or_create_chain(
                        evolution_chains, mem_a, mem_b
                    )
                    chain.append(mem_b)
                    processed.add(mem_b_id)

        # 未参与冲突/演进的记忆
        conflicted_ids = {m.get("id") for g in conflict_groups for m in g.options}
        evolved_ids = {m.get("id") for chain in evolution_chains for m in chain}
        independent = [
            m for m in results
            if m.get("id") not in conflicted_ids | evolved_ids
        ]

        return conflict_groups, independent, evolution_chains

    def _compute_similarity(self, mem_a: Dict, mem_b: Dict) -> float:
        """计算两条记忆的语义相似度"""
        content_a = mem_a.get("content", "").lower()
        content_b = mem_b.get("content", "").lower()

        if not content_a or not content_b:
            return 0.0

        # 中英文混合分词：中文按字，英文按词
        words_a = set(re.findall(r'[\u4e00-\u9fff]', content_a))
        words_a.update(re.findall(r'\b[a-z]+\b', content_a))
        words_b = set(re.findall(r'[\u4e00-\u9fff]', content_b))
        words_b.update(re.findall(r'\b[a-z]+\b', content_b))

        if not words_a or not words_b:
            return 0.0

        intersection = words_a & words_b
        union = words_a | words_b

        return len(intersection) / len(union) if union else 0.0

    def _compute_entity_overlap(self, mem_a: Dict, mem_b: Dict) -> float:
        """计算实体重叠度"""
        entities_a = self._extract_entities(mem_a.get("content", ""))
        entities_b = self._extract_entities(mem_b.get("content", ""))

        if not entities_a or not entities_b:
            return 0.0

        intersection = entities_a & entities_b
        union = entities_a | entities_b

        return len(intersection) / len(union) if union else 0.0

    def _extract_entities(self, text: str) -> Set[str]:
        """提取实体（简化版）"""
        entities = set()

        # 中文词组
        chinese_words = re.findall(r'[\u4e00-\u9fff]{2,}', text)
        entities.update(chinese_words)

        # 英文单词
        english_words = re.findall(r'\b[A-Za-z]+\b', text)
        entities.update(word.lower() for word in english_words if len(word) > 2)

        # 专有名词（大写开头）
        proper_nouns = re.findall(r'\b[A-Z][a-z]+\b', text)
        entities.update(proper_nouns)

        return entities

    def _is_contradictory(self, mem_a: Dict, mem_b: Dict) -> bool:
        """判断是否矛盾"""
        content_a = mem_a.get("content", "").lower()
        content_b = mem_b.get("content", "").lower()

        # 提取属性
        attrs_a = self._extract_attributes(content_a)
        attrs_b = self._extract_attributes(content_b)

        # 检查是否有相同实体但不同属性
        common_keys = set(attrs_a.keys()) & set(attrs_b.keys())
        for key in common_keys:
            if attrs_a[key] != attrs_b[key]:
                return True

        return False

    def _is_evolution(self, mem_a: Dict, mem_b: Dict) -> bool:
        """判断是否为版本演进"""
        # 规则: 相似内容 + 时间先后
        time_a = self._parse_time(mem_a.get("created_at"))
        time_b = self._parse_time(mem_b.get("created_at"))

        if time_a and time_b:
            return time_a < time_b

        # 如果没有时间信息，根据 ID 顺序判断
        return mem_a.get("id", "") < mem_b.get("id", "")

    def _extract_attributes(self, text: str) -> Dict[str, str]:
        """提取属性（简化版）"""
        attrs = {}

        # 模式: "X 是 Y" 或 "X 为 Y" — Y 可以是中文或英文
        patterns = [
            r'([\u4e00-\u9fff]+)\s*(?:是|为)\s*([\u4e00-\u9fff\w]+)',
            r'([\u4e00-\u9fff]+)\s*(?:使用|采用|用)\s*([\u4e00-\u9fff\w]+)',
            r'([\u4e00-\u9fff]+)\s*(?:升级到|更新到|改为)\s*([\u4e00-\u9fff\w]+)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text)
            for key, value in matches:
                attrs[key] = value

        return attrs

    def _parse_time(self, time_str: Optional[str]) -> Optional[datetime]:
        """解析时间字符串"""
        if not time_str:
            return None

        formats = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue

        return None

    def _find_or_create_group(self, groups: List[ConflictGroup],
                              mem_a: Dict, mem_b: Dict,
                              next_id: int) -> ConflictGroup:
        """查找或创建冲突组"""
        # 检查是否已有包含 mem_a 的组
        for group in groups:
            for opt in group.options:
                if opt.get("id") == mem_a.get("id"):
                    return group

        # 创建新组
        group = ConflictGroup(
            group_id=next_id,
            options=[mem_a],
            conflict_type="contradiction",
        )
        groups.append(group)
        return group

    def _find_or_create_chain(self, chains: List[List[Dict]],
                              mem_a: Dict, mem_b: Dict) -> List[Dict]:
        """查找或创建演进链"""
        # 检查是否已有包含 mem_a 的链
        for chain in chains:
            for item in chain:
                if item.get("id") == mem_a.get("id"):
                    return chain

        # 创建新链
        chain = [mem_a]
        chains.append(chain)
        return chain