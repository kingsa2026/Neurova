# -*- coding: utf-8 -*-
"""图谱实例编辑（S3）与工作台聚合读面（studio）。

S3 验收（升级计划 §11.4）：2D 新建实例关系必须经唯一咽喉落底座事实——
返回 fact_id/activity_id，编辑→fact 权威段成立；缺依据、未登记谓词、
缺主体/客体在写入处拒（400），不产生半截事实；同三元组重放幂等。
studio 一次性给出子图 + schema + 统计 + 截断读数（2D 工作台首屏数据面）。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.api.endpoints import knowledge_graph_api as kg_module
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

ADMIN = {"user_id": "1", "username": "root", "role": "admin",
         "tenant_id": "t1", "neuser_id": "1"}
USER = {"user_id": "2", "username": "alice", "role": "user",
        "tenant_id": "t1", "neuser_id": "2"}
KB_PREFIX = "/v1/knowledge"
KG_PREFIX = "/api/v1/knowledge-graph"

STATEMENT = "Alpha mentions Beta"


class _Api:
    def __init__(self, client, store, registry, engine):
        self.client = client
        self.store = store
        self.registry = registry
        self.engine = engine

    def asUser(self, user):
        self.client.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(user)


@pytest.fixture()
def api(tmp_path, monkeypatch):
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store)
    registry = OntologyTermRegistry(store)
    registry.register("document", "concept", label="文档", tenantId="t1")
    registry.register("report", "concept", label="报告", parentTermId="document", tenantId="t1")
    registry.register("mentions", "relation", label="提及",
                      domain=["document"], rangeTerms=["report"], tenantId="t1")
    engine = ForwardChainingEngine(store)

    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=KB_PREFIX)
    app.include_router(kg_module.router, prefix=KG_PREFIX)
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service] = lambda: dict(ADMIN)
    # 图谱投影替身：studio 的子图/统计读 manager，不造真投影。
    from neurova.cognitive_layers.knowledge_graph.manager import (
        GraphStats, KnowledgeGraphManager, NodeType, RelationType,
    )
    mgr = KnowledgeGraphManager(auto_save=False)
    n1 = mgr.add_node(label="Alpha", node_type=NodeType.CONCEPT).node_id
    n2 = mgr.add_node(label="Beta", node_type=NodeType.CONCEPT).node_id
    mgr.add_edge(n1, n2, relation_type=RelationType.RELATED_TO)
    monkeypatch.setattr(
        kg_module, "_get_kg_manager",
        lambda agent_id="default", tenant_id="default": mgr)

    yield _Api(TestClient(app), store, registry, engine)
    store.close()


def _body(**overrides):
    base = {
        "agent_id": "agent",
        "subject_label": "Alpha",
        "predicate_term_id": "mentions",
        "object_term": "Beta",
        "evidence_text": STATEMENT,
        "basis": "2D 工作台建边",
    }
    base.update(overrides)
    return base


class TestInstanceEdit:
    def testNonAdminForbidden(self, api):
        api.asUser(USER)
        resp = api.client.post(KB_PREFIX + "/graph/instances", json=_body())

        assert resp.status_code == 403, resp.text

    def testCreateInstanceLandsFactAndActivity(self, api):
        resp = api.client.post(KB_PREFIX + "/graph/instances", json=_body())

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["fact_id"]
        assert data["activity_id"]
        fact = api.store.fact(data["fact_id"])
        assert fact["predicate_term_id"] == "mentions"
        assert fact["subject_key"]
        assert fact["tenant_id"] == "t1"

    def testReplaySameTripleReturnsSameFact(self, api):
        first = api.client.post(KB_PREFIX + "/graph/instances", json=_body())
        second = api.client.post(KB_PREFIX + "/graph/instances", json=_body())

        assert second.status_code == 200, second.text
        assert second.json()["data"]["fact_id"] == first.json()["data"]["fact_id"]

    def testMissingEvidenceIsRejected(self, api):
        resp = api.client.post(
            KB_PREFIX + "/graph/instances", json=_body(evidence_text=""))

        assert resp.status_code == 400, resp.text
        assert "依据" in resp.json()["detail"] or "evidence" in resp.json()["detail"]

    def testUnregisteredPredicateIsRejected(self, api):
        resp = api.client.post(
            KB_PREFIX + "/graph/instances",
            json=_body(predicate_term_id="nonexistent_rel"))

        assert resp.status_code == 400, resp.text

    def testMissingSubjectOrObjectIsRejected(self, api):
        resp = api.client.post(
            KB_PREFIX + "/graph/instances", json=_body(subject_label="  "))

        assert resp.status_code == 400, resp.text

    def testFabricatedIdentifierInEvidenceIsRejected(self, api):
        """逐字可核闸：断言里的精确标识符（URL/路径/semver/hash）必须在证据里逐字存在。"""
        resp = api.client.post(KB_PREFIX + "/graph/instances", json=_body(
            content="Alpha mentions Beta per https://docs.example.internal/a/b",
            evidence_text=STATEMENT,
        ))

        assert resp.status_code == 400, resp.text

    def testEntryLinkCarriedToFact(self, api):
        resp = api.client.post(KB_PREFIX + "/graph/instances", json=_body(
            entry_id="kb-123"))

        assert resp.status_code == 200, resp.text
        fact = api.store.fact(resp.json()["data"]["fact_id"])
        assert "kb-123" in str(fact.get("source_turn_id") or "")


class TestStudioReadSurface:
    def testStudioAggregatesSubgraphSchemaAndStats(self, api):
        resp = api.client.get(KG_PREFIX + "/agent/studio")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert data["stats"]["node_count"] == 2
        assert data["truncated"] is False
        schema = data["schema"]
        assert "mentions" in {t["term_id"] for t in schema["terms"]}
        assert schema["schema_version"] > 0

    def testStudioHonorsLimit(self, api):
        resp = api.client.get(KG_PREFIX + "/agent/studio", params={"limit": 1})

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["nodes"]) == 1
        assert data["truncated"] is True
