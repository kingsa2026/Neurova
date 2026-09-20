# -*- coding: utf-8 -*-
"""OpenClaw 会话族（agent 库的 transcript_events）→ Ingest Bundle：只读源、只产包。

取证自本机该平台上游源码（不是靠样例猜）：
- 表结构 src/state/openclaw-agent-schema.sql：``transcript_events(session_id, seq,
  event_json, created_at)``，主键 (session_id, seq)，外键指向 ``session_windows``；
  会话出处在 session_windows（session_key / model / channel / chat_type / parent…）。
- 事件信封 src/config/sessions/session-accessor.sqlite-transcript-store.ts：
  ``{id, type, parentId, message}``，只有 ``type == "message"`` 时 message 才是可见正文；
  ``message.content`` 沿用 Anthropic 形块（text / thinking / tool_use / tool_result / 媒体），
  块词表因此复用 converters.blocks，不在第二家再抄一份规则。

seq 是主键但重写与压缩后会跳号：包内按会话重编 1..n，源 seq 留 extra.source_seq；
非 message 事件按类型申报条数，不猜它是正文。
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from neurova.memory_ingest import probe
from neurova.memory_ingest.bundle.manifest import BundleError, BundleManifest
from neurova.memory_ingest.bundle.media import MediaSink
from neurova.memory_ingest.bundle.writer import (SourceEvent, ensure_offset, materialize,
                                                 write_bundle)
from neurova.memory_ingest.converters.blocks import split_content
from neurova.memory_ingest.probe import Handprint, register_handprint

CONVERTER_NAME = "openclaw_transcript"
CONVERTER_VERSION = "1"
EVENT_TABLE = "transcript_events"
WINDOW_TABLE = "session_windows"

# 角色 → 包内 kind。结果与摘要是两种独立角色，判成"认不出"就等于把整条丢掉。
ROLE_KINDS = {"user": "user_message", "assistant": "assistant_message",
              "toolResult": "tool_result", "compactionSummary": "compact_summary",
              "system": "system"}
# 运行期与前端认得的角色名；表外的只留档不展示
RUNTIME_ROLES = ("user", "assistant", "system", "tool")
REQUIRED_EVENT_COLUMNS = ("session_id", "seq", "event_json", "created_at")

# 事件级与消息级字段的落点：表外的键一律按条数申报，不做"看起来不重要就略过"
EVENT_LANDINGS = ("id", "type", "message", "parentId", "timestamp")
MESSAGE_LANDINGS = ("role", "content", "summary", "timestamp", "idempotencyKey", "isError")

REASONS = {
    "event": "该事件类型不是可见正文（type != message），不猜映射",
    "event键": "该事件级字段在包内契约与 extra 都无落点，未携带",
    "消息键": "该消息级字段在包内契约与 extra 都无落点，未携带",
    "role": "该角色在包内无对应 kind，不猜映射",
    "media": "源里的媒体载体取不到字节，未携带",
    "空正文": "该事件没有可携带正文，未入包",
    "blocks": "该块型在包内契约无落点，未携带",
}


def convert(store: Path, out_dir: Path, *, agent_name: str) -> BundleManifest:
    """一支 OpenClaw agent 库 → Ingest Bundle（库里多场会话落进同一支包）。"""
    store, out_dir = Path(store), Path(out_dir)
    if not probe.matches_handprint(CONVERTER_NAME, store):
        raise BundleError(f"源不符合 {CONVERTER_NAME} 指纹，拒绝按这支转换器硬转：{store}")

    sink = MediaSink(out_dir, store=store)
    declared: Counter = Counter()
    conn = probe.read_only_connect(store)
    conn.row_factory = sqlite3.Row
    try:
        windows = {row["session_id"]: dict(row) for row in conn.execute(
            f"SELECT * FROM {WINDOW_TABLE}")}
        by_session: Dict[str, List[Tuple[str, List[SourceEvent]]]] = {}
        for row in conn.execute(f"SELECT session_id, seq, event_json, created_at"
                                f" FROM {EVENT_TABLE} ORDER BY session_id, seq"):
            session_id = str(row["session_id"])
            events = _event_records(row, windows.get(session_id, {}), sink, declared)
            if not events:
                continue
            by_session.setdefault(session_id, []).extend(events)
    finally:
        conn.close()

    groups = [(sid, rows) for sid, rows in by_session.items()]
    return write_bundle(
        out_dir, materialize(groups), agent_name=agent_name,
        source={"converter": CONVERTER_NAME, "version": CONVERTER_VERSION,
                "verified_against": "upstream schema + transcript reader"},
        dropped=_dropped_entries(declared),
        stores=[{"path": str(store), "handprint": CONVERTER_NAME,
                 "sessions": len(groups)}],
    )


def matches_store(path: Path) -> bool:
    """两张表一起认：外键目标没了就是漂移，不能半导。"""
    try:
        tables = set(probe.sqlite_tables(path))
        if not {EVENT_TABLE, WINDOW_TABLE} <= tables:
            return False
        return set(probe.source_columns(path, EVENT_TABLE)) >= set(REQUIRED_EVENT_COLUMNS)
    except sqlite3.Error:
        return False


def _event_records(row: sqlite3.Row, window: Dict[str, Any], sink: MediaSink,
                   declared: Counter) -> List[Tuple[str, List[SourceEvent]]]:
    body = _json(row["event_json"])
    event_id = str(body.get("id") or "").strip()
    declared.update(f"event键:{key}" for key in _strays(body, EVENT_LANDINGS))
    if not event_id:
        declared["event:<无id>"] += 1
        return []
    etype = str(body.get("type") or "<无类型>")
    if etype != "message":
        declared[f"event:{etype}"] += 1
        return []
    message = body.get("message") if isinstance(body.get("message"), dict) else {}
    role = str(message.get("role") or "")
    declared.update(f"消息键:{key}" for key in _strays(message, MESSAGE_LANDINGS))
    kind = ROLE_KINDS.get(role)
    if kind is None:
        declared[f"role:{role or '<空>'}"] += 1
        return []
    events, strays = split_content(message.get("content") or message.get("summary"), sink=sink)
    declared.update(strays)
    ts = _ts(body.get("timestamp"), row["created_at"])
    errored = "error" if message.get("isError") else ""
    # 包内 role 会被运行期与前端读到，源里的角色名（toolResult/compactionSummary）只留进 extra
    shown = role if role in RUNTIME_ROLES else ""
    built = [SourceEvent(kind=kind if event.kind == "assistant_message" else event.kind,
                         ts=ts, role=shown, text=event.text,
                         tool_call_id=event.tool_call_id, tool_name=event.tool_name,
                         tool_state=event.tool_state or errored,
                         reasoning=event.reasoning, reasoning_state=event.reasoning_state,
                         blocks=event.blocks,
                         extra={"source_seq": int(row["seq"] or 0), "event_type": etype,
                                "source_role": role or None,
                                "parent_event_id": body.get("parentId") or None,
                                "message_idempotency_key": message.get("idempotencyKey") or None,
                                "session_key": window.get("session_key"),
                                "model": window.get("model"),
                                "model_provider": window.get("model_provider"),
                                "channel": window.get("channel"),
                                "chat_type": window.get("chat_type"),
                                "source_created_at": row["created_at"],
                                "tool_input": event.tool_input or None})
             for event in events]
    if not built:
        declared["空正文"] += 1
        return []
    return [(f"{row['session_id']}#{event_id}", built)]


def _strays(body: Dict[str, Any], landings: Tuple[str, ...]) -> List[str]:
    """有值但表里没有落点的键——空值不算携带（包内契约本就"空值不写"）。"""
    return [key for key, value in body.items()
            if key not in landings and value not in (None, "", [], {})]


def _json(raw: Any) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ts(raw: Any, created_at: Any) -> str:
    """事件自带的 timestamp 是发生时刻，列 created_at 只是落库时刻——并存时取前者。"""
    if isinstance(raw, str) and raw.strip():
        text = ensure_offset(raw)
        try:
            datetime.fromisoformat(text)
        except ValueError:
            pass
        else:
            return text
    elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return _from_ms(raw)
    return _from_ms(created_at)


def _from_ms(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc).isoformat()


def _dropped_entries(declared: Counter) -> List[Dict[str, Any]]:
    entries = []
    for field, count in sorted(declared.items()):
        if count <= 0:
            continue
        prefix = field.split(":")[0]
        entries.append({"field": field, "count": count,
                        "reason": REASONS.get(prefix, REASONS["event"])})
    return entries


register_handprint(Handprint(CONVERTER_NAME, "sqlite", matches_store))
