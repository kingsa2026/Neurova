"""
性能优化模块
为 Agent 系统添加缓存、异步优化等性能提升功能
"""

import asyncio
import functools
import hashlib
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.core.cache import MemoryCache

logger = get_logger(__name__)


def cached(ttl: float = 300.0, max_size: int = 1000, key_func: Callable = None):
    """
    缓存装饰器

    Args:
        ttl: 过期时间（秒）
        max_size: 最大缓存大小
        key_func: 自定义键生成函数

    Returns:
        装饰器函数
    """

    def decorator(func: Callable) -> Callable:
        cache = MemoryCache(max_size=max_size, default_ttl=ttl)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 生成缓存键
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = cache._generate_key(*args, **kwargs)

            # 尝试从缓存获取
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            # 执行函数
            result = await func(*args, **kwargs)

            # 缓存结果
            cache.set(cache_key, result, ttl)

            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # 生成缓存键
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = cache._generate_key(*args, **kwargs)

            # 尝试从缓存获取
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            # 执行函数
            result = func(*args, **kwargs)

            # 缓存结果
            cache.set(cache_key, result, ttl)

            return result

        # 根据函数类型返回包装器
        if asyncio.iscoroutinefunction(func):
            wrapper = async_wrapper
        else:
            wrapper = sync_wrapper

        # 添加缓存管理方法
        wrapper.cache = cache
        wrapper.cache_clear = cache.clear
        wrapper.cache_stats = cache.stats

        return wrapper

    return decorator


class PerformanceMonitor:
    """
    性能监控器

    监控函数执行时间和性能指标。
    """

    def __init__(self):
        """初始化性能监控器"""
        self._lock = threading.RLock()

        # 性能数据
        self._data: Dict[str, Dict[str, Any]] = {}

        # 活跃计时器
        self._active_timers: Dict[str, float] = {}

    def start(self, name: str) -> str:
        """
        开始计时

        Args:
            name: 计时器名称

        Returns:
            计时器ID
        """
        with self._lock:
            timer_id = f"{name}_{int(time.time() * 1000)}"
            self._active_timers[timer_id] = time.time()
            return timer_id

    def stop(self, timer_id: str) -> float:
        """
        停止计时

        Args:
            timer_id: 计时器ID

        Returns:
            执行时间（秒）
        """
        with self._lock:
            if timer_id not in self._active_timers:
                logger.warning("计时器不存在: %s", timer_id)
                return 0.0

            start_time = self._active_timers[timer_id]
            elapsed = time.time() - start_time

            # 提取名称
            name = timer_id.rsplit("_", 1)[0]

            # 更新统计数据
            if name not in self._data:
                self._data[name] = {
                    "count": 0,
                    "total_time": 0.0,
                    "min_time": float("inf"),
                    "max_time": 0.0,
                    "avg_time": 0.0,
                    "last_time": 0.0,
                }

            stats = self._data[name]
            stats["count"] += 1
            stats["total_time"] += elapsed
            stats["min_time"] = min(stats["min_time"], elapsed)
            stats["max_time"] = max(stats["max_time"], elapsed)
            stats["avg_time"] = stats["total_time"] / stats["count"]
            stats["last_time"] = elapsed

            # 删除计时器
            del self._active_timers[timer_id]

            return elapsed

    def get_stats(self, name: str = None) -> Dict[str, Any]:
        """
        获取统计数据

        Args:
            name: 统计名称，None 返回所有

        Returns:
            统计数据
        """
        with self._lock:
            if name:
                return self._data.get(name, {})
            return self._data.copy()

    def print_report(self) -> str:
        """
        打印性能报告

        Returns:
            报告字符串
        """
        with self._lock:
            if not self._data:
                return "没有性能数据"

            report_lines = ["性能监控报告", "=" * 50]

            for name, stats in sorted(self._data.items()):
                report_lines.append(f"\n{name}:")
                report_lines.append(f"  调用次数: {stats['count']}")
                report_lines.append(f"  总时间: {stats['total_time']:.4f}s")
                report_lines.append(f"  平均时间: {stats['avg_time']:.4f}s")
                report_lines.append(f"  最小时间: {stats['min_time']:.4f}s")
                report_lines.append(f"  最大时间: {stats['max_time']:.4f}s")
                report_lines.append(f"  最后时间: {stats['last_time']:.4f}s")

            return "\n".join(report_lines)

    def clear(self) -> None:
        """清空统计数据"""
        with self._lock:
            self._data.clear()
            self._active_timers.clear()
            logger.debug("性能监控数据已清空")


# 全局性能监控器
_performance_monitor: Optional[PerformanceMonitor] = None
_monitor_lock = threading.Lock()


def get_performance_monitor() -> PerformanceMonitor:
    """
    获取全局性能监控器

    Returns:
        PerformanceMonitor 实例
    """
    global _performance_monitor
    if _performance_monitor is None:
        with _monitor_lock:
            if _performance_monitor is None:
                _performance_monitor = PerformanceMonitor()
    return _performance_monitor


def reset_performance_monitor() -> None:
    """
    重置全局性能监控器
    """
    global _performance_monitor
    with _monitor_lock:
        _performance_monitor = None


def timing_decorator(func: Callable) -> Callable:
    """
    计时装饰器

    Args:
        func: 要装饰的函数

    Returns:
        装饰后的函数
    """
    monitor = get_performance_monitor()

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        timer_id = monitor.start(func.__name__)
        try:
            result = await func(*args, **kwargs)
            return result
        finally:
            monitor.stop(timer_id)

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        timer_id = monitor.start(func.__name__)
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            monitor.stop(timer_id)

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper
