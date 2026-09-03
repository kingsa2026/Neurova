"""
EventBus 全面单元测试
测试 neurova.core.event_bus 模块的所有功能
"""
import pytest
import asyncio
import time
from dataclasses import dataclass
from typing import Any, List, Dict

from neurova.core.event_bus import (
    EventBus,
    Event,
    EventPriority,
    Subscription,
    get_event_bus,
    reset_event_bus,
)


class TestEventPriority:
    """测试事件优先级枚举"""

    def test_priority_values(self):
        """测试优先级数值"""
        assert EventPriority.CRITICAL == 0
        assert EventPriority.HIGH == 1
        assert EventPriority.NORMAL == 2
        assert EventPriority.LOW == 3
        assert EventPriority.BACKGROUND == 4

    def test_priority_ordering(self):
        """测试优先级排序"""
        priorities = [
            EventPriority.BACKGROUND,
            EventPriority.LOW,
            EventPriority.NORMAL,
            EventPriority.HIGH,
            EventPriority.CRITICAL,
        ]
        sorted_priorities = sorted(priorities, key=lambda p: p.value)
        assert sorted_priorities == [
            EventPriority.CRITICAL,
            EventPriority.HIGH,
            EventPriority.NORMAL,
            EventPriority.LOW,
            EventPriority.BACKGROUND,
        ]


class TestEvent:
    """测试 Event 数据类"""

    def test_event_creation_minimal(self):
        """测试最小参数创建事件"""
        event = Event(name="test_event")
        assert event.name == "test_event"
        assert event.data is None
        assert event.source is None
        assert isinstance(event.timestamp, float)
        assert event.metadata == {"priority": EventPriority.NORMAL}

    def test_event_creation_full(self):
        """测试完整参数创建事件"""
        data = {"key": "value"}
        metadata = {"custom": True}
        event = Event(
            name="full_event",
            data=data,
            source="test_module",
            timestamp=1234567890.0,
            metadata=metadata,
        )
        assert event.name == "full_event"
        assert event.data == data
        assert event.source == "test_module"
        assert event.timestamp == 1234567890.0
        assert event.metadata["custom"] is True
        assert event.metadata["priority"] == EventPriority.NORMAL

    def test_event_post_init_metadata_none(self):
        """测试 metadata=None 时自动设置为空字典，并添加默认优先级"""
        event = Event(name="test", metadata=None)
        assert event.metadata == {"priority": EventPriority.NORMAL}


class TestSubscription:
    """测试 Subscription 数据类"""

    def test_subscription_sync(self):
        """测试同步回调的订阅"""
        def sync_callback(event):
            return "sync"

        sub = Subscription(
            callback=sync_callback,
            priority=EventPriority.HIGH,
            once=False,
            module_id="test_module",
            is_async=False,
        )
        assert sub.callback == sync_callback
        assert sub.priority == EventPriority.HIGH
        assert sub.once is False
        assert sub.module_id == "test_module"
        assert sub.is_async is False

    def test_subscription_async(self):
        """测试异步回调的订阅"""
        async def async_callback(event):
            return "async"

        sub = Subscription(
            callback=async_callback,
            priority=EventPriority.CRITICAL,
            once=True,
            module_id="async_module",
            is_async=True,
        )
        assert sub.callback == async_callback
        assert sub.priority == EventPriority.CRITICAL
        assert sub.once is True
        assert sub.module_id == "async_module"
        assert sub.is_async is True


