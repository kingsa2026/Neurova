# -*- coding: utf-8 -*-
"""B4-005 启动加载与热集回载（判据 A9）。

红灯依据（改前实证）：

- 池构造时**完全不读**台账：既没有"登记 `COUNT(*)`"这一步，也没有任何回载入口。
  于是 `get_retention_stats()` / `/metrics` 里的 `ledger_persistence` 只有写侧计数，
  **库内已有多少条归档无人知道**——启动代价这条策略处于"没人实现"的状态（不是"做错了"）。
- 显式回载入口 `rehydrate(limit)` 不存在：需要预热时调用方无从下手。

契约（修复后，规格 D10）：

- 启动**只登记一次** `COUNT(*)`（机器可读落点：`get_retention_stats()["ledger"]["rows"]`），
  **不把历史塞回常驻**——D1 要的是"取得到"，不是"开局全在内存"；
- 登记查询次数为**常数**（与库内行数无关），且只在构造期发生一次；
- `rehydrate(limit)` 是显式入口，**默认路径不调用**；回载走 `id DESC LIMIT`，
  顺序稳定（前缀缓存契约：同库同 limit 两次回载得到同一顺序）；
- **`draw` 不查 DB**：常驻集是视图唯一来源（规格 §4 非目标），否则每轮扫库会把
  规模问题提前引爆。这条以"台账被注入探针"的方式断言。
"""

import sqlite3

import pytest

from neurova.context.eviction_ledger_db import EvictionLedgerDB
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool

HISTORY_ROWS = 300


class _CountingLedger(EvictionLedgerDB):
    """台账替身：用 `set_trace_callback` 逐条记录 SQL，用来断言"启动几次查询"
    与"视图路径零查询"。`sqlite3.Connection` 不允许挂自定义属性，故用 id 集合去重。"""

    def __init__(self, *args, **kwargs):
        self.statements = []
        self._hooked = set()
        super().__init__(*args, **kwargs)

    def _statementCount(self) -> int:
        return len(self.statements)

    def _requireConn(self):
        conn = super()._requireConn()
        if id(conn) not in self._hooked:
            conn.set_trace_callback(self.statements.append)
            self._hooked.add(id(conn))
        return conn


def _seed(dbPath, rows=HISTORY_ROWS):
    """预置历史归档（直接建库写入；本文件的被测对象是"启动做什么"，不是写入路径）。"""
    ledger = EvictionLedgerDB(db_path=dbPath, user_id="u1", agent_id="a1")
    ledger.beginBatch()
    for i in range(rows):
        ledger.record(content=f"历史归档第{i}条：设备固件升级窗口", turn_id=f"t{i}", session_id="s1")
    ledger.commitBatch()
    ledger.close()


def _pool(dbPath, **kwargs):
    return ContextPool(
        user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0,
        ledger_db=_CountingLedger(db_path=dbPath, user_id="u1", agent_id="a1"),
        **kwargs,
    )


class TestStartupRegistersOnly:
    """A9：启动只登记，不预载。"""

    def test_startup_query_count_is_constant(self, tmp_path):
        small = tmp_path / "small.db"
        big = tmp_path / "big.db"
        _seed(small, rows=5)
        _seed(big, rows=HISTORY_ROWS)

        smallPool = _pool(small)
        bigPool = _pool(big)
        smallQueries = smallPool._ledger_db._statementCount()
        bigQueries = bigPool._ledger_db._statementCount()

        assert smallQueries == bigQueries, (
            f"启动查询次数随库内行数变化（5 行 {smallQueries} 次 vs {HISTORY_ROWS} 行 {bigQueries} 次）"
            "——启动不该做与行数相关的工作"
        )
        assert bigPool.resident_count() == 0, "启动把历史塞回了常驻（D1 只要求取得到）"

    def test_history_size_is_reported(self, tmp_path):
        dbPath = tmp_path / "reported.db"
        _seed(dbPath, rows=HISTORY_ROWS)
        pool = _pool(dbPath)
        assert pool.get_retention_stats()["ledger"]["rows"] == HISTORY_ROWS, (
            "启动没有登记库内归档条数——/metrics 看不到持久规模"
        )
        assert pool.get_retention_stats()["ledger"]["registered_at_startup"] is True

    def test_register_uses_single_count_query(self, tmp_path):
        dbPath = tmp_path / "singlecount.db"
        _seed(dbPath)
        pool = _pool(dbPath)
        counts = [s for s in pool._ledger_db.statements if "COUNT(*)" in s.upper()]
        assert len(counts) == 1, f"启动对库的登记查询不是一次：{counts}"


