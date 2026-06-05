"""
性能优化模块
为 Agent 系统添加缓存、异步优化等性能提升功能
"""

import asyncio
import functools
import hashlib
import threading
import time
import typing
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class MemoryCache:
    """
    内存缓存
    
    提供基于内存的缓存功能，支持过期时间和大小限制。
    """
    
    def __init__(self, max_size: int = 1000, default_ttl: float = 300.0):
        """
        初始化内存缓存
        
        Args:
            max_size: 最大缓存条目数
            default_ttl: 默认过期时间（秒）
        """
        self._lock = threading.RLock()
        self._max_size = max_size
        self._default_ttl = default_ttl
        
        # 缓存存储
        self._cache: Dict[str, Tuple[Any, float, float]] = {}  # key -> (value, expire_time, create_time)
        
        # 统计信息
        self._hits = 0
        self._misses = 0
        
        logger.debug(f"MemoryCache 初始化，最大大小: {max_size}，默认TTL: {default_ttl}s")
    
    def _generate_key(self, *args, **kwargs) -> str:
        """
        生成缓存键
        
        Args:
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            缓存键字符串
        """
        # 将参数转换为字符串
        key_parts = []
        
        for arg in args:
            key_parts.append(str(arg))
        
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}={v}")
        
        key_str = ":".join(key_parts)
        
        # 生成哈希
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，不存在或过期返回 None
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            value, expire_time, create_time = self._cache[key]
            
            # 检查是否过期
            if time.time() > expire_time:
                del self._cache[key]
                self._misses += 1
                return None
            
            self._hits += 1
            return value
    
    def set(self, key: str, value: Any, ttl: float = None) -> None:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None 使用默认值
        """
        with self._lock:
            # 检查缓存大小
            if len(self._cache) >= self._max_size:
                self._evict()
            
            # 计算过期时间
            ttl = ttl if ttl is not None else self._default_ttl
            expire_time = time.time() + ttl
            create_time = time.time()
            
            self._cache[key] = (value, expire_time, create_time)
    
    def delete(self, key: str) -> bool:
        """
        删除缓存
        
        Args:
            key: 缓存键
            
        Returns:
            是否删除成功
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            logger.debug("缓存已清空")
    
    def stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
            
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "total_requests": total_requests
            }
    
    def _calculate_hit_rate(self) -> float:
        """
        计算命中率
        
        Returns:
            命中率 0.0-1.0
        """
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0
    
    def _evict(self) -> None:
        """驱逐过期或最少使用的缓存"""
        current_time = time.time()
        
        # 首先删除过期的
        expired_keys = []
        for key, (value, expire_time, create_time) in self._cache.items():
            if current_time > expire_time:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._cache[key]
        
        # 如果还是超过大小，删除最旧的
        if len(self._cache) >= self._max_size:
            # 按创建时间排序
            sorted_items = sorted(
                self._cache.items(),
                key=lambda x: x[1][2]  # create_time
            )
            
            # 删除最旧的 10%
            delete_count = max(1, len(sorted_items) // 10)
            for i in range(delete_count):
                if i < len(sorted_items):
                    del self._cache[sorted_items[i][0]]


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
                logger.warning(f"计时器不存在: {timer_id}")
                return 0.0
            
            start_time = self._active_timers[timer_id]
            elapsed = time.time() - start_time
            
            # 提取名称
            name = timer_id.rsplit('_', 1)[0]
            
            # 更新统计数据
            if name not in self._data:
                self._data[name] = {
                    "count": 0,
                    "total_time": 0.0,
                    "min_time": float('inf'),
                    "max_time": 0.0,
                    "avg_time": 0.0,
                    "last_time": 0.0
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