"""
EventBusEnhanced — 增强版事件总线深度模块

在现有EventBus基础上，增加以下功能：
1. 事件过滤（基于数据内容）
2. 事件重播（重新触发历史事件）
3. 死信队列（处理失败的事件）
4. 事件超时处理
5. 事件链（一个事件触发另一个事件）

设计原则：
- 小接口，深实现
- 向后兼容（继承EventBus）
- 可测试性
"""

import asyncio
from neurova.core.logger import get_logger
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from .event_bus import Event, EventBus, EventPriority, Subscription

logger = get_logger(__name__)


@dataclass
class EventFilter:
    """事件过滤器"""
    name: str
    predicate: Callable[[Event], bool]
    description: str = ""


@dataclass
class DeadLetter:
    """死信事件"""
    event: Event
    subscription: Subscription
    error: Exception
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0


class EventBusEnhanced(EventBus):
    """
    增强版事件总线

    在现有EventBus基础上，增加：
    1. 事件过滤
    2. 事件重播
    3. 死信队列
    4. 事件超时处理
    5. 事件链
    """

    def __init__(self, max_log_size: int = 1000, max_dead_letters: int = 100):
        super().__init__(max_log_size)
        self._filters: Dict[str, List[EventFilter]] = {}
        self._dead_letters: deque = deque(maxlen=max_dead_letters)
        self._event_chains: Dict[str, List[str]] = {}
        self._event_history: deque = deque(maxlen=1000)  # 用于重播
        self._timeout_handlers: Dict[str, float] = {}  # 事件超时配置
        self._lock = threading.RLock()
        logger.info("EventBusEnhanced initialized")

    def add_filter(self, event_name: str, filter_obj: EventFilter) -> None:
        """
        添加事件过滤器

        Args:
            event_name: 事件名称
            filter_obj: 过滤器对象
        """
        with self._lock:
            if event_name not in self._filters:
                self._filters[event_name] = []
            self._filters[event_name].append(filter_obj)
        logger.debug("Added filter for event '%s': %s", event_name, filter_obj.name)

    def remove_filter(self, event_name: str, filter_name: str) -> bool:
        """
        移除事件过滤器

        Args:
            event_name: 事件名称
            filter_name: 过滤器名称

        Returns:
            是否成功移除
        """
        with self._lock:
            if event_name not in self._filters:
                return False
            before = len(self._filters[event_name])
            self._filters[event_name] = [
                f for f in self._filters[event_name] if f.name != filter_name
            ]
            return len(self._filters[event_name]) < before

    def _apply_filters(self, event: Event) -> bool:
        """
        应用事件过滤器

        Args:
            event: 事件对象

        Returns:
            是否通过所有过滤器
        """
        filters = self._filters.get(event.name, [])
        for filter_obj in filters:
            try:
                if not filter_obj.predicate(event):
                    logger.debug("Event '%s' filtered out by '%s'", event.name, filter_obj.name)
                    return False
            except Exception as e:
                logger.error("Error in filter '%s' for event '%s': %s", filter_obj.name, event.name, e)
                # 过滤器异常时阻止事件
                return False
        return True

    def publish(self, event_name: str, data: Any = None, source: str = "") -> List[Any]:
        """
        同步发布事件（带过滤）

        Args:
            event_name: 事件名称
            data: 事件数据
            source: 事件来源

        Returns:
            所有同步 handler 的返回值列表
        """
        event = Event(name=event_name, data=data, source=source)

        # 应用过滤器
        if not self._apply_filters(event):
            return []

        # 记录到事件历史（用于重播）
        self._event_history.append(event)

        # 调用父类发布
        results = super().publish(event_name, data, source)

        # 处理事件链
        self._process_event_chains(event)

        return results

    async def publish_async(self, event_name: str, data: Any = None, source: str = "") -> List[Any]:
        """
        异步发布事件（带过滤）

        Args:
            event_name: 事件名称
            data: 事件数据
            source: 事件来源

        Returns:
            所有 handler 的返回值列表
        """
        event = Event(name=event_name, data=data, source=source)

        # 应用过滤器
        if not self._apply_filters(event):
            return []

        # 记录到事件历史（用于重播）
        self._event_history.append(event)

        # 调用父类异步发布
        results = await super().publish_async(event_name, data, source)

        # 处理事件链
        self._process_event_chains(event)

        return results

    def add_event_chain(self, trigger_event: str, target_events: List[str]) -> None:
        """
        添加事件链（一个事件触发多个事件）

        Args:
            trigger_event: 触发事件
            target_events: 目标事件列表
        """
        with self._lock:
            self._event_chains[trigger_event] = target_events
        logger.debug("Added event chain: %s -> %s", trigger_event, target_events)

    def remove_event_chain(self, trigger_event: str) -> bool:
        """
        移除事件链

        Args:
            trigger_event: 触发事件

        Returns:
            是否成功移除
        """
        with self._lock:
            if trigger_event in self._event_chains:
                del self._event_chains[trigger_event]
                return True
            return False

    def _process_event_chains(self, event: Event) -> None:
        """
        处理事件链

        Args:
            event: 触发事件
        """
        target_events = self._event_chains.get(event.name, [])
        for target_event in target_events:
            try:
                # 发布目标事件，传递原始事件数据
                self.publish(target_event, data=event.data, source=f"chain:{event.name}")
            except Exception as e:
                logger.error("Error in event chain from '%s' to '%s': %s", event.name, target_event, e)

    def replay_events(self, event_name: Optional[str] = None, limit: int = 100) -> int:
        """
        重播历史事件

        Args:
            event_name: 事件名称过滤（可选）
            limit: 重播数量限制

        Returns:
            重播的事件数量
        """
        count = 0
        events_to_replay = []

        # 获取要重播的事件
        for event in reversed(self._event_history):
            if event_name and event.name != event_name:
                continue
            events_to_replay.append(event)
            if len(events_to_replay) >= limit:
                break

        # 重播事件（按时间顺序）
        for event in reversed(events_to_replay):
            try:
                # 直接调用父类的publish，避免重复记录到历史
                Event(name=event.name, data=event.data, source=f"replay:{event.source}")
                # 使用父类的发布方法，不记录到历史
                results = []
                with self._lock:
                    subs = list(self._subscribers.get(event.name, []))
                
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
                        logger.error(f"Error in event handler for '{event.name}': {e}", exc_info=True)

                # 移除一次性订阅
                if to_remove:
                    with self._lock:
                        for sub in to_remove:
                            if sub in self._subscribers.get(event.name, []):
                                self._subscribers[event.name].remove(sub)
                
                count += 1
            except Exception as e:
                logger.error("Error replaying event '%s': %s", event.name, e)

        logger.info("Replayed %d events", count)
        return count

    def add_dead_letter(self, event: Event, subscription: Subscription, error: Exception) -> None:
        """
        添加死信事件

        Args:
            event: 事件对象
            subscription: 订阅信息
            error: 异常信息
        """
        dead_letter = DeadLetter(
            event=event,
            subscription=subscription,
            error=error,
        )
        with self._lock:
            self._dead_letters.append(dead_letter)
        logger.warning("Added dead letter for event '%s': %s", event.name, error)

    def get_dead_letters(self, limit: int = 50) -> List[DeadLetter]:
        """
        获取死信事件列表

        Args:
            limit: 返回数量限制

        Returns:
            死信事件列表
        """
        with self._lock:
            return list(self._dead_letters)[-limit:]

    def clear_dead_letters(self) -> int:
        """
        清空死信队列

        Returns:
            清空的死信数量
        """
        with self._lock:
            count = len(self._dead_letters)
            self._dead_letters.clear()
            return count

    def retry_dead_letter(self, dead_letter: DeadLetter) -> bool:
        """
        重试死信事件

        Args:
            dead_letter: 死信事件

        Returns:
            是否重试成功
        """
        try:
            self.publish(dead_letter.event.name, data=dead_letter.event.data, source=f"retry:{dead_letter.event.source}")
            return True
        except Exception as e:
            logger.error("Error retrying dead letter for event '%s': %s", dead_letter.event.name, e)
            return False

    def set_event_timeout(self, event_name: str, timeout_seconds: float) -> None:
        """
        设置事件超时时间

        Args:
            event_name: 事件名称
            timeout_seconds: 超时时间（秒）
        """
        with self._lock:
            self._timeout_handlers[event_name] = timeout_seconds
        logger.debug("Set timeout for event '%s': %.2f seconds", event_name, timeout_seconds)

    def get_event_history(self, event_name: Optional[str] = None, limit: int = 100) -> List[Event]:
        """
        获取事件历史

        Args:
            event_name: 事件名称过滤（可选）
            limit: 返回数量限制

        Returns:
            事件历史列表
        """
        events = []
        for event in reversed(self._event_history):
            if event_name and event.name != event_name:
                continue
            events.append(event)
            if len(events) >= limit:
                break
        return events

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取增强统计信息

        Returns:
            统计信息字典
        """
        base_stats = {
            "total_events": len(self._event_history),
            "total_subscriptions": self.subscription_count(),
            "dead_letters": len(self._dead_letters),
            "event_chains": len(self._event_chains),
            "filters": sum(len(filters) for filters in self._filters.values()),
        }
        return base_stats


# 全局单例
_global_event_bus_enhanced: Optional[EventBusEnhanced] = None
_bus_enhanced_lock = threading.Lock()


def get_event_bus_enhanced() -> EventBusEnhanced:
    """
    获取全局增强事件总线实例

    Returns:
        EventBusEnhanced 全局单例
    """
    global _global_event_bus_enhanced
    if _global_event_bus_enhanced is None:
        with _bus_enhanced_lock:
            if _global_event_bus_enhanced is None:
                _global_event_bus_enhanced = EventBusEnhanced()
                _global_event_bus_enhanced.start()
    return _global_event_bus_enhanced


def reset_event_bus_enhanced() -> None:
    """
    重置全局增强事件总线 (主要用于测试)
    """
    global _global_event_bus_enhanced
    with _bus_enhanced_lock:
        if _global_event_bus_enhanced is not None:
            _global_event_bus_enhanced.stop()
        _global_event_bus_enhanced = None