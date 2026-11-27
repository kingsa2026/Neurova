# -*- coding: utf-8 -*-
"""当前事实可见性：status 是生命周期，valid 窗口决定此刻是否可见。"""

from __future__ import annotations

import datetime
import json

import pytest

from neurova.cognitive_layers.memory_layer.modules.tkg_module import TKGModule
from neurova.knowledge.foundation import knowledge_facts
from neurova.knowledge.foundation.admission import productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.temporal_facts import TemporalFactReader
from neurova.knowledge.ontology.backward_chaining import proveGoal
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.state_machine_registry import StateMachineRegistry
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

NOW = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
PAST = (NOW - datetime.timedelta(days=1)).isoformat()
FUTURE = (NOW + datetime.timedelta(days=1)).isoformat()


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge_facts, "_now", lambda: NOW.isoformat())
    instance = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield instance
    instance.close()


def _subject(store, label="神经瓦"):
    return store.upsertSubject("default", label)


def _fact(store, key, predicate, obj, *, validFrom=None, validUntil=None, qualifier=None):
    return store.upsertFact(
        "default", key, predicate, obj, "%s %s %s" % (predicate, obj, "正文"),
        validFrom=validFrom, validUntil=validUntil, qualifier=qualifier,
    )


def _windowFacts(store, predicate="version"):
    key = _subject(store)
    return {
        "expired": _fact(store, key, predicate, "expired", validUntil=PAST),
        "future": _fact(store, key, predicate, "future", validFrom=FUTURE),
        "current": _fact(store, key, predicate, "current", validFrom=NOW.isoformat(),
                         validUntil=FUTURE),
    }


class TestCurrentFactPredicate:
    def test_store_read_surfaces_share_the_same_current_window(self, store):
        ids = _windowFacts(store)
        key = store.resolveSubjectKey("default", "神经瓦")

        assert {row["fact_id"] for row in store.factsForSubject(key)} == {ids["current"]}
        assert {row["fact_id"] for row in store.searchableFacts()} == {ids["current"]}
        assert {row["fact_id"] for row in store.latestFactsByPredicate("default", "version")} == {
            ids["current"]}

    def test_cardinality_reads_only_current_facts(self, store):
        ids = _windowFacts(store)
        key = store.resolveSubjectKey("default", "神经瓦")
        registry = OntologyTermRegistry(store)

        assert [row["fact_id"] for row in registry.activeFactsForPredicate(
            "default", key, "version")] == [ids["current"]]

    def test_state_machine_reads_only_current_state(self, store):
        ids = _windowFacts(store, "has_state")
        key = store.resolveSubjectKey("default", "神经瓦")

        assert StateMachineRegistry(store).currentState("default", key) == "current"
        assert ids["expired"] != ids["current"] and ids["future"] != ids["current"]

    def test_temporal_reader_keeps_boundary_consistent(self, store):
        ids = _windowFacts(store)
        atStart = _fact(store, store.resolveSubjectKey("default", "神经瓦"),
                        "version", "at-start", validFrom=NOW.isoformat())
        atEnd = _fact(store, store.resolveSubjectKey("default", "神经瓦"),
                      "version", "at-end", validUntil=NOW.isoformat())

        visible = {row["id"] for row in TemporalFactReader(
            store, agentId="default").forQuery("神经瓦", now=NOW)}

        assert ids["current"] in visible and atStart in visible
        assert ids["expired"] not in visible and ids["future"] not in visible
        assert atEnd not in visible

    def test_backward_proof_ignores_expired_and_future_facts(self, store):
        ids = _windowFacts(store)

        assert proveGoal(store, "神经瓦", "version", "current")["proved"] is True
        assert proveGoal(store, "神经瓦", "version", "expired")["proved"] is False
        assert proveGoal(store, "神经瓦", "version", "future")["proved"] is False
        assert ids["current"]

    def test_forward_rule_premises_ignore_expired_and_future_facts(self, store):
        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "premise", "kind": "relation"},
            {"termId": "conclusion", "kind": "relation"},
        ])
        engine = ForwardChainingEngine(
            store, gateFactory=lambda st: productionAdmissionGate(st, toolVersion="current-fact-test"))
        engine.registerRule(
            "rule_current", "conclusion",
            [{"atom": "premise", "subject": "X", "object": "Y"}],
            tenantId="default",
        )
        key = _subject(store)
        _fact(store, key, "premise", "expired", validUntil=PAST)
        _fact(store, key, "premise", "future", validFrom=FUTURE)
        _fact(store, key, "premise", "current", validFrom=NOW.isoformat(), validUntil=FUTURE)

        engine.fireFor("default", "premise")

        conclusions = [row["object_term"] for row in store.searchableFacts()
                       if row["predicate_term_id"] == "conclusion"]
        assert conclusions == ["current"]

    def test_exports_and_term_impact_only_include_current_facts(self, store):
        _windowFacts(store)
        registry = OntologyTermRegistry(store)

        assert registry.impactOf("version")["fact_count"] == 1
        from neurova.knowledge.ontology.export.jsonld import exportJsonLd
        from neurova.knowledge.ontology.turtle import serializeAll

        jsonLd = exportJsonLd(store)
        turtle = serializeAll(store)
        graph = json.loads(jsonLd)["@graph"]
        assert [row["kbg:version"] for row in graph if "kbg:version" in row] == ["current"]
        assert "expired" not in turtle and "future" not in turtle and "current" in turtle

    def test_baseline_freezes_only_current_facts(self, store):
        _windowFacts(store)
        assert store.createBaseline()["fact_count"] == 1

    def test_conflict_candidates_keep_temporal_history_and_exclude_retired(self, store):
        ids = _windowFacts(store)
        key = store.resolveSubjectKey("default", "神经瓦")
        retracted = _fact(store, key, "version", "retracted")
        superseded = _fact(store, key, "version", "superseded")
        store.retract(retracted, "测试撤销")
        store.supersede(ids["current"], superseded, reason="测试取代")
        store.expireDueFacts(now=NOW.isoformat())

        candidates = store.candidateFactsForConflict("神经瓦", "version")

        assert {row["fact_id"] for row in candidates} == {
            ids["expired"], ids["future"], ids["current"]}
        assert all(row["status"] in ("active", "expired") for row in candidates)


