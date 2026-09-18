"""
统一缓存模块

提供全局缓存实例和便捷接口。
所有缓存功能应使用此模块，避免重复实现。
"""

from neurova.core.logger import get_logger
from typing import Optional

from neurova.memory.core.cache import (
    CacheEntry,
    CacheStats,
    MemoryCache,
    register_cache,
    unregister_cache,
)

logger = get_logger(__name__)

# 全局缓存实例
_global_cache: Optional[MemoryCache] = None


def get_global_cache(
    capacity: int = 10000,
    default_ttl: Optional[float] = None,
) -> MemoryCache:
    """
    获取全局缓存实例
    
    Args:
        capacity: 最大容量
        default_ttl: 默认TTL（秒）
        
    Returns:
        MemoryCache: 全局缓存实例
    """
    global _global_cache
    if _global_cache is None:
        _global_cache = MemoryCache(
            capacity=capacity,
            default_ttl=default_ttl,
        )
        # P1-6：同一注册表登记，命中率才能被 /metrics 导出（不登记 = 该实例
        # 的 hit_rate 永远观测不到，与 memory/core/cache 的全局实例分列两条）
        register_cache("core_global", _global_cache)
        logger.info("全局缓存已初始化: capacity=%d", capacity)
    return _global_cache


def cache_get(key: str, default=None):
    """获取缓存值（便捷函数）"""
    return get_global_cache().get(key, default)


def cache_set(key: str, value, ttl=None):
    """设置缓存值（便捷函数）"""
    return get_global_cache().set(key, value, ttl)


def cache_delete(key: str):
    """删除缓存值（便捷函数）"""
    return get_global_cache().delete(key)


def cache_clear():
    """清空缓存（便捷函数）"""
    return get_global_cache().clear()


# 导出核心类
__all__ = [
    "CacheEntry",
    "CacheStats", 
    "MemoryCache",
    "get_global_cache",
    "cache_get",
    "cache_set",
    "cache_delete",
    "cache_clear",
    "register_cache",
    "unregister_cache",
]
