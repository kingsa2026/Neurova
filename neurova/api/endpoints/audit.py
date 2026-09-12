from __future__ import annotations

"""
审计日志接口 - Audit Endpoint

功能:
1. 获取审计日志 (GET /api/v1/audit)
2. 搜索审计日志 (POST /api/v1/audit/search)
3. 获取审计统计 (GET /api/v1/audit/stats)
"""

from neurova.core.logger import get_logger
import datetime
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from neurova.api.deps import require_admin

logger = get_logger(__name__)

router = APIRouter()

# 尝试导入审计日志管理器
try:
    from neurova.security.audit_logger import (
        AuditEventType,
        AuditLogEntry,
        AuditLogger,
        AuditSeverity,
        get_audit_logger,
    )
except ImportError:
    logger.warning("Audit logger service not available")
    get_audit_logger = None
    AuditLogger = None
    AuditEventType = None
    AuditSeverity = None
    AuditLogEntry = None


class AuditLog(BaseModel):
    """审计日志"""

    log_id: str
    timestamp: float
    user_id: Optional[str] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    details: Dict[str, Any] = {}
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AuditSearchRequest(BaseModel):
    """审计日志搜索请求"""

    query: Optional[str] = None
    user_id: Optional[str] = None
    action: Optional[str] = None
    resource_type: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    limit: int = Field(default=20, ge=1, le=100)


class AuditStats(BaseModel):
    """审计统计"""

    total_logs: int = 0
    unique_users: int = 0
    unique_actions: int = 0
    action_counts: Dict[str, int] = {}
    resource_type_counts: Dict[str, int] = {}


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _convert_audit_entry_to_log(entry: AuditLogEntry) -> AuditLog:
    """将AuditLogEntry转换为API响应格式"""
    return AuditLog(
        log_id=f"{entry.event_type.value}_{int(entry.timestamp * 1000)}",
        timestamp=entry.timestamp,
        user_id=entry.user_id if entry.user_id else None,
        action=entry.action,
        resource_type=entry.resource_type,
        resource_id=entry.resource_id if entry.resource_id else None,
        details=entry.details,
        ip_address=entry.ip_address if entry.ip_address else None,
        user_agent=entry.user_agent if entry.user_agent else None,
    )


def _entry_searchable(entry: AuditLogEntry) -> str:
    """搜索端点可用的拼接检索面"""
    return " ".join(
        [entry.action, entry.user_id, entry.resource_type, entry.resource_id]
        + [str(v) for v in (entry.details or {}).values()]
    ).lower()


