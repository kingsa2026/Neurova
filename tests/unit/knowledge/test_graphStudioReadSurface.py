# -*- coding: utf-8 -*-
"""图谱工作台读面（S0 前提）：`limit` 截断过的图必须自己说清"还有多少没给"。

修复前 `total_nodes = len(nodes)`，而 `nodes` 已经按 limit 切过——被裁的图与完整的图
在读面上长得一模一样，前端只能猜。空图提示与大图提示都要靠这组真读数，
所以统计口径的唯一出处是 `manager.get_stats()`，端点不自己重算一遍。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PREFIX = "/api/v1/agents"


def _manager(nodeCount: int, edgeCountPerNode: int = 1):
    from neurova.cognitive_layers.knowledge_graph.manager import (
        KnowledgeGraphManager,
        NodeType,
        RelationType,
    )

    mgr = KnowledgeGraphManager(auto_save=False)
    ids = [
        mgr.add_node(label="节点%d" % i, node_type=NodeType.CONCEPT).node_id
        for i in range(nodeCount)
    ]
    for i, src in enumerate(ids):
        for k in range(edgeCountPerNode):
            dst = ids[(i + k + 1) % len(ids)] if ids else None
            if dst and dst != src:
                mgr.add_edge(src, dst, relation_type=RelationType.RELATED_TO)
    return mgr


@pytest.fixture()
def makeClient(monkeypatch):
    """按 manager 造 client；桩由 pytest 的 monkeypatch 自动回收，不外泄到别的档。"""
    import neurova.api.endpoints.knowledge_graph_api as kg_mod

    def _make(manager):
        monkeypatch.setattr(
            kg_mod, "_get_kg_manager",
            lambda agent_id="default", tenant_id="default": manager)
        app = FastAPI()
        app.include_router(kg_mod.router, prefix=PREFIX)
        return TestClient(app)

    return _make


def _data(client, limit: int):
    resp = client.get(PREFIX + "/default/knowledge-graph", params={"limit": limit})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


class TestTrueTotalsUnderLimit:
    def testCappedGraphReportsItsRealSize(self, makeClient):
        client = makeClient(_manager(nodeCount=6, edgeCountPerNode=1))

        data = _data(client, limit=3)

        assert len(data["nodes"]) == 3
        assert data["total_nodes"] == 6, "被裁过的图仍报裁剪后的条数＝前端无从分辨"
        assert data["truncated"] is True

    def testUncappedGraphIsNotMarkedTruncated(self, makeClient):
        client = makeClient(_manager(nodeCount=3, edgeCountPerNode=0))

        data = _data(client, limit=100)

        assert data["total_nodes"] == 3
        assert data["truncated"] is False

    def testEdgeTotalsSurviveTheNodeSieve(self, makeClient):
        """边要先接在两头都在场的节点上才算数——真总量按 manager 的边数报，
        给出的边数按裁剪后的子图报，两者各说各的事，不能混成一个数。"""
        manager = _manager(nodeCount=5, edgeCountPerNode=1)
        client = makeClient(manager)

        data = _data(client, limit=2)

        assert data["total_edges"] == manager.get_stats().edge_count
        assert len(data["edges"]) <= data["total_edges"]


class TestStatsComeFromTheManager:
    def testStatsMatchTheSingleSource(self, makeClient):
        manager = _manager(nodeCount=4, edgeCountPerNode=1)
        client = makeClient(manager)

        data = _data(client, limit=100)

        assert data["stats"] == manager.get_stats().to_dict()

    def testTypeDistributionIsReadableForColouring(self, makeClient):
        client = makeClient(_manager(nodeCount=4, edgeCountPerNode=0))

        counts = _data(client, limit=100)["stats"]["node_type_counts"]

        assert counts.get("concept") == 4


class TestEmptyGraphHintStaysHonest:
    def testEmptyGraphIsNotTruncatedButIsExplained(self, makeClient):
        client = makeClient(_manager(nodeCount=0, edgeCountPerNode=0))

        data = _data(client, limit=100)

        assert data["total_nodes"] == 0
        assert data["truncated"] is False
        assert data["hint"]
        assert data["is_demo"] is False

    def testManagerAbsentDegradesToEmptyNotError(self, makeClient):
        """图谱解析失败仍按空图给（既有契约），但总量必须一致地是 0。"""
        client = makeClient(None)

        data = _data(client, limit=100)

        assert data["total_nodes"] == 0
        assert data["truncated"] is False
        assert data["stats"]["node_count"] == 0
