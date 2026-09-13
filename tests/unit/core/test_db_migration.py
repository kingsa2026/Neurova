# -*- coding: utf-8 -*-
"""PRAGMA user_version 版本化迁移机制（补课 1.2）。

替代"仅 IF NOT EXISTS"的无版本 schema 演进：注册表严格递增、
每条独立事务、失败回滚并上抛、执行过的版本按 user_version 跳过。

2026-09-13 契约更新（Yuxi 对比 P0-4）：注册表从全局单链改为**按 domain
隔离**（旧全局链会让 A 库注册的 v2 套到 B 库头上）。原测试语义
（基线/顺序/回滚/脚本型）逐条保留，仅调用形态随新契约显式带域。
"""
import sqlite3

import pytest

from neurova.core.db_migration import migrate, register_migration
import neurova.core.db_migration as dm


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个用例独立注册表快照（注册表是模块级按域字典）。"""
    saved = {k: list(v) for k, v in dm._DOMAIN_MIGRATIONS.items()}
    dm._DOMAIN_MIGRATIONS.clear()
    yield
    dm._DOMAIN_MIGRATIONS.clear()
    dm._DOMAIN_MIGRATIONS.update(saved)


@pytest.fixture()
def fresh_conn(tmp_path):
    conn = sqlite3.connect(tmp_path / "m.db")
    yield conn
    conn.close()


def test_fresh_db_gets_baseline_version(fresh_conn):
    register_migration(1, "SELECT 1", domain="test")
    applied = migrate(fresh_conn, "test")
    assert fresh_conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert applied == [1]


def test_migrations_run_in_order_once(fresh_conn):
    calls = []
    register_migration(101, lambda c: calls.append(101), domain="test-order")
    register_migration(102, lambda c: calls.append(102), domain="test-order")
    migrate(fresh_conn, "test-order")
    migrate(fresh_conn, "test-order")  # 第二次全跳过
    assert calls == [101, 102]
    assert fresh_conn.execute("PRAGMA user_version").fetchone()[0] == 102


def test_failed_migration_rolls_back(fresh_conn):
    def boom(conn):
        conn.execute("CREATE TABLE t1(a)")
        raise RuntimeError("migration boom")

    register_migration(201, boom, domain="test-fail")
    with pytest.raises(RuntimeError):
        migrate(fresh_conn, "test-fail")
    assert fresh_conn.execute("PRAGMA user_version").fetchone()[0] < 201
    # 事务回滚：boom 里建的表不存在
    assert (
        fresh_conn.execute("SELECT name FROM sqlite_master WHERE name='t1'").fetchone() is None
    )


def test_sql_script_migration(fresh_conn):
    register_migration(
        301,
        "CREATE TABLE IF NOT EXISTS t2(a INTEGER); INSERT INTO t2(a) VALUES (42);",
        domain="test-sql",
    )
    migrate(fresh_conn, "test-sql")
    assert fresh_conn.execute("SELECT a FROM t2").fetchone()[0] == 42
