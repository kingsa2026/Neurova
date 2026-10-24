# -*- coding: utf-8 -*-
"""3D 探索器的服务端子图裁剪（升级计划 S4 后端半）。

验收（§11.4 S4）：服务端按 focus/跳数/类型/上限裁剪——3D 画布不拉全量图，
N 节点渲染预算由服务端先兜住。判据：
- focus 必填、不存在 404；
- hops=1 的 BFS 只含直接邻居，边不越过裁剪边界；
- types 过滤节点类型；limit 截断如实报 truncated。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge_graph_api as kg_module
from neurova.cognitive_layers.knowledge_graph.manager import (
    KnowledgeGraphManager, NodeType, RelationType,
)

USER = {"user_id": "1", "username": "a", "role": "admin",
        "tenant_id": "t1", "neuser_id": "1"}
PREFIX = "/api/v1/knowledge-graph"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    mgr = KnowledgeGraphManager(auto_save=False)
    a = mgr.add_node(label="A", node_type=NodeType.CONCEPT).node_id
    b = mgr.add_node(label="B", node_type=NodeType.CONCEPT).node_id
    c = mgr.add_node(label="C", node_type=NodeType.ENTITY).node_id
    d = mgr.add_node(label="D", node_type=NodeType.CONCEPT).node_id
    for src, dst in ((a, b), (b, c), (c, d)):
        mgr.add_edge(src, dst, relation_type=RelationType.RELATED_TO)
    monkeypatch.setattr(
        kg_module, "_get_kg_manager",
        lambda agent_id="default", tenant_id="default": mgr)
    app = FastAPI()
    app.include_router(kg_module.router, prefix=PREFIX)
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service] = lambda: dict(USER)
    return TestClient(app), {"A": a, "B": b, "C": c, "D": d}


class TestSubgraphClipping:

    def testNoFocusReturnsClippedWhole(self, client):
        """首屏无焦点：不 422，按 limit 裁剪全图（同一端点两种模式）。"""
        http, _ids = client
        resp = http.get(PREFIX + "/agent/subgraph", params={"limit": 3})

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["nodes"]) == 3
        assert data["truncated"] is True

    def testUnknownFocusIs404(self, client):
        http, _ = client
        resp = http.get(PREFIX + "/agent/subgraph", params={"focus": "nope"})

        assert resp.status_code == 404, resp.text

    def testOneHopKeepsOnlyNeighbors(self, client):
        http, ids = client
        resp = http.get(PREFIX + "/agent/subgraph",
                        params={"focus": ids["B"], "hops": 1})

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        labels = {n["label"] for n in data["nodes"]}
        assert labels == {"A", "B", "C"}
        # 边不越过裁剪边界：C-D 不在返回里。
        assert all({e["source"], e["target"]} <= {ids["A"], ids["B"], ids["C"]}
                   for e in data["edges"])
        assert data["truncated"] is False

    def testTypeFilterNarrowsNodes(self, client):
        http, ids = client
        resp = http.get(PREFIX + "/agent/subgraph",
                        params={"focus": ids["B"], "hops": 2,
                                "types": "concept"})

        assert resp.status_code == 200, resp.text
        labels = {n["label"] for n in resp.json()["data"]["nodes"]}
        assert "C" not in labels
        assert {"A", "B", "D"} <= labels

    def testLimitReportsTruncation(self, client):
        http, ids = client
        resp = http.get(PREFIX + "/agent/subgraph",
                        params={"focus": ids["B"], "hops": 2, "limit": 2})

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["nodes"]) == 2
        assert data["truncated"] is True
        assert data["stats"]["node_count"] == 4

    def testHopsBeyondDiameterYieldsReachableClip(self, client):
        """hops 超过图直径：结果=可达集按 limit 截断，truncated 如实，不炸。
        同时咬合 BFS 提前终止——收录满 limit 后不再继续扩展层。"""
        http, ids = client
        resp = http.get(PREFIX + "/agent/subgraph",
                        params={"focus": ids["B"], "hops": 12, "limit": 3})

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["nodes"]) == 3
        assert data["truncated"] is True

    def testFocusAlwaysIncluded(self, client):
        http, ids = client
        resp = http.get(PREFIX + "/agent/subgraph",
                        params={"focus": ids["B"], "hops": 0, "limit": 1})

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert {n["label"] for n in data["nodes"]} == {"B"}
