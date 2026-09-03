"""
调度器 API 鉴权 + 立即运行 测试（2026-08-31 遗留修复）

契约:
1. 全部端点(/status /tasks CRUD /run) 未认证 401;
2. 认证后: 创建任务 200(cron_expression/parameters 契约)、run 端点
   触发执行(有 handler 时 completed; 无 handler failed)、未知任务 404。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api import endpoints as ep
from neurova.api.endpoints import scheduler as scheduler_ep
from neurova.api.deps import get_current_user
from neurova.collaborate.workflow.scheduler import AgentScheduler


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_SCHEDULER_STORE", str(tmp_path / "sched.json"))
    AgentScheduler._instance = None
    app = FastAPI()
    app.include_router(scheduler_ep.router, prefix="/api/v1/scheduler")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield app, c
    AgentScheduler._instance = None


def _auth(c):
    c.app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1", "username": "user1", "role": "user",
    }


class TestAuth:
    @pytest.mark.parametrize(
        "method,path,json",
        [
            ("get", "/api/v1/scheduler/status", None),
            ("get", "/api/v1/scheduler/tasks", None),
            ("post", "/api/v1/scheduler/tasks", {"name": "t", "action": "send_message"}),
            ("post", "/api/v1/scheduler/tasks/t-1/run", None),
            ("delete", "/api/v1/scheduler/tasks/t-1", None),
        ],
    )
    def test_unauthorized_401(self, client, method, path, json):
        app, c = client
        r = getattr(c, method)(path, json=json) if json is not None else getattr(c, method)(path)
        assert r.status_code == 401, (method, path, r.text[:120])


class TestRunNow:
    def test_create_and_run_now(self, client):
        app, c = client
        _auth(c)
        r = c.post("/api/v1/scheduler/tasks", json={
            "name": "run-now", "action": "no_such_action",
            "cron_expression": "0 9 * * *", "agent_id": "default", "parameters": {"message": "hi"},
        })
        assert r.status_code == 200, r.text[:160]
        task_id = r.json()["task_id"]
        # 立即执行(无 handler → failed; 至少证明触发链路工作)
        r2 = c.post(f"/api/v1/scheduler/tasks/{task_id}/run")
        assert r2.status_code == 200, r2.text[:160]
        assert r2.json()["data"]["status"] == "failed"

    def test_run_now_task_not_found(self, client):
        app, c = client
        _auth(c)
        r = c.post("/api/v1/scheduler/tasks/does-not-exist/run")
        assert r.status_code == 404

    def test_create_contract_fields_saved(self, client):
        app, c = client
        _auth(c)
        r = c.post("/api/v1/scheduler/tasks", json={
            "name": "contract", "action": "send_message",
            "cron_expression": "0 9 * * 0,2,4", "agent_id": "default",
            "parameters": {"message": "hello"},
        })
        assert r.status_code == 200
        d = r.json()
        assert d["cron_expression"] == "0 9 * * 0,2,4"
        assert d["next_run_at"] is not None
        assert d["agent_id"] == "default"
