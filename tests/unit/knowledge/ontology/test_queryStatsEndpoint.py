# -*- coding: utf-8 -*-
"""C 维增强批 P2-5：查询缓存统计读面（GET /ontology/query/stats）。

两层缓存（U2 行集缓存 + P1-1 投影图缓存）的命中/重建计数合并成一个只读
端点——运维可观测，不各翻各的内部字段。
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
from neurova.knowledge.ontology import sparql_query
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

ADMIN = {"user_id": "9", "username": "admin", "role": "admin",
         "tenant_id": "default"}
PREFIX = "/v1/knowledge"
QUERY = ("PREFIX kbg: <https://neurova.local/knowledge/>"
         " SELECT ?s ?o WHERE { ?s kbg:linked ?o } LIMIT 10")


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s)
    registry = OntologyTermRegistry(s)
    registry.register("linked", "relation")
    gate = productionAdmissionGate(s)
    content = "设备A linked 设备B"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="设备A", predicateTermId="linked",
        objectTerm="设备B", content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))
    yield s
    s.close()


@pytest.fixture
def client(store):
    from neurova.api.endpoints import knowledge_ontology

    app = FastAPI()
    app.include_router(knowledge_ontology.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(ADMIN)
    return TestClient(app)


class TestQueryStatsEndpoint:
    def test_statsShapeAndCounters(self, store, client):
        """跑两次同查询（1 未命中 + 1 命中）后，统计端点如实反映两层计数。"""
        sparql_query.runSparqlQuery(store, QUERY, agentId="default",
                                    tenantId="default")
        sparql_query.runSparqlQuery(store, QUERY, agentId="default",
                                    tenantId="default")
        resp = client.get(PREFIX + "/ontology/query/stats")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["row_cache"]["hits"] == 1, "第二次执行命中行集缓存"
        assert data["row_cache"]["misses"] == 1
        assert data["row_cache"]["enabled"] is True
        assert data["graph_cache"]["enabled"] is True
        assert data["graph_cache"]["full_rebuilds"] == 1, "首查全量建图一次"
        assert data["graph_cache"]["incremental_splices"] == 0, \
            "库未变，无增量拼接"

    def test_statsReflectsIncrementalSplice(self, store, client):
        """库变更后：图缓存增量拼接计数 +1，行集缓存未命中 +1。"""
        sparql_query.runSparqlQuery(store, QUERY, agentId="default",
                                    tenantId="default")
        gate = productionAdmissionGate(store)
        content = "设备A linked 设备X"
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="设备A", predicateTermId="linked",
            objectTerm="设备X", content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))
        sparql_query.runSparqlQuery(store, QUERY, agentId="default",
                                    tenantId="default")
        data = client.get(PREFIX + "/ontology/query/stats").json()["data"]
        assert data["graph_cache"]["incremental_splices"] == 1
        assert data["graph_cache"]["subjects_spliced"] == 1
        assert data["row_cache"]["misses"] == 2
