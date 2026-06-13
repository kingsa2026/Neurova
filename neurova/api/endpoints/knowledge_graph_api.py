"""
知识图谱接口 - Knowledge Graph API Endpoint
"""

import logging
import typing

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Demo graph data ────────────────────────────────────

_DEMO_NODES = [
    {
        "id": "n1",
        "label": "Machine Learning",
        "type": "concept",
        "description": "Field of AI that learns from data",
        "weight": 0.9,
        "created_at": "2026-01-01T00:00:00",
    },
    {
        "id": "n2",
        "label": "Neural Networks",
        "type": "concept",
        "description": "Computational models inspired by brain",
        "weight": 0.85,
        "created_at": "2026-01-01T00:00:00",
    },
    {
        "id": "n3",
        "label": "Python",
        "type": "tool",
        "description": "Programming language",
        "weight": 0.8,
        "created_at": "2026-01-02T00:00:00",
    },
    {
        "id": "n4",
        "label": "Transformer",
        "type": "architecture",
        "description": "Attention-based neural network",
        "weight": 0.95,
        "created_at": "2026-01-03T00:00:00",
    },
    {
        "id": "n5",
        "label": "Fine-tuning",
        "type": "technique",
        "description": "Adapting pre-trained models",
        "weight": 0.7,
        "created_at": "2026-01-04T00:00:00",
    },
]
_DEMO_EDGES = [
    {"source": "n1", "target": "n2", "relation": "includes", "weight": 0.9},
    {"source": "n2", "target": "n4", "relation": "implements", "weight": 0.85},
    {"source": "n3", "target": "n1", "relation": "used_for", "weight": 0.8},
    {"source": "n4", "target": "n5", "relation": "supports", "weight": 0.7},
    {"source": "n1", "target": "n5", "relation": "technique", "weight": 0.75},
]

_GRAPH_STORE: typing.Dict[str, dict] = {}  # agent_id -> {"nodes": [], "edges": []}


def _get_request_id(request) -> str:
    return getattr(request.state, "request_id", "unknown")


@router.get("/{agent_id}/knowledge-graph")
async def get_knowledge_graph(agent_id: str, request: Request, limit: int = Query(100, ge=1, le=500)):
    """获取 Agent 的知识图谱数据"""
    graph = _GRAPH_STORE.get(agent_id)
    if not graph:
        # Return demo data
        nodes = _DEMO_NODES[:limit]
        edges = [
            e
            for e in _DEMO_EDGES
            if e["source"] in [n["id"] for n in nodes] and e["target"] in [n["id"] for n in nodes]
        ]
    else:
        nodes = graph.get("nodes", [])[:limit]
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in graph.get("edges", []) if e["source"] in node_ids and e["target"] in node_ids]

    return {
        "code": 0,
        "message": "success",
        "data": {"nodes": nodes, "edges": edges, "total_nodes": len(nodes), "total_edges": len(edges)},
    }


@router.get("/{agent_id}/knowledge-graph/search")
async def search_graph_nodes(agent_id: str, q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=100)):
    """搜索知识图谱中的节点"""
    graph = _GRAPH_STORE.get(agent_id)
    nodes = graph.get("nodes", []) if graph else _DEMO_NODES

    q_lower = q.lower()
    matches = [n for n in nodes if q_lower in n.get("label", "").lower() or q_lower in n.get("description", "").lower()]
    return {"code": 0, "message": "success", "data": {"nodes": matches[:limit], "total": len(matches), "query": q}}


@router.get("/{agent_id}/knowledge-graph/nodes/{node_id}")
async def get_graph_node_detail(agent_id: str, node_id: str):
    """获取指定节点的详细信息及关联节点"""
    graph = _GRAPH_STORE.get(agent_id)
    nodes = graph.get("nodes", []) if graph else _DEMO_NODES
    edges = graph.get("edges", []) if graph else _DEMO_EDGES

    node = next((n for n in nodes if n["id"] == node_id), None)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    related = [e for e in edges if e["source"] == node_id or e["target"] == node_id]
    related_node_ids = set()
    for e in related:
        related_node_ids.add(e["source"] if e["target"] == node_id else e["target"])
    related_nodes = [n for n in nodes if n["id"] in related_node_ids]

    return {
        "code": 0,
        "message": "success",
        "data": {"node": node, "edges": related, "related_nodes": related_nodes},
    }
