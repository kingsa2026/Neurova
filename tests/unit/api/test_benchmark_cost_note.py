# -*- coding: utf-8 -*-
"""E1 成本标注透传：POST /run 接受可选 cost_note 并落运行记录（含真执行回写）。

D-H 口径：评测手动跑+成本标注。suite_eval.runSuite 已支持 costNote 落报告；
本组测试钉住端点侧链路——请求体可选 cost_note → 运行记录（simulated 立即
落 / 真执行由后台线程回写）→ GET /runs/{id} 可查。缺省不传时记录不含该键。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client():
    from neurova.api.endpoints import benchmark as benchmark_api

    app = FastAPI()
    app.include_router(benchmark_api.router, prefix="/api/v1/benchmark")
    from neurova.api.auth import get_current_user as _gcu

    app.dependency_overrides[_gcu] = lambda: {
        "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
    }
    return TestClient(app), benchmark_api


def test_simulated_run_carries_cost_note():
    client, _ = _make_client()
    resp = client.post("/api/v1/benchmark/run", json={
        "suite_id": "reasoning-v1", "agent_id": "default",
        "config": {"simulated": True},
        "cost_note": {"model": "manual", "est_tokens": 1200},
    })
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["cost_note"] == {"model": "manual", "est_tokens": 1200}
    got = client.get(f"/api/v1/benchmark/runs/{data['run_id']}").json()
    record = got.get("data") or got
    assert record["cost_note"] == {"model": "manual", "est_tokens": 1200}


def test_run_without_cost_note_omits_key():
    client, _ = _make_client()
    resp = client.post("/api/v1/benchmark/run", json={
        "suite_id": "reasoning-v1", "agent_id": "default",
        "config": {"simulated": True},
    })
    assert resp.status_code == 200
    assert "cost_note" not in resp.json()["data"], "缺省不传不落键（契约：新增可选）"


def test_real_execution_writes_back_cost_note():
    client, benchmark_api = _make_client()
    benchmark_api._RUNS_STORE["t-cost-1"] = {
        "run_id": "t-cost-1", "suite_id": "reasoning-v1", "status": "running",
    }
    benchmark_api._executeBenchmarkRun(
        "t-cost-1", "reasoning-v1", lambda prompt: "答案", None,
        cost_note={"model": "manual", "est_tokens": 5},
    )
    record = benchmark_api._RUNS_STORE["t-cost-1"]
    assert record["status"] == "completed"
    assert record["cost_note"] == {"model": "manual", "est_tokens": 5}
