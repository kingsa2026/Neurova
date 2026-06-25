"""
内存缓存管理器

提供基于 LRU 策略的内存缓存，支持 TTL 过期、线程安全、容量限制。
"""

from neurova.core.logger import get_logger
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = get_logger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""

    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    ttl: Optional[float] = None  # 秒，None 表示不过期

    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.ttl is None:
            return False
        return time.time() - self.created_at > self.ttl

    def touch(self):
        """更新访问信息"""
        self.last_accessed = time.time()
        self.access_count += 1


@dataclass
class CacheStats:
    """缓存统计信息"""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0
    capacity: int = 0

    @property
    def hit_rate(self) -> float:
        """命中率"""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "size": self.size,
            "capacity": self.capacity,
            "hit_rate": round(self.hit_rate, 4),
        }


class MemoryCache:
    """
    内存缓存管理器

    特性:
    - LRU 淘汰策略
    - TTL 过期支持
    - 线程安全
    - 容量限制
    - 访问统计

    使用示例:
        cache = MemoryCache(capacity=1000, default_ttl=300)
        cache.set("key1", "value1", ttl=60)
        value = cache.get("key1")
    """

    def __init__(
        self,
        capacity: int = 10000,
        default_ttl: Optional[float] = None,
        cleanup_interval: float = 60.0,
    ):
        """
        初始化缓存

        Args:
            capacity: 最大容量
            default_ttl: 默认 TTL（秒），None 表示不过期
            cleanup_interval: 清理间隔（秒）
        """
        self._capacity = max(1, capacity)
        self._default_ttl = default_ttl
        self._cleanup_interval = cleanup_interval

        # 使用 OrderedDict 实现 LRU
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()

        # 统计信息
        self._stats = CacheStats(capacity=self._capacity)

        # 线程安全
        self._lock = threading.RLock()

        # 清理定时器
        self._cleanup_timer: Optional[threading.Timer] = None
        self._start_cleanup_timer()

        logger.info("MemoryCache initialized: capacity=%s, default_ttl=%ss", capacity, default_ttl)

    def _start_cleanup_timer(self):
        """启动清理定时器"""
        if self._cleanup_interval > 0:
            self._cleanup_timer = threading.Timer(
                self._cleanup_interval,
                self._cleanup_expired,
            )
            self._cleanup_timer.daemon = True
            self._cleanup_timer.start()

    def _cleanup_expired(self):
        """清理过期条目"""
        with self._lock:
            expired_keys = [key for key, entry in self._cache.items() if entry.is_expired()]
            for key in expired_keys:
                del self._cache[key]
                self._stats.evictions += 1

            if expired_keys:
                logger.debug("Cleaned up %s expired cache entries", len(expired_keys))

            # 重新启动定时器
            self._start_cleanup_timer()

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取缓存值

        Args:
            key: 缓存键
            default: 默认值

        Returns:
            缓存值或默认值
        """
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._stats.misses += 1
                return default

            if entry.is_expired():
                del self._cache[key]
                self._stats.misses += 1
                self._stats.evictions += 1
                return default

            # 移到末尾（最近使用）
            self._cache.move_to_end(key)
            entry.touch()

            self._stats.hits += 1
            return entry.value

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
    ) -> bool:
        """
        设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None 使用默认 TTL

        Returns:
            是否设置成功
        """
        with self._lock:
            # 如果键已存在，更新它
            if key in self._cache:
                self._cache.move_to_end(key)
                entry = self._cache[key]
                entry.value = value
                entry.last_accessed = time.time()
                if ttl is not None:
                    entry.ttl = ttl
                elif self._default_ttl is not None:
                    entry.ttl = self._default_ttl
                return True

            # 检查容量，必要时淘汰
            while len(self._cache) >= self._capacity:
                # 淘汰最久未使用的（头部）
                evicted_key, _ = self._cache.popitem(last=False)
                self._stats.evictions += 1
                logger.debug("Evicted cache entry: %s", evicted_key)

            # 创建新条目
            entry_ttl = ttl if ttl is not None else self._default_ttl
            entry = CacheEntry(
                key=key,
                value=value,
                ttl=entry_ttl,
            )
            self._cache[key] = entry
            self._stats.size = len(self._cache)

            return True

    def delete(self, key: str) -> bool:
        """
        删除缓存值

        Args:
            key: 缓存键

        Returns:
            是否删除成功
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._stats.size = len(self._cache)
                return True
            return False

    def has(self, key: str) -> bool:
        """
        检查键是否存在

        Args:
            key: 缓存键

        Returns:
            是否存在
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            if entry.is_expired():
                del self._cache[key]
                self._stats.evictions += 1
                return False
            return True

    def clear(self) -> int:
        """
        清空缓存

        Returns:
            清除的条目数
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._stats.size = 0
            return count

    def keys(self) -> List[str]:
        """获取所有键"""
        with self._lock:
            return list(self._cache.keys())

    def values(self) -> List[Any]:
        """获取所有值"""
        with self._lock:
            return [entry.value for entry in self._cache.values() if not entry.is_expired()]

    def items(self) -> List[Tuple[str, Any]]:
        """获取所有键值对"""
        with self._lock:
            return [(key, entry.value) for key, entry in self._cache.items() if not entry.is_expired()]

    def get_or_set(
        self,
        key: str,
        factory,
        ttl: Optional[float] = None,
    ) -> Any:
        """
        获取缓存值，如果不存在则使用工厂函数创建

        Args:
            key: 缓存键
            factory: 工厂函数（无参数）
            ttl: 过期时间

        Returns:
            缓存值
        """
        value = self.get(key)
        if value is None:
            value = factory()
            self.set(key, value, ttl=ttl)
        return value

    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """
        批量获取

        Args:
            keys: 键列表

        Returns:
            键值对字典
        """
        result = {}
        for key in keys:
            value = self.get(key)
            if value is not None:
                result[key] = value
        return result

    def set_many(
        self,
        items: Dict[str, Any],
        ttl: Optional[float] = None,
    ) -> int:
        """
        批量设置

        Args:
            items: 键值对字典
            ttl: 过期时间

        Returns:
            设置成功的数量
        """
        count = 0
        for key, value in items.items():
            if self.set(key, value, ttl=ttl):
                count += 1
        return count

    def delete_many(self, keys: List[str]) -> int:
        """
        批量删除

        Args:
            keys: 键列表

        Returns:
            删除成功的数量
        """
        count = 0
        for key in keys:
            if self.delete(key):
                count += 1
        return count

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            self._stats.size = len(self._cache)
            return self._stats.to_dict()

    def get_entry_info(self, key: str) -> Optional[Dict[str, Any]]:
        """
        获取条目信息

        Args:
            key: 缓存键

        Returns:
            条目信息字典或 None
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            return {
                "key": entry.key,
                "created_at": entry.created_at,
                "last_accessed": entry.last_accessed,
                "access_count": entry.access_count,
                "ttl": entry.ttl,
                "is_expired": entry.is_expired(),
                "age": time.time() - entry.created_at,
            }

    def resize(self, new_capacity: int) -> int:
        """
        调整容量

        Args:
            new_capacity: 新容量

        Returns:
            淘汰的条目数
        """
        with self._lock:
            self._capacity = max(1, new_capacity)
            self._stats.capacity = self._capacity

            evicted = 0
            while len(self._cache) > self._capacity:
                self._cache.popitem(last=False)
                evicted += 1
                self._stats.evictions += 1

            return evicted

    def shutdown(self):
        """关闭缓存"""
        if self._cleanup_timer:
            self._cleanup_timer.cancel()
            self._cleanup_timer = None
        logger.info("MemoryCache shutdown")

    def __len__(self) -> int:
        """获取缓存大小"""
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        """检查键是否存在"""
        return self.has(key)

    def __repr__(self) -> str:
        """字符串表示"""
        return f"MemoryCache(capacity={self._capacity}, size={len(self._cache)}, hit_rate={self._stats.hit_rate * 100:.2f}%%)"


# ============================================================
# 全局缓存实例
# ============================================================

_global_cache: Optional[MemoryCache] = None
_cache_lock = threading.Lock()


def get_global_cache(
    capacity: int = 10000,
    default_ttl: Optional[float] = None,
) -> MemoryCache:
    """
    获取全局缓存实例

    Args:
        capacity: 缓存容量
        default_ttl: 默认 TTL

    Returns:
        全局缓存实例
    """
    global _global_cache
    with _cache_lock:
        if _global_cache is None:
            _global_cache = MemoryCache(
                capacity=capacity,
                default_ttl=default_ttl,
            )
        return _global_cache


def reset_global_cache():
    """重置全局缓存（用于测试）"""
    global _global_cache
    with _cache_lock:
        if _global_cache:
            _global_cache.shutdown()
        _global_cache = None


# ============================================================
# 缓存装饰器
# ============================================================


def cached(
    ttl: Optional[float] = None,
    key_prefix: str = "",
):
    """
    缓存装饰器

    Args:
        ttl: 过期时间
        key_prefix: 键前缀

    使用示例:
        @cached(ttl=60, key_prefix="user")
        def get_user(user_id: str):
            return fetch_user_from_db(user_id)
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            cache = get_global_cache()

            # 构建缓存键
            key_parts = [key_prefix, func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(filter(None, key_parts))

            # 尝试从缓存获取
            result = cache.get(cache_key)
            if result is not None:
                return result

            # 执行函数
            result = func(*args, **kwargs)

            # 存入缓存
            if result is not None:
                cache.set(cache_key, result, ttl=ttl)

            return result

        wrapper.cache_clear = lambda: get_global_cache().clear()
        return wrapper

    return decorator
