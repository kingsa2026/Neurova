# -*- coding: utf-8 -*-
"""公开会话族（conversation_history）→ Ingest Bundle：只读源、只产包，不碰任何 store。

三条硬规矩，都是本模块存在的理由：

1. 无损是承诺不是口号。每一列都必须在 COLUMN_LANDINGS 里有落点；源里冒出的新列、认不出的
   kind、契约装不下的块型一律写进 manifest.dropped 申报条数（实测源里确有 base64 图块）。
2. 一轮多调用按 blocks 展开。实测 model_turn 的 blocks 最多含 6 个 tool_call，而平列
   tool_call_id/tool_input 只留最后一个——按平列转就会把 179 个调用砍成 21 个（现脚本正是如此）。
   content 列等于各 text 块以换行拼接，所以 text 块是更细的同一份数据，不重复入包。
3. 编号与幂等键走 bundle.writer 的统一规则（源 seq 是全局流水号，包内按会话重编 1..n，
   源值留 extra.source_seq）。
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from neurova.memory_ingest import probe
from neurova.memory_ingest.bundle.manifest import BundleError, BundleManifest
from neurova.memory_ingest.probe import Handprint, register_handprint
from neurova.memory_ingest.bundle.writer import SourceEvent, materialize, write_bundle

CONVERTER_NAME = "qwenpaw_history"
CONVERTER_VERSION = "1"
SOURCE_TABLE = "conversation_history"

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
    "blocks": "展开为事件（text/tool_call/thinking）",
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

# 平列已表达过的块型：非 model_turn 行按平列取，这些块不算丢失
FLAT_REPRESENTED_BLOCKS = frozenset({"text", "tool_result", "thinking"})


def convert(store: Path, out_dir: Path, *, agent_name: str) -> BundleManifest:
    """把一支源 store 转成 Ingest Bundle，返回落盘的 manifest（供报告与申报）。"""
    store, out_dir = Path(store), Path(out_dir)
    if not probe.matches_handprint(CONVERTER_NAME, store):
        raise BundleError(f"源不符合 {CONVERTER_NAME} 指纹，拒绝按这支转换器硬转：{store}")

    rows = _read_rows(store)
    groups, skipped_kinds, stray_blocks = _groups(rows)
    records = materialize(groups)
    dropped = (_unmapped_column_drops(store, rows)
               + _declaration_entries("kind", skipped_kinds, "认不出的 kind 不猜映射，整行未入包")
               + _declaration_entries("blocks", stray_blocks,
                                      "该块型在包内契约无落点，未携带"
                                      "（图片/文件类需包内 media 内容寻址存储，本层未落地）"))
    return write_bundle(
        out_dir, records, agent_name=agent_name,
        source={"converter": CONVERTER_NAME, "version": CONVERTER_VERSION},
        dropped=dropped,
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


def _groups(rows: List[Dict[str, Any]]):
    """[(会话, [(幂等前缀, 事件)])]；会话按源 seq 升序，源 seq 全局唯一所以顺序确定。"""
    by_session: Dict[str, List[Tuple[str, List[SourceEvent]]]] = {}
    skipped_kinds: Counter = Counter()
    stray_blocks: Counter = Counter()
    for row in sorted(rows, key=_source_order):
        events, strays = _events_for_row(row)
        if events is None:
            skipped_kinds[_text(row.get("kind")) or "<空>"] += 1
            continue
        stray_blocks.update(strays)
        session_id = _text(row.get("session_id"))
        base_key = f"{session_id}#{_text(row.get('dedup_key')) or _int(row.get('seq'))}"
        by_session.setdefault(session_id, []).append((base_key, events))
    return list(by_session.items()), skipped_kinds, stray_blocks


def _source_order(row: Dict[str, Any]) -> Tuple[str, int]:
    """同一轮内各行共享 created_at，只有 seq 可信（实测全局唯一且单调）。"""
    return _text(row.get("session_id")), _int(row.get("seq"))


def _events_for_row(row: Dict[str, Any]) -> Tuple[Any, Counter]:
    """源行 → 事件列表；kind 认不出时返回 (None, ...) 交由申报处理。"""
    kind = SOURCE_KINDS.get(_text(row.get("kind")))
    blocks = _json_list(row.get("blocks"))
    if kind is None:
        return None, Counter()
    if kind == "assistant_message":
        return _expand_turn(row, blocks)
    return [_flat_event(row, kind, blocks)], _stray_blocks(blocks, FLAT_REPRESENTED_BLOCKS)


def _expand_turn(row: Dict[str, Any], blocks: List[Any]) -> Tuple[List[SourceEvent], Counter]:
    """model_turn 按块序展开：正文成段、每个调用独立成条，思考并入其后第一条。"""
    strays = _stray_blocks(blocks, frozenset({"text", "tool_call", "thinking"}))
    interesting = [block for block in blocks if isinstance(block, dict)]
    if not any(block.get("type") in ("text", "tool_call") for block in interesting):
        # 旧式行（无 blocks）或只有思考的行：平列才是正文的唯一载体
        thinking = "".join(_text(block.get("thinking")) for block in interesting
                           if block.get("type") == "thinking")
        return _fallback_events(row, thinking), strays

    events: List[SourceEvent] = []
    run: List[str] = []
    pending: List[str] = []
    for block in interesting:
        btype = block.get("type")
        if btype == "thinking":
            pending.append(_text(block.get("thinking")))
        elif btype == "text":
            run.append(str(block.get("text") or ""))
        elif btype == "tool_call":
            _flush_run(events, row, run, pending)
            events.append(_event(row, kind="tool_call", tool_call_id=_text(block.get("id")),
                                 tool_name=_text(block.get("name")),
                                 tool_state=_text(block.get("state")),
                                 tool_input=str(block.get("input") or ""),
                                 reasoning=_drain(pending)))
    _flush_run(events, row, run, pending)
    if pending and events:
        events[-1] = _with_reasoning(events[-1], _drain(pending))
    flat_call = _text(row.get("tool_call_id"))
    if flat_call and flat_call not in {event.tool_call_id for event in events}:
        events.append(_flat_tool_event(row))
    return [_tag_row_columns(row, index, event) for index, event in enumerate(events)], strays


def _fallback_events(row: Dict[str, Any], reasoning: str) -> List[SourceEvent]:
    """blocks 为空的旧式行：退回平列表达（正文 + 至多一个调用）。"""
    events: List[SourceEvent] = []
    if _text(row.get("content")) or reasoning:
        events.append(_event(row, text=_text(row.get("content")), reasoning=reasoning))
    if _text(row.get("tool_call_id")) or _text(row.get("tool_input")):
        events.append(_flat_tool_event(row))
    return [_tag_row_columns(row, index, event) for index, event in enumerate(events)]


def _flat_event(row: Dict[str, Any], kind: str, blocks: List[Any]) -> SourceEvent:
    thinking = "".join(_text(block.get("thinking")) for block in blocks
                       if isinstance(block, dict) and block.get("type") == "thinking")
    is_tool = kind in ("tool_call", "tool_result")
    event = _event(row, kind=kind, text=_text(row.get("content")),
                   tool_call_id=_text(row.get("tool_call_id")),
                   tool_name=_text(row.get("name")) if is_tool else "",
                   tool_state=_text(row.get("tool_state")), reasoning=thinking)
    if not is_tool:
        event = _with_extra(event, actor_name=_text(row.get("name")) or None)
    return _tag_row_columns(row, 0, event)


def _flat_tool_event(row: Dict[str, Any]) -> SourceEvent:
    return _event(row, kind="tool_call", tool_call_id=_text(row.get("tool_call_id")),
                  tool_name=_text(row.get("name")), tool_state=_text(row.get("tool_state")),
                  tool_input=str(row.get("tool_input") or ""))


def _flush_run(events: List[SourceEvent], row: Dict[str, Any], run: List[str],
               pending: List[str]) -> None:
    text = "".join(run)
    del run[:]
    if text:
        events.append(_event(row, text=text, reasoning=_drain(pending)))


def _event(row: Dict[str, Any], *, kind: str = "assistant_message", **fields: Any) -> SourceEvent:
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


def _with_reasoning(event: SourceEvent, extra: str) -> SourceEvent:
    """轮尾的思考并入最后一条事件：思考没有后继可挂靠时不丢。"""
    return replace(event, reasoning=event.reasoning + extra)


def _stray_blocks(blocks: List[Any], represented: frozenset) -> Counter:
    return Counter(str(block.get("type")) if isinstance(block, dict) else "<非对象>"
                   for block in blocks
                   if not isinstance(block, dict) or block.get("type") not in represented)


def _unmapped_column_drops(store: Path, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """源表比转换器已知列多出来的部分——按非空值计条数，让丢失量可核对。"""
    unknown = [col for col in probe.source_columns(store, SOURCE_TABLE)
               if col not in COLUMN_LANDINGS]
    return [{"field": col,
             "count": sum(1 for row in rows if _text(row.get(col))),
             "reason": "源列在包内契约与 extra 都无落点，未携带"}
            for col in unknown
            if any(_text(row.get(col)) for row in rows)]


def _declaration_entries(prefix: str, counter: Counter, reason: str) -> List[Dict[str, Any]]:
    return [{"field": f"{prefix}:{value}", "count": count, "reason": reason}
            for value, count in sorted(counter.items())]


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
    return _text(value) or datetime.now(timezone.utc).isoformat()


register_handprint(Handprint(CONVERTER_NAME, "sqlite",
                             probe.sqlite_has_columns(SOURCE_TABLE, REQUIRED_COLUMNS)))
