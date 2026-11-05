# -*- coding: utf-8 -*-
"""B11 L5 解释链端点（升级计划 §12.6 设计 4）：推导结论可回溯到规则与前提。

`GET /v1/knowledge/ontology/derivations/{fact_id}` 返回规则 id/版本、前提
fact_id、derivation_kind、confidence——B4 的引用标注与该端点同源（账本单点）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE, OntologyTermRegistry

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
PREFIX = "/v1/knowledge"


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s
    )
    yield s
    s.close()


@pytest.fixture
def seeded(store):
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "Order", "kind": "concept"},
        {"termId": "HighRiskOrder", "kind": "concept", "parentTermId": "Order"},
        {"termId": "hasRiskLevel", "kind": "relation", "domain": ["Order"]},
    ])
    gate = productionAdmissionGate(store)
    for subject, level in (("订单D01", "High"),):
        content = "%s is_a Order" % subject
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=subject, predicateTermId=IS_A_PREDICATE,
            objectTerm="Order", content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))
        content2 = "%s hasRiskLevel High" % subject
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=subject, predicateTermId="hasRiskLevel",
            objectTerm=level, content=content2,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content2}]))
        key = store.resolveSubjectKey("default", subject)
        registry.assignSubjectType(key, "Order")
    ForwardChainingEngine = pytest.importorskip(
        "neurova.knowledge.ontology.rule_engine").ForwardChainingEngine
    ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(st)).registerRule(
        "high_risk_order", IS_A_PREDICATE,
        [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "Order"},
         {"atom": "hasRiskLevel", "subject": "X", "objectConst": "High"}],
        headObjectConst="HighRiskOrder")
    derivedId = [f["fact_id"] for f in store.searchableFacts(agentId="default")
                 if f["object_term"] == "HighRiskOrder"][0]
    return {"store": store, "derivedId": derivedId}


@pytest.fixture
def client(store, seeded):
    from neurova.api.endpoints import knowledge_ontology

    app = FastAPI()
    app.include_router(knowledge_ontology.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: dict(ADMIN)
    return TestClient(app)


class TestExplanationChainEndpoint:
    def test_derivedFactExplainsToRuleAndPremises(self, client, seeded):
        resp = client.get(PREFIX + "/ontology/derivations/" + seeded["derivedId"])

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["derived"] is True
        assert data["rule_id"] == "high_risk_order"
        assert data["premise_count"] == 2
        assert len(data["premises"]) == 2
        assert all(p["premise_fact_id"] for p in data["premises"])

    def test_explicitFactExplainsAsNotDerived(self, client, seeded):
        explicitId = [f["fact_id"] for f in seeded["store"].searchableFacts(agentId="default")
                      if f["predicate_term_id"] == "hasRiskLevel"][0]

        resp = client.get(PREFIX + "/ontology/derivations/" + explicitId)

        assert resp.status_code == 200
        assert resp.json()["data"]["derived"] is False

    def test_missingFactIs404(self, client):
        resp = client.get(PREFIX + "/ontology/derivations/no_such_fact")
        assert resp.status_code == 404
