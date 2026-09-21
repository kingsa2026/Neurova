# -*- coding: utf-8 -*-
"""Codex rollout 族（rollout-<ts>-<id>.jsonl）→ Ingest Bundle：只读源、只产包。

格式取证自本机的该平台上游源码（写入侧就是这个枚举，不是靠样例猜）：
``RolloutItem`` 的落盘线形是 ``{\"type\": <变体>, \"payload\": {...}}``
（history/src/rollout_payload.rs，tag=\"type\" + snake_case），会话正文在
``response_item`` 里（protocol/src/models.rs）：

- ``message``：role + content[]（input_text / output_text / input_image / input_audio）；
- ``reasoning``：summary[] 是明文要点，``encrypted_content`` 是密文——包内用
  ``reasoning_state=opaque`` 明说"有推理但读不出正文"，不用空串冒充没有；
- ``function_call`` / ``function_call_output``：调用与结果**本来就是两条线**，靠
  ``call_id`` 关联，参数是"装 JSON 的字符串"（源注释明写），原样带走不猜解析。

其余线型（turn_context / token_usage_record / world_state / realtime_item /
retained_context / security_risk_score 等）是运行时上下文与记账，event_msg 是同源的展示
事件流——都不进包，但按类型申报条数，绝不说成"没东西"。没有 per-line 时间戳时用
session_meta 的时间戳，顺序按文件追加序（这族没有版本号字段，位置就是唯一可靠序）。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.memory_ingest import probe
from neurova.memory_ingest.bundle.manifest import BundleError, BundleManifest
from neurova.memory_ingest.bundle.media import MediaSink
from neurova.memory_ingest.bundle.writer import SourceEvent, ensure_offset, materialize, write_bundle
from neurova.memory_ingest.probe import Handprint, register_handprint

CONVERTER_NAME = "codex_rollout"
CONVERTER_VERSION = "1"

ROLE_KINDS = {"user": "user_message", "assistant": "assistant_message",
              "developer": "system", "system": "system"}
BOOKKEEPING_TYPES = ("turn_context", "token_usage_record", "world_state", "realtime_item",
                     "retained_context", "security_risk_score",
                     "inter_agent_communication_metadata")

REASONS: Dict[str, str] = {
    "payload": "该记录类型在包内契约无落点，未携带",
    "event_msg": "同一内容已由 response_item 表达，这条是同源的展示事件流，不重复入包",
    "media": "源里的媒体载体取不到字节（url 不是 data:/file: 也不是源树内可读路径）",
    "role": "该角色在包内无对应 kind，不猜映射",
    "空正文": "该记录没有可携带正文，未入包",
    "坏行": "该行不是合法 JSON，无法解析",
    "timestamp": "该行与 session_meta 都没给出可定标的时间，整行未入包（不猜时刻）",
}
for _t in BOOKKEEPING_TYPES:
    REASONS[f"payload:{_t}"] = "运行时上下文与计量记账，包内不表达（会话事实以 response_item 为准）"


def convert(store: Path, out_dir: Path, *, agent_name: str) -> BundleManifest:
    """一支 rollout 文件（= 一场会话）→ Ingest Bundle。"""
    store, out_dir = Path(store), Path(out_dir)
    if not probe.matches_handprint(CONVERTER_NAME, store):
        raise BundleError(f"源不符合 {CONVERTER_NAME} 指纹，拒绝按这支转换器硬转：{store}")

    sink = MediaSink(out_dir, store=store)
    declared: Counter = Counter()
    lines = _read_lines(store)
    meta = next((row["payload"] for row in lines if row["type"] == "session_meta"), {})
    session_id = str(_first(meta, "id", "session_id", "thread_id") or store.stem)
    # 会话头的时间只是该行自己的时间的兜底：定不出来就留空，由 _row_events 申报并跳过
    fallback_ts = str(_first(meta, "timestamp", "time", "created_at") or "")

    rows: List[Tuple[str, List[SourceEvent]]] = []
    for number, row in enumerate(lines, start=1):
        events = _row_events(row, session_id, number, fallback_ts, sink, declared)
        if not events:
            continue
        if rows or True:
            events = _attach_meta(events, meta, carried=bool(rows))
        rows.append((f"{session_id}#L{number}", events))
    records = materialize([(session_id, rows)])
    return write_bundle(
        out_dir, records, agent_name=agent_name,
        source={"converter": CONVERTER_NAME, "version": CONVERTER_VERSION,
                "verified_against": "upstream writer schema"},
        dropped=_dropped_entries(declared),
        stores=[{"path": str(store), "handprint": CONVERTER_NAME, "session_id": session_id,
                 "source_rows": len(lines)}],
    )


def matches_store(path: Path) -> bool:
    """认 session_meta 头：这族没有版本字段，记录类型头就是它能拿出的最硬证据。"""
    def _is_rollout(row: Dict[str, Any]) -> bool:
        return row.get("type") == "session_meta" and isinstance(row.get("payload"), dict)
    return probe.jsonl_head_has_row(_is_rollout)(path)


def _read_lines(store: Path) -> List[Dict[str, Any]]:
    out = []
    for raw in store.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        out.append(parsed if isinstance(parsed, dict) else {"type": "<坏行>", "payload": {}})
    return out


def _attach_meta(events: List[SourceEvent], meta: Dict[str, Any], *,
                 carried: bool) -> List[SourceEvent]:
    """会话头只跟首条事件：它是整场会话的出处，不该在每条上重复 60 次。"""
    if carried or not meta:
        return events
    first = events[0]
    return [SourceEvent(**{**first.__dict__,
                           "extra": {"session_meta": meta, **first.extra}}), *events[1:]]


def _row_events(row: Dict[str, Any], session_id: str, number: int, fallback_ts: str,
                sink: MediaSink, declared: Counter) -> List[SourceEvent]:
    rtype = str(row.get("type") or "<无类型>")
    if rtype == "<坏行>":
        declared["坏行"] += 1
        return []
    if rtype == "session_meta":
        return []                              # 出处信息经 _attach_meta 挂在首条事件上
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    ts = ensure_offset(str(_first(payload, "timestamp", "ts", "time") or fallback_ts))
    if not ts:
        declared["timestamp"] += 1
        return []
    if rtype == "response_item":
        return _response_items(payload, ts, sink, declared)
    if rtype == "compacted":
        return [SourceEvent(kind="compact_summary", ts=ts, role="assistant",
                            extra={"source_line": number, **{k: v for k, v in payload.items()
                                                             if k in ("replacement_history",
                                                                      "message")}})]
    if rtype == "inter_agent_communication":
        return _agent_message(payload, ts, declared)
    if rtype == "event_msg":
        declared["event_msg"] += 1
        return []
    declared[f"payload:{rtype}"] += 1
    return []


def _response_items(payload: Dict[str, Any], ts: str, sink: MediaSink,
                    declared: Counter) -> List[SourceEvent]:
    ptype = str(payload.get("type") or "<无类型>")
    if ptype == "message":
        return _message(payload, ts, sink, declared)
    if ptype == "reasoning":
        return _reasoning(payload, ts)
    if ptype == "function_call":
        return [SourceEvent(kind="tool_call", ts=ts, role="assistant",
                            tool_call_id=str(payload.get("call_id") or ""),
                            tool_name=str(payload.get("name") or ""),
                            extra={"tool_input": str(payload.get("arguments") or "")})]
    if ptype == "function_call_output":
        return [SourceEvent(kind="tool_result", ts=ts, role="tool",
                            tool_call_id=str(payload.get("call_id") or ""),
                            text=_flatten_output(payload.get("output")))]
    if ptype == "local_shell_call":
        return [SourceEvent(kind="tool_call", ts=ts, role="assistant",
                            tool_call_id=str(payload.get("call_id") or ""),
                            tool_name="local_shell",
                            extra={"tool_input": json.dumps(payload.get("action"),
                                                            ensure_ascii=False)})]
    declared[f"payload:{ptype}"] += 1
    return []


def _message(payload: Dict[str, Any], ts: str, sink: MediaSink,
             declared: Counter) -> List[SourceEvent]:
    role = str(payload.get("role") or "")
    kind = ROLE_KINDS.get(role)
    if kind is None:
        declared[f"role:{role or '<空>'}"] += 1
        return []
    texts: List[str] = []
    blocks: List[Dict[str, Any]] = []
    for item in payload.get("content") or []:
        if not isinstance(item, dict):
            declared["payload:<非对象内容项>"] += 1
            continue
        itype = str(item.get("type") or "")
        if itype in ("input_text", "output_text", "text"):
            texts.append(str(item.get("text") or ""))
        elif itype in ("input_image", "input_audio", "input_file"):
            ref = sink.resolve({"type": "image" if itype == "input_image" else "file",
                                "name": item.get("filename") or itype,
                                "source": item.get("image_url") or item.get("audio_url")
                                or item.get("file_url") or item.get("filename")})
            if ref is None:
                declared["media:不可达"] += 1
            else:
                blocks.append(dict(ref, type="image" if itype == "input_image" else "file"))
        else:
            declared[f"payload:{itype or '<无类型>'}"] += 1
    text = "\n".join(part for part in texts if part)
    if not text and not blocks:
        declared["空正文"] += 1
        return []
    return [SourceEvent(kind=kind, ts=ts, role=role, text=text, blocks=tuple(blocks),
                        extra={"phase": payload.get("phase")} if payload.get("phase") else {})]


def _reasoning(payload: Dict[str, Any], ts: str) -> List[SourceEvent]:
    """推理只有密文时标 opaque：有推理这件事不能说成没有。"""
    summary = payload.get("summary") or []
    text = "".join(str(item.get("text") or "") for item in summary if isinstance(item, dict))
    body = payload.get("content") or []
    text += "".join(str(item.get("text") or "") for item in body if isinstance(item, dict))
    opaque = bool(payload.get("encrypted_content")) and not text
    if not text and not opaque:
        return []
    return [SourceEvent(kind="assistant_message", ts=ts, role="assistant", reasoning=text,
                        reasoning_state="opaque" if opaque and not text else "")]


def _agent_message(payload: Dict[str, Any], ts: str,
                   declared: Counter) -> List[SourceEvent]:
    parts = [str(item.get("text") or "") for item in (payload.get("content") or [])
             if isinstance(item, dict) and item.get("type") == "InputText"]
    text = "\n".join(part for part in parts if part)
    if not text:
        declared["空正文"] += 1
        return []
    return [SourceEvent(kind="assistant_message", ts=ts, role="assistant", text=text,
                        extra={"author": payload.get("author"),
                               "recipient": payload.get("recipient")})]


def _flatten_output(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "".join(str(item.get("text") or "") for item in output if isinstance(item, dict))
    return "" if output is None else json.dumps(output, ensure_ascii=False)


def _first(mapping: Dict[str, Any], *keys: str) -> Optional[Any]:
    for key in keys:
        if mapping.get(key) not in (None, ""):
            return mapping[key]
    return None


def _dropped_entries(declared: Counter) -> List[Dict[str, Any]]:
    entries = []
    for field, count in sorted(declared.items()):
        if count <= 0:
            continue
        prefix = field.split(":")[0]
        entries.append({"field": field, "count": count,
                        "reason": REASONS.get(field) or REASONS.get(prefix) or REASONS["payload"]})
    return entries


register_handprint(Handprint(CONVERTER_NAME, "jsonl", matches_store))
