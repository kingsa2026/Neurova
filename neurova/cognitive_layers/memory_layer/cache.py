"""
记忆缓存模块

提供记忆数据的缓存功能，包括：
- LRU 缓存
- TTL 缓存
- 分层缓存
"""

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    ttl: Optional[float] = None  # None 表示不过期
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.ttl is None:
            return False
        return time.time() - self.created_at > self.ttl
    
    def touch(self):
        """更新访问时间"""
        self.last_accessed = time.time()
        self.access_count += 1


class MemoryCache:
    """记忆缓存"""
    
    def __init__(self, max_size: int = 1000, default_ttl: Optional[float] = None):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if key not in self._cache:
            self._misses += 1
            return None
        
        entry = self._cache[key]
        if entry.is_expired():
            del self._cache[key]
            self._misses += 1
            return None
        
        entry.touch()
        self._cache.move_to_end(key)
        self._hits += 1
        return entry.value
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None):
        """设置缓存值"""
        if key in self._cache:
            del self._cache[key]
        elif len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)
        
        self._cache[key] = CacheEntry(
            key=key,
            value=value,
            ttl=ttl or self.default_ttl
        )
    
    def delete(self, key: str) -> bool:
        """删除缓存值"""
        if key in self._cache:
            del self._cache[key]
            return True
        return False
    
    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
    
    def get_stats(self) -> dict:
        """获取缓存统计"""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0
        }
