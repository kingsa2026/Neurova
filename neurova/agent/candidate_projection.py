# -*- coding: utf-8 -*-
"""P2-3 候选板 H-4 事件重放投影（计划 §5，拍板 D-C：重放投影、不落新表）。

``CandidateMergeBoard`` 是进程内存态（candidate_merge.py 自注"不落盘"），重启或
跨进程后「在途候选还在不在、冲突裁决到哪一步」无从查起——审批链侧因此诚实报
"候选不存在"。本模块把 H-4 run 事件账本里的 candidate_* 事件按时间序折叠成与
``CandidateMergeBoard.snapshot()`` 同构的投影：账本仍是唯一持久层，这里**只读不写、
不建第二事实源**；判定权仍只在内存板（applyRoomCandidateAction 语义不变）。

折叠规则与 ``CandidateMergeBoard`` 的状态迁移一一对应：

- ``candidate_submitted``        → 落候选（submitted），同 key 同基准互相标冲突
                                   （与 ``_flagSameKeyClash`` 同构）；
- ``candidate_conflict_flagged`` → 登记提交期冲突对象（与上同刻，事件先于折叠也一致）；
- ``candidate_revise_required``  → 置 reviseRequired（验收/评审驳回，回炉链入口）；
- ``candidate_conflict``         → CAS 冲突：状态保持 submitted、note 记说明、冲突
                                   对象重算为"已合入且同 key"的候选（与
                                   ``_acceptedWithSameKeys`` 同构）；
- ``candidate_merge_rejected``   → 板上本就 no-op（状态不允许/重复合入不改板），投影同样 no-op；
- ``candidate_merged``           → 置 accepted、revision 推进到事件值、清 note
                                   （conflict_with 保留——与板的历史冲突标记一致）；
- ``candidate_rejected``         → 置 rejected（房间拦截/人工否决）。

诚实标注：
- ``incomplete=True``：事件引用了不存在的候选（账本被截断/缺 submitted）或
  submitted 载荷缺 candidate_id——此时投影是"能看到多少算多少"，不得冒充完整板；
- 正文（content）按"正文不进账本"纪律不在 H-4 账本里，投影**不含** content 字段，
  看正文走 member 会话（与档案读面同口径）。
"""
from __future__ import annotations

from typing import Any, Dict, List, TypedDict

from neurova.agent.candidate_merge import (
    CANDIDATE_ACCEPTED,
    CANDIDATE_REJECTED,
    CANDIDATE_REVISE_REQUIRED,
    CANDIDATE_SUBMITTED,
)

#: H-4 账本里的候选事件族（与 swarm._logRunEvent 的落点一一对应；candidate_rejected
#: 来自 applyRoomCandidateAction 的房间拦截路径，同属一族）
CANDIDATE_EVENT_TYPES = frozenset({
    "candidate_submitted",
    "candidate_conflict_flagged",
    "candidate_revise_required",
    "candidate_conflict",
    "candidate_merge_rejected",
    "candidate_merged",
    "candidate_rejected",
})


class CandidateProjectionEntry(TypedDict):
    """投影出的单条候选（字段集 = CandidateReport.toDict 去掉 content）。

    P2-4 契约：本 TypedDict 是服务端单源，前端 TS 类型（NeurUI/src/types/swarmGraph.ts）
    手抄对齐，漂移由 tests/unit/api/test_swarm_graph_contract.py 钉红。
    """

    candidate_id: str
    run_id: str
    artifact_keys: List[str]
    base_revision: int
    status: str
    conflict_with: List[str]
    note: str
    created_at: str
    decided_at: str


class CandidateBoardSnapshot(TypedDict):
    """候选板投影快照（形状对齐 CandidateMergeBoard.snapshot，另加诚实标注）。"""

    revision: int
    candidates: List[CandidateProjectionEntry]
    conflicts: List[CandidateProjectionEntry]
    incomplete: bool
    source: str


