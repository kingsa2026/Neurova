# -*- coding: utf-8 -*-
"""检索配方治理端点（C3，仅管理员）。

GET/PUT /governance/retrieval-recipe：active_recipe 四选一；
非法名 422；env 直改（NEUROVA_RETRIEVAL_RECIPE）优先于设置文件。
"""

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.security import retrieval_recipe_settings as rrs


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_RETRIEVAL_RECIPE_SETTINGS",
                       str(tmp_path / "recipe.json"))
    monkeypatch.delenv("NEUROVA_RETRIEVAL_RECIPE", raising=False)
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


def test_get_defaults(client):
    _as_admin(client)
    r = client.get("/api/v1/governance/retrieval-recipe")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["active_recipe"] == "default"
    assert data["source"] == "default"
    names = [o["name"] for o in data["options"]]
    assert names == ["default", "balanced", "precise", "graph_expanded"]


def test_put_roundtrip(client):
    _as_admin(client)
    r = client.put("/api/v1/governance/retrieval-recipe",
                   json={"active_recipe": "graph_expanded"})
    assert r.status_code == 200
    assert r.json()["data"]["active_recipe"] == "graph_expanded"
    assert rrs.load_settings()["active_recipe"] == "graph_expanded"


def test_put_rejects_unknown_recipe(client):
    _as_admin(client)
    r = client.put("/api/v1/governance/retrieval-recipe",
                   json={"active_recipe": "bogus"})
    assert r.status_code == 422


def test_put_rejects_unknown_keys(client):
    _as_admin(client)
    assert client.put("/api/v1/governance/retrieval-recipe",
                      json={"hacker": True}).status_code == 422


def test_env_still_wins_over_file(client, monkeypatch):
    _as_admin(client)
    client.put("/api/v1/governance/retrieval-recipe",
               json={"active_recipe": "precise"})
    monkeypatch.setenv("NEUROVA_RETRIEVAL_RECIPE", "balanced")
    r = client.get("/api/v1/governance/retrieval-recipe")
    data = r.json()["data"]
    assert data["active_recipe"] == "balanced"
    assert data["source"] == "env"


def test_requires_admin(client):
    assert client.get("/api/v1/governance/retrieval-recipe").status_code in (401, 403)
