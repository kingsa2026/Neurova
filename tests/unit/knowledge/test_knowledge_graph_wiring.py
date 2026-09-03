"""knowledge_graph_api 接入真实 KnowledgeGraphManager 回归测试（TDD）

修复前：端点只读内存 _GRAPH_STORE（无任何写入端点）+ 永远兜底硬编码
Demo 图——真实实现 cognitive_layers/knowledge_graph/manager.py (~983 行)
完全闲置。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client_factory():
    from neurova.api.endpoints import knowledge_graph_api

    def _make(manager):
        app = FastAPI()
        app.include_router(knowledge_graph_api.router, prefix="/api/v1/agents")
        import neurova.api.endpoints.knowledge_graph_api as kg_mod

        mp = pytest.MonkeyPatch()
        mp.setattr(kg_mod, "_get_kg_manager", lambda agent_id="default": manager)
        client = TestClient(app)
        client._mp = mp  # type: ignore[attr-defined]
        return client

    return _make


def _seeded_manager():
    from neurova.cognitive_layers.knowledge_graph.manager import (
        KnowledgeGraphManager,
        NodeType,
        RelationType,
    )

    mgr = KnowledgeGraphManager(auto_save=False)
    n1 = mgr.add_node(label="青海湖", node_type=NodeType.CONCEPT, properties={"description": "高原湖泊"})
    n2 = mgr.add_node(label="旅行计划")
    mgr.add_edge(n1.node_id, n2.node_id, relation_type=RelationType.RELATED_TO)
    return mgr


def test_graph_endpoint_returns_real_nodes(client_factory):
    client = client_factory(_seeded_manager())
    r = client.get("/api/v1/agents/default/knowledge-graph")
    assert r.status_code == 200
    data = r.json()["data"]
    labels = {n["label"] for n in data["nodes"]}
    assert "青海湖" in labels and "旅行计划" in labels
    assert len(data["edges"]) == 1
    assert data.get("is_demo") is not True


def test_search_hits_real_graph(client_factory):
    client = client_factory(_seeded_manager())
    r = client.get("/api/v1/agents/default/knowledge-graph/search", params={"q": "青海"})
    assert r.status_code == 200
    nodes = r.json()["data"]["nodes"]
    assert any(n["label"] == "青海湖" for n in nodes)


def test_empty_graph_returns_empty_no_demo(client_factory):
    """批次 2（RAG 演进 B3）：空图谱不再兜底 Demo 数据——
    返回空数组 + is_demo:false + 引导提示，图谱 manager 是唯一数据源"""
    from neurova.cognitive_layers.knowledge_graph.manager import KnowledgeGraphManager

    client = client_factory(KnowledgeGraphManager(auto_save=False))
    r = client.get("/api/v1/agents/default/knowledge-graph")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data.get("is_demo") is False
    assert data.get("nodes") == []
    assert data.get("hint")
