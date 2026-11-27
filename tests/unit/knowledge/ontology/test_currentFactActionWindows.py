# -*- coding: utf-8 -*-
"""P2-05 独立动作/溯因分组：当前事实窗口、边界与租户/agent 隔离。"""

from __future__ import annotations

import asyncio
import datetime

import pytest

from neurova.knowledge.foundation import knowledge_facts
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.abduction import explainGoal
from neurova.knowledge.ontology.action_runtime import (
    ActionPreconditionError,
    evaluatePrecondition,
    executeAction,
)
from neurova.knowledge.ontology.conflict_advice import adviseConflict
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.state_machine_registry import StateMachineRegistry
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.state_event_bridge import BRIDGE_ENV, StateEventBridge

NOW = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
PAST = (NOW - datetime.timedelta(days=2)).isoformat()
RECORDED = (NOW - datetime.timedelta(days=1)).isoformat()
FUTURE = (NOW + datetime.timedelta(days=1)).isoformat()
AGENT = "agent-a"
OTHER_AGENT = "agent-b"
TENANT = "default"
OTHER_TENANT = "tenant-b"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge_facts, "_now", lambda: NOW.isoformat())
    instance = KnowledgeFactStore(str(tmp_path / "current_fact_actions.db"))
    yield instance
    instance.close()


def _subject(store, label="设备A", *, agentId=AGENT, tenantId=TENANT,
             typeTermId=None):
    return store.upsertSubject(agentId, label, typeTermId=typeTermId,
                               tenantId=tenantId)


def _fact(store, subjectKey, predicate, objectTerm, *, agentId=AGENT,
          tenantId=TENANT, recordedAt=RECORDED, validFrom=None, validUntil=None,
          confidence=None):
    return store.upsertFact(
        agentId, subjectKey, predicate, objectTerm,
        "%s %s %s" % (predicate, objectTerm, agentId),
        recordedAt=recordedAt, validFrom=validFrom, validUntil=validUntil,
        tenantId=tenantId, confidence=confidence,
    )


def _preconditionAction(expected):
    return {
        "action_id": "current_fact_action",
        "precondition": {"facts": [{
            "predicate": "has_state", "subjectParam": "subject",
            "op": "equals", "value": expected,
        }]},
    }


class RecordingExecutor:
    """记录真实动作运行时调用；不伪装业务对象。"""

    def __init__(self):
        self.calls = []

    async def execute(self, toolName, params):
        self.calls.append((toolName, dict(params)))
        return {"success": True, "result": "ok"}


class TestAbductionCurrentFacts:
    @pytest.mark.parametrize(
        "objectTerm,recordedAt,validFrom,validUntil,visible",
        [
            ("expired", NOW.isoformat(), None, NOW.isoformat(), False),
            ("future", RECORDED, FUTURE, None, False),
            ("current", RECORDED, NOW.isoformat(), FUTURE, True),
            ("starts-now", RECORDED, NOW.isoformat(), None, True),
            ("recorded-now", NOW.isoformat(), None, None, True),
            ("recorded-future", FUTURE, None, None, False),
            ("from-overrides-recorded", FUTURE, PAST, None, True),
        ],
        ids=["expired", "future", "current", "starts-now", "recorded-now",
             "recorded-future", "from-overrides-recorded"],
    )
    def test_evidenceUsesCurrentFactWindow(
            self, store, objectTerm, recordedAt, validFrom, validUntil, visible):
        key = _subject(store)
        factId = _fact(store, key, "version", objectTerm, recordedAt=recordedAt,
                       validFrom=validFrom, validUntil=validUntil)

        result = explainGoal(store, "设备A", "version", objectTerm,
                             agentId=AGENT, tenantId=TENANT)

        assert result["satisfied"] is visible
        evidence = {step["fact_id"] for step in result["steps"]
                    if step.get("kind") == "fact"}
        assert (factId in evidence) is visible

    def test_ruleExpansionUsesOnlyCurrentPremises(self, store):
        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "premise", "kind": "relation"},
            {"termId": "conclusion", "kind": "relation"},
        ])
        engine = ForwardChainingEngine(store)
        engine.registerRule(
            "rule_current", "conclusion",
            [{"atom": "premise", "subject": "S", "object": "O"}],
            headSubjectVar="S", tenantId=TENANT)
        key = _subject(store)
        current = _fact(store, key, "premise", "current",
                        validFrom=NOW.isoformat(), validUntil=FUTURE)
        _fact(store, key, "premise", "expired", validUntil=NOW.isoformat())
        _fact(store, key, "premise", "future", validFrom=FUTURE)

        proved = explainGoal(store, "设备A", "conclusion", "current",
                             agentId=AGENT, tenantId=TENANT)
        expired = explainGoal(store, "设备A", "conclusion", "expired",
                              agentId=AGENT, tenantId=TENANT)
        future = explainGoal(store, "设备A", "conclusion", "future",
                             agentId=AGENT, tenantId=TENANT)

        assert proved["satisfied"] is True
        assert current in {step.get("fact_id") for step in proved["steps"]}
        assert expired["satisfied"] is False
        assert future["satisfied"] is False

    def test_agentAndTenantCannotSupplyEvidence(self, store):
        _subject(store)
        _subject(store, agentId=OTHER_AGENT)
        _subject(store, tenantId=OTHER_TENANT)
        mine = _fact(store, store.resolveSubjectKey(AGENT, "设备A", TENANT),
                     "version", "mine")
        _fact(store, store.resolveSubjectKey(OTHER_AGENT, "设备A", TENANT),
              "version", "other-agent", agentId=OTHER_AGENT)
        _fact(store, store.resolveSubjectKey(AGENT, "设备A", OTHER_TENANT),
              "version", "other-tenant", tenantId=OTHER_TENANT)

        for value in ("mine", "other-agent", "other-tenant"):
            result = explainGoal(store, "设备A", "version", value,
                                 agentId=AGENT, tenantId=TENANT)
            assert result["satisfied"] is (value == "mine")
            evidence = {step.get("fact_id") for step in result["steps"]}
            assert (mine in evidence) is (value == "mine")


