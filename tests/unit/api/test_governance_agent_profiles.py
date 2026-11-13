# -*- coding: utf-8 -*-
"""R6 per-agent 执行档位 governance 端点（仅管理员）。

GET/PUT /governance/agent-exec-profiles[/{agent_id}]——合法域 = EXEC_PROFILES
键集；非法档位/空 id 422；存储走 agent_profile_settings 单文件 JSON。
"""
import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.security import agent_profile_settings as aps


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_AGENT_PROFILES_SETTINGS", str(tmp_path / "profiles.json"))
    app = create_app(enable_memory=False, enable_channels=False)
    return TestClient(app)


def _as_admin(client):
    from neurova.api.deps import get_current_user
    from neurova.api import auth as auth_mod
    from neurova.api.deps import require_admin

    override_user = {"user_id": "adm", "username": "adm", "role": "admin"}
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: override_user
    app.dependency_overrides[auth_mod.get_current_user] = lambda: override_user

    async def _admin_ok():
        return override_user

    app.dependency_overrides[require_admin] = _admin_ok


def test_get_empty_profiles(client):
    _as_admin(client)
    r = client.get("/api/v1/governance/agent-exec-profiles")
    assert r.status_code == 200
    assert r.json()["data"] == {}
    assert "lite" in r.json()["domains"] and "heavy" in r.json()["domains"]


def test_put_and_get_roundtrip(client):
    _as_admin(client)
    r = client.put("/api/v1/governance/agent-exec-profiles/agent-1",
                   json={"profile": "lite"})
    assert r.status_code == 200
    assert r.json()["data"] == {"agent_id": "agent-1", "profile": "lite"}
    r = client.get("/api/v1/governance/agent-exec-profiles")
    assert r.json()["data"]["agent-1"] == "lite"
    assert aps.get_agent_profile("agent-1") == "lite"


def test_put_rejects_invalid_profile(client):
    _as_admin(client)
    r = client.put("/api/v1/governance/agent-exec-profiles/agent-1",
                   json={"profile": "turbo"})
    assert r.status_code == 422
    assert aps.get_agent_profile("agent-1") == ""


def test_put_rejects_blank_agent_id(client):
    _as_admin(client)
    r = client.put("/api/v1/governance/agent-exec-profiles/%20",
                   json={"profile": "lite"})
    assert r.status_code == 422


def test_requires_admin(client):
    r = client.get("/api/v1/governance/agent-exec-profiles")
    assert r.status_code in (401, 403)


# ── R3 任务级档位分类器开关（设置项化）────────────────────────────

def test_task_profile_default_off_and_put_roundtrip(client, tmp_path, monkeypatch):
    _as_admin(client)
    monkeypatch.setenv("NEUROVA_TASK_PROFILE_SETTINGS", str(tmp_path / "tp.json"))
    monkeypatch.delenv("NEUROVA_TASK_PROFILE", raising=False)
    r = client.get("/api/v1/governance/task-profile")
    assert r.status_code == 200
    assert r.json()["data"]["classification_enabled"] is False
    r = client.put("/api/v1/governance/task-profile",
                   json={"classification_enabled": True})
    assert r.status_code == 200
    assert r.json()["data"]["classification_enabled"] is True
    r = client.get("/api/v1/governance/task-profile")
    assert r.json()["data"]["classification_enabled"] is True


def test_task_profile_rejects_extra_keys(client):
    _as_admin(client)
    r = client.put("/api/v1/governance/task-profile",
                   json={"classification_enabled": True, "hacker": 1})
    assert r.status_code == 422


def test_task_profile_requires_admin(client):
    r = client.get("/api/v1/governance/task-profile")
    assert r.status_code in (401, 403)
