"""事件总线与状态管理接缝的集成测试。

`EventBus` 是本仓**选定的唯一总线实现**（`cognitive_layers/memory_layer/bus_event.py:6-8` 记着
逐项比对后退役的另一份），本档钉它三形：多订阅者都收得到同一发、订阅方的回调真的落得到日志、
按优先级降序执行（`neurova/core/event_bus.py:146` 订阅即 `sort(key=priority, reverse=True)`，
HIGH=2 > NORMAL=1 > LOW=0）。

第四格钉 `StateManager` 自己的接缝：`set()` 必须把 `(key, old, new)` 同时交给 `on_change` 的键监听器
与 `on_any_change` 的全局监听器（`neurova/core/state_manager.py:102-104` 两步都在锁内）。

这一档原来写的不是这些：`setUp` 里给 `StateManager` 传了一个 `event_bus=` 关键字——该类 `__init__`
**不收任何参数**（`state_manager.py:63`），四格于是全在 setUp 就 TypeError；而第一格断言的
「状态变更会经 EventBus 发出 `state.changed`」也不是实装——`set` 调的 `_emit_state_event:220`
名字承诺"发事件"，实为遍历本地 `_any_listeners`，总线上收不到任何东西。名实不符已进
`audit-reports/zero-consumer-module-dossier-2026-10-23.md`（§6-404），本批不改生产语义，
只把判据改回它验得了的东西，并顺手把 `on_any_change` 这条**此前全仓无人钉**的读路补上。

另两处连坐修正（旧写法被 setUp 的 TypeError 盖住，从没跑到过）：`publish` 的第二个位置参是
`data`（`event_bus.py:174`），不是 `value=` 关键字；要发的第二参是**事件名字符串**，不是 `Event`
对象——`Event` 由总线自己构造。
"""

import unittest

from neurova.core.event_bus import Event, EventBus, EventPriority, get_event_bus
from neurova.core.logger import LogManager
from neurova.core.state_manager import StateManager


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
        event = self.captured_events[0]
        self.assertIsInstance(event, Event, "订阅者收到的不再是 Event 对象——契约漂移，先改判据再改总线")
        self.assertEqual(event.name, "state.changed")
        self.assertEqual(event.data["key"], "k1")
        self.assertEqual(event.data["new_value"], "v1")


class TestStateManagementSeam(unittest.TestCase):
    """`StateManager` 自己的变更接缝——不经事件总线，这条线必须说清楚。"""

    def setUp(self):
        self.manager = StateManager()

    def test_setNotifiesKeyListenerAndGlobalListener(self):
        """`set` 必须同时喂给键监听器与全局监听器，参数是 (key, old, new)。

        `on_any_change` 这一路由 `set:104` 的 `_emit_state_event` 消费，此前全仓无人钉；
        只钉 `on_change` 的话，把 `_emit_state_event` 的调用整行删掉也不会有判据变红。
        """
        seenByKey = []
        seenByAny = []
        self.manager.on_change("test_key", lambda k, old, new: seenByKey.append((k, old, new)))
        self.manager.on_any_change(lambda k, old, new: seenByAny.append((k, old, new)))

        self.manager.set("test_key", "test_value")

        self.assertEqual(seenByKey, [("test_key", None, "test_value")])
        self.assertEqual(seenByAny, [("test_key", None, "test_value")])

    def test_setDoesNotPublishOnEventBus(self):
        """实况记录：状态变更**不会**出现在全局总线上。

        本格不是给"不发事件"这个设计背书——`_emit_state_event:220` 的名字与实装不符，已立案待裁
        （`audit-reports/zero-consumer-module-dossier-2026-10-23.md`）。它要钉的是另一件事：
        **别让判据去断言一条不存在的通道**。旧档正是靠这条不存在的通道红了四格，还顺带把
        `publish` 的两处用法错误盖在 setUp 后面。

        监听的是 `get_event_bus()` 那个**单例**而不是临时实例：接线的人只会把事件发到单例上
        （`api/deps.py:197`、`endpoints/logs.py:70` 取的都是它），所以真接上了这条就会当场变红，
        是个有牙的哨，不是恒真断言。
        """
        bus = get_event_bus()
        captured = []
        bus.subscribe("state.changed", lambda event: captured.append(event),
                      module_name="seamSentinelForStateBus")
        self.addCleanup(bus.unsubscribe_module, "seamSentinelForStateBus")

        self.manager.set("project.id", "p-1")

        self.assertEqual(
            captured, [],
            "状态变更出现在总线上了——本格的实况前提已变：要么 §6-404 那张票裁定接线了，"
            "要么 `_emit_state_event` 被改成真发事件。两处都要同步改，别留名实不符")
