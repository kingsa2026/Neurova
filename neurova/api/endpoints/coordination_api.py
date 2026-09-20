"""
Neurova Multi-Agent Coordination API Endpoints
Multi-agent 协作管理 RESTful API
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, Dict, Any
from datetime import datetime

from neurova.core.logger import get_logger
from neurova.agents.seen_boundary import get_seen_boundary, reset_seen_boundary
from neurova.collaboration.glance_yield_rules import (
    get_glance_yield_checker,
    reset_glance_yield_checker,
)
from neurova.llm.triage import (
    get_small_brain_triage_gate,
    reset_small_brain_triage_gate,
)
from neurova.agents.wake_debounce import (
    get_wake_debounce_manager,
    reset_wake_debounce_manager,
)
from neurova.experiments.ab_test_manager import (
    get_ab_test_manager,
    reset_ab_test_manager,
    ExperimentConfig,
    ExperimentGroup,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/coordination", tags=["coordination"])


# ========== Seen Boundary Endpoints ==========

@router.get("/seen-boundary/stats")
async def get_seen_boundary_stats():
    """获取 Seen Boundary 统计信息"""
    boundary = await get_seen_boundary()
    return {"seen_boundary": boundary.get_stats()}


@router.post("/seen-boundary/reset")
async def reset_seen_boundary_endpoint():
    """重置 Seen Boundary（仅用于测试）"""
    reset_seen_boundary()
    logger.info("Reset seen boundary")
    return {"status": "reset"}


@router.post("/seen-boundary/check-freshness")
async def check_freshness(
    agent_id: str = Query(..., description="Agent ID"),
    conversation_id: str = Query(..., description="Conversation ID"),
    last_seen_seq: int = Query(..., description="Last seen sequence number"),
):
    """检查消息新鲜度"""
    boundary = await get_seen_boundary()
    
    held = await boundary.check_freshness(
        agent_id=agent_id,
        conversation_id=conversation_id,
        last_seen_seq=last_seen_seq,
    )
    
    if held:
        return {
            "is_stale": True,
            "held_envelope": held.to_held_envelope(),
        }
    else:
        return {
            "is_stale": False,
            "new_baseline": held.new_baseline if hasattr(held, 'new_baseline') else None,
        }


# ========== Yield Checker Endpoints ==========

@router.get("/yield-checker/stats")
async def get_yield_checker_stats():
    """获取 Yield Checker 统计信息"""
    checker = await get_glance_yield_checker()
    return {"yield_checker": checker.get_stats()}


@router.post("/yield-checker/register-agent")
async def register_agent(
    agent_id: str = Query(..., description="Agent ID"),
    model_name: str = Query(..., description="Model name"),
):
    """注册 Agent 到 Yield Checker"""
    checker = await get_glance_yield_checker()
    checker.register_agent(agent_id, model_name)
    
    logger.info(f"Registered agent: {agent_id} with model: {model_name}")
    return {"status": "registered", "agent_id": agent_id, "model_name": model_name}


@router.post("/yield-checker/check")
async def check_yield_rules(
    agent_id: str = Query(..., description="Agent ID"),
    model_name: str = Query(..., description="Model name"),
    proposed_operations: list[str] = Query(..., description="Proposed operations"),
    conversation_id: Optional[str] = Query(None, description="Conversation ID"),
):
    """检查是否需要 yield"""
    checker = await get_glance_yield_checker()
    
    decision = checker.check_yield_rules(
        agent_id=agent_id,
        model_name=model_name,
        proposed_operations=proposed_operations,
        conversation_id=conversation_id,
    )
    
    return {
        "should_yield": decision.should_yield,
        "reason": decision.reason.value if decision.reason else None,
        "wait_time_seconds": decision.wait_time_seconds,
        "backoff_round": decision.backoff_round,
    }


@router.post("/yield-checker/unregister-agent")
async def unregister_agent(
    agent_id: str = Query(..., description="Agent ID"),
):
    """取消注册 Agent"""
    checker = await get_glance_yield_checker()
    checker.unregister_agent(agent_id)
    
    logger.info(f"Unregistered agent: {agent_id}")
    return {"status": "unregistered", "agent_id": agent_id}


@router.post("/yield-checker/reset")
async def reset_yield_checker_endpoint():
    """重置 Yield Checker（仅用于测试）"""
    reset_glance_yield_checker()
    logger.info("Reset yield checker")
    return {"status": "reset"}


# ========== Triage Gate Endpoints ==========

@router.get("/triage/stats")
async def get_triage_stats():
    """获取 Triage Gate 统计信息"""
    gate = get_small_brain_triage_gate()
    return {"triage_gate": gate.get_stats()}


@router.post("/triage/check")
async def triage_message(
    conversation_id: str = Query(..., description="Conversation ID"),
):
    """对对话进行 triage 分类"""
    gate = get_small_brain_triage_gate()
    
    result = await gate.triage_message(conversation_id)
    
    return {
        "actionable": result.actionable,
        "reason": result.reason,
        "confidence": result.confidence,
        "conversation_hash": result.conversation_hash,
    }


@router.post("/triage/clear-cache")
async def clear_triage_cache():
    """清除 Triage 缓存"""
    gate = get_small_brain_triage_gate()
    gate.clear_cache()
    
    logger.info("Cleared triage cache")
    return {"status": "cache_cleared"}


@router.post("/triage/reset")
async def reset_triage_gate_endpoint():
    """重置 Triage Gate（仅用于测试）"""
    reset_small_brain_triage_gate()
    logger.info("Reset triage gate")
    return {"status": "reset"}


# ========== Wake Debounce Endpoints ==========

@router.get("/debounce/stats")
async def get_debounce_stats():
    """获取 Debounce Manager 统计信息"""
    manager = get_wake_debounce_manager()
    return {"debounce_manager": manager.get_stats()}


@router.post("/debounce/wake-event")
async def on_wake_event(
    agent_id: str = Query(..., description="Agent ID"),
    conversation_id: str = Query(..., description="Conversation ID"),
    message_id: str = Query(..., description="Message ID"),
):
    """处理 Wake Event"""
    manager = get_wake_debounce_manager()
    
    from neurova.agents.wake_debounce import WakeEvent
    manager.on_wake_event(WakeEvent(
        agent_id=agent_id,
        conversation_id=conversation_id,
        message_id=message_id,
    ))
    
    logger.info(f"Wake event: agent={agent_id}, convo={conversation_id}, msg={message_id}")
    return {"status": "received", "debounce_ms": manager.debounce_ms}


@router.get("/debounce/turn/{agent_id}/{conversation_id}")
async def get_coalesced_turn(
    agent_id: str,
    conversation_id: str,
):
    """获取 Coalesced Turn"""
    manager = get_wake_debounce_manager()
    
    turn = manager.get_coalesced_turn(agent_id, conversation_id)
    
    if turn:
        return {
            "found": True,
            "turn": turn.to_turn_payload(),
            "message_count": len(turn.messages),
        }
    else:
        return {"found": False}


@router.post("/debounce/cancel")
async def cancel_debounce(
    agent_id: str = Query(..., description="Agent ID"),
    conversation_id: str = Query(..., description="Conversation ID"),
):
    """取消 Pending 的 Debounce"""
    manager = get_wake_debounce_manager()
    manager.cancel_pending(agent_id, conversation_id)
    
    logger.info(f"Canceled debounce: agent={agent_id}, convo={conversation_id}")
    return {"status": "cancelled"}


@router.post("/debounce/reset")
async def reset_debounce_manager_endpoint():
    """重置 Debounce Manager（仅用于测试）"""
    reset_wake_debounce_manager()
    logger.info("Reset debounce manager")
    return {"status": "reset"}


# ========== A/B Test Endpoints ==========

@router.get("/ab-tests/list")
async def list_ab_tests():
    """列出所有实验"""
    manager = await get_ab_test_manager()
    return {"experiments": manager.list_experiments()}


@router.post("/ab-tests/start")
async def start_ab_test(config: ExperimentConfig):
    """启动新的 A/B 测试"""
    manager = await get_ab_test_manager()
    
    success = await manager.start_experiment(config)
    
    if success:
        logger.info(
            f"Started A/B test: {config.name} - "
            f"{len(config.groups)} groups"
        )
        return {
            "status": "started",
            "experiment_name": config.name,
            "groups": [g.value for g in config.groups],
        }
    else:
        raise HTTPException(status_code=400, detail="Failed to start experiment")


@router.post("/ab-tests/assign")
async def assign_experiment_group(
    agent_id: str = Query(..., description="Agent ID"),
    experiment_name: str = Query(..., description="Experiment Name"),
):
    """分配 Agent 到实验组"""
    manager = await get_ab_test_manager()
    
    group = await manager.get_experiment_group(agent_id, experiment_name)
    
    if group is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    
    return {
        "agent_id": agent_id,
        "experiment_name": experiment_name,
        "group": group.value,
    }


@router.post("/ab-tests/record-metric")
async def record_metric(
    experiment_name: str = Query(..., description="Experiment Name"),
    group: str = Query(..., description="Experiment Group"),
    metrics: Dict[str, float] = Query(..., description="Metrics"),
    context: Dict[str, Any] = Query(..., description="Context"),
):
    """记录实验指标"""
    manager = await get_ab_test_manager()
    
    try:
        group_enum = ExperimentGroup(group)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid group: {group}")
    
    await manager.record_metric(
        experiment_name=experiment_name,
        group=group_enum,
        metrics=metrics,
        context=context,
    )
    
    logger.info(f"Recorded metric: exp={experiment_name}, group={group}")
    return {"status": "recorded"}


@router.post("/ab-tests/end/{experiment_name}")
async def end_ab_test(experiment_name: str):
    """结束实验"""
    manager = await get_ab_test_manager()
    
    success = await manager.end_experiment(experiment_name)
    
    if success:
        return {"status": "ended", "experiment_name": experiment_name}
    else:
        raise HTTPException(status_code=404, detail="Experiment not found")


@router.get("/ab-tests/results/{experiment_name}")
async def get_ab_test_results(experiment_name: str):
    """获取实验结果"""
    manager = await get_ab_test_manager()
    
    results = await manager.get_experiment_results(experiment_name)
    
    if results is None:
        raise HTTPException(status_code=404, detail="Experiment not found or not completed")
    
    return results


@router.post("/ab-tests/reset")
async def reset_ab_test_manager_endpoint():
    """重置 A/B Test Manager（仅用于测试）"""
    reset_ab_test_manager()
    logger.info("Reset ab test manager")
    return {"status": "reset"}


# ========== Summary Endpoint ==========

@router.get("/summary")
async def get_coordination_summary():
    """获取完整的 Coordination System 摘要"""
    seen_stats = (await get_seen_boundary()).get_stats()
    yield_stats = (await get_glance_yield_checker()).get_stats()
    triage_stats = get_small_brain_triage_gate().get_stats()
    debounce_stats = get_wake_debounce_manager().get_stats()
    ab_tests = get_ab_test_manager().list_experiments()
    
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "seen_boundary": seen_stats,
        "yield_checker": yield_stats,
        "triage_gate": triage_stats,
        "wake_debounce": debounce_stats,
        "active_experiments": len(ab_tests),
        "system_status": "healthy" if all([
            seen_stats.get("total_checks", 0) >= 0,
            yield_stats.get("total_checks", 0) >= 0,
        ]) else "degraded",
    }
