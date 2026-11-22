"""
服务商真实流量分布（D-R2 收尾观测项）契约测试。

锁定三件事：
1. UsageHistoryStore.provider_totals()：按 provider 聚合 calls/tokens，
   空串 provider 不计（无主流量不冒充分布），user_id 过滤生效；
2. GET /stats/usage-overview 的 by_provider 段：按 tokens 降序、
   share = tokens 占比（百分比一位小数；总数 0 → 诚实记 0），
   与 by_model 同源同窗（同一 usage_history）；
3. 空库零态：by_provider == []，绝不 500。
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


def _record(user_id: str, provider: str, tokens: int, calls: int = 1):
    d = date.today() - timedelta(days=1)
    store = get_usage_history()
    for _ in range(calls):
        store.record(
            ts=f"{d.isoformat()}T10:00:00Z",
            usage_date=d.isoformat(),
            user_id=user_id,
            model="sample-flash-model",
            provider=provider,
            prompt_tokens=tokens,
            completion_tokens=0,
        )


class TestProviderTotals:
    def test_groups_by_provider_and_excludes_empty(self):
        store = get_usage_history()
        _record("u1", "wa", 100, calls=2)   # 200
        _record("u1", "wb", 50, calls=1)    # 50
        _record("u1", "", 999, calls=1)     # 空 provider：无主流量不进分布
        rows = store.provider_totals()
        assert rows == [
            {"provider": "wa", "calls": 2, "tokens": 200},
            {"provider": "wb", "calls": 1, "tokens": 50},
        ]

    def test_user_filter(self):
        _record("u1", "wa", 100)
        _record("u2", "wb", 300)
        rows = get_usage_history().provider_totals(user_id="u1")
        assert rows == [{"provider": "wa", "calls": 1, "tokens": 100}]

    def test_empty_store_returns_empty(self):
        assert get_usage_history().provider_totals() == []


class TestOverviewByProvider:
    @pytest.mark.asyncio
    async def test_by_provider_sorted_with_share(self, monkeypatch):
        _record("u1", "wa", 100, calls=2)   # 200 → 80.0%
        _record("u1", "wb", 50, calls=1)    # 50 → 20.0%
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository",
            lambda: SimpleNamespace(list_sessions=lambda user_id="", agent_id="": []),
        )
        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=7, trend_days=7, current_user=None
        )
        assert res["by_provider"] == [
            {"provider": "wa", "calls": 2, "tokens": 200, "share": 80.0},
            {"provider": "wb", "calls": 1, "tokens": 50, "share": 20.0},
        ]

    @pytest.mark.asyncio
    async def test_by_provider_user_scope(self, monkeypatch):
        _record("u1", "wa", 100)
        _record("u2", "wb", 300)
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository",
            lambda: SimpleNamespace(list_sessions=lambda user_id="", agent_id="": []),
        )
        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=7, trend_days=7,
            current_user={"user_id": "u1", "role": "user"},
        )
        assert res["scope"] == "user"
        assert res["by_provider"] == [
            {"provider": "wa", "calls": 1, "tokens": 100, "share": 100.0},
        ]

    @pytest.mark.asyncio
    async def test_empty_state_by_provider_empty(self, monkeypatch):
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository",
            lambda: SimpleNamespace(list_sessions=lambda user_id="", agent_id="": []),
        )
        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=7, trend_days=7, current_user=None
        )
        assert res["by_provider"] == []