class TestEventBusBasic:
    """测试 EventBus 基础功能"""

    @pytest.fixture
    def event_bus(self):
        """创建 EventBus 实例"""
        bus = EventBus()
        yield bus
        # 清理
        if bus.is_running:
            asyncio.get_event_loop().run_until_complete(bus.stop())

    def test_initial_state(self, event_bus):
        """测试初始状态"""
        assert event_bus.is_running is False
        assert event_bus.subscription_count == 0
        assert event_bus.get_registered_events() == []
        assert event_bus.get_event_log() == []

    def test_subscribe_sync(self, event_bus):
        """测试订阅同步事件"""
        def handler(event):
            return "handled"

        event_bus.subscribe("test_event", handler)
        assert event_bus.subscription_count == 1
        assert "test_event" in event_bus.get_registered_events()

    def test_subscribe_async(self, event_bus):
        """测试订阅异步事件"""
        async def async_handler(event):
            return "async_handled"

        event_bus.subscribe("test_event", async_handler)
        assert event_bus.subscription_count == 1
        subs = event_bus.get_subscribers("test_event")
        assert len(subs) == 1
        assert subs[0].is_async is True

    def test_subscribe_with_priority(self, event_bus):
        """测试带优先级的订阅"""
        def handler(event):
            return "handled"

        event_bus.subscribe("test_event", handler, priority=EventPriority.HIGH)
        subs = event_bus.get_subscribers("test_event")
        assert subs[0].priority == EventPriority.HIGH

    def test_subscribe_once(self, event_bus):
        """测试一次性订阅"""
        def handler(event):
            return "handled"

        event_bus.subscribe("test_event", handler, once=True)
        subs = event_bus.get_subscribers("test_event")
        assert subs[0].once is True

    def test_subscribe_with_module_id(self, event_bus):
        """测试带模块ID的订阅"""
        def handler(event):
            return "handled"

        event_bus.subscribe("test_event", handler, module_id="test_module")
        subs = event_bus.get_subscribers("test_event")
        assert subs[0].module_id == "test_module"

    def test_unsubscribe(self, event_bus):
        """测试取消订阅"""
        def handler(event):
            return "handled"

        event_bus.subscribe("test_event", handler)
        assert event_bus.subscription_count == 1

        result = event_bus.unsubscribe("test_event", handler)
        assert result is True
        assert event_bus.subscription_count == 0

    def test_unsubscribe_nonexistent_event(self, event_bus):
        """测试取消不存在的事件订阅"""
        def handler(event):
            return "handled"

        result = event_bus.unsubscribe("nonexistent", handler)
        assert result is False

    def test_unsubscribe_module(self, event_bus):
        """测试取消模块的所有订阅"""
        def handler1(event):
            return "handler1"

        def handler2(event):
            return "handler2"

        event_bus.subscribe("event1", handler1, module_id="module_a")
        event_bus.subscribe("event2", handler2, module_id="module_a")
        event_bus.subscribe("event3", handler1, module_id="module_b")

        count = event_bus.unsubscribe_module("module_a")
        assert count == 2
        assert event_bus.subscription_count == 1


class TestEventBusPublish:
    """测试 EventBus 事件发布功能"""

    @pytest.fixture
    def event_bus(self):
        """创建 EventBus 实例"""
        bus = EventBus()
        yield bus

    def test_publish_string_event(self, event_bus):
        """测试发布字符串事件（自动转换为Event对象）"""
        results = []
        def handler(event):
            results.append(event.data)

        event_bus.subscribe("test_event", handler)
        event_bus.publish("test_event", key="value")

        assert len(results) == 1
        assert results[0]["key"] == "value"

    def test_publish_event_object(self, event_bus):
        """测试发布Event对象"""
        results = []
        def handler(event):
            results.append(event)

        event_bus.subscribe("test_event", handler)
        event = Event(name="test_event", data={"test": True})
        event_bus.publish(event)

        assert len(results) == 1
        assert results[0].data == {"test": True}

    def test_publish_no_subscribers(self, event_bus):
        """测试发布没有订阅者的事件"""
        results = event_bus.publish("no_subscribers")
        assert results == []

    def test_publish_sync_handler(self, event_bus):
        """测试同步处理器"""
        results = []
        def handler(event):
            results.append("handled")
            return "result"

        event_bus.subscribe("test_event", handler)
        return_values = event_bus.publish("test_event")

        assert len(results) == 1
        assert "handled" in results
        assert len(return_values) == 1
        assert return_values[0] == "result"

    def test_publish_priority_ordering(self, event_bus):
        """测试优先级排序执行"""
        results = []
        
        def make_handler(name, priority):
            def handler(event):
                results.append((priority, name))
            return handler

        # 按逆序订阅
        event_bus.subscribe("test_event", make_handler("low", EventPriority.LOW), priority=EventPriority.LOW)
        event_bus.subscribe("test_event", make_handler("high", EventPriority.HIGH), priority=EventPriority.HIGH)
        event_bus.subscribe("test_event", make_handler("critical", EventPriority.CRITICAL), priority=EventPriority.CRITICAL)

        event_bus.publish("test_event")

        # 验证按优先级顺序执行
        assert results[0][0] == EventPriority.CRITICAL
        assert results[1][0] == EventPriority.HIGH
        assert results[2][0] == EventPriority.LOW

    def test_publish_once_subscription(self, event_bus):
        """测试一次性订阅"""
        results = []
        def handler(event):
            results.append("handled")

        event_bus.subscribe("test_event", handler, once=True)
        event_bus.publish("test_event")
        event_bus.publish("test_event")

        assert len(results) == 1  # 只执行一次

    def test_publish_handler_exception(self, event_bus):
        """测试处理器异常不影响其他处理器"""
        results = []
        
        def failing_handler(event):
            raise ValueError("Test error")

        def success_handler(event):
            results.append("success")

        event_bus.subscribe("test_event", failing_handler)
        event_bus.subscribe("test_event", success_handler)
        
        # 不应该抛出异常
        event_bus.publish("test_event")

        assert len(results) == 1
        assert "success" in results