class TestRehydrate:
    """显式回载：默认不调用，调用时顺序稳定。"""

    def test_default_path_does_not_rehydrate(self, tmp_path):
        dbPath = tmp_path / "default.db"
        _seed(dbPath)
        pool = _pool(dbPath)
        assert pool.resident_count() == 0, "默认路径回载了历史（默认必须不预载）"

    def test_rehydrate_loads_recent_in_stable_order(self, tmp_path):
        dbPath = tmp_path / "rehydrate.db"
        _seed(dbPath, rows=50)
        pool = _pool(dbPath)

        loaded = pool.rehydrate(limit=10)
        assert len(loaded) == 10
        assert [c.content for c in loaded] == [
            f"历史归档第{i}条：设备固件升级窗口" for i in range(49, 39, -1)
        ], "回载顺序不是 id DESC（前缀缓存契约要求顺序稳定）"
        assert pool.resident_count() == 10

        other = _pool(dbPath)
        assert [c.content for c in other.rehydrate(limit=10)] == [c.content for c in loaded], (
            "同库同 limit 两次回载顺序不一致（前缀缓存契约失效）"
        )

    def test_rehydrate_is_idempotent_per_content(self, tmp_path):
        dbPath = tmp_path / "idem.db"
        _seed(dbPath, rows=20)
        pool = _pool(dbPath)
        pool.rehydrate(limit=5)
        pool.rehydrate(limit=5)
        assert pool.resident_count() == 5, "重复回载把同内容又加了一遍（去重语义失效）"

    def test_rehydrate_without_ledger_is_noop(self):
        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0)
        assert pool.rehydrate(limit=10) == []


class TestDrawNeverTouchesLedger:
    """`draw` 零 DB 访问（规格 §4 非目标：常驻集是视图唯一来源）。"""

    def test_draw_and_query_hit_no_database(self, tmp_path):
        dbPath = tmp_path / "draw.db"
        _seed(dbPath, rows=30)
        pool = _pool(dbPath)
        pool.rehydrate(limit=5)
        before = pool._ledger_db._statementCount()

        for _ in range(3):
            pool.draw(need="固件升级窗口")
            pool.query()
            pool.get_contexts()
            pool.resident_count()

        assert pool._ledger_db._statementCount() == before, (
            "视图路径查了库（draw/query/get_contexts 之一）——常驻集必须自足"
        )

    def test_recall_is_the_only_read_path(self, tmp_path):
        """反向锁：唯一允许查库的读路径是 `recall_evicted`（否则是修过头）。"""
        dbPath = tmp_path / "recall.db"
        _seed(dbPath, rows=10)
        pool = _pool(dbPath)
        before = pool._ledger_db._statementCount()
        recalled = pool.recall_evicted(query="固件", limit=5)

        assert recalled, "显式召回取不到内容（修过头）"
        assert pool._ledger_db._statementCount() > before, "recall_evicted 没有查库——它拿什么召回"


class TestRegistrationFailureIsVisible:
    """登记失败不阻断池构造，但必须是可见状态（不是看起来正常的 0）。"""

    def test_failed_registration_is_reported(self, tmp_path, caplog):
        import logging

        class _BrokenCountLedger(EvictionLedgerDB):
            def count(self):
                raise sqlite3.OperationalError("database is locked")

        dbPath = tmp_path / "broken.db"
        _seed(dbPath, rows=3)
        with caplog.at_level(logging.WARNING, logger="neurova.context_pool"):
            pool = ContextPool(
                user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0,
                ledger_db=_BrokenCountLedger(db_path=dbPath, user_id="u1", agent_id="a1"),
            )
        ledgerRead = pool.get_retention_stats()["ledger"]
        assert ledgerRead["registered_at_startup"] is False
        assert "OperationalError" in (ledgerRead["last_error"] or ""), (
            "登记失败没有点名原因（读数看起来像一个正常的 0）"
        )
        warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("启动登记失败" in m and "OperationalError" in m for m in warnings)


class TestLedgerRowsOnMetrics:
    """登记值必须真的被 /metrics 读走（否则就是"只写不读"的断点）。"""

    def test_ledger_rows_reaches_metrics(self, tmp_path):
        from prometheus_client import REGISTRY

        dbPath = tmp_path / "metrics.db"
        _seed(dbPath, rows=7)
        pool = _pool(dbPath)
        from neurova.core.metrics import get_metrics

        get_metrics().observe_context_pools()

        labels = {"pool": pool.isolation_key}
        assert REGISTRY.get_sample_value(
            "neurova_context_pool_ledger_rows", labels
        ) == 7.0, "登记到的持久规模没有进 /metrics（指标只写不读等于断点）"


class TestLedgerRegistrationLifecycle:
    """登记的库内条数随写入/清理同步（不写成一份会过期的缓存）。"""

    def test_registered_count_follows_writes(self, tmp_path):
        dbPath = tmp_path / "follow.db"
        _seed(dbPath, rows=5)
        pool = _pool(dbPath)
        assert pool.get_retention_stats()["ledger"]["rows"] == 5

        for i in range(3):
            pool.add_context(
                ContextInput(source=ContextSource.CONVERSATION, content=f"新归档第{i}条", metadata={"turn_id": f"n{i}"})
            )

        assert pool.get_retention_stats()["ledger"]["rows"] == 8, (
            "登记值停在启动快照（对调用方而言是一份过期读数）"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
