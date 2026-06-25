from __future__ import annotations

"""
日志接口 - Logs Endpoint

功能:
1. 获取日志列表 (GET /api/v1/logs)
2. 获取日志详情 (GET /api/v1/logs/{log_id})
3. 搜索日志 (POST /api/v1/logs/search)
4. 清空日志 (DELETE /api/v1/logs)
"""

from neurova.core.logger import get_logger
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter()


class LogEntry(BaseModel):
    """日志条目"""

    log_id: str
    level: str
    message: str
    source: str = ""
    timestamp: float = 0
    metadata: Dict[str, Any] = {}


class SearchLogsRequest(BaseModel):
    """搜索日志请求"""

    query: str = Field(default="", description="搜索查询")
    level: Optional[str] = Field(default=None, description="日志级别过滤")
    source: Optional[str] = Field(default=None, description="来源过滤")
    start_time: Optional[float] = Field(default=None, description="开始时间")
    end_time: Optional[float] = Field(default=None, description="结束时间")
    limit: int = Field(default=100, description="返回数量限制")


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


@router.get("", response_model=List[LogEntry])
async def list_logs(
    request: Request,
    level: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """获取日志列表"""
    _get_request_id(request)

    # TODO: 从日志存储获取日志
    # 这里返回内存中的日志缓冲区内容
    logs = []

    # 获取最近的日志记录
    try:
        from neurova.core.event_bus import get_event_bus

        event_bus = get_event_bus()
        event_log = event_bus.get_event_log(limit=limit)

        for entry in event_log:
            if level and entry.get("priority", "").name.lower() != level.lower():
                continue
            logs.append(
                LogEntry(
                    log_id=str(uuid.uuid4())[:8],
                    level=(
                        entry.get("priority", "INFO").name
                        if hasattr(entry.get("priority", ""), "name")
                        else str(entry.get("priority", "INFO"))
                    ),
                    message=f"Event: {entry.get('event', 'unknown')}",
                    source=entry.get("source", ""),
                    timestamp=entry.get("timestamp", 0),
                )
            )
    except Exception as e:
        logger.warning("Get logs error: %s", e)

    return logs


@router.post("/search", response_model=List[LogEntry])
async def search_logs(request: Request, body: SearchLogsRequest):
    """搜索日志"""
    _get_request_id(request)

    logs = []
    try:
        from neurova.core.event_bus import get_event_bus

        event_bus = get_event_bus()
        event_log = event_bus.get_event_log(limit=body.limit)

        for entry in event_log:
            # 过滤
            if body.level:
                entry_level = (
                    entry.get("priority", "").name
                    if hasattr(entry.get("priority", ""), "name")
                    else str(entry.get("priority", ""))
                )
                if entry_level.lower() != body.level.lower():
                    continue

            if body.source and entry.get("source", "") != body.source:
                continue

            if body.start_time and entry.get("timestamp", 0) < body.start_time:
                continue

            if body.end_time and entry.get("timestamp", 0) > body.end_time:
                continue

            # 搜索
            message = f"Event: {entry.get('event', 'unknown')}"
            if body.query and body.query.lower() not in message.lower():
                continue

            logs.append(
                LogEntry(
                    log_id=str(uuid.uuid4())[:8],
                    level=(
                        entry.get("priority", "INFO").name
                        if hasattr(entry.get("priority", ""), "name")
                        else str(entry.get("priority", "INFO"))
                    ),
                    message=message,
                    source=entry.get("source", ""),
                    timestamp=entry.get("timestamp", 0),
                )
            )
    except Exception as e:
        logger.warning("Search logs error: %s", e)

    return logs


@router.delete("")
async def clear_logs(request: Request):
    """清空日志"""
    _get_request_id(request)

    try:
        from neurova.core.event_bus import get_event_bus

        event_bus = get_event_bus()
        event_bus.clear_event_log()
    except Exception as e:
        logger.warning("Clear logs error: %s", e)

    return {"code": 0, "message": "Logs cleared"}


@router.get("/levels")
async def get_log_levels(request: Request):
    """获取可用的日志级别"""
    _get_request_id(request)

    return {
        "code": 0,
        "data": {
            "levels": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        },
    }
