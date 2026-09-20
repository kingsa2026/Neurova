"""
LLM Cost Tracking Middleware
自动追踪所有 LLM 调用的成本并记录到账本
Neurova Style: Follows existing patterns (Singleton, Decorator, etc.)
"""

import time
from datetime import datetime
from typing import Callable, Any, Optional, Dict
from functools import wraps

from neurova.core.logger import get_logger
from neurova.models.cost_tracking import (
    CostTracker, 
    LLMCall, 
    LLMProvider, 
    LLMDirection,
    get_cost_tracker,
)
from neurova.collaboration.outbox_handler import (
    get_outbox_handler,
)

logger = get_logger(__name__)


class CostTrackingMixin:
    """
    Cost tracking mixin for LLM clients
    
    Provides automatic cost tracking for all LLM calls
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cost_tracker = None
    
    async def call_with_cost_tracking(self, messages: list, **kwargs) -> dict:
        """
        Call LLM with automatic cost tracking
        
        Args:
            messages: Message history
            kwargs: Additional arguments (session_id, agent_id, etc.)
        
        Returns:
            LLM response with usage metrics
        """
        # Extract context
        agent_id = kwargs.get('agent_id', getattr(self, 'agent_id', 'unknown'))
        session_id = kwargs.get('session_id')
        
        # Start timing
        start_time = time.time()
        
        try:
            # Execute original call
            result = await self.original_call(messages, **kwargs)
            
            # Extract usage from result
            usage = result.get('usage', {})
            input_tokens = usage.get('prompt_tokens', 0)
            output_tokens = usage.get('completion_tokens', 0)
            
            # Calculate cost
            cost_usd = self._calculate_cost(
                model=self.model_name,
                provider=self.provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            
            # Duration
            duration_seconds = time.time() - start_time
            
            # Log to cost ledger
            await self._log_to_ledger(
                agent_id=agent_id,
                session_id=session_id,
                provider=self.provider,
                model=self.model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                duration_seconds=duration_seconds,
            )
            
            # Publish event to outbox
            self._publish_cost_event(
                agent_id=agent_id,
                session_id=session_id,
                provider=self.provider,
                model=self.model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                duration_seconds=duration_seconds,
            )
            
            # Add tracking info to result
            result['_cost_tracking'] = {
                'cost_usd': cost_usd,
                'duration_seconds': duration_seconds,
                'tokens': {
                    'input': input_tokens,
                    'output': output_tokens,
                },
            }
            
            logger.debug(
                f"LLM call tracked: {self.model_name} - "
                f"${cost_usd:.6f} ({input_tokens + output_tokens} tokens)"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"LLM call failed with cost tracking: {e}")
            
            # Still publish failure event
            if session_id:
                self._publish_timing_event(
                    agent_id=agent_id,
                    session_id=session_id,
                    duration=time.time() - start_time,
                    success=False,
                )
            
            raise
    
    def _calculate_cost(
        self,
        model: str,
        provider: LLMProvider,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Calculate cost based on model and token counts"""
        
        # Price tables (USD per 1K tokens)
        price_tables = {
            LLMProvider.OPENAI: {
                "gpt-4": {"input": 0.03, "output": 0.06},
                "gpt-4-turbo": {"input": 0.01, "output": 0.03},
                "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
                "gpt-4o": {"input": 0.0025, "output": 0.01},
                "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
            },
            LLMProvider.ANTHROPIC: {
                "claude-3-opus": {"input": 0.015, "output": 0.075},
                "claude-3-sonnet": {"input": 0.003, "output": 0.015},
                "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
                "claude-3.5-sonnet": {"input": 0.003, "output": 0.015},
            },
            LLMProvider.GEMINI: {
                "gemini-1.5-pro": {"input": 0.0025, "output": 0.0075},
                "gemini-1.5-flash": {"input": 0.000375, "output": 0.00075},
            },
        }
        
        price_map = price_tables.get(provider, {}).get(model, {"input": 0, "output": 0})
        
        cost = (
            input_tokens * price_map["input"] / 1000 +
            output_tokens * price_map["output"] / 1000
        )
        
        return round(cost, 6)
    
    async def _log_to_ledger(
        self,
        agent_id: str,
        session_id: Optional[str],
        provider: LLMProvider,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        duration_seconds: float,
    ) -> None:
        """Log cost to ledger"""
        try:
            tracker = get_cost_tracker()
            
            call = LLMCall(
                agent_id=agent_id,
                session_id=session_id,
                provider=provider,
                model=model,
                direction=LLMDirection.OUTPUT,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                called_at=datetime.utcnow(),
                metadata={
                    "duration_seconds": duration_seconds,
                },
            )
            
            if hasattr(tracker, 'log_call'):
                await tracker.log_call(call)
            
            logger.debug(f"Logged cost to ledger: ${cost_usd:.6f}")
            
        except Exception as e:
            logger.warning(f"Failed to log cost to ledger: {e}")
    
    def _publish_cost_event(
        self,
        agent_id: str,
        session_id: Optional[str],
        provider: LLMProvider,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        duration_seconds: float,
    ) -> None:
        """Publish cost event to outbox"""
        try:
            outbox = get_outbox_handler()
            
            payload = {
                "model": model,
                "provider": provider.value,
                "cost_usd": cost_usd,
                "tokens": {
                    "input": input_tokens,
                    "output": output_tokens,
                },
                "duration_seconds": duration_seconds,
                "timestamp": time.time(),
            }
            
            outbox.publish(
                event_type="llm_cost_recorded",
                agent_id=agent_id,
                session_id=session_id,
                payload=payload,
                priority=5,
                expiration_ttl=86400,  # 24 hours
            )
            
            logger.debug(f"Published cost event for {agent_id}")
            
        except Exception as e:
            logger.warning(f"Failed to publish cost event: {e}")
    
    def _publish_timing_event(
        self,
        agent_id: str,
        session_id: str,
        duration: float,
        success: bool,
    ) -> None:
        """Publish performance metric event"""
        try:
            outbox = get_outbox_handler()
            
            payload = {
                "duration_seconds": duration,
                "success": success,
                "timestamp": time.time(),
            }
            
            outbox.publish(
                event_type="llm_performance_metric",
                agent_id=agent_id,
                session_id=session_id,
                payload=payload,
                priority=3,
                expiration_ttl=3600,
            )
            
        except Exception as e:
            logger.warning(f"Failed to publish timing event: {e}")


