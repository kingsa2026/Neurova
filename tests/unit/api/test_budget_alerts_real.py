# -*- coding: utf-8 -*-
"""P2-8 budget /alerts 真数据红测（全库断点审计 2026-11-12）。

缺陷：/alerts 恒回空占位（TODO "Query alerts from database"）——告警触发
（_send_alert）从未落任何历史，前端/调用方拿不到真实告警。

修复口径（审计开方"接真查询"）：BudgetManager 触发告警时落有界历史
（deque maxlen=200），/alerts 从历史读真数。
"""
import datetime as dt
from decimal import Decimal

import pytest


@pytest.fixture
def manager():
    from neurova.models.cost_budget import BudgetManager, BudgetConfig, BudgetScope

    mgr = BudgetManager()
    now = dt.datetime.now()
    mgr.register_budget(
        BudgetConfig(
            scope=BudgetScope.AGENT,
            identifier="agent_alert",
            amount=Decimal("100"),
            period_start=now - dt.timedelta(hours=1),
            period_end=now + dt.timedelta(hours=1),
        )
    )
    return mgr


def test_triggered_alerts_enter_history(manager):
    from neurova.models.cost_budget import BudgetScope

    # 60% 用量 → 越过 INFO(50%) 阈值，告警必须落历史
    manager.record_usage(BudgetScope.AGENT, "agent_alert", 60)
    history = manager.get_alert_history(limit=10)
    assert history, "越线告警必须进历史（P2-8）"
    assert history[0]["identifier"] == "agent_alert"
    assert history[0]["level"] == "info"
    assert history[0]["percentage"] == pytest.approx(60.0)


def test_alert_history_is_bounded_and_newest_first(manager):
    from neurova.models.cost_budget import BudgetScope

    for i in range(250):
        manager.record_usage(BudgetScope.AGENT, "agent_alert", 0.1)
    history = manager.get_alert_history(limit=500)
    assert len(history) <= 200, "告警历史必须有界"
    stamps = [h["timestamp"] for h in history]
    assert stamps == sorted(stamps, reverse=True), "历史必须新→旧"


def test_alerts_endpoint_serves_real_history(manager):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace

    from neurova.api.endpoints import budget_api
    from neurova.models.cost_budget import BudgetScope

    manager.record_usage(BudgetScope.AGENT, "agent_alert", 60)

    application = FastAPI()
    application.include_router(budget_api.router)
    application.dependency_overrides[budget_api.get_current_user] = lambda: {
        "user_id": "u1", "username": "u", "role": "admin", "neuser_id": "ne1",
    }
    application.dependency_overrides[budget_api.get_budget_service] = lambda: SimpleNamespace(
        manager=manager
    )
    client = TestClient(application)
    resp = client.get("/budgets/alerts", params={"limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["alerts"], "/alerts 必须返回真实告警历史（P2-8）"
    assert body["alerts"][0]["identifier"] == "agent_alert"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
