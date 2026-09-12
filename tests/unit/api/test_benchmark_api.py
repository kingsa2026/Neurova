# -*- coding: utf-8 -*-
"""benchmark API 契约锁：POST /run 的 agent_id 必填（Agent 层隔离）。

实测事故（2026-09-03）：前端 BenchmarkPage 只发 {suite_id} → Pydantic 422
(Unprocessable Entity)。本测试锁定后端契约真相：agent_id 必填缺省 422；
提供后运行按 agent 记录并可通过 /runs 查回 —— 前端侧修复应为发全字段，
而非后端放宽必填校验（否则 Agent 层隔离徒有虚名）。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client():
    from neurova.api.endpoints import benchmark as benchmark_api

    app = FastAPI()
    app.include_router(benchmark_api.router, prefix="/api/v1/benchmark")
    # P0-5（审计 2026-09-11）：router 级鉴权后的测试身份注入
    from neurova.api.auth import get_current_user as _gcu

    app.dependency_overrides[_gcu] = lambda: {
        "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
    }
    return TestClient(app)


def test_run_requires_agent_id():
    """锁契约：agent_id 必填 —— 缺它返回 422，而非静默默认"""
    client = _make_client()
    resp = client.post("/api/v1/benchmark/run", json={"suite_id": "reasoning-v1"})
    assert resp.status_code == 422
    assert "agent_id" in resp.text


def test_run_with_agent_id_records_run():
    """带 agent_id 运行成功，且按 agent 记录落库，/runs 可查回"""
    client = _make_client()
    resp = client.post(
        "/api/v1/benchmark/run",
        json={"suite_id": "reasoning-v1", "agent_id": "default"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["agent_id"] == "default"
    assert body["data"]["suite_id"] == "reasoning-v1"
    run_id = body["data"]["run_id"]

    runs = client.get("/api/v1/benchmark/runs").json()
    assert runs["code"] == 0
    assert runs["data"]["items"][0]["run_id"] == run_id


def test_run_unknown_suite_404():
    client = _make_client()
    resp = client.post(
        "/api/v1/benchmark/run",
        json={"suite_id": "no-such-suite", "agent_id": "default"},
    )
    assert resp.status_code == 404


# ── P6 诚实化（2026-09-12）：/run 原用 random.randint 伪造分数 ──


def test_run_is_marked_simulated_and_has_no_fabricated_score():
    client = _make_client()
    resp = client.post("/api/v1/benchmark/run", json={"suite_id": "reasoning-v1", "agent_id": "default"})
    assert resp.status_code == 200
    run = resp.json()["data"]
    assert run["simulated"] is True, "模拟运行必须如实标注"
    assert run["status"] == "simulated"
    # 不得再出现 random 伪造的具体分数/延迟
    assert run["score"] is None
    assert run["avg_latency_ms"] is None
    assert run["tasks_correct"] is None