def _asInt(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def projectCandidateBoard(
    eventsByRun: Dict[str, List[Dict[str, Any]]],
) -> CandidateBoardSnapshot:
    """按时间序折叠六类（+房间否决）candidate_* 事件，重建候选板快照。

    Args:
        eventsByRun: run_id（subagent_id）→ 该 run 的 H-4 事件列表
            （``swarm_event_log.readRunEvents`` 的原样形态）。

    Returns:
        CandidateBoardSnapshot：revision/candidates/conflicts 与内存板 snapshot
        逐字段同构；incomplete 标注账本缺事件；source 恒为 "replay"。
    """
    events: List[Dict[str, Any]] = []
    for runEvents in (eventsByRun or {}).values():
        for event in runEvents or []:
            if isinstance(event, dict) and str(event.get("type") or "") in CANDIDATE_EVENT_TYPES:
                events.append(event)
    # 全序：occurred_at（ISO 同格式字符串可比）→ seq（per-run 计数，只作同刻微调）
    # → event_id（兜底稳定序）。**不能**按 run 分组后各自折叠：revision 是跨 run
    # 的单源计数，合入顺序必须按发生时刻全局排。
    events.sort(key=_eventOrderKey)

    candidates: Dict[str, CandidateProjectionEntry] = {}
    revision = 0
    incomplete = False

    for event in events:
        eventType = str(event.get("type") or "")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        occurredAt = str(event.get("occurred_at") or "")
        runId = str(event.get("subagent_id") or "")
        candidateId = str(payload.get("candidate_id") or "")

        if eventType == "candidate_submitted":
            if not candidateId:
                incomplete = True
                continue
            entry: CandidateProjectionEntry = {
                "candidate_id": candidateId,
                "run_id": runId,
                "artifact_keys": [str(k) for k in (payload.get("artifact_keys") or [])
                                  if str(k or "").strip()],
                "base_revision": _asInt(payload.get("base_revision"), 0),
                "status": CANDIDATE_SUBMITTED,
                "conflict_with": [],
                "note": "",
                "created_at": occurredAt,
                "decided_at": "",
            }
            candidates[candidateId] = entry
            # 提交时板的版本 = 候选基准（swarm 侧 baseRevision 取提交时刻的 revision）
            revision = max(revision, entry["base_revision"])
            _flagSameKeyClash(entry, candidates)
            continue

        entry = candidates.get(candidateId)
        if entry is None:
            # submitted 事件缺失（账本截断/归档窗外）：不凭空造候选，诚实标注
            incomplete = True
            continue

        if eventType == "candidate_conflict_flagged":
            for other in (payload.get("conflict_with") or []):
                otherId = str(other or "")
                if otherId and otherId not in entry["conflict_with"]:
                    entry["conflict_with"].append(otherId)
        elif eventType == "candidate_revise_required":
            entry["status"] = CANDIDATE_REVISE_REQUIRED
            entry["note"] = str(payload.get("reason") or "验收驳回")
            entry["decided_at"] = occurredAt
        elif eventType == "candidate_conflict":
            # CAS 失败：状态保持 submitted；冲突对象与板同构重算（替换，不并集）
            entry["note"] = str(payload.get("detail") or entry["note"])
            entry["conflict_with"] = _acceptedWithSameKeys(entry, candidates)
        elif eventType == "candidate_merged":
            entry["status"] = CANDIDATE_ACCEPTED
            entry["note"] = ""
            entry["decided_at"] = occurredAt
            mergedRevision = _asInt(payload.get("revision"), 0)
            revision = max(revision, mergedRevision if mergedRevision > 0 else revision + 1)
        elif eventType == "candidate_rejected":
            entry["status"] = CANDIDATE_REJECTED
            entry["decided_at"] = occurredAt
            if not entry["note"]:
                actor = str(payload.get("actor") or "")
                entry["note"] = (f"房间拦截（by {actor or '群主'}）"
                                 if str(payload.get("by") or "") == "room"
                                 else f"人工否决（by {actor}）")
        # candidate_merge_rejected：板上 no-op，投影同样 no-op

    ordered = sorted(candidates.values(),
                     key=lambda c: (c["created_at"], c["candidate_id"]))
    return CandidateBoardSnapshot(
        revision=revision,
        candidates=[dict(c) for c in ordered],
        conflicts=[dict(c) for c in ordered if c["conflict_with"]],
        incomplete=incomplete,
        source="replay",
    )


def _eventOrderKey(event: Dict[str, Any]) -> tuple:
    return (str(event.get("occurred_at") or ""),
            _asInt(event.get("seq"), 0),
            str(event.get("event_id") or ""))


def _flagSameKeyClash(entry: CandidateProjectionEntry,
                      candidates: Dict[str, CandidateProjectionEntry]) -> None:
    """同 artifactKey 且同 baseRevision 的在途候选互相标冲突（镜像板内同名私有逻辑）。"""
    if not entry["artifact_keys"]:
        return
    for other in candidates.values():
        if other["candidate_id"] == entry["candidate_id"]:
            continue
        if other["base_revision"] != entry["base_revision"]:
            continue
        if not set(other["artifact_keys"]) & set(entry["artifact_keys"]):
            continue
        for a, b in ((entry, other), (other, entry)):
            # 去重卫：conflict_with 里存的是**对方** id；板内卫是"自己 id 不在表里"
            # （提交期一次性标记下等价）。投影还要吃乱序 conflict_flagged 事件，
            # 按对方 id 去重才不会叠出重复项。
            if b["candidate_id"] not in a["conflict_with"]:
                a["conflict_with"].append(b["candidate_id"])
            if not a["note"]:
                a["note"] = (f"与候选 {b['candidate_id']} 主张同一产物 "
                             f"{sorted(set(a['artifact_keys']) & set(b['artifact_keys']))}"
                             f" 且基准版本相同（{a['base_revision']}），待人工裁决")


def _acceptedWithSameKeys(entry: CandidateProjectionEntry,
                          candidates: Dict[str, CandidateProjectionEntry]) -> List[str]:
    """已合入且与该候选主张同 key 的候选 id 列表（镜像板内同名私有逻辑）。"""
    if not entry["artifact_keys"]:
        return []
    return [c["candidate_id"] for c in candidates.values()
            if c["candidate_id"] != entry["candidate_id"]
            and c["status"] == CANDIDATE_ACCEPTED
            and set(c["artifact_keys"]) & set(entry["artifact_keys"])]
