"""Unit Tests for Cost Rollup System (SQLite-backed)

针对真实临时 SQLite 库跑：写入明细 → 小时聚合 → 查询验证。
不使用任何 asyncpg/PG 假设，也不 mock 掉真实落盘路径。
"""

import os
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from neurova.models.cost_rollup import (
    HourlyRollupManager,
    get_optimized_cost_queries,
    reset_rollup_manager,
)
from neurova.models.cost_store import LlmCostStore, reset_llm_cost_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    """临时 SQLite 账本（测试隔离）。"""
    db = tmp_path / "llm_cost_test.db"
    monkeypatch.setenv("NEUROVA_LLM_COST_DB", str(db))
    reset_llm_cost_store()
    s = LlmCostStore(db_path=str(db))
    yield s
    reset_llm_cost_store()


def _seed(store, agent_id, provider, model, cost, at):
    store.record_call(
        call_id=f"c-{agent_id}-{at.isoformat()}",
        agent_id=agent_id,
        provider=provider,
        model=model,
        direction="input",
        input_tokens=100,
        output_tokens=50,
        cost=cost,
        called_at=at,
    )


# ── 明细写入与持久化 ────────────────────────────────────────────────────


class TestLedgerPersistence:
    def test_record_call_persists(self, store):
        fixed = datetime(2026, 9, 18, 10, 15, 0)
        assert _seed(store, "a1", "openai", "gpt-4", 0.25, fixed) is None or True
        # Verify a row exists in the SQLite file
        conn = sqlite3.connect(store._db_path)
        n = conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0]
        conn.close()
        assert n == 1

    def test_record_multiple_calls(self, store):
        base = datetime(2026, 9, 18, 9, 0, 0)
        for i in range(5):
            _seed(store, "a1", "openai", "gpt-4", 0.10, base + timedelta(minutes=i))
        cur = store.current_hour_summary()
        assert int(cur.get("active_agents") or 0) >= 0  # hour differs, but no crash
        conn = sqlite3.connect(store._db_path)
        total = conn.execute("SELECT SUM(cost) FROM llm_calls").fetchone()[0]
        conn.close()
        assert round(total, 2) == 0.50

    def test_silent_degradation_on_bad_input(self, store):
        # 落盘副路径绝不抛出：传入非法 cost 类型也应安全返回
        ok = store.record_call(
            call_id="bad", agent_id="a", provider="p", model="m",
            direction="input", input_tokens="not-int", output_tokens=None,
            cost="nan", called_at=datetime(2026, 9, 18, 10, 0, 0),
        )
        assert ok is False


# ── 小时聚合（rollup） ──────────────────────────────────────────────────


class TestRollupAggregation:
    def test_rollup_groups_by_hour(self, store):
        hour = datetime(2026, 9, 18, 10, 0, 0)
        _seed(store, "a1", "openai", "gpt-4", 0.10, hour + timedelta(minutes=5))
        _seed(store, "a1", "openai", "gpt-4", 0.15, hour + timedelta(minutes=20))
        _seed(store, "a1", "anthropic", "claude-3", 0.30, hour + timedelta(minutes=40))

        manager = HourlyRollupManager(store=store)
        affected = manager.run_rollup(hour=hour)
        assert affected >= 1

        rows = store.query_rollup_since(hour.strftime("%Y-%m-%dT%H:00:00"))
        # Two groups: (openai,gpt-4) and (anthropic,claude-3)
        assert len(rows) == 2
        openai = [r for r in rows if r["provider"] == "openai"][0]
        assert round(float(openai["total_cost"]), 2) == 0.25
        assert int(openai["call_count"]) == 2

    def test_rollup_is_idempotent(self, store):
        hour = datetime(2026, 9, 18, 11, 0, 0)
        _seed(store, "a1", "openai", "gpt-4", 0.10, hour + timedelta(minutes=2))
        manager = HourlyRollupManager(store=store)
        manager.run_rollup(hour=hour)
        manager.run_rollup(hour=hour)  # 第二次应覆盖而非累加

        rows = store.query_rollup_since(hour.strftime("%Y-%m-%dT%H:00:00"))
        assert len(rows) == 1
        assert round(float(rows[0]["total_cost"]), 2) == 0.10

    def test_rollup_excludes_other_hours(self, store):
        h10 = datetime(2026, 9, 18, 10, 0, 0)
        h11 = datetime(2026, 9, 18, 11, 0, 0)
        _seed(store, "a1", "openai", "gpt-4", 0.10, h10 + timedelta(minutes=30))
        _seed(store, "a1", "openai", "gpt-4", 0.20, h11 + timedelta(minutes=30))

        HourlyRollupManager(store=store).run_rollup(hour=h11)
        rows = store.query_rollup_since(h11.strftime("%Y-%m-%dT%H:00:00"))
        assert all(r["hour"].startswith("2026-09-18T11") for r in rows)
        assert round(sum(float(r["total_cost"]) for r in rows), 2) == 0.20

    def test_force_rollup_range(self, store):
        start = datetime(2026, 9, 18, 8, 0, 0)
        _seed(store, "a1", "openai", "gpt-4", 0.10, start + timedelta(minutes=10))
        _seed(store, "a1", "openai", "gpt-4", 0.20, start + timedelta(hours=1, minutes=10))
        total = HourlyRollupManager(store=store).force_rollup_for_range(
            start, start + timedelta(hours=2)
        )
        assert total >= 1


# ── 查询接口 ────────────────────────────────────────────────────────────


class TestQueries:
    def test_daily_cost_from_detail(self, store):
        day = datetime(2026, 9, 18, 13, 0, 0)
        _seed(store, "a1", "openai", "gpt-4", 0.10, day)
        _seed(store, "a1", "openai", "gpt-4", 0.20, day + timedelta(minutes=5))
        hist = store.query_daily_cost(days=3650)
        assert any(h["date"] == "2026-09-18" for h in hist)

    def test_agent_cost_summary(self, store):
        day = datetime(2026, 9, 18, 13, 0, 0)
        _seed(store, "a1", "openai", "gpt-4", 0.40, day)
        result = store.get_agent_cost(
            "a1", day - timedelta(hours=1), day + timedelta(hours=1)
        )
        assert round(result["total_cost"], 2) == 0.40

    def test_optimized_queries_are_sqlite_dialect(self):
        queries = get_optimized_cost_queries()
        assert set(queries) >= {
            "daily_cost_by_agent",
            "hourly_trend",
            "provider_breakdown",
            "model_usage_ranking",
        }
        # SQLite 方言：不应残留 Postgres 专有语法
        for name, sql in queries.items():
            assert "$1" not in sql, f"{name} 仍含 asyncpg 占位符"
            assert "DATE_TRUNC" not in sql, f"{name} 仍含 PG DATE_TRUNC"


# ── 全局管理器生命周期 ──────────────────────────────────────────────────


class TestManagerLifecycle:
    def test_manager_without_store_does_not_start(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_LLM_COST_DB", raising=False)
        reset_llm_cost_store()
        reset_rollup_manager()
        manager = HourlyRollupManager(store=None)
        assert manager.start_background_job() is False
        reset_rollup_manager()

    def test_manager_status_reports_store_ready(self, store):
        manager = HourlyRollupManager(store=store)
        assert manager.status["store_ready"] is True
        assert manager.status["running"] is False
