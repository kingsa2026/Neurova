from __future__ import annotations

"""
监控接口 - Monitor Endpoint

功能:
1. 获取系统状态 (GET /api/v1/monitor/status)
2. 获取资源使用 (GET /api/v1/monitor/resources)
3. 获取连接状态 (GET /api/v1/monitor/connections)
4. 获取告警信息 (GET /api/v1/monitor/alerts)
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from neurova.api.endpoints import get_app_state
from neurova.api.deps import get_current_user, require_admin

logger = get_logger(__name__)

router = APIRouter()


class SystemStatus(BaseModel):
    """系统状态"""

    status: str = "running"
    uptime: float = 0
    version: str = "1.0.0-beta1"
    python_version: str = ""
    start_time: float = 0


class ResourceUsage(BaseModel):
    """资源使用"""

    cpu_percent: float = 0
    memory_percent: float = 0
    memory_used: int = 0
    memory_total: int = 0
    disk_percent: float = 0
    disk_used: int = 0
    disk_total: int = 0


class ConnectionStatus(BaseModel):
    """连接状态"""

    active_connections: int = 0
    total_connections: int = 0
    websocket_connections: int = 0
    database_connections: int = 0


class Alert(BaseModel):
    """告警信息"""

    alert_id: str
    level: str
    message: str
    source: str = ""
    timestamp: float = 0
    resolved: bool = False


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_app_state():
    """获取应用状态"""
    return get_app_state()


@router.get("/status", response_model=SystemStatus)
async def get_system_status(request: Request, current_user: dict = Depends(get_current_user)):
    """获取系统状态 — 登录用户可读"""
    _get_request_id(request)

    import sys

    state = _get_app_state()
    start_time = state.get("start_time", time.time()) if state else time.time()

    return SystemStatus(
        status="running",
        uptime=time.time() - start_time,
        version="1.0.0-beta1",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        start_time=start_time,
    )


@router.get("/resources", response_model=ResourceUsage)
async def get_resource_usage(request: Request, current_user: dict = Depends(get_current_user)):
    """获取资源使用 — 登录用户可读"""
    _get_request_id(request)

    usage = ResourceUsage()

    try:
        import psutil

        # CPU
        usage.cpu_percent = psutil.cpu_percent()

        # 内存
        mem = psutil.virtual_memory()
        usage.memory_percent = mem.percent
        usage.memory_used = mem.used
        usage.memory_total = mem.total

        # 磁盘
        disk = psutil.disk_usage("/")
        usage.disk_percent = disk.percent
        usage.disk_used = disk.used
        usage.disk_total = disk.total

    except ImportError:
        logger.warning("psutil not available for resource monitoring")

    return usage


@router.get("/connections", response_model=ConnectionStatus)
async def get_connections(request: Request, current_user: dict = Depends(get_current_user)):
    """获取连接状态 — 登录用户可读"""
    _get_request_id(request)

    return ConnectionStatus(
        active_connections=0,
        total_connections=0,
        websocket_connections=0,
        database_connections=0,
    )


@router.get("/alerts", response_model=List[Alert])
async def get_alerts(
    request: Request,
    current_user: dict = Depends(get_current_user),
    level: Optional[str] = Query(default=None),
    resolved: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """获取告警信息 — 登录用户可读"""
    _get_request_id(request)

    # TODO: 从告警存储获取告警
    alerts = []

    return alerts


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(request: Request, alert_id: str, admin: dict = Depends(require_admin())):
    """解决告警 — 仅管理员"""
    _get_request_id(request)

    # TODO: 标记告警为已解决

    return {
        "code": 0,
        "message": f"Alert '{alert_id}' resolved",
    }
