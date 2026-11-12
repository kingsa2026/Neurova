# -*- coding: utf-8 -*-
"""W4 动作 state_change（specs/2026-11-12 §6）：执行成功后经 admission 写
has_state（W3 迁移约束自动继承——非法迁移→动作回执诚实失败）；
工具失败→零状态写；回执带 fact_id/溯源。
"""

from __future__ import annotations

import asyncio

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.action_registry import ActionRegistry
from neurova.knowledge.ontology.action_runtime import executeAction
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


class FakeExecutor:
    def __init__(self, result=None):
        self.calls = []
        self._result = result or {"success": True, "result": "ok"}

    async def execute(self, tool_name, params):
        self.calls.append((tool_name, params))
        return self._result


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("orders", "concept", label="订单")
    registry.register("has_state", "relation", cardinality=1)
    registry.register("stock_level", "relation")
    # orders 挂真状态机（supersede 只在机器管辖下工作——W3 设计口径）
    from neurova.knowledge.ontology.state_machine_registry import StateMachineRegistry

    StateMachineRegistry(s).register(
        termId="orders", tenantId="default",
        states=["created", "paid", "shipped"],
        transitions=[{"from": "created", "to": "paid"},
                     {"from": "paid", "to": "shipped"}],
        initialState="created")
    gate = productionAdmissionGate(s)
    # 主体：已挂 orders 类型＋当前状态 paid
    content = "订单S1 is_a orders"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="订单S1", predicateTermId="is_a",
        objectTerm="orders", content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))
    registry.assignSubjectType(s.resolveSubjectKey("default", "订单S1"), "orders")
    # 初始状态 → 合法迁移到 paid（机器管辖下 paid 不能直写为首状态）
    content2 = "订单S1 has_state created"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="订单S1", predicateTermId="has_state",
        objectTerm="created", content=content2,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content2}]))
    content3 = "订单S1 has_state paid（created→paid 迁移）"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="订单S1", predicateTermId="has_state",
        objectTerm="paid", content=content3,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content3}]))
    yield s, registry
    s.close()


class FakeMachineRegistry:
    def __init__(self):
        self._machine = {"term_id": "orders", "enabled": True,
                         "states": ["created", "paid", "shipped"],
                         "transitions": [{"from": "paid", "to": "shipped"}],
                         "initial_state": "created"}

    def get(self, termId, tenantId="default"):
        return self._machine if termId == "orders" else None

    def currentState(self, agentId, subjectKey, tenantId="default"):
        facts = [f for f in self._store_facts(subjectKey)
                 if f.get("predicate_term_id") == "has_state"
                 and f.get("status") == "active"]
        return str(facts[0]["object_term"]) if facts else ""

    def _store_facts(self, subjectKey):
        raise NotImplementedError


def _registerShip(kb):
    s, registry = kb
    reg = ActionRegistry(s)
    row = reg.upsert(
        actionId="ship_order", label="发货",
        precondition={"facts": [{"predicate": "has_state", "subjectParam": "order",
                                 "op": "equals", "value": "paid"}]},
        impact=["has_state"],
        stateChange={"subjectParam": "order", "toState": "shipped"},
        boundTool="noop_tool", riskTier="medium",
        registeredTools=["noop_tool"])
    return reg, row


class TestStateChange:
    def test_successWritesHasStateViaAdmission(self, kb):
        s, _registry = kb
        _reg, row = _registerShip(kb)
        executor = FakeExecutor()
        receipt = asyncio.run(executeAction(row, {"order": "订单S1"}, executor, store=s,
                                            agentId="default", tenantId="default",
                                            machineRegistry=None))
        assert receipt["state_change"]["fact_id"], "回执带 fact_id"
        key = s.resolveSubjectKey("default", "订单S1")
        states = [f["object_term"] for f in s.factsForSubject(key)
                  if f["predicate_term_id"] == "has_state" and f["status"] == "active"]
        assert states == ["shipped"], "paid 旧值经 W3 supersede 退场，shipped 唯一"
        assert states != ["paid", "shipped"]

    def test_toolFailureMeansZeroStateWrite(self, kb):
        s, _registry = kb
        _reg, row = _registerShip(kb)
        executor = FakeExecutor(result={"error": "工具炸了"})
        receipt = asyncio.run(executeAction(row, {"order": "订单S1"}, executor, store=s,
                                            agentId="default", tenantId="default",
                                            machineRegistry=None))
        assert receipt["executed"] is False
        assert "state_change" not in receipt or not receipt["state_change"], \
            "工具失败零状态写"
        key = s.resolveSubjectKey("default", "订单S1")
        states = [f["object_term"] for f in s.factsForSubject(key)
                  if f["predicate_term_id"] == "has_state" and f["status"] == "active"]
        assert states == ["paid"], "状态未被推进"

    def test_illegalTransitionHonestFailure(self, kb):
        """state_change 目标不在迁移闭集 → admission 拒 → 动作回执诚实失败
        （工具已执行——执行与状态写是两段，回执如实呈现）。"""
        s, _registry = kb
        reg = ActionRegistry(s)
        row = reg.upsert(
            actionId="jump_order", label="跳变",
            stateChange={"subjectParam": "order", "toState": "created"},
            boundTool="noop_tool", registeredTools=["noop_tool"])
        executor = FakeExecutor()
        receipt = asyncio.run(executeAction(row, {"order": "订单S1"}, executor, store=s,
                                            agentId="default", tenantId="default",
                                            machineRegistry=None))
        assert receipt["executed"] is True
        assert receipt["state_change"]["ok"] is False, "非法迁移诚实失败"
        assert receipt["state_change"].get("detail")
        key = s.resolveSubjectKey("default", "订单S1")
        states = [f["object_term"] for f in s.factsForSubject(key)
                  if f["predicate_term_id"] == "has_state" and f["status"] == "active"]
        assert states == ["paid"], "状态未被非法迁移改写"

    def test_unboundToolRejectedAtRegistration(self, kb):
        """bound_tool 悬空拒既有判据不动。"""
        s, _registry = kb
        reg = ActionRegistry(s)
        with pytest.raises(ValueError, match="悬空"):
            reg.upsert(actionId="a9", label="x", boundTool="ghost_tool",
                       registeredTools=["noop_tool"])
