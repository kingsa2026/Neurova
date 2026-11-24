# -*- coding: utf-8 -*-
"""D5-R6：存量记忆温度全量初始化 60° 的离线脚本判据。

脚本在後端停止后执行（同 v3 切换纪律）；只动 temperature 一列，
updated_at/last_accessed_at/access_count 不得被触碰；--dry-run 零改动。
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest


def _load_script():
    path = Path(__file__).resolve().parents[3] / "scripts" / "reset_memory_temperature_60.py"
    spec = importlib.util.spec_from_file_location("reset_memory_temperature_60", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_db(path: Path, rows: int = 3, temperature: float = 100.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memories ("
        " id TEXT PRIMARY KEY, content TEXT, temperature REAL NOT NULL,"
        " access_count INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,"
        " last_accessed_at TEXT)"
    )
    for i in range(rows):
        conn.execute(
            "INSERT INTO memories (id, content, temperature, access_count,"
            " updated_at, last_accessed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (f"{path.parent.parent.name}-{i}", "c", temperature, i, "2026-11-24", None),
        )
    conn.commit()
    conn.close()


@pytest.fixture()
def fake_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    # v3 布局两个 agent + v2 平铺一个 agent
    _make_db(root / "agent" / "1" / "kai" / "memory" / "neurova_memories_persist.db", 4)
    _make_db(root / "agent" / "share" / "default" / "memory" / "neurova_memories_persist.db", 2)
    _make_db(root / "scr_x" / "memory" / "neurova_memories_persist.db", 1)
    return root


def test_reset_all_agents_to_60(fake_root: Path):
    mod = _load_script()
    dbs = sorted(fake_root.rglob("neurova_memories_persist.db"))
    before = {}
    for db in dbs:
        conn = sqlite3.connect(str(db))
        before[str(db)] = conn.execute(
            "SELECT id, access_count, updated_at, last_accessed_at FROM memories"
        ).fetchall()
        conn.close()
    assert mod.main(["--data-root", str(fake_root)]) == 0
    for db in dbs:
        conn = sqlite3.connect(str(db))
        temps = [r[0] for r in conn.execute("SELECT temperature FROM memories")]
        after = conn.execute(
            "SELECT id, access_count, updated_at, last_accessed_at FROM memories"
        ).fetchall()
        conn.close()
        assert temps and all(t == 60.0 for t in temps), f"{db} 未全部重置为 60"
        assert after == before[str(db)], f"{db} 的其他列被误改"


def test_dry_run_makes_no_change(fake_root: Path):
    mod = _load_script()
    assert mod.main(["--data-root", str(fake_root), "--dry-run"]) == 0
    for db in fake_root.rglob("neurova_memories_persist.db"):
        conn = sqlite3.connect(str(db))
        temps = [r[0] for r in conn.execute("SELECT temperature FROM memories")]
        conn.close()
        assert all(t == 100.0 for t in temps), "dry-run 不得改数据"
