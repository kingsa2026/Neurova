# -*- coding: utf-8 -*-
"""1.x 工作区会话 JSONL（一文件一场会话）→ Ingest Bundle：只读源、只产包。

信封是 `{type: "message", message: {role, content}, timestamp}`，同文件还混着
model_change / custom 等非消息记录——那些不猜语义，整行不入包但按类型申报条数。
时间戳带 Z（UTC），换算到 +08:00 只挪时区不改时刻，与每日对话族同一天口径。
"""
from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from neurova.memory_ingest import probe
from neurova.memory_ingest.bundle.manifest import BundleManifest
from neurova.memory_ingest.converters.chat_jsonl import JsonlChatFamily, convert_store
from neurova.memory_ingest.probe import Handprint, register_handprint

CONVERTER_NAME = "legacy_session"
CONVERTER_VERSION = "1"
_SOURCE_ZONE = timezone(timedelta(hours=8))
ROLE_KINDS = {"user": "user_message", "assistant": "assistant_message",
              "toolResult": "tool_result"}


def _envelope(parsed: Dict[str, Any], lineno: int) -> Tuple[Optional[Dict[str, Any]],
                                                            Optional[str]]:
    if str(parsed.get("type") or "") != "message":
        return None, f"type:{parsed.get('type') or '<空>'}"
    inner = parsed.get("message") or {}
    role = str(inner.get("role") or "") if isinstance(inner, dict) else ""
    if role not in ROLE_KINDS:
        return None, f"role:{role or '<空>'}"
    return {"role": role, "content": inner.get("content"),
            "ts_raw": parsed.get("timestamp") or inner.get("timestamp"),
            "name": inner.get("name"), "id": parsed.get("id"),
            "metadata": inner.get("metadata"),
            "tool_call_id": inner.get("toolCallId"), "tool_name": inner.get("toolName")}, None


FAMILY = JsonlChatFamily(
    name=CONVERTER_NAME, version=CONVERTER_VERSION,
    required_keys=("type", "message", "timestamp"),
    session_id=lambda path: path.stem,
    naive_zone=_SOURCE_ZONE,
    envelope=_envelope,
    row_key=lambda parsed, lineno: str(parsed.get("id") or f"L{lineno}"),
    covered_keys=("type", "message", "timestamp", "id", "parentId"),
    role_kinds=ROLE_KINDS,
)


def convert(store: Path, out_dir: Path, *, agent_name: str) -> BundleManifest:
    return convert_store(FAMILY, store, out_dir, agent_name=agent_name)


register_handprint(Handprint(CONVERTER_NAME, "jsonl",
                             probe.jsonl_has_keys(FAMILY.required_keys)))
