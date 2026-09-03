"""
/stats/usage-overview 端点契约测试（防回归）

锁定：GET /api/v1/stats/usage-overview 必须从 usage_history（SQLite 持久化）
返回 summary/heatmap/trends/by_model 四块契约，登录用户→user 口径、
匿名/无身份→global 口径，空库零态绝不 500。
"""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.api.endpoints import stats as stats_endpoint
from neurova.core.usage_history import get_usage_history, reset_usage_history


@pytest.fixture(autouse=True)
def _clean_history():
    reset_usage_history()
    yield
    reset_usage_history()


def _record(user_id: str, days_ago: int, tokens: int, model: str = "glm-5.3-flash", calls: int = 1):
    """按相对今天的天数落盘 usage_history（days_ago=0 今天，1 昨天…）。"""
    d = date.today() - timedelta(days=days_ago)
    store = get_usage_history()
    for _ in range(calls):
        store.record(
            ts=f"{d.isoformat()}T10:00:00Z",
            usage_date=d.isoformat(),
            user_id=user_id,
            model=model,
            provider="zhipu",
            prompt_tokens=tokens,
            completion_tokens=0,
        )


class TestEmptyState:
    @pytest.mark.asyncio
    async def test_no_records_returns_zero_state(self, monkeypatch):
        # 空态定义：无 token 历史且无会话（mock 掉真实会话目录）
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository",
            lambda: SimpleNamespace(list_sessions=lambda user_id="", agent_id="": []),
        )
        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=7, trend_days=7, current_user=None
        )
        assert res["scope"] == "global"
        assert res["summary"]["total_tokens"] == 0
        assert res["summary"]["total_calls"] == 0
        assert res["summary"]["peak_daily_tokens"] == 0
        assert res["summary"]["peak_daily_date"] is None
        assert res["summary"]["longest_session_seconds"] == 0
        assert res["summary"]["current_streak_days"] == 0
        assert res["summary"]["longest_streak_days"] == 0
        assert res["summary"]["active_days"] == 0
        assert len(res["heatmap"]) == 7
        assert all(h["tokens"] == 0 and h["calls"] == 0 for h in res["heatmap"])
        assert res["trends"] == []
        assert res["by_model"] == []


class TestContract:
    @pytest.mark.asyncio
    async def test_summary_heatmap_trends_by_model(self, monkeypatch):
        _record("u1", days_ago=0, tokens=100)
        _record("u1", days_ago=0, tokens=50, model="deepseek-v4")
        _record("u1", days_ago=1, tokens=30)

        # 空会话（不干扰 streak/时长断言）
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository",
            lambda: SimpleNamespace(list_sessions=lambda user_id="", agent_id="": []),
        )

        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=30, trend_days=7, current_user={"user_id": "u1"}
        )
        assert res["scope"] == "user"
        s = res["summary"]
        assert s["total_tokens"] == 180
        assert s["total_calls"] == 3
        assert s["peak_daily_tokens"] == 150
        assert s["peak_daily_date"] == date.today().isoformat()
        assert s["current_streak_days"] >= 1
        assert s["longest_streak_days"] >= 2
        assert s["active_days"] >= 1

        assert len(res["heatmap"]) == 30
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        hmap = {h["date"]: h for h in res["heatmap"]}
        assert hmap[today]["tokens"] == 150
        assert hmap[today]["calls"] == 2
        assert hmap[yesterday]["tokens"] == 30
        assert res["heatmap"][-1]["date"] == today  # 窗口以今天收尾，连续

        keyed = {(t["date"], t["model"]): t["tokens"] for t in res["trends"]}
        assert keyed[(today, "glm-5.3-flash")] == 100
        assert keyed[(today, "deepseek-v4")] == 50
        assert keyed[(yesterday, "glm-5.3-flash")] == 30

        by_model = {m["model"]: m for m in res["by_model"]}
        assert by_model["glm-5.3-flash"]["tokens"] == 130
        assert by_model["deepseek-v4"]["tokens"] == 50


class TestScope:
    @pytest.mark.asyncio
    async def test_user_scope_filters_by_user(self, monkeypatch):
        _record("u1", days_ago=0, tokens=100)
        _record("u2", days_ago=0, tokens=777)
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository",
            lambda: SimpleNamespace(list_sessions=lambda user_id="", agent_id="": []),
        )

        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=7, trend_days=7, current_user={"user_id": "u1"}
        )
        assert res["scope"] == "user"
        assert res["summary"]["total_tokens"] == 100

    @pytest.mark.asyncio
    async def test_global_scope_aggregates_all(self, monkeypatch):
        _record("u1", days_ago=0, tokens=100)
        _record("u2", days_ago=0, tokens=777)
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository",
            lambda: SimpleNamespace(list_sessions=lambda user_id="", agent_id="": []),
        )

        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=7, trend_days=7, current_user=None
        )
        assert res["scope"] == "global"
        assert res["summary"]["total_tokens"] == 877


class TestLongestSession:
    @pytest.mark.asyncio
    async def test_longest_session_seconds_from_sessions(self, monkeypatch):
        _record("u1", days_ago=0, tokens=10)
        sessions = [
            {
                "user_id": "u1",
                "created_at": "2026-09-01T10:00:00",
                "updated_at": "2026-09-01T10:05:00",  # 300s
            },
            {
                "user_id": "u1",
                "created_at": "2026-09-02T08:00:00",
                "updated_at": "2026-09-02T08:01:30",  # 90s
            },
            {
                "user_id": "u2",
                "created_at": "2026-09-02T08:00:00",
                "updated_at": "2026-09-02T09:00:00",  # 3600s（用户隔离下不可见）
            },
        ]
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository",
            lambda: SimpleNamespace(list_sessions=lambda user_id="", agent_id="": [s for s in sessions if not user_id or s["user_id"] == user_id]),
        )
        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=7, trend_days=7, current_user={"user_id": "u1"}
        )
        assert res["summary"]["longest_session_seconds"] == 300
