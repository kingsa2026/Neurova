# -*- coding: utf-8 -*-
"""MoE 后台渐进索引行为锁定（v4 对比文档曾误判"未实现"，实测已实现）。

实现位于 neurova/mem_core.py:285 _background_index_memories（daemon 线程
moe-semantic-indexer，mem_core.py:760 启动）：按温度降序 OFFSET 分页、
预算 vector_search.moe_index_limit、游标无进展守卫、完成状态落盘
data/moe_index_state_{md5}.json。本测试锁定这些既有行为防回归。
"""
from pathlib import Path

from neurova.mem_core import (
    _background_index_memories,
    _moe_index_completed,
    _save_moe_index_state,
)


class _FakeStore:
    """模拟 UnifiedVectorStore 契约：memory_ids 属性 + index_memories 去重。"""

    def __init__(self):
        self.memory_ids: list = []

    def index_memories(self, items, incremental=False):
        before = len(self.memory_ids)
        for m in items:
            if m["id"] not in self.memory_ids:
                self.memory_ids.append(m["id"])
        return len(self.memory_ids) - before


def _row(i):
    return {"id": f"m{i}", "content": f"c{i}", "category": "general", "lifecycle_stage": "active"}


def test_background_index_respects_budget():
    store = _FakeStore()
    rows = [_row(i) for i in range(100)]

    def fetch_page(offset, size):
        return rows[offset : offset + size]

    added = _background_index_memories(
        store, fetch_page, index_limit=30, batch_size=20, batch_delay=0
    )
    assert added == 30
    assert len(store.memory_ids) == 30


def test_background_index_stops_on_stale_cursor():
    store = _FakeStore()

    def fetch_page(offset, size):  # 恒返回同一批 → 游标无进展
        return [{"id": "same", "content": "c", "category": "g", "lifecycle_stage": "a"}]

    added = _background_index_memories(store, fetch_page, index_limit=100, batch_delay=0)
    assert added == 1  # 游标守卫提前终止，不死循环


def test_state_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "neurova.mem_core._moe_index_state_path", lambda scope: tmp_path / "st.json"
    )
    store = _FakeStore()
    _save_moe_index_state(500, store, "scope")
    assert _moe_index_completed(500, "scope") is False  # 未达上限不跳过

    store.memory_ids = [f"x{i}" for i in range(500)]
    _save_moe_index_state(500, store, "scope")
    assert _moe_index_completed(500, "scope") is True
    assert _moe_index_completed(1000, "scope") is False  # limit 变更不跳过
