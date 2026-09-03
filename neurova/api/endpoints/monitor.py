from __future__ import annotations

"""
监控接口 - Monitor Endpoint

功能:
1. 获取系统状态 (GET /api/v1/monitor/status)
2. 获取资源使用 (GET /api/v1/monitor/resources)   — psutil 真值 + 滚动历史
3. 获取连接状态 (GET /api/v1/monitor/connections) — 真实状态汇总(providers/agents/db)
4. 获取告警信息 (GET /api/v1/monitor/alerts)      — ExecutionMonitor 真实告警
5. 解决告警 (POST /api/v1/monitor/alerts/{id}/resolve) — acknowledge

2026-09-03 修复: 原实现 connections 恒 0 计数 stub、alerts TODO 恒空、
resources 扁平字段与前端嵌套契约错位 → 页面全空。全部端点要求 admin
(与前端 MonitorPage 的 isAdmin gate 一致)。
"""

from neurova.core.logger import get_logger
import time
import uuid
import psutil
from collections import deque
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from neurova.api.endpoints import get_app_state
from neurova.api.deps import require_admin

logger = get_logger(__name__)

router = APIRouter()

# 资源历史: 进程内滚动采样(10s 自动刷新足够; 上限 20 点)
_RESOURCE_HISTORY: Dict[str, deque] = {
    "cpu": deque(maxlen=20),
    "memory": deque(maxlen=20),
    "disk": deque(maxlen=20),
}
_HISTORY_RECORDED = {"last_ts": 0.0}


class SystemStatus(BaseModel):
    """系统状态"""

    status: str = "running"
    uptime: float = 0
    version: str = "1.0.0-beta1"
    python_version: str = ""
    start_time: float = 0


class ResourceSnapshot(BaseModel):
    """单个资源快照(前端嵌套契约)"""

    usage: float = 0
    trend: float = 0
    history: List[float] = []
    used: int = 0
    total: int = 0


class ResourceUsage(BaseModel):
    """资源使用 — 前端契约: cpu/memory/disk 各为对象"""

    cpu: ResourceSnapshot
    memory: ResourceSnapshot
    disk: ResourceSnapshot


class ConnectionStatus(BaseModel):
    """连接状态 — 前端契约: 状态汇总数组"""

    name: str
    detail: str
    status: str = "connected"


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_app_state():
    """获取应用状态"""
    return get_app_state()


def _record_history(key: str, usage: float) -> List[float]:
    """滚动记录采样点; 两次采样间隔 <2s 视为同轮(avoid双写)"""
    now = time.time()
    if key == "cpu" or (now - _HISTORY_RECORDED["last_ts"]) >= 2.0:
        _RESOURCE_HISTORY[key].append(usage)
        _HISTORY_RECORDED["last_ts"] = now
    return list(_RESOURCE_HISTORY[key])


def _trend(history: List[float]) -> float:
    """最近两点差值(正=上升)"""
    if len(history) >= 2:
        return round(history[-1] - history[-2], 2)
    return 0.0


@router.get("/status", response_model=SystemStatus)
async def get_system_status(request: Request, _admin: dict = Depends(require_admin())):
    """获取系统状态 — 仅管理员"""
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
async def get_resource_usage(request: Request, _admin: dict = Depends(require_admin())):
    """获取资源使用 — psutil 真值; 前端契约: 每资源带 usage/trend/history"""
    _get_request_id(request)

    try:
        cpu = psutil.cpu_percent()
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        cpu_hist = _record_history("cpu", cpu)
        mem_hist = _record_history("memory", mem.percent)
        disk_hist = _record_history("disk", disk.percent)

        return ResourceUsage(
            cpu=ResourceSnapshot(usage=cpu, trend=_trend(cpu_hist), history=cpu_hist, used=0, total=0),
            memory=ResourceSnapshot(
                usage=mem.percent, trend=_trend(mem_hist), history=mem_hist,
                used=mem.used, total=mem.total,
            ),
            disk=ResourceSnapshot(
                usage=disk.percent, trend=_trend(disk_hist), history=disk_hist,
                used=disk.used, total=disk.total,
            ),
        )
    except Exception as e:
        logger.warning("resource monitoring failed: %s", e)
        return ResourceUsage(
            cpu=ResourceSnapshot(), memory=ResourceSnapshot(), disk=ResourceSnapshot()
        )


