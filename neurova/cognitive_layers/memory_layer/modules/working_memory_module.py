"""
WorkingMemoryModule — 工作记忆模块

管理短期工作记忆，支持快速访问和上下文切换
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WorkingMemoryModule:
    """
    工作记忆模块

    管理短期工作记忆，特点：
    - 容量有限（Miller's Law: 7±2）
    - 快速访问
    - 自动衰减
    - 支持上下文切换
    """

    def __init__(
        self,
        capacity: int = 7,
        decay_time: float = 300.0,  # 5分钟
    ):
        """
        Args:
            capacity: 工作记忆容量
            decay_time: 衰减时间（秒）
        """
        self._capacity = capacity
        self._decay_time = decay_time

        self._items: deque = deque(maxlen=capacity)
        self._item_map: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._initialized = False

    @property
    def name(self) -> str:
        """模块名称"""
        return "working_memory_module"

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("WorkingMemoryModule initialized")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._clear_all()
        self._initialized = False
        logger.info("WorkingMemoryModule shutdown")

    def add(
        self,
        item_id: str,
        content: Any,
        priority: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        添加到工作记忆

        Args:
            item_id: 条目ID
            content: 内容
            priority: 优先级 (1-5)
            metadata: 额外元数据

        Returns:
            是否添加成功
        """
        with self._lock:
            # 如果已存在，更新
            if item_id in self._item_map:
                self._item_map[item_id].update(
                    {
                        "content": content,
                        "priority": priority,
                        "metadata": metadata or {},
                        "updated_at": time.time(),
                        "access_count": self._item_map[item_id].get("access_count", 0),
                    }
                )
                return True

            # 检查容量
            if len(self._items) >= self._capacity:
                # 移除最旧的低优先级条目
                self._evict_lowest()

            item_data = {
                "item_id": item_id,
                "content": content,
                "priority": priority,
                "metadata": metadata or {},
                "created_at": time.time(),
                "updated_at": time.time(),
                "access_count": 0,
            }

            self._items.append(item_id)
            self._item_map[item_id] = item_data

            return True

    def get(self, item_id: str) -> Optional[Any]:
        """
        获取工作记忆条目

        Args:
            item_id: 条目ID

        Returns:
            条目内容，不存在返回 None
        """
        with self._lock:
            item = self._item_map.get(item_id)
            if item is None:
                return None

            # 检查是否衰减
            if self._is_decayed(item):
                self._remove_item(item_id)
                return None

            # 更新访问信息
            item["access_count"] = item.get("access_count", 0) + 1
            item["updated_at"] = time.time()

            return item["content"]

    def contains(self, item_id: str) -> bool:
        """检查是否包含条目"""
        with self._lock:
            if item_id not in self._item_map:
                return False
            return not self._is_decayed(self._item_map[item_id])

    def remove(self, item_id: str) -> bool:
        """移除条目"""
        with self._lock:
            return self._remove_item(item_id)

    def get_all(self, include_decayed: bool = False) -> List[Dict[str, Any]]:
        """获取所有条目"""
        with self._lock:
            items = []
            for item_id in list(self._items):
                item = self._item_map.get(item_id)
                if item is None:
                    continue

                if not include_decayed and self._is_decayed(item):
                    continue

                items.append(
                    {
                        "item_id": item_id,
                        "content": item["content"],
                        "priority": item["priority"],
                        "created_at": item["created_at"],
                        "access_count": item.get("access_count", 0),
                    }
                )

            return items

    def clear(self) -> int:
        """清空工作记忆"""
        with self._lock:
            count = len(self._items)
            self._clear_all()
            return count

    def get_recent(self, count: int = 5) -> List[Dict[str, Any]]:
        """获取最近的条目"""
        with self._lock:
            items = self.get_all()
            items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
            return items[:count]

    def get_by_priority(self, min_priority: int = 1) -> List[Dict[str, Any]]:
        """按优先级获取条目"""
        with self._lock:
            items = self.get_all()
            return [item for item in items if item.get("priority", 1) >= min_priority]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            active_items = self.get_all()

            return {
                "capacity": self._capacity,
                "current_size": len(active_items),
                "utilization": len(active_items) / self._capacity if self._capacity > 0 else 0,
                "decay_time": self._decay_time,
                "total_accesses": sum(item.get("access_count", 0) for item in active_items),
            }

    def _is_decayed(self, item: Dict[str, Any]) -> bool:
        """检查条目是否已衰减"""
        last_update = item.get("updated_at", item.get("created_at", 0))
        return (time.time() - last_update) > self._decay_time

    def _remove_item(self, item_id: str) -> bool:
        """移除条目（内部方法）"""
        if item_id in self._item_map:
            del self._item_map[item_id]
            try:
                self._items.remove(item_id)
            except ValueError:
                pass
            return True
        return False

    def _evict_lowest(self) -> None:
        """驱逐最低优先级的条目"""
        if not self._items:
            return

        # 找到优先级最低的条目
        lowest_priority = float("inf")
        lowest_id = None

        for item_id in self._items:
            item = self._item_map.get(item_id)
            if item and item.get("priority", 1) < lowest_priority:
                lowest_priority = item["priority"]
                lowest_id = item_id

        if lowest_id:
            self._remove_item(lowest_id)

    def _clear_all(self) -> None:
        """清空所有（内部方法）"""
        self._items.clear()
        self._item_map.clear()
