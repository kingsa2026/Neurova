"""
ExplainabilityModule — 可解释性模块

提供记忆检索和决策的可解释性
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Explanation:
    """解释记录"""

    explanation_id: str
    action: str  # 描述被解释的动作
    reasons: List[str]  # 原因列表
    confidence: float  # 解释置信度 [0, 1]
    factors: Dict[str, float] = field(default_factory=dict)  # 影响因素及其权重

    def to_dict(self) -> Dict[str, Any]:
        return {
            "explanation_id": self.explanation_id,
            "action": self.action,
            "reasons": self.reasons,
            "confidence": self.confidence,
            "factors": self.factors,
        }

    def to_text(self) -> str:
        """转换为可读文本"""
        text = f"动作: {self.action}\n"
        text += f"置信度: {self.confidence:.2f}\n"
        text += "原因:\n"
        for i, reason in enumerate(self.reasons, 1):
            text += f"  {i}. {reason}\n"

        if self.factors:
            text += "影响因素:\n"
            for factor, weight in sorted(self.factors.items(), key=lambda x: x[1], reverse=True):
                text += f"  - {factor}: {weight:.2f}\n"

        return text


class ExplainabilityModule:
    """
    可解释性模块

    提供记忆检索和决策的可解释性，支持：
    - 检索解释：为什么返回这些记忆
    - 决策解释：为什么做出这个决策
    - 因素分析：哪些因素影响了结果
    """

    def __init__(self, max_explanations: int = 100):
        """
        Args:
            max_explanations: 最大解释记录数
        """
        self._max_explanations = max_explanations
        self._lock = threading.RLock()
        self._initialized = False

        # 解释历史
        self._explanations: List[Explanation] = []

        # 因素权重
        self._factor_weights: Dict[str, float] = {
            "relevance": 0.3,
            "recency": 0.2,
            "importance": 0.2,
            "frequency": 0.15,
            "emotion": 0.15,
        }

    @property
    def name(self) -> str:
        """模块名称"""
        return "explainability_module"

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("ExplainabilityModule initialized")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("ExplainabilityModule shutdown")

    def explain_retrieval(
        self,
        query: str,
        retrieved_ids: List[str],
        scores: Dict[str, float],
        factors: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Explanation:
        """
        解释检索结果

        Args:
            query: 查询
            retrieved_ids: 检索到的记忆ID列表
            scores: 记忆ID -> 分数
            factors: 记忆ID -> 因素 -> 分数

        Returns:
            解释记录
        """
        reasons = []

        # 分析检索原因
        if retrieved_ids:
            top_id = retrieved_ids[0]
            top_score = scores.get(top_id, 0)

            reasons.append(f"查询 '{query}' 与 {len(retrieved_ids)} 条记忆匹配")
            reasons.append(f"最高匹配分数: {top_score:.2f}")

            # 分析因素
            if factors and top_id in factors:
                top_factors = factors[top_id]
                max_factor = max(top_factors.items(), key=lambda x: x[1])
                reasons.append(f"主要匹配因素: {max_factor[0]} ({max_factor[1]:.2f})")

        # 计算置信度
        confidence = 0.0
        if scores:
            avg_score = sum(scores.values()) / len(scores)
            confidence = min(1.0, avg_score)

        explanation = Explanation(
            explanation_id=f"retrieval_{len(self._explanations)}",
            action=f"检索 '{query}'",
            reasons=reasons,
            confidence=confidence,
            factors=self._factor_weights,
        )

        with self._lock:
            self._explanations.append(explanation)
            if len(self._explanations) > self._max_explanations:
                self._explanations = self._explanations[-self._max_explanations :]

        return explanation

    def explain_decision(
        self,
        decision: str,
        context: Dict[str, Any],
        alternatives: Optional[List[str]] = None,
    ) -> Explanation:
        """
        解释决策

        Args:
            decision: 决策内容
            context: 决策上下文
            alternatives: 备选方案

        Returns:
            解释记录
        """
        reasons = []

        # 分析决策原因
        reasons.append(f"选择: {decision}")

        if alternatives:
            reasons.append(f"考虑了 {len(alternatives)} 个备选方案")

        # 从上下文中提取因素
        factors = {}
        if "importance" in context:
            factors["importance"] = context["importance"]
        if "confidence" in context:
            factors["confidence"] = context["confidence"]
        if "risk" in context:
            factors["risk"] = context["risk"]

        confidence = context.get("confidence", 0.7)

        explanation = Explanation(
            explanation_id=f"decision_{len(self._explanations)}",
            action=decision,
            reasons=reasons,
            confidence=confidence,
            factors=factors,
        )

        with self._lock:
            self._explanations.append(explanation)
            if len(self._explanations) > self._max_explanations:
                self._explanations = self._explanations[-self._max_explanations :]

        return explanation

    def add_explanation(
        self,
        action: str,
        reasons: List[str],
        confidence: float = 0.7,
        factors: Optional[Dict[str, float]] = None,
    ) -> Explanation:
        """添加自定义解释"""
        explanation = Explanation(
            explanation_id=f"custom_{len(self._explanations)}",
            action=action,
            reasons=reasons,
            confidence=confidence,
            factors=factors or {},
        )

        with self._lock:
            self._explanations.append(explanation)
            if len(self._explanations) > self._max_explanations:
                self._explanations = self._explanations[-self._max_explanations :]

        return explanation

    def get_explanations(self, limit: int = 10) -> List[Explanation]:
        """获取解释历史"""
        with self._lock:
            return self._explanations[-limit:]

    def get_explanation(self, explanation_id: str) -> Optional[Explanation]:
        """获取特定解释"""
        with self._lock:
            for exp in self._explanations:
                if exp.explanation_id == explanation_id:
                    return exp
        return None

    def set_factor_weights(self, weights: Dict[str, float]) -> None:
        """设置因素权重"""
        with self._lock:
            self._factor_weights.update(weights)

    def get_factor_weights(self) -> Dict[str, float]:
        """获取因素权重"""
        with self._lock:
            return dict(self._factor_weights)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            if not self._explanations:
                return {
                    "total_explanations": 0,
                    "avg_confidence": 0,
                }

            avg_confidence = sum(e.confidence for e in self._explanations) / len(self._explanations)

            return {
                "total_explanations": len(self._explanations),
                "avg_confidence": avg_confidence,
                "factor_weights": dict(self._factor_weights),
            }
