"""
问题分解器

将复杂问题分解为子问题，支持：
- 问题分解
- 问题类型检测
- 检索策略规划
"""

import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class QuestionType(Enum):
    """问题类型枚举"""
    CAUSAL = "causal"  # 因果问题
    COMPARATIVE = "comparative"  # 比较问题
    EXPLORATORY = "exploratory"  # 探索问题
    FACTUAL = "factual"  # 事实问题
    PROCEDURAL = "procedural"  # 程序问题
    TEMPORAL = "temporal"  # 时间问题
    UNKNOWN = "unknown"  # 未知类型


@dataclass
class SubQuestion:
    """子问题数据类"""
    text: str
    question_type: QuestionType
    priority: float = 1.0
    dependencies: List[str] = field(default_factory=list)


class QuestionDecomposer:
    """问题分解器
    
    将复杂问题分解为子问题，并为每个子问题规划检索策略。
    """
    
    # 问题类型关键词
    TYPE_KEYWORDS = {
        QuestionType.CAUSAL: ["为什么", "why", "原因", "cause", "reason", "导致", "lead to", "due to"],
        QuestionType.COMPARATIVE: ["比较", "compare", "对比", "difference", "vs", "versus", "哪个", "which"],
        QuestionType.EXPLORATORY: ["什么是", "what is", "介绍", "tell me about", "描述", "describe"],
        QuestionType.FACTUAL: ["谁", "who", "何时", "when", "哪里", "where", "多少", "how many"],
        QuestionType.PROCEDURAL: ["如何", "how to", "怎么", "步骤", "steps", "方法", "method"],
        QuestionType.TEMPORAL: ["什么时候", "when", "时间", "time", "日期", "date", "之前", "after"],
    }
    
    def __init__(self, llm_client=None):
        """初始化问题分解器
        
        Args:
            llm_client: LLM客户端（可选）
        """
        self.llm_client = llm_client
        logger.debug("QuestionDecomposer 初始化完成")
    
    def decompose(self, question: str) -> List[str]:
        """将复杂问题分解为子问题
        
        Args:
            question: 复杂问题
            
        Returns:
            List[str]: 子问题列表
        """
        # 首先检测问题类型
        question_type = self.detect_question_type(question)
        
        # 根据问题类型分解
        if question_type == QuestionType.CAUSAL:
            return self._decompose_causal(question)
        elif question_type == QuestionType.COMPARATIVE:
            return self._decompose_comparative(question)
        elif question_type == QuestionType.PROCEDURAL:
            return self._decompose_procedural(question)
        else:
            return self._decompose_general(question)
    
    def detect_question_type(self, question: str) -> QuestionType:
        """检测问题类型
        
        Args:
            question: 问题文本
            
        Returns:
            QuestionType: 问题类型
        """
        question_lower = question.lower()
        
        # 计算每种类型的匹配分数
        scores = {}
        for q_type, keywords in self.TYPE_KEYWORDS.items():
            score = 0
            for keyword in keywords:
                if keyword.lower() in question_lower:
                    score += 1
            scores[q_type] = score
        
        # 返回得分最高的类型
        if scores:
            best_type = max(scores.items(), key=lambda x: x[1])
            if best_type[1] > 0:
                return best_type[0]
        
        return QuestionType.UNKNOWN
    
    def plan_retrieval_strategy(self, sub_questions: List[str]) -> Dict[str, Any]:
        """为子问题规划检索策略
        
        Args:
            sub_questions: 子问题列表
            
        Returns:
            Dict[str, Any]: 检索策略
        """
        strategies = []
        
        for i, sub_question in enumerate(sub_questions):
            # 检测子问题类型
            q_type = self.detect_question_type(sub_question)
            
            # 根据类型选择检索策略
            strategy = self._get_strategy_for_type(q_type, sub_question)
            strategy["question"] = sub_question
            strategy["index"] = i
            strategies.append(strategy)
        
        return {
            "strategies": strategies,
            "total_questions": len(sub_questions),
            "recommended_order": self._determine_order(strategies),
        }
    
    def _decompose_causal(self, question: str) -> List[str]:
        """分解因果问题"""
        # 提取"为什么"后面的内容
        why_pattern = r"为什么(.+?)[，,？?]"
        match = re.search(why_pattern, question)
        
        if match:
            subject = match.group(1).strip()
            
            # 检查是否包含"如何解决"
            if "如何解决" in question or "怎么解决" in question:
                return [
                    f"为什么{subject}？",
                    f"如何解决{subject}的问题？",
                ]
            else:
                return [
                    f"为什么{subject}？",
                    f"{subject}的原因是什么？",
                ]
        
        # 通用分解
        return [
            question.replace("为什么", "原因："),
            question.replace("为什么", "结果："),
        ]
    
    def _decompose_comparative(self, question: str) -> List[str]:
        """分解比较问题"""
        # 提取比较对象
        compare_pattern = r"(.+?)\s*(?:和|与|vs|versus|对比|比较)\s*(.+?)[，,？?]"
        match = re.search(compare_pattern, question, re.IGNORECASE)
        
        if match:
            obj1 = match.group(1).strip()
            obj2 = match.group(2).strip()
            
            return [
                f"{obj1}的特点是什么？",
                f"{obj2}的特点是什么？",
                f"{obj1}和{obj2}的主要区别是什么？",
            ]
        
        # 通用分解
        return [
            question + "（第一个对象）",
            question + "（第二个对象）",
            question + "（差异分析）",
        ]
    
    def _decompose_procedural(self, question: str) -> List[str]:
        """分解程序问题"""
        # 提取"如何"后面的内容
        how_pattern = r"如何(.+?)[，,？?]"
        match = re.search(how_pattern, question)
        
        if match:
            action = match.group(1).strip()
            
            return [
                f"{action}的前置条件是什么？",
                f"{action}的具体步骤是什么？",
                f"{action}的注意事项有哪些？",
            ]
        
        # 通用分解
        return [
            question + "（准备工作）",
            question + "（具体步骤）",
            question + "（验证结果）",
        ]
    
    def _decompose_general(self, question: str) -> List[str]:
        """通用分解"""
        # 简单分解：提取关键词
        words = question.split()
        
        if len(words) <= 3:
            return [question]
        
        # 分成两部分
        mid = len(words) // 2
        part1 = " ".join(words[:mid])
        part2 = " ".join(words[mid:])
        
        return [
            f"{part1}是什么？",
            f"{part2}是什么？",
            f"{part1}和{part2}的关系是什么？",
        ]
    
    def _get_strategy_for_type(self, q_type: QuestionType, question: str) -> Dict[str, Any]:
        """根据问题类型获取检索策略"""
        strategies = {
            QuestionType.CAUSAL: {
                "channels": ["graph", "temporal"],
                "weights": {"graph": 0.6, "temporal": 0.2, "text": 0.2},
                "max_depth": 4,
                "min_score": 0.2,
            },
            QuestionType.COMPARATIVE: {
                "channels": ["category", "text"],
                "weights": {"category": 0.4, "text": 0.3, "graph": 0.3},
                "diversity": 0.7,
                "min_score": 0.2,
            },
            QuestionType.EXPLORATORY: {
                "channels": ["temperature", "text"],
                "weights": {"temperature": 0.2, "text": 0.3, "graph": 0.5},
                "serendipity": 0.3,
                "min_score": 0.1,
            },
            QuestionType.FACTUAL: {
                "channels": ["text", "temperature"],
                "weights": {"text": 0.5, "temperature": 0.3, "category": 0.2},
                "limit": 5,
                "min_score": 0.3,
            },
            QuestionType.PROCEDURAL: {
                "channels": ["text", "graph"],
                "weights": {"text": 0.4, "graph": 0.4, "temporal": 0.2},
                "max_depth": 3,
                "min_score": 0.2,
            },
            QuestionType.TEMPORAL: {
                "channels": ["temporal", "temperature"],
                "weights": {"temporal": 0.6, "temperature": 0.2, "text": 0.2},
                "time_decay": 0.8,
                "min_score": 0.2,
            },
            QuestionType.UNKNOWN: {
                "channels": ["text", "temperature"],
                "weights": {"text": 0.4, "temperature": 0.3, "graph": 0.3},
                "min_score": 0.2,
            },
        }
        
        return strategies.get(q_type, strategies[QuestionType.UNKNOWN])
    
    def _determine_order(self, strategies: List[Dict[str, Any]]) -> List[int]:
        """确定子问题的执行顺序"""
        # 按优先级排序（如果有依赖关系）
        order = list(range(len(strategies)))
        
        # 简单排序：按问题类型的重要性
        type_priority = {
            QuestionType.FACTUAL: 1,
            QuestionType.CAUSAL: 2,
            QuestionType.COMPARATIVE: 3,
            QuestionType.PROCEDURAL: 4,
            QuestionType.EXPLORATORY: 5,
            QuestionType.TEMPORAL: 6,
            QuestionType.UNKNOWN: 7,
        }
        
        # 这里可以添加更复杂的排序逻辑
        return order


def get_question_decomposer(llm_client=None) -> QuestionDecomposer:
    """获取问题分解器实例
    
    Args:
        llm_client: LLM客户端（可选）
        
    Returns:
        QuestionDecomposer: 问题分解器实例
    """
    return QuestionDecomposer(llm_client)