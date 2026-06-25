from __future__ import annotations

"""
审计日志接口 - Audit Endpoint

功能:
1. 获取审计日志 (GET /api/v1/audit)
2. 搜索审计日志 (POST /api/v1/audit/search)
3. 获取审计统计 (GET /api/v1/audit/stats)
"""

from neurova.core.logger import get_logger
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

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


@router.get("", response_model=List[AuditLog])
async def get_audit_logs(
    request: Request,
    user_id: Optional[str] = Query(default=None, description="用户ID筛选"),
    action: Optional[str] = Query(default=None, description="操作类型筛选"),
    resource_type: Optional[str] = Query(default=None, description="资源类型筛选"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取审计日志"""
    try:
        if get_audit_logger is None:
            logger.warning("Audit logger service not available")
            return []

        # 获取审计日志管理器
        get_audit_logger()

        # 获取审计日志
        # 注意：这里简化实现，实际应该根据筛选条件查询
        # AuditLogger可能有更复杂的查询方法
        logs = []

        # 这里可以添加实际的查询逻辑
        # 例如：logger_instance.get_logs(user_id=user_id, action=action, ...)

        # 返回空列表（实际实现需要扩展AuditLogger）
        return logs

    except Exception as e:
        logger.exception("Failed to get audit logs: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get audit logs: {str(e)}"
        )


@router.post("/search", response_model=List[AuditLog])
async def search_audit_logs(
    request: Request,
    body: AuditSearchRequest,
):
    """搜索审计日志"""
    try:
        if get_audit_logger is None:
            logger.warning("Audit logger service not available")
            return []

        # 获取审计日志管理器
        get_audit_logger()

        # 搜索审计日志
        # 注意：这里简化实现，实际应该根据搜索条件查询
        logs = []

        # 这里可以添加实际的搜索逻辑
        # 例如：logger_instance.search_logs(query=body.query, user_id=body.user_id, ...)

        # 返回空列表（实际实现需要扩展AuditLogger）
        return logs

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
):
    """获取审计统计"""
    try:
        if get_audit_logger is None:
            logger.warning("Audit logger service not available")
            return AuditStats()

        # 获取审计日志管理器
        get_audit_logger()

        # 获取审计统计
        # 注意：这里简化实现，实际应该计算统计信息
        # AuditLogger可能有统计方法

        # 返回默认统计（实际实现需要扩展AuditLogger）
        return AuditStats(
            total_logs=0,
            unique_users=0,
            unique_actions=0,
            action_counts={},
            resource_type_counts={},
        )

    except Exception as e:
        logger.exception("Failed to get audit stats: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get audit stats: {str(e)}"
        )
