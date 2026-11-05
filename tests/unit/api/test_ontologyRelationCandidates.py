# -*- coding: utf-8 -*-
"""B8 候选审核 API（升级计划 §5 B8 绿灯补档）：列表/批准/拒绝/越权。

候选面是未知关系的唯一人工入口：批准走注册表登记（不另造路径），
拒绝保留审计；非管理员不得审批。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.graph_bridge import admitExtractedFacts
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
def seeded(store):
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "person", "kind": "concept"},
        {"termId": "company", "kind": "concept"},
    ])
    data = {"entities": [{"label": "张三", "type": "person"},
                         {"label": "甲公司", "type": "company"}],
            "relations": [{"source": "张三", "type": "telepathizes",
                           "target": "甲公司"}]}
    item = {"agent_id": "default", "tenant_id": "default",
            "knowledge_id": "k1", "title": "t", "content": "c"}
    admitExtractedFacts(data, item, store, termRegistry=registry)
    return registry


@pytest.fixture
def client(store, seeded):
    from neurova.api.endpoints import knowledge_ontology

    app = FastAPI()
    app.include_router(knowledge_ontology.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: dict(ADMIN)
    return TestClient(app)


def _as(client, user):
    client.app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(user)
    return client


class TestRelationCandidateEndpoints:
    def test_listPendingShowsExtractedUnknownRelation(self, client):
        resp = client.get(PREFIX + "/ontology/relation-candidates",
                          params={"status": "pending"})

        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1 and items[0]["surface"] == "telepathizes"

    def test_approvePromotesTermAndBackfillsCandidate(self, client, seeded):
        pending = client.get(PREFIX + "/ontology/relation-candidates").json()["data"]["items"]

        resp = client.post(PREFIX + "/ontology/relation-candidates/%s/approve"
                           % pending[0]["candidate_id"])

        assert resp.status_code == 200
        promoted = resp.json()["data"]["candidate"]
        assert promoted["promoted_term_id"] == "telepathizes"
        assert seeded.term("telepathizes") is not None, "批准即登记术语"

    def test_rejectKeepsAuditRow(self, client, seeded):
        pending = client.get(PREFIX + "/ontology/relation-candidates").json()["data"]["items"]

        resp = client.post(PREFIX + "/ontology/relation-candidates/%s/reject"
                           % pending[0]["candidate_id"])

        assert resp.status_code == 200
        assert resp.json()["data"]["candidate"]["status"] == "rejected"

    def test_approveTwiceReturns409(self, client, seeded):
        pending = client.get(PREFIX + "/ontology/relation-candidates").json()["data"]["items"]
        candidateId = pending[0]["candidate_id"]
        client.post(PREFIX + "/ontology/relation-candidates/%s/approve" % candidateId)

        resp = client.post(PREFIX + "/ontology/relation-candidates/%s/approve" % candidateId)

        assert resp.status_code == 409

    def test_nonAdminCannotApproveOrReject(self, store, seeded, client):
        from neurova.api.endpoints import knowledge_ontology

        app = FastAPI()
        app.include_router(knowledge_ontology.router, prefix=PREFIX)
        app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
            lambda: dict(VIEWER)
        viewer = TestClient(app)

        pending = client.get(PREFIX + "/ontology/relation-candidates").json()["data"]["items"]
        candidateId = pending[0]["candidate_id"]

        assert viewer.post(PREFIX + "/ontology/relation-candidates/%s/approve"
                           % candidateId).status_code == 403
        assert viewer.post(PREFIX + "/ontology/relation-candidates/%s/reject"
                           % candidateId).status_code == 403
        from neurova.knowledge.ontology.relation_candidates import RelationCandidateStore
        assert len(RelationCandidateStore(store).list(status="pending")) == 1, \
            "越权审批不产生任何状态变化"

    def test_unknownStatusIs400(self, client):
        resp = client.get(PREFIX + "/ontology/relation-candidates",
                          params={"status": "bogus"})

        assert resp.status_code == 400