def _provider_connection() -> ConnectionStatus:
    """LLM 服务商健康汇总(真实来源: provider_manager)"""
    try:
        from neurova.llm.provider_manager import get_provider_manager

        providers = get_provider_manager().list_providers()
        enabled = [p for p in providers if getattr(p, "enabled", True)]
        healthy = sum(
            1
            for p in enabled
            if getattr(p, "health_status", "unknown") in ("healthy", "unknown")
        )
        detail = f"{healthy}/{len(enabled)} healthy"
        status = "connected" if healthy == len(enabled) else "degraded"
        return ConnectionStatus(name="LLM Providers", detail=detail, status=status)
    except Exception as e:
        logger.warning("provider health check failed: %s", e)
        return ConnectionStatus(name="LLM Providers", detail="unknown", status="degraded")


def _db_connection() -> ConnectionStatus:
    """SQLite 数据库可读性探针"""
    try:
        import sqlite3

        state = _get_app_state()
        db_path = "data/neurova.db"
        if state and state.get("database_path"):
            db_path = state["database_path"]
        conn = sqlite3.connect(db_path, timeout=1)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return ConnectionStatus(name="SQLite Database", detail="ok", status="connected")
    except Exception as e:
        logger.warning("database probe failed: %s", e)
        return ConnectionStatus(name="SQLite Database", detail="unavailable", status="degraded")


@router.get("/connections", response_model=List[ConnectionStatus])
async def get_connections(request: Request, _admin: dict = Depends(require_admin())):
    """获取连接状态 — 真实状态汇总(providers/agents/db), 前端契约: 数组"""
    _get_request_id(request)

    items: List[ConnectionStatus] = [_provider_connection(), _db_connection()]

    state = _get_app_state()
    agents = getattr(state, "agents", None) if state else None
    if isinstance(agents, dict) and agents:
        items.append(
            ConnectionStatus(name="Agent Runtime", detail=f"{len(agents)} agents", status="connected")
        )

    from neurova.shared_core.execution_engine import get_execution_engine

    monitor = get_execution_engine().get_execution_monitor()
    if monitor is not None:
        n_alerts = len(monitor.get_alerts(acknowledged=False))
        items.append(
            ConnectionStatus(
                name="Execution Monitor",
                detail=f"{n_alerts} open alerts",
                status="warning" if n_alerts else "connected",
            )
        )

    return items


@router.get("/alerts")
async def get_alerts(
    request: Request,
    _admin: dict = Depends(require_admin()),
    level: Optional[str] = Query(default=None),
    resolved: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """获取告警 — ExecutionMonitor 真实告警; 前端契约: {id,severity,message,...}"""
    _get_request_id(request)

    from neurova.shared_core.execution_engine import get_execution_engine

    monitor = get_execution_engine().get_execution_monitor()
    if monitor is None:
        return []

    try:
        from neurova.execution_engine.execution_monitor import AlertLevel

        lvl = AlertLevel(level) if level else None
        records = monitor.get_alerts(level=lvl, acknowledged=resolved, limit=limit)
    except Exception as e:
        logger.warning("alert query failed: %s", e)
        return []

    def _map(a: Any) -> Dict[str, Any]:
        ts = getattr(a.timestamp, "timestamp", None)
        return {
            "id": a.alert_id,
            "severity": a.level.value,
            "title": a.title,
            "message": a.message,
            "source": a.source,
            "timestamp": ts() if callable(ts) else 0,
            "resolved": a.acknowledged,
        }

    return [_map(a) for a in records]


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(request: Request, alert_id: str, _admin: dict = Depends(require_admin())):
    """解决告警 — acknowledge; 不存在返回 404"""
    _get_request_id(request)

    from neurova.shared_core.execution_engine import get_execution_engine

    monitor = get_execution_engine().get_execution_monitor()
    if monitor is None or not monitor.acknowledge_alert(alert_id):
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found")

    return {
        "code": 0,
        "message": f"Alert '{alert_id}' resolved",
    }
