"""
EventBus 单元测试
"""

import unittest
import asyncio
from unittest.mock import patch, MagicMock, call

from neurova.core.event_bus import (
    EventBus,
    Event,
    EventPriority,
    get_event_bus,
    reset_event_bus,
)


class TestEventBus(unittest.TestCase):
    """EventBus 测试类"""

    def setUp(self) -> None:
        """测试前初始化"""
        reset_event_bus()
        self.event_bus = EventBus()

    def tearDown(self) -> None:
        """测试后清理"""
        reset_event_bus()

    def test_event_creation(self) -> None:
        """测试事件创建"""
        event = Event(
            name="test.event",
            data={"key": "value"},
            source="test_module"
        )

        self.assertEqual(event.name, "test.event")
        self.assertEqual(event.data, {"key": "value"})
        self.assertEqual(event.source, "test_module")
        self.assertIsNotNone(event.timestamp)

    def test_event_default_metadata(self) -> None:
        """测试事件默认元数据"""
        event = Event(name="test.event")
        self.assertEqual(event.metadata["priority"], EventPriority.NORMAL)

    def test_subscribe_and_publish(self) -> None:
        """测试订阅和发布"""
        callback = MagicMock()

        self.event_bus.subscribe("test.event", callback)
        self.event_bus.publish("test.event", data="test_data")

        callback.assert_called_once()
        args = callback.call_args[0]
        self.assertEqual(args[0].name, "test.event")
        self.assertEqual(args[0].data, {"data": "test_data"})

    def test_unsubscribe(self) -> None:
        """测试取消订阅"""
        callback = MagicMock()

        self.event_bus.subscribe("test.event", callback)
        self.event_bus.publish("test.event")
        callback.assert_called_once()

        callback.reset_mock()
        self.event_bus.unsubscribe("test.event", callback)
        self.event_bus.publish("test.event")
        callback.assert_not_called()

    def test_unsubscribe_module(self) -> None:
        """测试取消模块订阅"""
        callback1 = MagicMock()
        callback2 = MagicMock()

        self.event_bus.subscribe("event1", callback1, module_id="module1")
        self.event_bus.subscribe("event2", callback2, module_id="module1")
        self.event_bus.subscribe("event1", MagicMock(), module_id="module2")

        removed = self.event_bus.unsubscribe_module("module1")
        self.assertEqual(removed, 2)

    def test_once_subscription(self) -> None:
        """测试一次性订阅"""
        callback = MagicMock()

        self.event_bus.subscribe("test.event", callback, once=True)
        self.event_bus.publish("test.event")
        self.event_bus.publish("test.event")

        callback.assert_called_once()

    def test_priority_order(self) -> None:
        """测试优先级顺序"""
        calls = []

        def low_priority(event):
            calls.append("low")

        def high_priority(event):
            calls.append("high")

        def normal_priority(event):
            calls.append("normal")

        self.event_bus.subscribe("test.event", low_priority, priority=EventPriority.LOW)
        self.event_bus.subscribe("test.event", normal_priority, priority=EventPriority.NORMAL)
        self.event_bus.subscribe("test.event", high_priority, priority=EventPriority.HIGH)

        self.event_bus.publish("test.event")

        self.assertEqual(calls, ["high", "normal", "low"])

    def test_event_logging(self) -> None:
        """测试事件日志"""
        self.event_bus.publish("event1")
        self.event_bus.publish("event2")
        self.event_bus.publish("event1")

        log = self.event_bus.get_event_log()
        self.assertEqual(len(log), 3)

        # 按事件名称过滤
        event1_log = self.event_bus.get_event_log(event_name="event1")
        self.assertEqual(len(event1_log), 2)

    def test_clear_event_log(self) -> None:
        """测试清空事件日志"""
        self.event_bus.publish("test.event")
        self.assertEqual(len(self.event_bus.get_event_log()), 1)

        self.event_bus.clear_event_log()
        self.assertEqual(len(self.event_bus.get_event_log()), 0)

    def test_get_subscribers(self) -> None:
        """测试获取订阅者"""
        callback1 = MagicMock()
        callback2 = MagicMock()

        self.event_bus.subscribe("test.event", callback1)
        self.event_bus.subscribe("test.event", callback2)

        subscribers = self.event_bus.get_subscribers("test.event")
        self.assertEqual(len(subscribers), 2)

    def test_get_registered_events(self) -> None:
        """测试获取已注册事件"""
        self.event_bus.subscribe("event1", MagicMock())
        self.event_bus.subscribe("event2", MagicMock())

        events = self.event_bus.get_registered_events()
        self.assertEqual(set(events), {"event1", "event2"})

    def test_subscription_count(self) -> None:
        """测试订阅数量"""
        self.event_bus.subscribe("event1", MagicMock())
        self.event_bus.subscribe("event1", MagicMock())
        self.event_bus.subscribe("event2", MagicMock())

        self.assertEqual(self.event_bus.subscription_count, 3)

    def test_global_event_bus(self) -> None:
        """测试全局事件总线"""
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        self.assertIs(bus1, bus2)

    def test_publish_event_object(self) -> None:
        """测试发布事件对象"""
        callback = MagicMock()
        event = Event(name="test.event", data={"custom": "data"})

        self.event_bus.subscribe("test.event", callback)
        self.event_bus.publish(event)

        callback.assert_called_once()
        self.assertEqual(callback.call_args[0][0].data, {"custom": "data"})


class TestEventBusAsync(unittest.TestCase):
    """EventBus 异步测试类"""

    def setUp(self) -> None:
        """测试前初始化"""
        reset_event_bus()
        self.event_bus = EventBus()

    def tearDown(self) -> None:
        """测试后清理"""
        reset_event_bus()

    def test_async_callback(self) -> None:
        """测试异步回调"""
        result = []

        async def async_callback(event):
            result.append("async")

        def sync_callback(event):
            result.append("sync")

        self.event_bus.subscribe("test.event", async_callback)
        self.event_bus.subscribe("test.event", sync_callback)

        # 测试同步发布
        self.event_bus.publish("test.event")
        self.assertEqual(result, ["sync"])

    def test_start_stop(self) -> None:
        """测试启动和停止"""
        self.assertFalse(self.event_bus.is_running)

        async def test():
            await self.event_bus.start()
            self.assertTrue(self.event_bus.is_running)
            await self.event_bus.stop()
            self.assertFalse(self.event_bus.is_running)

        asyncio.run(test())


if __name__ == "__main__":
    unittest.main()
