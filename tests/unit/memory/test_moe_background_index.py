# -*- coding: utf-8 -*-
"""MoE 后台渐进索引行为锁定（v4 对比文档曾误判"未实现"，实测已实现）。

实现位于 neurova/mem_core.py:285 _background_index_memories（daemon 线程
moe-semantic-indexer，init_moe_router 内启动）：按温度降序 OFFSET 分页、
预算 vector_search.moe_index_limit、游标无进展守卫、完成状态落盘
moe_index_state_{md5(agent_id:persist_db_path)}.json。

状态目录由 NEUROVA_MOE_INDEX_STATE_DIR 注入；未设置时回落仓库 data/。
本测试锁定这些既有行为 + 注入点防回归。
"""
from pathlib import Path

from neurova.mem_core import (
    _background_index_memories,
    _moe_index_completed,
    _moe_index_state_path,
    _save_moe_index_state,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPO_DATA_DIR = PROJECT_ROOT / "data"


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


def _rows_page(n):
    return [_row(i) for i in range(n)]


def test_background_index_respects_budget():
    store = _FakeStore()
    rows = _rows_page(100)

    def fetch_page(offset, size):
        return rows[offset : offset + size]

    added, exhausted = _background_index_memories(
        store, fetch_page, index_limit=30, batch_size=20, batch_delay=0
    )
    assert added == 30
    assert len(store.memory_ids) == 30
    assert exhausted is False  # 撞预算截断，源没扫尽


def test_background_index_reports_exhausted_on_drained_source():
    store = _FakeStore()
    rows = _rows_page(40)

    def fetch_page(offset, size):
        return rows[offset : offset + size]

    added, exhausted = _background_index_memories(
        store, fetch_page, index_limit=500, batch_size=20, batch_delay=0
    )
    assert (added, exhausted) == (40, True)


def test_background_index_stops_on_stale_cursor():
    store = _FakeStore()

    def fetch_page(offset, size):  # 恒返回同一批 → 游标无进展
        return [{"id": "same", "content": "c", "category": "g", "lifecycle_stage": "a"}]

    added, exhausted = _background_index_memories(
        store, fetch_page, index_limit=100, batch_delay=0
    )
    assert added == 1  # 游标守卫提前终止，不死循环
    assert exhausted is False


def test_state_dir_honors_injected_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEUROVA_MOE_INDEX_STATE_DIR", str(tmp_path / "moeIndexState"))
    path = _moe_index_state_path("yi_ling:E:/w/memory/neurova_memories_persist.db")
    assert path.parent == tmp_path / "moeIndexState"
    assert path.name.startswith("moe_index_state_")


def test_state_dir_defaults_to_repo_data_when_env_unset(monkeypatch):
    monkeypatch.delenv("NEUROVA_MOE_INDEX_STATE_DIR", raising=False)
    assert _moe_index_state_path("scope").parent == REPO_DATA_DIR


def test_state_dir_pinned_out_of_repo_data_during_tests(tmp_path: Path):
    """防再泄漏：autouse 隔离失效时，测试会把一次性状态文件写进仓库 data/。

    实测（2026-09-19）单跑 tests/unit/agent/test_agent.py 即新增 6 个
    moe_index_state_*.json，全仓累积 6773 个。
    """
    parent = _moe_index_state_path("probe").parent
    assert REPO_DATA_DIR not in parent.parents
    assert tmp_path in parent.parents


def test_state_dir_survives_monkeypatch_undo(moe_state_session_dir, monkeypatch):
    """daemon 线程可能在 monkeypatch 撤销之后才落盘——兜底必须仍在临时目录。

    撤销后 env 回到未设置（摘掉会话层本测试即红，已验证），此时迟到的索引
    线程会退回生产默认目录写盘；实测全量 tests/unit 期间 4 个真实 workspace
    键（default/kai/descagent/216fb777）就以新格式落进了仓库 data/。
    """
    import os

    monkeypatch.undo()
    assert os.environ.get("NEUROVA_MOE_INDEX_STATE_DIR") == str(moe_state_session_dir)
    parent = _moe_index_state_path("probe").parent
    assert parent == moe_state_session_dir
    assert REPO_DATA_DIR not in parent.parents


def test_state_skip_when_source_unchanged_and_exhausted(tmp_path: Path, monkeypatch):
    """小库扫尽即完成：源行数未变则跳过重扫（此前只有撞上限才算完成）。"""
    monkeypatch.setenv("NEUROVA_MOE_INDEX_STATE_DIR", str(tmp_path))
    store = _FakeStore()
    store.memory_ids = ["m1", "m2", "m3"]
    _save_moe_index_state(500, store, "scope", source_rows=3, scan_exhausted=True)

    assert _moe_index_completed(500, "scope", 3) is True
    assert _moe_index_completed(500, "scope", 4) is False  # 库长大了必须重扫
    assert _moe_index_completed(500, "scope", -1) is False  # 行数未知不跳过


def test_state_no_skip_on_partial_scan(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEUROVA_MOE_INDEX_STATE_DIR", str(tmp_path))
    store = _FakeStore()
    store.memory_ids = ["m1", "m2"]
    _save_moe_index_state(500, store, "scope", source_rows=10, scan_exhausted=False)

    assert _moe_index_completed(500, "scope", 10) is False


def test_state_skip_preserved_when_saturated(tmp_path: Path, monkeypatch):
    """饱和判据（indexed_count 达上限）不受行数指纹影响。"""
    monkeypatch.setenv("NEUROVA_MOE_INDEX_STATE_DIR", str(tmp_path))
    store = _FakeStore()
    store.memory_ids = [f"x{i}" for i in range(500)]
    _save_moe_index_state(500, store, "scope", source_rows=9999, scan_exhausted=False)

    assert _moe_index_completed(500, "scope", 0) is True
    assert _moe_index_completed(1000, "scope", 0) is False  # limit 变更不跳过
