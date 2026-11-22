"""资源治理 P2-5：SQLite 存储自治理。

- runDatabaseMaintenance：WAL checkpoint(TRUNCATE) + optimize 真执行，
  返回统计并点亮 neurova_db_maintenance_last_run_unixtime gauge；
- registerDatabaseMaintenanceJob：每日系统 job 注册契约（jobId/秒数）。
"""

import sqlite3

import pytest

from neurova.core.connection_pool import get_connection_pool, close_all_pools
from neurova.core.db_maintenance import (
    registerDatabaseMaintenanceJob,
    runDatabaseMaintenance,
)
from neurova.core.metrics import get_metrics


@pytest.fixture()
def fresh_pool(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_ROOT", str(tmp_path))
    close_all_pools()
    yield str(tmp_path)
    close_all_pools()


class TestRunDatabaseMaintenance:
    def test_checkpoint_and_optimize_execute(self, fresh_pool):
        # 先造一点 WAL 流量
        pool = get_connection_pool()
        with pool.connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS probe(id INTEGER)")
            conn.execute("INSERT INTO probe VALUES (1)")
            conn.commit()
        stats = runDatabaseMaintenance()
        assert stats["db"].endswith("neurova_memory.db")
        assert stats["wal_busy"] in (0, 1)
        assert stats["wal_log_frames"] >= 0
        assert stats["wal_checkpointed_frames"] >= 0

    def test_gauge_lit_after_maintenance(self, fresh_pool):
        runDatabaseMaintenance()
        gauge = get_metrics().db_maintenance_last_run_unixtime
        assert gauge._value.get() > 0

    def test_register_job_contract(self):
        captured = {}

        class _StubScheduler:
            def addSystemJob(self, func, jobId, seconds):
                captured["func"] = func
                captured["jobId"] = jobId
                captured["seconds"] = seconds

        assert registerDatabaseMaintenanceJob(_StubScheduler()) is True
        assert captured["jobId"] == "db_maintenance"
        assert captured["seconds"] == 86400
        # 注册的 job 本体可安全执行（fail-soft 包装）
        assert "ok" not in captured["func"]() or captured["func"]()["ok"] is not False

    def test_register_refuses_none(self):
        assert registerDatabaseMaintenanceJob(None) is False
