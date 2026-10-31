"""健康检查周期调度与 /health/detailed 缓存语义（交接文档 2026-10-31 §7）。

修前：`interval` 参数只存不用，检查只在请求时现场跑。
修后：lifespan 起周期任务按 interval 刷新缓存；/health/detailed 读缓存，
并显式回报 `cached`，冷启动无读数时现场跑一次并如实标 False。
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.app import AppState, _add_health_routes
from neurova.core.health_checker import HealthChecker, HealthStatus


@pytest.mark.asyncio
async def test_scheduler_populates_cache_without_any_request():
    checker = HealthChecker()
    calls = []

    def probe():
        calls.append(1)
        return True, "ok"

    checker.register("periodic", probe, interval=0.2)
    checker.startScheduler()
    try:
        for _ in range(100):
            if checker.get_check_result("periodic") is not None:
                break
            await asyncio.sleep(0.05)
        result = checker.get_check_result("periodic")
        assert result is not None, "周期任务未在 interval 内填充缓存"
        assert result.status == HealthStatus.HEALTHY
        assert calls, "检查函数必须真的被执行过"
    finally:
        checker.stopScheduler()


def _client(checker):
    app = FastAPI()
    state = AppState()
    state.health_checker = checker
    _add_health_routes(app, state)
    return TestClient(app)


def test_detailed_reads_cache_and_reports_freshness():
    checker = HealthChecker()
    calls = []

    def probe():
        calls.append(1)
        return True, "ok"

    checker.register("db", probe, interval=60)
    client = _client(checker)

    first = client.get("/health/detailed").json()
    assert first["cached"] is False, "冷启动没有读数时必须如实标未缓存"
    assert first["status"] == "healthy"
    assert len(calls) == 1

    second = client.get("/health/detailed").json()
    assert second["cached"] is True
    assert len(calls) == 1, "有缓存后请求不得再现场跑"


def test_detailed_without_checker_is_explicit():
    app = FastAPI()
    _add_health_routes(app, AppState())
    body = TestClient(app).get("/health/detailed").json()
    assert body["status"] == "unknown"
    assert body["cached"] is False
