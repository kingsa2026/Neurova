# -*- coding: utf-8 -*-
"""本体图分析只读面（C 维增强批 P1-3）：k 跳邻域 / 最短路 / 度概览 / 社区检测。

定位（教义第 6/7 条：只编排既有单点实现，不造第二套分析栈）：

- 图形状与 `community_graph._readGraph` 同一份数据面：主体
  （knowledge_subjects.canonical_label）沿 active triple 的 object_term 展开，
  **无向**处理（邻域/最短路按探索语义双向走）；
- 社区检测**直接复用** `community_graph._labelPropagation`（全仓唯一的标签
  传播实现），本模块只做只读投影不落库（持久化仍是 CommunityGraphBuilder
  的职责）；
- 逐跳/最短路用 Python BFS（边集一次读入，条数封顶），规模边界诚实声明：
  这是治理/诊断用的只读分析面，不是大规模图计算引擎（对方参照系 ae 的
  中心性/链路预测等重分析不在本仓承诺面）。

全部函数只读（SELECT），零事实写入；agentId 传 None 表示本租户全 agent。
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

from neurova.core.logger import get_logger
from neurova.core.tenant_scope import tenant_sql_where

logger = get_logger(__name__)

#: 跳数/深度上限（诊断面边界，防呆不防算）
MAX_HOPS = 6
#: 边集扫描上限：超过即截断并在回执标 truncated（分析面不做全库无限扫描）
EDGE_SCAN_CAP = 50000
#: 邻域/概览返回节点数上限
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000


def _readEdges(store: Any, agentId: Optional[str],
               tenantId: str) -> Tuple[List[Tuple[str, str, str]], bool]:
    """读边集：(主体规范标签, 谓词, 客体词) 三元组列表（与 community_graph
    的图数据面同形）。返回 (edges, truncated)。"""
    fClause, fParams = tenant_sql_where(str(tenantId or "default"), alias="f")
    sql = ("SELECT s.canonical_label AS src, f.predicate_term_id AS pred,"
           " f.object_term AS dst"
           " FROM knowledge_facts f JOIN knowledge_subjects s"
           " ON s.subject_key = f.subject_key"
           " WHERE " + fClause + " AND f.status = 'active'"
           " AND f.record_kind = 'triple'")
    params: List[Any] = list(fParams)
    if agentId:
        sql += " AND f.agent_id = ?"
        params.append(str(agentId))
    sql += " ORDER BY s.canonical_label, f.predicate_term_id, f.object_term"
    with store._lock:
        rows = store._conn.execute(
            sql + (" LIMIT %d" % (EDGE_SCAN_CAP + 1,)), params).fetchall()
    truncated = len(rows) > EDGE_SCAN_CAP
    return [(str(r["src"]), str(r["pred"]), str(r["dst"]))
            for r in rows[:EDGE_SCAN_CAP]], truncated


def _adjacency(edges: List[Tuple[str, str, str]]):
    """无向邻接：label → [(邻居, 谓词, 是否正向边)]；孤立边端点也入册。"""
    adj: Dict[str, List[Tuple[str, str, bool]]] = {}
    for src, pred, dst in edges:
        adj.setdefault(src, []).append((dst, pred, True))
        adj.setdefault(dst, []).append((src, pred, False))
    return adj


def _clampHops(maxHops: Optional[int]) -> int:
    try:
        return max(1, min(int(maxHops if maxHops is not None else 2), MAX_HOPS))
    except (TypeError, ValueError):
        return 2


def _clampLimit(limit: Optional[int]) -> int:
    try:
        return max(1, min(int(limit if limit is not None else DEFAULT_LIMIT),
                          MAX_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def kHopNeighbors(store: Any, *, agentId: Optional[str], tenantId: str,
                  startLabel: str, maxHops: Optional[int] = 2,
                  limit: Optional[int] = DEFAULT_LIMIT) -> Dict[str, Any]:
    """k 跳邻域：从 startLabel 出发无向 BFS，返回逐层节点与触及边。"""
    hops = _clampHops(maxHops)
    cap = _clampLimit(limit)
    edges, truncated = _readEdges(store, agentId, tenantId)
    adj = _adjacency(edges)
    start = str(startLabel or "").strip()
    if start not in adj:
        return {"start": start, "max_hops": hops, "nodes": [], "edges": [],
                "truncated": truncated, "limit": cap}
    hopOf: Dict[str, int] = {start: 0}
    order: List[str] = [start]
    queue = deque([start])
    touched: List[Tuple[str, str, str]] = []
    while queue:
        node = queue.popleft()
        if hopOf[node] >= hops:
            continue
        for neighbor, pred, forward in adj.get(node, []):
            edge = ((node, pred, neighbor) if forward
                    else (neighbor, pred, node))
            touched.append(edge)
            if neighbor not in hopOf:
                hopOf[neighbor] = hopOf[node] + 1
                order.append(neighbor)
                queue.append(neighbor)
    nodes = [{"label": label, "hop": hopOf[label]} for label in order[:cap]]
    keep = {n["label"] for n in nodes}
    outEdges = [{"src": src, "predicate": pred, "dst": dst}
                for src, pred, dst in touched
                if src in keep and dst in keep][:cap]
    return {"start": start, "max_hops": hops, "nodes": nodes,
            "edges": outEdges, "truncated": truncated, "limit": cap}


def shortestPath(store: Any, *, agentId: Optional[str], tenantId: str,
                 fromLabel: str, toLabel: str,
                 maxDepth: Optional[int] = MAX_HOPS) -> Dict[str, Any]:
    """最短路：无向 BFS＋父指针；不可达/参数为空如实 found=False。"""
    depth = _clampHops(maxDepth)
    src = str(fromLabel or "").strip()
    dst = str(toLabel or "").strip()
    if not src or not dst:
        return {"found": False, "path": [], "hops": 0,
                "reason": "from_label/to_label 不能为空"}
    edges, _truncated = _readEdges(store, agentId, tenantId)
    adj = _adjacency(edges)
    if src == dst and src:
        return {"found": True, "path": [src], "hops": 0}
    parent: Dict[str, str] = {src: ""}
    depthOf: Dict[str, int] = {src: 0}
    queue = deque([(src, 0)])
    while queue:
        node, nodeDepth = queue.popleft()
        if nodeDepth >= depth:
            continue
        for neighbor, _pred, _forward in adj.get(node, []):
            if neighbor in parent:
                continue
            parent[neighbor] = node
            depthOf[neighbor] = nodeDepth + 1
            if neighbor == dst:
                path = [dst]
                while parent[path[-1]]:
                    path.append(parent[path[-1]])
                path.reverse()
                return {"found": True, "path": path, "hops": len(path) - 1}
            queue.append((neighbor, nodeDepth + 1))
    return {"found": False, "path": [], "hops": 0,
            "reason": "%d 跳内不可达" % depth}


def graphOverview(store: Any, *, agentId: Optional[str], tenantId: str,
                  topK: Optional[int] = 10) -> Dict[str, Any]:
    """图概览：节点/边计数、谓词分布、无向度 Top-K（治理诊断读面）。"""
    try:
        k = max(1, min(int(topK if topK is not None else 10), 50))
    except (TypeError, ValueError):
        k = 10
    edges, truncated = _readEdges(store, agentId, tenantId)
    adj = _adjacency(edges)
    degrees = sorted(((label, len(neighbors))
                      for label, neighbors in adj.items()),
                     key=lambda item: (-item[1], item[0]))[:k]
    predCount: Dict[str, int] = {}
    for _src, pred, _dst in edges:
        predCount[pred] = predCount.get(pred, 0) + 1
    predicates = sorted(predCount.items(),
                        key=lambda item: (-item[1], item[0]))[:k]
    return {"nodes": len(adj), "edges": len(edges), "truncated": truncated,
            "top_degree": [{"label": label, "degree": degree}
                           for label, degree in degrees],
            "predicates": [{"term": term, "count": count}
                           for term, count in predicates],
            "top_k": k}


def detectOntologyCommunities(store: Any, *, agentId: Optional[str],
                              tenantId: str,
                              maxCommunities: Optional[int] = 20
                              ) -> Dict[str, Any]:
    """社区检测（只读投影）：复用 community_graph._labelPropagation 唯一实现，
    对本体事实图做标签传播，返回社区划分（不落 ontology_communities 表——
    持久化是 CommunityGraphBuilder 的职责，本面只读）。"""
    from neurova.knowledge.community_graph import _labelPropagation

    try:
        cap = max(1, min(int(maxCommunities if maxCommunities is not None
                             else 20), 100))
    except (TypeError, ValueError):
        cap = 20
    edges, truncated = _readEdges(store, agentId, tenantId)
    nodesSet: Set[str] = set()
    for src, _pred, dst in edges:
        nodesSet.add(src)
        nodesSet.add(dst)
    nodes = sorted(nodesSet)
    groups = _labelPropagation(nodes, [(a, b) for a, _p, b in edges])
    communities = [{"members": members, "size": len(members)}
                   for members in groups[:cap]]
    return {"communities": communities,
            "count": len(groups), "truncated": truncated,
            "nodes": len(nodes), "edges": len(edges)}
