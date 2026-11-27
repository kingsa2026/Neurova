# -*- coding: utf-8 -*-
"""P2-05：函数与 Rete 推理只消费固定时刻仍有效的事实。"""

from __future__ import annotations

import datetime

import pytest

from neurova.knowledge.foundation import knowledge_facts
from neurova.knowledge.foundation.admission import productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology import function_eval, rule_engine
from neurova.knowledge.ontology.function_engine import FunctionEngine
from neurova.knowledge.ontology.function_eval import SelectorCapError, makeSelectorRunner
from neurova.knowledge.ontology.function_registry import FunctionRegistry
from neurova.knowledge.ontology.rete_network import _AlphaIndex
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

NOW = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
PAST = NOW - datetime.timedelta(days=1)
FUTURE = NOW + datetime.timedelta(days=1)
AGENT = "default"
TENANT = "tenant-current"
TERMS = ("measure", "total", "linked", "reachable", "blocked")


@pytest.fixture(autouse=True)
def fixedNow(monkeypatch):
    monkeypatch.setattr(knowledge_facts, "_now", lambda: NOW.isoformat())
    monkeypatch.setattr(rule_engine, "_now", lambda: NOW.isoformat())


@pytest.fixture
def store(tmp_path):
    instance = _newStore(tmp_path / "current.db")
    yield instance
    instance.close()


def _newStore(path):
    instance = KnowledgeFactStore(str(path))
    OntologyTermRegistry(instance).registerMany([
        {"termId": term, "kind": "relation"} for term in TERMS
    ], tenantId=TENANT)
    return instance


def _engine(store):
    return ForwardChainingEngine(
        store, gateFactory=lambda st: productionAdmissionGate(
            st, toolVersion="current-fact-reasoning-test"))


def _fact(store, label, predicate, obj, *, validFrom=None, validUntil=None):
    subjectKey = store.upsertSubject(AGENT, label, tenantId=TENANT)
    return store.upsertFact(
        AGENT, subjectKey, predicate, obj,
        "%s %s %s" % (label, predicate, obj),
        validFrom=validFrom, validUntil=validUntil, tenantId=TENANT)


def test_functionRuleDiscoversAndAggregatesOnlyCurrentFacts(store):
    FunctionRegistry(store).register(
        functionId="current_total", tenantId=TENANT,
        exprText='sum(facts("measure", {"subject_key": "$subject"}))',
        outputPredicate="total", inputBindings={"subject": "subject"},
        materialization="enforce")
    _fact(store, "当前仓库", "measure", "2", validFrom=NOW, validUntil=FUTURE)
    _fact(store, "当前仓库", "measure", "100", validUntil=PAST)
    _fact(store, "当前仓库", "measure", "200", validFrom=FUTURE)
    _fact(store, "仅过期仓库", "measure", "300", validUntil=PAST)
    _fact(store, "仅未来仓库", "measure", "400", validFrom=FUTURE)
    engine = FunctionEngine(
        store, gateFactory=lambda st: productionAdmissionGate(
            st, toolVersion="current-fact-function-test"))

    assert engine._subjectsFor(AGENT, "measure", TENANT) == ["当前仓库"]
    produced = engine.fireFor(AGENT, "measure", TENANT)

    assert len(produced) == 1
    conclusion = store.fact(produced[0])
    assert conclusion["qualifier"]["value"] == 2.0


def test_selectorCapCountsOnlyCurrentFacts(store, monkeypatch):
    currentId = _fact(store, "当前仓库", "measure", "2", validFrom=NOW)
    _fact(store, "当前仓库", "measure", "100", validUntil=PAST)
    _fact(store, "当前仓库", "measure", "200", validFrom=FUTURE)
    monkeypatch.setattr(function_eval, "SELECTOR_ROW_CAP", 1)
    runner = makeSelectorRunner(store, agentId=AGENT, tenantId=TENANT)

    result = runner({"predicate": "measure"}, {})

    assert result.factIds == [currentId]
    assert result.values == [2.0]
    assert result.matchedCount == 1

    _fact(store, "当前仓库", "measure", "3", validFrom=NOW)
    with pytest.raises(SelectorCapError):
        runner({"predicate": "measure"}, {})


def test_reteAlphaSnapshotExcludesNonCurrentFacts(store):
    engine = _engine(store)
    rule = engine.registerRule(
        "current_link", "reachable",
        [{"atom": "linked", "subject": "S", "object": "O"}],
        headSubjectVar="S", materialization="enforce", tenantId=TENANT)
    currentId = _fact(store, "当前甲", "linked", "当前乙", validFrom=NOW)
    _fact(store, "到期甲", "linked", "到期乙", validUntil=NOW)
    _fact(store, "未来甲", "linked", "未来乙", validFrom=FUTURE)

    index = _AlphaIndex(engine, AGENT, [rule], TENANT)

    assert [fact["fact_id"] for fact in index.byPredicate("linked")] == [currentId]


def test_reasoningStrategiesHaveIdenticalCurrentFactConclusions(tmp_path):
    observed = {}
    for strategy in ("full_replay", "rete", "rete_network"):
        store = _newStore(tmp_path / ("%s.db" % strategy))
        try:
            engine = _engine(store)
            engine.registerRule(
                "current_reachable", "reachable",
                [{"atom": "linked", "subject": "S", "object": "O"},
                 {"not": "blocked", "subject": "S", "object": "O"}],
                headSubjectVar="S", materialization="enforce", tenantId=TENANT)
            _fact(store, "当前甲", "linked", "当前乙", validFrom=NOW, validUntil=FUTURE)
            _fact(store, "当前甲", "blocked", "当前乙", validUntil=PAST)
            _fact(store, "待定甲", "linked", "待定乙", validFrom=NOW)
            _fact(store, "待定甲", "blocked", "待定乙", validFrom=FUTURE)
            _fact(store, "过期甲", "linked", "过期乙", validUntil=NOW)
            _fact(store, "未来甲", "linked", "未来乙", validFrom=FUTURE)
            engine.setEvaluationStrategy(strategy)

            engine.fireAll(agentId=AGENT, tenantId=TENANT)

            observed[strategy] = {
                (fact["canonical_label"], fact["object_term"])
                for fact in store.searchableFacts(agentId=AGENT, tenantId=TENANT)
                if fact["predicate_term_id"] == "reachable"
                and fact["qualifier"].get("derived_by") == "current_reachable"
            }
        finally:
            store.close()

    expected = {("当前甲", "当前乙"), ("待定甲", "待定乙")}
    assert observed["full_replay"] == expected
    assert observed["rete"] == observed["full_replay"]
    assert observed["rete_network"] == observed["full_replay"]
