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
