"""usage_history 延迟指标测试（OpenOcta 启发 P1-8：写读分离记账的延迟维度）

OpenOcta 每条消息记录 durationMs / firstTokenMs / toolDurationMs，
延迟报表（p95）由真实数据聚合。Neurova 的 usage_history SQLite 已有
token 记账，本组测试锁定延迟维度增量：

- record() 接受 first_token_ms / duration_ms（缺省 0 = 旧调用方零改动）
- 旧库（无延迟列）打开时自动补列（ALTER TABLE 幂等迁移），存量数据不炸
- latency_stats() 按模型聚合 calls/p50/p95/max（仅统计 duration_ms > 0 的行，
  缺延迟数据不进报表——诚实统计）
"""
from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def store(tmp_path):
    from neurova.core.usage_history import UsageHistoryStore

    return UsageHistoryStore(db_path=str(tmp_path / "u.db"))


class TestLatencyRecord:
    def test_record_accepts_latency_fields(self, store):
        """延迟字段随行落盘（latency_stats 可读回）。"""
        store.record(model="m1", prompt_tokens=1, completion_tokens=1,
                     first_token_ms=120, duration_ms=800)
        stats = store.latency_stats()
        assert len(stats) == 1
        row = stats[0]
        assert row["model"] == "m1"
        assert row["calls"] == 1
        assert row["max_ms"] == 800
        assert row["p50_ms"] == 800
        assert row["p95_ms"] == 800

    def test_record_defaults_zero_keeps_old_callers(self, store):
        """旧调用方（不传延迟）零改动：行照常入账、不进延迟报表。"""
        store.record(model="m1", prompt_tokens=1, completion_tokens=1)
        assert store.daily_totals()[0]["calls"] == 1
        assert store.latency_stats() == []

    def test_p50_p95_aggregation(self, store):
        for d in (100, 200, 300, 400, 1000):
            store.record(model="m", prompt_tokens=1, completion_tokens=1,
                         first_token_ms=10, duration_ms=d)
        row = store.latency_stats()[0]
        assert row["calls"] == 5
        assert row["p50_ms"] == 300
        assert row["p95_ms"] == 1000
        assert row["max_ms"] == 1000

    def test_per_model_isolation(self, store):
        store.record(model="fast", prompt_tokens=1, completion_tokens=1, duration_ms=100)
        store.record(model="slow", prompt_tokens=1, completion_tokens=1, duration_ms=5000)
        stats = {r["model"]: r for r in store.latency_stats()}
        assert stats["fast"]["max_ms"] == 100
        assert stats["slow"]["max_ms"] == 5000


class TestMigration:
    def test_legacy_db_without_latency_columns(self, tmp_path):
        """旧库（存量 schema）打开自动补列，旧数据与继续写入都不炸。"""
        db = tmp_path / "legacy.db"
        with sqlite3.connect(db) as conn:
            conn.execute(
                """
                CREATE TABLE llm_usage (
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
                )
                """
            )
            conn.execute(
                "INSERT INTO llm_usage (ts, usage_date, model, prompt_tokens, completion_tokens, total_tokens)"
                " VALUES ('t', '2026-09-04', 'old', 1, 1, 2)"
            )

        from neurova.core.usage_history import UsageHistoryStore

        store = UsageHistoryStore(db_path=str(db))
        # 旧数据可查
        assert store.daily_totals()[0]["calls"] == 1
        # 新字段可写（迁移后）
        store.record(model="new", prompt_tokens=1, completion_tokens=1,
                     first_token_ms=50, duration_ms=400)
        assert store.latency_stats()[0]["max_ms"] == 400

    def test_migration_idempotent(self, tmp_path):
        """重复打开同一库不重复补列（ALTER 幂等）。"""
        from neurova.core.usage_history import UsageHistoryStore

        db = str(tmp_path / "again.db")
        UsageHistoryStore(db_path=db)
        store2 = UsageHistoryStore(db_path=db)  # 第二次打开
        store2.record(model="m", prompt_tokens=1, completion_tokens=1, duration_ms=10)
        assert store2.latency_stats()[0]["max_ms"] == 10
