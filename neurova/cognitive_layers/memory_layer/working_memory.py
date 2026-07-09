"""
工作记忆增强模块

提供工作记忆的增强功能，包括：
- 短期记忆管理
- 注意力机制
- 上下文窗口管理
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Sentinel 用于区分 cache miss (key 不存在) 与 cached None (key 存在但 content=None)
# get() 在 key 不存在时返回 _MISSING，而非 None
_MISSING: Any = object()


@dataclass
class MemoryItem:
    """记忆项"""

    content: Any
    importance: float = 0.5
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0

    def touch(self):
        """更新访问时间"""
        self.last_accessed = time.time()
        self.access_count += 1


class WorkingMemoryAugmenter:
    """工作记忆增强器

    线程安全：所有公共方法均通过 self._lock (RLock) 保护，
    RLock 允许同一线程内重入调用链（如 add -> _evict）。
    """

    def __init__(self, capacity: int = 100, config: Dict[str, Any] = None):
        if config:
            self.capacity = config.get("max_items", capacity)
        else:
            self.capacity = capacity
        self._items: Dict[str, MemoryItem] = {}
        # Bug 1 修复: 共享可变 _items 必须有锁保护，使用 RLock 允许重入调用链
        self._lock = threading.RLock()

    def add(self, key: str, content: Any, importance: float = 0.5) -> bool:
        """添加记忆项"""
        with self._lock:
            if len(self._items) >= self.capacity:
                self._evict()
            self._items[key] = MemoryItem(content=content, importance=importance)
            return True

    def get(self, key: str) -> Any:
        """获取记忆项

        Bug 2 修复: 返回 _MISSING sentinel 区分 cache miss (key 不存在)
        与 cached None (key 存在但 content=None)。
        调用方可用 `result is _MISSING` 判断是否为 miss。
        """
        with self._lock:
            if key in self._items:
                item = self._items[key]
                item.touch()
                return item.content
            return _MISSING

    def remove(self, key: str) -> bool:
        """移除记忆项"""
        with self._lock:
            if key in self._items:
                del self._items[key]
                return True
            return False

    def _evict(self):
        """淘汰最不重要的记忆项"""
        with self._lock:
            if not self._items:
                return
            # 按重要性和最后访问时间排序
            sorted_items = sorted(
                self._items.items(), key=lambda x: (x[1].importance, x[1].last_accessed)
            )
            # 淘汰最不重要的
            if sorted_items:
                del self._items[sorted_items[0][0]]

    def get_recent(self, limit: int = 10) -> List[Any]:
        """获取最近的记忆项"""
        with self._lock:
            sorted_items = sorted(
                self._items.items(), key=lambda x: x[1].last_accessed, reverse=True
            )
            return [item.content for _, item in sorted_items[:limit]]

    def clear(self):
        """清空工作记忆"""
        with self._lock:
            self._items.clear()

    def get_stats(self) -> dict:
        """获取统计信息"""
        with self._lock:
            return {
                "size": len(self._items),
                "capacity": self.capacity,
            }
