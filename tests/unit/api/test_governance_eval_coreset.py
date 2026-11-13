# -*- coding: utf-8 -*-
"""评测集核选 K 值治理端点（仅管理员）：GET/PUT /governance/eval-coreset。

合法域 0–200（0=不核选）；env NEUROVA_EVAL_CORESET_K 灰度直改仍优先。
"""
import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.security import eval_coreset_settings as ecs


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_EVAL_CORESET_SETTINGS", str(tmp_path / "cs.json"))
    monkeypatch.delenv("NEUROVA_EVAL_CORESET_K", raising=False)
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


def test_get_default_zero(client):
    _as_admin(client)
    r = client.get("/api/v1/governance/eval-coreset")
    assert r.status_code == 200
    assert r.json()["data"]["coreset_k"] == 0


def test_put_roundtrip_and_env_wins(client, monkeypatch):
    _as_admin(client)
    r = client.put("/api/v1/governance/eval-coreset", json={"coreset_k": 6})
    assert r.status_code == 200
    assert r.json()["data"]["coreset_k"] == 6
    monkeypatch.setenv("NEUROVA_EVAL_CORESET_K", "2")
    assert client.get("/api/v1/governance/eval-coreset").json()["data"]["coreset_k"] == 2


def test_put_rejects_out_of_domain(client):
    _as_admin(client)
    assert client.put("/api/v1/governance/eval-coreset",
                      json={"coreset_k": 9999}).status_code == 422
    assert client.put("/api/v1/governance/eval-coreset",
                      json={"coreset_k": -1}).status_code == 422


def test_requires_admin(client):
    assert client.get("/api/v1/governance/eval-coreset").status_code in (401, 403)
