"""DEAD-11：图谱遍历收口到 manager 读口，端点不再直摸私有存储。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge_graph_api as kg_module
from neurova.cognitive_layers.knowledge_graph.manager import (
    KnowledgeGraphManager,
    NodeType,
    RelationType,
)


USER = {"user_id": "1", "username": "a", "role": "admin", "tenant_id": "t1"}


def _seededGraph():
    graph = KnowledgeGraphManager(auto_save=False)
    a = graph.add_node(label="A", node_type=NodeType.CONCEPT).node_id
    b = graph.add_node(label="B", node_type=NodeType.CONCEPT).node_id
    c = graph.add_node(label="C", node_type=NodeType.ENTITY).node_id
    d = graph.add_node(label="D", node_type=NodeType.CONCEPT).node_id
    for source, target in ((a, b), (b, c), (c, d)):
        graph.add_edge(source, target, relation_type=RelationType.RELATED_TO)
    return graph, {"A": a, "B": b, "C": c, "D": d}


def test_managerReadMethodsReturnEndpointPayloads():
    graph, ids = _seededGraph()

    payload = graph.get_graph(limit=3)
    assert payload["nodes"]
    assert {"id", "label", "type", "description"} <= set(payload["nodes"][0])
    assert "node_id" not in payload["nodes"][0]

    details = graph.get_node_details(ids["B"])
    assert details["node"]["id"] == ids["B"]
    assert {edge["source"] for edge in details["edges"]} == {ids["A"], ids["B"]}
    assert {node["id"] for node in details["related_nodes"]} == {ids["A"], ids["C"]}


def test_managerSubgraphOwnsFocusHopsTypeAndLimitSemantics():
    graph, ids = _seededGraph()

    oneHop = graph.get_subgraph(focus=ids["B"], hops=1, limit=3)
    assert {node["label"] for node in oneHop["nodes"]} == {"A", "B", "C"}
    assert oneHop["dropped_by_limit"] is False

    throughFilteredNode = graph.get_subgraph(
        focus=ids["B"], hops=2, types={"concept"}, limit=3,
    )
    assert {node["label"] for node in throughFilteredNode["nodes"]} == {"A", "B", "D"}

    clipped = graph.get_subgraph(focus=ids["B"], hops=2, limit=2)
    assert len(clipped["nodes"]) == 2
    assert clipped["dropped_by_limit"] is True

    wholeGraph = graph.get_subgraph(limit=2)
    assert len(wholeGraph["nodes"]) == 2
    assert wholeGraph["dropped_by_limit"] is True


class ReadSurfaceOnlyManager:
    """只暴露 manager 读口；缺少 _nodes/_edges 时端点仍必须完成委托。"""

    def __init__(self, delegate):
        self._delegate = delegate

    def get_graph(self, **kwargs):
        return self._delegate.get_graph(**kwargs)

    def get_node_details(self, node_id):
        return self._delegate.get_node_details(node_id)

    def get_subgraph(self, **kwargs):
        return self._delegate.get_subgraph(**kwargs)

    def get_stats(self):
        return self._delegate.get_stats()

    def nodePayload(self, node):
        return self._delegate.nodePayload(node)

    def nodesSnapshot(self, limit=2000):
        return self._delegate.nodesSnapshot(limit=limit)

    def search_nodes(self, query, **kwargs):
        return self._delegate.search_nodes(query, **kwargs)


def test_endpointsDelegateGraphTraversalToManager(monkeypatch):
    graph, ids = _seededGraph()
    monkeypatch.setattr(
        kg_module,
        "_get_kg_manager",
        lambda agent_id="default", tenant_id="default": ReadSurfaceOnlyManager(graph),
    )
    app = FastAPI()
    app.include_router(kg_module.router, prefix="/api/v1/agents")
    app.dependency_overrides[knowledge_auth.get_current_user_or_default] = lambda: dict(USER)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: dict(USER)
    client = TestClient(app)

    graphResponse = client.get("/api/v1/agents/default/knowledge-graph")
    assert graphResponse.status_code == 200, graphResponse.text
    assert {node["label"] for node in graphResponse.json()["data"]["nodes"]} == {"A", "B", "C", "D"}

    detailResponse = client.get(f"/api/v1/agents/default/knowledge-graph/nodes/{ids['B']}")
    assert detailResponse.status_code == 200, detailResponse.text
    assert {node["label"] for node in detailResponse.json()["data"]["related_nodes"]} == {"A", "C"}

    subgraphResponse = client.get(
        "/api/v1/agents/default/subgraph",
        params={"focus": ids["B"], "hops": 1},
    )
    assert subgraphResponse.status_code == 200, subgraphResponse.text
    assert {node["label"] for node in subgraphResponse.json()["data"]["nodes"]} == {"A", "B", "C"}
