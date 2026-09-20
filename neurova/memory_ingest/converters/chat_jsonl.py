# -*- coding: utf-8 -*-
"""会话 JSONL 族的公共机制：一个文件就是一场会话。

与表族的区别：没有全局 seq，顺序只能靠源时间戳；一行一条消息，正文在 content 块里。
族差异（信封字段、会话号、裸时间按哪个时区定标）由 JsonlChatFamily 描述；解析、定序、
申报口径统一在这里，两族各写一份就会从第二家开始漂移。
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.memory_ingest import probe
from neurova.memory_ingest.bundle.manifest import BundleError, BundleManifest
from neurova.memory_ingest.bundle.writer import SourceEvent, materialize, write_bundle
from neurova.memory_ingest.bundle.media import MediaSink
from neurova.memory_ingest.converters.blocks import split_content

# 申报字段前缀 → 人读原因（报告要说清"少了什么、为什么少"）
REASONS: Dict[str, str] = {
    "坏行": "该行不是合法 JSON，无法解析",
    "空正文": "该行没有任何可携带内容，未入包",
    "timestamp": "时间戳解不开就无法定序（包内顺序靠 seq，不能猜位置）",
    "role": "该角色在本族无对应 kind，不猜映射",
    "type": "该记录类型不是消息行，本族不表达",
    "blocks": "该块型在包内契约无落点，未携带",
    "media": "源里的媒体载体取不到字节（路径不在源目录树的 media/ 下，或 base64 不可解）",
    "extra": "源字段在包内契约与 extra 都无落点，未携带",
}


@dataclass(frozen=True)
class JsonlChatFamily:
    """一支会话 JSONL 族的方言描述（信封、会话号、时区口径、幂等前缀）。"""
    name: str
    version: str
    required_keys: Tuple[str, ...]
    session_id: Callable[[Path], str]
    naive_zone: tzinfo
    envelope: Callable[[Dict[str, Any], int], Tuple[Optional[Dict[str, Any]], Optional[str]]]
    row_key: Callable[[Dict[str, Any], int], str]
    covered_keys: Tuple[str, ...]
    role_kinds: Dict[str, str] = None        # type: ignore[assignment]


def convert_store(family: JsonlChatFamily, store: Path, out_dir: Path, *,
                  agent_name: str) -> BundleManifest:
    """一支 JSONL 会话文件 → Ingest Bundle（只读源、只产包）。"""
    store, out_dir = Path(store), Path(out_dir)
    if not probe.matches_handprint(family.name, store):
        raise BundleError(f"源不符合 {family.name} 指纹，拒绝按这支转换器硬转：{store}")

    session_id = family.session_id(store)
    sink = MediaSink(out_dir, store=store)
    declared: Counter = Counter()
    rows: List[Tuple[datetime, str, List[SourceEvent]]] = []
    for lineno, raw in enumerate(_lines(store), start=1):
        if not raw.strip():
            continue
        parsed = _parse_line(raw)
        if parsed is None:
            declared["坏行"] += 1
            continue
        moment, events = _row_events(family, parsed, lineno, declared, sink)
        if moment is None or not events:
            continue
        rows.append((moment, f"{session_id}#{family.row_key(parsed, lineno)}", events))

    # 单个日志文件本身就是追加序（源自己的 seq），按读入顺序落包，不按时间重排
    records = materialize([(session_id, [(identity, events) for _, identity, events in rows])])
    return write_bundle(
        out_dir, records, agent_name=agent_name,
        source={"converter": family.name, "version": family.version},
        dropped=_dropped_entries(declared),
        stores=[{"path": str(store), "handprint": family.name, "session_id": session_id,
                 "source_rows": len(rows)}],
    )


def _row_events(family: JsonlChatFamily, parsed: Dict[str, Any], lineno: int,
                declared: Counter, sink: MediaSink) -> Tuple[Optional[datetime], List[SourceEvent]]:
    message, skip_field = family.envelope(parsed, lineno)
    if message is None:
        declared[skip_field or "type:<未知>"] += 1
        return None, []
    moment = _moment(message["ts_raw"], family.naive_zone)
    if moment is None:
        declared["timestamp"] += 1
        return None, []
    declared.update(f"extra:{key}" for key in _uncovered_keys(parsed, family))
    events, strays = split_content(message["content"], sink=sink)
    declared.update(strays)
    built = _build(events, message, moment, family)
    if not built:
        declared["空正文"] += 1
    return moment, built


def _build(events, message: Dict[str, Any], moment: datetime,
           family: JsonlChatFamily) -> List[SourceEvent]:
    """块事件 → 包内事件：正文按行的角色定 kind，工具事件保留自己的 kind。

    实测两族都把工具结果寄在别的角色行里（每日对话用 system 行的 tool_result 块，
    1.x 用 role=toolResult 的独立行），所以工具的归属只能按事件本身判。
    """
    role = str(message["role"])
    if role not in family.role_kinds:
        return []
    ts = moment.isoformat()
    extra = {"actor_name": message.get("name") or None, "source_id": message.get("id") or None,
             "source_metadata": message.get("metadata")}
    built = []
    for event in events:
        kind = event.kind if event.kind.startswith("tool_") else family.role_kinds[role]
        built.append(SourceEvent(
            kind=kind, ts=ts, role=role, text=event.text,
            tool_call_id=event.tool_call_id or str(message.get("tool_call_id") or ""),
            tool_name=event.tool_name or str(message.get("tool_name") or ""),
            blocks=event.blocks,
            reasoning=event.reasoning if kind == "assistant_message" else "",
            extra={**extra, "tool_input": event.tool_input or None}))
    return built


def _uncovered_keys(parsed: Dict[str, Any], family: JsonlChatFamily) -> List[str]:
    return [key for key, value in parsed.items()
            if key not in family.covered_keys and value not in (None, "", [], {})]


def _lines(store: Path) -> List[str]:
    return store.read_text(encoding="utf-8", errors="replace").splitlines()


def _parse_line(raw: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _moment(raw: Any, zone: tzinfo) -> Optional[datetime]:
    text = str(raw or "").strip().replace(" ", "T")
    if not text:
        return None
    try:
        parsed = (datetime.fromisoformat(text[:-1]).replace(tzinfo=timezone.utc)
                  if text.endswith("Z") else datetime.fromisoformat(text))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def _dropped_entries(declared: Counter) -> List[Dict[str, Any]]:
    entries = []
    for field, count in sorted(declared.items()):
        if count <= 0:
            continue
        prefix = field.split(":")[0]
        entries.append({"field": field, "count": count,
                        "reason": REASONS.get(prefix, REASONS["type"])})
    return entries
