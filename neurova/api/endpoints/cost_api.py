"""
LLM Cost Tracking API Endpoints
"""

from fastapi import APIRouter, HTTPException, Depends, status
from typing import List, Optional
from datetime import datetime, timedelta

from neurova.core.logger import get_logger
from neurova.models.cost_tracking import (
    CostTracker,
    LLMCall,
    LLMProvider,
    LLMDirection,
    get_cost_tracker,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/cost", tags=["Cost Tracking"])

# ============================================================================
# Agent Cost Summary
# ============================================================================

@router.get("/agent/{agent_id}/summary")
async def get_agent_cost_summary(
    agent_id: str,
    hours: int = 24,
):
    """
    获取 Agent 成本汇总

    - **agent_id**: Agent ID
    - **hours**: 时间范围 (小时，默认 24 小时)
    """
    try:
        tracker = get_cost_tracker()

        start_time = datetime.utcnow() - timedelta(hours=hours)
        end_time = datetime.utcnow()

        summary = await tracker.get_agent_cost_summary(agent_id, start_time, end_time)

        if not summary:
            raise HTTPException(status_code=404, detail="No cost data found")

        return summary

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get agent cost summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/agent/{agent_id}/detailed")
async def get_agent_cost_detailed(
    agent_id: str,
    hours: int = 24,
    provider: Optional[LLMProvider] = None,
    model: Optional[str] = None,
):
    """
    获取 Agent 详细成本记录

    - **agent_id**: Agent ID
    - **hours**: 时间范围 (小时)
    - **provider**: 服务商过滤 (可选)
    - **model**: 模型过滤 (可选)
    """
    try:
        tracker = get_cost_tracker()

        # TODO: Implement detailed query with filters
        # For now, return basic summary
        return await get_agent_cost_summary(agent_id, hours=hours)

    except Exception as e:
        logger.error(f"Failed to get detailed cost: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Company Cost Summary
# ============================================================================

@router.get("/company/{company_id}/summary")
async def get_company_cost_summary(
    company_id: str,
    hours: int = 24,
):
    """
    获取公司成本汇总

    - **company_id**: 公司 ID
    - **hours**: 时间范围 (小时)
    """
    try:
        tracker = get_cost_tracker()

        start_time = datetime.utcnow() - timedelta(hours=hours)
        end_time = datetime.utcnow()

        summary = await tracker.get_company_cost_summary(company_id, start_time, end_time)

        if not summary:
            raise HTTPException(status_code=404, detail="No cost data found")

        return summary

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get company cost summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/company/{company_id}/leaderboard")
async def get_company_cost_leaderboard(
    company_id: str,
    hours: int = 24,
    limit: int = 20,
):
    """
    获取公司成本排行榜 (按 Agent 消耗排序)

    - **company_id**: 公司 ID
    - **hours**: 时间范围 (小时)
    - **limit**: 返回数量限制
    """
    try:
        tracker = get_cost_tracker()

        start_time = datetime.utcnow() - timedelta(hours=hours)
        end_time = datetime.utcnow()

        summary = await tracker.get_company_cost_summary(company_id, start_time, end_time)

        if not summary:
            raise HTTPException(status_code=404, detail="No cost data found")

        # Sort by total_cost and limit
        agents = sorted(summary.get("agents", []), key=lambda x: x["total_cost"], reverse=True)[:limit]

        return {
            "company_id": company_id,
            "period": {"start": start_time, "end": end_time},
            "leaderboard": agents,
            "grand_total": summary["grand_total"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get leaderboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Cost Calculation Utilities
# ============================================================================

@router.post("/calculate")
async def calculate_llm_cost(
    provider: LLMProvider,
    model: str,
    input_tokens: int,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
):
    """
    计算 LLM 调用成本

    - **provider**: 服务商
    - **model**: 模型名称
    - **input_tokens**: 输入 token 数
    - **output_tokens**: 输出 token 数
    - **cache_read_tokens**: 缓存读取 token
    - **cache_write_tokens**: 缓存写入 token
    """
    try:
        tracker = get_cost_tracker()

        cost = tracker.calculate_cost(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

        return {
            "provider": provider.value,
            "model": model,
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "cache_read": cache_read_tokens,
                "cache_write": cache_write_tokens,
            },
            "cost_usd": cost,
        }

    except Exception as e:
        logger.error(f"Failed to calculate cost: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Hourly Rollup Queries
# ============================================================================

@router.get("/rollup/hourly")
async def get_hourly_rollup(
    hours: int = 24,
    company_id: Optional[str] = None,
):
    """
    获取每小时成本汇总

    - **hours**: 时间范围 (小时)
    - **company_id**: 公司 ID (可选)
    """
    try:
        tracker = get_cost_tracker()

        start_time = datetime.utcnow() - timedelta(hours=hours)
        end_time = datetime.utcnow()

        # TODO: Implement hourly rollup query
        # This should aggregate llm_calls by hour

        return {
            "period": {"start": start_time, "end": end_time},
            "rollup": [],  # Placeholder
        }

    except Exception as e:
        logger.error(f"Failed to get hourly rollup: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Real-time Cost Dashboard
# ============================================================================

@router.get("/dashboard/realtime")
async def get_realtime_dashboard(
    company_id: str,
    window_minutes: int = 60,
):
    """
    实时成本仪表盘

    - **company_id**: 公司 ID
    - **window_minutes**: 时间窗口 (分钟)
    """
    try:
        tracker = get_cost_tracker()

        start_time = datetime.utcnow() - timedelta(minutes=window_minutes)
        end_time = datetime.utcnow()

        # TODO: Implement real-time aggregation
        # Should include:
        # - Current minute spend rate
        # - Projected daily cost
        # - Top spending agents
        # - Provider breakdown

        return {
            "company_id": company_id,
            "period": {"start": start_time, "end": end_time},
            "metrics": {
                "current_spend_rate_per_minute": 0.0,
                "projected_daily_cost": 0.0,
                "top_agents": [],
                "provider_breakdown": {},
            }
        }

    except Exception as e:
        logger.error(f"Failed to get realtime dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))
