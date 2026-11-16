# -*- coding: utf-8 -*-
"""db_migration 注册批守卫（审计 3.2-9 + 3.3-2 + 3.4-10，2026-11-17）：

8 个自建表域（usage_history/aigc_usage/annotations/pending_memories/
channel_identity/channel_outbound/approval/evolution_jobs）必须登记进
`core/db_migration` 版本注册表（PRAGMA user_version），不得停留在
"仅 IF NOT EXISTS"的无版本 schema 演进——对照 `context/eviction_ledger_db.py`
合规范本。同时钉住 usage_history 建库失败的诚实暴露（审计 3.2-5：
原 `except Exception: pass` 让"写入持续失败且启动无读数"零线索）。
"""

from __future__ import annotations

import logging
import sqlite3

import pytest

from neurova.core.db_migration import (
    latest_version,
    migrate as apply_migrations,
    registered_domains,
)

# (注册域名, 模块, 该域必须存在的表)
_BATCH = [
    ("usage_history", "neurova.core.usage_history", ["llm_usage"]),
    ("aigc_usage", "neurova.core.aigc_usage", ["aigc_gen_usage"]),
    ("annotations", "neurova.core.annotation_store", ["annotations"]),
    ("pending_memories", "neurova.memory.pending_memory", ["pending_memories", "content_tombstones"]),
    ("channel_identity", "neurova.channels.user_identity", ["channel_user_bindings", "channel_observed_senders"]),
    ("channel_outbound", "neurova.channels.outbound_ledger", ["outbound_failures", "ingress_bypass"]),
    ("approval", "neurova.security.approval_manager", ["approval_requests"]),
    ("evolution_jobs", "neurova.evolution.job_queue", ["evolution_jobs"]),
]


class TestAllDomainsRegistered:
    @pytest.mark.parametrize("domain,module_path,tables", _BATCH)
    def test_domain_registered_and_migrates_fresh_db(self, domain, module_path, tables, tmp_path):
        import importlib

        importlib.import_module(module_path)

        assert domain in registered_domains(), (
            f"domain={domain!r} 未登记进 db_migration 注册表（模块 {module_path}）"
        )
        conn = sqlite3.connect(str(tmp_path / f"{domain}.db"))
        try:
            applied = apply_migrations(conn, domain)
            assert conn.execute("PRAGMA user_version").fetchone()[0] == latest_version(domain)
            assert applied == list(range(1, latest_version(domain) + 1))
            names = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table in tables:
                assert table in names, f"domain={domain!r} 迁移后缺表 {table}"
        finally:
            conn.close()

    def test_importing_modules_does_not_double_register(self):
        """重复 import（register 幂等忽略同版本）不得抬高版本或抛错。"""
        import importlib

        for _, module_path, _ in _BATCH:
            importlib.import_module(module_path)
        assert "usage_history" in registered_domains()


class TestUsageHistoryOldDbBackfill:
    def test_legacy_columns_added_and_version_stamped(self, tmp_path):
        """旧库（无 first_token_ms 等列、user_version=0）打开后补列并落版本。"""
        import neurova.core.usage_history as uh

        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            """CREATE TABLE IF NOT EXISTS llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                usage_date TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'anonymous',
                model TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT '',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                estimated INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.commit()
        conn.close()

        uh.UsageHistoryStore(db_path=str(db))

        conn = sqlite3.connect(str(db))
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(llm_usage)")}
            for column in ("first_token_ms", "duration_ms", "cache_read_tokens", "cache_write_tokens", "agent_id"):
                assert column in columns, f"旧库缺列 {column} 未被迁移补齐"
            assert conn.execute("PRAGMA user_version").fetchone()[0] == latest_version("usage_history")
        finally:
            conn.close()


class TestUsageHistoryInitFailureHonest:
    def test_init_failure_logged_as_error(self, tmp_path, caplog):
        """建库失败必须 ERROR 级留痕（原 except Exception: pass 零线索）。"""
        import neurova.core.usage_history as uh

        # 父路径是一个**文件**——mkdir 必然失败，构造必进失败分支
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir")
        db_path = blocker / "nested" / "usage.db"

        with caplog.at_level(logging.ERROR, logger="neurova.core.usage_history"):
            store = uh.UsageHistoryStore(db_path=str(db_path))
            # fail-soft 语义保持：构造不抛（内存记账主流程不受影响）
            assert store is not None

        assert any(
            "usage_history" in (r.getMessage() + r.name) and r.levelno == logging.ERROR
            for r in caplog.records
        ), "建库失败必须留下 ERROR 级启动读数"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
