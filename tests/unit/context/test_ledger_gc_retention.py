# -*- coding: utf-8 -*-
"""B4-007 台账保留策略：GC 在生产可触发，且 FTS 与内容表不脱节。

根因（规格 D11，本文件红灯即证）：

``_LEDGER_GC_EVERY`` 的节流计数挂在 ``_archive_evicted`` 上，而该方法的两个调用方
在生产构造面都不可达——``resident_limit=None``（不回收）、``ttl_seconds=0``
（``cleanup_expired()`` 立即返回 0）。持久层真跑起来之后，进程不再退出，
**GC 一次也不会触发**：库只会单调增长，"保留策略生效"是句空话。

契约（修复后，判据 A5）：

- GC 触发点落在**真有调用方**的位置：一次归档批量提交 = 一次触发计数的来源；
- 保留策略两维默认生效（``keep_count`` / ``keep_days``），不是"配了才生效"；
- 超限清理后内容表收敛到上限，且 **FTS 行数与之相等**（两表不脱节）；
- 清理是**可见状态**：触发次数与清理条数经 ``get_retention_stats()`` 上报，不静默；
- FTS 对齐走**分批删除**，不用整表 ``NOT IN``（分批不长时间持写锁）；
  ``delete-all`` 对本表不合法（普通 FTS5），不得依赖。
"""

import sqlite3

import pytest

from neurova.context.eviction_ledger_db import EvictionLedgerDB
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool


def _chunk(content):
    return ContextInput(source=ContextSource.CONVERSATION, content=content)


def _pool(db_path, **kwargs):
    return ContextPool(
        user_id="u", agent_id="a", session_id="s1", ttl_seconds=0,
        ledger_db=EvictionLedgerDB(db_path=db_path, user_id="u", agent_id="a", **kwargs),
    )


def _ftsRows(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM evicted_fts").fetchone()[0]
    finally:
        conn.close()


class TestGcTriggerHasRealCaller:
    def test_batchCommitDrivesGcThrottle(self, tmp_path, monkeypatch):
        """一次归档批量提交计入一次 GC 节流（生产可达的触发点）。

        红灯依据：节流计数挂在 ``_archive_evicted`` 上，而归档走
        ``archiveBatch`` → ``_flushBatch``，该路径不经过驱逐——计数恒 0。
        """
        import neurova.context_pool as cp_module

        ledger = EvictionLedgerDB(db_path=tmp_path / "l.db", user_id="u", agent_id="a")
        gc_calls = []
        original = ledger.gc_stale

        def countingGc():
            gc_calls.append(1)
            return original()

        ledger.gc_stale = countingGc
        monkeypatch.setattr(cp_module, "_LEDGER_GC_EVERY", 2)
        pool = _pool(tmp_path / "l.db")
        pool._ledger_db = ledger

        for batch in range(4):
            with pool.archiveBatch():
                for i in range(3):
                    pool.add_context(_chunk(f"批次{batch}条目{i}"))

        assert gc_calls, "批量提交未驱动 GC——保留策略在生产不可达（同 _archive_evicted 的根因）"

    def test_singleWriteDrivesGcThrottle(self, tmp_path, monkeypatch):
        """批外单条写入同样计入节流（两条写路径都要真能触发）。"""
        import neurova.context_pool as cp_module

        ledger = EvictionLedgerDB(db_path=tmp_path / "l.db", user_id="u", agent_id="a")
        gc_calls = []
        original = ledger.gc_stale
        ledger.gc_stale = lambda: (gc_calls.append(1), original())[1]
        monkeypatch.setattr(cp_module, "_LEDGER_GC_EVERY", 2)
        pool = _pool(tmp_path / "l.db")
        pool._ledger_db = ledger

        for i in range(4):
            pool.add_context(_chunk(f"单条{i}"))

        assert gc_calls, "单条写路径未驱动 GC 节流"


class TestGcObservable:
    def test_retention_statsReportGc(self, tmp_path, monkeypatch):
        """GC 触发与清理条数必须可见（不静默）。"""
        import neurova.context_pool as cp_module

        pool = _pool(tmp_path / "l.db", keep_count=2)
        monkeypatch.setattr(cp_module, "_LEDGER_GC_EVERY", 1)

        for i in range(5):
            pool.add_context(_chunk(f"c{i}"))

        gcStats = pool.get_retention_stats()["ledger_gc"]
        assert gcStats["runs"] >= 1, "GC 触发计数不可见"
        assert gcStats["removed"] >= 1, "清理条数不可见"

    def test_poolGcConvergesLibrary(self, tmp_path, monkeypatch):
        """池侧触发的 GC 真的收敛了库（不只是在测试替身上数调用次数）。"""
        import neurova.context_pool as cp_module

        pool = _pool(tmp_path / "l.db", keep_count=3)
        monkeypatch.setattr(cp_module, "_LEDGER_GC_EVERY", 1)

        for i in range(8):
            pool.add_context(_chunk(f"c{i}"))

        assert pool._ledger_db.count() == 3
        assert _ftsRows(tmp_path / "l.db") == 3
        assert pool.get_retention_stats()["ledger_gc"]["removed"] >= 5


class TestRetentionConvergence:
    def test_keepCountConvergesContentAndFts(self, tmp_path):
        """A5：超限清理后内容表收敛到上限，FTS 行数与之相等。"""
        dbPath = tmp_path / "l.db"
        ledger = EvictionLedgerDB(db_path=dbPath, user_id="u", agent_id="a", keep_count=200)
        for i in range(900):
            ledger.record(content=f"归档条目 {i}", session_id="s1")

        removed = ledger.gc_stale()

        assert removed >= 700
        assert ledger.count() == 200
        assert _ftsRows(dbPath) == ledger.count(), "FTS 与内容表脱节"

    def test_keepDaysExpiresOldRows(self, tmp_path):
        """keep_days 维度同样生效：注入旧 evicted_at 后被清理。"""
        import datetime

        dbPath = tmp_path / "l.db"
        ledger = EvictionLedgerDB(db_path=dbPath, user_id="u", agent_id="a", keep_days=30)
        for i in range(5):
            ledger.record(content=f"新条目 {i}", session_id="s1")
        old = (datetime.datetime.now() - datetime.timedelta(days=90)).isoformat()
        conn = sqlite3.connect(str(dbPath))
        try:
            conn.execute("UPDATE evicted_chunks SET evicted_at = ?", (old,))
            conn.commit()
        finally:
            conn.close()

        removed = ledger.gc_stale()

        assert removed == 5
        assert ledger.count() == 0
        assert _ftsRows(dbPath) == 0

    def test_purgeScopeIsPerUserAgent(self, tmp_path):
        """清理只动本 (user, agent) 分区，不越权删别人的归档。"""
        dbPath = tmp_path / "l.db"
        mine = EvictionLedgerDB(db_path=dbPath, user_id="u", agent_id="a", keep_count=2)
        other = EvictionLedgerDB(db_path=dbPath, user_id="u2", agent_id="a2", keep_count=2)
        for i in range(6):
            mine.record(content=f"我的 {i}", session_id="s1")
            other.record(content=f"他人的 {i}", session_id="s1")

        mine.gc_stale()

        assert mine.count() == 2
        assert other.count() == 6, "越权清理了别的 (user, agent) 分区"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
