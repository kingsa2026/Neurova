"""
系统健康检查器（核心模块）

提供 HealthChecker 用于注册、运行健康检查并生成整体健康报告。
API 层 (neurova.api.endpoints / neurova.api.deps) 通过 get_health_checker()
获取全局单例。

设计说明：
- HealthStatus / CheckType / RecoveryAction 为公开枚举。
- HealthCheck 描述单个检查（名称、类型、检查函数、超时、关键性、间隔）。
- HealthCheckResult 为单次检查结果。
- HealthChecker 负责注册、执行、聚合状态与生成报告。
- get_health_checker() 返回进程级单例。
"""

from __future__ import annotations

import asyncio
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple
from neurova.core.lazy_singleton import lazySingleton
from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 检查函数签名：无参数，返回 (成功: bool, 消息: str)
CheckFunc = Callable[[], Tuple[bool, str]]


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class CheckType(str, Enum):
    LIVENESS = "liveness"
    READINESS = "readiness"
    DEPENDENCY = "dependency"
    CUSTOM = "custom"


class RecoveryAction(str, Enum):
    RESTART = "restart"
    RECONNECT = "reconnect"
    FALLBACK = "fallback"
    ALERT = "alert"
    NONE = "none"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

class HealthCheck:
    """单个健康检查定义"""

    def __init__(
        self,
        name: str,
        check_func: CheckFunc,
        check_type: CheckType = CheckType.CUSTOM,
        timeout: float = 5.0,
        critical: bool = False,
        interval: float = 60.0,
        description: str = "",
    ) -> None:
        self.name = name
        self.check_func = check_func
        self.check_type = check_type
        self.timeout = timeout
        self.critical = critical
        self.interval = interval
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "check_type": self.check_type.value,
            "timeout": self.timeout,
            "critical": self.critical,
            "interval": self.interval,
            "description": self.description,
        }


class HealthCheckResult:
    """单个健康检查结果"""

    def __init__(
        self,
        name: str,
        status: HealthStatus,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
        duration: float = 0.0,
        check_type: CheckType = CheckType.CUSTOM,
    ) -> None:
        self.name = name
        self.status = status
        self.message = message
        self.details = details or {}
        self.duration = duration
        self.check_type = check_type

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "duration": self.duration,
            "check_type": self.check_type.value,
        }


# ---------------------------------------------------------------------------
# 健康检查器
# ---------------------------------------------------------------------------

