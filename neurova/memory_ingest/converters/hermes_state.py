# -*- coding: utf-8 -*-
"""Hermes 会话族（单库里的 messages + sessions 两张表）→ Ingest Bundle：只读源、只产包。

取证自该平台上游公开源码的建表语句与写入侧行构造（其 SCHEMA_VERSION=30）：
- ``messages`` 26 列；正文列是 TEXT，块数组以 ``"\\x00json:"`` 哨兵前缀存 JSON（编解码成对出现），
  一次调用一条 ``tool_calls`` 元素，工具结果另起一行靠 ``tool_call_id`` 关联；
- ``sessions`` 是会话出处（source / session_key / model / chat_type / parent_session_id / title），
  ``messages.session_id`` 外键指向它；
- ``schema_version(version)`` 一支——这一家带版本号，漂移可以直接判，不必像无版本的两族那样
  只靠必需列齐不齐兜底。

顺序靠 ``messages.id``（AUTOINCREMENT）而不是时间戳；时间列是 REAL 秒。``_compressed_summary``
标出的行是压缩摘要，不是普通 system 行。三个结构化推理列存的不是人类可读推理：包内只标
opaque、不搬密文，并按条数申报。
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.memory_ingest import probe
from neurova.memory_ingest.bundle.manifest import BundleError, BundleManifest
from neurova.memory_ingest.bundle.media import MediaSink
from neurova.memory_ingest.bundle.writer import SourceEvent, materialize, write_bundle
from neurova.memory_ingest.converters.blocks import ContentEvent, split_content
from neurova.memory_ingest.probe import Handprint, register_handprint

CONVERTER_NAME = "hermes_state"
CONVERTER_VERSION = "1"
MESSAGE_TABLE = "messages"
SESSION_TABLE = "sessions"
VERSION_TABLE = "schema_version"
KNOWN_SCHEMA_VERSION = 30
CONTENT_JSON_PREFIX = "\x00json:"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

ROLE_KINDS = {"user": "user_message", "assistant": "assistant_message",
              "tool": "tool_result", "system": "system"}
REQUIRED_MESSAGE_COLUMNS = ("id", "session_id", "role", "content", "tool_call_id",
                            "tool_calls", "tool_name", "timestamp")
REQUIRED_SESSION_COLUMNS = ("id", "source")
# 推理只在结构化列里出现时仍要看得见条数（正文读不出，但"有多少条"不能糊过去）
STRUCTURED_REASONING = ("reasoning_details", "codex_reasoning_items", "codex_message_items")
# 已知且刻意不携带的列：仍按非空行数申报，丢失量要能核对
UNCARRIED = ("api_content", "display_metadata", "display_identity")

# 每一列都必须有落点；表里冒出已知列之外的列就按非空行数申报，不做"看起来不重要就略过"
COLUMN_LANDINGS: Dict[str, str] = {
    "id": "identity_key",
    "session_id": "session_id",
    "role": "kind/role",
    "content": "content_blocks（哨兵前缀的块数组按块展开）",
    "tool_call_id": "tool_call_id",
    "tool_calls": "展开为 tool_call 事件（一行可多条）",
    "tool_name": "tool_name",
    "effect_disposition": "extra.effect_disposition",
    "timestamp": "ts",
    "token_count": "extra.token_count",
    "finish_reason": "extra.finish_reason",
    "reasoning": "reasoning_text",
    "reasoning_content": "reasoning_text",
    "reasoning_details": "reasoning_state=opaque（结构化不搬运）",
    "codex_reasoning_items": "reasoning_state=opaque（同上）",
    "codex_message_items": "reasoning_state=opaque（同上）",
    "platform_message_id": "extra.platform_message_id",
    "observed": "extra.observed",
    "_compressed_summary": "kind=compact_summary",
    "active": "extra.active",
    "compacted": "extra.compacted",
    "api_content": "申报不携带：发送侧原文与正文同义，包内只留一份正文",
    "display_kind": "extra.display_kind",
    "display_metadata": "申报不携带：展示层附加信息，非会话内容",
    "display_identity": "申报不携带：源侧去重用的 BLOB 摘要",
    "display_order": "extra.display_order",
}

UNKNOWN_COLUMN_REASON = "源列在包内契约与 extra 都无落点，未携带"
REASONS = {
    "role": "该角色在包内无对应 kind，不猜映射",
    "空正文": "该行没有任何可携带正文，未入包",
    "blocks": "该块型在包内契约无落点，未携带",
    "media": "源里的媒体载体取不到字节，未携带",
    "tool_calls": "该调用元素读不出字段，未展开",
    "reasoning": "该行推理只存在于结构化列，包内标 opaque、不搬运密文",
    "schema_version": "该库结构版本比转换器已知的更新，列面逐列核对通过才转",
    "api_content": "发送侧原文与正文同义，包内只留一份正文",
    "display_metadata": "展示层附加信息，非会话内容，未携带",
    "display_identity": "源侧去重用的 BLOB 摘要，包内无从表达，未携带",
}


def convert(store: Path, out_dir: Path, *, agent_name: str) -> BundleManifest:
    """一支 Hermes 状态库 → Ingest Bundle（库里多场会话落进同一支包）。"""
    store, out_dir = Path(store), Path(out_dir)
    if not probe.matches_handprint(CONVERTER_NAME, store):
        raise BundleError(f"源不符合 {CONVERTER_NAME} 指纹，拒绝按这支转换器硬转：{store}")

    sink = MediaSink(out_dir, store=store)
    declared: Counter = Counter()
    conn = probe.read_only_connect(store)
    conn.row_factory = sqlite3.Row
    try:
        version = _schema_version(conn)
        sessions = {row["id"]: dict(row) for row in conn.execute(f"SELECT * FROM {SESSION_TABLE}")}
        groups: Dict[str, List[Tuple[str, List[SourceEvent]]]] = {}
        for raw in conn.execute(f"SELECT * FROM {MESSAGE_TABLE} ORDER BY session_id, id"):
            row = dict(raw)
            session_id = str(row.get("session_id") or "")
            events = _row_events(row, sessions.get(session_id, {}), sink, declared)
            if events:
                groups.setdefault(session_id, []).append((f"{session_id}#{row.get('id')}", events))
        columns = [column[1] for column in conn.execute(f"PRAGMA table_info({MESSAGE_TABLE})")]
        column_entries = _column_entries(conn, columns)
    finally:
        conn.close()

    return write_bundle(
        out_dir, materialize([(sid, rows) for sid, rows in groups.items()]),
        agent_name=agent_name,
        source={"converter": CONVERTER_NAME, "version": CONVERTER_VERSION,
                "verified_against": "upstream schema DDL + row builder"},
        dropped=_dropped_entries(declared) + column_entries + _version_entry(version),
        stores=[{"path": str(store), "handprint": CONVERTER_NAME,
                 "source_table": MESSAGE_TABLE, "schema_version": version,
                 "sessions": len(groups)}],
    )


def matches_store(path: Path) -> bool:
    """三张表一起认：出处表或版本号没了就是漂移，宁可判未识别也不半导。"""
    try:
        if not {MESSAGE_TABLE, SESSION_TABLE, VERSION_TABLE} <= set(probe.sqlite_tables(path)):
            return False
        if not set(probe.source_columns(path, MESSAGE_TABLE)) >= set(REQUIRED_MESSAGE_COLUMNS):
            return False
        return set(probe.source_columns(path, SESSION_TABLE)) >= set(REQUIRED_SESSION_COLUMNS)
    except sqlite3.Error:
        return False


def _row_events(row: Dict[str, Any], session: Dict[str, Any], sink: MediaSink,
                declared: Counter) -> List[SourceEvent]:
    role = str(row.get("role") or "")
    kind = "compact_summary" if row.get("_compressed_summary") else ROLE_KINDS.get(role)
    if kind is None:
        declared[f"role:{role or '<空>'}"] += 1
        return []
    blocks, strays = split_content(_decode_content(row.get("content")), sink=sink)
    declared.update(strays)
    reasoning, opaque = _reasoning(row)
    if opaque:
        # 有明文摘要不等于结构化列没被丢：密文项照条数申报，两份来源都得看得见
        declared["reasoning:结构化"] += 1
    base = _extra(row, session)
    events = _content_events(row, kind, blocks, base, reasoning, opaque)
    events += _call_events(row, base, declared)
    if not events:
        declared["空正文"] += 1
    return events


def _content_events(row: Dict[str, Any], kind: str, blocks: List[ContentEvent],
                    base: Dict[str, Any], reasoning: str,
                    opaque: bool) -> List[SourceEvent]:
    if not blocks and row.get("tool_call_id"):
        blocks = [ContentEvent("tool_result")]      # 结果为空串时调用位也不能丢
    state = "text" if reasoning else ("opaque" if opaque else "")
    events = []
    for index, block in enumerate(blocks):
        events.append(SourceEvent(
            kind=block.kind if block.kind.startswith("tool_") else kind,
            ts=_ts(row.get("timestamp")), role=str(row.get("role") or ""),
            text=block.text, blocks=block.blocks,
            tool_call_id=str(row.get("tool_call_id") or "") or block.tool_call_id,
            tool_name=str(row.get("tool_name") or "") or block.tool_name,
            tool_state=block.tool_state,
            reasoning=reasoning if index == 0 else "",
            reasoning_state=(state if index == 0 else "") or block.reasoning_state,
            extra={**base, "tool_input": block.tool_input or None}))
    return events


def _call_events(row: Dict[str, Any], base: Dict[str, Any],
                 declared: Counter) -> List[SourceEvent]:
    """assistant 行的 tool_calls 数组：一条元素一次调用，结果在后续 tool 行里。"""
    if not row.get("tool_calls"):
        return []
    raw = _json(row["tool_calls"])
    if not isinstance(raw, list):
        declared["tool_calls:<非数组>"] += 1
        return []
    events = []
    for entry in raw:
        parsed = _call_fields(entry)
        if parsed is None:
            declared["tool_calls:<读不出字段>"] += 1
            continue
        call_id, name, arguments = parsed
        events.append(SourceEvent(kind="tool_call", ts=_ts(row.get("timestamp")),
                                  role=str(row.get("role") or ""), tool_call_id=call_id,
                                  tool_name=name,
                                  extra={**base, "tool_input": _dump(arguments)}))
    return events


def _call_fields(entry: Any) -> Optional[Tuple[str, str, Any]]:
    """调用元素两形都收：套 function 子对象的与平铺 name/arguments 的。"""
    if not isinstance(entry, dict):
        return None
    spec = entry.get("function") if isinstance(entry.get("function"), dict) else entry
    call_id = str(entry.get("id") or entry.get("call_id") or "").strip()
    name = str(spec.get("name") or "").strip()
    if not (call_id or name):
        return None
    return call_id, name, _first(spec, ("arguments", "input", "args"))


def _extra(row: Dict[str, Any], session: Dict[str, Any]) -> Dict[str, Any]:
    return {"source_message_id": row.get("id"),
            "effect_disposition": row.get("effect_disposition"),
            "token_count": row.get("token_count"), "finish_reason": row.get("finish_reason"),
            "platform_message_id": row.get("platform_message_id"),
            "observed": row.get("observed"), "active": row.get("active"),
            "compacted": row.get("compacted"), "display_kind": row.get("display_kind"),
            "display_order": row.get("display_order"),
            "session_source": session.get("source"), "session_key": session.get("session_key"),
            "chat_id": session.get("chat_id"), "chat_type": session.get("chat_type"),
            "model": session.get("model"), "session_title": session.get("title"),
            "parent_session_id": session.get("parent_session_id")}


def _reasoning(row: Dict[str, Any]) -> Tuple[str, bool]:
    text = str(row.get("reasoning") or "") + str(row.get("reasoning_content") or "")
    return text, any(row.get(column) for column in STRUCTURED_REASONING)


def _decode_content(raw: Any) -> Any:
    """哨兵前缀的 JSON 还原成块数组；前缀之外的一律当正文，不额外猜 JSON。"""
    if isinstance(raw, str) and raw.startswith(CONTENT_JSON_PREFIX):
        try:
            return json.loads(raw[len(CONTENT_JSON_PREFIX):])
        except ValueError:
            return raw[len(CONTENT_JSON_PREFIX):]
    return raw


def _column_entries(conn: sqlite3.Connection,
                    columns: List[str]) -> List[Dict[str, Any]]:
    """漂移列（契约外新冒出来的）与刻意不携带的已知列，都按非空行数申报。"""
    entries = []
    for column in columns:
        if column in COLUMN_LANDINGS and column not in UNCARRIED:
            continue
        count = _non_empty_rows(conn, column)
        if count:
            entries.append({"field": column, "count": count,
                            "reason": REASONS.get(column, UNKNOWN_COLUMN_REASON)})
    return entries


def _non_empty_rows(conn: sqlite3.Connection, column: str) -> int:
    """列名来自 sqlite_master，仍按标识符白名单把关——拼 SQL 的地方不留口子。"""
    if not IDENTIFIER.match(column):
        return 0
    quoted = f'"{column}"'
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {MESSAGE_TABLE}"
                                f" WHERE {quoted} IS NOT NULL AND {quoted} != ''").fetchone()[0])
    except (sqlite3.Error, TypeError, ValueError):
        return 0


def _version_entry(version: Optional[int]) -> List[Dict[str, Any]]:
    if version is None or version <= KNOWN_SCHEMA_VERSION:
        return []
    return [{"field": f"schema_version:{version}", "count": 1,
             "reason": f"{REASONS['schema_version']}（已知上限 {KNOWN_SCHEMA_VERSION}）"}]


def _schema_version(conn: sqlite3.Connection) -> Optional[int]:
    try:
        value = conn.execute(f"SELECT MAX(version) FROM {VERSION_TABLE}").fetchone()[0]
    except sqlite3.Error:
        return None
    return int(value) if value is not None else None


def _dropped_entries(declared: Counter) -> List[Dict[str, Any]]:
    return [{"field": field, "count": count,
             "reason": REASONS.get(str(field).split(":")[0], UNKNOWN_COLUMN_REASON)}
            for field, count in sorted(declared.items()) if count > 0]


def _json(raw: Any) -> Any:
    try:
        return json.loads(raw) if isinstance(raw, str) and raw else raw
    except ValueError:
        return None


def _first(mapping: Dict[str, Any], keys: Tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _dump(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _ts(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc).isoformat()


register_handprint(Handprint(CONVERTER_NAME, "sqlite", matches_store))
