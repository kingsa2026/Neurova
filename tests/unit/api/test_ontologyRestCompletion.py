# -*- coding: utf-8 -*-
"""B10/B11/B12 REST 补口：shapes CRUD、四格式导出、pipeline rollback、双时态 query。

这些端点是 UI-0–UI-4 从「诚实规划中」转为真实调用的前置。判据只咬行为：
写入后列表可见、回滚后基线外术语退场、导出逐格式可读、双时态按轴裁剪。
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
from neurova.knowledge.ontology.pipeline import OntologyPipeline
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
VIEWER = {"user_id": "5", "username": "viewer", "role": "viewer", "tenant_id": "default"}
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
def client(store):
    from neurova.api.endpoints import knowledge_access_facade, knowledge_ontology

    app = FastAPI()
    app.include_router(knowledge_ontology.router, prefix=PREFIX)
    app.include_router(knowledge_access_facade.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(ADMIN)
    return TestClient(app)


def _seedOntology(store: KnowledgeFactStore):
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "Order", "kind": "concept", "label": "订单"},
        {"termId": "HighRiskOrder", "kind": "concept", "parentTermId": "Order"},
        {"termId": "hasRiskLevel", "kind": "relation", "domain": ["Order"]},
    ])
    return registry


class TestShapesRest:
    def testCreateListDelete(self, client):
        body = {
            "shape_id": "risk_enum",
            "target_kind": "relation",
            "target_term_id": "hasRiskLevel",
            "path": {"predicate": "hasRiskLevel"},
            "constraint_kind": "in",
            "constraint": {"values": ["High", "Low"]},
            "severity": "warning",
            "message": "风险等级取值越界",
        }
        created = client.post(PREFIX + "/ontology/shapes", json=body)
        assert created.status_code == 200
        assert created.json()["data"]["shape"]["shape_id"] == "risk_enum"

        listed = client.get(PREFIX + "/ontology/shapes")
        assert listed.status_code == 200
        assert [s["shape_id"] for s in listed.json()["data"]["items"]] == ["risk_enum"]

        deleted = client.delete(PREFIX + "/ontology/shapes/risk_enum")
        assert deleted.status_code == 200
        assert client.get(PREFIX + "/ontology/shapes").json()["data"]["items"] == []

    def testBuiltinConstraintKindRejected(self, client):
        body = {
            "shape_id": "dup_domain",
            "target_kind": "relation",
            "target_term_id": "hasRiskLevel",
            "constraint_kind": "domain",
            "constraint": {},
        }
        resp = client.post(PREFIX + "/ontology/shapes", json=body)
        assert resp.status_code == 400

    def testNonAdminCannotWriteShapes(self, client):
        client.app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
            lambda: dict(VIEWER)
        resp = client.post(PREFIX + "/ontology/shapes", json={
            "shape_id": "x", "target_kind": "relation", "constraint_kind": "in",
            "constraint": {"values": ["a"]},
        })
        assert resp.status_code == 403


class TestRollbackRest:
    def testRollbackRestoresBaseline(self, client, store):
        registry = OntologyTermRegistry(store)
        registry.register("keep_me", "concept")
        engine = ForwardChainingEngine(store)
        pipeline = OntologyPipeline(store, registry=registry, engine=engine)
        baselineId = pipeline.run(
            agentId="default", tenantId="default", termUpserts=[],
            ruleRegistrations=[], factCandidates=[], reason="基线")["baselineId"]

        registry.register("extra_term", "concept")
        resp = client.post(PREFIX + "/ontology/pipeline/rollback",
                           json={"toBaselineId": baselineId, "reason": "单测回滚"})

        assert resp.status_code == 200
        assert OntologyTermRegistry(store).term("extra_term") is None
        assert OntologyTermRegistry(store).term("keep_me") is not None

    def testUnknownBaseline404(self, client):
        resp = client.post(PREFIX + "/ontology/pipeline/rollback",
                           json={"toBaselineId": "missing", "reason": "x"})
        assert resp.status_code == 404


class TestExportRest:
    def testFourFormatsReturnContent(self, client, store):
        _seedOntology(store)
        gate = productionAdmissionGate(store)
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="D01", predicateTermId="hasRiskLevel",
            objectTerm="High", content="D01 hasRiskLevel High",
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": "D01 hasRiskLevel High"}]))

        cases = [
            ("/ontology/export.jsonld", "application/ld+json", "@context"),
            ("/ontology/export.owl", "text/turtle", "rdfs:subClassOf"),
            ("/ontology/export.shacl", "text/turtle", "sh:"),
            ("/ontology/export.prov", "text/turtle", "prov:"),
        ]
        for path, media, marker in cases:
            resp = client.get(PREFIX + path)
            assert resp.status_code == 200, path
            assert media in resp.headers["content-type"], path
            assert marker in resp.text, path


class TestBitemporalQueryRest:
    def testAsOfAndKnownAtFilterFacts(self, client, store):
        gate = productionAdmissionGate(store)
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="订单D01", predicateTermId="is_a",
            objectTerm="Order", content="订单D01 is_a Order",
            validFrom="2026-01-01", validUntil="2026-12-31",
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": "订单D01 is_a Order"}]))

        inside = client.post(PREFIX + "/access/query",
                             params={"agent_id": "default"},
                             json={"query": "D01", "asOf": "2026-06-01",
                                   "knownAt": "2026-11-06"})
        assert inside.status_code == 200
        assert len(inside.json()) == 1
        assert inside.json()[0]["knowledge_id"]

        outside = client.post(PREFIX + "/access/query",
                              params={"agent_id": "default"},
                              json={"query": "D01", "asOf": "2027-01-01",
                                    "knownAt": "2026-11-06"})
        assert outside.status_code == 200
        assert outside.json() == []
