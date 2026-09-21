"""
Neurova Multi-Agent Coordination API Endpoints
Multi-agent 协作管理 RESTful API
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

from neurova.core.logger import get_logger
from neurova.collaboration.glance_yield_rules import (
    get_glance_yield_checker,
    reset_glance_yield_checker,
)
from neurova.llm.triage import (
    get_small_brain_triage_gate,
    reset_small_brain_triage_gate,
)
from neurova.experiments.ab_test_manager import (
    get_ab_test_manager,
    reset_ab_test_manager,
    ExperimentConfig,
    ExperimentGroup,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/coordination", tags=["coordination"])


# ========== Seen Boundary Endpoints（未实现，已摘除）==========
#
# 原 3 个 seen-boundary 端点依赖 `neurova.agents.seen_boundary`
# （get_seen_boundary / reset_seen_boundary）——该模块在本仓不存在，
# 导致整份 coordination_api 无法导入（25 个端点全部 404）。
# 只有测试 tests/integration/test_multi_agent_coordination.py 引用过它。
# 未实现的模块不保留影子端点：要实现请连带实现模块并配可运行测试，
# 而不是留一份 import 即炸的 API 面。
#
#   GET  /seen-boundary/stats
#   POST /seen-boundary/reset
#   POST /seen-boundary/check-freshness
#
# 同类新鲜度能力由 neurova/collaboration/seen_cursor.py
# （SeenCursorManager.check_freshness）与 glance_yield_rules 的
# freshness preflight 承担，已由下面的 yield-checker 端点对外服务。

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


# ========== Wake Debounce Endpoints（未实现，已摘除）==========
#
# 原 5 个 debounce 端点依赖 `neurova.agents.wake_debounce`
# （get_wake_debounce_manager / reset_wake_debounce_manager / WakeEvent）——
# 该模块在本仓不存在，是 coordination_api 导入失败的分母之一。
# 去抖/合并（Wake debounce & coalesce）目前仅在
# neurova/collaboration/glance_yield_rules.py 里有设计注记，无实现。
#
#   GET  /debounce/stats
#   POST /debounce/wake-event
#   GET  /debounce/turn/{agent_id}/{conversation_id}
#   POST /debounce/cancel
#   POST /debounce/reset

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


class RecordMetricRequest(BaseModel):
    """记录实验指标请求体。

    metrics/context 是结构化字典，不能作为 query 参数——FastAPI 会在
    路由注册期断言 "Query parameter must be one of the supported types"，
    使整份模块导入即失败；故收敛为 JSON 请求体（与 acp_api 等一致）。
    """

    experiment_name: str = Field(..., description="Experiment Name")
    group: str = Field(..., description="Experiment Group")
    metrics: Dict[str, float] = Field(default_factory=dict, description="Metrics")
    context: Dict[str, Any] = Field(default_factory=dict, description="Context")


@router.post("/ab-tests/record-metric")
async def record_metric(payload: RecordMetricRequest):
    """记录实验指标"""
    experiment_name = payload.experiment_name
    group = payload.group
    metrics = payload.metrics
    context = payload.context
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
    yield_stats = (await get_glance_yield_checker()).get_stats()
    triage_stats = get_small_brain_triage_gate().get_stats()
    ab_tests = get_ab_test_manager().list_experiments()

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "yield_checker": yield_stats,
        "triage_gate": triage_stats,
        "active_experiments": len(ab_tests),
        "system_status": "healthy" if all([
            yield_stats.get("total_checks", 0) >= 0,
        ]) else "degraded",
    }
