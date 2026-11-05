# -*- coding: utf-8 -*-
"""B3：四动词统一门面 `/v1/knowledge/access/{query|analyze|validate|use}`。

判据（升级计划 §5 B3 ＋ §4 拍板项 3 选 A）：门面是**接线不是第二实现**——
四个动词各转发一处既有处理函数（facts/条目检索、/analyze、B2 validate、
/facts/{id}/adoption），零新业务逻辑；未知路径天然 404；旧路由保持直接入口，
两处消费同一实现（教义第 7 条：接通后退役才谈得上，本批不删旧路由）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

ALICE = {"user_id": "1", "username": "alice", "role": "user", "tenant_id": "default"}
ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
PREFIX = "/v1/knowledge"

_ITEM = {
    "knowledge_id": "k1",
    "title": "客户流失手册",
    "content": "流失预警要看 30 天活跃",
    "category": "general",
    "tags": ["kb"],
    "source": "unit",
    "confidence": 0.9,
    "created_at": 1,
    "updated_at": 1,
    "visibility": "public",
    "owner_user_id": "1",
}


class _FakeRepo:
    def __init__(self):
        self.calls = []

    def search_visible_items(self, user, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        return [dict(_ITEM)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store
    )
    repo = _FakeRepo()
    monkeypatch.setattr(
        "neurova.api.endpoints.knowledge_core.get_repository", lambda: repo
    )
    app = FastAPI()
    # 旧路由（聚合器）与门面同前缀并存：旧入口不受影响是本批的回归判据之一
    app.include_router(knowledge_module.router, prefix=PREFIX)
    from neurova.api.endpoints import knowledge_access_facade

    app.include_router(knowledge_access_facade.router, prefix=PREFIX)
    holder = {"user": dict(ADMIN)}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = (
        lambda: holder["user"]
    )
    client = TestClient(app)
    yield client, holder, store, repo
    store.close()


class TestFourVerbsForward:
    def test_query_forwardsToExistingSearchHandler(self, env):
        client, _holder, _store, repo = env

        resp = client.post(PREFIX + "/access/query", json={"query": "流失"})

        assert resp.status_code == 200, resp.text
        assert repo.calls and repo.calls[0]["query"] == "流失", "query 动词必须真转发"
        body = resp.json()
        assert body[0]["knowledge_id"] == "k1", "响应形状与旧 /search 一致"

    def test_analyze_forwardsToSemanticSearchAnalyze(self, env):
        client, _holder, _store, _repo = env

        resp = client.post(PREFIX + "/access/analyze", json={"query": "怎么配置路由器"})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["query"] == "怎么配置路由器"
        assert "features" in body["data"] and "recommended_weights" in body["data"]

    def test_validate_forwardsToOntologyDryRun(self, env):
        client, _holder, store, _repo = env
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "person", "kind": "concept"},
            {"termId": "city", "kind": "concept"},
            {"termId": "lives_in", "kind": "relation", "domain": ["person"],
             "rangeTerms": ["city"]},
        ])
        key = store.upsertSubject("a1", "甲")
        registry.assignSubjectType(key, "city")  # domain 违规

        resp = client.post(PREFIX + "/access/validate", json={
            "agentId": "a1",
            "triples": [{"subjectLabel": "甲", "predicateTermId": "lives_in",
                         "objectTerm": "city"}],
        })

        assert resp.status_code == 200, resp.text
        row = resp.json()["data"]["results"][0]
        assert row["verdict"] == "violation"
        assert row["subjectKey"] == key

    def test_use_forwardsToAdoptionHandler(self, env):
        client, holder, store, _repo = env
        factId = store.upsertFact("a1", "subj_x", "is_a", "person", "甲是人")

        resp = client.post(PREFIX + "/access/use/%s" % factId,
                           json={"outcome": "success"})

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["outcome"] == "success"
        row = store._conn.execute(
            "SELECT adoption_outcome FROM knowledge_facts WHERE fact_id = ?",
            (factId,)).fetchone()
        assert row["adoption_outcome"] == "success"

    def test_use_keepsAdoptionAdminGate(self, env):
        """门面不放宽治理门：use 经转发后依旧仅管理员。"""
        client, holder, store, _repo = env
        holder["user"] = dict(ALICE)
        factId = store.upsertFact("a1", "subj_x", "is_a", "person", "甲是人")

        resp = client.post(PREFIX + "/access/use/%s" % factId,
                           json={"outcome": "success"})

        assert resp.status_code == 403, resp.text


class TestFacadeBoundaries:
    def test_unknownVerb_is404(self, env):
        client, _holder, _store, _repo = env

        resp = client.post(PREFIX + "/access/teleport", json={})

        assert resp.status_code == 404, "未声明的动词不许有隐式处理面"

    def test_oldRoutes_stillWorkAlongsideFacade(self, env):
        """旧路由是直接入口：门面上线不遮蔽、不改写它们。"""
        client, _holder, _store, repo = env

        resp = client.post(PREFIX + "/search", json={"query": "流失"})

        assert resp.status_code == 200, resp.text
        assert repo.calls and repo.calls[-1]["query"] == "流失"
        assert resp.json()[0]["knowledge_id"] == "k1"
