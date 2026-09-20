# -*- coding: utf-8 -*-
"""整包校验：字段齐备、seq 连续、identity_key 唯一、origin 在闭集内、计数相符。

任一条不合即返回错误列表，由调用方（intake）拒绝整支 store——半导出的数据既难察觉
又难撤销，比不导更糟。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from neurova.memory_ingest.bundle.manifest import SUPPORTED_SCHEMA_VERSION
from neurova.memory_ingest.models import VALID_ORIGINS

_REQUIRED = {
    "transcripts.jsonl": ("session_id", "seq", "kind", "ts", "identity_key"),
    "memories.jsonl": ("identity_key", "content", "memory_type", "category",
                       "origin", "importance", "ts"),
}


def validate_bundle(root: Path) -> List[str]:
    """返回错误列表；空列表即通过。不抛异常，便于 CLI 逐条打印。"""
    root = Path(root)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return [f"缺 manifest.json: {manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"manifest.json 不是合法 JSON: {exc}"]
    if manifest.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        return [f"schema_version 不支持: {manifest.get('schema_version')!r}"]

    counts = manifest.get("counts", {})
    errors: List[str] = []
    for name, required in _REQUIRED.items():
        path = root / name
        claimed = int(counts.get(name.split(".")[0], 0))
        if not path.exists():
            if claimed:
                errors.append(f"{name} 缺失但 counts 声称有 {claimed} 条")
            continue
        try:
            rows = _read_jsonl(path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        errors += _missing_field_errors(name, rows, required)
        errors += _duplicate_identity_errors(name, rows)
        errors += _count_errors(name, rows, claimed)
        if name == "transcripts.jsonl":
            errors += _seq_errors(rows)
        else:
            errors += _origin_errors(rows)
    return errors


def _read_jsonl(path: Path) -> List[dict]:
    rows: List[dict] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{lineno} 不是合法 JSON: {exc}") from exc
    return rows


def _missing_field_errors(name: str, rows: List[dict], required) -> List[str]:
    errors = []
    for row in rows:
        missing = [key for key in required if row.get(key) in (None, "")]
        if missing:
            errors.append(f"{name} 缺字段 {missing}（identity_key={row.get('identity_key')!r}）")
    return errors


def _duplicate_identity_errors(name: str, rows: List[dict]) -> List[str]:
    seen, errors = set(), []
    for row in rows:
        key = row.get("identity_key")
        if key in seen:
            errors.append(f"{name} identity_key 重复: {key!r}")
        seen.add(key)
    return errors


def _count_errors(name: str, rows: List[dict], claimed: int) -> List[str]:
    if claimed != len(rows):
        return [f"{name} 计数不符: manifest={claimed} 实际={len(rows)}"]
    return []


def _seq_errors(rows: List[dict]) -> List[str]:
    """会话内 seq 必须从 1 起连续：各家都靠它排序（时钟会倒退，不能信 ts）。"""
    by_session: Dict[str, List[int]] = {}
    for row in rows:
        seq = row.get("seq")
        if isinstance(seq, int):
            by_session.setdefault(str(row.get("session_id")), []).append(seq)
    errors = []
    for session_id, seqs in by_session.items():
        ordered = sorted(seqs)
        if ordered != list(range(1, len(ordered) + 1)):
            errors.append(f"会话 {session_id} 的 seq 必须从 1 起连续，实际 {ordered}")
    return errors


def _origin_errors(rows: List[dict]) -> List[str]:
    return [f"memories.jsonl origin 越界: {row.get('origin')!r}"
            for row in rows if row.get("origin") not in VALID_ORIGINS]
