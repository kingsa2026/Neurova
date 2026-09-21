# -*- coding: utf-8 -*-
"""公开会话族（conversation_history）→ Ingest Bundle：只读源、只产包，不碰任何 store。

三条硬规矩，都是本模块存在的理由：

1. 无损是承诺不是口号。每一列都必须在 COLUMN_LANDINGS 里有落点；源里冒出的新列、认不出的
   kind、契约装不下的块型一律写进 manifest.dropped 申报条数。
2. 一轮多调用按 blocks 展开。实测 model_turn 的 blocks 最多含 6 个 tool_call，而平列
   tool_call_id/tool_input 只留最后一个——按平列转就会把 179 个调用砍成 21 个（现脚本正是如此）。
   content 列等于各 text 块以换行拼接，所以 text 块是更细的同一份数据，不重复入包。
3. 编号与幂等键走 bundle.writer 的统一规则（源 seq 是全局流水号，包内按会话重编 1..n，
   源值留 extra.source_seq）；媒体块按 bundle.media 的内容寻址落进包里。
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from neurova.memory_ingest import probe
from neurova.memory_ingest.bundle.manifest import BundleError, BundleManifest
from neurova.memory_ingest.bundle.media import MEDIA_BLOCK_TYPES, MediaSink
from neurova.memory_ingest.bundle.writer import (SourceEvent, dropped_entries, ensure_offset,
                                                 materialize, write_bundle)
from neurova.memory_ingest.probe import Handprint, register_handprint

CONVERTER_NAME = "qwenpaw_history"
CONVERTER_VERSION = "1"
SOURCE_TABLE = "conversation_history"
_SOURCE_ZONE = timezone(timedelta(hours=8))

# 必需列：缺任何一列就是漂移，宁可判"未识别"也不半导
REQUIRED_COLUMNS = ("seq", "session_id", "kind", "role", "content", "tool_call_id",
                    "created_at", "dedup_key")

# 源列 → 包内落点。空值不写，因此"落点"是字段归属而非"必然出现"。
COLUMN_LANDINGS: Dict[str, str] = {
    "seq": "extra.source_seq",
    "session_id": "session_id",
    "agent_id": "extra.agent_id",
    "kind": "kind",
    "role": "role",
    "name": "tool_name（工具行）/ extra.actor_name（其余行）",
    "content": "content_blocks",
    "tool_call_id": "tool_call_id",
    "tool_input": "extra.tool_input",
    "tool_state": "tool_state",
    "headline": "extra.headline",
    "blocks": "展开为事件（text/tool_call/thinking/媒体）",
    "metadata": "extra.source_metadata",
    "created_at": "ts",
    "dedup_key": "identity_key",
}

# 源 kind 词表 → 包内规范 kind；表外的值不猜，整行不入包并申报。
SOURCE_KINDS: Dict[str, str] = {
    "context_msg": "user_message",
    "model_turn": "assistant_message",
    "tool_result": "tool_result",
    "system": "system",
    "compact_summary": "compact_summary",
}

TURN_BLOCK_TYPES = frozenset({"text", "tool_call", "thinking"}) | frozenset(MEDIA_BLOCK_TYPES)
# 平列已表达过的块型：非 model_turn 行按平列取，这些块不算丢失
FLAT_REPRESENTED_BLOCKS = (frozenset({"text", "tool_result", "thinking"})
                           | frozenset(MEDIA_BLOCK_TYPES))

REASONS: Dict[str, str] = {
    "kind": "认不出的 kind 不猜映射，整行未入包",
    "blocks": "该块型在包内契约无落点，未携带",
    "media": "源里的媒体载体取不到字节（路径不在源目录树的 media/ 下，或 base64 不可解）",
    "column": "源列在包内契约与 extra 都无落点，未携带",
    "timestamp": "时间戳定不出时区/解不开，整行未入包（不猜时刻）",
    "空正文": "该行没有任何可携带内容（正文块为空且无调用），未入包",
}


def convert(store: Path, out_dir: Path, *, agent_name: str) -> BundleManifest:
    """把一支源 store 转成 Ingest Bundle，返回落盘的 manifest（供报告与申报）。"""
    store, out_dir = Path(store), Path(out_dir)
    if not probe.matches_handprint(CONVERTER_NAME, store):
        raise BundleError(f"源不符合 {CONVERTER_NAME} 指纹，拒绝按这支转换器硬转：{store}")

    rows = _read_rows(store)
    groups, declared = _groups(rows, MediaSink(out_dir, store=store))
    declared.update(_column_decls(store, rows))
    records = materialize(groups)
    return write_bundle(
        out_dir, records, agent_name=agent_name,
        source={"converter": CONVERTER_NAME, "version": CONVERTER_VERSION},
        dropped=_dropped_entries(declared),
        stores=[{"path": str(store), "handprint": CONVERTER_NAME,
                 "source_table": SOURCE_TABLE, "source_rows": len(rows)}],
    )


def _read_rows(store: Path) -> List[Dict[str, Any]]:
    conn = probe.read_only_connect(store)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {SOURCE_TABLE}")]
    finally:
        conn.close()


def _groups(rows: List[Dict[str, Any]], sink: MediaSink):
    """[(会话, [(幂等前缀, 事件)])] + 申报计数；会话按源 seq 升序（实测全局唯一且单调）。"""
    by_session: Dict[str, List[Tuple[str, List[SourceEvent]]]] = {}
    declared: Counter = Counter()
    for row in sorted(rows, key=_source_order):
        events = _events_for_row(row, sink, declared)
        if events is None:
            continue
        session_id = _text(row.get("session_id"))
        base_key = f"{session_id}#{_text(row.get('dedup_key')) or _int(row.get('seq'))}"
        by_session.setdefault(session_id, []).append((base_key, events))
    return list(by_session.items()), declared


def _source_order(row: Dict[str, Any]) -> Tuple[str, int]:
    """同一轮内各行共享 created_at，只有 seq 可信。"""
    return _text(row.get("session_id")), _int(row.get("seq"))


def _events_for_row(row: Dict[str, Any], sink: MediaSink, declared: Counter):
    """源行 → 事件列表；kind 认不出时申报后返回 None。"""
    kind = SOURCE_KINDS.get(_text(row.get("kind")))
    blocks = _json_list(row.get("blocks"))
    if kind is None:
        declared[f"kind:{_text(row.get('kind')) or '<空>'}"] += 1
        return None
    if not _ts(row.get("created_at")):
        declared["timestamp"] += 1
        return None
    if kind == "assistant_message":
        events = _expand_turn(row, blocks, sink)
        if not events:
            # 块全是空正文又无调用：这行确实没有可携带内容，但"没东西"必须报出来，
            # 不能让它在包外看成一个从未存在的行。
            declared["空正文"] += 1
            return None
    else:
        events = [_flat_event(row, kind, blocks, sink)]
    declared.update(_stray_blocks(blocks, sink, TURN_BLOCK_TYPES if kind == "assistant_message"
                                  else FLAT_REPRESENTED_BLOCKS))
    return events


def _expand_turn(row: Dict[str, Any], blocks: List[Any], sink: MediaSink) -> List[SourceEvent]:
    """model_turn 按块序展开：正文成段、每个调用独立成条，思考与媒体并入其后第一条。"""
    interesting = [block for block in blocks if isinstance(block, dict)]
    carriers = [block for block in interesting
                if block.get("type") in ("text", "tool_call")]
    media = _media_refs(interesting, sink)
    if not carriers:
        # 旧式行（无 blocks）或只有思考/媒体的行：平列才是正文的唯一载体
        thinking = "".join(_text(block.get("thinking")) for block in interesting
                           if block.get("type") == "thinking")
        return _fallback_events(row, thinking, media)

    events: List[SourceEvent] = []
    run: List[str] = []
    pending: List[str] = []
    awaiting = list(media)                       # 媒体按块序挂到它之后的第一条事件上
    for block in interesting:
        btype = block.get("type")
        if btype == "thinking":
            pending.append(_text(block.get("thinking")))
        elif btype == "text":
            run.append(str(block.get("text") or ""))
        elif btype == "tool_call":
            _flush_run(events, row, run, pending, awaiting)
            awaiting = []
            events.append(_event(row, kind="tool_call", tool_call_id=_text(block.get("id")),
                                 tool_name=_text(block.get("name")),
                                 tool_state=_text(block.get("state")),
                                 tool_input=str(block.get("input") or ""),
                                 reasoning=_drain(pending)))
    _flush_run(events, row, run, pending, awaiting)
    _tail(events, pending, awaiting)
    flat_call = _text(row.get("tool_call_id"))
    if flat_call and flat_call not in {event.tool_call_id for event in events}:
        events.append(_flat_tool_event(row))
    return [_tag_row_columns(row, index, event) for index, event in enumerate(events)]


def _fallback_events(row: Dict[str, Any], reasoning: str,
                     media: List[Dict[str, Any]]) -> List[SourceEvent]:
    """blocks 为空的旧式行：退回平列表达（正文 + 至多一个调用）。"""
    events: List[SourceEvent] = []
    if _text(row.get("content")) or reasoning or media:
        events.append(_event(row, text=_text(row.get("content")), reasoning=reasoning,
                             blocks=tuple(media)))
    if _text(row.get("tool_call_id")) or _text(row.get("tool_input")):
        events.append(_flat_tool_event(row))
    return [_tag_row_columns(row, index, event) for index, event in enumerate(events)]


def _flat_event(row: Dict[str, Any], kind: str, blocks: List[Any],
                sink: MediaSink) -> SourceEvent:
    interesting = [block for block in blocks if isinstance(block, dict)]
    thinking = "".join(_text(block.get("thinking")) for block in interesting
                       if block.get("type") == "thinking")
    is_tool = kind in ("tool_call", "tool_result")
    event = _event(row, kind=kind, text=_text(row.get("content")),
                   tool_call_id=_text(row.get("tool_call_id")),
                   tool_name=_text(row.get("name")) if is_tool else "",
                   tool_state=_text(row.get("tool_state")), reasoning=thinking,
                   blocks=tuple(_media_refs(interesting, sink)))
    if not is_tool:
        event = _with_extra(event, actor_name=_text(row.get("name")) or None)
    return _tag_row_columns(row, 0, event)


def _flat_tool_event(row: Dict[str, Any]) -> SourceEvent:
    return _event(row, kind="tool_call", tool_call_id=_text(row.get("tool_call_id")),
                  tool_name=_text(row.get("name")), tool_state=_text(row.get("tool_state")),
                  tool_input=str(row.get("tool_input") or ""))


def _flush_run(events: List[SourceEvent], row: Dict[str, Any], run: List[str],
               pending: List[str], awaiting: List[Dict[str, Any]]) -> None:
    text = "".join(run)
    del run[:]
    if text or (pending and not events) or (awaiting and not events):
        events.append(_event(row, text=text, reasoning=_drain(pending),
                             blocks=tuple(awaiting)))
        del awaiting[:]


def _tail(events: List[SourceEvent], pending: List[str],
          awaiting: List[Dict[str, Any]]) -> None:
    """轮尾剩下的思考/媒体并入最后一条：没有后继可挂靠时也不丢。"""
    if not events:
        return
    reasoning, blocks = _drain(pending), list(awaiting)
    if reasoning or blocks:
        events[-1] = replace(events[-1], reasoning=events[-1].reasoning + reasoning,
                             blocks=events[-1].blocks + tuple(blocks))
        del awaiting[:]


def _event(row: Dict[str, Any], *, kind: str = "assistant_message",
           **fields: Any) -> SourceEvent:
    """行级公共字段（ts/role + 契约无落点的列）统一在此挂上。"""
    extra = {"source_seq": _int(row.get("seq")), "agent_id": row.get("agent_id"),
             "tool_input": fields.pop("tool_input", None)}
    return SourceEvent(kind=kind, ts=_ts(row.get("created_at")), role=_text(row.get("role")),
                       extra=extra, **fields)


def _tag_row_columns(row: Dict[str, Any], index: int, event: SourceEvent) -> SourceEvent:
    """行级列（headline/metadata）只跟首条事件，展开后不重复计数。"""
    if index > 0:
        return event
    return _with_extra(event, headline=row.get("headline"), source_metadata=row.get("metadata"))


def _with_extra(event: SourceEvent, **items: Any) -> SourceEvent:
    return replace(event, extra={**event.extra, **items})


def _media_refs(blocks: List[Any], sink: MediaSink) -> List[Dict[str, Any]]:
    refs = []
    for block in blocks:
        if block.get("type") not in MEDIA_BLOCK_TYPES:
            continue
        ref = sink.resolve(block)
        if ref:
            refs.append(dict(ref, type="image" if block.get("type") == "data"
                             else block.get("type")))
    return refs


def _stray_blocks(blocks: List[Any], sink: MediaSink, represented: frozenset) -> Counter:
    """这一行装不下的东西：未知块型与解不出字节的媒体，各自计数。"""
    strays: Counter = Counter()
    for block in blocks:
        btype = block.get("type") if isinstance(block, dict) else None
        if isinstance(block, dict) and btype in MEDIA_BLOCK_TYPES:
            if not sink.resolve(block):
                strays["media:不可达"] += 1
            continue
        if btype not in represented:
            strays[f"blocks:{btype or '<非对象>'}"] += 1
    return strays


def _column_decls(store: Path, rows: List[Dict[str, Any]]) -> Counter:
    """源表比转换器已知列多出来的部分——按非空值计条数，让丢失量可核对。"""
    unknown = [col for col in probe.source_columns(store, SOURCE_TABLE)
               if col not in COLUMN_LANDINGS]
    return Counter({f"column:{col}": sum(1 for row in rows if _text(row.get(col)))
                    for col in unknown})


def _dropped_entries(declared: Counter) -> List[Dict[str, Any]]:
    entries = dropped_entries(declared, dict(REASONS, __fallback__=REASONS["blocks"]))
    for entry in entries:                      # 源列申报只显示列名（列名前缀是本族约定）
        entry["field"] = entry["field"].split(":", 1)[1] \
            if entry["field"].startswith("column:") else entry["field"]
    return entries


def _json_list(raw: Any) -> List[Any]:
    try:
        parsed = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _drain(items: List[str]) -> str:
    text = "".join(items)
    del items[:]
    return text


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _ts(value: Any) -> str:
    """源里是本地墙钟裸时间（实测 2026-08-20T21:20:52.669271）：按 +08:00 定标。"""
    return ensure_offset(_text(value), _SOURCE_ZONE)


register_handprint(Handprint(CONVERTER_NAME, "sqlite",
                             probe.sqlite_has_columns(SOURCE_TABLE, REQUIRED_COLUMNS)))
