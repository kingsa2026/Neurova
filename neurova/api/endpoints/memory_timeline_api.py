"""
Memory Timeline API - 记忆时间线API

审计 §3.1-11 诚实化：四个端点原先恒回空/零（`count += 0 # placeholder`），
是"活的装饰数据面"——前端拿到 200 + 空数据无从分辨"没有记忆"和"接口没实现"。
现统一显式 501，点名未实现与真实可用的替代数据面（/v1/memories 检索、
/v1/memory/stats），不再用占位数据冒充功能。
"""

from fastapi import APIRouter, HTTPException, Query
from neurova.api.auth import get_current_user, Depends

router = APIRouter(dependencies=[Depends(get_current_user)],)

_NOT_IMPLEMENTED_DETAIL = (
    "记忆时间线数据面未实现（无真实数据源，历史版本返回恒空/零的占位数据）。"
    "检索记忆请用 /v1/memories，统计请用 /v1/memory/stats。"
)


@router.get("/recent")
async def get_recent_memories(days: int = Query(7, ge=1, le=365), limit: int = Query(50, ge=1, le=200)):
    """获取最近N天的记忆（未实现，显式 501）"""
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_DETAIL)


@router.get("/range")
async def get_memories_by_time_range(
    start: str = Query(..., description="ISO datetime start"),
    end: str = Query(..., description="ISO datetime end"),
    page: int = 1,
    size: int = 50,
):
    """按时间范围获取记忆（未实现，显式 501）"""
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_DETAIL)


@router.get("/grouped")
async def get_memories_grouped(
    group_by: str = Query("day", regex="^(day|week|month)$"), days: int = Query(30, ge=1, le=365)
):
    """获取记忆时间线分组（未实现，显式 501）"""
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_DETAIL)


@router.get("/stats")
async def get_timeline_stats():
    """获取时间线统计信息（未实现，显式 501）"""
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_DETAIL)
