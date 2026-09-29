"""协作域生命周期事件出口（成本账本接线面）。

本模块承载 agent/session/task 等生命周期事件到 Outbox 的发布出口，
供 `api/endpoints/phase3_api.py` 消费。

**成本记账不在这里。** 本模块曾另有一个 `track_llm_call_integration` 装饰器
（第三套并行记账装饰器，与 `models/cost_tracking.track_llm_call`、
已退役的 `llm/cost_tracking_middleware` 同形），生产侧零引用，
已随第三份记账面一并退役——记账的唯一入口是
`models/cost_tracking.record_llm_cost`。
"""

import time
import threading
from typing import Optional, Dict

from neurova.core.logger import get_logger
from neurova.collaboration.outbox_handler import get_outbox_handler

logger = get_logger(__name__)

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
