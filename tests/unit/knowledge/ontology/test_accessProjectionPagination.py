# -*- coding: utf-8 -*-
"""B12 L6：ontology 列表的 cursor 分页与 fields 投影（升级计划 §12.7）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
PREFIX = "/v1/knowledge"


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s
    )
    registry = OntologyTermRegistry(s)
    for i in range(5):
        registry.register("term_%d" % i, "concept", label="术语%d" % i)
    yield s
    s.close()


@pytest.fixture
def client(store):
    from neurova.api.endpoints import knowledge_ontology

    app = FastAPI()
    app.include_router(knowledge_ontology.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: dict(ADMIN)
    return TestClient(app)


class TestTermsPaginationProjection:
    def test_cursorPaginationKeysetStable(self, client):
        page1 = client.get(PREFIX + "/ontology/terms",
                           params={"limit": 2}).json()["data"]
        assert len(page1["items"]) == 2
        assert page1["next_cursor"], "有下一页必有游标"

        page2 = client.get(PREFIX + "/ontology/terms",
                           params={"limit": 2, "cursor": page1["next_cursor"]}).json()["data"]

        ids1 = [t["term_id"] for t in page1["items"]]
        ids2 = [t["term_id"] for t in page2["items"]]
        assert not set(ids1) & set(ids2), "游标页不重叠"
        assert page2["next_cursor"], "还有第三页"

    def test_fieldsProjectionMinimizes(self, client):
        resp = client.get(PREFIX + "/ontology/terms",
                          params={"fields": "term_id,kind"}).json()["data"]

        item = resp["items"][0]
        assert set(item.keys()) <= {"term_id", "kind"}, "投影只留点名字段"

    def test_termsPaginationDefaultsCompatible(self, client):
        """不传游标/fields 时行为与旧读数一致（全量、全字段）。"""
        resp = client.get(PREFIX + "/ontology/terms").json()["data"]

        assert len(resp["items"]) >= 5
        assert "label" in resp["items"][0]
