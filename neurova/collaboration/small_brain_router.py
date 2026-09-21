"""
Small-Brain Triage Gate - Lightweight LLM Filtering
"""

import hashlib
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

from neurova.core.logger import get_logger

logger = get_logger(__name__)

class RoutingDecision(str, Enum):
    """路由决策类型"""

    ALLOW = "allow"              # 允许执行
    DENY = "deny"                # 拒绝执行
    REDIRECT = "redirect"        # 重定向到其他 agent
    DEFER = "defer"              # 延迟执行
    ESCALATE = "escalate"        # 升级到大模型处理

@dataclass
class RoutingContext:
    """路由上下文"""

    agent_id: str
    model_name: str
    user_query: str
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    proposed_operations: List[str] = field(default_factory=list)
    cost_budget: float = 0.0
    urgency_level: int = 5  # 1-10 scale

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "agent_id": self.agent_id,
            "model_name": self.model_name,
            "user_query": self.user_query,
            "conversation_history": self.conversation_history,
            "proposed_operations": self.proposed_operations,
            "cost_budget": self.cost_budget,
            "urgency_level": self.urgency_level,
        }

@dataclass
class RoutingDecisionResult:
    """路由决策结果"""

    decision: RoutingDecision
    reason: str
    confidence_score: float = 0.0
    suggested_model: Optional[str] = None
    estimated_cost: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "confidence_score": self.confidence_score,
            "suggested_model": self.suggested_model,
            "estimated_cost": self.estimated_cost,
            "metadata": self.metadata,
        }

