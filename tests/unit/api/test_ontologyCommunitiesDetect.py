# -*- coding: utf-8 -*-
"""W8 社区检测手动触发端点（specs/2026-11-12 §14 U4 闭环）：检测缺省 off，
无触发面时社区图层永远空转。POST /ontology/communities/detect（管理员）→
标签传播＋持久化；登录读数面随即可见；普通用户触发 403。

红：端点不存在 404／普通用户 403。绿：admin 触发后 data 非空且读数面同源可见。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api import deps as knowledge_deps
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

ADMIN = {"user_id": "9", "username": "admin", "role": "admin",
         "tenant_id": "default", "agent_id": "default"}
VIEWER = {"user_id": "5", "username": "viewer", "role": "viewer",
          "tenant_id": "default", "agent_id": "default"}
PREFIX = "/v1/knowledge"


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s
    )
    yield s
    s.close()


def _seedGraph(store) -> None:
    """小图：A1-A2 互连＋A1-B1 弱边——标签传播至少产出一个社区。"""
    from neurova.knowledge.foundation.admission import (
        AdmissionRequest,
        productionAdmissionGate,
    )
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    registry = OntologyTermRegistry(store)
    registry.register("cluster_a", "concept")
    registry.register("linked_a", "relation")
    registry.register("linked_b", "relation")
    gate = productionAdmissionGate(store)
    for src, dst, pred in [("A1", "A2", "linked_a"), ("A2", "A1", "linked_a"),
                           ("A1", "B1", "linked_b")]:
        content = "%s %s %s" % (src, pred, dst)
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=src, predicateTermId=pred,
            objectTerm=dst, content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))


@pytest.fixture
def client(store):
    from neurova.api.endpoints import knowledge_ontology

    app = FastAPI()
    app.include_router(knowledge_ontology.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(ADMIN)
    # require_admin 工厂闭包捕获的本体——按对象键 override（先例：test_agentDeptMigration）
    app.dependency_overrides[knowledge_deps.strictIdentityGate] = lambda: dict(ADMIN)
    return TestClient(app)


class TestCommunitiesDetectEndpoint:
    def test_adminDetectCreatesVisibleCommunities(self, client, store):
        _seedGraph(store)
        # 红：触发面缺失 → 404/405
        r = client.post(f"{PREFIX}/ontology/communities/detect")
        assert r.status_code == 200, r.text[:200]
        rows = r.json()["data"]
        assert isinstance(rows, list) and len(rows) >= 1, "触发后应产出社区"
        # 读数面同源可见
        r2 = client.get(f"{PREFIX}/ontology/communities")
        assert r2.status_code == 200
        assert len(r2.json()["data"]) >= 1, "读数面应看到刚检测的社区"

    def test_viewerCannotDetect(self, client, store):
        _seedGraph(store)
        client.app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
            lambda: dict(VIEWER)
        client.app.dependency_overrides[knowledge_deps.strictIdentityGate] = \
            lambda: dict(VIEWER)
        r = client.post(f"{PREFIX}/ontology/communities/detect")
        assert r.status_code == 403, f"普通用户触发应 403，得到 {r.status_code}"
