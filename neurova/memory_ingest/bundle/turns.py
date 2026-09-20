# -*- coding: utf-8 -*-
"""扁平事件流 → 轮形会话消息：让导入产物与运行期落盘同形。

运行期一条 assistant 轮写的是"一条消息 + metadata.tool_calls 列表"（正文块之间以换行拼接），
前端步骤卡按 tool_name/params/result 读。bundle 里一行一事件是传输形态，直接落盘就成了
运行期从不产出的形状，工具轨迹在 UI 上看不见——装配就在这一层收口。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from neurova.memory_ingest.bundle.records import VALID_ROLE_KINDS, TranscriptRecord

_TURN_KINDS = ("assistant_message", "tool_call", "tool_result")


def to_turn_messages(records: Sequence[TranscriptRecord]) -> List[Dict[str, Any]]:
    """按"用户/系统边界 + 会话边界"切轮；一轮合成一条 assistant 消息。"""
    messages: List[Dict[str, Any]] = []
    pending: Optional[Dict[str, Any]] = None
    for record in records:
        boundary = pending is not None and record.session_id != pending["first"].session_id
        if record.kind in _TURN_KINDS and not boundary:
            pending = pending or _open_turn(record)
            _extend_turn(pending, record)
            continue
        flushed = _finalize_turn(pending)
        if flushed:
            messages.append(flushed)
        pending = None
        if record.kind in _TURN_KINDS:
            pending = _open_turn(record)
            _extend_turn(pending, record)
        else:
            messages.append(_standalone_message(record))
    flushed = _finalize_turn(pending)
    if flushed:
        messages.append(flushed)
    return messages


def _open_turn(record: TranscriptRecord) -> Dict[str, Any]:
    return {"first": record, "last": record, "texts": [], "reasonings": [],
            "entries": [], "keys": [], "media": []}


def _extend_turn(turn: Dict[str, Any], record: TranscriptRecord) -> None:
    turn["last"] = record
    turn["keys"].append(record.identity_key)
    if record.kind == "assistant_message":
        if record.text():
            turn["texts"].append(record.text())
    else:
        turn["entries"].append(_tool_entry(record))
    if record.reasoning_text:
        turn["reasonings"].append(record.reasoning_text)
    turn["media"].extend(_media_of(record))


def _media_of(record: TranscriptRecord) -> List[Dict[str, Any]]:
    return [block for block in record.content_blocks
            if isinstance(block, dict) and block.get("media")]


def _finalize_turn(turn: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not turn or not (turn["texts"] or turn["entries"] or turn["reasonings"] or turn["media"]):
        return None
    first, last = turn["first"], turn["last"]
    metadata: Dict[str, Any] = {
        "ingest": {"identity_key": first.identity_key, "kind": "turn",
                   "seq_from": first.seq, "seq_to": last.seq,
                   "event_keys": list(turn["keys"])},
    }
    if turn["reasonings"]:
        metadata["reasoning_content"] = "\n".join(turn["reasonings"])
    if turn["entries"]:
        metadata["tool_calls"] = turn["entries"]
    if turn["media"]:
        metadata["media"] = list(turn["media"])
    return {"role": "assistant", "content": "\n".join(turn["texts"]),
            "timestamp": first.ts, "metadata": metadata}


def _standalone_message(record: TranscriptRecord) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "ingest": {"identity_key": record.identity_key, "kind": record.kind,
                   "seq": record.seq},
    }
    if record.reasoning_text:
        metadata["reasoning_content"] = record.reasoning_text
    media = _media_of(record)
    if media:
        metadata["media"] = media
    return {"role": record.role or VALID_ROLE_KINDS[record.kind],
            "content": record.text(), "timestamp": record.ts, "metadata": metadata}


def _tool_entry(record: TranscriptRecord) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"type": record.kind, "tool_name": record.tool_name,
                             "timestamp": record.ts}
    if record.tool_call_id:
        entry["tool_call_id"] = record.tool_call_id
    if record.kind == "tool_call":
        entry["params"] = _params(record.extra.get("tool_input"))
    else:
        entry["result"] = record.text()
    if record.tool_state:
        entry["state"] = record.tool_state      # 源词表原样带上，不猜成布尔
    return entry


def _params(raw: Any) -> Any:
    """参数解不开就原样带走：换成空字典等于把调用说成"什么都没传"。"""
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw or "")
    try:
        return json.loads(text) if text.strip() else {}
    except (TypeError, ValueError):
        return text
