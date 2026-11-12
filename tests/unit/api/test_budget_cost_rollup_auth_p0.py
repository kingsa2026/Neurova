"""P1-1 budget/cost_rollup 十五端点零鉴权红测（全库断点审计 2026-11-12）

证据（审计 P1-1，本文件红灯实证）：
- budget_api.py:15 / cost_rollup_api.py:20 两 router 裸挂，无任何鉴权依赖，
  两文件 get_current_user 零命中；
- 匿名可读全部成本/预算，POST /budgets/record 可伪造成本记录污染预算判定，
  POST /cost-rollup/rollup/now 可匿名强制跑重聚合。

修复口径（审计开方，红灯钉住后实施）：
- 两 router 级挂 get_current_user；
- rollup/now、rollup/range、alerts/config/update、budgets/record 四个写面收 admin。

测试基建：budget/rollup 服务一律替身（本文件只测鉴权门，不测 handler 业务）；
require_admin 的角色门内嵌 strictIdentityGate = get_current_user 本体
（deps.py:39 别名），override 一个函数对象即路由级与角色门双门齐打。
"""

import os

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_for_p1-1_budget_cost_auth")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_for_p1-1_budget_cost_auth")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user
from neurova.api.endpoints import budget_api, cost_rollup_api
from neurova.models.cost_budget import AlertLevel


class FakeBudgetService:
    """鉴权替身：handler 走通即可，不落真库"""

    def __init__(self):
        self.recorded = []
        self._initialized = True
        alert_config = type(
            "AlertConfig",
            (),
            {
                "level": AlertLevel.WARNING,
                "enabled": True,
                "channels": [],
                "message_template": None,
            },
        )()
        self.manager = type(
            "Manager", (), {"_budgets": {}, "_alert_configs": [alert_config]}
        )()

    def get_agent_budget_status(self, agent_id):
        return {"agent_id": agent_id}

    def get_all_budget_statuses(self):
        return {}

    def record_llm_call_cost(self, **kwargs):
        self.recorded.append(kwargs)


class FakeRollupManager:
    def __init__(self):
        self.status = {"store_ready": True}

    def run_rollup(self):
        return 0

    def force_rollup_for_range(self, start_time, end_time):
        return 0


@pytest.fixture
def fake_budget():
    return FakeBudgetService()


@pytest.fixture
def fake_rollup():
    return FakeRollupManager()


@pytest.fixture
def app(fake_budget, fake_rollup, monkeypatch):
    application = FastAPI()
    application.include_router(budget_api.router)
    application.include_router(cost_rollup_api.router)
    application.dependency_overrides[budget_api.get_budget_service] = lambda: fake_budget
    monkeypatch.setattr(cost_rollup_api, "get_rollup_manager", lambda: fake_rollup)
    return application


def _client(app, role=None):
    if role is not None:
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": f"u_{role}",
            "username": f"user_{role}",
            "role": role,
            "neuser_id": f"ne_{role}",
        }
    return TestClient(app)


RECORD_PARAMS = {
    "agent_id": "agent_x",
    "provider": "p",
    "model": "m",
    "cost": 1.0,
}
RANGE_PARAMS = {
    "start_time": "2026-11-01T00:00:00",
    "end_time": "2026-11-02T00:00:00",
}
ALERT_BODY = {"level": "warning", "enabled": False}


# ── 1. 匿名一律 401（红态：读面 200、写面穿透到 handler） ──────────


class TestAnonymousDenied:
    def test_anon_read_budget_alerts_401(self, app):
        assert _client(app).get("/budgets/alerts").status_code == 401

    def test_anon_read_budget_health_401(self, app):
        assert _client(app).get("/budgets/health").status_code == 401

    def test_anon_write_budget_record_401(self, app):
        resp = _client(app).post("/budgets/record", params=RECORD_PARAMS)
        assert resp.status_code == 401

    def test_anon_write_alert_config_401(self, app):
        resp = _client(app).post("/budgets/alerts/config/update", json=ALERT_BODY)
        assert resp.status_code == 401

    def test_anon_read_rollup_queries_401(self, app):
        assert _client(app).get("/cost-rollup/queries/daily_cost_by_agent").status_code == 401

    def test_anon_read_rollup_status_401(self, app):
        assert _client(app).get("/cost-rollup/rollup/status").status_code == 401

    def test_anon_trigger_rollup_now_401(self, app):
        assert _client(app).post("/cost-rollup/rollup/now").status_code == 401

    def test_anon_trigger_rollup_range_401(self, app):
        resp = _client(app).post("/cost-rollup/rollup/range", params=RANGE_PARAMS)
        assert resp.status_code == 401


# ── 2. 四个写面收 admin：普通登录用户 403（红态：穿透成功 200） ────


class TestWriteFacesAdminOnly:
    def test_user_role_budget_record_403(self, app, fake_budget):
        resp = _client(app, "user").post("/budgets/record", params=RECORD_PARAMS)
        assert resp.status_code == 403
        assert fake_budget.recorded == []

    def test_user_role_alert_config_403(self, app):
        resp = _client(app, "user").post("/budgets/alerts/config/update", json=ALERT_BODY)
        assert resp.status_code == 403

    def test_user_role_rollup_now_403(self, app):
        assert _client(app, "user").post("/cost-rollup/rollup/now").status_code == 403

    def test_user_role_rollup_range_403(self, app):
        resp = _client(app, "user").post("/cost-rollup/rollup/range", params=RANGE_PARAMS)
        assert resp.status_code == 403


# ── 3. admin 四写面照常可用（门不误伤） ───────────────────────────


class TestAdminPasses:
    def test_admin_budget_record_200(self, app, fake_budget):
        resp = _client(app, "admin").post("/budgets/record", params=RECORD_PARAMS)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert len(fake_budget.recorded) == 1

    def test_admin_alert_config_200(self, app):
        resp = _client(app, "admin").post("/budgets/alerts/config/update", json=ALERT_BODY)
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_admin_rollup_now_200(self, app):
        resp = _client(app, "admin").post("/cost-rollup/rollup/now")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_admin_rollup_range_200(self, app):
        resp = _client(app, "admin").post("/cost-rollup/rollup/range", params=RANGE_PARAMS)
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── 4. 读面保持登录即可：普通用户不被过度收权 ─────────────────────


class TestReadFacesAuthenticated:
    def test_user_read_budget_alerts_200(self, app):
        assert _client(app, "user").get("/budgets/alerts").status_code == 200

    def test_user_read_rollup_queries_200(self, app):
        resp = _client(app, "user").get("/cost-rollup/queries/daily_cost_by_agent")
        assert resp.status_code == 200
        assert resp.json()["name"] == "daily_cost_by_agent"

    def test_user_read_rollup_status_200(self, app):
        assert _client(app, "user").get("/cost-rollup/rollup/status").status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