class TestActionCurrentFacts:
    @pytest.mark.parametrize(
        "objectTerm,recordedAt,validFrom,validUntil,allowed",
        [
            ("expired", NOW.isoformat(), None, NOW.isoformat(), False),
            ("future", RECORDED, FUTURE, None, False),
            ("current", RECORDED, NOW.isoformat(), FUTURE, True),
            ("starts-now", RECORDED, NOW.isoformat(), None, True),
            ("recorded-future", FUTURE, None, None, False),
        ],
        ids=["expired", "future", "current", "starts-now", "recorded-future"],
    )
    def test_preconditionUsesCurrentFactWindow(
            self, store, objectTerm, recordedAt, validFrom, validUntil, allowed):
        key = _subject(store)
        _fact(store, key, "has_state", objectTerm, recordedAt=recordedAt,
              validFrom=validFrom, validUntil=validUntil)
        action = _preconditionAction(objectTerm)

        if allowed:
            evaluatePrecondition(action, {"subject": "设备A"}, store,
                                 AGENT, TENANT)
        else:
            with pytest.raises(ActionPreconditionError, match="前置不满足"):
                evaluatePrecondition(action, {"subject": "设备A"}, store,
                                     AGENT, TENANT)

    def test_preconditionCannotBorrowCrossScopeState(self, store):
        _subject(store)
        _subject(store, agentId=OTHER_AGENT)
        _subject(store, tenantId=OTHER_TENANT)
        _fact(store, store.resolveSubjectKey(OTHER_AGENT, "设备A", TENANT),
              "has_state", "current", agentId=OTHER_AGENT)
        _fact(store, store.resolveSubjectKey(AGENT, "设备A", OTHER_TENANT),
              "has_state", "current", tenantId=OTHER_TENANT)
        key = store.resolveSubjectKey(AGENT, "设备A", TENANT)
        _fact(store, key, "has_state", "expired", validUntil=NOW.isoformat())
        action = _preconditionAction("current")

        with pytest.raises(ActionPreconditionError, match="前置不满足"):
            evaluatePrecondition(action, {"subject": "设备A"}, store,
                                 AGENT, TENANT)

        _fact(store, key, "has_state", "current",
              validFrom=NOW.isoformat(), validUntil=FUTURE)
        evaluatePrecondition(action, {"subject": "设备A"}, store,
                             AGENT, TENANT)

    def test_stateChangeReadbackUsesCurrentFactWindow(self, store):
        registry = OntologyTermRegistry(store)
        registry.register("orders", "concept")
        registry.register("has_state", "relation", cardinality=1)
        StateMachineRegistry(store).register(
            "orders", tenantId=TENANT, states=["current"], transitions=[],
            initialState="current")
        key = _subject(store, "订单S1", typeTermId="orders")
        _fact(store, key, "has_state", "current", recordedAt=PAST,
              validFrom=NOW.isoformat(), validUntil=FUTURE)
        _fact(store, key, "has_state", "future", recordedAt=RECORDED,
              validFrom=FUTURE)
        _fact(store, key, "has_state", "expired", recordedAt=NOW.isoformat(),
              validUntil=NOW.isoformat())
        action = {
            "action_id": "reject_invalid_state", "bound_tool": "noop_tool",
            "state_change": {"subjectParam": "order", "toState": "invalid"},
        }
        executor = RecordingExecutor()

        receipt = asyncio.run(executeAction(
            action, {"order": "订单S1"}, executor, store, AGENT,
            tenantId=TENANT))

        assert executor.calls == [("noop_tool", {"order": "订单S1"})]
        assert receipt["executed"] is True
        assert receipt["state_change"]["ok"] is False
        assert receipt["state_change"]["detail"]
        assert receipt["state_change"]["current_state"] == "current"

    def test_stateChangeReadbackIsTenantAndAgentScoped(self, store):
        registry = OntologyTermRegistry(store)
        registry.register("orders", "concept")
        registry.register("has_state", "relation", cardinality=1)
        StateMachineRegistry(store).register(
            "orders", tenantId=TENANT, states=["current"], transitions=[],
            initialState="current")
        key = _subject(store, "订单S2", typeTermId="orders")
        otherAgentKey = _subject(store, "订单S2", agentId=OTHER_AGENT,
                                 typeTermId="orders")
        otherTenantKey = _subject(store, "订单S2", tenantId=OTHER_TENANT,
                                  typeTermId="orders")
        _fact(store, key, "has_state", "current", recordedAt=PAST,
              validFrom=NOW.isoformat(), validUntil=FUTURE)
        _fact(store, otherAgentKey, "has_state", "other-agent",
              agentId=OTHER_AGENT, recordedAt=NOW.isoformat(),
              validUntil=NOW.isoformat())
        _fact(store, otherTenantKey, "has_state", "other-tenant",
              tenantId=OTHER_TENANT, recordedAt=RECORDED, validFrom=FUTURE)
        action = {
            "action_id": "reject_invalid_state", "bound_tool": "noop_tool",
            "state_change": {"subjectParam": "order", "toState": "invalid"},
        }

        receipt = asyncio.run(executeAction(
            action, {"order": "订单S2"}, RecordingExecutor(), store, AGENT,
            tenantId=TENANT))

        assert receipt["state_change"]["ok"] is False
        assert receipt["state_change"]["current_state"] == "current"


