# -*- coding: utf-8 -*-
"""公开会话族（conversation_history）→ Ingest Bundle：只读源、只产包，不碰任何 store。

三条硬规矩，都是本模块存在的理由：

1. 无损是承诺不是口号。每一列都必须在 COLUMN_LANDINGS 里有落点；源里冒出的新列、认不出的
   kind、契约装不下的块型一律写进 manifest.dropped 申报条数（实测源里确有 base64 图块）。
2. 一轮多调用按 blocks 展开。实测 model_turn 的 blocks 最多含 6 个 tool_call，而平列
   tool_call_id/tool_input 只留最后一个——按平列转就会把 179 个调用砍成 21 个（现脚本正是如此）。
   content 列等于各 text 块以换行拼接，所以 text 块是更细的同一份数据，不重复入包。
3. 包内 seq 由本模块按会话重编 1..n（源 seq 是全局流水号，跨会话不连续），源 seq 留在
   extra.source_seq；一行展开成多条时 identity_key 追加事件序号，保证幂等键各自可寻址。
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from neurova.memory_ingest import probe
from neurova.memory_ingest.bundle.manifest import BundleError, BundleManifest, dump_manifest
from neurova.memory_ingest.bundle.records import TranscriptRecord

CONVERTER_NAME = "qwenpaw_history"
CONVERTER_VERSION = "1"
SOURCE_TABLE = "conversation_history"

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


@dataclass(frozen=True)
class _Event:
    """源行展开后的一条待落包事件（seq 与 identity_key 稍后按会话统一编号）。"""
    kind: str
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_state: str = ""
    tool_input: str = ""
    reasoning: str = ""


def convert(store: Path, out_dir: Path, *, agent_name: str) -> BundleManifest:
    """把一支源 store 转成 Ingest Bundle，返回落盘的 manifest（供报告与申报）。"""
    store, out_dir = Path(store), Path(out_dir)
    if not probe.matches_handprint(CONVERTER_NAME, store):
        raise BundleError(f"源不符合 {CONVERTER_NAME} 指纹，拒绝按这支转换器硬转：{store}")

    rows = _read_rows(store)
    records, skipped_kinds, stray_blocks = _to_records(rows)
    dropped = (_unmapped_column_drops(store, rows)
               + _declaration_entries("kind", skipped_kinds, "认不出的 kind 不猜映射，整行未入包")
               + _declaration_entries("blocks", stray_blocks,
                                      "该块型在包内契约无落点，未携带"
                                      "（图片/文件类需包内 media 内容寻址存储，本层未落地）"))

    manifest = BundleManifest(
        schema_version=1,
        generated_at=datetime.now(timezone.utc).isoformat(),
        agent_name=agent_name,
        source={"converter": CONVERTER_NAME, "version": CONVERTER_VERSION},
        counts={"transcripts": len(records), "memories": 0, "relations": 0},
        dropped=tuple(dropped),
        stores=({"path": str(store), "handprint": CONVERTER_NAME,
                 "source_table": SOURCE_TABLE, "source_rows": len(rows)},),
    )
    _write_bundle(out_dir, records, manifest)
    return manifest


def _read_rows(store: Path) -> List[Dict[str, Any]]:
    conn = probe.read_only_connect(store)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {SOURCE_TABLE}")]
    finally:
        conn.close()


def _to_records(rows: List[Dict[str, Any]]) -> Tuple[List[TranscriptRecord], Counter, Counter]:
    """按会话分组重编号；返回 (记录, 被跳过的 kind 计数, 装不下的块型计数)。"""
    seq_in_session: Dict[str, int] = {}
    records: List[TranscriptRecord] = []
    skipped_kinds: Counter = Counter()
    stray_blocks: Counter = Counter()
    for row in sorted(rows, key=_source_order):
        events, strays = _events_for_row(row)
        if events is None:
            skipped_kinds[_text(row.get("kind")) or "<空>"] += 1
            continue
        stray_blocks.update(strays)
        session_id = _text(row.get("session_id"))
        for index, event in enumerate(events):
            seq_in_session[session_id] = seq_in_session.get(session_id, 0) + 1
            records.append(_build_record(row, event, session_id=session_id,
                                         seq=seq_in_session[session_id],
                                         event_index=index, event_count=len(events)))
    return records, skipped_kinds, stray_blocks


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


def _expand_turn(row: Dict[str, Any], blocks: List[Any]) -> Tuple[List[_Event], Counter]:
    """model_turn 按块序展开：正文成段、每个调用独立成条，思考并入其后第一条。"""
    strays = _stray_blocks(blocks, frozenset({"text", "tool_call", "thinking"}))
    interesting = [block for block in blocks if isinstance(block, dict)]
    if not any(block.get("type") in ("text", "tool_call") for block in interesting):
        # 旧式行（无 blocks）或只有思考的行：平列才是正文的唯一载体
        thinking = "".join(_text(block.get("thinking")) for block in interesting
                           if block.get("type") == "thinking")
        return _fallback_events(row, thinking), strays

    events: List[_Event] = []
    run: List[str] = []
    pending: List[str] = []
    for block in interesting:
        btype = block.get("type")
        if btype == "thinking":
            pending.append(_text(block.get("thinking")))
        elif btype == "text":
            run.append(str(block.get("text") or ""))
        elif btype == "tool_call":
            _flush_run(events, run, pending)
            events.append(_Event(kind="tool_call", tool_call_id=_text(block.get("id")),
                                 tool_name=_text(block.get("name")),
                                 tool_state=_text(block.get("state")),
                                 tool_input=str(block.get("input") or ""),
                                 reasoning=_drain(pending)))
    _flush_run(events, run, pending)
    if pending and events:
        events[-1] = _with_reasoning(events[-1], _drain(pending))
    flat_call = _text(row.get("tool_call_id"))
    if flat_call and flat_call not in {event.tool_call_id for event in events}:
        events.append(_flat_tool_event(row))
    return events, strays


def _fallback_events(row: Dict[str, Any], reasoning: str) -> List[_Event]:
    """blocks 为空的旧式行：退回平列表达（正文 + 至多一个调用）。"""
    events: List[_Event] = []
    if _text(row.get("content")) or reasoning:
        events.append(_Event(kind="assistant_message", text=_text(row.get("content")),
                             reasoning=reasoning))
    if _text(row.get("tool_call_id")) or _text(row.get("tool_input")):
        events.append(_flat_tool_event(row))
    return events


def _flat_event(row: Dict[str, Any], kind: str, blocks: List[Any]) -> _Event:
    thinking = "".join(_text(block.get("thinking")) for block in blocks
                       if isinstance(block, dict) and block.get("type") == "thinking")
    return _Event(kind=kind, text=_text(row.get("content")),
                  tool_call_id=_text(row.get("tool_call_id")),
                  tool_name=_text(row.get("name")), tool_state=_text(row.get("tool_state")),
                  reasoning=thinking)


def _flat_tool_event(row: Dict[str, Any]) -> _Event:
    return _Event(kind="tool_call", tool_call_id=_text(row.get("tool_call_id")),
                  tool_name=_text(row.get("name")), tool_state=_text(row.get("tool_state")),
                  tool_input=str(row.get("tool_input") or ""))


def _flush_run(events: List[_Event], run: List[str], pending: List[str]) -> None:
    text = "".join(run)
    del run[:]
    if text:
        events.append(_Event(kind="assistant_message", text=text, reasoning=_drain(pending)))


def _stray_blocks(blocks: List[Any], represented: frozenset) -> Counter:
    return Counter(str(block.get("type")) if isinstance(block, dict) else "<非对象>"
                   for block in blocks
                   if not isinstance(block, dict) or block.get("type") not in represented)


def _build_record(row: Dict[str, Any], event: _Event, *, session_id: str, seq: int,
                  event_index: int, event_count: int) -> TranscriptRecord:
    source_seq = _int(row.get("seq"))
    identity = f"{session_id}#{_text(row.get('dedup_key')) or source_seq}"
    extra: Dict[str, Any] = {"source_seq": source_seq, "agent_id": row.get("agent_id")}
    if event_index == 0 or event_count == 1:
        extra["headline"] = row.get("headline")
        extra["source_metadata"] = row.get("metadata")
    if event.kind == "tool_call":
        extra["tool_input"] = event.tool_input or None
    else:
        extra["actor_name"] = _text(row.get("name")) or None
    return TranscriptRecord(
        session_id=session_id,
        seq=seq,
        kind=event.kind,
        ts=_ts(row.get("created_at")),
        identity_key=identity if event_count == 1 else f"{identity}#{event_index}",
        role=_text(row.get("role")),
        content_blocks=({"type": "text", "text": event.text},) if event.text else (),
        tool_call_id=event.tool_call_id,
        tool_name=event.tool_name if event.kind != "assistant_message" else "",
        tool_state=event.tool_state,
        reasoning_state="text" if event.reasoning else "absent",
        reasoning_text=event.reasoning,
        extra={key: value for key, value in extra.items() if value is not None},
    )


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


def _write_bundle(out_dir: Path, records: List[TranscriptRecord],
                  manifest: BundleManifest) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "transcripts.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
    (out_dir / "memories.jsonl").write_text("", encoding="utf-8")
    dump_manifest(manifest, out_dir / "manifest.json")


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


def _with_reasoning(event: _Event, extra: str) -> _Event:
    """轮尾的思考并入最后一条事件：思考没有后继可挂靠时不丢。"""
    return replace(event, reasoning=event.reasoning + extra)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _ts(value: Any) -> str:
    return _text(value) or datetime.now(timezone.utc).isoformat()