class HealthChecker:
    """健康检查器：注册/运行健康检查并生成整体健康报告"""

    def __init__(self) -> None:
        self._checks: Dict[str, HealthCheck] = {}
        self._results: Dict[str, HealthCheckResult] = {}
        # 每项最近一次**写入结果的时刻**（墙钟）；周期调度据此判 interval 是否到期。
        self._lastRunAt: Dict[str, float] = {}
        # 调度在事件循环里、检查函数经 to_thread 在工作线程里写结果——读写两侧要互斥，
        # get_report 还要在迭代前取快照（字典边迭代边被写会抛 RuntimeError）。
        self._resultsLock = threading.RLock()
        self._schedulerTask: Optional[asyncio.Task] = None

    # -- 注册 ----------------------------------------------------------------

    def register_check(self, health_check: HealthCheck) -> None:
        """注册一个健康检查定义"""
        self._checks[health_check.name] = health_check

    def register(
        self,
        name: str,
        check_func: CheckFunc,
        check_type: CheckType = CheckType.CUSTOM,
        timeout: float = 5.0,
        critical: bool = False,
        interval: float = 60.0,
        description: str = "",
    ) -> None:
        """快捷注册：根据函数直接创建并注册一个健康检查"""
        self.register_check(
            HealthCheck(
                name=name,
                check_func=check_func,
                check_type=check_type,
                timeout=timeout,
                critical=critical,
                interval=interval,
                description=description,
            )
        )

    # -- 运行 ----------------------------------------------------------------

    def run_check(self, name: str) -> Optional[HealthCheckResult]:
        """执行指定名称的健康检查，返回结果（不存在返回 None）"""
        health_check = self._checks.get(name)
        if health_check is None:
            return None

        start = time.monotonic()
        try:
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
                future = _pool.submit(health_check.check_func)
                success, message = future.result(timeout=health_check.timeout)
            status = HealthStatus.HEALTHY if success else HealthStatus.UNHEALTHY
        except _cf.TimeoutError:
            status = HealthStatus.UNHEALTHY
            message = f"Health check '{name}' timed out after {health_check.timeout}s"
        except Exception as exc:  # 检查函数抛异常视为不健康
            status = HealthStatus.UNHEALTHY
            message = str(exc)
        duration = (time.monotonic() - start) * 1000.0

        result = HealthCheckResult(
            name=name,
            status=status,
            message=message,
            duration=duration,
            check_type=health_check.check_type,
        )
        with self._resultsLock:
            self._results[name] = result
            self._lastRunAt[name] = time.time()
        return result

    def run_all_checks(self) -> Dict[str, HealthCheckResult]:
        """执行所有已注册的健康检查"""
        return {name: self.run_check(name) for name in list(self._checks)}

    # -- 周期调度 ------------------------------------------------------------

    def startScheduler(self) -> None:
        """启动按 `interval` 刷新的后台任务（幂等；必须在运行中的事件循环里调用）。"""
        if self._schedulerTask is not None and not self._schedulerTask.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("健康检查周期调度未启动：当前没有运行中的事件循环")
            return
        self._schedulerTask = loop.create_task(
            self._schedulerLoop(), name="health-check-scheduler"
        )
        logger.info("健康检查周期调度已启动（%d 项）", len(self._checks))

    def stopScheduler(self) -> None:
        """停止周期任务（幂等）。"""
        task = self._schedulerTask
        self._schedulerTask = None
        if task is not None and not task.done():
            task.cancel()

    def _tickSeconds(self) -> float:
        """调度最小步长：取各检查 interval 的最小值，夹在 [0.05, 5] 秒。"""
        intervals = [max(float(check.interval), 0.05) for check in list(self._checks.values())]
        return min(min(intervals), 5.0) if intervals else 5.0

    async def _schedulerLoop(self) -> None:
        """按每个检查自己的 `interval` 到期即刷新缓存。

        检查函数是同步 I/O，经 `to_thread` 执行——直接 await 会占住事件循环
        （本仓 §6-93/§6-99 同族故障：一次慢查询拖住整个服务）。
        """
        try:
            while True:
                now = time.time()
                for check in list(self._checks.values()):
                    dueAt = self._lastRunAt.get(check.name, 0.0) + max(
                        float(check.interval), 0.05
                    )
                    if now < dueAt:
                        continue
                    try:
                        await asyncio.to_thread(self.run_check, check.name)
                    except Exception:  # noqa: BLE001 - 单项失败不影响其余检查
                        logger.warning("健康检查 %s 周期执行异常", check.name, exc_info=True)
                await asyncio.sleep(self._tickSeconds())
        except asyncio.CancelledError:
            raise

    # -- 查询 ----------------------------------------------------------------

    def get_check_result(self, name: str) -> Optional[HealthCheckResult]:
        """获取某检查的最近一次结果"""
        with self._resultsLock:
            return self._results.get(name)

    def get_all_results(self) -> Dict[str, HealthCheckResult]:
        """获取所有检查结果的快照（迭代期间不被调度写入干扰）。"""
        with self._resultsLock:
            return dict(self._results)

    def clear_results(self) -> None:
        """清空所有缓存的检查结果"""
        with self._resultsLock:
            self._results.clear()
            self._lastRunAt.clear()

    def get_overall_status(self) -> HealthStatus:
        """根据最近结果聚合整体健康状态"""
        if not self._results:
            return HealthStatus.UNKNOWN
        if any(r.status == HealthStatus.UNHEALTHY for r in self._results.values()):
            return HealthStatus.UNHEALTHY
        if any(r.status == HealthStatus.DEGRADED for r in self._results.values()):
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    def get_report(self) -> Dict[str, Any]:
        """生成健康报告（与 API 层 HealthReportResponse 字段对齐）"""
        results = self.get_all_results()
        status = self.get_overall_status()
        checks: Dict[str, Any] = {
            name: result.to_dict() for name, result in results.items()
        }
        healthy_count = sum(
            1 for r in results.values() if r.status == HealthStatus.HEALTHY
        )
        unhealthy_count = sum(
            1 for r in results.values() if r.status == HealthStatus.UNHEALTHY
        )
        return {
            "status": status.value,
            "checks": checks,
            "total_checks": len(results),
            "healthy_count": healthy_count,
            "unhealthy_count": unhealthy_count,
            "timestamp": time.time(),
        }


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_health_checker_instance: Optional[HealthChecker] = None


@lazySingleton("_health_checker_instance")
def get_health_checker() -> HealthChecker:
    """获取全局健康检查器单例"""
    return HealthChecker()