class SmallBrainRouter:
    """
    Small-Brain Router - 轻量级路由器

    功能:
    1. Query classification (查询分类)
    2. Cost estimation (成本估算)
    3. Model selection (模型选择)
    4. Routing decisions (路由决策)
    """

    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # Thread safety
        self._lock = threading.RLock()

        # Routing rules
        self._rules: List[Dict[str, Any]] = []

        # Model cost tables
        self._model_costs: Dict[str, float] = {}

        # Classification models (simple keyword-based for now)
        self._classification_patterns: Dict[str, List[str]] = {}

        # Statistics
        self._routing_stats: Dict[str, int] = {}

        # Initialize default rules
        self._initialize_default_rules()

        logger.info("SmallBrainRouter initialized")

    def _initialize_default_rules(self) -> None:
        """初始化默认路由规则"""
        # Simple keyword-based classification patterns
        self._classification_patterns = {
            "simple_question": ["what", "who", "where", "when", "why", "how"],
            "code_generation": ["write code", "create function", "implement", "develop"],
            "debugging": ["fix", "error", "bug", "exception", "crash"],
            "analysis": ["analyze", "explain", "compare", "summarize"],
            "creative": ["write", "create", "design", "compose"],
            "complex_task": ["plan", "strategy", "architecture", "system design"],
        }

        # Default model costs (USD per 1K tokens)
        self._model_costs = {
            "gpt-4": 0.03,
            "gpt-4-turbo": 0.01,
            "gpt-3.5-turbo": 0.0005,
            "claude-3-opus": 0.015,
            "claude-3-sonnet": 0.003,
            "claude-3-haiku": 0.00025,
            "gemini-pro": 0.0025,
            "llama-3": 0.001,
        }

        # Default routing rules
        self._rules = [
            {
                "name": "simple_questions",
                "patterns": ["simple_question"],
                "min_confidence": 0.7,
                "decision": RoutingDecision.ALLOW,
                "suggested_model": "gpt-3.5-turbo",
                "max_cost": 0.01,
            },
            {
                "name": "code_generation",
                "patterns": ["code_generation"],
                "min_confidence": 0.6,
                "decision": RoutingDecision.ALLOW,
                "suggested_model": "gpt-4-turbo",
                "max_cost": 0.05,
            },
            {
                "name": "complex_tasks",
                "patterns": ["complex_task"],
                "min_confidence": 0.8,
                "decision": RoutingDecision.ESCALATE,
                "suggested_model": "gpt-4",
                "max_cost": 0.5,
            },
        ]

    def classify_query(
        self,
        query: str,
        context: Optional[RoutingContext] = None,
    ) -> Tuple[str, float]:
        """
        分类用户查询

        Args:
            query: 用户查询
            context: 路由上下文

        Returns:
            (category, confidence_score)
        """
        query_lower = query.lower()

        best_category = "unknown"
        best_confidence = 0.0

        for category, patterns in self._classification_patterns.items():
            matches = sum(1 for pattern in patterns if pattern in query_lower)

            if matches > 0:
                # Calculate confidence based on match ratio
                confidence = min(matches / len(patterns), 1.0)

                if confidence > best_confidence:
                    best_category = category
                    best_confidence = confidence

        # Boost confidence if multiple patterns match
        if best_confidence > 0.5 and len(query) > 20:
            best_confidence = min(best_confidence + 0.1, 1.0)

        logger.debug(f"Classified query as '{best_category}' with confidence {best_confidence:.2f}")

        return best_category, best_confidence

    def estimate_cost(
        self,
        model_name: str,
        estimated_tokens: int,
        direction: str = "output",
    ) -> float:
        """
        估算调用成本

        Args:
            model_name: 模型名称
            estimated_tokens: 预估 token 数
            direction: 方向 (input/output)

        Returns:
            估算成本 (USD)
        """
        base_cost_per_1k = self._model_costs.get(model_name, 0.01)

        # Output tokens typically cost more
        if direction == "output":
            base_cost_per_1k *= 2

        cost = (estimated_tokens * base_cost_per_1k) / 1000
        return round(cost, 6)

    def select_model(
        self,
        context: RoutingContext,
        available_models: List[str],
    ) -> Tuple[str, RoutingDecision]:
        """
        选择最佳模型

        Args:
            context: 路由上下文
            available_models: 可用模型列表

        Returns:
            (selected_model, decision)
        """
        # Classify query
        category, confidence = self.classify_query(context.user_query, context)

        # Rule-based model selection
        if category == "simple_question" and confidence > 0.7:
            preferred = "gpt-3.5-turbo"
            decision = RoutingDecision.ALLOW

        elif category == "code_generation" and confidence > 0.6:
            preferred = "gpt-4-turbo"
            decision = RoutingDecision.ALLOW

        elif category == "complex_task" or confidence < 0.5:
            preferred = "gpt-4"
            decision = RoutingDecision.ESCALATE

        elif context.urgency_level >= 8:
            # High urgency - use fastest model
            preferred = "gpt-3.5-turbo"
            decision = RoutingDecision.ALLOW

        else:
            # Default to balanced model
            preferred = "gpt-4-turbo"
            decision = RoutingDecision.ALLOW

        # Check if preferred model is available
        if preferred not in available_models:
            # Fallback to best available
            preferred = available_models[0] if available_models else "gpt-4-turbo"

        logger.debug(f"Selected model '{preferred}' with decision '{decision.value}'")

        return preferred, decision

    def route_request(
        self,
        context: RoutingContext,
        available_models: Optional[List[str]] = None,
    ) -> RoutingDecisionResult:
        """
        主路由方法

        Args:
            context: 路由上下文
            available_models: 可用模型列表

        Returns:
            RoutingDecisionResult
        """
        if available_models is None:
            available_models = list(self._model_costs.keys())

        # Classify query
        category, confidence = self.classify_query(context.user_query, context)

        # Select model
        selected_model, decision = self.select_model(context, available_models)

        # Estimate cost
        estimated_tokens = self._estimate_tokens(context)
        estimated_cost = self.estimate_cost(selected_model, estimated_tokens)

        # Check budget
        if estimated_cost > context.cost_budget:
            decision = RoutingDecision.DENY
            reason = f"Estimated cost ${estimated_cost:.4f} exceeds budget ${context.cost_budget:.4f}"
        elif decision == RoutingDecision.ESCALATE:
            reason = f"Complex task detected ({category}), escalating to larger model"
        elif confidence < 0.5:
            reason = f"Low confidence classification ({confidence:.2f}), using default model"
        else:
            reason = f"Route to {selected_model} for {category}"

        # Update statistics
        self._update_stats(decision)

        result = RoutingDecisionResult(
            decision=decision,
            reason=reason,
            confidence_score=confidence,
            suggested_model=selected_model,
            estimated_cost=estimated_cost,
            metadata={
                "category": category,
                "estimated_tokens": estimated_tokens,
            },
        )

        logger.info(f"Routed request: {result.reason}")

        return result

    def _estimate_tokens(self, context: RoutingContext) -> int:
        """估算 token 数量（走全仓唯一尺子，成本闸门与上下文预算同口径）。"""
        from neurova.context.token_estimator import estimate_tokens as estimate_text_tokens

        total = estimate_text_tokens(context.user_query or "")
        total += sum(estimate_text_tokens(str(h)) for h in context.conversation_history)

        return max(total, 100)  # 下限 100 token（路由成本下限）

    def _update_stats(self, decision: RoutingDecision) -> None:
        """更新路由统计"""
        decision_key = decision.value
        self._routing_stats[decision_key] = self._routing_stats.get(decision_key, 0) + 1

    def add_rule(self, rule: Dict[str, Any]) -> None:
        """添加自定义路由规则"""
        with self._lock:
            self._rules.append(rule)
            logger.info(f"Added routing rule: {rule['name']}")

    def get_routing_stats(self) -> Dict[str, Any]:
        """获取路由统计"""
        total = sum(self._routing_stats.values())

        return {
            "total_requests": total,
            "decisions": self._routing_stats.copy(),
            "decision_distribution": {
                k: round(v / max(total, 1), 3)
                for k, v in self._routing_stats.items()
            },
        }

    def reset(self) -> None:
        """重置所有状态 (用于测试)"""
        with self._lock:
            self._routing_stats.clear()
            logger.info("SmallBrainRouter reset")

# Global instance management
_small_brain_router_instance: Optional[SmallBrainRouter] = None
_small_brain_router_lock = threading.Lock()

def get_small_brain_router() -> SmallBrainRouter:
    """获取全局 SmallBrainRouter 实例 (Singleton)"""
    global _small_brain_router_instance

    if _small_brain_router_instance is None:
        with _small_brain_router_lock:
            if _small_brain_router_instance is None:
                _small_brain_router_instance = SmallBrainRouter()

    return _small_brain_router_instance

def reset_small_brain_router() -> None:
    """重置 SmallBrainRouter 实例 (用于测试)"""
    global _small_brain_router_instance
    _small_brain_router_instance = None
