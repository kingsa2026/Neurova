"""
Token 用量持久化历史红测（TDD，先测后码）

原缺陷：TokenUsageAccounting 纯内存记账，重启归零、无 user_id/时间戳，
"使用统计"看板无历史源。

新语义：
- UsageHistoryStore（SQLite，data/usage_history.db，env NEUROVA_USAGE_HISTORY_DB
  可覆盖——conftest autouse 已把测试指向 tmp_path）
- record() 一次 LLM 调用一行；daily_totals/daily_by_model/model_totals/
  peak_daily/total 聚合查询；user_id 可选过滤
- compute_streaks(active_dates, today)：当前/最长连续天数纯函数
- 全部查询异常回退空/0，record 失败静默（主流程零影响）
"""

from datetime import date, timedelta

import pytest

from neurova.core.usage_history import (
    UsageHistoryStore,
    compute_streaks,
    get_usage_history,
    reset_usage_history,
)


@pytest.fixture(autouse=True)
def _clean_history():
    reset_usage_history()
    yield
    reset_usage_history()


def _store() -> UsageHistoryStore:
    return get_usage_history()


class TestRecordAndTotal:
    def test_record_persists_and_total_aggregates(self):
        store = _store()
        store.record(
            ts="2026-09-01T10:00:00Z",
            usage_date="2026-09-01",
            user_id="u1",
            model="glm-5.3-flash",
            provider="zhipu",
            prompt_tokens=100,
            completion_tokens=50,
        )
        store.record(
            ts="2026-09-01T11:00:00Z",
            usage_date="2026-09-01",
            user_id="u1",
            model="deepseek-v4",
            provider="deepseek",
            prompt_tokens=30,
            completion_tokens=20,
            estimated=True,
        )
        total = store.total()
        assert total["tokens"] == 200
        assert total["calls"] == 2

    def test_record_isolated_between_instances(self):
        """落盘持久化：新实例可读到旧记录（跨重启语义）。"""
        db_path = None  # 走 env（conftest 已指向 tmp）
        reset_usage_history()
        UsageHistoryStore().record(
            ts="2026-09-02T08:00:00Z",
            usage_date="2026-09-02",
            user_id="u1",
            model="m",
            provider="p",
            prompt_tokens=10,
            completion_tokens=5,
        )
        # 未 reset 单例 → get 同实例；直接新建读同一 DB
        fresh = UsageHistoryStore()
        assert fresh.total()["tokens"] == 15


class TestAggregations:
    def _seed_two_days(self):
        store = _store()
        store.record(ts="2026-08-30T10:00:00Z", usage_date="2026-08-30", user_id="u1",
                     model="m1", provider="p", prompt_tokens=100, completion_tokens=0)
        store.record(ts="2026-08-30T11:00:00Z", usage_date="2026-08-30", user_id="u1",
                     model="m1", provider="p", prompt_tokens=50, completion_tokens=50)
        store.record(ts="2026-08-31T09:00:00Z", usage_date="2026-08-31", user_id="u1",
                     model="m2", provider="p", prompt_tokens=20, completion_tokens=10)

    def test_daily_totals_groups_by_date(self):
        self._seed_two_days()
        rows = _store().daily_totals()
        by_day = {r["usage_date"]: r for r in rows}
        assert by_day["2026-08-30"]["tokens"] == 200
        assert by_day["2026-08-30"]["calls"] == 2
        assert by_day["2026-08-31"]["tokens"] == 30
        assert by_day["2026-08-31"]["calls"] == 1

    def test_daily_by_model_groups_by_date_model(self):
        self._seed_two_days()
        rows = _store().daily_by_model()
        keyed = {(r["usage_date"], r["model"]): r["tokens"] for r in rows}
        assert keyed[("2026-08-30", "m1")] == 200
        assert keyed[("2026-08-31", "m2")] == 30

    def test_model_totals(self):
        self._seed_two_days()
        by_model = {m["model"]: m for m in _store().model_totals()}
        assert by_model["m1"]["tokens"] == 200
        assert by_model["m1"]["calls"] == 2
        assert by_model["m2"]["tokens"] == 30

    def test_peak_daily(self):
        self._seed_two_days()
        peak = _store().peak_daily()
        assert peak == {"usage_date": "2026-08-30", "tokens": 200}

    def test_peak_daily_empty_returns_none(self):
        assert _store().peak_daily() is None

    def test_user_filter_isolates(self):
        store = _store()
        store.record(ts="2026-08-30T10:00:00Z", usage_date="2026-08-30", user_id="u1",
                     model="m", provider="p", prompt_tokens=100, completion_tokens=0)
        store.record(ts="2026-08-30T11:00:00Z", usage_date="2026-08-30", user_id="u2",
                     model="m", provider="p", prompt_tokens=7, completion_tokens=3)
        assert _store().total(user_id="u1")["tokens"] == 100
        assert _store().total(user_id="u2")["tokens"] == 10
        assert _store().total()["tokens"] == 110  # 不过滤=全部


class TestRobustness:
    def test_record_with_bad_db_path_is_silent(self, monkeypatch, tmp_path):
        """DB 路径不可用（父级是文件，无法建目录）时 record 不抛（主流程零影响）。"""
        from pathlib import Path

        blocker = Path(tmp_path) / "blocker"
        blocker.write_text("", encoding="utf-8")  # 文件 → 后续 mkdir 必失败
        monkeypatch.setenv("NEUROVA_USAGE_HISTORY_DB", str(blocker / "usage.db"))
        reset_usage_history()
        store = _store()
        store.record(ts="2026-09-01T10:00:00Z", usage_date="2026-09-01", user_id="u1",
                     model="m", provider="p", prompt_tokens=1, completion_tokens=0)
        # 查询亦回退空
        assert store.total() == {"tokens": 0, "calls": 0}

    def test_persist_survives_singleton_reset(self):
        """持久化语义：reset 单例（模拟进程重启）后重建仍读同一 DB。"""
        store = _store()
        store.record(ts="2026-09-01T10:00:00Z", usage_date="2026-09-01", user_id="u1",
                     model="m", provider="p", prompt_tokens=1, completion_tokens=2)
        assert store.total()["tokens"] == 3
        reset_usage_history()
        assert _store().total()["tokens"] == 3


class TestComputeStreaks:
    def test_empty_set_returns_zero(self):
        assert compute_streaks([], date(2026, 9, 3)) == (0, 0)

    def test_single_day_is_one(self):
        assert compute_streaks(["2026-09-01"], date(2026, 9, 3)) == (0, 1)

    def test_streak_counting_today_active(self):
        days = ["2026-09-01", "2026-09-02", "2026-09-03"]
        assert compute_streaks(days, date(2026, 9, 3)) == (3, 3)

    def test_current_streak_rolls_back_to_yesterday(self):
        """今天未活跃：当前连续从昨天起算，最长含今天中断前的一段。"""
        days = ["2026-08-30", "2026-08-31", "2026-09-01", "2026-09-02"]
        assert compute_streaks(days, date(2026, 9, 3)) == (4, 4)

    def test_cross_month_and_gap(self):
        days = ["2026-07-31", "2026-08-01", "2026-08-03", "2026-08-04"]
        today = date(2026, 8, 5)
        # 今天未活跃 → 回退昨天（8-4 活跃）；当前连续 = 8-03/8-04 = 2；最长 = 2
        assert compute_streaks(days, today) == (2, 2)

    def test_unsorted_duplicates_tolerated(self):
        days = ["2026-09-02", "2026-09-01", "2026-09-02", "2026-09-03"]
        assert compute_streaks(days, date(2026, 9, 3)) == (3, 3)
