# -*- coding: utf-8 -*-
"""实验性评测机制开关治理端点（N1-N3 设置项化，仅管理员）。

GET/PUT /governance/eval-experiments：profile_variants_enabled /
lineage_pareto_enabled / diagnosis_rollouts 三键；合法域 0/1 开关与 1–5 采样；
env 灰度直改仍优先于设置文件。
"""
import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.security import eval_experiment_settings as ees


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_EVAL_EXPERIMENT_SETTINGS", str(tmp_path / "exp.json"))
    for key in ("NEUROVA_PROFILE_VARIANTS", "NEUROVA_LINEAGE_PARETO",
                "NEUROVA_DIAGNOSIS_ROLLOUTS", "NEUROVA_EVOLUTION_REPAIR_ROUNDS"):
        monkeypatch.delenv(key, raising=False)
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


def test_get_defaults_all_off(client):
    _as_admin(client)
    r = client.get("/api/v1/governance/eval-experiments")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["profile_variants_enabled"] is False
    assert data["lineage_pareto_enabled"] is False
    assert data["diagnosis_rollouts"] == 1


def test_put_roundtrip(client):
    _as_admin(client)
    r = client.put("/api/v1/governance/eval-experiments", json={
        "profile_variants_enabled": True,
        "lineage_pareto_enabled": True,
        "diagnosis_rollouts": 3,
    })
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["profile_variants_enabled"] is True
    assert data["lineage_pareto_enabled"] is True
    assert data["diagnosis_rollouts"] == 3
    # 持久化可读
    assert ees.load_settings()["profile_variants_enabled"] is True


def test_put_rejects_out_of_domain(client):
    _as_admin(client)
    assert client.put("/api/v1/governance/eval-experiments",
                      json={"diagnosis_rollouts": 0}).status_code == 422
    assert client.put("/api/v1/governance/eval-experiments",
                      json={"diagnosis_rollouts": 9}).status_code == 422


def test_put_rejects_unknown_keys(client):
    _as_admin(client)
    assert client.put("/api/v1/governance/eval-experiments",
                      json={"hacker": True}).status_code == 422


def test_env_still_wins_over_file(client, monkeypatch):
    _as_admin(client)
    client.put("/api/v1/governance/eval-experiments",
               json={"profile_variants_enabled": False})
    monkeypatch.setenv("NEUROVA_PROFILE_VARIANTS", "1")
    r = client.get("/api/v1/governance/eval-experiments")
    assert r.json()["data"]["profile_variants_enabled"] is True


def test_repair_rounds_roundtrip_and_domain(client):
    """V1 修复额度走同一治理面：默认 0（关）、roundtrip 生效、越域 422。"""
    _as_admin(client)
    r = client.get("/api/v1/governance/eval-experiments")
    assert r.status_code == 200
    assert r.json()["data"]["repair_rounds"] == 0
    assert r.json()["domains"]["repair_rounds_max"] == 5

    r = client.put("/api/v1/governance/eval-experiments", json={"repair_rounds": 2})
    assert r.status_code == 200
    assert r.json()["data"]["repair_rounds"] == 2
    assert ees.load_settings()["repair_rounds"] == 2

    assert client.put("/api/v1/governance/eval-experiments",
                      json={"repair_rounds": 6}).status_code == 422
    assert client.put("/api/v1/governance/eval-experiments",
                      json={"repair_rounds": -1}).status_code == 422


def test_requires_admin(client):
    assert client.get("/api/v1/governance/eval-experiments").status_code in (401, 403)
