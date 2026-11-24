# -*- coding: utf-8 -*-
"""批二：记忆温度分层装载（D5 后的启动规模化第二段）。

热层（高温 Top-N）构造期同步装载保证召回即就绪；冷层由后台线程补载，
启动关键路径不再随记忆总量线性变长。判据：
- HOT_LIMIT=N：同步装载后快照恰为温度 Top-N（平票按 last_accessed_at/
  access_count 决出）；
- 冷层补载完成后快照 = 全量（无静默失忆）；
- HOT_LIMIT=0 关闭分层（全量同步，行为同旧）；
- forgotten 不占热层名额，但冷层照常补入。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager


def _seed_rows(manager: MemoryManager, specs) -> None:
    """specs: [(id, temperature, lifecycle_stage, last_accessed_days_ago|None)]"""
    conn = sqlite3.connect(str(manager._persist_db_path))
    now = datetime.now(timezone.utc).isoformat()
    for memory_id, temp, stage, days in specs:
        la = (
            (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            if days is not None
            else None
        )
        conn.execute(
            "INSERT INTO memories (id, content, temperature, lifecycle_stage,"
            " agent_id, access_count, created_at, updated_at, last_accessed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (memory_id, f"内容{memory_id}", temp, stage, manager._agent_id, 0, now, now, la),
        )
    conn.commit()
    conn.close()


def _make_seeded_manager(tmp_path, name: str, specs) -> MemoryManager:
    """先建库播种，再走一遍分层装载（构造期空载 + 二次装载 = 真实分层路径）。"""
    manager = MemoryManager(db_path=str(tmp_path / name), agent_id="tier")
    _seed_rows(manager, specs)
    manager._load_from_db()
    return manager


def _snapshot_ids(manager: MemoryManager) -> set:
    return set(manager._memories.keys())


@pytest.fixture()
def clean_turn():
    from neurova.core.cancel_token import clearTurnCancelToken

    clearTurnCancelToken()
    yield
    clearTurnCancelToken()


class TestTieredLoading:
    def test_hot_tier_loads_only_top_n(self, tmp_path, monkeypatch, clean_turn):
        monkeypatch.setenv("NEUROVA_MEMORY_HOT_LIMIT", "50")
        specs = [(f"hot{i:03d}", 90.0 + i * 0.1, "active", 0) for i in range(50)]
        specs += [(f"cold{i:03d}", 30.0, "active", 30) for i in range(150)]
        manager = _make_seeded_manager(tmp_path, "hot.db", specs)
        # 同步装载的只有热层 Top-50
        assert len(_snapshot_ids(manager)) == 50
        assert all(i.startswith("hot") for i in _snapshot_ids(manager))

    def test_cold_tier_fills_in_background(self, tmp_path, monkeypatch, clean_turn):
        monkeypatch.setenv("NEUROVA_MEMORY_HOT_LIMIT", "50")
        specs = [(f"hot{i:03d}", 90.0, "active", 0) for i in range(50)]
        specs += [(f"cold{i:03d}", 30.0, "active", 30) for i in range(150)]
        manager = _make_seeded_manager(tmp_path, "cold.db", specs)
        assert manager._cold_load_done.wait(timeout=15), "冷层补载未在时限内完成"
        assert manager._cold_load_ok is True
        assert len(_snapshot_ids(manager)) == 200, "补载完成后快照必须等于全量"

    def test_hot_limit_zero_disables_tiering(self, tmp_path, monkeypatch, clean_turn):
        monkeypatch.setenv("NEUROVA_MEMORY_HOT_LIMIT", "0")
        specs = [(f"m{i:03d}", 60.0, "active", 5) for i in range(120)]
        manager = _make_seeded_manager(tmp_path, "off.db", specs)
        assert len(_snapshot_ids(manager)) == 120, "HOT_LIMIT=0 必须全量同步装载"
        assert manager._cold_load_done.is_set(), "关闭分层时无冷层待补"

    def test_forgotten_excluded_from_hot_but_filled_by_cold(
        self, tmp_path, monkeypatch, clean_turn
    ):
        monkeypatch.setenv("NEUROVA_MEMORY_HOT_LIMIT", "10")
        specs = [(f"act{i}", 90.0, "active", 0) for i in range(10)]
        specs += [(f"fg{i}", 99.0, "forgotten", 1) for i in range(5)]
        manager = _make_seeded_manager(tmp_path, "fg.db", specs)
        assert len(_snapshot_ids(manager)) == 10
        assert all(not i.startswith("fg") for i in _snapshot_ids(manager))
        assert manager._cold_load_done.wait(timeout=15)
        assert len(_snapshot_ids(manager)) == 15, "forgotten 由冷层补入，管理面最终一致"
