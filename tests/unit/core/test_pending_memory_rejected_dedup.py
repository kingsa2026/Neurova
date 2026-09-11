# -*- coding: utf-8 -*-
"""P2-5（审计 2026-09-11）回归：存量库 rejected 同分区重复不阻断建库。

唯一索引谓词含 rejected；旧版 _LEGACY_CLEANUP 只去重 pending——
存量同 (fingerprint, proposed_by) 多条 rejected 会让 CREATE UNIQUE INDEX
抛错 → PendingMemoryStore 建库失败且每次启动复现。
"""
from __future__ import annotations

import sqlite3

from neurova.memory.pending_memory import PendingMemoryStore


def test_legacy_duplicate_rejected_rows_are_converged(tmp_path):
    db = str(tmp_path / "pending.db")

    # 第一遍：正常建库（生成 schema + 索引）
    store = PendingMemoryStore(db)
    store._conn.close()

    # 造"存量"：撤掉索引后塞入同分区两条 rejected（旧库升级前的形态）
    raw = sqlite3.connect(db)
    raw.execute("DROP INDEX IF EXISTS pending_memories_live_fp_idx")
    for i, decided in enumerate((100.0, 200.0)):
        raw.execute(
            "INSERT INTO pending_memories (id, content, status, fingerprint,"
            " proposed_by, created_at, decided_by, decided_at)"
            " VALUES (?, ?, 'rejected', ?, ?, ?, 'admin', ?)",
            (f"r{i}", f"content-{i}", "fp-x", "user-a", 50.0, decided),
        )
    raw.commit()
    raw.close()

    # 修复前：此处 CREATE UNIQUE INDEX 抛 IntegrityError → 建库失败
    store2 = PendingMemoryStore(db)
    rows = store2._conn.execute(
        "SELECT id, decided_at FROM pending_memories WHERE status='rejected'"
        " AND fingerprint='fp-x' AND proposed_by='user-a'"
    ).fetchall()
    assert len(rows) == 1, rows
    assert rows[0][1] == 200.0, "同分区去重必须保留最新 decided_at"
    store2._conn.close()
