# -*- coding: utf-8 -*-
"""结构完整性 Doctor —— 上下文工程十轴专项 · 轴9（P0-3）。

对会话侧上下文结构做**只读体检**：消息流、上下文池归档、会话时间线三路
输入交叉核对，检出五类结构病与一类不可逆丢失。只诊断、不修补——修补
（剔孤儿、重建索引、补载荷）属写路径，不在本卡范围。

## 五类病的判据口径（以真实数据结构为准）

- **concurrent_fork**（互斥分叉）：同一槽位（turn_id × role × tool_call_id）
  出现 ≥2 条**内容互异**的消息/池条目。同轮多条 assistant 行是顺序合法
  形态，不按槽位判；内容一致的重复行不互斥，不判 fork。
  轮次编号以 `recovery.assign_turn_ids` 为单源（user 行开新轮，全会话稳定），
  消息带显式 `metadata.turn_id` 时以显式值为准。
- **orphan_turn**（孤儿轮引用）：`role=tool` 行的 `tool_call_id` 未被任何
  `assistant.tool_calls` 声明（判据单源 `recovery.orphanToolRows`）；或池条目
  `metadata.pairs_with` / `metadata.turn_id` 指向池内与消息流中都不存在的轮次。
- **stale_index**（失效索引）：SUMMARY 层节点 `covers`（`fold_index.buildCovers`
  写入侧的形状）、`fold_baseline` 事件的 `covered`、压缩事件的
  `cutoffMessageId`——指纹在池 hash 与消息指纹（两种口径分别核对）中都
  解析不到：索引还在，指向的原文已不在。声明参加索引却解析不出的 covers
  同样点名（`covers_unparsable`），不许装没病。
- **segment_split**（轮次断档/乱序）：消息流轮次序号倒序或断档；池条目
  轮次集合断档（池条目按归档序写入、按最旧驱逐，轮次集合应连续）。
  派生轮次天然连续，只有显式 `metadata.turn_id` 才可能在消息流断档。
- **lost_content**（不可逆丢失）：应有内容的行 `content` 为空（带
  `tool_calls` 的 assistant 行豁免——协议允许只发调用）；池条目 content
  为空；时间线事件有 kind 却缺该 kind 的关键载荷字段（无法重放）。

诚实边界：只对三路输入里**实际检查过的对象**出具结论（`checked` 计数）；
不认识的 timeline kind 不判；查无此会话时 issues 为空、`session_found=0`——
"没检查出依据"不等于"没病"，也不伪造病。同输入两次诊断结论逐条一致
（纯函数：无 I/O、无时钟、无随机；池条目输入顺序不影响结论）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from neurova.context.fold_index import COVERS_KEY, parseCovers
from neurova.context.recovery import assign_turn_ids, orphanToolRows

#: 五类结构病（封闭集合）。
ISSUE_CONCURRENT_FORK = "concurrent_fork"
ISSUE_ORPHAN_TURN = "orphan_turn"
ISSUE_STALE_INDEX = "stale_index"
ISSUE_SEGMENT_SPLIT = "segment_split"
ISSUE_LOST_CONTENT = "lost_content"

ISSUE_TYPES = frozenset({
    ISSUE_CONCURRENT_FORK,
    ISSUE_ORPHAN_TURN,
    ISSUE_STALE_INDEX,
    ISSUE_SEGMENT_SPLIT,
    ISSUE_LOST_CONTENT,
})

#: 严重级（封闭集合）：high=影响模型正确性/协议或不可逆；medium=能力降级。
SEV_HIGH = "high"
SEV_MEDIUM = "medium"
SEV_LOW = "low"

SEVERITIES = frozenset({SEV_HIGH, SEV_MEDIUM, SEV_LOW})

SEVERITY_BY_TYPE = {
    ISSUE_CONCURRENT_FORK: SEV_HIGH,
    ISSUE_ORPHAN_TURN: SEV_HIGH,
    ISSUE_STALE_INDEX: SEV_MEDIUM,
    ISSUE_SEGMENT_SPLIT: SEV_MEDIUM,
    ISSUE_LOST_CONTENT: SEV_HIGH,
}

#: 各 timeline kind 重放所需的关键载荷字段（缺失即 lost_content）。
TIMELINE_REQUIRED_FIELDS = {
    "context_compacted": ("cutoffIndex", "tokensBefore", "tokensAfter", "foldedCount"),
    "compaction_cooldown": ("consecutiveFailures", "cooldownSeconds"),
    "fold_baseline": ("foldSeq", "covered"),
}

#: 适配面单会话扫描上限（防超大时间线/池拖垮只读诊断）。
MAX_TIMELINE_EVENTS = 5000
MAX_POOL_ENTRIES = 20000

_EVIDENCE_PREVIEW_CHARS = 40
_EVIDENCE_SAMPLE_MAX = 10


def _preview(text: Any) -> str:
    """证据里的内容预览（定位用，不携带全文）。"""
    return str(text or "")[:_EVIDENCE_PREVIEW_CHARS]


def _issueSortKey(issue: "StructureIssue") -> Tuple[str, str, str]:
    """结论的规范化排序键（确定性：输入顺序不影响输出顺序）。"""
    return (
        issue.type,
        issue.severity,
        json.dumps(issue.evidence, sort_keys=True, ensure_ascii=False, default=str),
    )


@dataclass
class StructureIssue:
    """一条结构病结论：类型 + 严重级 + 定位证据 + 修复建议。"""

    type: str
    severity: str
    evidence: Dict[str, Any]
    suggestion: str

    def __post_init__(self):
        if self.type not in ISSUE_TYPES:
            raise ValueError(f"未知结构病类型: {self.type!r}（封闭集合 {sorted(ISSUE_TYPES)}）")
        if self.severity not in SEVERITIES:
            raise ValueError(f"未知严重级: {self.severity!r}（封闭集合 {sorted(SEVERITIES)}）")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "severity": self.severity,
            "evidence": self.evidence,
            "suggestion": self.suggestion,
        }


@dataclass
class StructureDiagnosis:
    """一次结构体检的完整结论（issues 按规范化序排列，保证确定性）。"""

    session_id: str = ""
    agent_id: str = ""
    issues: List[StructureIssue] = field(default_factory=list)
    #: 检查依据：各路输入实际核对的对象数（诚实计数，"检查过"的证据）。
    checked: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        self.issues.sort(key=_issueSortKey)

    @property
    def issueCount(self) -> int:
        return len(self.issues)

    @property
    def healthy(self) -> bool:
        return not self.issues

    def countsByType(self) -> Dict[str, int]:
        counts = {issueType: 0 for issueType in sorted(ISSUE_TYPES)}
        for issue in self.issues:
            counts[issue.type] += 1
        return counts

    def to_dict(self, detailLimit: Optional[int] = None) -> Dict[str, Any]:
        """序列化；`detailLimit` 截断明细条数（总数与计数不受截断影响）。"""
        issues = self.issues
        capped = issues if detailLimit is None else issues[: max(0, int(detailLimit))]
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "healthy": self.healthy,
            "issue_count": len(issues),
            "counts_by_type": self.countsByType(),
            "checked": dict(self.checked),
            "issues_total": len(issues),
            "issues_returned": len(capped),
            "issues": [issue.to_dict() for issue in capped],
        }


# ── 轮次编号（单源：recovery.assign_turn_ids + 显式 turn_id 覆盖） ──

def _messageTurnIds(messages: Sequence[dict]) -> List[str]:
    """逐条消息的轮次 id：显式 metadata.turn_id 优先，否则按 user 行开新轮派生。"""
    turns: List[str] = []
    for message, derived in assign_turn_ids(list(messages or [])):
        explicit = ""
        if isinstance(message, dict):
            meta = message.get("metadata")
            if isinstance(meta, dict):
                explicit = str(meta.get("turn_id") or "")
            if not explicit:
                explicit = str(message.get("turn_id") or "")
        turns.append(explicit if explicit else derived)
    return turns


def _turnNumber(turnId: str) -> Optional[int]:
    """`turn_N` → int；非该形态返回 None（不参与数值判据）。"""
    text = str(turnId or "")
    if text.startswith("turn_") and text[5:].isdigit():
        return int(text[5:])
    return None


# ── 消息侧检查 ────────────────────────────────────────────

def _checkMessageLostContent(messages, turns, issues) -> None:
    for index, message in enumerate(messages):
        role = str(message.get("role") or "")
        content = message.get("content")
        hasCalls = bool(message.get("tool_calls"))
        if (content is None or str(content) == "") and not (role == "assistant" and hasCalls):
            issues.append(StructureIssue(
                type=ISSUE_LOST_CONTENT, severity=SEVERITY_BY_TYPE[ISSUE_LOST_CONTENT],
                evidence={
                    "stream": "messages", "index": index, "role": role,
                    "turn_id": turns[index],
                },
                suggestion="该行应有内容但 content 为空：核对写入侧是否漏写正文。",
            ))


def _checkMessageSegmentSplit(messages, turns, issues) -> None:
    issues.extend(_sequenceIssues(
        [(index, turns[index], _turnNumber(turns[index])) for index in range(len(messages))],
        stream="messages",
    ))


def _sequenceIssues(
    rows: List[Tuple[int, str, Optional[int]]], stream: str, checkDisorder: bool = True,
) -> List[StructureIssue]:
    """轮次序号断档/乱序判据（消息流按行序查乱序+断档；池只查断档）。"""
    out: List[StructureIssue] = []
    maxSeen: Optional[int] = None
    for index, turnId, number in rows:
        if number is None:
            continue
        if checkDisorder and maxSeen is not None and number < maxSeen:
            out.append(StructureIssue(
                type=ISSUE_SEGMENT_SPLIT, severity=SEVERITY_BY_TYPE[ISSUE_SEGMENT_SPLIT],
                evidence={
                    "stream": stream, "kind": "disorder", "index": index,
                    "turn_id": turnId, "max_seen_turn": f"turn_{maxSeen}",
                },
                suggestion="轮次序号乱序：核对消息写入顺序与轮次编号派生口径。",
            ))
        maxSeen = number if maxSeen is None else max(maxSeen, number)
    distinct = sorted({number for _, _, number in rows if number is not None})
    for prev, cur in zip(distinct, distinct[1:]):
        if cur - prev > 1:
            missing = list(range(prev + 1, cur))
            out.append(StructureIssue(
                type=ISSUE_SEGMENT_SPLIT, severity=SEVERITY_BY_TYPE[ISSUE_SEGMENT_SPLIT],
                evidence={
                    "stream": stream, "kind": "gap", "after_turn": f"turn_{prev}",
                    "before_turn": f"turn_{cur}",
                    "missing_count": len(missing),
                    "missing_sample": [f"turn_{n}" for n in missing[:_EVIDENCE_SAMPLE_MAX]],
                },
                suggestion="轮次序号断档：核对归档/驱逐是否越序移除中间轮次，或显式轮次编号是否有缺口。",
            ))
    return out


def _checkMessageConcurrentFork(messages, turns, issues) -> None:
    slots: Dict[Tuple[str, str, str], List[Tuple[int, str]]] = {}
    for index, message in enumerate(messages):
        role = str(message.get("role") or "")
        turnId = turns[index]
        if role == "user":
            slots.setdefault((turnId, "user", ""), []).append(
                (index, str(message.get("content") or "")))
        elif role == "tool":
            callId = str(message.get("tool_call_id") or "")
            slots.setdefault((turnId, "tool", callId), []).append(
                (index, str(message.get("content") or "")))
        elif role == "assistant":
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") if isinstance(call.get("function"), dict) else {}
                callId = str(call.get("id") or "")
                variant = f"{(function or {}).get('name') or ''}:{(function or {}).get('arguments') or ''}"
                slots.setdefault((turnId, "assistant", callId), []).append((index, variant))
    _emitForks(slots, issues)


def _emitForks(slots: Dict[Tuple[str, str, str], List[Tuple[int, str]]], issues) -> None:
    for (turnId, role, callId), rows in slots.items():
        variants = {content for _, content in rows}
        if len(rows) <= 1 or len(variants) <= 1:
            continue  # 单条或内容一致（不互斥）都不判 fork
        issues.append(StructureIssue(
            type=ISSUE_CONCURRENT_FORK, severity=SEVERITY_BY_TYPE[ISSUE_CONCURRENT_FORK],
            evidence={
                "turn_id": turnId, "role": role, "tool_call_id": callId,
                "row_indexes": sorted(index for index, _ in rows),
                "variants": sorted(_preview(v) for v in variants),
            },
            suggestion="同槽位出现互斥消息：核对写入侧是否发生重试/分叉双写，保留唯一权威版本后修复槽位。",
        ))


def _checkMessageOrphanTools(messages, turns, issues) -> None:
    indexById = {id(message): index for index, message in enumerate(messages)}
    for orphan in orphanToolRows(list(messages)):
        index = indexById.get(id(orphan))
        issues.append(StructureIssue(
            type=ISSUE_ORPHAN_TURN, severity=SEVERITY_BY_TYPE[ISSUE_ORPHAN_TURN],
            evidence={
                "stream": "messages", "index": index,
                "turn_id": turns[index] if index is not None else "",
                "tool_call_id": str(orphan.get("tool_call_id") or ""),
                "reason": "result_without_call",
            },
            suggestion="工具结果没有声明它的调用：核对 assistant.tool_calls 是否被折叠/剥离，先修配对再入模。",
        ))


# ── 池侧检查 ──────────────────────────────────────────────

def _normalizeEntries(entries: Sequence[Any]) -> List[Dict[str, Any]]:
    """池条目归一为 {source, content, hash, metadata}（兼容对象与 dict 两种形态）。"""
    norm: List[Dict[str, Any]] = []
    for entry in entries or []:
        if isinstance(entry, dict):
            source = entry.get("source")
            norm.append({
                "source": str(getattr(source, "value", source) or ""),
                "content": entry.get("content") or "",
                "hash": str(entry.get("hash") or ""),
                "metadata": dict(entry.get("metadata") or {}),
            })
        else:
            source = getattr(entry, "source", None)
            norm.append({
                "source": str(getattr(source, "value", source) or ""),
                "content": getattr(entry, "content", "") or "",
                "hash": str(getattr(entry, "hash", "") or ""),
                "metadata": dict(getattr(entry, "metadata", None) or {}),
            })
    return norm


def _entryRole(norm: Dict[str, Any]) -> str:
    """条目的角色：metadata.role 优先，缺省按来源推断（对话归档写侧契约）。"""
    role = str(norm["metadata"].get("role") or "")
    if role:
        return role
    return {"user_input": "user", "tool_call": "tool"}.get(norm["source"], "")


def _checkPoolLostContent(normEntries, issues) -> None:
    for entry in normEntries:
        if str(entry["content"]) == "":
            issues.append(StructureIssue(
                type=ISSUE_LOST_CONTENT, severity=SEVERITY_BY_TYPE[ISSUE_LOST_CONTENT],
                evidence={
                    "stream": "pool", "entry_hash": entry["hash"] or None,
                    "source": entry["source"],
                    "turn_id": str(entry["metadata"].get("turn_id") or "") or None,
                },
                suggestion="池条目 content 为空：核对归档写入是否丢正文。",
            ))


def _checkPoolConcurrentFork(normEntries, issues) -> None:
    slots: Dict[Tuple[str, str, str], List[Tuple[str, str]]] = {}
    for entry in normEntries:
        role = _entryRole(entry)
        turnId = str(entry["metadata"].get("turn_id") or "")
        if not turnId:
            continue  # 无轮次锚（如 /build 直写条目）不按槽位判
        if role == "user":
            slots.setdefault((turnId, "user", ""), []).append((entry["hash"], str(entry["content"])))
        elif role == "tool":
            callId = str(entry["metadata"].get("tool_call_id") or "")
            slots.setdefault((turnId, "tool", callId), []).append((entry["hash"], str(entry["content"])))
    _emitForksPool(slots, issues)


def _emitForksPool(slots: Dict[Tuple[str, str, str], List[Tuple[str, str]]], issues) -> None:
    for (turnId, role, callId), rows in slots.items():
        variants = {content for _, content in rows}
        if len(rows) <= 1 or len(variants) <= 1:
            continue
        issues.append(StructureIssue(
            type=ISSUE_CONCURRENT_FORK, severity=SEVERITY_BY_TYPE[ISSUE_CONCURRENT_FORK],
            evidence={
                "turn_id": turnId, "role": role, "tool_call_id": callId,
                "entry_hashes": sorted(entryHash for entryHash, _ in rows if entryHash),
                "variants": sorted(_preview(v) for v in variants),
            },
            suggestion="同槽位出现互斥消息：核对写入侧是否发生重试/分叉双写，保留唯一权威版本后修复槽位。",
        ))


def _checkPoolOrphanRefs(normEntries, messageTurnIds, issues) -> None:
    poolTurnIds = {str(e["metadata"].get("turn_id") or "") for e in normEntries}
    poolTurnIds.discard("")
    poolHashes = {e["hash"] for e in normEntries if e["hash"]}
    for entry in normEntries:
        meta = entry["metadata"]
        pairsWith = str(meta.get("pairs_with") or "")
        if pairsWith and pairsWith not in poolTurnIds and pairsWith not in poolHashes \
                and pairsWith not in messageTurnIds:
            issues.append(StructureIssue(
                type=ISSUE_ORPHAN_TURN, severity=SEVERITY_BY_TYPE[ISSUE_ORPHAN_TURN],
                evidence={
                    "stream": "pool", "entry_hash": entry["hash"] or None,
                    "pairs_with": pairsWith, "reason": "pairs_with_target_absent",
                },
                suggestion="池条目的 pairs_with 对端不在池内也不在消息流：核对归档与驱逐路径是否把对端单独移除。",
            ))
        turnId = str(meta.get("turn_id") or "")
        if turnId and turnId not in messageTurnIds:
            issues.append(StructureIssue(
                type=ISSUE_ORPHAN_TURN, severity=SEVERITY_BY_TYPE[ISSUE_ORPHAN_TURN],
                evidence={
                    "stream": "pool", "entry_hash": entry["hash"] or None,
                    "turn_id": turnId, "reason": "turn_absent_in_messages",
                    "message_turn_count": len(messageTurnIds),
                },
                suggestion="池条目引用的轮次在消息流中不存在：核对会话消息是否被删改或轮次编号口径漂移。",
            ))


def _checkPoolSegmentSplit(normEntries, issues) -> None:
    rows = []
    for entry in normEntries:
        number = _turnNumber(str(entry["metadata"].get("turn_id") or ""))
        if number is not None:
            rows.append((0, f"turn_{number}", number))
    # 池只查断档不查乱序：多写方（swarm/voice 等）插入序不构成轮次乱序证据，
    # 条目按归档序写入、按最旧驱逐，轮次集合应连续。
    issues.extend(_sequenceIssues(rows, stream="pool", checkDisorder=False))


# ── 索引/指纹核对（池 covers + 时间线 covered/cutoff） ──────

def _messageChunkHash(message: dict) -> str:
    """消息的归档指纹（与编排器 `_windowChunkIdentity` 同源：tool→TOOL_CALL，余→CONVERSATION）。"""
    from neurova.context.pool_models import ContextInput, ContextSource

    source = ContextSource.TOOL_CALL if str(message.get("role") or "") == "tool" else ContextSource.CONVERSATION
    return ContextInput.compute_hash(source, str(message.get("content") or ""))


def _checkStaleIndex(normEntries, events, messages, issues) -> None:
    from neurova.context_pool import contextFingerprint

    knownChunkHashes = {e["hash"] for e in normEntries if e["hash"]}
    knownChunkHashes |= {_messageChunkHash(m) for m in messages}
    knownFingerprints = {contextFingerprint(m) for m in messages}

    for entry in normEntries:
        meta = entry["metadata"]
        if COVERS_KEY not in meta:
            continue
        covers = parseCovers(meta)
        if covers is None:
            issues.append(StructureIssue(
                type=ISSUE_STALE_INDEX, severity=SEVERITY_BY_TYPE[ISSUE_STALE_INDEX],
                evidence={
                    "stream": "pool", "entry_hash": entry["hash"] or None,
                    "reason": "covers_unparsable",
                },
                suggestion="covers 字段解析失败：按 fold_index.parseCovers 口径修复索引形态。",
            ))
            continue
        missing = [h for h in covers["hashes"] if h not in knownChunkHashes]
        if missing:
            issues.append(StructureIssue(
                type=ISSUE_STALE_INDEX, severity=SEVERITY_BY_TYPE[ISSUE_STALE_INDEX],
                evidence={
                    "stream": "pool", "entry_hash": entry["hash"] or None,
                    "fold_seq": meta.get("fold_seq"),
                    "reason": "covers_unresolved", "missing_count": len(missing),
                    "missing_hashes": missing[:_EVIDENCE_SAMPLE_MAX],
                },
                suggestion="covers 指纹解析不到原文：从台账/消息流核对被覆盖条目是否仍存在，失效索引应重建或标注。",
            ))

    for index, event in enumerate(events):
        kind = str(event.get("kind") or "")
        payload = event.get("event") if isinstance(event.get("event"), dict) else {}
        if kind == "fold_baseline":
            missing = [str(h) for h in (payload.get("covered") or []) if h and str(h) not in knownChunkHashes]
            if missing:
                issues.append(StructureIssue(
                    type=ISSUE_STALE_INDEX, severity=SEVERITY_BY_TYPE[ISSUE_STALE_INDEX],
                    evidence={
                        "stream": "timeline", "event_index": index, "kind": kind,
                        "reason": "covered_unresolved", "missing_count": len(missing),
                        "missing_hashes": missing[:_EVIDENCE_SAMPLE_MAX],
                    },
                    suggestion="fold_baseline.covered 指纹失效：核对折叠覆盖集与消息流是否一致。",
                ))
        elif kind == "context_compacted":
            cutoffId = str(payload.get("cutoffMessageId") or "")
            try:
                cutoffIndex = int(payload.get("cutoffIndex") or 0)
            except (TypeError, ValueError):
                cutoffIndex = 0
            if cutoffId and cutoffIndex > 0 and cutoffId not in knownFingerprints:
                issues.append(StructureIssue(
                    type=ISSUE_STALE_INDEX, severity=SEVERITY_BY_TYPE[ISSUE_STALE_INDEX],
                    evidence={
                        "stream": "timeline", "event_index": index, "kind": kind,
                        "reason": "cutoff_fingerprint_unresolved", "cutoff_message_id": cutoffId,
                    },
                    suggestion="压缩事件 cutoffMessageId 在消息流中不存在：核对被折叠消息是否仍在会话存储。",
                ))


# ── 时间线载荷检查 ────────────────────────────────────────

def _checkTimelineLostContent(events, issues) -> None:
    for index, event in enumerate(events):
        kind = str(event.get("kind") or "")
        required = TIMELINE_REQUIRED_FIELDS.get(kind)
        if required is None:
            continue  # 不认识的 kind 不判（没检查的字段不判病）
        payload = event.get("event") if isinstance(event.get("event"), dict) else {}
        missing = [field for field in required if payload.get(field) is None]
        if kind == "context_compacted":
            try:
                cutoffIndex = int(payload.get("cutoffIndex") or 0)
            except (TypeError, ValueError):
                cutoffIndex = 0
            if cutoffIndex > 0 and not str(payload.get("cutoffMessageId") or ""):
                missing.append("cutoffMessageId")
        if kind == "fold_baseline" and not (payload.get("covered") or []) \
                and not str(payload.get("summary") or ""):
            try:
                foldSeq = int(payload.get("foldSeq") or 0)
            except (TypeError, ValueError):
                foldSeq = 0
            if foldSeq <= 0:
                missing.append("fold_state_empty")
        if missing:
            issues.append(StructureIssue(
                type=ISSUE_LOST_CONTENT, severity=SEVERITY_BY_TYPE[ISSUE_LOST_CONTENT],
                evidence={
                    "stream": "timeline", "event_index": index, "kind": kind,
                    "missing_fields": missing,
                },
                suggestion="时间线事件缺关键载荷字段，无法重放：补齐写入侧 payload。",
            ))


# ── 纯判据核心 ────────────────────────────────────────────

def diagnoseStructure(
    *,
    messages: Sequence[Any],
    pool_entries: Sequence[Any],
    timeline_events: Sequence[Any],
) -> StructureDiagnosis:
    """三路输入交叉体检（纯函数，无 I/O）。

    Args:
        messages: 会话消息（OpenAI 形态；显式 metadata.turn_id 优先，否则派生轮次）。
        pool_entries: 上下文池条目（ContextInput 或同形 dict）。
        timeline_events: 会话时间线事件（{kind, ts, event{...}}）。

    Returns:
        StructureDiagnosis：issues 按规范化序排列，同输入两次调用结果一致。
    """
    msgs = [m for m in (messages or []) if isinstance(m, dict)]
    normEntries = _normalizeEntries(pool_entries or [])
    events = [e for e in (timeline_events or []) if isinstance(e, dict)]

    turns = _messageTurnIds(msgs)
    messageTurnIds = set(turns)
    poolTurnIds = {str(e["metadata"].get("turn_id") or "") for e in normEntries}
    poolTurnIds.discard("")

    found: List[StructureIssue] = []
    _checkMessageLostContent(msgs, turns, found)
    _checkMessageSegmentSplit(msgs, turns, found)
    _checkMessageConcurrentFork(msgs, turns, found)
    _checkMessageOrphanTools(msgs, turns, found)
    _checkPoolLostContent(normEntries, found)
    _checkPoolConcurrentFork(normEntries, found)
    _checkPoolOrphanRefs(normEntries, messageTurnIds, found)
    _checkPoolSegmentSplit(normEntries, found)
    _checkStaleIndex(normEntries, events, msgs, found)
    _checkTimelineLostContent(events, found)

    return StructureDiagnosis(
        issues=found,
        checked={
            "messages": len(msgs),
            "pool_entries": len(normEntries),
            "timeline_events": len(events),
            "message_turns": len(messageTurnIds),
            "pool_turns": len(poolTurnIds),
        },
    )


# ── 薄适配：从真实存储取三路数据 ──────────────────────────

def _findAgentIdForSession(sessionManager: Any, sessionId: str) -> str:
    """按 session_id 反查 agent_id（会话文件 → 时间线文件），查不到返回空串。"""
    sid = str(sessionId or "")
    if not sid:
        return ""
    try:
        for agentDir in sessionManager._all_session_dirs():
            if any(agentDir.glob(f"session_{sid}_*.json")):
                return str(sessionManager._agent_id_for_session_dir(agentDir) or "")
        for agentDir in sessionManager._all_session_dirs():
            if (agentDir / "_timeline" / f"{sid}.jsonl").exists():
                return str(sessionManager._agent_id_for_session_dir(agentDir) or "")
    except Exception:  # noqa: BLE001 - 反查失败按"未找到"处理，诊断面不抛存储异常
        pass
    return ""


def _collectSessionPoolEntries(pool: Any, sessionId: str) -> List[Any]:
    """取该会话的池条目：显式 pool 优先，否则扫描注册表中 session 匹配的全部池。"""
    from neurova.context_pool_registry import get_registry

    pools = [pool] if pool is not None else list(get_registry().allPools())
    entries: List[Any] = []
    for candidate in pools:
        if str(getattr(candidate, "session_id", "") or "") != str(sessionId or ""):
            continue
        try:
            entries.extend(candidate.query(session_id=sessionId, limit=MAX_POOL_ENTRIES) or [])
        except Exception:  # noqa: BLE001 - 单池读数失败不拖垮诊断（与 /stats 同纪律）
            from neurova.core.logger import get_logger

            get_logger(__name__).warning("structure doctor: 单池读数失败", exc_info=True)
    return entries


def diagnoseSession(
    session_id: str,
    *,
    agent_id: str = None,
    session_manager: Any = None,
    pool: Any = None,
) -> StructureDiagnosis:
    """对真实存储里的一个会话做结构体检（只读）。

    三路数据来源：
    - messages：`session_manager.get_recent_model_context(..., max_messages=None)`
      （工具轮重建后的 OpenAI 形态，全会话不截断）；
    - pool_entries：注册表（或显式 pool）中 session 匹配池的 `query(session_id=...)`；
    - timeline_events：`session_manager.read_timeline(agent_id, session_id)`。

    `agent_id` 缺省时按会话文件/时间线文件反查。查无此会话时返回
    `checked["session_found"]=0` 且 issues 为空——不造数据凑诊断。
    """
    from neurova.session_manager import get_session_manager

    manager = session_manager if session_manager is not None else get_session_manager()
    sessionId = str(session_id or "")
    resolvedAgent = str(agent_id or "").strip() or _findAgentIdForSession(manager, sessionId)

    messages: List[Any] = []
    timeline: List[Any] = []
    sessionDates: List[Any] = []
    if resolvedAgent:
        messages = list(manager.get_recent_model_context(resolvedAgent, sessionId, max_messages=None) or [])
        timeline = list(manager.read_timeline(resolvedAgent, sessionId, limit=MAX_TIMELINE_EVENTS) or [])
        sessionDates = list(manager.get_sessions_by_id(resolvedAgent, sessionId) or [])

    poolEntries = _collectSessionPoolEntries(pool, sessionId)

    diagnosis = diagnoseStructure(
        messages=messages, pool_entries=poolEntries, timeline_events=timeline,
    )
    diagnosis.session_id = sessionId
    diagnosis.agent_id = resolvedAgent
    diagnosis.checked["session_found"] = int(
        bool(resolvedAgent) and bool(messages or timeline or poolEntries or sessionDates)
    )
    return diagnosis
