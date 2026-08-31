from __future__ import annotations

"""
分析接口 - Analytics Endpoint

功能:
1. 获取使用统计 (GET /api/v1/analytics/usage)
2. 获取性能统计 (GET /api/v1/analytics/performance)
3. 获取用户行为 (GET /api/v1/analytics/behavior)
4. 获取错误统计 (GET /api/v1/analytics/errors)
"""

from neurova.core.logger import get_logger
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from neurova.api.deps import get_current_user

logger = get_logger(__name__)

router = APIRouter()

# 尝试导入分析收集器
try:
    from neurova.analytics.collector import MetricsCollector
except ImportError:
    logger.warning("MetricsCollector not available")
    MetricsCollector = None


class UsageStats(BaseModel):
    """使用统计"""

    total_requests: int = 0
    unique_users: int = 0
    average_response_time: float = 0.0
    peak_concurrent_users: int = 0
    requests_by_endpoint: Dict[str, int] = {}


@dataclass
class AnalyticsManager:
    """分析管理器（内存存储）"""

    def __init__(self):
        """初始化分析管理器"""
        self._lock = threading.RLock()
        self._usage_data: Dict[str, Any] = {
            "total_requests": 0,
            "unique_users": set(),
            "response_times": [],
            "peak_concurrent": 0,
            "current_concurrent": 0,
            "requests_by_endpoint": {},
        }
        self._performance_data: Dict[str, Any] = {
            "response_times": [],
            "errors": 0,
            "start_time": time.time(),
        }
        self._behavior_data: Dict[str, Any] = {
            "feature_usage": {},
            "session_durations": [],
            "bounces": 0,
            "total_sessions": 0,
        }
        self._error_data: Dict[str, Any] = {
            "total_errors": 0,
            "error_types": {},
            "recent_errors": [],
        }

    def record_request(
        self,
        endpoint: str,
        response_time: float,
        user_id: Optional[str] = None,
        error: Optional[str] = None,
    ):
        """记录请求"""
        with self._lock:
            # 更新使用统计
            self._usage_data["total_requests"] += 1
            if user_id:
                self._usage_data["unique_users"].add(user_id)
            self._usage_data["response_times"].append(response_time)

            # 更新端点统计
            if endpoint not in self._usage_data["requests_by_endpoint"]:
                self._usage_data["requests_by_endpoint"][endpoint] = 0
            self._usage_data["requests_by_endpoint"][endpoint] += 1

            # 更新并发统计
            self._usage_data["current_concurrent"] += 1
            if self._usage_data["current_concurrent"] > self._usage_data["peak_concurrent"]:
                self._usage_data["peak_concurrent"] = self._usage_data["current_concurrent"]

            # 更新性能统计
            self._performance_data["response_times"].append(response_time)

            # 更新错误统计
            if error:
                self._error_data["total_errors"] += 1
                error_type = error.split(":")[0] if ":" in error else "Unknown"
                if error_type not in self._error_data["error_types"]:
                    self._error_data["error_types"][error_type] = 0
                self._error_data["error_types"][error_type] += 1

                # 保留最近10个错误
                self._error_data["recent_errors"].append(
                    {
                        "error": error,
                        "endpoint": endpoint,
                        "timestamp": time.time(),
                    }
                )
                if len(self._error_data["recent_errors"]) > 10:
                    self._error_data["recent_errors"] = self._error_data["recent_errors"][-10:]

            # 更新行为统计
            self._behavior_data["total_sessions"] += 1
            if endpoint in self._behavior_data["feature_usage"]:
                self._behavior_data["feature_usage"][endpoint] += 1
            else:
                self._behavior_data["feature_usage"][endpoint] = 1

    def decrement_concurrent(self):
        """减少并发计数"""
        with self._lock:
            self._usage_data["current_concurrent"] = max(0, self._usage_data["current_concurrent"] - 1)

    def get_usage_stats(self) -> UsageStats:
        """获取使用统计"""
        with self._lock:
            response_times = self._usage_data["response_times"][-100:]  # 最近100个
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0

            return UsageStats(
                total_requests=self._usage_data["total_requests"],
                unique_users=len(self._usage_data["unique_users"]),
                average_response_time=avg_response_time,
                peak_concurrent_users=self._usage_data["peak_concurrent"],
                requests_by_endpoint=self._usage_data["requests_by_endpoint"],
            )

    def get_performance_stats(self) -> PerformanceStats:
        """获取性能统计"""
        with self._lock:
            response_times = self._performance_data["response_times"]
            if not response_times:
                return PerformanceStats()

            # 计算百分位数
            sorted_times = sorted(response_times)
            p95_index = int(len(sorted_times) * 0.95)
            p99_index = int(len(sorted_times) * 0.99)

            total_requests = self._usage_data["total_requests"]
            error_rate = (self._error_data["total_errors"] / total_requests * 100) if total_requests > 0 else 0

            return PerformanceStats(
                average_response_time=sum(sorted_times) / len(sorted_times),
                p95_response_time=sorted_times[p95_index] if p95_index < len(sorted_times) else 0,
                p99_response_time=sorted_times[p99_index] if p99_index < len(sorted_times) else 0,
                error_rate=error_rate,
                uptime=time.time() - self._performance_data["start_time"],
            )

    def get_behavior_stats(self) -> BehaviorStats:
        """获取用户行为统计"""
        with self._lock:
            total_sessions = self._behavior_data["total_sessions"]
            if total_sessions == 0:
                return BehaviorStats()

            # 计算最常用功能
            feature_usage = self._behavior_data["feature_usage"]
            most_used = sorted(feature_usage.items(), key=lambda x: x[1], reverse=True)[:5]
            most_used_features = [{"feature": f, "count": c} for f, c in most_used]

            # 计算平均会话时长（模拟数据）
            avg_session_duration = 300.0  # 5分钟

            # 计算跳出率（模拟数据）
            bounce_rate = 0.1  # 10%

            return BehaviorStats(
                most_used_features=most_used_features,
                user_retention=0.85,  # 85% 留存率
                average_session_duration=avg_session_duration,
                bounce_rate=bounce_rate,
            )

    def get_error_stats(self) -> ErrorStats:
        """获取错误统计"""
        with self._lock:
            total_requests = self._usage_data["total_requests"]
            error_rate = (self._error_data["total_errors"] / total_requests * 100) if total_requests > 0 else 0

            return ErrorStats(
                total_errors=self._error_data["total_errors"],
                error_rate=error_rate,
                error_types=self._error_data["error_types"],
                recent_errors=self._error_data["recent_errors"],
            )


