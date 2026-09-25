"""
Smart Model Selector
基于查询复杂度智能选择最佳 LLM 模型
Neurova Style: Follows existing patterns (Singleton, Thread-safe)
"""

import hashlib
import time
import threading
from typing import List, Optional, Dict, Any
from functools import lru_cache

from neurova.core.logger import get_logger
from neurova.collaboration.small_brain_router import (
    get_small_brain_router,
    RoutingContext,
    RoutingDecision,
)

logger = get_logger(__name__)


class SmartModelSelector:
    """
    Smart model selector using Small-Brain Router
    
    Selects optimal model based on query complexity, budget, and urgency
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
        
        # Get router instance
        self.router = get_small_brain_router()
        
        # Default models
        self.default_models = [
            "gpt-4o-mini",
            "gpt-3.5-turbo", 
            "gpt-4o",
            "claude-3-haiku",
            "claude-3-sonnet",
        ]
        
        # Cache for recent selections
        self._selection_cache: Dict[str, str] = {}
        self._cache_ttl = 300  # 5 minutes
        
        logger.info("SmartModelSelector initialized")
    
    async def select_model(
        self,
        agent_id: str,
        user_query: str,
        available_models: Optional[List[str]] = None,
        cost_budget: float = 0.1,
        urgency_level: int = 5,
    ) -> str:
        """
        Select optimal model for query
        
        Args:
            agent_id: Agent ID
            user_query: User's query
            available_models: Available models (uses defaults if not specified)
            cost_budget: Cost budget in USD
            urgency_level: Urgency 1-10
        
        Returns:
            Selected model name
        """
        if available_models is None:
            available_models = self.default_models
        
        # Create cache key
        cache_key = f"{agent_id}:{hashlib.md5(user_query.encode()).hexdigest()[:16]}"
        
        # Check cache
        if cache_key in self._selection_cache:
            cached_model, cached_time = self._selection_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                logger.debug(f"Using cached model selection: {cached_model}")
                return cached_model
        
        # Create routing context
        context = RoutingContext(
            agent_id=agent_id,
            model_name="",  # Will be selected
            user_query=user_query,
            cost_budget=cost_budget,
            urgency_level=urgency_level,
        )
        
        # Route through Small-Brain Router
        result = self.router.route_request(context, available_models)
        
        # Select model based on decision
        if result.decision == RoutingDecision.ALLOW:
            selected_model = result.suggested_model or available_models[0]
            logger.debug(f"Selected model {selected_model} for simple query")
        
        elif result.decision == RoutingDecision.ESCALATE:
            selected_model = result.suggested_model or "gpt-4"
            logger.debug(f"Escalated to {selected_model} for complex task")
        
        elif result.decision == RoutingDecision.DENY:
            # Use cheapest available model
            selected_model = self._get_cheapest_model(available_models)
            logger.warning(f"Budget exceeded, using cheap model {selected_model}")
        
        else:
            # Fallback
            selected_model = available_models[0]
            logger.warning(f"Unknown decision, using default {selected_model}")
        
        # Cache selection
        self._selection_cache[cache_key] = (selected_model, time.time())
        
        logger.info(f"Selected '{selected_model}' for agent '{agent_id}'")
        
        return selected_model
    
    def _get_cheapest_model(self, models: List[str]) -> str:
        """Get cheapest model from list"""
        # Simple heuristic: shorter names are usually cheaper
        # In production, would use actual price tables
        price_order = [
            "gpt-4o-mini",
            "claude-3-haiku",
            "gpt-3.5-turbo",
            "gemini-1.5-flash",
            "claude-3-sonnet",
            "gpt-4o",
            "claude-3-opus",
            "gpt-4",
        ]
        
        for model in price_order:
            if model in models:
                return model
        
        return models[0]
    
    def clear_cache(self) -> None:
        """Clear selection cache"""
        self._selection_cache.clear()
        logger.debug("Cleared model selection cache")
    
    def get_selection_stats(self) -> Dict[str, Any]:
        """Get selection statistics"""
        return {
            "cache_size": len(self._selection_cache),
            "cache_ttl_seconds": self._cache_ttl,
            "default_models": self.default_models,
        }


# Global instance management
_smart_model_selector_instance: Optional[SmartModelSelector] = None
_smart_model_selector_lock = threading.Lock()


def get_smart_model_selector() -> SmartModelSelector:
    """Get global SmartModelSelector instance"""
    global _smart_model_selector_instance
    
    if _smart_model_selector_instance is None:
        with _smart_model_selector_lock:
            if _smart_model_selector_instance is None:
                _smart_model_selector_instance = SmartModelSelector()
    
    return _smart_model_selector_instance


def reset_smart_model_selector() -> None:
    """Reset SmartModelSelector instance (for testing)"""
    global _smart_model_selector_instance
    _smart_model_selector_instance = None
