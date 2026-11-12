# -*- coding: utf-8 -*-
"""W4 动作前置条件（specs/2026-11-12 §6）。

precondition＝事实/状态谓词存在性＋函数比较（复用 function_eval 只读求值）；
不满足显式拒且**不触工具**（假 executor 计数断言）；bound_tool 悬空拒既有判据
不动；动作语义三段（precondition/impact/state_change）是数据（v45 三列）。
"""

from __future__ import annotations

import asyncio

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.action_registry import ActionRegistry
from neurova.knowledge.ontology.action_runtime import (
    ActionPreconditionError,
    executeAction,
)
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


class FakeExecutor:
    """execute 契约假件：记录调用并返回可编程结果。"""

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
    registry.register("stock_low", "relation")
    registry.register("stock_level", "relation")
    yield s, registry
    s.close()


def _registerAction(kb, **overrides):
    s, registry = kb
    reg = ActionRegistry(s)
    base = dict(
        actionId="ship_order", label="发货",
        precondition={"facts": [{"predicate": "has_state", "subjectParam": "order",
                                 "op": "equals", "value": "paid"}]},
        impact=["has_state"],
        stateChange={"subjectParam": "order", "toState": "shipped"},
        boundTool="noop_tool", riskTier="medium",
        registeredTools=["noop_tool"])
    base.update(overrides)
    kwargs = dict(base)
    kwargs["precondition"] = kwargs.pop("precondition")
    kwargs["impact"] = kwargs.pop("impact")
    kwargs["stateChange"] = kwargs.pop("stateChange")
    return reg, reg.upsert(**kwargs)


class FakeStateMachineRegistry:
    """状态机注册表替身：orders 挂 created→paid→shipped 机器。"""

    def __init__(self, states, transitions):
        self._machine = {"term_id": "orders", "enabled": True,
                         "states": states, "transitions": transitions,
                         "initial_state": states[0] if states else ""}

    def get(self, termId, tenantId="default"):
        if termId == "orders":
            return self._machine
        return None

    def currentState(self, agentId, subjectKey, tenantId="default"):
        return ""


class TestPrecondition:
    def test_unsatisfiedPreconditionRejectsWithoutToolCall(self, kb):
        """前置不满足：显式拒且 ToolExecutor 零调用（计数断言）。"""
        s, registry = kb
        _reg, row = _registerAction(kb)
        executor = FakeExecutor()
        with pytest.raises(ActionPreconditionError) as excinfo:
            asyncio.run(executeAction(row, {"order": "订单X"}, executor, store=s,
                                      agentId="default", tenantId="default",
                                      machineRegistry=FakeStateMachineRegistry(
                                          ["paid", "shipped"], [])))
        assert "paid" in str(excinfo.value)
        assert executor.calls == [], "前置不满足不得触工具"

    def test_satisfiedPreconditionCallsToolOnce(self, kb):
        s, registry = kb
        _reg, row = _registerAction(kb)
        # 主体 has_state=paid 事实在库（前置满足）
        from neurova.knowledge.foundation.admission import (
            AdmissionRequest, productionAdmissionGate,
        )

        gate = productionAdmissionGate(s)
        content = "订单X has_state paid"
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="订单X", predicateTermId="has_state",
            objectTerm="paid", content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))
        executor = FakeExecutor()
        receipt = asyncio.run(executeAction(row, {"order": "订单X"}, executor, store=s,
                                            agentId="default", tenantId="default",
                                            machineRegistry=FakeStateMachineRegistry(
                                                ["created", "paid", "shipped"],
                                                [{"from": "paid", "to": "shipped"}])))
        assert len(executor.calls) == 1
        assert executor.calls[0][0] == "noop_tool"
        assert receipt["impact"] == ["has_state"], "回执含 impact 声明"

    def test_exprPreconditionFunctionEval(self, kb):
        """函数比较前置：复用 function_eval 只读求值（不满足即拒）。"""
        s, registry = kb
        _reg, row = _registerAction(kb, precondition={
            "expr": 'count(facts("stock_low")) > 0'})
        executor = FakeExecutor()
        with pytest.raises(ActionPreconditionError):
            asyncio.run(executeAction(row, {}, executor, store=s, agentId="default",
                                      tenantId="default", machineRegistry=None))
        assert executor.calls == []


class TestRegistrationShape:
    def test_unknownPreconditionPredicateRejected(self, kb):
        """precondition 引用的谓词不在注册表 → 登记即拒（B-10 同款）。"""
        s, _registry = kb
        reg = ActionRegistry(s)
        with pytest.raises(ValueError, match="注册表"):
            reg.upsert(actionId="a1", label="x", boundTool="noop_tool",
                       registeredTools=["noop_tool"],
                       precondition={"facts": [{"predicate": "ghost_pred"}]})

    def test_stateChangeRequiresBothFields(self, kb):
        s, _registry = kb
        reg = ActionRegistry(s)
        with pytest.raises(ValueError, match="state_change"):
            reg.upsert(actionId="a2", label="x", boundTool="noop_tool",
                       registeredTools=["noop_tool"],
                       stateChange={"subjectParam": "order"})

    def test_threeColumnsRoundTrip(self, kb):
        s, registry = kb
        reg, row = _registerAction(kb)
        assert row["precondition"]["facts"][0]["predicate"] == "has_state"
        assert row["impact"] == ["has_state"]
        assert row["state_change"]["toState"] == "shipped"
