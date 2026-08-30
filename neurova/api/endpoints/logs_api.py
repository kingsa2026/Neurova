"""
工作日志系统 API

提供以下端点:
- POST   /v1/logs-api                记录日志
- GET    /v1/logs-api                获取日志列表
- GET    /v1/logs-api/daily-summary  获取日总结
- GET    /v1/logs-api/weekly-report  获取周报
- GET    /v1/logs-api/stats          获取统计
- GET    /v1/logs-api/export         导出日志
"""

import datetime
from neurova.core.logger import get_logger
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user

logger = get_logger(__name__)
# P0 安全修复: 工作日志含用户活动数据，读写/导出均必须认证
router = APIRouter(dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class LogEntry(BaseModel):
    """日志条目"""

    log_id: str
    user_id: str
    agent_id: str
    title: str
    content: str = ""
    category: str = "general"
    tags: List[str] = []
    duration_minutes: Optional[int] = None
    created_at: float = 0


class LogCreate(BaseModel):
    """创建日志请求"""

    title: str = Field(..., description="日志标题")
    content: str = Field(default="", description="日志内容")
    category: str = Field(default="general", description="分类")
    tags: List[str] = Field(default_factory=list, description="标签")
    duration_minutes: Optional[int] = Field(default=None, description="持续时间(分钟)")


class DailySummary(BaseModel):
    """日总结"""

    date: str
    total_logs: int = 0
    total_duration: int = 0
    categories: Dict[str, int] = {}
    tags: Dict[str, int] = {}


class WeeklyReport(BaseModel):
    """周报"""

    week_start: str
    week_end: str
    total_logs: int = 0
    total_duration: int = 0
    daily_breakdown: List[DailySummary] = []
    top_categories: Dict[str, int] = {}
    top_tags: Dict[str, int] = {}


class LogStats(BaseModel):
    """日志统计"""

    total_logs: int = 0
    total_duration: int = 0
    by_category: Dict[str, int] = {}
    by_tag: Dict[str, int] = {}
    by_day: Dict[str, int] = {}


# ---------------------------------------------------------------------------
# In-Memory Store
# ---------------------------------------------------------------------------

_logs_store: Dict[str, Dict[str, Any]] = {}


def _get_wls():
    """获取工作日志系统"""
    try:
        from neurova.projects.work_log import WorkLogSystem

        return WorkLogSystem()
    except Exception:
        return None


def _get_user_from_auth(auth_header: Optional[str] = None) -> Dict[str, str]:
    """从认证头获取用户信息"""
    return {"user_id": "default", "agent_id": "default"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", response_model=LogEntry)
async def create_log(body: LogCreate):
    """记录日志"""
    log_id = str(uuid.uuid4())
    now = time.time()

    # 尝试使用后端系统
    wls = _get_wls()
    if wls and hasattr(wls, "create_log"):
        try:
            result = await wls.create_log(
                title=body.title,
                content=body.content,
                category=body.category,
                tags=body.tags,
                duration_minutes=body.duration_minutes,
            )
            return LogEntry(**result)
        except Exception as e:
            logger.warning("WorkLogSystem.create_log failed: %s", e)

    # 使用内存存储
    entry = {
        "log_id": log_id,
        "user_id": "default",
        "agent_id": "default",
        "title": body.title,
        "content": body.content,
        "category": body.category,
        "tags": body.tags,
        "duration_minutes": body.duration_minutes,
        "created_at": now,
    }
    _logs_store[log_id] = entry
    return LogEntry(**entry)


@router.get("", response_model=List[LogEntry])
async def list_logs(
    category: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    """获取日志列表"""
    # 尝试使用后端系统
    wls = _get_wls()
    if wls and hasattr(wls, "list_logs"):
        try:
            logs = await wls.list_logs(
                category=category,
                tag=tag,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
            return [LogEntry(**l) for l in logs]
        except Exception as e:
            logger.warning("WorkLogSystem.list_logs failed: %s", e)

    # 使用内存存储
    logs = list(_logs_store.values())

    if category:
        logs = [l for l in logs if l.get("category") == category]
    if tag:
        logs = [l for l in logs if tag in l.get("tags", [])]

    logs.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return [LogEntry(**l) for l in logs[:limit]]


@router.get("/daily-summary", response_model=DailySummary)
async def get_daily_summary(
    date: Optional[str] = Query(default=None, description="日期 YYYY-MM-DD"),
):
    """获取日总结"""
    if not date:
        date = datetime.date.today().isoformat()

    # 筛选当天的日志
    day_logs = []
    for log in _logs_store.values():
        log_date = datetime.datetime.fromtimestamp(log.get("created_at", 0)).date().isoformat()
        if log_date == date:
            day_logs.append(log)

    total_duration = sum(l.get("duration_minutes", 0) or 0 for l in day_logs)

    categories: Dict[str, int] = {}
    tags: Dict[str, int] = {}
    for log in day_logs:
        cat = log.get("category", "general")
        categories[cat] = categories.get(cat, 0) + 1
        for tag in log.get("tags", []):
            tags[tag] = tags.get(tag, 0) + 1

    return DailySummary(
        date=date,
        total_logs=len(day_logs),
        total_duration=total_duration,
        categories=categories,
        tags=tags,
    )


@router.get("/weekly-report", response_model=WeeklyReport)
async def get_weekly_report(
    week_offset: int = Query(default=0, description="周偏移量 (0=本周)"),
):
    """获取周报"""
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday() + 7 * week_offset)
    week_end = week_start + datetime.timedelta(days=6)

    daily_breakdown = []
    total_logs = 0
    total_duration = 0
    top_categories: Dict[str, int] = {}
    top_tags: Dict[str, int] = {}

    for i in range(7):
        day = week_start + datetime.timedelta(days=i)
        day_str = day.isoformat()

        day_logs = []
        for log in _logs_store.values():
            log_date = datetime.datetime.fromtimestamp(log.get("created_at", 0)).date().isoformat()
            if log_date == day_str:
                day_logs.append(log)

        day_duration = sum(l.get("duration_minutes", 0) or 0 for l in day_logs)
        day_categories: Dict[str, int] = {}
        day_tags: Dict[str, int] = {}

        for log in day_logs:
            cat = log.get("category", "general")
            day_categories[cat] = day_categories.get(cat, 0) + 1
            top_categories[cat] = top_categories.get(cat, 0) + 1
            for tag in log.get("tags", []):
                day_tags[tag] = day_tags.get(tag, 0) + 1
                top_tags[tag] = top_tags.get(tag, 0) + 1

        daily_breakdown.append(
            DailySummary(
                date=day_str,
                total_logs=len(day_logs),
                total_duration=day_duration,
                categories=day_categories,
                tags=day_tags,
            )
        )

        total_logs += len(day_logs)
        total_duration += day_duration

    return WeeklyReport(
        week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
        total_logs=total_logs,
        total_duration=total_duration,
        daily_breakdown=daily_breakdown,
        top_categories=top_categories,
        top_tags=top_tags,
    )


@router.get("/stats", response_model=LogStats)
async def get_stats():
    """获取项目统计"""
    logs = list(_logs_store.values())

    total_duration = sum(l.get("duration_minutes", 0) or 0 for l in logs)

    by_category: Dict[str, int] = {}
    by_tag: Dict[str, int] = {}
    by_day: Dict[str, int] = {}

    for log in logs:
        cat = log.get("category", "general")
        by_category[cat] = by_category.get(cat, 0) + 1

        for tag in log.get("tags", []):
            by_tag[tag] = by_tag.get(tag, 0) + 1

        day = datetime.datetime.fromtimestamp(log.get("created_at", 0)).date().isoformat()
        by_day[day] = by_day.get(day, 0) + 1

    return LogStats(
        total_logs=len(logs),
        total_duration=total_duration,
        by_category=by_category,
        by_tag=by_tag,
        by_day=by_day,
    )


@router.get("/export")
async def export_logs(
    format: str = Query(default="json", description="导出格式: json/csv"),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
):
    """导出日志"""
    logs = list(_logs_store.values())

    if start_date:
        logs = [
            l for l in logs if datetime.datetime.fromtimestamp(l.get("created_at", 0)).date().isoformat() >= start_date
        ]
    if end_date:
        logs = [
            l for l in logs if datetime.datetime.fromtimestamp(l.get("created_at", 0)).date().isoformat() <= end_date
        ]

    if format == "csv":
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["log_id", "title", "content", "category", "tags", "duration_minutes", "created_at"])

        for log in logs:
            writer.writerow(
                [
                    log.get("log_id", ""),
                    log.get("title", ""),
                    log.get("content", ""),
                    log.get("category", ""),
                    ",".join(log.get("tags", [])),
                    log.get("duration_minutes", ""),
                    datetime.datetime.fromtimestamp(log.get("created_at", 0)).isoformat(),
                ]
            )

        from fastapi.responses import StreamingResponse

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=logs.csv"},
        )

    return {"code": 0, "data": {"logs": logs}}
