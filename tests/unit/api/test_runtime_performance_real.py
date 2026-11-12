# -*- coding: utf-8 -*-
"""P2-2 runtime /performance 真指标验收（全库断点审计 2026-11-12）。

缺陷：/performance TODO 恒全零假指标（requests_per_second/average_response_time/
error_rate/cache_hit_rate 全 0）——前端 getPerformanceMetrics 拿到的永远是死数。

实装：从 core/metrics 的 HTTP 计数/时长直方图与缓存/连接池 gauge 聚合。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from neurova.api.endpoints import runtime as runtime_api
    from neurova.core.metrics import get_metrics

    get_metrics().http_requests_total._metrics.clear()
    get_metrics().http_request_seconds._metrics.clear()

    application = FastAPI()
    application.include_router(runtime_api.router, prefix="/v1/runtime")
    application.dependency_overrides[runtime_api.get_current_user] = lambda: {
        "user_id": "u1", "username": "u", "role": "admin", "neuser_id": "ne1",
    }
    return TestClient(application)


def test_performance_reports_real_numbers(client):
    from neurova.core.metrics import get_metrics

    metrics = get_metrics()
    metrics.record_http_request("GET", "/x", 200, 0.4)
    metrics.record_http_request("GET", "/x", 200, 0.6)
    metrics.record_http_request("GET", "/x", 500, 1.0)

    first = client.get("/v1/runtime/performance").json()
    assert first["average_response_time"] > 0, "平均响应时长必须来自真直方图"
    assert first["error_rate"] > 0, "5xx 错误率必须来自真计数"

    # 再来一次请求 → 与上次采样的差分给出非零 RPS
    metrics.record_http_request("GET", "/x", 200, 0.2)
    second = client.get("/v1/runtime/performance").json()
    assert second["requests_per_second"] > 0, "两次采样差分应给出非零 RPS"
    assert second["error_rate"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
