# -*- coding: utf-8 -*-
"""PRAGMA user_version 版本化迁移机制（补课 1.2）。

替代"仅 IF NOT EXISTS"的无版本 schema 演进：注册表严格递增、
每条独立事务、失败回滚并上抛、执行过的版本按 user_version 跳过。
"""
import sqlite3

import pytest

from neurova.core.db_migration import migrate, register_migration, _MIGRATIONS


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个用例独立注册表快照（注册表是模块级全局）。"""
    import neurova.core.db_migration as dm

    saved = list(dm._MIGRATIONS)
    dm._MIGRATIONS.clear()
    yield
    dm._MIGRATIONS.clear()
    dm._MIGRATIONS.extend(saved)


@pytest.fixture()
def fresh_conn(tmp_path):
    conn = sqlite3.connect(tmp_path / "m.db")
    yield conn
    conn.close()


def test_fresh_db_gets_baseline_version(fresh_conn):
    register_migration(1, "SELECT 1")
    applied = migrate(fresh_conn, "test")
    assert fresh_conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert applied == [1]


def test_migrations_run_in_order_once(fresh_conn):
    calls = []
    register_migration(101, lambda c: calls.append(101))
    register_migration(102, lambda c: calls.append(102))
    migrate(fresh_conn, "test-order")
    migrate(fresh_conn, "test-order")  # 第二次全跳过
    assert calls == [101, 102]
    assert fresh_conn.execute("PRAGMA user_version").fetchone()[0] == 102


def test_failed_migration_rolls_back(fresh_conn):
    def boom(conn):
        conn.execute("CREATE TABLE t1(a)")
        raise RuntimeError("migration boom")

    register_migration(201, boom)
    with pytest.raises(RuntimeError):
        migrate(fresh_conn, "test-fail")
    assert fresh_conn.execute("PRAGMA user_version").fetchone()[0] < 201
    # 事务回滚：boom 里建的表不存在
    assert (
        fresh_conn.execute("SELECT name FROM sqlite_master WHERE name='t1'").fetchone() is None
    )


def test_sql_script_migration(fresh_conn):
    register_migration(
        301, "CREATE TABLE IF NOT EXISTS t2(a INTEGER); INSERT INTO t2(a) VALUES (42);"
    )
    migrate(fresh_conn, "test-sql")
    assert fresh_conn.execute("SELECT a FROM t2").fetchone()[0] == 42
