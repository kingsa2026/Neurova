from __future__ import annotations

"""
统一事件总线模块 - 发布-订阅模式的事件系统

功能:
- 事件注册/取消订阅
- 同步/异步事件分发
- 事件优先级
- 事件日志追踪
"""

import asyncio
import collections
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class EventPriority(IntEnum):
    """事件优先级"""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Event:
    """事件数据结构"""

    name: str
    data: Any = None
    source: str = ""
    timestamp: float = field(default_factory=time.time)
    priority: EventPriority = EventPriority.NORMAL


@dataclass
class Subscription:
    """订阅信息"""

    event_name: str
    handler: Callable
    priority: EventPriority = EventPriority.NORMAL
    is_async: bool = False
    module_name: str = ""
    once: bool = False


class EventBus:
    """
    统一事件总线

    支持同步和异步事件处理，事件优先级，以及事件日志追踪。
    """

    def __init__(self, max_log_size: int = 1000):
        self._subscribers: Dict[str, List[Subscription]] = defaultdict(list)
        self._event_log: collections.deque = collections.deque(maxlen=max_log_size)
        self._running = False
        self._async_queue: Optional[asyncio.Queue] = None
        self._async_task: Optional[asyncio.Task] = None
        self._lock = threading.RLock()
        self._registered_events: Set[str] = set()
        logger.info("EventBus initialized")

    def start(self) -> None:
        """启动事件总线"""
        if self._running:
            return
        self._running = True
        # 异步队列在事件循环中创建
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                self._async_queue = asyncio.Queue()
                self._async_task = asyncio.ensure_future(self._process_async_queue())
        except RuntimeError:
            pass  # 没有事件循环，异步功能不可用
        logger.info("EventBus started")

    def stop(self) -> None:
        """停止事件总线"""
        self._running = False
        if self._async_task and not self._async_task.done():
            self._async_task.cancel()
        logger.info("EventBus stopped")

    def subscribe(
        self,
        event_name: str,
        handler: Callable,
        priority: EventPriority = EventPriority.NORMAL,
        module_name: str = "",
        once: bool = False,
    ) -> Subscription:
        """
        订阅事件

        Args:
            event_name: 事件名称
            handler: 事件处理函数
            priority: 事件优先级
            module_name: 订阅者所属模块名
            once: 是否只触发一次

        Returns:
            Subscription 对象
        """
        is_async = asyncio.iscoroutinefunction(handler)
        sub = Subscription(
            event_name=event_name,
            handler=handler,
            priority=priority,
            is_async=is_async,
            module_name=module_name,
            once=once,
        )
        with self._lock:
            self._subscribers[event_name].append(sub)
            # 按优先级排序（高优先级先执行）
            self._subscribers[event_name].sort(key=lambda s: s.priority, reverse=True)
            self._registered_events.add(event_name)
        logger.debug("Subscribed to '%s' (priority=%s, async=%s, module=%s)", event_name, priority, is_async, module_name)
        return sub

    def unsubscribe(self, event_name: str, handler: Callable) -> bool:
        """取消订阅"""
        with self._lock:
            if event_name not in self._subscribers:
                return False
            before = len(self._subscribers[event_name])
            self._subscribers[event_name] = [s for s in self._subscribers[event_name] if s.handler != handler]
            return len(self._subscribers[event_name]) < before

    def unsubscribe_module(self, module_name: str) -> int:
        """取消指定模块的所有订阅"""
        count = 0
        with self._lock:
            for event_name in list(self._subscribers.keys()):
                before = len(self._subscribers[event_name])
                self._subscribers[event_name] = [
                    s for s in self._subscribers[event_name] if s.module_name != module_name
                ]
                count += before - len(self._subscribers[event_name])
                if not self._subscribers[event_name]:
                    del self._subscribers[event_name]
        return count

    def publish(self, event_name: str, data: Any = None, source: str = "") -> List[Any]:
        """
        同步发布事件

        Args:
            event_name: 事件名称
            data: 事件数据
            source: 事件来源

        Returns:
            所有同步 handler 的返回值列表
        """
        event = Event(name=event_name, data=data, source=source)
        self._log_event(event)

        results = []
        with self._lock:
            subs = list(self._subscribers.get(event_name, []))

        to_remove = []
        for sub in subs:
            if sub.is_async:
                # 异步处理器放入队列
                if self._async_queue:
                    self._async_queue.put_nowait((sub, event))
                continue
            try:
                result = sub.handler(event)
                results.append(result)
                if sub.once:
                    to_remove.append(sub)
            except Exception as e:
                logger.error(f"Error in event handler for '{event_name}': {e}", exc_info=True)

        # 移除一次性订阅
        if to_remove:
            with self._lock:
                for sub in to_remove:
                    if sub in self._subscribers.get(event_name, []):
                        self._subscribers[event_name].remove(sub)

        return results

    async def publish_async(self, event_name: str, data: Any = None, source: str = "") -> List[Any]:
        """
        异步发布事件

        Args:
            event_name: 事件名称
            data: 事件数据
            source: 事件来源

        Returns:
            所有 handler 的返回值列表
        """
        event = Event(name=event_name, data=data, source=source)
        self._log_event(event)

        results = []
        with self._lock:
            subs = list(self._subscribers.get(event_name, []))

        to_remove = []
        for sub in subs:
            try:
                if sub.is_async:
                    result = await sub.handler(event)
                else:
                    result = sub.handler(event)
                results.append(result)
                if sub.once:
                    to_remove.append(sub)
            except Exception as e:
                logger.error(f"Error in async event handler for '{event_name}': {e}", exc_info=True)

        if to_remove:
            with self._lock:
                for sub in to_remove:
                    if sub in self._subscribers.get(event_name, []):
                        self._subscribers[event_name].remove(sub)

        return results

    async def _process_async_queue(self) -> None:
        """处理异步事件队列"""
        while self._running:
            try:
                if self._async_queue is None:
                    await asyncio.sleep(0.1)
                    continue
                sub, event = await asyncio.wait_for(self._async_queue.get(), timeout=1.0)
                await self._safe_async_handler(sub, event)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing async queue: {e}", exc_info=True)

    async def _safe_async_handler(self, sub: Subscription, event: Event) -> None:
        """安全执行异步处理器"""
        try:
            await sub.handler(event)
        except Exception as e:
            logger.error(f"Error in async handler for '{event.name}': {e}", exc_info=True)

    def _log_event(self, event: Event) -> None:
        """记录事件日志"""
        entry = {
            "event": event.name,
            "source": event.source,
            "timestamp": event.timestamp,
            "priority": event.priority,
        }
        self._event_log.append(entry)

    def get_event_log(self, limit: int = 50) -> List[Dict]:
        """获取事件日志"""
        return list(self._event_log)[-limit:]

    def clear_event_log(self) -> None:
        """清空事件日志"""
        self._event_log.clear()

    def get_subscribers(self, event_name: str) -> List[Subscription]:
        """获取指定事件的订阅列表"""
        with self._lock:
            return list(self._subscribers.get(event_name, []))

    def get_registered_events(self) -> Set[str]:
        """获取所有已注册的事件名"""
        return self._registered_events.copy()

    def is_running(self) -> bool:
        """事件总线是否在运行"""
        return self._running

    def subscription_count(self) -> int:
        """获取总订阅数"""
        with self._lock:
            return sum(len(subs) for subs in self._subscribers.values())


# 全局单例
_global_event_bus: Optional[EventBus] = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """
    获取全局事件总线实例

    Returns:
        EventBus 全局单例
    """
    global _global_event_bus
    if _global_event_bus is None:
        with _bus_lock:
            if _global_event_bus is None:
                _global_event_bus = EventBus()
                _global_event_bus.start()
    return _global_event_bus


def reset_event_bus() -> None:
    """
    重置全局事件总线 (主要用于测试)
    """
    global _global_event_bus
    with _bus_lock:
        if _global_event_bus is not None:
            _global_event_bus.stop()
        _global_event_bus = None
