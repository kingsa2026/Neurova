# -*- coding: utf-8 -*-
"""工具溢出阈值参数进设置-高级（P1 #6 触点5）。

governance 端点组（require_admin + JSON 持久化，agent-limits 同模式）：
GET/PUT /governance/tool-offload → {threshold_kb, min_kb, max_kb, default_kb}
范围 8–512（用户拍板），默认 64；越界钳位、非法 422。
"""
import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.security import tool_offload_settings as tos


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_SETTINGS", str(tmp_path / "offload.json"))
    monkeypatch.delenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", raising=False)
    app = create_app(enable_memory=False, enable_channels=False)
    return TestClient(app)


def _as_admin(client):
    from neurova.api.deps import get_current_user
    from neurova.api import auth as auth_mod

    override_user = {"user_id": "adm", "username": "adm", "role": "admin"}
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: override_user
    app.dependency_overrides[auth_mod.get_current_user] = lambda: override_user
    from neurova.api.deps import require_admin

    async def _admin_ok():
        return override_user

    app.dependency_overrides[require_admin] = _admin_ok


def test_get_tool_offload_defaults(client):
    _as_admin(client)
    r = client.get("/api/v1/governance/tool-offload")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["threshold_kb"] == 64
    assert data["min_kb"] == 8 and data["max_kb"] == 512 and data["default_kb"] == 64


def test_put_persists_and_rejects_out_of_range(client):
    """端点层严格 422（诚实拒绝>静默改值）；settings 层钳位只兜 env/文件脏值。"""
    _as_admin(client)
    r = client.put("/api/v1/governance/tool-offload", json={"threshold_kb": 128})
    assert r.status_code == 200
    assert r.json()["data"]["threshold_kb"] == 128
    assert tos.load_settings()["threshold_kb"] == 128
    assert client.put("/api/v1/governance/tool-offload", json={"threshold_kb": 2048}).status_code == 422
    assert client.put("/api/v1/governance/tool-offload", json={"threshold_kb": 1}).status_code == 422


def test_put_rejects_non_positive(client):
    _as_admin(client)
    r = client.put("/api/v1/governance/tool-offload", json={"threshold_kb": 0})
    assert r.status_code == 422
