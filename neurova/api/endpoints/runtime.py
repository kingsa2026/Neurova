from __future__ import annotations

"""
运行时管理接口 - Runtime Endpoint

功能:
1. 获取运行时状态 (GET /api/v1/runtime/status)
2. 获取资源使用 (GET /api/v1/runtime/resources)
3. 获取性能指标 (GET /api/v1/runtime/performance)
4. 执行垃圾回收 (POST /api/v1/runtime/gc)
"""

from neurova.core.logger import get_logger
import time
import uuid

from fastapi import APIRouter, Request
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel

from neurova.api.endpoints import get_app_state

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)],)

# P2-2：上一次 /performance 采样 (monotonic 秒, 累计请求数)——每秒速率的差分基线
_perf_last_sample = None


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
        logger.warning("Failed to get resource usage: %s", e)

    return resources


@router.get("/performance", response_model=PerformanceMetrics)
async def get_performance_metrics(request: Request):
    """获取性能指标（真数：core/metrics 注册表聚合）。

    P2-2（全库断点审计 2026-11-12）：原实现 TODO 恒全零假指标。现从
    HTTP 计数/时长直方图与缓存/连接池 gauge 聚合：
    - requests_per_second：距上次采样的每秒请求速率（首样无差分，诚实 0）
    - average_response_time：http_request_seconds 直方图 sum/count（秒）
    - error_rate：5xx 占比
    - cache_hit_rate：各进程内缓存 gauge 均值
    - active_connections：连接池 active gauge 合计
    """
    from neurova.core.metrics import get_metrics

    metrics = get_metrics()
    metrics.observe_caches()
    metrics.observe_pools()

    total_requests = 0
    error_requests = 0
    for family in metrics.http_requests_total.collect():
        for sample in family.samples:
            # 只认 counter 本体的 `_total` 样本：prometheus_client 会附送
            # `_created` 派生样本（值为创建时刻的 Unix 时间戳），混入求和会把
            # total 抬成 ~1e9 量级、error_rate 拉成 ~0.5 的死数（新建 label
            # 组时还会让 RPS 差分爆表）。按暴露的样本名逐字匹配，与
            # analytics._counterSamples 同一教训、同一口径。
            if sample.name != "neurova_http_requests_total":
                continue
            total_requests += int(sample.value)
            if str(sample.labels.get("status", "")).startswith("5"):
                error_requests += int(sample.value)

    duration_sum = 0.0
    duration_count = 0
    for family in metrics.http_request_seconds.collect():
        for sample in family.samples:
            if sample.name.endswith("_sum"):
                duration_sum += float(sample.value)
            elif sample.name.endswith("_count"):
                duration_count += int(sample.value)

    now = time.monotonic()
    global _perf_last_sample
    previous = _perf_last_sample
    _perf_last_sample = (now, total_requests)
    rps = 0.0
    if previous and now > previous[0]:
        rps = max(0, total_requests - previous[1]) / (now - previous[0])

    cache_values: list = []
    for family in metrics.cache_hit_rate.collect():
        for sample in family.samples:
            cache_values.append(float(sample.value))

    active_connections = 0
    for family in metrics.db_pool_connections.collect():
        for sample in family.samples:
            if sample.labels.get("state") == "active":
                active_connections += int(sample.value)

    return PerformanceMetrics(
        requests_per_second=round(rps, 3),
        average_response_time=round(duration_sum / duration_count, 6) if duration_count else 0,
        active_connections=active_connections,
        error_rate=round(error_requests / total_requests, 4) if total_requests else 0,
        cache_hit_rate=round(sum(cache_values) / len(cache_values), 4) if cache_values else 0,
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
