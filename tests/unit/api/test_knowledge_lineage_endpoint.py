"""血缘端点与 Turtle 导出端点（工单 024 / G01 的用户可见面）。

端点只做"把底座那份读数原样搬出来"这一件事：再算一套就会与 `FactLineageView`
分叉，两条真源比一条粗读数糟。
"""

from __future__ import annotations

import os

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_lineage_0123456789")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user_or_service
from neurova.api.endpoints import knowledge_core
from neurova.knowledge.foundation import knowledge_facts as kf
from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.turtle import parseTurtle


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_core.router, prefix="/api/v1/knowledge")
    app.dependency_overrides[get_current_user_or_service] = lambda: {"user_id": "u1",
                                                                    "role": "admin"}
    return TestClient(app)


@pytest.fixture
def isolatedStore(tmp_path, monkeypatch):
    store = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(kf, "get_knowledge_fact_store", lambda *a, **k: store)
    monkeypatch.setattr("neurova.knowledge.foundation.get_knowledge_fact_store",
                        lambda *a, **k: store)
    yield store
    store.close()


def _admit(store, subject, predicate, obj):
    content = "%s %s %s" % (subject, predicate, obj)
    return productionAdmissionGate(store, toolVersion="unit").admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate, objectTerm=obj,
        content=content,
        assertions=[{"actorType": "user", "actorId": "u1", "mediumRef": "unit:test",
                     "statementText": content}],
    ), allowPendingSegments=True).factId


def test_lineageEndpointReturnsTheHops(isolatedStore):
    factId = _admit(isolatedStore, "青海湖", "is_a", "湖泊")

    body = _client().get(f"/api/v1/knowledge/facts/{factId}/lineage").json()

    assert body["fact_id"] == factId
    assert body["provenance_state"] == "evidenced" and body["missing"] == []
    assert body["hops"][0]["statement_text"] == "青海湖 is_a 湖泊"


def test_lineageEndpointKeepsMissingDimensionsExplicit(isolatedStore):
    key = isolatedStore.upsertSubject("default", "裸事实")
    factId = isolatedStore.upsertFact(agentId="default", subjectKey=key,
                                      predicateTermId="is_a", objectTerm="未知",
                                      content="没有断言")

    body = _client().get(f"/api/v1/knowledge/facts/{factId}/lineage").json()

    assert body["missing"] == ["assertions"] and body["hops"] == []


def test_unknownFactIs404NotAnEmptyObject(isolatedStore):
    res = _client().get("/api/v1/knowledge/facts/fact_nope/lineage")

    assert res.status_code == 404


def test_turtleEndpointParsesBackAndSaysItsMediaType(isolatedStore):
    factId = _admit(isolatedStore, "青海湖", "is_a", "湖泊")

    res = _client().get(f"/api/v1/knowledge/facts/{factId}/turtle")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/turtle")
    triples = parseTurtle(res.text)
    assert any(p == "kbg:is_a" and o == '"湖泊"@zh' for _, p, o in triples)
