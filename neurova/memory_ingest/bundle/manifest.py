# -*- coding: utf-8 -*-
"""manifest.json：包版本与计数的唯一入口。

被调研的六族里只有两家带格式版本字段（Claude Code 官方还明写"内部格式跨版本会变"），
这正是它们互相导入时静默丢数据的根因之一——所以本包把版本与计数做成硬门槛。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

SUPPORTED_SCHEMA_VERSION = 1
_REQUIRED_FIELDS = ("generated_at", "agent_name", "source", "counts")


class BundleError(Exception):
    """包不合规：版本不符、缺文件、坏行、越界值。调用方必须整包拒绝。"""


@dataclass(frozen=True)
class BundleManifest:
    schema_version: int
    generated_at: str
    agent_name: str
    source: Dict[str, Any]
    counts: Dict[str, int]
    dropped: Tuple[Dict[str, Any], ...]
    stores: Tuple[Dict[str, Any], ...]


def load_manifest(path: Path) -> BundleManifest:
    path = Path(path)
    if not path.exists():
        raise BundleError(f"缺 manifest.json: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BundleError(f"manifest.json 不是合法 JSON: {exc}") from exc

    version = raw.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise BundleError(
            f"schema_version 不支持: {version!r}（本版本只认 {SUPPORTED_SCHEMA_VERSION}）")
    missing = [key for key in _REQUIRED_FIELDS if key not in raw]
    if missing:
        raise BundleError(f"manifest 缺字段 {missing}")
    return BundleManifest(
        schema_version=version,
        generated_at=str(raw["generated_at"]),
        agent_name=str(raw["agent_name"]),
        source=dict(raw["source"]),
        counts=dict(raw["counts"]),
        dropped=tuple(raw.get("dropped", ())),
        stores=tuple(raw.get("stores", ())),
    )
