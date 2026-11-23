# -*- coding: utf-8 -*-
"""C 维增强批 P1-3：本体图分析只读面（k 跳邻域/最短路/度概览/社区检测）。

三个面同判据（教义第 6 条）：核心模块（graph_analytics.py）、REST 四条只读
路由、MCP 两件新工具（ontology_graph_path / ontology_graph_overview）都转交
同一份实现。社区检测**复用** community_graph._labelPropagation（不造第二份
标签传播）。全部真咽喉写入，零打桩。
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.graph_analytics import (
    detectOntologyCommunities,
    graphOverview,
    kHopNeighbors,
    shortestPath,
)
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

ADMIN = {"user_id": "9", "username": "admin", "role": "admin",
         "tenant_id": "default"}
PREFIX = "/v1/knowledge"
_SERVICE_TOKEN = "test-mcp-service-token"


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """两个连通分量：甲—乙—丙 链 + 丁—戊 孤对。"""
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s)
    registry = OntologyTermRegistry(s)
    registry.register("linked", "relation")
    gate = productionAdmissionGate(s)

    def admit(sub, obj):
        content = "%s linked %s" % (sub, obj)
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=sub, predicateTermId="linked",
            objectTerm=obj, content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))

    for sub, obj in (("甲", "乙"), ("乙", "丙"), ("丁", "戊")):
        admit(sub, obj)
    yield s
    s.close()


class TestGraphAnalyticsCore:
    def test_kHopNeighborsLevels(self, kb):
        """k 跳邻域：1 跳到直接邻居，逐层外扩，无向（乙的 1 跳含甲与丙）。"""
        one = kHopNeighbors(kb, agentId="default", tenantId="default",
                            startLabel="甲", maxHops=1)
        assert {n["label"] for n in one["nodes"]} == {"甲", "乙"}
        two = kHopNeighbors(kb, agentId="default", tenantId="default",
                            startLabel="乙", maxHops=1)
        assert {n["label"] for n in two["nodes"]} == {"乙", "甲", "丙"}, \
            "无向遍历：乙的邻居含前驱甲与后继丙"
        three = kHopNeighbors(kb, agentId="default", tenantId="default",
                              startLabel="甲", maxHops=3)
        assert {n["label"] for n in three["nodes"]} == {"甲", "乙", "丙"}, \
            "3 跳覆盖链上全部节点（丁戊在另一连通分量，不可达）"
        assert three["nodes"][0]["hop"] == 0 and \
            max(n["hop"] for n in three["nodes"]) == 2, "起点 0 层，逐层递增"

    def test_kHopUnknownStartIsHonestEmpty(self, kb):
        """起点不是任何主体/客体：诚实空集，不报错不编造。"""
        out = kHopNeighbors(kb, agentId="default", tenantId="default",
                            startLabel="不存在", maxHops=2)
        assert out["nodes"] == [] and out["edges"] == []

    def test_shortestPathAlongChain(self, kb):
        """最短路：甲到丙经乙两跳；自身零跳；不可达如实 found=False。"""
        path = shortestPath(kb, agentId="default", tenantId="default",
                            fromLabel="甲", toLabel="丙")
        assert path["found"] is True and path["path"] == ["甲", "乙", "丙"]
        assert path["hops"] == 2
        selfPath = shortestPath(kb, agentId="default", tenantId="default",
                                fromLabel="甲", toLabel="甲")
        assert selfPath["found"] is True and selfPath["path"] == ["甲"]
        miss = shortestPath(kb, agentId="default", tenantId="default",
                            fromLabel="甲", toLabel="不存在")
        assert miss["found"] is False and miss["path"] == []

    def test_shortestPathUndirected(self, kb):
        """无向最短路：戊到丁一跳（反向沿 丁→戊 的边）。"""
        path = shortestPath(kb, agentId="default", tenantId="default",
                            fromLabel="戊", toLabel="丁")
        assert path["found"] is True and path["path"] == ["戊", "丁"]

    def test_graphOverviewCountsAndDegrees(self, kb):
        """概览：节点/边计数与度排行（无向度=触及边数）。"""
        out = graphOverview(kb, agentId="default", tenantId="default")
        assert out["nodes"] == 5 and out["edges"] == 3
        degrees = {d["label"]: d["degree"] for d in out["top_degree"]}
        assert degrees == {"甲": 1, "乙": 2, "丙": 1, "丁": 1, "戊": 1}
        assert out["predicates"][0]["term"] == "linked"
        assert out["predicates"][0]["count"] == 3

    def test_communitiesDetectTwoClusters(self, kb):
        """社区检测复用既有标签传播：两个连通分量各成一社区，大者在前。"""
        out = detectOntologyCommunities(kb, agentId="default",
                                        tenantId="default")
        sizes = [c["size"] for c in out["communities"]]
        assert sizes == [3, 2], "甲乙丙 一簇、丁戊 一簇"
        members = {frozenset(c["members"]) for c in out["communities"]}
        assert frozenset({"甲", "乙", "丙"}) in members
        assert frozenset({"丁", "戊"}) in members


@pytest.fixture
def client(kb):
    from neurova.api.endpoints import knowledge_ontology

    app = FastAPI()
    app.include_router(knowledge_ontology.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(ADMIN)
    return TestClient(app)


class TestGraphAnalyticsRest:
    def test_neighborsRoute(self, client):
        resp = client.get(PREFIX + "/ontology/graph/neighbors",
                          params={"subject": "甲", "max_hops": 3})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert {n["label"] for n in data["nodes"]} == {"甲", "乙", "丙"}

    def test_pathRoute(self, client):
        resp = client.get(PREFIX + "/ontology/graph/path",
                          params={"from_label": "甲", "to_label": "丙"})
        assert resp.status_code == 200
        assert resp.json()["data"]["path"] == ["甲", "乙", "丙"]

    def test_overviewRoute(self, client):
        resp = client.get(PREFIX + "/ontology/graph/overview")
        assert resp.status_code == 200
        assert resp.json()["data"]["edges"] == 3

    def test_communitiesRoute(self, client):
        resp = client.get(PREFIX + "/ontology/graph/communities")
        assert resp.status_code == 200
        assert [c["size"] for c in resp.json()["data"]["communities"]] == [3, 2]


# ── MCP 工具面（复用既有 asgi 范式：env 令牌 + _store 替身 + lifespan 驱动）──

@pytest.fixture()
def asgi_app(kb, monkeypatch):
    monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", _SERVICE_TOKEN)
    import neurova.mcp_ontology_server as mod

    monkeypatch.setattr(mod, "_store", lambda: kb)
    from neurova.mcp_ontology_server import build_ontology_mcp_asgi

    asgiEntry, lifespanCm = build_ontology_mcp_asgi()
    return {"asgi": asgiEntry, "lifespan": lifespanCm}


def _mcpSession(app, headers):
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 9))
    http_client = httpx.AsyncClient(transport=transport, headers=headers,
                                    base_url="http://127.0.0.1:9")

    @asynccontextmanager
    async def cm():
        async with streamable_http_client("http://127.0.0.1:9/",
                                          http_client=http_client) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                yield session

    return cm()


class TestGraphAnalyticsMcp:
    @pytest.mark.asyncio
    async def test_mcpGraphPathTool(self, asgi_app):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _mcpSession(asgi_app["asgi"], headers) as session:
            tools = await session.list_tools()
            assert "ontology_graph_path" in {t.name for t in tools.tools}
            res = await session.call_tool(
                "ontology_graph_path", {"from_label": "甲", "to_label": "丙"})
            payload = json.loads(res.content[0].text)
            assert payload["found"] is True
            assert payload["path"] == ["甲", "乙", "丙"]

    @pytest.mark.asyncio
    async def test_mcpGraphOverviewTool(self, asgi_app):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _mcpSession(asgi_app["asgi"], headers) as session:
            res = await session.call_tool("ontology_graph_overview",
                                          {"top_k": 5})
            payload = json.loads(res.content[0].text)
            assert payload["edges"] == 3 and payload["nodes"] == 5
