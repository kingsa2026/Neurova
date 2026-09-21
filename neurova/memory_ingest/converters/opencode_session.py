# -*- coding: utf-8 -*-
"""opencode 会话族（opencode.db）→ Ingest Bundle：只读源、只产包。

取证自本机真实库（4 场会话 / 845 消息 / 4423 块）。这族的形态与前三支都不一样：

- 一次助手轮的正文散在 part 表的多个块里（text / reasoning / tool / step-* / patch /
  compaction / file），块内没有序号，只能按 time_created 定序；
- **tool 块把调用与结果放在同一个 state 里**（state.input 与 state.output，失败时是
  state.error），所以一支块要展开成包内两条事件，靠 callID 关联——这是互导最容易丢的地方；
- 计量（cost/tokens/model/agent/finish/path）挂在 message 的 data JSON 上，step-finish 块
  只是它的重复投影，因此不单独入包（申报里写清等价去处）；
- 源里时间是 epoch 毫秒（绝对时刻，无本地语义），统一按 UTC 定标，日期分桶因此可复现。

认不出的块型、非 user/assistant 的角色、以及本转换器还没覆盖的表（session_message /
session_input / todo）一律按条数申报：不猜映射，也不静默丢。
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
from neurova.memory_ingest.bundle.writer import (SourceEvent, dropped_entries,
                                                 materialize, write_bundle)
from neurova.memory_ingest.probe import Handprint, register_handprint

CONVERTER_NAME = "opencode_session"
CONVERTER_VERSION = "1"
SOURCE_ZONE = timezone.utc
ROLE_KINDS = {"user": "user_message", "assistant": "assistant_message"}
ROLE_PREFIXES = {"user_message": "user", "assistant_message": "assistant"}

REASONS: Dict[str, str] = {
    "part": "该块型在包内契约无落点，未携带",
    "part:step-start": "步进快照是运行时记账，包内不表达",
    "part:step-finish": "步进收尾的 cost/tokens 等价信息已挂在 message 级 extra 上，不重复入包",
    "part:patch": "本轮改动文件清单在包内无对应 kind，未携带",
    "media": "源里的媒体载体取不到字节（url 不是 data: 也不是源树内可读路径）",
    "role": "该角色在包内无对应 kind，不猜映射",
    "table": "该表承载的内容不在本转换器表达范围内（待记忆侧映射定案）",
    "无块": "该消息没有任何 content 块，正文载体缺失",
    "空正文": "该块没有可携带正文，未入包",
    "timestamp": "该块的 time_created 不是 epoch 毫秒，整块未入包（不猜时刻）",
}


def convert(store: Path, out_dir: Path, *, agent_name: str) -> BundleManifest:
    """一支 opencode.db → Ingest Bundle（只读源；库里多场会话落进同一支包）。"""
    store, out_dir = Path(store), Path(out_dir)
    if not probe.matches_handprint(CONVERTER_NAME, store):
        raise BundleError(f"源不符合 {CONVERTER_NAME} 指纹，拒绝按这支转换器硬转：{store}")

    sink = MediaSink(out_dir, store=store)
    declared: Counter = Counter()
    conn = probe.read_only_connect(store)
    conn.row_factory = sqlite3.Row
    try:
        titles = {row["id"]: row for row in _rows(conn, "SELECT id, title, parent_id FROM session")}
        groups = []
        for session_id in _session_order(conn):
            rows = _session_rows(conn, session_id, titles.get(session_id), sink, declared)
            if rows:
                groups.append((session_id, rows))
        _declare_side_tables(conn, declared)
    finally:
        conn.close()

    return write_bundle(
        out_dir, materialize(groups), agent_name=agent_name,
        source={"converter": CONVERTER_NAME, "version": CONVERTER_VERSION},
        dropped=_dropped_entries(declared),
        stores=[{"path": str(store), "handprint": CONVERTER_NAME, "sessions": len(groups)}],
    )


def matches_store(path: Path) -> bool:
    """认 message + part 两张表的骨架：缺任一张就不是这族。"""
    try:
        tables = set(probe.sqlite_tables(path))
        if not {"message", "part"} <= tables:
            return False
        return (set(probe.source_columns(path, "message")) >= {"id", "session_id", "data"}
                and set(probe.source_columns(path, "part")) >= {"id", "message_id", "data"})
    except sqlite3.Error:
        return False


def _session_order(conn: sqlite3.Connection) -> List[str]:
    rows = _rows(conn, "SELECT session_id, MIN(time_created) AS first_at FROM message"
                       " GROUP BY session_id ORDER BY first_at, session_id")
    return [row["session_id"] for row in rows]


def _session_rows(conn: sqlite3.Connection, session_id: str, session: Optional[sqlite3.Row],
                  sink: MediaSink, declared: Counter) -> List[Tuple[str, List[SourceEvent]]]:
    rows: List[Tuple[str, List[SourceEvent]]] = []
    for message in _rows(conn, "SELECT id, data, time_created FROM message"
                               " WHERE session_id = ? ORDER BY time_created, id", (session_id,)):
        data = _json(message["data"])
        kind = ROLE_KINDS.get(str(data.get("role") or ""))
        if kind is None:
            declared[f"role:{data.get('role') or '<空>'}"] += 1
            continue
        metering = _metering(data, session, first=not rows)
        parts = _rows(conn, "SELECT id, data, time_created FROM part"
                            " WHERE message_id = ? ORDER BY time_created, id", (message["id"],))
        produced = pending_thinking = 0
        pending: List[str] = []                          # 思考只在本条消息内挂靠
        for part in parts:
            body = _json(part["data"])
            if str(body.get("type") or "") == "reasoning":
                pending.append(str(body.get("text") or ""))
                pending_thinking += 1
                continue
            events = _part_events(part, body, kind, metering, sink, declared)
            if not events:
                continue
            produced += len(events)
            if pending:
                events = [events[0].__class__(**{**events[0].__dict__,
                                                 "reasoning": "".join(pending)}), *events[1:]]
                del pending[:]
            rows.append((f"{session_id}#{part['id']}", events))
        if pending:
            # 这条消息没有可挂靠的事件（可能整条只有思考块）：思考自己成一条，
            # 既不丢、也不会顺着会话窜到下一条消息（包括 user 消息）头上。
            rows.append((f"{session_id}#{message['id']}#reasoning",
                         [SourceEvent(kind=kind, ts=_ts(message["time_created"]),
                                      role=ROLE_PREFIXES[kind], reasoning="".join(pending),
                                      extra=dict(metering))]))
        elif not produced and not pending_thinking:
            declared["无块"] += 1
    return rows


def _part_events(part: sqlite3.Row, body: Dict[str, Any], kind: str, metering: Dict[str, Any],
                 sink: MediaSink, declared: Counter) -> List[SourceEvent]:
    """一支块 → 包内事件；tool 块出两条（调用 + 结果）。"""
    btype = str(body.get("type") or "<无类型>")
    ts = _ts(part["time_created"])
    if not ts:
        declared["timestamp"] += 1
        return []
    if btype == "text":
        text = str(body.get("text") or "")
        if not text.strip():
            declared["空正文"] += 1
            return []
        return [SourceEvent(kind=kind, ts=ts, role=ROLE_PREFIXES[kind], text=text,
                            extra=dict(metering))]
    if btype == "tool":
        return _tool_events(body, ts, metering)
    if btype == "compaction":
        return [SourceEvent(kind="compact_summary", ts=ts, role="assistant",
                            extra={**metering, "auto": body.get("auto"),
                                   "overflow": body.get("overflow"),
                                   "tail_start_id": body.get("tail_start_id")})]
    if btype == "file":
        ref = sink.resolve({"type": "file", "name": body.get("filename"),
                            "source": body.get("url")})
        if ref is None:
            declared["media:不可达"] += 1
            return []
        return [SourceEvent(kind=kind, ts=ts, role=ROLE_PREFIXES[kind],
                            blocks=(dict(ref, type="file",
                                         mime=body.get("mime") or ref.get("mime")),),
                            extra=dict(metering))]
    declared[f"part:{btype}"] += 1
    return []


def _tool_events(body: Dict[str, Any], ts: str, metering: Dict[str, Any]) -> List[SourceEvent]:
    state = body.get("state") if isinstance(body.get("state"), dict) else {}
    status = str(state.get("status") or "")
    output = state.get("output")
    if output is None:
        output = state.get("error")
    call_id = str(body.get("callID") or "")
    name = str(body.get("tool") or "")
    call = SourceEvent(kind="tool_call", ts=ts, role="assistant", tool_call_id=call_id,
                       tool_name=name, tool_state=status,
                       extra={**metering,
                              "tool_input": json.dumps(state.get("input") or {},
                                                       ensure_ascii=False),
                              "tool_title": state.get("title")})
    result = SourceEvent(kind="tool_result", ts=_end_time(state) or ts, role="tool",
                         text=str(output or ""), tool_call_id=call_id, tool_name=name,
                         tool_state=status)
    return [call, result]


def _end_time(state: Dict[str, Any]) -> Optional[str]:
    moment = state.get("time") if isinstance(state.get("time"), dict) else {}
    return _ts(moment.get("end")) if moment.get("end") else None


def _metering(data: Dict[str, Any], session: Optional[sqlite3.Row], *,
              first: bool) -> Dict[str, Any]:
    """message 级事实：模型、代理、花费、token、路径；会话标题与父子关系只跟首条。"""
    extra: Dict[str, Any] = {
        "agent": data.get("agent"), "model_id": data.get("modelID"),
        "provider_id": data.get("providerID"), "mode": data.get("mode"),
        "cost": data.get("cost"), "tokens": data.get("tokens"), "finish": data.get("finish"),
        "path": data.get("path"), "source_message_id": data.get("id"),
        "has_error": "error" in data,
    }
    if first and session is not None:
        extra["session_title"] = session["title"]
        extra["parent_session_id"] = session["parent_id"]
    return {key: value for key, value in extra.items() if value is not None and value is not False}


def _declare_side_tables(conn: sqlite3.Connection, declared: Counter) -> None:
    """本转换器还没覆盖的表：有条数就报，不假装看见了全部。"""
    for table in ("session_message", "session_input", "todo"):
        try:
            count = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.Error:
            continue                              # 老版本没这张表，不算丢失
        if count:
            declared[f"table:{table}"] += count


def _rows(conn: sqlite3.Connection, sql: str, args: Tuple = ()) -> List[sqlite3.Row]:
    return list(conn.execute(sql, args))


def _json(raw: Any) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ts(value: Any) -> str:
    """epoch 毫秒（绝对时刻）→ 带偏移 ISO；定不出来回空串，由调用方申报并跳过。"""
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return ""
    try:
        return datetime.fromtimestamp(millis / 1000, SOURCE_ZONE).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _dropped_entries(declared: Counter) -> List[Dict[str, Any]]:
    return dropped_entries(declared, dict(REASONS, __fallback__=REASONS["part"]))


register_handprint(Handprint(CONVERTER_NAME, "sqlite", matches_store))
