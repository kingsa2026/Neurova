# -*- coding: utf-8 -*-
"""P1-1 蜂群协作拓扑图投影（v2 全边集：spawn+依赖+审批+候选，拍板 D-A）。

**服务端只出投影，前端只做渲染**（P2-4 契约）：一切语义解析在本模块完成，浏览器
拿 render-ready 的 ``{nodes, edges, meta}``，不 import 事件语义、不做 trace 解释。
本模块是**纯折叠**：输入=agent_runs 台账行 + H-4 事件 + 审批记录 + P2-3 候选投影，
输出=纯结构；不落新表、不写新账（事实源仍是台账、事件账本、审批审计/ApprovalManager、
候选板投影）。

节点三类（同一字段集，``nodeType`` 判别）：
- run 节点（``nodeType="run"``）：id=subagent_id；字段来自台账行 + 事件 lineage
  （depth/parent）+ 可选 memberProfiles 富化（团队名册显示名/外部执行体标识/内存态）；
- 审批卡（``nodeType="approval"``）：id=``approval:<request_id>``，从属挂到发起 run；
- 候选卡（``nodeType="candidate"``）：id=``candidate:<candidate_id>``，从属挂到发起 run。

边四类（v2 全边集）：
- spawn：parent→child（H-4 事件 lineage.parent_subagent_id）；
- dependency：TaskUnit.dependencies 的解析结果（dispatch_team 同源映射后的
  subagent_id；来自内存 run 态，重启后缺席=如实缺边，不凭空补）；
- approval：run→审批卡，带 level 与裁决态；
- candidate：run→候选卡，带候选状态。

诚实标注（meta）：truncated=runs 超上限被截；candidates_incomplete=候选账本缺事件；
counts.danglingEdges=端点不在节点集而被丢弃的边数（vue-flow 本就会丢悬空边，
这里把"丢了多少"说出口）。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, TypedDict

#: run 节点状态取值域：台账状态（queued/running/parked/completed/failed/cancelled）
#: ∪ 蜂群内存态（pending/running/in_review/completed/failed）。前端着色映射对齐
#: LEDGER_TO_WINDOW_STATUS（useSubAgentWindows.ts），契约由 test_swarm_graph_contract 钉住。


class GraphNode(TypedDict):
    """图节点（P2-4 服务端单源；前端 TS 类型手抄对齐，漂移即红）。

    run 节点：id=subagent_id、run_id=台账 run_id；
    卡节点：id=approval:<request_id> / candidate:<candidate_id>、
    run_id=所属 run 的 subagent_id（供前端回链）。
    """

    id: str
    nodeType: str          # run | approval | candidate
    run_id: str
    member_name: str       # run=成员显示名；审批卡=操作摘要；候选卡=产物键摘要
    kind: str              # internal | external（仅 run 节点；卡节点空串）
    executor_tool: str     # 外部成员执行体工具标识（仅 run 节点）
    status: str            # run 状态 / 审批裁决态(approved|rejected|pending) / 候选状态
    depth: int             # 派生深度（0=未知）
    team_id: str
    started_at: float      # 卡节点=请求/提交时刻
    finished_at: float     # 卡节点=裁决时刻（未决 0）
    duration_ms: float
    error_type: str
    level: str             # 审批卡：L0/L1/L2
    decision: str          # 审批卡：approve/reject
    decided_by: str        # 审批卡：裁决人
    request_id: str        # 审批卡：审批单 id
    candidate_id: str      # 候选卡：候选 id
    artifact_keys: List[str]  # 候选卡：主张产物键
    base_revision: int     # 候选卡：CAS 基准
    note: str              # 候选卡：驳回/冲突说明


#: 图边（"from" 是保留字，函数式 TypedDict 以字符串键声明；序列化键即 "from"/"to"）
GraphEdge = TypedDict("GraphEdge", {
    "id": str,
    "type": str,           # spawn | dependency | approval | candidate
    "from": str,           # 源节点 id
    "to": str,             # 目标节点 id
    "level": str,          # 审批边：L0/L1/L2
    "status": str,         # 审批边=裁决态；候选边=候选状态
    "decision": str,       # 审批边：approve/reject
    "decided_by": str,     # 审批边：裁决人
})


class GraphMeta(TypedDict):
    revision: int              # 候选板集成版本（P2-3 投影）
    generated_at: float
    truncated: bool            # runs 超上限诚实标注
    candidates_incomplete: bool  # 候选账本缺事件（P2-3 incomplete 透传）
    counts: Dict[str, int]


class GraphProjection(TypedDict):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    meta: GraphMeta


def buildSwarmGraph(
    runRows: List[Dict[str, Any]],
    eventsByRun: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    memberProfiles: Optional[Dict[str, Dict[str, Any]]] = None,
    taskUnits: Optional[Dict[str, Dict[str, Any]]] = None,
    approvals: Optional[List[Dict[str, Any]]] = None,
    candidateBoard: Optional[Dict[str, Any]] = None,
    maxNodes: int = 200,
) -> GraphProjection:
    """折叠台账行+事件+审批+候选投影 → render-ready 协作图。

    Args:
        runRows: ``agent_runs`` 台账行（``list_subagent_runs`` 形态，seq 降序）。
        eventsByRun: subagent_id → H-4 事件列表（取 lineage 的 depth/parent）。
        memberProfiles: subagent_id → {member_name, kind, executor_tool[, status]}
            （团队名册/内存 run 态富化；缺席时 member_name 回落 agent_id、kind 回落 internal）。
        taskUnits: subagent_id → TaskUnit.toDict()（内存 run 态；依赖边数据源，
            重启后缺席=依赖边如实缺）。
        approvals: 审批记录列表（审计配对 + ApprovalManager 单源，见 console 组装）。
        candidateBoard: P2-3 ``projectCandidateBoard`` 快照（候选卡+候选边数据源）。
        maxNodes: run 节点上限，超出按台账序（新→旧）截断并标 truncated。
    """
    eventsByRun = eventsByRun or {}
    memberProfiles = memberProfiles or {}
    taskUnits = taskUnits or {}
    approvals = approvals or []
    candidateBoard = candidateBoard or {}

    truncated = len(runRows) > maxNodes
    keptRows = [r for r in runRows[:maxNodes] if str(r.get("subagent_id") or "").strip()]

    # ── 第一遍：run 节点全量注册（边判悬空前，节点集必须先齐）─────────
    runNodes: List[GraphNode] = []
    nodeIds: Dict[str, None] = {}
    for r in keptRows:
        sid = str(r.get("subagent_id") or "")
        node = _runNode(r, eventsByRun.get(sid) or [], memberProfiles.get(sid) or {})
        runNodes.append(node)
        nodeIds[sid] = None

    # ── 第二遍：spawn / dependency 边 ───────────────────────────
    edges: Dict[str, GraphEdge] = {}
    dangling = 0
    for node in runNodes:
        sid = node["id"]
        parent = _parentOf(eventsByRun.get(sid) or [])
        if parent:
            if parent in nodeIds:
                edges[f"spawn:{parent}->{sid}"] = {
                    "id": f"spawn:{parent}->{sid}", "type": "spawn",
                    "from": parent, "to": sid,
                    "level": "", "status": "", "decision": "", "decided_by": "",
                }
            else:
                dangling += 1
        unit = taskUnits.get(sid) or {}
        for dep in (unit.get("dependencies") or []):
            depId = str(dep or "").strip()
            if not depId:
                continue
            if depId == sid:
                dangling += 1  # 自引用：dispatch_team 本就会丢弃，投影同样不连
                continue
            if depId not in nodeIds:
                dangling += 1
                continue
            edges[f"dep:{depId}->{sid}"] = {
                "id": f"dep:{depId}->{sid}", "type": "dependency",
                "from": depId, "to": sid,
                "level": "", "status": "", "decision": "", "decided_by": "",
            }

    # ── 审批卡节点 + 审批边 ─────────────────────────────────────
    approvalNodes: List[GraphNode] = []
    for rec in approvals:
        requestId = str(rec.get("request_id") or "")
        runRef = str(rec.get("run_id") or "")
        if not requestId or not runRef:
            continue
        decision = str(rec.get("decision") or "")
        if decision:
            verdict = "approved" if decision == "approve" else (
                "rejected" if decision == "reject" else "pending")
        else:
            verdict = "pending"
        card: GraphNode = {
            "id": f"approval:{requestId}",
            "nodeType": "approval",
            "run_id": runRef,
            "member_name": str(rec.get("operation") or "审批")[:120],
            "kind": "",
            "executor_tool": "",
            "status": verdict,
            "depth": 0,
            "team_id": "",
            "started_at": float(rec.get("requested_at") or 0.0),
            "finished_at": float(rec.get("decided_at") or 0.0),
            "duration_ms": 0.0,
            "error_type": "",
            "level": str(rec.get("level") or ""),
            "decision": decision,
            "decided_by": str(rec.get("decided_by") or ""),
            "request_id": requestId,
            "candidate_id": "",
            "artifact_keys": [],
            "base_revision": 0,
            "note": "",
        }
        if runRef in nodeIds:
            approvalNodes.append(card)
            nodeIds[card["id"]] = None
            edges[f"approval:{requestId}"] = {
                "id": f"approval:{requestId}", "type": "approval",
                "from": runRef, "to": card["id"],
                "level": card["level"], "status": verdict,
                "decision": decision, "decided_by": card["decided_by"],
            }
        else:
            dangling += 1

    # ── 候选卡节点 + 候选边（数据源=P2-3 重放投影）────────────────
    candidateNodes: List[GraphNode] = []
    for cand in (candidateBoard.get("candidates") or []):
        candidateId = str(cand.get("candidate_id") or "")
        runRef = str(cand.get("run_id") or "")
        if not candidateId or not runRef:
            continue
        keys = [str(k) for k in (cand.get("artifact_keys") or [])]
        card = {
            "id": f"candidate:{candidateId}",
            "nodeType": "candidate",
            "run_id": runRef,
            "member_name": ("、".join(keys) if keys
                            else str(cand.get("note") or candidateId))[:120],
            "kind": "",
            "executor_tool": "",
            "status": str(cand.get("status") or ""),
            "depth": 0,
            "team_id": "",
            "started_at": _epochOrZero(cand.get("created_at")),
            "finished_at": _epochOrZero(cand.get("decided_at")),
            "duration_ms": 0.0,
            "error_type": "",
            "level": "",
            "decision": "",
            "decided_by": "",
            "request_id": "",
            "candidate_id": candidateId,
            "artifact_keys": keys,
            "base_revision": int(cand.get("base_revision") or 0),
            "note": str(cand.get("note") or ""),
        }
        if runRef in nodeIds:
            candidateNodes.append(card)
            nodeIds[card["id"]] = None
            edges[f"candidate:{candidateId}"] = {
                "id": f"candidate:{candidateId}", "type": "candidate",
                "from": runRef, "to": card["id"],
                "level": "", "status": card["status"],
                "decision": "", "decided_by": "",
            }
        else:
            dangling += 1

    # run 节点按（深度, 开始时刻, id）排序：父先于子、布局稳定；卡节点随后
    runNodes.sort(key=lambda n: (n["depth"], n["started_at"], n["id"]))
    nodes = runNodes + approvalNodes + candidateNodes

    edgeList = list(edges.values())
    counts: Dict[str, int] = {
        "nodes": len(nodes),
        "runNodes": len(runNodes),
        "approvalCards": len(approvalNodes),
        "candidateCards": len(candidateNodes),
        "edges": len(edgeList),
        "danglingEdges": dangling,
    }
    for e in edgeList:
        counts[e["type"]] = counts.get(e["type"], 0) + 1

    return GraphProjection(
        nodes=nodes,
        edges=edgeList,
        meta=GraphMeta(
            revision=int(candidateBoard.get("revision") or 0),
            generated_at=time.time(),
            truncated=truncated,
            candidates_incomplete=bool(candidateBoard.get("incomplete")),
            counts=counts,
        ),
    )


def _runNode(row: Dict[str, Any], runEvents: List[Dict[str, Any]],
             profile: Dict[str, Any]) -> GraphNode:
    """台账行 + 事件 lineage + 富化档案 → run 节点。"""
    sid = str(row.get("subagent_id") or "")
    depth = 0
    for e in runEvents:
        lin = e.get("lineage") if isinstance(e, dict) else None
        if isinstance(lin, dict) and lin.get("depth"):
            try:
                depth = int(lin["depth"])
                break
            except (TypeError, ValueError):
                continue
    startedAt = float(row.get("started_at") or 0.0)
    finishedAt = float(row.get("finished_at") or 0.0)
    durationMs = 0.0
    if startedAt and finishedAt:
        durationMs = round((finishedAt - startedAt) * 1000.0, 3)
    else:
        for e in runEvents:
            if str(e.get("type") or "") == "terminal":
                payload = e.get("payload") or {}
                try:
                    durationMs = float(payload.get("duration_ms") or 0.0)
                except (TypeError, ValueError):
                    durationMs = 0.0
                break
    return GraphNode(
        id=sid,
        nodeType="run",
        run_id=str(row.get("run_id") or ""),
        member_name=str(profile.get("member_name") or row.get("agent_id") or sid),
        kind=str(profile.get("kind") or "internal"),
        executor_tool=str(profile.get("executor_tool") or ""),
        status=str(profile.get("status") or row.get("status") or ""),
        depth=depth,
        team_id=str(row.get("team_id") or ""),
        started_at=startedAt,
        finished_at=finishedAt,
        duration_ms=durationMs,
        error_type=str(row.get("error_type") or ""),
        level="",
        decision="",
        decided_by="",
        request_id="",
        candidate_id="",
        artifact_keys=[],
        base_revision=0,
        note="",
    )


def _parentOf(runEvents: List[Dict[str, Any]]) -> str:
    """取该 run 第一个带 lineage 事件的 parent_subagent_id（无则空串）。"""
    for e in runEvents:
        lin = e.get("lineage") if isinstance(e, dict) else None
        if isinstance(lin, dict) and str(lin.get("parent_subagent_id") or ""):
            return str(lin["parent_subagent_id"])
    return ""


def _epochOrZero(value: Any) -> float:
    """候选投影的时刻可能是 ISO 字符串（重放投影）或 epoch 秒（内存板）——统一成 epoch。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    try:
        from datetime import datetime

        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
