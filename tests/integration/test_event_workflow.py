"""
事件总线工作流集成测试
测试多个模块通过事件总线的协同工作
"""

import unittest
import time
from unittest.mock import patch, MagicMock, call

try:
    from neurova.core.event_bus import EventBus, Event
    from neurova.core.state_manager import StateManager
    from neurova.core.logger import LogManager
    HAS_REQUIRED_MODULES = True
except ImportError:
    HAS_REQUIRED_MODULES = False


@unittest.skipIf(not HAS_REQUIRED_MODULES, "Required modules not available")
class TestEventBusWorkflow(unittest.TestCase):
    """事件总线工作流集成测试"""

    def setUp(self):
        """测试前初始化"""
        self.event_bus = EventBus()
        self.state_manager = StateManager(event_bus=self.event_bus)
        self.log_manager = LogManager()

        self.captured_events = []

    def _capture_event(self, event: Event):
        """捕获事件用于测试"""
        self.captured_events.append(event)

    def test_state_change_event_emit_and_capture(self):
        """测试状态变更事件的发送和捕获"""
        # 订阅状态变更事件
        self.event_bus.subscribe("state.changed", self._capture_event)

        # 设置状态，会触发事件
        self.state_manager.set("test_key", "test_value")

        # 验证事件被捕获
        self.assertEqual(len(self.captured_events), 1)
        event = self.captured_events[0]
        self.assertEqual(event.name, "state.changed")
        self.assertEqual(event.data["key"], "test_key")
        self.assertEqual(event.data["new_value"], "test_value")

    def test_multiple_event_subscribers(self):
        """测试多个订阅者的事件处理"""
        results1 = []
        results2 = []

        handler1 = lambda e: results1.append(e.data.get("value"))
        handler2 = lambda e: results2.append(e.data.get("value"))

        self.event_bus.subscribe("test.event", handler1)
        self.event_bus.subscribe("test.event", handler2)

        # 发布事件
        self.event_bus.publish("test.event", value="test_data")

        # 验证两个订阅者都收到了事件
        self.assertEqual(len(results1), 1)
        self.assertEqual(results1[0], "test_data")
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0], "test_data")

    def test_logging_on_state_events(self):
        """测试在事件与日志记录的集成"""
        # 注册事件监听器记录日志
        def log_event_callback(event):
            self.log_manager.info(
                module="test",
                message=f"Event: {event.name}",
                context={"event_data": event.data}
            )

        self.event_bus.subscribe("test.logging", log_event_callback)

        # 发布事件
        test_event = Event(
            name="test.logging",
            data={"action": "test"}
        )
        self.event_bus.publish(test_event)

        # 验证日志记录
        logs = self.log_manager.get_entries()
        self.assertGreater(len(logs), 0)

    def test_priority_events(self):
        """测试事件优先级"""
        execution_order = []

        high_priority = lambda e: execution_order.append("high")
        normal_priority = lambda e: execution_order.append("normal")
        low_priority = lambda e: execution_order.append("low")

        from neurova.core.event_bus import EventPriority

        self.event_bus.subscribe("test.priority", low_priority, priority=EventPriority.LOW)
        self.event_bus.subscribe("test.priority", high_priority, priority=EventPriority.HIGH)
        self.event_bus.subscribe("test.priority", normal_priority, priority=EventPriority.NORMAL)

        self.event_bus.publish("test.priority")

        # 验证优先级顺序（注意：EventBus按优先级排序执行顺序：HIGH, NORMAL, LOW
        self.assertEqual(execution_order, ["high", "normal", "low"])


if __name__ == "__main__":
    unittest.main()
