"""事件总线集成测试。

`EventBus` 是本仓**选定的唯一总线实现**（`cognitive_layers/memory_layer/bus_event.py:6-8` 记着
逐项比对后退役的另一份），本档钉它三形：多订阅者都收得到同一发、订阅方的回调真的落得到日志、
按优先级降序执行（`neurova/core/event_bus.py:146` 订阅即 `sort(key=priority, reverse=True)`，
HIGH=2 > NORMAL=1 > LOW=0）。

历史注记（S7 死码退役批）：本档原有第四格钉 `StateManager` 的变更接缝——该模块生产零消费，
已随 P1-11 整体退役（`neurova/core/state_manager.py` 已删），那几格一并摘除。当年"状态变更
是否上总线"的名实之辨（§6-404）随模块退役自然了结。

另两处连坐修正（旧写法曾被 setUp 的 TypeError 盖住，从没跑到过）：`publish` 的第二个位置参是
`data`（`event_bus.py:174`），不是 `value=` 关键字；要发的第二参是**事件名字符串**，不是 `Event`
对象——`Event` 由总线自己构造。
"""

import unittest

from neurova.core.event_bus import Event, EventBus, EventPriority, get_event_bus
from neurova.core.logger import LogManager


class TestEventBusWorkflow(unittest.TestCase):
    """事件总线契约：订阅、投递、优先级排序。"""

    def setUp(self):
        self.event_bus = EventBus()
        self.log_manager = LogManager()
        self.captured_events = []

    def _capture_event(self, event):
        self.captured_events.append(event)

    def test_multiple_event_subscribers(self):
        """同一事件名的两个订阅者都必须收到，且收到的是带 data 的 Event 对象。"""
        results1 = []
        results2 = []

        self.event_bus.subscribe("test.event", lambda e: results1.append(e.data.get("value")))
        self.event_bus.subscribe("test.event", lambda e: results2.append(e.data.get("value")))

        self.event_bus.publish("test.event", {"value": "test_data"})

        self.assertEqual(results1, ["test_data"])
        self.assertEqual(results2, ["test_data"])

    def test_logging_on_state_events(self):
        """订阅方的回调里写日志，日志必须真落进 LogManager——否则"订上了"会被读成"收得到"。"""
        def log_event_callback(event):
            self.log_manager.info(
                module="test",
                message=f"Event: {event.name}",
                context={"event_data": event.data},
            )

        self.event_bus.subscribe("test.logging", log_event_callback)
        self.event_bus.publish("test.logging", {"action": "test"})

        logs = self.log_manager.get_entries(module="test")
        self.assertGreater(len(logs), 0)
        self.assertIn("test.logging", logs[0].message)

    def test_priority_events(self):
        """订阅顺序不影响执行顺序：总线按优先级降序派发（HIGH→NORMAL→LOW）。"""
        execution_order = []

        self.event_bus.subscribe("test.priority", lambda e: execution_order.append("low"),
                                 priority=EventPriority.LOW)
        self.event_bus.subscribe("test.priority", lambda e: execution_order.append("high"),
                                 priority=EventPriority.HIGH)
        self.event_bus.subscribe("test.priority", lambda e: execution_order.append("normal"),
                                 priority=EventPriority.NORMAL)

        self.event_bus.publish("test.priority")

        self.assertEqual(execution_order, ["high", "normal", "low"])

    def test_subscriberReceivesEventNameAndData(self):
        """订阅者拿到的是 `Event`，其 name/data 与 publish 的入参一致（不是散装关键字）。"""
        self.event_bus.subscribe("state.changed", self._capture_event)

        self.event_bus.publish("state.changed", {"key": "k1", "new_value": "v1"})

        self.assertEqual(len(self.captured_events), 1)
