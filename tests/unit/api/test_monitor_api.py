"""
TDD Red: /monitor 数据为空 —— 契约错位 + stub 端点修复

背景(2026-09-03): MonitorPage 调 /monitor/resources|connections|alerts:
- resources: 前端取 cpu.usage 等嵌套字段, 后端返扁平 cpu_percent → 恒 0%
- connections: 后端 stub 恒返 0 计数对象, 前端期望数组 → 恒空
- alerts: 后端 TODO 恒返 [], 前端期望 {id,severity,message,resolved} → 恒空

契约(修复后):
- /resources → {cpu:{usage,trend,history}, memory:{...}, disk:{...}} (psutil 真值)
- /connections → [{name,detail,status}] (providers/agents/db 真状态汇总)
- /alerts → [{id,severity,message,source,timestamp,resolved}] (ExecutionMonitor 真实告警)
- /alerts/{id}/resolve → acknowledge_alert (404 当不存在)
- 全部 require_admin(与前端 gate 一致)

当前实现全部失败(字段错位/stub/无 monitor 接线)。
"""
import os
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.monitor import router
from neurova.api.deps import get_current_user
from neurova.execution_engine.execution_monitor import AlertLevel, ExecutionMonitor

BASE = "/api/v1/monitor"

ADMIN = {"user_id": "a9", "username": "admin", "role": "admin", "neuser_id": "a9"}
USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}


class FakeMonitor:
    """真实 ExecutionMonitor 的最小替身: 只有 get_alerts/acknowledge_alert 真读告警"""


@pytest.fixture
def engine_stub():
    engine = MagicMock()
    engine._execution_monitor = ExecutionMonitor()
    engine.get_execution_monitor.return_value = engine._execution_monitor
    return engine


@pytest.fixture
def app_client(engine_stub):
    app = FastAPI()

    class _FakeState:
        agents = {"default": MagicMock(), "kai": MagicMock()}

    with (
        patch("neurova.shared_core.execution_engine.get_execution_engine", return_value=engine_stub),
        patch("neurova.api.endpoints.monitor.get_app_state", return_value=_FakeState()),
        patch("neurova.llm.provider_manager.get_provider_manager") as pm,
    ):
        manager = MagicMock()
        healthy = MagicMock()
        healthy.id = "openai"
        healthy.enabled = True
        healthy.health_status = "healthy"
        degraded = MagicMock()
        degraded.id = "sensetime"
        degraded.enabled = True
        degraded.health_status = "unhealthy"
        manager.list_providers.return_value = [healthy, degraded]
        pm.return_value = manager

        app.include_router(router, prefix=BASE)
        app.dependency_overrides[get_current_user] = lambda: ADMIN
        yield TestClient(app), engine_stub


def _auth(client, user):
    client.app.dependency_overrides[get_current_user] = lambda: user


class TestAlertsContract:
    def test_alerts_mapped_from_execution_monitor(self, app_client):
        client, engine = app_client
        alert = engine._execution_monitor.create_alert(
            AlertLevel.WARNING, "DB slow", "responses took 2s", source="db"
        )
        resp = client.get(f"{BASE}/alerts")
        assert resp.status_code == 200, resp.text
        items = resp.json()
        assert isinstance(items, list) and len(items) == 1
        a = items[0]
        assert a["id"] == alert.alert_id
        assert a["severity"] == "warning"
        assert a["message"] == "responses took 2s"
        assert a["source"] == "db"
        assert a["resolved"] is False

    def test_alerts_empty_when_no_monitor(self, app_client):
        client, engine = app_client
        engine._execution_monitor = None
        resp = client.get(f"{BASE}/alerts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_resolve_acknowledges_alert(self, app_client):
        client, engine = app_client
        alert = engine._execution_monitor.create_alert(AlertLevel.ERROR, "boom", "oops")
        resp = client.post(f"{BASE}/alerts/{alert.alert_id}/resolve")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        acked = engine._execution_monitor.get_alerts(acknowledged=True)
        assert acked and acked[-1].alert_id == alert.alert_id

    def test_resolve_unknown_alert_404(self, app_client):
        client, _ = app_client
        resp = client.post(f"{BASE}/alerts/no-such-id/resolve")
        assert resp.status_code == 404

    def test_non_admin_403(self, app_client):
        client, _ = app_client
        _auth(client, USER)
        assert client.get(f"{BASE}/alerts").status_code == 403
        assert client.get(f"{BASE}/connections").status_code == 403
        assert client.get(f"{BASE}/resources").status_code == 403


class TestResourcesContract:
    def test_resources_nested_with_history(self, app_client, monkeypatch):
        client, _ = app_client

        class FakePsutil:
            @staticmethod
            def cpu_percent():
                return 42.5

            @staticmethod
            def virtual_memory():
                return MagicMock(percent=55.0, used=5_500, total=10_000)

            @staticmethod
            def disk_usage(path):
                return MagicMock(percent=63.0, used=6_300, total=10_000)

        monkeypatch.setattr("neurova.api.endpoints.monitor.psutil", FakePsutil)
        resp = client.get(f"{BASE}/resources")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["cpu"]["usage"] == 42.5
        assert data["memory"]["usage"] == 55.0
        assert data["memory"]["total"] == 10_000
        assert data["disk"]["usage"] == 63.0
        assert isinstance(data["cpu"]["history"], list)


class TestConnectionsContract:
    def test_connections_from_real_sources(self, app_client):
        client, _ = app_client
        resp = client.get(f"{BASE}/connections")
        assert resp.status_code == 200, resp.text
        items = resp.json()
        by_name = {i["name"]: i for i in items}
        assert by_name["LLM Providers"]["detail"] == "1/2 healthy"
        assert by_name["Agent Runtime"]["detail"] == "2 agents"
        for item in items:
            assert item["status"] in ("connected", "degraded")
