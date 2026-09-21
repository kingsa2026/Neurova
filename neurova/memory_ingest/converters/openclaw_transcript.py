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
from typing import Any, Dict, List, Optional, Tuple

from neurova.memory_ingest import probe
from neurova.memory_ingest.bundle.manifest import BundleError, BundleManifest
from neurova.memory_ingest.bundle.media import MediaSink
from neurova.memory_ingest.bundle.records import MemoryRecord
from neurova.memory_ingest.bundle.writer import (SourceEvent, dropped_entries, ensure_offset,
                                                 materialize, write_bundle)
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

# 记忆索引三表（同一支 agent 库）：正文在 chunks，出处与召回各一张附表
MEMORY_TABLE = "memory_index_chunks"
PROVENANCE_TABLE = "memory_index_chunk_provenance"
RECALL_TABLE = "memory_index_chunk_recall_metadata"
# 源列闭集两值 → 包内 (memory_type, category)；表外值不猜映射
SOURCE_FAMILIES = {"memory": ("semantic", "knowledge"), "sessions": ("episodic", "conversation")}
# 出处四值与本系统 MemoryOrigin 同词，逐字透传；缺出处落 untrusted 并申报（不整条丢，也不抬信任）
ORIGIN_CLASSES = ("owner", "agent", "untrusted", "system")
DEFAULT_IMPORTANCE = 50.0        # 源里没打重要度时用本系统默认档，不臆造分数
IMPORTANCE_SCALE = 10.0          # 源是 1-10，包内是 0-100
MEMORY_REASONS = {
    "memory:无出处": "源里没记 origin_class（或记的是词表外的值）：按 untrusted 最低信任导入",
    "memory:来源未知": "source 列出现已知两值之外的取值，不猜记忆类型映射，整条未导",
    "memory:空正文": "该索引项没有正文，包内 content 必填，未导",
    "memory:派生索引": "向量/内容哈希/嵌入模型属源侧派生索引，包内不搬（本系统自算）",
    "memory:无时间": "该条既不是 epoch 毫秒也不是可定标时间，整条未导（不写导入时刻）",
}

# 事件级与消息级字段的落点：表外的键一律按条数申报，不做"看起来不重要就略过"
EVENT_LANDINGS = ("id", "type", "message", "parentId", "timestamp")
MESSAGE_LANDINGS = ("role", "content", "summary", "timestamp", "idempotencyKey", "isError")

REASONS = {
    "event": "该事件类型不是可见正文（type != message），不猜映射",
    "事件id": "同一会话内 event id 被多行复用：幂等键立在行主键 (session_id, seq) 上，"
              "该 id 只作 extra 里的来源标识留档",
    "event键": "该事件级字段在包内契约与 extra 都无落点，未携带",
    "消息键": "该消息级字段在包内契约与 extra 都无落点，未携带",
    "role": "该角色在包内无对应 kind，不猜映射",
    "media": "源里的媒体载体取不到字节，未携带",
    "空正文": "该事件没有可携带正文，未入包",
    "blocks": "该块型在包内契约无落点，未携带",
    "timestamp": "事件与列都没给出可定标的时间，整行未入包（不猜时刻）",
}


def convert(store: Path, out_dir: Path, *, agent_name: str) -> BundleManifest:
    """一支 OpenClaw agent 库 → Ingest Bundle（会话与记忆索引同属这一支 store）。"""
    store, out_dir = Path(store), Path(out_dir)
    if not probe.matches_handprint(CONVERTER_NAME, store):
        raise BundleError(f"源不符合 {CONVERTER_NAME} 指纹，拒绝按这支转换器硬转：{store}")

    sink = MediaSink(out_dir, store=store)
    declared: Counter = Counter()
    memory_declared: Dict[str, List[Any]] = {}
    conn = probe.read_only_connect(store)
    conn.row_factory = sqlite3.Row
    try:
        windows = {row["session_id"]: dict(row) for row in conn.execute(
            f"SELECT * FROM {WINDOW_TABLE}")}
        by_session: Dict[str, List[Tuple[str, List[SourceEvent]]]] = {}
        seen_event_ids: Dict[str, set] = {}
        for row in conn.execute(f"SELECT session_id, seq, event_json, created_at"
                                f" FROM {EVENT_TABLE} ORDER BY session_id, seq"):
            session_id = str(row["session_id"])
            events = _event_records(row, windows.get(session_id, {}), sink, declared,
                                    seen_event_ids.setdefault(session_id, set()))
            if not events:
                continue
            by_session.setdefault(session_id, []).extend(events)
        memories = _memory_records(conn, memory_declared)
        tables = _table_names(conn)
    finally:
        conn.close()

    groups = [(sid, rows) for sid, rows in by_session.items()]
    return write_bundle(
        out_dir, materialize(groups), agent_name=agent_name,
        source={"converter": CONVERTER_NAME, "version": CONVERTER_VERSION,
                "verified_against": "upstream schema + transcript reader + memory index"},
        dropped=_dropped_entries(declared) + _declarations(memory_declared),
        stores=[{"path": str(store), "handprint": CONVERTER_NAME,
                 "sessions": len(groups), "memory_index": MEMORY_TABLE in tables}],
        memories=memories,
    )


def _table_names(conn: sqlite3.Connection) -> List[str]:
    return [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]


