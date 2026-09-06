from __future__ import annotations

"""
CogArch 1.0.0 事件总线 — MemoryManager 的骨架替代
=================================================

职责：
  1. MemoryEvent — 模块间通信的唯一载体
  2. MemoryModule — 所有子系统的统一协议
  3. EventBus — 事件路由引擎（同步 + async 双模）

设计原则：
  - 模块不直接引用彼此，只 emit / subscribe 事件
"""

import asyncio
import inspect
from neurova.core.logger import get_logger
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = get_logger(__name__)


# ────── ModuleHealth ──────


@dataclass
class ModuleHealth:
    """模块健康状态"""

    module_name: str
    status: str = "ok"  # ok, degraded, error
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def is_healthy(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_name": self.module_name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
        }


# ────── MemoryEvent ──────


class MemoryEvent:
    """模块间通信的事件载体"""

    # 事件类型常量
    MEMORY_CREATED = "memory_created"
    MEMORY_ACCESSED = "memory_accessed"
    MEMORY_UPDATED = "memory_updated"
    MEMORY_DELETED = "memory_deleted"
    MEMORY_CONSOLIDATED = "memory_consolidated"
    MEMORY_CONFLICT = "memory_conflict"
    TEMPERATURE_UPDATED = "temperature_updated"
    BUFFER_FLUSHED = "buffer_flushed"
    SLEEP_STARTED = "sleep_started"
    SLEEP_COMPLETED = "sleep_completed"
    # P2-10：TOOL_INVOKED / METACOGNITION_EVALUATED 死常量已删除——V3 直写
    # 穿透架构下全仓无 emitter 也无 subscriber，属"事件→账本"叙事的僵尸痕迹。

    def __init__(self, type: str, source: str, payload: Optional[Dict[str, Any]] = None):
        self.type = type
        self.source = source
        self.payload = payload or {}
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "source": self.source,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return f"MemoryEvent(type={self.type!r}, source={self.source!r})"


# ────── MemoryModule ──────


class MemoryModule(ABC):
    """所有记忆子模块的统一协议"""

    @property
    @abstractmethod
    def name(self) -> str:
        """模块唯一名称"""
        ...

    @abstractmethod
    def init(self, bus: "EventBus", config: Dict[str, Any]) -> None:
        """初始化模块，注册事件监听"""
        ...

    @abstractmethod
    def shutdown(self) -> None:
        """优雅关闭"""
        ...

    def health(self) -> ModuleHealth:
        """返回模块健康状态（子类可覆盖）"""
        return ModuleHealth(module_name=self.name, status="ok")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


# ────── EventBus ──────


class EventBus:
    """事件路由引擎（同步 + async 双模）

    Bug 6 修复：所有 _handlers / _emit_count 读写均用 self._lock 保护。
    emit/aemit 在锁内复制 handlers list 后释放锁，再迭代调用 handler —
    避免：(1) off() 在迭代时修改 list 抛 RuntimeError；
          (2) 持锁调用 handler 导致递归 emit 死锁。
    """

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}
        self._emit_count: int = 0
        # Bug 6 修复：用 threading.Lock（非 RLock）保护 _handlers 和 _emit_count
        # emit() 在锁内仅做复制 + 计数，handler 调用在锁外，故 Lock 足够
        self._lock = threading.Lock()

    def on(self, event_type: str, handler: Callable) -> None:
        """订阅事件"""
        # Bug 6 修复：加锁保护 TOCTOU（"if not in" 后被另一线程抢先）
        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)

    def off(self, event_type: str, handler: Callable) -> None:
        """取消订阅"""
        # Bug 6 修复：加锁保护 list.remove
        with self._lock:
            if event_type in self._handlers:
                try:
                    self._handlers[event_type].remove(handler)
                except ValueError:
                    pass

    def emit(self, event: MemoryEvent) -> int:
        """同步发射事件，返回调用的 handler 数量"""
        # Bug 6 修复：锁内仅做计数 + 复制 handlers，锁外调用 handler
        with self._lock:
            self._emit_count += 1
            handlers = list(self._handlers.get(event.type, []))
        called = 0
        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    asyncio.ensure_future(self._run_async_handler(handler, event))
                else:
                    handler(event)
                called += 1
            except Exception as e:
                logger.error("EventBus handler error for %s: %s", event.type, e)
        return called

    async def aemit(self, event: MemoryEvent) -> int:
        """异步发射事件，返回调用的 handler 数量"""
        # Bug 6 修复：同 emit()，锁内复制，锁外 await
        with self._lock:
            self._emit_count += 1
            handlers = list(self._handlers.get(event.type, []))
        called = 0
        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
                called += 1
            except Exception as e:
                logger.error("EventBus async handler error for %s: %s", event.type, e)
        return called

    async def _run_async_handler(self, handler: Callable, event: MemoryEvent) -> None:
        """在异步上下文中运行 async handler"""
        try:
            await handler(event)
        except Exception as e:
            logger.error("EventBus _run_async_handler error: %s", e)

    def registered_events(self) -> List[str]:
        """返回已注册事件类型的列表"""
        with self._lock:
            return list(self._handlers.keys())

    def handler_count(self, event_type: Optional[str] = None) -> int:
        """返回 handler 数量"""
        with self._lock:
            if event_type:
                return len(self._handlers.get(event_type, []))
            return sum(len(h) for h in self._handlers.values())

    @property
    def emit_count(self) -> int:
        # int 读取在 CPython 下原子，但加锁保证内存可见性
        with self._lock:
            return self._emit_count

    def __repr__(self) -> str:
        return f"EventBus(events={len(self._handlers)}, handlers={self.handler_count()})"

    def health_report(self) -> Dict[str, Any]:
        """返回 EventBus 健康报告（P-2 修复: 测试期望 _bus.health_report() 返回 dict）

        注意: _lock 是 threading.Lock (非 RLock), 不能在持锁时调用 handler_count()
        (handler_count 自身也要获取同一把锁, 会死锁)。这里在锁内仅做一次复制 + 计算,
        与 emit()/off() 的"锁内复制, 锁外调用"模式一致。

        Returns:
            {"storage": "healthy", "events": int, "handlers": int, "registered_events": int}
        """
        with self._lock:
            handlers_total = sum(len(h) for h in self._handlers.values())
            return {
                "storage": "healthy",
                "events": self._emit_count,
                "handlers": handlers_total,
                "registered_events": len(self._handlers),
            }