class TestObservedDerivationsStayOutOfTkg:
    def test_tkg_readers_exclude_observe_but_keep_enforce(self, store, monkeypatch):
        monkeypatch.delenv("NEUROVA_CONDITION_CLASSES_ROUTE", raising=False)
        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "premise", "kind": "relation"},
            {"termId": "conclusion", "kind": "relation"},
        ])
        engine = ForwardChainingEngine(store)
        observeRule = engine.registerRule(
            "rule_observe", "conclusion",
            [{"atom": "missing", "subject": "X", "object": "Y"}],
            materialization="observe", tenantId="default")
        enforceRule = engine.registerRule(
            "rule_enforce", "conclusion",
            [{"atom": "missing", "subject": "X", "object": "Y"}],
            materialization="enforce", tenantId="default")
        key = _subject(store)
        premise = _fact(store, key, "premise", "seed")
        observed = _fact(store, key, "conclusion", "observed",
                         qualifier={"derived_by": "rule:rule_observe"})
        enforced = _fact(store, key, "conclusion", "enforced",
                         qualifier={"derived_by": "rule:rule_enforce"})
        store._derivationLedger.recordDerivation(observed, [premise], observeRule)
        store._derivationLedger.recordDerivation(enforced, [premise], enforceRule)

        temporalIds = {row["id"] for row in TemporalFactReader(
            store, agentId="default").forQuery("神经瓦", now=NOW)}
        tkgIds = {row["fact_id"] for row in TKGModule(factStore=store).query_facts(
            subject="神经瓦", limit=20)}

        assert observed not in temporalIds and observed not in tkgIds
        assert enforced in temporalIds and enforced in tkgIds