def _memory_records(conn: sqlite3.Connection,
                    declared: Dict[str, List[Any]]) -> List[MemoryRecord]:
    """记忆索引 → MemoryRecord：出处决定信任，来源决定类型，两者都缺就申报不猜。"""
    tables = set(_table_names(conn))
    if MEMORY_TABLE not in tables:
        return []
    sql = _memory_sql(tables)
    records = []
    for row in conn.execute(sql):
        record = _memory_record(row, declared)
        if record is not None:
            records.append(record)
    return records


def _memory_sql(tables: set) -> str:
    """附表可以没建（老库）：缺的表按 NULL 读，"没出处"由上层申报而不是 SQL 报错。"""
    prov_join = (f"LEFT JOIN {PROVENANCE_TABLE} AS p ON p.chunk_id = c.id"
                 if PROVENANCE_TABLE in tables else "")
    prov_cols = ("p.origin_class, p.session_kind, p.observed_at, p.supersedes_key"
                 if prov_join else "NULL AS origin_class, NULL AS session_kind,"
                                   " NULL AS observed_at, NULL AS supersedes_key")
    recall_join = (f"LEFT JOIN {RECALL_TABLE} AS m ON m.chunk_id = c.id"
                   if RECALL_TABLE in tables else "")
    recall_cols = ("m.importance, m.triggers, m.project_key" if recall_join
                   else "NULL AS importance, NULL AS triggers, NULL AS project_key")
    return (f"SELECT c.id, c.source, c.text, c.path, c.start_line, c.end_line, c.updated_at,"
            f" {prov_cols}, {recall_cols} FROM {MEMORY_TABLE} AS c"
            f" {prov_join} {recall_join} ORDER BY c.id")


def _memory_record(row: sqlite3.Row, declared: Dict[str, List[Any]]) -> Optional[MemoryRecord]:
    family = SOURCE_FAMILIES.get(str(row["source"] or ""))
    if family is None:
        _declare(declared, "memory:来源未知")
        return None
    origin = str(row["origin_class"] or "")
    if origin in ORIGIN_CLASSES:
        observed_at = row["observed_at"]
    else:
        # 没出处按最低信任导（源侧自己的回填也是 untrusted）：整条丢掉是丢内容，
        # 悄悄抬成 owner 是投毒；两者都不可取，就落最低档并把条数报出来。
        origin, observed_at = "untrusted", row["updated_at"]
        _declare(declared, "memory:无出处")
    text = str(row["text"] or "").strip()
    if not text:
        _declare(declared, "memory:空正文")
        return None
    _declare(declared, "memory:派生索引")
    moment = _from_ms(observed_at)
    if not moment:
        _declare(declared, "memory:无时间")
        return None
    importance = row["importance"]
    return MemoryRecord(
        identity_key=str(row["id"]), content=text, memory_type=family[0], category=family[1],
        origin=origin, importance=DEFAULT_IMPORTANCE if importance is None
        else float(importance) * IMPORTANCE_SCALE,
        ts=moment,
        tags=tuple(_memory_tags(row)), source_ref=f"{row['path']}#L{row['start_line']}"
                                                  f"-L{row['end_line']}",
        supersedes=str(row["supersedes_key"] or ""))


def _memory_tags(row: sqlite3.Row) -> List[str]:
    kinds = [("session_kind:" + str(row["session_kind"])) if row["session_kind"] else "",
             ("project:" + str(row["project_key"])) if row["project_key"] else "",
             ("trigger:" + str(row["triggers"])) if row["triggers"] else ""]
    return [tag for tag in kinds if tag]


def _declare(declared: Dict[str, List[Any]], field: str) -> None:
    bucket = declared.setdefault(field, [0, MEMORY_REASONS[field]])
    bucket[0] += 1


def _declarations(declared: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    return [{"field": field, "count": value[0], "reason": value[1]}
            for field, value in sorted(declared.items()) if value[0] > 0]


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
                   declared: Counter, seen_ids: set) -> List[Tuple[str, List[SourceEvent]]]:
    """一行源记录 → 幂等前缀 + 事件列表。

    幂等键立在**行自己的主键** ``(session_id, seq)`` 上，不立在信封的 event id 上：
    指纹只要求 transcript_events 与 session_windows 两张表，而 event id 的唯一性由上游第三张表
    transcript_event_identities 承担；老库没有那张表，且上游复制既往事件时会把同一条事件按新
    seq 再落一份（只修 parentId），因此"同 id 不同 seq"是合法形状。把它当幂等键，重复即整支
    store 被校验器判死；把它当可选标识，缺 id 的正文行又会被整行丢掉。两者都是把源侧不确定的
    东西当成我们的不变量。
    """
    body = _json(row["event_json"])
    if not _ts(body.get("timestamp"), row["created_at"]):
        declared["timestamp"] += 1
        return []
    event_id = str(body.get("id") or "").strip()
    declared.update(f"event键:{key}" for key in _strays(body, EVENT_LANDINGS))
    if event_id:
        if event_id in seen_ids:
            declared["事件id:复用"] += 1
        seen_ids.add(event_id)
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
                                "source_event_id": event_id or None,
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
    return [(f"{row['session_id']}#{int(row['seq'] or 0)}", built)]


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
    """epoch 毫秒 → 带偏移 ISO；也给字符串一次机会（老库有写 ISO 的），仍定不出回空串。"""
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ensure_offset(str(value or ""))


def _dropped_entries(declared: Counter) -> List[Dict[str, Any]]:
    return dropped_entries(declared, dict(REASONS, __fallback__=REASONS["event"]))


register_handprint(Handprint(CONVERTER_NAME, "sqlite", matches_store))