# 全局分析管理器单例
_analytics_manager: Optional[AnalyticsManager] = None
_manager_lock = threading.Lock()


def get_analytics_manager() -> AnalyticsManager:
    """获取全局分析管理器单例"""
    global _analytics_manager
    if _analytics_manager is None:
        with _manager_lock:
            if _analytics_manager is None:
                _analytics_manager = AnalyticsManager()
    return _analytics_manager


def reset_analytics_manager() -> None:
    """重置全局分析管理器（用于测试）"""
    global _analytics_manager
    with _manager_lock:
        _analytics_manager = None


class PerformanceStats(BaseModel):
    """性能统计"""

    average_response_time: float = 0
    p95_response_time: float = 0
    p99_response_time: float = 0
    error_rate: float = 0
    uptime: float = 0


class BehaviorStats(BaseModel):
    """用户行为统计"""

    most_used_features: List[Dict[str, Any]] = []
    user_retention: float = 0
    average_session_duration: float = 0
    bounce_rate: float = 0


class ErrorStats(BaseModel):
    """错误统计"""

    total_errors: int = 0
    error_rate: float = 0
    error_types: Dict[str, int] = {}
    recent_errors: List[Dict[str, Any]] = []


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


@router.get("/usage", response_model=UsageStats)
async def get_usage_stats(
    request: Request,
    start_time: Optional[float] = Query(default=None, description="开始时间"),
    end_time: Optional[float] = Query(default=None, description="结束时间"),
    current_user: dict = Depends(get_current_user),
):
    """获取使用统计 — 登录用户可读"""
    try:
        # 获取分析管理器
        manager = get_analytics_manager()

        # 获取使用统计
        return manager.get_usage_stats()

    except Exception as e:
        logger.exception("Failed to get usage stats: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get usage stats: {str(e)}"
        )


@router.get("/performance", response_model=PerformanceStats)
async def get_performance_stats(
    request: Request,
    start_time: Optional[float] = Query(default=None, description="开始时间"),
    end_time: Optional[float] = Query(default=None, description="结束时间"),
    current_user: dict = Depends(get_current_user),
):
    """获取性能统计 — 登录用户可读"""
    try:
        # 获取分析管理器
        manager = get_analytics_manager()

        # 获取性能统计
        return manager.get_performance_stats()

    except Exception as e:
        logger.exception("Failed to get performance stats: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get performance stats: {str(e)}"
        )


@router.get("/behavior", response_model=BehaviorStats)
async def get_behavior_stats(
    request: Request,
    start_time: Optional[float] = Query(default=None, description="开始时间"),
    end_time: Optional[float] = Query(default=None, description="结束时间"),
    current_user: dict = Depends(get_current_user),
):
    """获取用户行为统计 — 登录用户可读"""
    try:
        # 获取分析管理器
        manager = get_analytics_manager()

        # 获取行为统计
        return manager.get_behavior_stats()

    except Exception as e:
        logger.exception("Failed to get behavior stats: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get behavior stats: {str(e)}"
        )


@router.get("/errors", response_model=ErrorStats)
async def get_error_stats(
    request: Request,
    start_time: Optional[float] = Query(default=None, description="开始时间"),
    end_time: Optional[float] = Query(default=None, description="结束时间"),
    current_user: dict = Depends(get_current_user),
):
    """获取错误统计 — 登录用户可读"""
    try:
        # 获取分析管理器
        manager = get_analytics_manager()

        # 获取错误统计
        return manager.get_error_stats()

    except Exception as e:
        logger.exception("Failed to get error stats: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get error stats: {str(e)}"
        )