class TestConflictAdviceCurrentFacts:
    def test_candidatesAndStrategyUseCurrentWindow(self, store):
        key = _subject(store, "订单C1")
        high = _fact(store, key, "risk", "high", agentId="source-a",
                     confidence=0.9)
        low = _fact(store, key, "risk", "low", agentId="source-b",
                    confidence=0.8)
        starts = _fact(store, key, "risk", "starts", confidence=0.1,
                       validFrom=NOW.isoformat())
        _fact(store, key, "risk", "expired", confidence=0.99,
              recordedAt=NOW.isoformat(), validUntil=NOW.isoformat())
        _fact(store, key, "risk", "future", confidence=0.98,
              recordedAt=RECORDED, validFrom=FUTURE)
        _fact(store, key, "risk", "ended", confidence=0.97,
              recordedAt=RECORDED, validUntil=NOW.isoformat())

        before = store.queryReadOnly(
            "SELECT * FROM knowledge_facts ORDER BY fact_id")
        result = adviseConflict(store, TENANT, key, "risk")

        assert result["strategy"] == "highest_confidence"
        assert result["suggestedValue"] == "high"
        assert result["evidence"] == [high]
        assert {candidate["factId"] for candidate in result["candidates"]} == {
            high, low, starts}
        assert store.queryReadOnly(
            "SELECT * FROM knowledge_facts ORDER BY fact_id") == before

    def test_otherTenantCannotCreateConflict(self, store):
        key = _subject(store, "订单C2")
        mine = _fact(store, key, "risk", "mine", confidence=0.9)
        _fact(store, key, "risk", "other", tenantId=OTHER_TENANT,
              confidence=0.1)

        result = adviseConflict(store, TENANT, key, "risk")

        assert result["strategy"] == "none"
        assert result["suggestedValue"] == "mine"
        assert result["evidence"] == [mine]


