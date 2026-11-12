# -*- coding: utf-8 -*-
"""W3 事件桥（specs/2026-11-12 §5）：state_event_bridge.py。

启动按 event_bindings 登记 subscribe_event；事件到达→映射 descriptor 取
subject/state→构造 AdmissionRequest→admit（身份按 descriptor 显式带
tenant/agent，不从 ContextVar 猜）；未映射事件零写入；fail-closed：admit 拒
记审计不重试风暴；缺省 off（env 开关），off 零订阅。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.state_machine_registry import StateMachineRegistry
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.state_event_bridge import (
    BRIDGE_ENV,
    StateEventBridge,
    module_name as BRIDGE_MODULE,
)


@pytest.fixture
def kb(tmp_path, monkeypatch):
    monkeypatch.delenv(BRIDGE_ENV, raising=False)
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("orders", "concept", label="订单")
    registry.register("has_state", "relation", cardinality=1)
    reg = StateMachineRegistry(s)
    reg.register(
        termId="orders", tenantId="default",
        states=["created", "paid"],
        transitions=[{"from": "created", "to": "paid"}],
        initialState="created",
        eventBindings=[{"eventName": "kb.order.paid",
                        "subjectField": "order_label",
                        "stateField": "new_state",
                        "agentId": "default",
                        "tenantId": "default"}])
    yield s, registry, reg
    s.close()


class TestEventBridge:
    def test_defaultOffZeroSubscriptions(self, kb, monkeypatch):
        """缺省 off：start 后零订阅（配置开关语义）。"""
        s, _registry, _reg = kb
        from neurova.core.event_bus import resolveEventBus

        bus = resolveEventBus()
        before = dict(bus._subscribers)
        bridge = StateEventBridge(s)
        bridge.start()
        assert dict(bus._subscribers) == before, "缺省 off 不订阅"
        bridge.stop()

    def test_onThenEventAdmitsHasState(self, kb, monkeypatch):
        s, _registry, _reg = kb
        monkeypatch.setenv(BRIDGE_ENV, "1")
        from neurova.core.event_bus import resolveEventBus

        bus = resolveEventBus()
        bridge = StateEventBridge(s)
        bridge.start()
        try:
            subs = bus._subscribers.get("kb.order.paid") or []
            assert subs, "开关 on 后按 event_bindings 订阅"
            gate = productionAdmissionGate(s)
            content = "订单EV1 is_a orders"
            gate.admit(AdmissionRequest(
                agentId="default", subjectLabel="订单EV1", predicateTermId="is_a",
                objectTerm="orders", content=content,
                assertions=[{"actorType": "pipeline", "actorId": "unit",
                             "mediumRef": "unit:test", "statementText": content}]))
            _registry.assignSubjectType(s.resolveSubjectKey("default", "订单EV1"), "orders")
            bus.publish("kb.order.paid",
                        {"order_label": "订单EV1", "new_state": "created"},
                        source="test")
            key = s.resolveSubjectKey("default", "订单EV1")
            states = [f["object_term"] for f in s.factsForSubject(key)
                      if f["predicate_term_id"] == "has_state" and f["status"] == "active"]
            assert states == ["created"], "事件→descriptor→admit 落 has_state"
        finally:
            bridge.stop()
        assert not (bus._subscribers.get("kb.order.paid")), "stop 退订"

    def test_unmappedEventZeroWrites(self, kb, monkeypatch):
        s, _registry, _reg = kb
        monkeypatch.setenv(BRIDGE_ENV, "1")
        from neurova.core.event_bus import resolveEventBus

        bus = resolveEventBus()
        bridge = StateEventBridge(s)
        bridge.start()
        try:
            bus.publish("kb.order.unmapped", {"order_label": "订单EV2",
                                              "new_state": "paid"}, source="test")
            bus.publish("kb.order.paid", {"order_label": "订单EV2",
                                          "new_state": "ghost_state"}, source="test")
            hits = [f for f in s.factsForSubject(s.resolveSubjectKey("default", "订单EV2"))]
            assert hits == [], "未映射事件与闭集外状态零写入"
        finally:
            bridge.stop()

    def test_illegalTransitionRejectedNoRetry(self, kb, monkeypatch):
        """迁移约束继承（admission 校验自动咬合）：非法迁移如实拒、不重试风暴。"""
        s, registry, _reg = kb
        registry.register("paid", "relation")
        monkeypatch.setenv(BRIDGE_ENV, "1")
        gate = productionAdmissionGate(s)
        content = "订单EV3 is_a orders"
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="订单EV3", predicateTermId="is_a",
            objectTerm="orders", content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))
        registry.assignSubjectType(s.resolveSubjectKey("default", "订单EV3"), "orders")
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="订单EV3", predicateTermId="has_state",
            objectTerm="created", content="订单EV3 has_state created",
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test",
                         "statementText": "订单EV3 has_state created"}]))
        from neurova.core.event_bus import resolveEventBus

        bus = resolveEventBus()
        bridge = StateEventBridge(s)
        bridge.start()
        try:
            for _ in range(5):
                bus.publish("kb.order.paid", {"order_label": "订单EV3",
                                              "new_state": "created"}, source="test")
            # created→created 不在 transitions：每次都拒且不重试（fail-closed 留名）
            key = s.resolveSubjectKey("default", "订单EV3")
            states = [f["object_term"] for f in s.factsForSubject(key)
                      if f["predicate_term_id"] == "has_state"
                      and f["status"] == "active"]
            assert states == ["created"], "created→created 非法迁移：每次如实拒且不重试"
        finally:
            bridge.stop()

    def test_moduleNameStable(self):
        assert BRIDGE_MODULE == "kb_state_event_bridge"
