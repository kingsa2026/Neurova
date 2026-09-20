# -*- coding: utf-8 -*-
"""来源识别：结构指纹，不是文件名猜测。

指纹只写"可核实的结构事实"（表名+必需列集合、JSONL 首行键集合），依据是设计 §2 的取证
矩阵：六族里只有两家带格式版本字段，靠文件名或猜测会在版本漂移处静默错导。
三态：唯一命中 / 多指纹冲突 / 未识别。后两态都不写库，未识别还要回结构摘要，
让"再加一家"变成填一条指纹而不是考古。

私有方言（qwenpaw_memory* 一族：_relations/_archive/humanthinking_* 等）在公开 QwenPaw
全仓与各 wheel 中零命中，属本机私有工程产物，有意不在指纹表内。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

_DB_SUFFIXES = (".db", ".sqlite", ".sqlite3")


@dataclass(frozen=True)
class Handprint:
    name: str
    applies_to: str            # "sqlite" | "jsonl"
    matches: Callable[[Path], bool]


@dataclass(frozen=True)
class StoreFinding:
    path: str
    kind: str                  # "sqlite" | "jsonl" | "unknown"
    hits: Tuple[str, ...]
    verdict: str               # unique | conflict | unknown
    structure: Dict[str, object] = field(default_factory=dict)


def _ro_connect(path: Path) -> sqlite3.Connection:
    """外部库一律只读打开：识别阶段不允许改动源。"""
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _sqlite_tables(path: Path) -> List[str]:
    conn = _ro_connect(path)
    try:
        return [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
    finally:
        conn.close()


def _columns(path: Path, table: str) -> List[str]:
    conn = _ro_connect(path)
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def _first_json_line_keys(path: Path) -> List[str]:
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.strip():
                try:
                    return sorted(json.loads(line).keys())
                except json.JSONDecodeError:
                    return []
    return []


def _sqlite_has_columns(table: str, required: Tuple[str, ...]) -> Callable[[Path], bool]:
    def _matches(path: Path) -> bool:
        return table in _sqlite_tables(path) and set(required) <= set(_columns(path, table))
    return _matches


_HANDPRINTS: List[Handprint] = [
    Handprint("qwenpaw_history", "sqlite", _sqlite_has_columns(
        "conversation_history",
        ("seq", "session_id", "kind", "role", "content", "tool_call_id",
         "created_at", "dedup_key"))),
    Handprint("dsh_session", "jsonl",
              lambda path: {"type", "version", "id", "createdAt"}
              <= set(_first_json_line_keys(path))),
]


def register_handprint(handprint: Handprint) -> None:
    """新家在此登记指纹（与转换器同名，避免两处各写一份）。"""
    _HANDPRINTS.append(handprint)


def _kind_of(path: Path) -> Optional[str]:
    if path.suffix.lower() in _DB_SUFFIXES:
        return "sqlite"
    if path.suffix.lower() == ".jsonl":
        return "jsonl"
    return None


def _structure(path: Path, kind: str) -> Dict[str, object]:
    if kind == "sqlite":
        try:
            return {"tables": _sqlite_tables(path)}
        except Exception as exc:                      # 打不开也要回话，不能空着
            return {"error": str(exc)}
    if kind == "jsonl":
        return {"first_line_keys": _first_json_line_keys(path)}
    return {}


def _probe_one(path: Path) -> StoreFinding:
    kind = _kind_of(path) or "unknown"
    hits = tuple(h.name for h in _HANDPRINTS
                 if h.applies_to == kind and _safe_match(h, path))
    verdict = "unique" if len(hits) == 1 else ("conflict" if hits else "unknown")
    return StoreFinding(str(path), kind, hits, verdict, _structure(path, kind))


def _safe_match(handprint: Handprint, path: Path) -> bool:
    """指纹求值异常（坏库/无权限）视为不命中，情况由 structure 说明。"""
    try:
        return bool(handprint.matches(path))
    except Exception:
        return False


def probe_store(path):
    """单个 store → StoreFinding；目录 → 逐 store 的列表（识别单位是 store 不是目录）。"""
    target = Path(path)
    if target.is_dir():
        return [_probe_one(child) for child in sorted(target.rglob("*"))
                if child.is_file() and _kind_of(child)]
    return _probe_one(target)
