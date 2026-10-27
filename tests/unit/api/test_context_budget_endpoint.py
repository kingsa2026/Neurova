"""GET /v1/context/budget（N6 只读常驻面预算）端点测试。"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import context as context_endpoint
from neurova.context.budget_report import (
    buildAlwaysOnBudgetReport,
    recordContextBudget,
    resetContextBudget,
)

MOCK_USER = {"user_id": "test_user", "username": "testuser", "role": "user"}


@pytest.fixture(autouse=True)
def _isolate_budget():
    resetContextBudget()
    yield
    resetContextBudget()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(context_endpoint.router, prefix="/v1/context")

    from neurova.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_budget_report_marks_over_segment_cap():
    report = buildAlwaysOnBudgetReport(
        {"skill_catalog": "x" * 9000, "tools": "y" * 10, "soul": "z" * 5}
    )
    assert report["total_chars"] == 9015
    assert report["over_segment_caps"] == ["skill_catalog"]
    assert report["segments"][0]["segment"] == "skill_catalog"
    assert report["segments"][0]["over_cap"] is True


def test_record_budget_logs_warning_without_changing_prompt(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        report = recordContextBudget("agent", {"skill_catalog": "x" * 9000})
    assert report["over_segment_caps"] == ["skill_catalog"]
    assert any("分段超预算" in record.message for record in caplog.records)


class TestContextBudgetEndpoint:
    def test_404_when_never_measured(self, client):
        assert client.get("/v1/context/budget").status_code == 404

    def test_200_after_measurement(self, client):
        recordContextBudget("default", {"soul": "s" * 100, "tools": "t" * 50})
        resp = client.get("/v1/context/budget")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "default"
        assert data["total_chars"] == 150
        assert data["over_budget"] is False
        assert {item["segment"] for item in data["segments"]} == {"soul", "tools"}

    def test_agent_scoped_query(self, client):
        recordContextBudget("agentK", {"soul": "k" * 9})
        assert client.get(
            "/v1/context/budget", params={"agent_id": "agentK"}
        ).json()["agent_id"] == "agentK"
        assert client.get(
            "/v1/context/budget", params={"agent_id": "other"}
        ).status_code == 404

    def test_requires_auth(self):
        from neurova.api.auth import get_current_user

        app = FastAPI()
        app.include_router(context_endpoint.router, prefix="/v1/context")
        with TestClient(app) as c:
            assert c.get("/v1/context/budget").status_code in (401, 403)
