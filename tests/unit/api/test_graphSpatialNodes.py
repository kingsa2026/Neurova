# -*- coding: utf-8 -*-
"""空间视图（A6）节点落图端点：可见图节点按同名条目 geo 解析坐标。

红：端点缺失 404。绿：同名条目带 geo 的节点返回坐标；无坐标节点不进结果
（诚实不造坐标）；可见性走 repo.visible_items。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge_graph_api as kg_module
from neurova.cognitive_layers.knowledge_graph.manager import (
    KnowledgeGraphManager,
    NodeType,
)

USER = {"user_id": "1", "username": "a", "role": "admin",
        "tenant_id": "t1", "neuser_id": "1"}
PREFIX = "/api/v1/knowledge-graph"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    mgr = KnowledgeGraphManager(auto_save=False)
    mgr.add_node(label="客户反馈", node_type=NodeType.CONCEPT)
    mgr.add_node(label="无坐标节点", node_type=NodeType.ENTITY)
    monkeypatch.setattr(
        kg_module, "_get_kg_manager",
        lambda agent_id="default", tenant_id="default": mgr)

    class _Repo:
        def visible_items(self, user, scope="all", agent_id=None, **kw):
            return [
                {"knowledge_id": "k1", "title": "客户反馈",
                 "geo": {"lat": 31.23, "lon": 121.47}},
                {"knowledge_id": "k2", "title": "无坐标节点", "geo": None},
            ]

    monkeypatch.setattr(
        "neurova.api.endpoints.knowledge_common.get_repository", lambda: _Repo())
    app = FastAPI()
    app.include_router(kg_module.router, prefix=PREFIX)
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service] = lambda: dict(USER)
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_default] = lambda: dict(USER)
    return TestClient(app)


class TestSpatialNodes:
    def test_nodesResolvedFromEntryGeo(self, client):
        r = client.get(f"{PREFIX}/default/spatial-nodes")
        assert r.status_code == 200, r.text[:200]
        rows = r.json()["data"]
        labels = {row["label"]: row for row in rows}
        assert "客户反馈" in labels, "同名条目带 geo 的节点应落图"
        assert labels["客户反馈"]["geo"]["lat"] == 31.23
        assert "无坐标节点" not in labels, "无坐标节点不进结果（不造坐标）"

    def test_emptyGraphReturnsEmpty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            kg_module, "_get_kg_manager",
            lambda agent_id="default", tenant_id="default": None)
        monkeypatch.setattr(
            "neurova.api.endpoints.knowledge_common.get_repository",
            lambda: type("R", (), {"visible_items": lambda self, *a, **k: []})())
        app = FastAPI()
        app.include_router(kg_module.router, prefix=PREFIX)
        app.dependency_overrides[
            knowledge_auth.get_current_user_or_default] = lambda: dict(USER)
        c = TestClient(app)
        r = c.get(f"{PREFIX}/default/spatial-nodes")
        assert r.status_code == 200 and r.json()["data"] == []
