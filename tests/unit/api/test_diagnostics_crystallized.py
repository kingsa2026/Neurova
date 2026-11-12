# -*- coding: utf-8 -*-
"""P2-16 结晶经验管理器只读诊断面红测（全库断点审计 2026-11-12）。

缺陷：CrystallizedExperienceManager 的 observe/get_health/add_failure_callback/
clear_cache 全仓零消费、_metrics 只写不读——健康度/失败回调/缓存清空承诺
不可达。拍板：补只读诊断口（admin 门）。
"""
import os

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_for_diagnostics_0123456789")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_for_diagnostics_0123456789")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_agent():
    from neurova.agent.crystallized_experience_manager import (
        CrystallizedExperienceManager,
    )
    from neurova.api.endpoints import set_app_state

    class FakePipeline:
        pass

    class FakeAgent:
        pass

    pipeline = FakePipeline()
    pipeline._crystallized_experience_manager = CrystallizedExperienceManager(
        agent_id="agent_d1", user_id="u1"
    )
    agent = FakeAgent()
    agent.chat_pipeline = pipeline

    set_app_state({"agents": {"agent_d1": agent}})
    yield
    set_app_state(None)


@pytest.fixture
def app_pair(app_with_agent):
    from neurova.api.endpoints import crystallized_health_api as diagnostics_api
    from neurova.api.auth import get_current_user

    application = FastAPI()
    application.include_router(diagnostics_api.router, prefix="/v1")
    return application, get_current_user


def test_diagnostics_requires_admin(app_pair):
    application, get_current_user = app_pair
    application.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1", "username": "u", "role": "user", "neuser_id": "ne1",
    }
    resp = TestClient(application).get("/v1/diagnostics/crystallized")
    assert resp.status_code == 403, "诊断面是 admin 门（普通用户 403）"


def test_diagnostics_reports_health_and_metrics(app_pair):
    application, get_current_user = app_pair
    application.dependency_overrides[get_current_user] = lambda: {
        "user_id": "admin1", "username": "admin", "role": "admin", "neuser_id": "ne_admin",
    }
    resp = TestClient(application).get("/v1/diagnostics/crystallized")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    entry = data["agents"][0]
    assert entry["agent_id"] == "agent_d1"
    assert entry["health"] == "healthy"
    assert entry["metrics"]["total_attempts"] == 0


def test_diagnostics_anon_401(app_with_agent):
    from neurova.api.endpoints import crystallized_health_api as diagnostics_api

    application = FastAPI()
    application.include_router(diagnostics_api.router, prefix="/v1")
    resp = TestClient(application).get("/v1/diagnostics/crystallized")
    assert resp.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
