"""
工作记忆增强模块

提供工作记忆的增强功能，包括：
- 短期记忆管理
- 注意力机制
- 上下文窗口管理
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    """工作记忆增强器"""

    def __init__(self, capacity: int = 100, config: Dict[str, Any] = None):
        if config:
            self.capacity = config.get("max_items", capacity)
            self.memory_manager = config.get("memory_manager")
        else:
            self.capacity = capacity
            self.memory_manager = None
        self._items: Dict[str, MemoryItem] = {}

    def add(self, key: str, content: Any, importance: float = 0.5) -> bool:
        """添加记忆项"""
        if len(self._items) >= self.capacity:
            self._evict()
        self._items[key] = MemoryItem(content=content, importance=importance)
        return True

    def get(self, key: str) -> Optional[Any]:
        """获取记忆项"""
        if key in self._items:
            item = self._items[key]
            item.touch()
            return item.content
        return None

    def remove(self, key: str) -> bool:
        """移除记忆项"""
        if key in self._items:
            del self._items[key]
            return True
        return False

    def _evict(self):
        """淘汰最不重要的记忆项"""
        if not self._items:
            return
        # 按重要性和最后访问时间排序
        sorted_items = sorted(self._items.items(), key=lambda x: (x[1].importance, x[1].last_accessed))
        # 淘汰最不重要的
        if sorted_items:
            del self._items[sorted_items[0][0]]

    def get_recent(self, limit: int = 10) -> List[Any]:
        """获取最近的记忆项"""
        sorted_items = sorted(self._items.items(), key=lambda x: x[1].last_accessed, reverse=True)
        return [item.content for _, item in sorted_items[:limit]]

    def clear(self):
        """清空工作记忆"""
        self._items.clear()

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "size": len(self._items),
            "capacity": self.capacity,
        }