def track_llm_call_decorator(
    provider: LLMProvider,
    model: str,
    agent_id: str,
    session_id: Optional[str] = None,
):
    """
    Decorator for automatic LLM cost tracking
    
    Usage:
        @track_llm_call_decorator(
            provider=LLMProvider.OPENAI,
            model="gpt-4",
            agent_id="default"
        )
        async def call_llm(messages):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                
                usage = result.get('usage', {})
                input_tokens = usage.get('prompt_tokens', 0)
                output_tokens = usage.get('completion_tokens', 0)
                
                # Calculate cost
                price_tables = {
                    LLMProvider.OPENAI: {
                        "gpt-4": {"input": 0.03, "output": 0.06},
                    },
                }
                
                price_map = price_tables.get(provider, {}).get(model, {"input": 0, "output": 0})
                cost_usd = (
                    input_tokens * price_map["input"] / 1000 +
                    output_tokens * price_map["output"] / 1000
                )
                
                # Log to ledger
                tracker = get_cost_tracker()
                call = LLMCall(
                    agent_id=agent_id,
                    session_id=session_id,
                    provider=provider,
                    model=model,
                    direction=LLMDirection.OUTPUT,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    called_at=datetime.utcnow(),
                )
                
                if hasattr(tracker, 'log_call'):
                    await tracker.log_call(call)
                
                # Publish event
                outbox = get_outbox_handler()
                outbox.publish(
                    event_type="llm_cost_recorded",
                    agent_id=agent_id,
                    session_id=session_id,
                    payload={
                        "cost_usd": cost_usd,
                        "tokens": {"input": input_tokens, "output": output_tokens},
                    },
                    priority=5,
                )
                
                return result
                
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                raise
            
            finally:
                duration = time.time() - start_time
        
        return wrapper
    return decorator
