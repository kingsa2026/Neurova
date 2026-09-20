"""
Phase 3 API Endpoints - Intelligence & Realtime Features
"""

from fastapi import APIRouter, HTTPException, Depends, status
from typing import List, Optional, Dict, Any

from neurova.core.logger import get_logger
from neurova.collaboration.small_brain_router import (
    SmallBrainRouter,
    RoutingContext,
    RoutingDecisionResult,
    get_small_brain_router,
    reset_small_brain_router,
)
from neurova.collaboration.outbox_handler import (
    OutboxEvent,
    EventStatus,
    get_outbox_handler,
    reset_outbox_handler,
)
from neurova.collaboration.cost_ledger_integration import (
    get_cost_alert_system,
    CostAlertSystem,
    reset_cost_alert_system,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/phase3", tags=["Phase 3 Intelligence"])

# ============================================================================
# Small-Brain Router Endpoints
# ============================================================================

@router.post("/route/request")
async def route_request(
    user_query: str,
    agent_id: str,
    model_name: str = "gpt-4-turbo",
    cost_budget: float = 0.1,
    urgency_level: int = 5,
    available_models: Optional[List[str]] = None,
):
    """
    路由请求到最佳模型

    - **user_query**: 用户查询
    - **agent_id**: Agent ID
    - **model_name**: 建议的模型
    - **cost_budget**: 成本预算
    - **urgency_level**: 紧急程度 (1-10)
    - **available_models**: 可用模型列表
    """
    try:
        router_instance = get_small_brain_router()

        context = RoutingContext(
            agent_id=agent_id,
            model_name=model_name,
            user_query=user_query,
            cost_budget=cost_budget,
            urgency_level=urgency_level,
        )

        result = router_instance.route_request(context, available_models)

        return result.to_dict()

    except Exception as e:
        logger.error(f"Failed to route request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/router/stats")
async def get_router_stats():
    """获取路由器统计信息"""
    try:
        router_instance = get_small_brain_router()

        stats = router_instance.get_routing_stats()

        return stats

    except Exception as e:
        logger.error(f"Failed to get router stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/classify/query")
async def classify_query(
    query: str,
):
    """
    分类查询

    - **query**: 查询文本
    """
    try:
        router_instance = get_small_brain_router()

        category, confidence = router_instance.classify_query(query)

        return {
            "category": category,
            "confidence": confidence,
        }

    except Exception as e:
        logger.error(f"Failed to classify query: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Outbox Handler Endpoints
# ============================================================================

@router.post("/outbox/publish")
async def publish_event(
    event_type: str,
    agent_id: str,
    payload: Dict[str, Any],
    session_id: Optional[str] = None,
    priority: int = 5,
    expiration_ttl: int = 3600,
):
    """
    发布事件到 Outbox

    - **event_type**: 事件类型
    - **agent_id**: Agent ID
    - **payload**: 事件载荷
    - **session_id**: Session ID
    - **priority**: 优先级 (1-10)
    - **expiration_ttl**: 过期时间 (秒)
    """
    try:
        outbox = get_outbox_handler()

        event = outbox.publish(
            event_type=event_type,
            agent_id=agent_id,
            payload=payload,
            session_id=session_id,
            priority=priority,
            expiration_ttl=expiration_ttl,
        )

        return event.to_dict()

    except Exception as e:
        logger.error(f"Failed to publish event: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/outbox/events/{agent_id}")
async def get_agent_events(
    agent_id: str,
    status_filter: Optional[str] = None,
):
    """
    获取 agent 的所有事件

    - **agent_id**: Agent ID
    - **status_filter**: 状态过滤 (pending/sent/failed/delivered)
    """
    try:
        outbox = get_outbox_handler()

        if status_filter:
            status_enum = EventStatus(status_filter)
        else:
            status_enum = None

        events = outbox.get_agent_events(agent_id, status_filter=status_enum)

        return [event.to_dict() for event in events]

    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")
    except Exception as e:
        logger.error(f"Failed to get agent events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/outbox/process-pending")
async def process_pending_events():
    """处理待发送的事件"""
    try:
        outbox = get_outbox_handler()

        processed_count = outbox.process_pending_events()

        return {"processed_count": processed_count}

    except Exception as e:
        logger.error(f"Failed to process pending events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/outbox/stats")
async def get_outbox_stats():
    """获取 Outbox 统计信息"""
    try:
        outbox = get_outbox_handler()

        stats = outbox.get_stats()

        return stats

    except Exception as e:
        logger.error(f"Failed to get outbox stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Cost Alert System Endpoints
# ============================================================================

@router.post("/alerts/threshold/set")
async def set_cost_threshold(
    agent_id: str,
    threshold_usd: float,
):
    """
    设置成本阈值

    - **agent_id**: Agent ID
    - **threshold_usd**: 阈值 (USD)
    """
    try:
        alert_system = get_cost_alert_system()

        alert_system.set_threshold(agent_id, threshold_usd)

        return {
            "agent_id": agent_id,
            "threshold_usd": threshold_usd,
            "status": "set",
        }

    except Exception as e:
        logger.error(f"Failed to set cost threshold: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/alerts/check/{agent_id}")
async def check_cost_threshold(
    agent_id: str,
    cost_usd: float,
):
    """
    检查是否超过成本阈值

    - **agent_id**: Agent ID
    - **cost_usd**: 当前成本
    """
    try:
        alert_system = get_cost_alert_system()

        exceeded = alert_system.check_threshold(agent_id, cost_usd)

        return {
            "agent_id": agent_id,
            "cost_usd": cost_usd,
            "exceeded": exceeded,
        }

    except Exception as e:
        logger.error(f"Failed to check cost threshold: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/alerts/reset/{agent_id}")
async def reset_agent_spend(
    agent_id: str,
):
    """
    重置 agent 的当前支出

    - **agent_id**: Agent ID
    """
    try:
        alert_system = get_cost_alert_system()

        alert_system.reset_spend(agent_id)

        return {
            "agent_id": agent_id,
            "status": "reset",
        }

    except Exception as e:
        logger.error(f"Failed to reset agent spend: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Lifecycle Hooks Endpoints
# ============================================================================

@router.post("/hooks/agent-created")
async def on_agent_created(
    agent_id: str,
    company_id: str = "",
):
    """触发 Agent 创建事件"""
    try:
        from neurova.collaboration.cost_ledger_integration import on_agent_created as trigger_agent_created

        trigger_agent_created(agent_id, company_id)

        return {"status": "published", "agent_id": agent_id}

    except Exception as e:
        logger.error(f"Failed to trigger agent_created hook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/hooks/session-started")
async def on_session_started(
    session_id: str,
    agent_id: str,
    user_id: str,
):
    """触发 Session 启动事件"""
    try:
        from neurova.collaboration.cost_ledger_integration import on_session_started as trigger_session_started

        trigger_session_started(session_id, agent_id, user_id)

        return {"status": "published", "session_id": session_id}

    except Exception as e:
        logger.error(f"Failed to trigger session_started hook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/hooks/task-completed")
async def on_task_completed(
    task_id: str,
    agent_id: str,
    success: bool = True,
    duration: float = 0.0,
    cost_usd: float = 0.0,
):
    """触发任务完成事件"""
    try:
        from neurova.collaboration.cost_ledger_integration import on_task_completed as trigger_task_completed

        trigger_task_completed(task_id, agent_id, success, duration, cost_usd)

        return {"status": "published", "task_id": task_id}

    except Exception as e:
        logger.error(f"Failed to trigger task_completed hook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Admin & Cleanup
# ============================================================================

@router.post("/cleanup-old-events")
async def cleanup_old_events(
    keep_days: int = 7,
):
    """清理旧事件"""
    try:
        outbox = get_outbox_handler()

        cleaned_count = outbox.cleanup_old_events(keep_days=keep_days)

        return {"cleaned_count": cleaned_count}

    except Exception as e:
        logger.error(f"Failed to cleanup old events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reset")
async def reset_phase3_state():
    """重置所有 Phase 3 状态 (仅用于测试)"""
    reset_small_brain_router()
    reset_outbox_handler()
    reset_cost_alert_system()

    return {"status": "reset"}
