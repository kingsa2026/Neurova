"""资源治理 P1-2：后台任务每日原子配额（fail-closed）契约。

- 原子性：BEGIN IMMEDIATE 串行化「读-判-增」，多连接并发领取不越限；
- fail-closed：配额存储不可用（连接坏/表坏/语句抛错）一律拒绝放行——
  后台任务少跑一轮可恢复，失控跑批不可恢复；
- 粒度：(配额名, UTC 日) 二元组，跨日自动归零；
- 上限经环境变量注入，垃圾值回落缺省。
"""

import sqlite3
import threading

import pytest

from neurova.core.background_quota import (
    acquireDailyQuota,
    dailyLimitFromEnv,
    ensureQuotaSchema,
)


def _freshConn(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "quota.db"), timeout=5.0)
    ensureQuotaSchema(conn)
    return conn


class TestAcquireDailyQuota:
    def test_grants_up_to_limit_then_denies(self, tmp_path):
        conn = _freshConn(tmp_path)
        for _ in range(3):
            assert acquireDailyQuota("rsi_iteration", 3, conn=conn) is True
        assert acquireDailyQuota("rsi_iteration", 3, conn=conn) is False

    def test_names_are_isolated(self, tmp_path):
        conn = _freshConn(tmp_path)
        assert acquireDailyQuota("a", 1, conn=conn) is True
        assert acquireDailyQuota("b", 1, conn=conn) is True
        assert acquireDailyQuota("a", 1, conn=conn) is False

    def test_days_are_isolated(self, tmp_path):
        conn = _freshConn(tmp_path)
        assert acquireDailyQuota("a", 1, conn=conn, day="2026-11-22") is True
        assert acquireDailyQuota("a", 1, conn=conn, day="2026-11-22") is False
        assert acquireDailyQuota("a", 1, conn=conn, day="2026-11-23") is True

    def test_zero_or_negative_limit_denies(self, tmp_path):
        conn = _freshConn(tmp_path)
        assert acquireDailyQuota("a", 0, conn=conn) is False
        assert acquireDailyQuota("a", -1, conn=conn) is False

    def test_fail_closed_when_connection_closed(self, tmp_path):
        conn = _freshConn(tmp_path)
        conn.close()  # 存储不可用
        assert acquireDailyQuota("a", 5, conn=conn) is False

    def test_fail_closed_on_broken_store(self):
        class _Boom:
            def execute(self, *args, **kwargs):
                raise sqlite3.OperationalError("boom")

        assert acquireDailyQuota("a", 5, conn=_Boom()) is False

    def test_uses_default_pool_when_conn_omitted(self, tmp_path, monkeypatch):
        # 无 conn 时走连接池默认库（数据根），配额真实落库可复查
        monkeypatch.setenv("NEUROVA_DATA_ROOT", str(tmp_path))
        from neurova.core import connection_pool as cp

        cp.close_all_pools()
        try:
            assert acquireDailyQuota("pool_probe", 1) is True
            assert acquireDailyQuota("pool_probe", 1) is False
        finally:
            cp.close_all_pools()

    def test_concurrent_acquires_never_exceed_limit(self, tmp_path):
        # 多连接并发（各自独立连接打到同一库文件）：BEGIN IMMEDIATE 串行化，
        # 20 线程抢 5 个名额，放行数必须恰为 5
        db_file = tmp_path / "quota.db"
        conn0 = sqlite3.connect(str(db_file), timeout=5.0)
        ensureQuotaSchema(conn0)
        conn0.close()

        granted = []
        lock = threading.Lock()

        def worker():
            conn = sqlite3.connect(str(db_file), timeout=5.0)
            try:
                ok = acquireDailyQuota("a", 5, conn=conn)
            finally:
                conn.close()
            with lock:
                granted.append(ok)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(1 for x in granted if x) == 5


class TestDailyLimitFromEnv:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEST_QUOTA", "7")
        assert dailyLimitFromEnv("NEUROVA_TEST_QUOTA", 500) == 7

    def test_garbage_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEST_QUOTA", "abc")
        assert dailyLimitFromEnv("NEUROVA_TEST_QUOTA", 500) == 500

    def test_missing_env_uses_default(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_TEST_QUOTA", raising=False)
        assert dailyLimitFromEnv("NEUROVA_TEST_QUOTA", 500) == 500

    def test_negative_env_clamped_to_zero(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEST_QUOTA", "-3")
        assert dailyLimitFromEnv("NEUROVA_TEST_QUOTA", 500) == 0
