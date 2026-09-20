"""
LLM Cost Ledger Integration - Automatic Cost Tracking
"""

import time
import functools
import threading
from typing import Callable, Any, Optional, Dict
from functools import wraps
from datetime import datetime

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
    OutboxEvent,
)

logger = get_logger(__name__)

def track_llm_call_integration(
    provider: LLMProvider,
    model: str,
    agent_id: str,
    session_id: Optional[str] = None,
):
    """
    增强的 LLM 调用追踪装饰器 (集成 Outbox)

    Usage:
        @track_llm_call_integration(
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
            # Start tracking
            start_time = time.time()

            try:
                # Execute LLM call
                result = await func(*args, **kwargs)

                # Extract usage from result
                usage = result.get('usage', {})

                # Calculate cost
                input_tokens = usage.get('prompt_tokens', 0)
                output_tokens = usage.get('completion_tokens', 0)

                cost_usd = _calculate_cost_from_usage(
                    provider, model, input_tokens, output_tokens
                )

                # Log to cost tracker
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
                        "duration_seconds": time.time() - start_time,
                    },
                )

                # Async log to cost ledger
                cost_tracker = get_cost_tracker()
                if hasattr(cost_tracker, 'log_call'):
                    await cost_tracker.log_call(call)

                # Publish cost event to outbox
                _publish_cost_event(
                    agent_id=agent_id,
                    session_id=session_id,
                    call=call,
                )

                return result

            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                raise

            finally:
                # Record in outbox even on failure
                duration = time.time() - start_time

                if session_id:
                    _publish_timing_event(
                        agent_id=agent_id,
                        session_id=session_id,
                        duration=duration,
                        success=False,
                    )

        return wrapper
    return decorator

def _calculate_cost_from_usage(
    provider: LLMProvider,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """从 usage 计算成本"""
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

def _publish_cost_event(
    agent_id: str,
    session_id: Optional[str],
    call: LLMCall,
) -> None:
    """发布成本事件到 Outbox"""
    try:
        outbox = get_outbox_handler()

        payload = {
            "call_id": call.call_id,
            "model": call.model,
            "tokens": {
                "input": call.input_tokens,
                "output": call.output_tokens,
            },
            "cost_usd": call.cost_usd,
            "timestamp": call.called_at.isoformat(),
        }

        outbox.publish(
            event_type="llm_cost_recorded",
            agent_id=agent_id,
            session_id=session_id,
            payload=payload,
            priority=5,
            expiration_ttl=86400,  # 24 hours
        )

        logger.debug(f"Published cost event for call {call.call_id}")

    except Exception as e:
        logger.warning(f"Failed to publish cost event: {e}")

def _publish_timing_event(
    agent_id: str,
    session_id: str,
    duration: float,
    success: bool,
) -> None:
    """发布性能指标事件"""
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
            expiration_ttl=3600,  # 1 hour
        )

    except Exception as e:
        logger.warning(f"Failed to publish timing event: {e}")

# ============================================================================
# Agent Lifecycle Hooks
# ============================================================================

def on_agent_created(agent_id: str, company_id: str = "") -> None:
    """Agent 创建时触发的事件"""
    try:
        outbox = get_outbox_handler()

        outbox.publish(
            event_type="agent_created",
            agent_id=agent_id,
            session_id=None,
            payload={
                "company_id": company_id,
                "created_at": time.time(),
            },
            priority=8,
            expiration_ttl=86400,
        )

        logger.info(f"Published agent_created event for {agent_id}")

    except Exception as e:
        logger.error(f"Failed to publish agent_created event: {e}")

def on_session_started(session_id: str, agent_id: str, user_id: str) -> None:
    """Session 启动时触发的事件"""
    try:
        outbox = get_outbox_handler()

        outbox.publish(
            event_type="session_started",
            agent_id=agent_id,
            session_id=session_id,
            payload={
                "user_id": user_id,
                "started_at": time.time(),
            },
            priority=7,
            expiration_ttl=86400,
        )

        logger.info(f"Published session_started event for {session_id}")

    except Exception as e:
        logger.error(f"Failed to publish session_started event: {e}")

def on_task_completed(
    task_id: str,
    agent_id: str,
    success: bool,
    duration: float,
    cost_usd: float = 0.0,
) -> None:
    """任务完成时触发的事件"""
    try:
        outbox = get_outbox_handler()

        outbox.publish(
            event_type="task_completed",
            agent_id=agent_id,
            session_id=None,
            payload={
                "task_id": task_id,
                "success": success,
                "duration_seconds": duration,
                "cost_usd": cost_usd,
                "completed_at": time.time(),
            },
            priority=6,
            expiration_ttl=86400,
        )

        logger.info(f"Published task_completed event for {task_id}")

    except Exception as e:
        logger.error(f"Failed to publish task_completed event: {e}")

def on_collaboration_event(
    event_name: str,
    participating_agents: list,
    context: dict,
) -> None:
    """协作事件"""
    try:
        outbox = get_outbox_handler()

        for agent_id in participating_agents:
            outbox.publish(
                event_type="collaboration_event",
                agent_id=agent_id,
                session_id=context.get("session_id"),
                payload={
                    "event_name": event_name,
                    "participating_agents": participating_agents,
                    "context": context,
                    "timestamp": time.time(),
                },
                priority=5,
                expiration_ttl=3600,
            )

        logger.info(f"Published collaboration_event: {event_name}")

    except Exception as e:
        logger.error(f"Failed to publish collaboration_event: {e}")

# ============================================================================
# Cost Alert System
# ============================================================================

class CostAlertSystem:
    """成本告警系统"""

    def __init__(self):
        self._thresholds: Dict[str, float] = {}  # agent_id -> threshold
        self._current_spends: Dict[str, float] = {}  # agent_id -> current_spend

    def set_threshold(self, agent_id: str, threshold_usd: float) -> None:
        """设置成本阈值"""
        self._thresholds[agent_id] = threshold_usd
        logger.info(f"Set cost threshold for {agent_id}: ${threshold_usd:.2f}")

    def check_threshold(self, agent_id: str, cost_usd: float) -> bool:
        """检查是否超过阈值"""
        threshold = self._thresholds.get(agent_id)

        if not threshold:
            return False

        # Update current spend
        self._current_spends[agent_id] = self._current_spends.get(agent_id, 0) + cost_usd

        # Check threshold
        if self._current_spends[agent_id] >= threshold:
            logger.warning(
                f"COST ALERT: Agent {agent_id} exceeded threshold! "
                f"Spend: ${self._current_spends[agent_id]:.2f} / ${threshold:.2f}"
            )
            return True

        return False

    def reset_spend(self, agent_id: str) -> None:
        """重置 agent 的当前支出"""
        self._current_spends[agent_id] = 0
        logger.debug(f"Reset spend for agent {agent_id}")

# Global instance management
_cost_alert_system_instance: Optional[CostAlertSystem] = None
_cost_alert_system_lock = threading.Lock()

def get_cost_alert_system() -> CostAlertSystem:
    """获取全局 CostAlertSystem 实例"""
    global _cost_alert_system_instance

    if _cost_alert_system_instance is None:
        with _cost_alert_system_lock:
            if _cost_alert_system_instance is None:
                _cost_alert_system_instance = CostAlertSystem()

    return _cost_alert_system_instance

def reset_cost_alert_system() -> None:
    """重置 CostAlertSystem 实例"""
    global _cost_alert_system_instance
    _cost_alert_system_instance = None
