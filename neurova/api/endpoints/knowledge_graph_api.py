"""
知识图谱接口 - Knowledge Graph API Endpoint

数据源统一：接入真实 KnowledgeGraphManager（cognitive_layers/knowledge_graph/
manager.py）。此前端点只读内存 _GRAPH_STORE（且无任何写入端点），
空图时永远兜底硬编码 Demo 数据——真实图谱实现完全闲置。

空图谱仍返回 Demo 兜底（避免前端页面空白），但响应显式携带
`is_demo: true` 供前端辨识。
"""

from neurova.core.logger import get_logger
import typing

from fastapi import APIRouter, HTTPException, Query, Request

logger = get_logger(__name__)
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


def _get_request_id(request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _get_kg_manager(agent_id: str = "default"):
    """解析 Agent 对应的真实知识图谱管理器。

    优先取运行时 Agent 挂载的实例，否则用全局单例。
    """
    try:
        from neurova.api.app_state import get_app_state

        state = get_app_state()
        agent = (state or {}).get("agents", {}).get(agent_id)
        manager = getattr(agent, "knowledge_graph_manager", None)
        if manager is not None:
            return manager
    except Exception:  # noqa: BLE001
        pass

    from neurova.cognitive_layers.knowledge_graph.manager import (
        get_knowledge_graph_manager,
    )

    return get_knowledge_graph_manager()


def _node_to_dict(node) -> dict:
    props = getattr(node, "properties", {}) or {}
    created_at = getattr(node, "created_at", None)
    if created_at is not None and not isinstance(created_at, (int, float)):
        created_at = created_at.isoformat()
    return {
        "id": node.node_id,
        "label": node.label,
        "type": getattr(node.node_type, "value", str(node.node_type)),
        "description": props.get("description", ""),
        "weight": node.weight,
        "created_at": created_at,
    }


def _edge_to_dict(edge) -> dict:
    return {
        "source": edge.source_id,
        "target": edge.target_id,
        "relation": getattr(edge.relation_type, "value", str(edge.relation_type)),
        "weight": edge.weight,
    }


def _graph_payload(manager, limit: int) -> dict:
    nodes = [_node_to_dict(n) for n in list(manager._nodes.values())[:limit]]
    node_ids = {n["id"] for n in nodes}
    edges = [
        _edge_to_dict(e)
        for e in manager._edges.values()
        if e.source_id in node_ids and e.target_id in node_ids
    ]
    return {"nodes": nodes, "edges": edges}


@router.get("/{agent_id}/knowledge-graph")
async def get_knowledge_graph(agent_id: str, request: Request, limit: int = Query(100, ge=1, le=500)):
    """获取 Agent 的知识图谱数据（真实 KnowledgeGraphManager；空图兜底 Demo 并标记）"""
    _get_request_id(request)
    is_demo = False
    try:
        manager = _get_kg_manager(agent_id)
        data = _graph_payload(manager, limit) if manager else {}
    except Exception as e:  # noqa: BLE001
        logger.warning("读取知识图谱失败，降级 Demo: %s", e)
        data = {}

    if not data.get("nodes"):
        nodes = _DEMO_NODES[:limit]
        edges = [
            e
            for e in _DEMO_EDGES
            if e["source"] in [n["id"] for n in nodes] and e["target"] in [n["id"] for n in nodes]
        ]
        is_demo = True
    else:
        nodes = data["nodes"]
        edges = data["edges"]

    return {
        "code": 0,
        "message": "success",
        "data": {
            "nodes": nodes,
            "edges": edges,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "is_demo": is_demo,
        },
    }


@router.get("/{agent_id}/knowledge-graph/search")
async def search_graph_nodes(
    agent_id: str, request: Request, q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=100)
):
    """搜索知识图谱中的节点（走真实 search_nodes 索引）"""
    _get_request_id(request)
    try:
        manager = _get_kg_manager(agent_id)
        found = manager.search_nodes(q, limit=limit) if manager else []
        matches = [_node_to_dict(n) for n in found]
    except Exception as e:  # noqa: BLE001
        logger.warning("知识图谱搜索失败: %s", e)
        matches = []

    return {"code": 0, "message": "success", "data": {"nodes": matches, "total": len(matches), "query": q}}


@router.get("/{agent_id}/knowledge-graph/nodes/{node_id}")
async def get_graph_node_detail(agent_id: str, request: Request, node_id: str):
    """获取指定节点的详细信息及关联节点"""
    _get_request_id(request)
    try:
        manager = _get_kg_manager(agent_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))

    node = manager.get_node(node_id) if manager else None
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    related_edges = []
    related_node_ids = set()
    for e in manager._edges.values():
        if e.source_id == node_id or e.target_id == node_id:
            related_edges.append(_edge_to_dict(e))
            related_node_ids.add(e.source_id if e.target_id == node_id else e.target_id)

    related_nodes = [
        _node_to_dict(manager._nodes[nid]) for nid in related_node_ids if nid in manager._nodes
    ]

    return {
        "code": 0,
        "message": "success",
        "data": {
            "node": _node_to_dict(node),
            "edges": related_edges,
            "related_nodes": related_nodes,
        },
    }