class TestEventBusAsync:
    """测试 EventBus 异步功能"""

    @pytest.fixture
    def event_loop(self):
        """创建事件循环"""
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()

    @pytest.fixture
    def event_bus(self):
        """创建并启动 EventBus"""
        bus = EventBus()
        yield bus
        if bus.is_running:
            asyncio.get_event_loop().run_until_complete(bus.stop())

    @pytest.mark.asyncio
    async def test_start_stop(self, event_bus):
        """测试启动和停止"""
        assert event_bus.is_running is False
        
        await event_bus.start()
        assert event_bus.is_running is True

        await event_bus.stop()
        assert event_bus.is_running is False

    @pytest.mark.asyncio
    async def test_start_already_running(self, event_bus):
        """测试重复启动"""
        await event_bus.start()
        assert event_bus.is_running is True

        # 再次启动应该无操作
        await event_bus.start()
        assert event_bus.is_running is True

        await event_bus.stop()

    @pytest.mark.asyncio
    async def test_stop_not_running(self, event_bus):
        """测试停止未运行的总线"""
        # 不应该抛出异常
        await event_bus.stop()
        assert event_bus.is_running is False

    @pytest.mark.asyncio
    async def test_publish_async(self, event_bus):
        """测试异步发布事件"""
        results = []
        
        async def async_handler(event):
            results.append("async_handled")
            return "async_result"

        event_bus.subscribe("test_event", async_handler)
        
        await event_bus.start()
        return_values = await event_bus.publish_async("test_event")

        assert len(results) == 1
        assert "async_handled" in results
        await event_bus.stop()

    @pytest.mark.asyncio
    async def test_publish_async_with_sync_handler(self, event_bus):
        """测试异步发布中调用同步处理器"""
        results = []
        
        def sync_handler(event):
            results.append("sync_handled")
            return "sync_result"

        event_bus.subscribe("test_event", sync_handler)
        
        await event_bus.start()
        return_values = await event_bus.publish_async("test_event")

        assert len(results) == 1
        assert "sync_handled" in results
        await event_bus.stop()


