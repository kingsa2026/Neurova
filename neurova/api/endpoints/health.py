from __future__ import annotations

"""
系统健康检查和监控 API

端点:
- GET /v1/health - 获取系统健康状态
- GET /v1/health/checks - 获取所有检查项
- GET /v1/health/checks/{name} - 获取单个检查结果
- POST /v1/health/checks/{name}/run - 手动执行检查
- POST /v1/health/recover - 触发恢复
- GET /v1/health/report - 获取详细健康报告
"""

import logging
import typing
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class HealthStatusResponse(BaseModel):
    """健康状态响应"""
    status: str
    timestamp: float
    uptime: float = 0
    checks_count: int = 0
    healthy_count: int = 0
    unhealthy_count: int = 0


class CheckResultResponse(BaseModel):
    """检查结果响应"""
    name: str
    status: str
    message: str = ""
    duration: float = 0
    check_type: str = ""


class HealthReportResponse(BaseModel):
    """健康报告响应"""
    status: str
    checks: Dict[str, Any]
    total_checks: int
    healthy_count: int
    unhealthy_count: int
    timestamp: float


class RecoveryResponse(BaseModel):
    """恢复响应"""
    success: bool
    message: str
    actions_taken: List[str] = []


class RegisterCheckRequest(BaseModel):
    """注册检查请求"""
    name: str
    check_type: str = "custom"
    description: str = ""
    timeout: float = 5.0
    critical: bool = False


def _get_health_checker():
    """获取健康检查器"""
    from neurova.api.endpoints import get_health_checker
    return get_health_checker()


@router.get("", response_model=HealthStatusResponse)
async def get_health_status():
    """获取系统整体健康状态"""
    checker = _get_health_checker()
    if not checker:
        return HealthStatusResponse(
            status="unknown",
            timestamp=0,
            message="Health checker not available",
        )

    checker.run_all_checks()
    report = checker.get_report()

    return HealthStatusResponse(
        status=report["status"],
        timestamp=report["timestamp"],
        checks_count=report["total_checks"],
        healthy_count=report["healthy_count"],
        unhealthy_count=report["unhealthy_count"],
    )


@router.get("/checks", response_model=List[CheckResultResponse])
async def get_all_checks():
    """获取所有已注册的健康检查项及最新结果"""
    checker = _get_health_checker()
    if not checker:
        return []

    results = checker.get_all_results()
    return [
        CheckResultResponse(
            name=name,
            status=result.status.value,
            message=result.message,
            duration=result.duration,
            check_type=result.check_type.value,
        )
        for name, result in results.items()
    ]


@router.get("/checks/{name}", response_model=CheckResultResponse)
async def get_check_result(name: str):
    """获取指定健康检查的最新结果"""
    checker = _get_health_checker()
    if not checker:
        raise HTTPException(status_code=503, detail="Health checker not available")

    result = checker.get_check_result(name)
    if not result:
        raise HTTPException(status_code=404, detail=f"Check '{name}' not found")

    return CheckResultResponse(
        name=result.name,
        status=result.status.value,
        message=result.message,
        duration=result.duration,
        check_type=result.check_type.value,
    )


@router.post("/checks/{name}/run", response_model=CheckResultResponse)
async def run_check(name: str):
    """手动触发指定健康检查"""
    checker = _get_health_checker()
    if not checker:
        raise HTTPException(status_code=503, detail="Health checker not available")

    result = checker.run_check(name)
    if not result:
        raise HTTPException(status_code=404, detail=f"Check '{name}' not found")

    return CheckResultResponse(
        name=result.name,
        status=result.status.value,
        message=result.message,
        duration=result.duration,
        check_type=result.check_type.value,
    )


@router.get("/report", response_model=HealthReportResponse)
async def get_health_report():
    """获取完整的系统健康报告"""
    checker = _get_health_checker()
    if not checker:
        raise HTTPException(status_code=503, detail="Health checker not available")

    checker.run_all_checks()
    report = checker.get_report()

    return HealthReportResponse(**report)


@router.post("/recover", response_model=RecoveryResponse)
async def trigger_recovery():
    """触发系统恢复"""
    # TODO: 实现恢复逻辑
    return RecoveryResponse(
        success=True,
        message="Recovery triggered",
        actions_taken=["No automatic recovery actions configured"],
    )
