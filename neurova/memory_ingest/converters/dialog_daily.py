# -*- coding: utf-8 -*-
"""每日对话 JSONL（一文件一天）→ Ingest Bundle：只读源、只产包。

源里的时间戳是本地裸时间（无偏移），按源所在时区 +08:00 定标——只补时区语义，不改时刻；
会话号取文件名（日期），与运行期自生成的会话号同形可寻址。
"""
from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from neurova.memory_ingest import probe
from neurova.memory_ingest.bundle.manifest import BundleManifest
from neurova.memory_ingest.converters.chat_jsonl import JsonlChatFamily, convert_store
from neurova.memory_ingest.probe import Handprint, register_handprint

CONVERTER_NAME = "dialog_daily"
CONVERTER_VERSION = "1"
_SOURCE_ZONE = timezone(timedelta(hours=8))
ROLE_KINDS = {"user": "user_message", "assistant": "assistant_message",
              "system": "system"}
COVERED_KEYS = ("role", "name", "content", "timestamp", "id", "metadata")

def _envelope(parsed: Dict[str, Any], lineno: int) -> Tuple[Optional[Dict[str, Any]],
                                                            Optional[str]]:
    role = str(parsed.get("role") or "")
    if role not in ROLE_KINDS:
        return None, f"role:{role or '<空>'}"
    return {"role": role, "content": parsed.get("content"), "ts_raw": parsed.get("timestamp"),
            "name": parsed.get("name"), "id": parsed.get("id"),
            "metadata": parsed.get("metadata")}, None


def _row_key(parsed: Dict[str, Any], lineno: int) -> str:
    """幂等键按行号：实测同一场对话里多条行共用一个 id（调用行与它的 system 结果行同 id），
    用源 id 当键会整包撞重被拒；源 id 仍在 extra.source_id 里可回查。"""
    return f"L{lineno}"


FAMILY = JsonlChatFamily(
    name=CONVERTER_NAME, version=CONVERTER_VERSION,
    required_keys=("role", "content", "timestamp"),
    session_id=lambda path: f"dialog-{path.stem}",
    naive_zone=_SOURCE_ZONE,
    envelope=_envelope,
    row_key=_row_key,
    covered_keys=COVERED_KEYS,
    role_kinds=ROLE_KINDS,
)


def convert(store: Path, out_dir: Path, *, agent_name: str) -> BundleManifest:
    return convert_store(FAMILY, store, out_dir, agent_name=agent_name)


register_handprint(Handprint(CONVERTER_NAME, "jsonl",
                             probe.jsonl_has_keys(FAMILY.required_keys)))
