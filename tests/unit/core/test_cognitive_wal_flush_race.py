# -*- coding: utf-8 -*-
"""DATA-P1-3（审计 2026-09-11）回归：flush 后 WAL 不再无条件清空。

竞态场景：flush 快照 nodes → 并发 store() 追加节点 X（WAL + 缓冲）→
flush 提交 L1 → 截断 WAL。原实现把 X 的 WAL 记录一并抹掉——X 尚未写 L1，
崩溃即永久丢失。修复后 WAL 按已写入 L1 的 id 重写，X 的记录必须保留。
"""
from __future__ import annotations

import json
from pathlib import Path

from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
    CognitiveStorageEngine,
    UnifiedMemoryNode,
)


def _make_engine(tmp_path: Path) -> CognitiveStorageEngine:
    eng = CognitiveStorageEngine(agent_id="itest", data_dir=str(tmp_path / "data"))
    eng._auto_flush = False
    return eng


def _node(nid: str, content: str) -> UnifiedMemoryNode:
    return UnifiedMemoryNode(id=nid, content=content)


def test_flush_keeps_wal_entries_not_in_batch(tmp_path):
    eng = _make_engine(tmp_path)
    n1 = _node("id-1", "first")
    eng._wal_append(n1)
    eng._l0_buffer = [n1]

    # 竞态窗口模拟：store() 已把 X 追加进 WAL，但 flush 的缓冲快照
    # 未包含它（生产时序：wal_append 与 buffer append 之间被 flush 抢入）
    n2 = _node("id-2", "concurrent")
    eng._wal_append(n2)

    eng._flush_l0_to_l1()

    wal_ids = {
        json.loads(line)["id"]
        for line in eng._wal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert "id-1" not in wal_ids, "已写入 L1 的条目应从 WAL 收敛掉"
    assert "id-2" in wal_ids, "不在本批快照内的 WAL 条目必须保留（崩溃恢复依据）"
    assert all(n.id != "id-1" for n in eng._l0_buffer)


def test_flush_writes_batch_to_l1(tmp_path):
    eng = _make_engine(tmp_path)
    n1 = _node("id-a", "aaa")
    eng._wal_append(n1)
    eng._l0_buffer = [n1]
    eng._flush_l0_to_l1()
    row = eng._db.execute(
        "SELECT content FROM memories WHERE id = ?", ("id-a",)
    ).fetchone()
    assert row is not None and row[0] == "aaa"