class TestStateEventCurrentFacts:
    def _registerMachine(self, store, eventName):
        registry = OntologyTermRegistry(store)
        registry.register("orders", "concept")
        registry.register("has_state", "relation", cardinality=1)
        StateMachineRegistry(store).register(
            "orders", tenantId=TENANT, states=["created", "paid", "shipped"],
            transitions=[{"from": "created", "to": "paid"},
                         {"from": "paid", "to": "shipped"}],
            initialState="created",
            eventBindings=[{
                "eventName": eventName, "subjectField": "order_label",
                "stateField": "new_state", "agentId": AGENT, "tenantId": TENANT,
            }])

    def test_eventTransitionIgnoresExpiredAndFutureStates(
            self, store, monkeypatch):
        eventName = "kb.order.current-window"
        self._registerMachine(store, eventName)
        key = _subject(store, "订单EV1", typeTermId="orders")
        _fact(store, key, "has_state", "created", recordedAt=PAST,
              validFrom=NOW.isoformat(), validUntil=FUTURE)
        _fact(store, key, "has_state", "future", recordedAt=RECORDED,
              validFrom=FUTURE)
        _fact(store, key, "has_state", "expired", recordedAt=NOW.isoformat(),
              validUntil=NOW.isoformat())
        monkeypatch.setenv(BRIDGE_ENV, "1")
        from neurova.core.event_bus import resolveEventBus

        bridge = StateEventBridge(store)
        bridge.start()
        try:
            resolveEventBus().publish(
                eventName, {"order_label": "订单EV1", "new_state": "paid"},
                source="test")
        finally:
            bridge.stop()

        assert [fact["object_term"] for fact in store.factsForSubject(key)
                if fact["predicate_term_id"] == "has_state"] == ["paid"]

    def test_eventCannotTransitionFromNonCurrentState(self, store, monkeypatch):
        eventName = "kb.order.no-current-window"
        self._registerMachine(store, eventName)
        key = _subject(store, "订单EV2", typeTermId="orders")
        _fact(store, key, "has_state", "created", recordedAt=RECORDED,
              validFrom=FUTURE)
        _fact(store, key, "has_state", "expired", recordedAt=NOW.isoformat(),
              validUntil=NOW.isoformat())
        monkeypatch.setenv(BRIDGE_ENV, "1")
        from neurova.core.event_bus import resolveEventBus

        bridge = StateEventBridge(store)
        bridge.start()
        try:
            resolveEventBus().publish(
                eventName, {"order_label": "订单EV2", "new_state": "paid"},
                source="test")
        finally:
            bridge.stop()

        assert [fact["object_term"] for fact in store.factsForSubject(key)
                if fact["predicate_term_id"] == "has_state"] == []
        assert store.queryReadOnly(
            "SELECT COUNT(*) AS n FROM knowledge_facts"
            " WHERE subject_key = ? AND predicate_term_id = 'has_state'",
            (key,))[0]["n"] == 2

    @pytest.mark.parametrize(
        "agentId,tenantId",
        [(OTHER_AGENT, TENANT), (AGENT, OTHER_TENANT)],
        ids=["other-agent", "other-tenant"],
    )
    def test_eventTypeGuardIsTenantAndAgentScoped(
            self, store, monkeypatch, agentId, tenantId):
        eventName = "kb.order.scope-window"
        self._registerMachine(store, eventName)
        key = _subject(store, "订单EV3", agentId=agentId, tenantId=tenantId,
                       typeTermId="orders")
        monkeypatch.setenv(BRIDGE_ENV, "1")
        from neurova.core.event_bus import resolveEventBus

        bridge = StateEventBridge(store)
        bridge.start()
        try:
            resolveEventBus().publish(
                eventName, {"order_label": "订单EV3", "new_state": "paid"},
                source="test")
        finally:
            bridge.stop()

        assert store.queryReadOnly(
            "SELECT COUNT(*) AS n FROM knowledge_facts"
            " WHERE subject_key = ? AND predicate_term_id = 'has_state'",
            (key,))[0]["n"] == 0