class TestEventBusLogging:
    """测试 EventBus 事件日志功能"""

    @pytest.fixture
    def event_bus(self):
        """创建 EventBus 实例"""
        bus = EventBus()
        yield bus

    def test_log_event(self, event_bus):
        """测试事件日志记录"""
        def handler(event):
            pass

        event_bus.subscribe("test_event", handler)
        event_bus.publish("test_event", data="test")

        log = event_bus.get_event_log()
        assert len(log) == 1
        assert log[0][1].name == "test_event"
        assert log[0][1].data == {"data": "test"}

    def test_log_event_with_limit(self, event_bus):
        """测试获取日志限制数量"""
        def handler(event):
            pass

        event_bus.subscribe("test_event", handler)
        
        # 发布多个事件
        for i in range(10):
            event_bus.publish("test_event", index=i)

        log = event_bus.get_event_log(limit=5)
        assert len(log) == 5

    def test_log_event_filter_by_name(self, event_bus):
        """测试按事件名称过滤日志"""
        def handler(event):
            pass

        event_bus.subscribe("event1", handler)
        event_bus.subscribe("event2", handler)
        
        event_bus.publish("event1")
        event_bus.publish("event2")
        event_bus.publish("event1")

        log = event_bus.get_event_log(event_name="event1")
        assert len(log) == 2
        assert all(evt.name == "event1" for _, evt in log)

    def test_clear_log(self, event_bus):
        """测试清空日志"""
        def handler(event):
            pass

        event_bus.subscribe("test_event", handler)
        event_bus.publish("test_event")

        assert len(event_bus.get_event_log()) == 1

        event_bus.clear_event_log()
        assert len(event_bus.get_event_log()) == 0

    def test_log_size_limit(self, event_bus):
        """测试日志大小限制"""
        def handler(event):
            pass

        event_bus.subscribe("test_event", handler)
        event_bus._max_log_size = 10  # 设置小限制

        # 发布超过限制的事件
        for i in range(20):
            event_bus.publish("test_event", index=i)

        log = event_bus.get_event_log()
        assert len(log) <= event_bus._max_log_size


class TestGlobalEventBus:
    """测试全局 EventBus 函数"""

    def teardown_method(self):
        """每个测试后重置全局总线"""
        reset_event_bus()

    def test_get_event_bus_singleton(self):
        """测试全局总线单例"""
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_get_event_bus_type(self):
        """测试全局总线类型"""
        bus = get_event_bus()
        assert isinstance(bus, EventBus)

    def test_reset_event_bus(self):
        """测试重置全局总线"""
        bus1 = get_event_bus()
        reset_event_bus()
        bus2 = get_event_bus()
        assert bus1 is not bus2


class TestEventBusEdgeCases:
    """测试 EventBus 边界情况"""

    @pytest.fixture
    def event_bus(self):
        """创建 EventBus 实例"""
        bus = EventBus()
        yield bus

    def test_multiple_handlers_same_event(self, event_bus):
        """测试同一事件的多个处理器"""
        results = []
        
        def handler1(event):
            results.append("handler1")

        def handler2(event):
            results.append("handler2")

        def handler3(event):
            results.append("handler3")

        event_bus.subscribe("test_event", handler1)
        event_bus.subscribe("test_event", handler2)
        event_bus.subscribe("test_event", handler3)

        event_bus.publish("test_event")

        assert len(results) == 3
        assert "handler1" in results
        assert "handler2" in results
        assert "handler3" in results

    def test_subscribe_unsubscribe_resubscribe(self, event_bus):
        """测试订阅-取消-重新订阅"""
        results = []
        def handler(event):
            results.append("handled")

        event_bus.subscribe("test_event", handler)
        event_bus.publish("test_event")
        assert len(results) == 1

        event_bus.unsubscribe("test_event", handler)
        event_bus.publish("test_event")
        assert len(results) == 1  # 未增加

        event_bus.subscribe("test_event", handler)
        event_bus.publish("test_event")
        assert len(results) == 2  # 重新订阅后增加

    def test_get_subscribers_nonexistent(self, event_bus):
        """测试获取不存在事件的订阅者"""
        subs = event_bus.get_subscribers("nonexistent")
        assert subs == []

    def test_publish_with_complex_data(self, event_bus):
        """测试发布复杂数据"""
        received = []
        
        def handler(event):
            received.append(event.data)

        event_bus.subscribe("test_event", handler)

        complex_data = {
            "list": [1, 2, 3],
            "dict": {"nested": True},
            "none": None,
            "number": 42,
            "text": "hello",
        }
        event_bus.publish("test_event", **complex_data)

        assert len(received) == 1
        # 数据会放在 data 字段中
        assert received[0]["list"] == [1, 2, 3]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
