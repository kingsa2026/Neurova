"""
知识图谱 Demo 兜底移除（批次 2 / B3）

契约：空图/读取异常时返回空数组 + is_demo:false + 引导提示（hint），
不再返回任何硬编码 Demo 数据；图谱 manager 是唯一数据源。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import knowledge_graph_api as kga


class StubManager:
    """`KnowledgeGraphManager` 的手写替身，只补端点真正读的读面。

    `get_stats` 是端点报"真总量"的唯一出处，替身不带上它就不是同一份契约——
    宁可这里手写补齐，也不用 MagicMock 兜（自动造出来的属性会让统计口径与
    节点数各说各话，正是要防的那类假绿）。
    """

    def __init__(self, nodes=None, edges=None):
        self._nodes = nodes or {}
        self._edges = edges or {}

    def get_stats(self):
        from collections import Counter

        from neurova.cognitive_layers.knowledge_graph.manager import GraphStats

        def enumValue(item, attr):
            raw = getattr(item, attr, "")
            return str(getattr(raw, "value", raw))

        return GraphStats(
            node_count=len(self._nodes),
            edge_count=len(self._edges),
            node_type_counts=dict(
                Counter(enumValue(n, "node_type") for n in self._nodes.values())),
            relation_type_counts=dict(
                Counter(enumValue(e, "relation_type") for e in self._edges.values())),
        )


def _make_client(monkeypatch, manager):
    app = FastAPI()
    app.include_router(kga.router, prefix="/v1")
    monkeypatch.setattr(kga, "_get_kg_manager", lambda agent_id="default", tenant_id="default": manager)
    return TestClient(app)


def test_empty_graph_returns_empty_with_hint(monkeypatch):
    client = _make_client(monkeypatch, StubManager())
    resp = client.get("/v1/agent-x/knowledge-graph")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["nodes"] == []
    assert data["edges"] == []
    assert data["is_demo"] is False
    assert data.get("hint")


def test_empty_graph_has_no_demo_labels(monkeypatch):
    client = _make_client(monkeypatch, StubManager())
    resp = client.get("/v1/agent-x/knowledge-graph")
    text = resp.text
    assert "Machine Learning" not in text
    assert "Transformer" not in text


def test_nonempty_graph_returns_real_nodes(monkeypatch):
    class Node:
        node_id = "n1"
        label = "Real Node"
        node_type = "concept"
        properties = {"description": "from manager"}
        weight = 0.8
        created_at = None

    class Edge:
        source_id = "n1"
        target_id = "n1"
        relation_type = "related_to"
        weight = 0.5

    client = _make_client(monkeypatch, StubManager(nodes={"n1": Node()}, edges={"e1": Edge()}))
    resp = client.get("/v1/agent-x/knowledge-graph")
    data = resp.json()["data"]
    assert data["is_demo"] is False
    assert [n["label"] for n in data["nodes"]] == ["Real Node"]


def test_manager_exception_returns_empty_not_demo(monkeypatch):
    def boom(agent_id="default"):
        raise RuntimeError("manager offline")

    app = FastAPI()
    app.include_router(kga.router, prefix="/v1")
    monkeypatch.setattr(kga, "_get_kg_manager", boom)
    client = TestClient(app)
    resp = client.get("/v1/agent-x/knowledge-graph")
    data = resp.json()["data"]
    assert data["nodes"] == []
    assert data["is_demo"] is False
