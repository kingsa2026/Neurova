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


def read_only_connect(path: Path) -> sqlite3.Connection:
    """外部库一律只读打开：识别与转换阶段都不允许改动源。"""
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _sqlite_tables(path: Path) -> List[str]:
    conn = read_only_connect(path)
    try:
        return [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
    finally:
        conn.close()


def source_columns(path: Path, table: str) -> List[str]:
    """表的实际列清单：转换器据此发现源里多出的列，而不是按写死的列名猜。"""
    conn = read_only_connect(path)
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def jsonl_first_keys(path: Path) -> List[str]:
    """首行键集合（报告用：未识别时要打印可核实的结构事实）。"""
    for keys in jsonl_head_key_sets(path, limit=1):
        return keys
    return []


def jsonl_head_key_sets(path: Path, limit: int = 32) -> List[List[str]]:
    """前 limit 个非空行的键集合。

    实测真实日志可能以表头记录开头（一文件一场会话的那族，31/31 个文件首行是
    {cwd,id,timestamp,type,version}），只看首行的指纹会永远认不出它。
    """
    sets: List[List[str]] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                return sets
            if isinstance(parsed, dict):
                sets.append(sorted(parsed.keys()))
            if len(sets) >= limit:
                break
    return sets


def sqlite_has_columns(table: str, required: Tuple[str, ...]) -> Callable[[Path], bool]:
    def _matches(path: Path) -> bool:
        return table in _sqlite_tables(path) and set(required) <= set(source_columns(path, table))
    return _matches


def jsonl_has_keys(required: Tuple[str, ...]) -> Callable[[Path], bool]:
    """前若干行里任一行含齐必需键即命中（表头开头是这一类日志的正常形态）。"""
    def _matches(path: Path) -> bool:
        return any(set(required) <= set(keys) for keys in jsonl_head_key_sets(path))
    return _matches


# 只留"有指纹、暂无转换器"的一家；各家转换器的指纹由 converters/ 模块自己 register，
# 识别面与适配面同名同处，不会出现在 A 处认得出、B 处无路可走的两张皮。
_HANDPRINTS: List[Handprint] = [
    Handprint("dsh_session", "jsonl", jsonl_has_keys(("type", "version", "id", "createdAt"))),
]


def register_handprint(handprint: Handprint) -> None:
    """新家在此登记指纹（与转换器同名，避免两处各写一份）。"""
    _HANDPRINTS.append(handprint)


def matches_handprint(name: str, path: Path) -> bool:
    """转换器自证入口：只对已登记的具名指纹求值，列清单不在两处各写一份。"""
    handprint = next((h for h in _HANDPRINTS if h.name == name), None)
    if handprint is None:
        raise KeyError(f"指纹未登记，无从判定来源: {name!r}")
    return _safe_match(handprint, Path(path))


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
        return {"first_line_keys": jsonl_first_keys(path)}
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
