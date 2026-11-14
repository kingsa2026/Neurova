# -*- coding: utf-8 -*-
"""P2-2 runtime /performance 真指标验收（全库断点审计 2026-11-12）。

缺陷：/performance TODO 恒全零假指标（requests_per_second/average_response_time/
error_rate/cache_hit_rate 全 0）——前端 getPerformanceMetrics 拿到的永远是死数。

实装：从 core/metrics 的 HTTP 计数/时长直方图与缓存/连接池 gauge 聚合。

Flaky 改造（2026-11-14）：RPS 原依赖两次真实墙钟采样的差分，而 Windows 上
time.monotonic() = GetTickCount64()（实测分辨率 15.625ms，本机 20 万次连续读
只出 2 个值）。进程内 TestClient 两次采样常落入同一刻度 → now > previous[0]
不成立 → RPS 恒 0 → 断言偶发红（基线实测 10 跑 9 红）。现把 runtime 模块的
time 替换为可手动推进的时钟替身：采样间隔由测试显式 advance 确定，断言从
"> 0" 收紧为确定值——假零/假成功类回归仍被逐项咬住。
"""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _ManualClock:
    """runtime 模块 time 的替身：读取不推进，测试用 advance() 显式推钟。

    monotonic() 在同一次采样内幂等（同一时刻读数相同），两次采样的间隔由
    advance 精确控制——宿主墙钟分辨率（Windows 15.6ms）不再进入断言。
    其余属性透传真 time 模块，runtime 内其他取时点不受影响。
    """

    def __init__(self) -> None:
        self._now = 1_000_000.0

    def advance(self, seconds: float) -> None:
        self._now += float(seconds)

    def monotonic(self) -> float:
        return self._now

    def __getattr__(self, name: str):
        return getattr(time, name)


@pytest.fixture
def client():
    from neurova.api.endpoints import runtime as runtime_api
    from neurova.core.metrics import get_metrics

    get_metrics().http_requests_total._metrics.clear()
    get_metrics().http_request_seconds._metrics.clear()
    # 差分基线是 runtime 的模块级全局：跨用例残留会把"首样诚实零"变成随机读数，先归零
    runtime_api._perf_last_sample = None

    application = FastAPI()
    application.include_router(runtime_api.router, prefix="/v1/runtime")
    application.dependency_overrides[runtime_api.get_current_user] = lambda: {
        "user_id": "u1", "username": "u", "role": "admin", "neuser_id": "ne1",
    }
    return TestClient(application)


def test_performance_reports_real_numbers(client, monkeypatch):
    from neurova.api.endpoints import runtime as runtime_api
    from neurova.core.metrics import get_metrics

    clock = _ManualClock()
    # 注入口：runtime 以模块全局 `time.monotonic()` 取采样钟，测试期整体替换为可控钟
    monkeypatch.setattr(runtime_api, "time", clock)

    metrics = get_metrics()
    metrics.record_http_request("GET", "/x", 200, 0.4)
    metrics.record_http_request("GET", "/x", 200, 0.6)
    metrics.record_http_request("GET", "/x", 500, 1.0)

    first = client.get("/v1/runtime/performance").json()
    assert first["requests_per_second"] == 0.0, "首样无差分基线，必须诚实 0"
    assert first["average_response_time"] == pytest.approx(2 / 3, abs=1e-5), \
        "平均响应时长必须来自真直方图 (0.4+0.6+1.0)/3"
    assert first["error_rate"] == pytest.approx(1 / 3, abs=1e-3), "5xx 错误率必须来自真计数 1/3"

    # 钟精确推 0.5s 后再采样：恰 1 个新请求 → RPS 确定等于 1/0.5 = 2.0
    clock.advance(0.5)
    metrics.record_http_request("GET", "/x", 200, 0.2)
    second = client.get("/v1/runtime/performance").json()
    assert second["requests_per_second"] == pytest.approx(2.0), "差分 (4-3)/0.5s 必须给出确定 RPS"
    assert second["average_response_time"] == pytest.approx(0.55), "累计 (2.0+0.2)/4 必须等于 0.55"
    assert second["error_rate"] == pytest.approx(0.25), "累计 1 个 5xx / 4 个请求 = 0.25"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
