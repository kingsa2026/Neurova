# -*- coding: utf-8 -*-
"""Agent 建/改表单的执行档位派发（R6）端点测试。

锁定行为：
1. POST /agents 带 exec_profile=lite → per-agent 档位存储落盘、GET 回显；
2. PUT exec_profile="" → 清除（回落部署档位，GET 回显 null）；
3. PUT exec_profile=非法值 → 422；
4. DELETE agent → 档位随删清理（不同 id 重建不继承残留）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from neurova.agent_config import reset_config_manager
    from neurova.api.endpoints import set_app_state

    reset_config_manager()
    set_app_state({"agents": {}})
    yield tmp_path
    set_app_state(None)
    reset_config_manager()


@pytest.fixture()
def client():
    from neurova.api.endpoints import agent
    from neurova.api.auth import get_current_user

    app = FastAPI()
    app.include_router(agent.router, prefix="/v1/agents")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1", "role": "admin", "username": "admin",
    }
    return TestClient(app)


def _profile(agent_id: str) -> str:
    from neurova.security.agent_profile_settings import get_agent_profile

    return get_agent_profile(agent_id)


def test_create_with_exec_profile_persists_and_echoes(client, env):
    try:
        r = client.post("/v1/agents", json={
            "agent_id": "profagent", "name": "P", "exec_profile": "lite",
        })
        assert r.status_code == 200, r.text
        assert r.json()["exec_profile"] == "lite"
        assert _profile("profagent") == "lite"
        detail = client.get("/v1/agents/profagent")
        assert detail.json()["exec_profile"] == "lite"
    finally:
        client.delete("/v1/agents/profagent")


def test_update_empty_profile_clears(client, env):
    try:
        client.post("/v1/agents", json={
            "agent_id": "clragent", "name": "C", "exec_profile": "heavy",
        })
        assert _profile("clragent") == "heavy"
        r = client.put("/v1/agents/clragent", json={"exec_profile": ""})
        assert r.status_code == 200
        assert _profile("clragent") == ""
        assert r.json()["exec_profile"] is None
    finally:
        client.delete("/v1/agents/clragent")


def test_update_invalid_profile_422(client, env):
    try:
        client.post("/v1/agents", json={"agent_id": "invagent", "name": "I"})
        r = client.put("/v1/agents/invagent", json={"exec_profile": "turbo"})
        assert r.status_code == 422
        assert _profile("invagent") == ""
    finally:
        client.delete("/v1/agents/invagent")


def test_delete_clears_profile(client, env):
    client.post("/v1/agents", json={
        "agent_id": "delagent", "name": "D", "exec_profile": "standard",
    })
    assert _profile("delagent") == "standard"
    client.delete("/v1/agents/delagent")
    assert _profile("delagent") == ""
