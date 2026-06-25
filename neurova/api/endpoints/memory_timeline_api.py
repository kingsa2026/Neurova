"""
Memory Timeline API - 记忆时间线API
"""

import datetime
from neurova.core.logger import get_logger
from fastapi import APIRouter, Query

logger = get_logger(__name__)
router = APIRouter()


@router.get("/recent")
async def get_recent_memories(days: int = Query(7, ge=1, le=365), limit: int = Query(50, ge=1, le=200)):
    """获取最近N天的记忆"""
    now = datetime.datetime.utcnow()
    start = (now - datetime.timedelta(days=days)).isoformat()
    return {
        "code": 0,
        "message": "success",
        "data": {"memories": [], "total": 0, "from": start, "to": now.isoformat(), "days": days},
    }


@router.get("/range")
async def get_memories_by_time_range(
    start: str = Query(..., description="ISO datetime start"),
    end: str = Query(..., description="ISO datetime end"),
    page: int = 1,
    size: int = 50,
):
    """按时间范围获取记忆"""
    return {
        "code": 0,
        "message": "success",
        "data": {"memories": [], "total": 0, "start": start, "end": end, "page": page, "size": size},
    }


@router.get("/grouped")
async def get_memories_grouped(
    group_by: str = Query("day", regex="^(day|week|month)$"), days: int = Query(30, ge=1, le=365)
):
    """获取记忆时间线（按天/周/月分组）"""
    now = datetime.datetime.utcnow()
    groups = []
    for i in range(min(days, 30)):
        d = now - datetime.timedelta(days=i)
        key = (
            d.strftime("%Y-%m-%d")
            if group_by == "day"
            else d.strftime("%Y-W%W") if group_by == "week" else d.strftime("%Y-%m")
        )
        if not groups or groups[-1]["key"] != key:
            groups.append({"key": key, "count": 0, "date": d.strftime("%Y-%m-%d")})
        elif group_by == "day":
            groups[-1]["count"] += 0  # placeholder

    return {"code": 0, "message": "success", "data": {"groups": groups, "group_by": group_by, "total_days": days}}


@router.get("/stats")
async def get_timeline_stats():
    """获取时间线统计信息"""
    return {
        "code": 0,
        "message": "success",
        "data": {
            "total_memories": 0,
            "memories_today": 0,
            "memories_this_week": 0,
            "memories_this_month": 0,
            "most_active_day": None,
            "avg_per_day": 0.0,
        },
    }
