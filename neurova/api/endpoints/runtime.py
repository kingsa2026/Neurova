from __future__ import annotations

"""
运行时管理接口 - Runtime Endpoint

功能:
1. 获取运行时状态 (GET /api/v1/runtime/status)
2. 获取资源使用 (GET /api/v1/runtime/resources)
3. 获取性能指标 (GET /api/v1/runtime/performance)
4. 执行垃圾回收 (POST /api/v1/runtime/gc)
"""

import logging
import time
import typing
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class RuntimeStatus(BaseModel):
    """运行时状态"""
    status: str = "running"
    uptime: float = 0
    start_time: float = 0
    python_version: str = ""
    platform: str = ""
    agent_count: int = 0


class ResourceUsage(BaseModel):
    """资源使用"""
    cpu_percent: float = 0
    memory_percent: float = 0
    memory_used_mb: float = 0
    memory_total_mb: float = 0
    disk_percent: float = 0
    disk_used_gb: float = 0
    disk_total_gb: float = 0


class PerformanceMetrics(BaseModel):
    """性能指标"""
    requests_per_second: float = 0
    average_response_time: float = 0
    active_connections: int = 0
    error_rate: float = 0
    cache_hit_rate: float = 0


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_app_state():
    """获取应用状态"""
    from neurova.api.endpoints import get_app_state
    return get_app_state()


@router.get("/status", response_model=RuntimeStatus)
async def get_runtime_status(request: Request):
    """获取运行时状态"""
    app_state = _get_app_state()
    
    import sys
    
    status = RuntimeStatus(
        status="running",
        uptime=0,
        start_time=time.time(),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        platform=sys.platform,
        agent_count=0,
    )
    
    if app_state:
        if hasattr(app_state, "get_uptime"):
            status.uptime = app_state.get_uptime()
        if hasattr(app_state, "start_time"):
            status.start_time = app_state.start_time
        if hasattr(app_state, "agents"):
            status.agent_count = len(app_state.agents)
    
    return status


@router.get("/resources", response_model=ResourceUsage)
async def get_resource_usage(request: Request):
    """获取资源使用情况"""
    resources = ResourceUsage()
    
    try:
        import psutil
        
        # CPU
        resources.cpu_percent = psutil.cpu_percent(interval=0.1)
        
        # 内存
        memory = psutil.virtual_memory()
        resources.memory_percent = memory.percent
        resources.memory_used_mb = memory.used / (1024 * 1024)
        resources.memory_total_mb = memory.total / (1024 * 1024)
        
        # 磁盘
        disk = psutil.disk_usage("/")
        resources.disk_percent = disk.percent
        resources.disk_used_gb = disk.used / (1024 * 1024 * 1024)
        resources.disk_total_gb = disk.total / (1024 * 1024 * 1024)
    except ImportError:
        logger.warning("psutil not available")
    except Exception as e:
        logger.warning(f"Failed to get resource usage: {e}")
    
    return resources


@router.get("/performance", response_model=PerformanceMetrics)
async def get_performance_metrics(request: Request):
    """获取性能指标"""
    # TODO: 实现真正的性能指标收集
    return PerformanceMetrics(
        requests_per_second=0,
        average_response_time=0,
        active_connections=0,
        error_rate=0,
        cache_hit_rate=0,
    )


@router.post("/gc")
async def trigger_garbage_collection(request: Request):
    """执行垃圾回收"""
    request_id = _get_request_id(request)
    
    import gc
    
    collected = gc.collect()
    
    return {
        "code": 0,
        "message": "Garbage collection completed",
        "data": {
            "objects_collected": collected,
        },
        "request_id": request_id,
    }