def _parse_time(value: Optional[str]) -> Optional[float]:
    """接受 epoch 数字或 ISO8601 字符串（AuditPage 传 dateRange.toISOString()）"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid time value: {value!r}")


def _entry_to_record(entry: AuditLogEntry) -> Dict[str, Any]:
    """AuditPage AuditRecord 契约（id/timestamp(ISO)/user/action/resource/details）"""
    ts = datetime.datetime.fromtimestamp(entry.timestamp, datetime.timezone.utc)
    return {
        "id": f"{entry.event_type.value}_{int(entry.timestamp * 1000)}",
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "user": entry.user_id,
        "action": entry.action,
        "resource": entry.resource_type or entry.resource_id,
        "details": entry.details,
    }


_WARN_SEVERITIES = {AuditSeverity.HIGH, AuditSeverity.CRITICAL}


def _query_entries(user: Optional[str] = None, start: Optional[float] = None,
                   end: Optional[float] = None, action: Optional[str] = None) -> List[AuditLogEntry]:
    """统一取数：logger.query 只支持 user_id/时间，action 在服务层过滤"""
    entries = get_audit_logger().query(user_id=user, start_time=start, end_time=end, limit=5000)
    if action:
        entries = [e for e in entries if e.action == action]
    return entries


@router.get("")
async def get_audit_logs(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: Optional[str] = Query(default=None, description="用户ID筛选"),
    action: Optional[str] = Query(default=None, description="操作类型筛选"),
    start: Optional[str] = Query(default=None, description="开始时间(ISO/epoch)"),
    end: Optional[str] = Query(default=None, description="结束时间(ISO/epoch)"),
    _admin: Dict[str, Any] = Depends(require_admin()),
):
    """获取审计日志（BUG AUDIT S-08: 原零鉴权; 审计数据仅管理员, 前端
    AuditPage 挂在 platformAdmin 导航分组）。
    2026-09-12 空数据修复: 原恒返回 []（stub），现接 AuditLogger SQLite 真实查询，
    并按 FE 信封契约 {items,total,page,page_size,stats{total,today,warnings}} 返回。"""
    try:
        if get_audit_logger is None:
            logger.warning("Audit logger service not available")
            return {"code": 0, "message": "success", "data": {
                "items": [], "total": 0, "page": page, "page_size": page_size,
                "stats": {"total": 0, "today": 0, "warnings": 0},
            }}

        entries = _query_entries(user, _parse_time(start), _parse_time(end), action)
        total = len(entries)
        midnight = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp()
        stats = {
            "total": total,
            "today": sum(1 for e in entries if e.timestamp >= midnight),
            "warnings": sum(1 for e in entries if e.severity in _WARN_SEVERITIES),
        }
        lo = (page - 1) * page_size
        return {"code": 0, "message": "success", "data": {
            "items": [_entry_to_record(e) for e in entries[lo: lo + page_size]],
            "total": total, "page": page, "page_size": page_size, "stats": stats,
        }}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get audit logs: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get audit logs: {str(e)}"
        )


@router.get("/export")
async def export_audit_logs(
    request: Request,
    user: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    _admin: Dict[str, Any] = Depends(require_admin()),
):
    """导出审计日志 JSON（AuditPage Export 按钮；原后端无此路由恒 404）"""
    try:
        if get_audit_logger is None:
            raise HTTPException(status_code=503, detail="Audit logger service not available")
        entries = _query_entries(user, _parse_time(start), _parse_time(end), action)
        payload = [e.to_dict() for e in entries]
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return JSONResponse(
            content=payload,
            headers={"Content-Disposition": f"attachment; filename=audit_export_{stamp}.json"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to export audit logs: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to export audit logs: {str(e)}"
        )


@router.post("/search", response_model=List[AuditLog])
async def search_audit_logs(
    request: Request,
    body: AuditSearchRequest,
    _admin: Dict[str, Any] = Depends(require_admin()),
):
    """搜索审计日志"""
    try:
        if get_audit_logger is None:
            logger.warning("Audit logger service not available")
            return []

        entries = get_audit_logger().query(
            user_id=body.user_id,
            start_time=body.start_time,
            end_time=body.end_time,
            limit=5000,
        )
        if body.action:
            entries = [e for e in entries if e.action == body.action]
        if body.resource_type:
            entries = [e for e in entries if e.resource_type == body.resource_type]
        text = (body.query or "").lower()
        if text:
            entries = [
                e for e in entries
                if text in _entry_searchable(e)
            ]
        return [_convert_audit_entry_to_log(e) for e in entries[: body.limit]]

    except Exception as e:
        logger.exception("Failed to search audit logs: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to search audit logs: {str(e)}"
        )


@router.get("/stats", response_model=AuditStats)
async def get_audit_stats(
    request: Request,
    start_time: Optional[float] = Query(default=None, description="开始时间"),
    end_time: Optional[float] = Query(default=None, description="结束时间"),
    _admin: Dict[str, Any] = Depends(require_admin()),
):
    """获取审计统计"""
    try:
        if get_audit_logger is None:
            logger.warning("Audit logger service not available")
            return AuditStats()

        entries = get_audit_logger().query(
            start_time=start_time, end_time=end_time, limit=5000
        )
        action_counts: Dict[str, int] = {}
        resource_counts: Dict[str, int] = {}
        for e in entries:
            action_counts[e.action] = action_counts.get(e.action, 0) + 1
            if e.resource_type:
                resource_counts[e.resource_type] = resource_counts.get(e.resource_type, 0) + 1
        return AuditStats(
            total_logs=len(entries),
            unique_users=len({e.user_id for e in entries if e.user_id}),
            unique_actions=len(action_counts),
            action_counts=action_counts,
            resource_type_counts=resource_counts,
        )

    except Exception as e:
        logger.exception("Failed to get audit stats: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get audit stats: {str(e)}"
        )
