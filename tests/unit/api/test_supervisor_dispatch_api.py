# -*- coding: utf-8 -*-
"""Supervisor 扇出端点：已注册 Worker → 任务扇出 + 聚合。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.agent.protocols.acp_runtime import ACPRuntime
from neurova.agent.supervisor import InProcessWorkerBus
from neurova.api.endpoints import acp_api


@pytest.fixture()
def api(monkeypatch):
    runtime = ACPRuntime()
    InProcessWorkerBus(runtime).register(
        "worker-a", lambda task: {"success": True, "items": [{"id": "d1", "score": 1.0}]}
    )
    monkeypatch.setattr(
        "neurova.agent.protocols.acp_runtime.get_acp_runtime", lambda: runtime
    )
    app = FastAPI()
    app.include_router(acp_api.router, prefix="/v1/acp")
    app.dependency_overrides[acp_api.get_current_user] = lambda: {"user_id": "u1", "role": "user"}
    return TestClient(app)


def testDispatchAggregatesRegisteredWorker(api):
    resp = api.post("/v1/acp/supervisor/dispatch", json={
        "tasks": [{"task_id": "t1", "worker_id": "worker-a", "payload": {"query": "alpha"}}],
    })

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["success"] is True
    assert data["tasks"][0]["success"] is True
    assert data["aggregate"][0]["id"] == "d1"
    assert data["trace_id"]

    replay = api.post("/v1/acp/supervisor/dispatch", json={
        "tasks": [{"task_id": "t1", "worker_id": "worker-a", "payload": {"query": "alpha"}}],
    })
    assert replay.status_code == 200
    assert replay.json()["data"]["tasks"][0]["replayed"] is True


def testEmptyTasks400(api):
    assert api.post("/v1/acp/supervisor/dispatch", json={"tasks": []}).status_code == 400
