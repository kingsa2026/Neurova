"""
PatternMiner v1.0.0 — PrefixSpan 序列模式挖掘

Phase 2 P2-1: 从工具执行日志中发现高频工具序列模式。
使用 PrefixSpan 算法进行频繁序列模式挖掘。

核心流程:
  ToolExecutionLogger (JSON Lines) ──▶ PatternMiner.add_sequence()
      │
      ▼
  PrefixSpan 投影数据库增长
...
"""

import collections
from dataclasses import dataclass
from typing import List, Dict, Set, Optional, Any
import logging

from collections import defaultdict

logger = logging.getLogger(__name__)

@dataclass
class FrequentPattern:
    """频繁模式数据"""
    tools: List[str]
    support: int
    context: str = ""

class PatternMiner:
    """
    PatternMiner v1.0.0 — PrefixSpan 序列模式挖掘
    
    从工具执行日志中发现高频工具序列模式。
    使用 PrefixSpan 算法进行频繁序列模式挖掘。
    """
    
    def __init__(self, min_support: int = 2, min_length: int = 2, max_length: int = 10):
        """
        初始化 PatternMiner
        
        Args:
            min_support: 最小支持度阈值
            min_length: 最小模式长度
            max_length: 最大模式长度
        """
        self.min_support = min_support
        self.min_length = min_length
        self.max_length = max_length
        
        # 存储所有序列
        self._sequences: List[List[str]] = []
        # 存储所有工具
        self._all_tools: Set[str] = set()
        # 存储挖掘结果
        self._patterns: List[FrequentPattern] = []
        
        logger.info(f"PatternMiner initialized: min_support={min_support}, min_length={min_length}, max_length={max_length}")
    
    @property
    def sequence_count(self) -> int:
        """记录序列总数"""
        return len(self._sequences)
    
    @property
    def unique_tools_count(self) -> int:
        """统计唯一工具数"""
        return len(self._all_tools)
    
    def add_sequence(self, sequence) -> None:
        """
        添加工具调用序列
        
        Args:
            sequence: 工具调用序列，可以是字符串列表或 ToolEntry 对象列表
        """
        # 提取工具名称
        tool_names = []
        for item in sequence:
            if hasattr(item, 'tool_name'):
                tool_names.append(item.tool_name)
            elif isinstance(item, str):
                tool_names.append(item)
            else:
                logger.warning(f"Unknown sequence item type: {type(item)}")
                continue
        
        if tool_names:
            self._sequences.append(tool_names)
            self._all_tools.update(tool_names)
            logger.debug(f"Added sequence: {tool_names}")
    
    def mine(self) -> List[FrequentPattern]:
        """
        挖掘频繁模式
        
        Returns:
            FrequentPattern 列表
        """
        if not self._sequences:
            return []
        
        # 使用 PrefixSpan 算法挖掘频繁模式
        self._patterns = self._mine_sequences()
        
        # 按支持度排序
        self._patterns.sort(key=lambda p: p.support, reverse=True)
        
        logger.info(f" mined {len(self._patterns)} patterns")
        return self._patterns
    
    def get_top_patterns(self, k: int = 10) -> List[FrequentPattern]:
        """
        获取 Top-K 模式（按支持度排序）
        
        Args:
            k: 返回的模式数量
            
        Returns:
            Top-K 频繁模式列表
        """
        if not self._patterns:
            self.mine()
        
        return self._patterns[:k]
    
    def reset(self) -> None:
        """清空所有数据"""
        self._sequences.clear()
        self._all_tools.clear()
        self._patterns.clear()
        logger.info("PatternMiner reset")
    
    def to_skill_template_list(self, min_support: Optional[int] = None, min_success_rate: float = 0.0) -> List[Dict[str, Any]]:
        """
        将挖掘出的高频模式导出为 AutoSkillBuilder 可用的格式
        
        Args:
            min_support: 最小支持度阈值，如果为 None 则使用 self.min_support
            min_success_rate: 最小成功率（暂未使用）
            
        Returns:
            技能模板列表
        """
        if not self._patterns:
            self.mine()
        
        support_threshold = min_support if min_support is not None else self.min_support
        
        templates = []
        for pattern in self._patterns:
            if pattern.support >= support_threshold:
                template = {
                    "tools": pattern.tools,
                    "context": pattern.context,
                    "support": pattern.support,
                    "success_rate": 1.0  # 暂时设为 1.0
                }
                templates.append(template)
        
        logger.info(f"Exported {len(templates)} skill templates")
        return templates
    
    def _mine_sequences(self) -> List[FrequentPattern]:
        """
        使用 PrefixSpan 算法挖掘频繁模式
        
        Returns:
            FrequentPattern 列表
        """
        patterns = []
        
        # 1. 找到所有频繁 1-项集
        item_counts = defaultdict(int)
        for seq in self._sequences:
            for item in set(seq):  # 使用 set 避免重复计数
                item_counts[item] += 1
        
        # 过滤低于支持度阈值的项
        frequent_items = {item for item, count in item_counts.items() if count >= self.min_support}
        
        if not frequent_items:
            return []
        
        # 2. 对每个频繁项进行投影数据库挖掘
        for item in frequent_items:
            # 创建投影数据库
            projected_db = []
            for seq in self._sequences:
                # 找到该项在序列中的位置
                for i, seq_item in enumerate(seq):
                    if seq_item == item:
                        # 提取后缀
                        suffix = seq[i+1:]
                        if suffix:
                            projected_db.append(suffix)
                        break
            
            # 递归挖掘投影数据库
            suffix_patterns = self._prefix_span(projected_db, [item], 1)
            patterns.extend(suffix_patterns)
        
        # 3. 添加单个频繁项作为模式（如果长度 >= min_length）
        for item in frequent_items:
            if self.min_length <= 1:
                patterns.append(FrequentPattern(
                    tools=[item],
                    support=item_counts[item],
                    context=f"Single item: {item}"
                ))
        
        return patterns
    
    def _prefix_span(self, projected_db: List[List[str]], prefix: List[str], depth: int) -> List[FrequentPattern]:
        """
        PrefixSpan 递归挖掘
        
        Args:
            projected_db: 投影数据库
            prefix: 当前前缀
            depth: 递归深度
            
        Returns:
            FrequentPattern 列表
        """
        patterns = []
        
        # 检查深度限制
        if depth >= self.max_length:
            return patterns
        
        # 统计投影数据库中每个项的出现次数
        item_counts = defaultdict(int)
        for seq in projected_db:
            for item in set(seq):
                item_counts[item] += 1
        
        # 过滤低于支持度阈值的项
        frequent_items = {item for item, count in item_counts.items() if count >= self.min_support}
        
        if not frequent_items:
            return patterns
        
        # 对每个频繁项进行扩展
        for item in frequent_items:
            # 创建新的前缀
            new_prefix = prefix + [item]
            
            # 如果模式长度符合要求，添加到结果
            if len(new_prefix) >= self.min_length:
                # 计算支持度（在原始序列中出现的次数）
                support = self._count_pattern_support(new_prefix)
                patterns.append(FrequentPattern(
                    tools=new_prefix,
                    support=support,
                    context=f"Pattern: {' -> '.join(new_prefix)}"
                ))
            
            # 创建新的投影数据库
            new_projected_db = []
            for seq in projected_db:
                # 找到该项在序列中的位置
                for i, seq_item in enumerate(seq):
                    if seq_item == item:
                        # 提取后缀
                        suffix = seq[i+1:]
                        if suffix:
                            new_projected_db.append(suffix)
                        break
            
            # 递归挖掘
            if new_projected_db:
                sub_patterns = self._prefix_span(new_projected_db, new_prefix, depth + 1)
                patterns.extend(sub_patterns)
        
        return patterns
    
    def _count_pattern_support(self, pattern: List[str]) -> int:
        """
        计算模式在原始序列中的支持度
        
        Args:
            pattern: 模式（工具序列）
            
        Returns:
            支持度（出现次数）
        """
        count = 0
        for seq in self._sequences:
            if self._is_subsequence(pattern, seq):
                count += 1
        return count
    
    def _is_subsequence(self, pattern: List[str], sequence: List[str]) -> bool:
        """
        检查模式是否是序列的子序列
        
        Args:
            pattern: 模式
            sequence: 序列
            
        Returns:
            是否是子序列
        """
        if not pattern:
            return True
        
        pattern_idx = 0
        for seq_item in sequence:
            if pattern_idx < len(pattern) and seq_item == pattern[pattern_idx]:
                pattern_idx += 1
                if pattern_idx == len(pattern):
                    return True
        
        return False
