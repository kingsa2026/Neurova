"""
知识图谱接口 - Knowledge Graph API Endpoint

数据源统一：接入真实 KnowledgeGraphManager（cognitive_layers/knowledge_graph/
manager.py）。此前端点只读内存 _GRAPH_STORE（且无任何写入端点），
空图时永远兜底硬编码 Demo 数据——真实图谱实现完全闲置。

批次 2（RAG 演进）：Demo 兜底已移除——空图/读取异常一律返回空数组 +
is_demo:false + 引导提示（hint），图谱 manager 是唯一数据源。
（"知识条目→图谱节点"的写入链路见 neurova/knowledge/graph_bridge.py，批次 3）
"""

from neurova.core.logger import get_logger
import typing
from typing import Dict

from fastapi import APIRouter, HTTPException, Query, Request

logger = get_logger(__name__)
router = APIRouter()


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
    """获取 Agent 的知识图谱数据（真实 KnowledgeGraphManager 唯一数据源；空图返回空数组+引导）"""
    _get_request_id(request)
    try:
        manager = _get_kg_manager(agent_id)
        data = _graph_payload(manager, limit) if manager else {}
    except Exception as e:  # noqa: BLE001
        logger.warning("读取知识图谱失败，返回空图谱: %s", e)
        data = {}

    nodes = data.get("nodes") or []
    edges = data.get("edges") or []

    return {
        "code": 0,
        "message": "success",
        "data": {
            "nodes": nodes,
            "edges": edges,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "is_demo": False,
            "hint": "" if nodes else "图谱为空：导入知识或通过知识条目抽取生成图谱节点（见 graph_bridge）",
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


# ══════════════════════════════════════════════════════════════
# P1-1 实体消解：人工队列 + 攒批裁决（仅管理员）
# ══════════════════════════════════════════════════════════════

from fastapi import Depends  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from neurova.api.auth import get_current_user_or_service  # noqa: E402
from neurova.knowledge.resolution import EntityResolver  # noqa: E402


class ResolutionDecisionRequest(BaseModel):
    decision: str = Field(..., description="merged=同一实体（执行合并） / kept=不同实体")


def _get_resolver(agent_id: str) -> EntityResolver:
    return EntityResolver(_get_kg_manager(agent_id))


def _admin_or_403(current_user) -> None:
    if (current_user or {}).get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作实体消解")


@router.get("/{agent_id}/knowledge-graph/resolution/reviews")
async def list_resolution_reviews(
    agent_id: str,
    request: Request,
    status: str = Query("pending", description="pending 待审 / resolved 历史"),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """实体消解人工队列（灰区对：高置信已自动处置，低置信转人工）"""
    _admin_or_403(current_user)
    resolver = _get_resolver(agent_id)
    return {"code": 0, "data": {"reviews": resolver.list_human_reviews(status=status)}}


@router.post("/{agent_id}/knowledge-graph/resolution/reviews/{review_id}/resolve")
async def resolve_resolution_review(
    agent_id: str,
    review_id: str,
    body: ResolutionDecisionRequest,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """人工裁决灰区对：merged 执行合并（可 undo_merge 回滚），kept 关闭不再提议"""
    _admin_or_403(current_user)
    resolver = _get_resolver(agent_id)
    try:
        ok = resolver.resolve_human(review_id, body.decision, decided_by=str(current_user.get("user_id", "")))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Review '%s' not found or already resolved" % review_id)
    return {"code": 0, "message": "resolved (%s)" % body.decision}


@router.post("/{agent_id}/knowledge-graph/resolution/run")
async def run_resolution(
    agent_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """运行一轮消解：灰区召回 + 攒批裁决（未配 LLM 时灰区对全部转人工）"""
    _admin_or_403(current_user)
    resolver = _get_resolver(agent_id)

    # LLM 调用器可选：失败/未配置时裁决全部转人工（消解绝不阻断）
    llm_call = None
    try:
        from neurova.api.endpoints.knowledge import _default_llm_call

        llm_call = _default_llm_call(request)
    except Exception as e:  # noqa: BLE001
        logger.info("实体消解：LLM 调用器不可用，灰区对转人工: %s", e)

    result = resolver.run_adjudication(llm_call=llm_call)
    grey = resolver.find_candidates()["grey"]
    return {
        "code": 0,
        "data": {"result": result, "pending_grey": len(grey), "human_reviews": len(resolver.list_human_reviews())},
    }
