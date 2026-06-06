"""
实时记忆流引擎

记录记忆系统的所有操作，支持实时查看和导出
"""

from __future__ import annotations

import collections
import datetime
import json
import logging
import threading
import typing
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryEventType(str, Enum):
    """记忆事件类型"""
    STORE = "store"
    RETRIEVE = "retrieve"
    UPDATE = "update"
    DELETE = "delete"
    FORGET = "forget"
    CONSOLIDATE = "consolidate"
    REPLAY = "replay"
    SEARCH = "search"
    FLUSH = "flush"
    ERROR = "error"


@dataclass
class MemoryEvent:
    """记忆事件数据结构"""
    event_type: MemoryEventType
    memory_id: str
    agent_id: str
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    content_preview: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    duration_ms: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "event_type": self.event_type.value,
            "memory_id": self.memory_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp.isoformat(),
            "content_preview": self.content_preview[:200],
            "success": self.success,
        }
        if self.metadata:
            result["metadata"] = self.metadata
        if self.duration_ms is not None:
            result["duration_ms"] = round(self.duration_ms, 2)
        if self.error_message:
            result["error_message"] = self.error_message
        return result

    def __repr__(self) -> str:
        return f"MemoryEvent({self.event_type.value}, id={self.memory_id[:8]}, agent={self.agent_id})"


class MemoryStream:
    """
    实时记忆流引擎
    
    记录记忆系统的所有操作，支持：
    - 事件记录与订阅
    - 时间窗口查询
    - 按类型/agent过滤
    - JSON导出
    """
    
    def __init__(self, max_size: int = 10000):
        self._events: Deque[MemoryEvent] = deque(maxlen=max_size)
        self._lock = threading.RLock()
        self._subscribers: List[Callable[[MemoryEvent], None]] = []
        self._max_size = max_size
        self._event_counts: Dict[str, int] = collections.Counter()
        self._agent_counts: Dict[str, int] = collections.Counter()
    
    @property
    def size(self) -> int:
        """当前事件数量"""
        return len(self._events)
    
    @property
    def max_size(self) -> int:
        """最大事件容量"""
        return self._max_size
    
    def record_event(self, event: MemoryEvent) -> None:
        """记录一个事件"""
        with self._lock:
            self._events.append(event)
            self._event_counts[event.event_type.value] += 1
            self._agent_counts[event.agent_id] += 1
            
            # 通知订阅者
            for subscriber in self._subscribers:
                try:
                    subscriber(event)
                except Exception as e:
                    logger.warning(f"Subscriber callback failed: {e}")
    
    def record(
        self,
        event_type: MemoryEventType,
        memory_id: str,
        agent_id: str,
        content_preview: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        """便捷记录方法"""
        event = MemoryEvent(
            event_type=event_type,
            memory_id=memory_id,
            agent_id=agent_id,
            content_preview=content_preview,
            metadata=metadata or {},
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
        )
        self.record_event(event)
    
    def get_stream(
        self,
        limit: int = 100,
        event_type: Optional[MemoryEventType] = None,
        agent_id: Optional[str] = None,
        since: Optional[datetime.datetime] = None,
    ) -> List[MemoryEvent]:
        """获取事件流"""
        with self._lock:
            events = list(self._events)
        
        # 过滤
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if agent_id:
            events = [e for e in events if e.agent_id == agent_id]
        if since:
            events = [e for e in events if e.timestamp >= since]
        
        # 最新的在前
        events.reverse()
        return events[:limit]
    
    def get_recent(
        self,
        count: int = 20,
        event_type: Optional[MemoryEventType] = None,
    ) -> List[MemoryEvent]:
        """获取最近的事件"""
        return self.get_stream(limit=count, event_type=event_type)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "total_events": len(self._events),
                "max_size": self._max_size,
                "event_type_counts": dict(self._event_counts),
                "agent_counts": dict(self._agent_counts),
                "oldest_event": self._events[0].timestamp.isoformat() if self._events else None,
                "newest_event": self._events[-1].timestamp.isoformat() if self._events else None,
            }
    
    def subscribe(self, callback: Callable[[MemoryEvent], None]) -> None:
        """订阅事件流"""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)
    
    def unsubscribe(self, callback: Callable[[MemoryEvent], None]) -> None:
        """取消订阅"""
        with self._lock:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass
    
    def clear(self) -> int:
        """清空事件流，返回清除的事件数"""
        with self._lock:
            count = len(self._events)
            self._events.clear()
            self._event_counts.clear()
            self._agent_counts.clear()
            return count
    
    def export_json(self, limit: Optional[int] = None) -> str:
        """导出为JSON"""
        events = self.get_stream(limit=limit or self._max_size)
        return json.dumps(
            [e.to_dict() for e in events],
            ensure_ascii=False,
            indent=2,
        )


# 全局单例
_memory_stream: Optional[MemoryStream] = None
_stream_lock = threading.Lock()


def get_memory_stream(max_size: int = 10000) -> MemoryStream:
    """获取全局记忆流单例"""
    global _memory_stream
    if _memory_stream is None:
        with _stream_lock:
            if _memory_stream is None:
                _memory_stream = MemoryStream(max_size=max_size)
    return _memory_stream


def reset_memory_stream() -> None:
    """重置全局记忆流（用于测试）"""
    global _memory_stream
    with _stream_lock:
        _memory_stream = None
