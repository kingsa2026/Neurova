"""R8+R9 成本读数出街 —— 红灯测试。

§10.2 R8/R9：成本此前只有进程级快照（usage_accounting）与按天/按 agent 的
token 读数；缺「按用户/模型聚合的成本单」与出街端点。本文件钉：

1. TokenUsageAccounting.estimate_cost_for：定价目录估算（未知模型 0，不伪造）；
2. usage_history.per_user_cost_totals：按用户×模型聚合 token 并估成本
   （tmp 库；成本是定价目录估算值，与 total_cost 同一目录同一口径）；
3. /analytics/cost-readout：进程级 + 按用户成本读数出街（登录即可读）。
"""

import pytest

from neurova.core.usage_accounting import (
    TokenUsageAccounting,
    get_usage_accounting,
    reset_usage_accounting,
)
from neurova.core.usage_history import UsageHistoryStore


def _store(tmp_path):
    return UsageHistoryStore(db_path=str(tmp_path / "usage.db"))


class TestEstimateCostFor:
    def test_known_model_uses_pricing(self):
        # gpt-4o：prompt 2.5e-6 / completion 1e-5（$/token）
        cost = TokenUsageAccounting.estimate_cost_for("gpt-4o", 1000, 100)
        assert cost == pytest.approx(1000 * 2.5e-6 + 100 * 1e-5)

    def test_unknown_model_is_zero_not_fabricated(self):
        assert TokenUsageAccounting.estimate_cost_for("no-such-model", 1000, 100) == 0.0


class TestPerUserCostTotals:
    def test_groups_by_user_and_model_with_cost(self, tmp_path):
        store = _store(tmp_path)
        store.record(model="gpt-4o", provider="p", prompt_tokens=1000,
                     completion_tokens=100, user_id="u1")
        store.record(model="gpt-4o", provider="p", prompt_tokens=2000,
                     completion_tokens=200, user_id="u1")
        store.record(model="deepseek-chat", provider="p", prompt_tokens=1000,
                     completion_tokens=100, user_id="u2")
        rows = store.per_user_cost_totals()
        assert len(rows) == 2
        u1 = next(r for r in rows if r["user_id"] == "u1")
        assert u1["tokens"] == 3300
        assert u1["calls"] == 2
        assert u1["cost_usd"] == pytest.approx(3000 * 2.5e-6 + 300 * 1e-5, rel=1e-4)
        assert u1["by_model"][0]["model"] == "gpt-4o"
        u2 = next(r for r in rows if r["user_id"] == "u2")
        # deepseek-chat 1.4e-7 / 2.8e-7
        assert u2["cost_usd"] == pytest.approx(1000 * 1.4e-7 + 100 * 2.8e-7, rel=1e-4)

    def test_user_filter(self, tmp_path):
        store = _store(tmp_path)
        store.record(model="gpt-4o", provider="p", prompt_tokens=1000,
                     completion_tokens=0, user_id="u1")
        store.record(model="gpt-4o", provider="p", prompt_tokens=3000,
                     completion_tokens=0, user_id="u2")
        rows = store.per_user_cost_totals(user_id="u2")
        assert len(rows) == 1 and rows[0]["user_id"] == "u2"
        assert rows[0]["tokens"] == 3000

    def test_empty_db_empty_rows(self, tmp_path):
        assert _store(tmp_path).per_user_cost_totals() == []


# ── R9：analytics 出街端点 ───────────────────────────────────────

class TestCostReadoutEndpoint:
    @pytest.mark.asyncio
    async def test_endpoint_returns_process_and_per_user(self, monkeypatch, tmp_path):
        import pathlib

        from neurova.api.endpoints import analytics

        reset_usage_accounting()
        acc = get_usage_accounting()
        acc.record(model="gpt-4o", provider="p", prompt_tokens=500,
                   completion_tokens=50)
        store = _store(pathlib.Path(tmp_path))
        store.record(model="gpt-4o", provider="p", prompt_tokens=1000,
                     completion_tokens=100, user_id="u1")
        monkeypatch.setattr(
            __import__("neurova.core.usage_history", fromlist=["get_usage_history"]),
            "get_usage_history", lambda: store)

        response = await analytics.get_cost_readout(current_user={"user_id": "u"})
        data = response["data"]
        assert data["process"]["total_tokens"] == 550
        assert data["process"]["estimated_cost_usd"] > 0
        assert data["by_user"][0]["user_id"] == "u1"
        assert data["by_user"][0]["cost_usd"] > 0
