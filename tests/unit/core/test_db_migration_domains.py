# -*- coding: utf-8 -*-
"""db_migration 版本域推广 + 防降级校验（Yuxi 对比 P0-4）。

根因：原 _MIGRATIONS 是**全局单链**——任何库注册 v2 都会套到所有库的
user_version 上（记忆库 v2 = 别的库 v2），这是"每库版本域"的隐藏缺陷。
本组测试锁住新契约：
- 版本按 domain 隔离注册/应用
- migrate(conn, domain) 域未注册 → ValueError（强制登记纪律，不静默）
- user_version 高于该域已注册最大版本 → SchemaVersionError（防降级损坏，
  对位 Yuxi require_current_schema / OpenClaw user_version 拒绝打开）
- 存量迁移语义（顺序/独立事务/回滚上抛/脚本型）不下降
"""
import sqlite3

import pytest

import neurova.core.db_migration as dm
from neurova.core.db_migration import (
    SchemaVersionError,
    migrate,
    register_migration,
)


@pytest.fixture(autouse=True)
def _isolate_domains():
    saved = {k: list(v) for k, v in dm._DOMAIN_MIGRATIONS.items()}
    yield
    dm._DOMAIN_MIGRATIONS.clear()
    dm._DOMAIN_MIGRATIONS.update(saved)


@pytest.fixture()
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "d.db")
    yield c
    c.close()


def test_domains_are_isolated(conn, tmp_path):
    register_migration(1, "SELECT 1", domain="alpha")
    conn2 = sqlite3.connect(tmp_path / "b.db")
    try:
        register_migration(2, "CREATE TABLE IF NOT EXISTS only_alpha(x)", domain="alpha")
        register_migration(1, "SELECT 1", domain="beta")
        register_migration(2, "CREATE TABLE IF NOT EXISTS only_beta(y)", domain="beta")
        applied_a = migrate(conn, "alpha")
        applied_b = migrate(conn2, "beta")
        assert applied_a == [1, 2] and applied_b == [1, 2]
        # alpha 的表不出现在 beta 库
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name='only_alpha'"
        ).fetchone()
        assert conn2.execute(
            "SELECT name FROM sqlite_master WHERE name='only_alpha'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name='only_beta'"
        ).fetchone() is None
    finally:
        conn2.close()


def test_unknown_domain_raises_not_silent(conn):
    with pytest.raises(ValueError):
        migrate(conn, "no_such_domain")


def test_downgrade_rejected(conn):
    register_migration(1, "SELECT 1", domain="mem_x")
    conn.execute("PRAGMA user_version=9")
    conn.commit()
    with pytest.raises(SchemaVersionError):
        migrate(conn, "mem_x")


def test_equal_version_noop(conn):
    register_migration(1, "SELECT 1", domain="mem_y")
    migrate(conn, "mem_y")
    assert migrate(conn, "mem_y") == []  # 幂等
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_memory_domain_registered_at_import():
    # cognitive_storage_engine migrate(conn, "memory") 兼容不下降
    assert dm._DOMAIN_MIGRATIONS.get("memory"), "memory 域基线必须在模块导入时登记"


def test_registered_versions_snapshot(conn):
    register_migration(1, "SELECT 1", domain="snap")
    register_migration(3, "SELECT 1", domain="snap")
    migrate(conn, "snap")
    assert dm.schema_version(conn) == 3
    assert "snap" in dm.registered_domains()
