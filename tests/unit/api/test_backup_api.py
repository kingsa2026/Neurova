# -*- coding: utf-8 -*-
"""BackupOrchestrator admin API 接线测试（防孤儿代码回归）。

BackupOrchestrator（Ed25519 签名备份，commit 3923ce3）能力完整但此前
无 API/CLI 触达——本测试锁定 /v1/backups 三端点的接线与信任语义。
"""
import json
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 隔离：key 与备份产物落 tmp；sources 指向 tmp 目录
    monkeypatch.setenv("NEUROVA_BACKUP_KEY_PATH", str(tmp_path / "key.bin"))
    monkeypatch.setenv("NEUROVA_BACKUP_WORK_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv(
        "NEUROVA_BACKUP_SOURCES",
        json.dumps({"sessions": str(tmp_path / "sessions"), "agent_workspaces": str(tmp_path / "ws")}),
    )

    from neurova.api.endpoints import backup_api

    backup_api._reset_backup_orchestrator()
    app = FastAPI()
    app.include_router(backup_api.router, prefix="/v1/backups")
    yield TestClient(app)
    backup_api._reset_backup_orchestrator()


@pytest.fixture()
def authed_client(client):
    from neurova.api.deps import get_current_user

    def fake_admin():
        return {"username": "admin", "role": "admin"}

    client.app.dependency_overrides[get_current_user] = fake_admin
    yield client
    client.app.dependency_overrides.clear()


def _make_source(tmp_path: Path):
    (tmp_path / "sessions").mkdir(exist_ok=True)
    (tmp_path / "sessions" / "a.json").write_text('{"k": 1}', encoding="utf-8")
    (tmp_path / "ws").mkdir(exist_ok=True)
    (tmp_path / "ws" / "cfg.json").write_text('{"w": 2}', encoding="utf-8")


def test_create_backup_returns_signed_zip(authed_client, tmp_path):
    _make_source(tmp_path)
    resp = authed_client.post("/v1/backups/create")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    zip_path = Path(body["data"]["zip_path"])
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "sessions/a.json" in names
        assert "agent_workspaces/cfg.json" in names
        assert "meta.json" in names


def test_list_and_restore_roundtrip(authed_client, tmp_path):
    _make_source(tmp_path)
    created = authed_client.post("/v1/backups/create").json()["data"]["zip_path"]

    listed = authed_client.get("/v1/backups").json()
    assert listed["success"] is True
    assert any(item["zip_path"] == created for item in listed["data"]["items"])

    # 破坏源文件后恢复
    (tmp_path / "sessions" / "a.json").unlink()
    resp = authed_client.post("/v1/backups/restore", json={"zip_path": created})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["write_back"]["written"] >= 1
    assert (tmp_path / "sessions" / "a.json").read_text(encoding="utf-8") == '{"k": 1}'


def test_restore_rejects_foreign_signature(authed_client, tmp_path):
    from neurova.backup.trust import SigningKey, sign_backup

    other_key_dir = tmp_path / "other"
    other_key_dir.mkdir()
    foreign_zip = tmp_path / "foreign.zip"
    with zipfile.ZipFile(foreign_zip, "w") as zf:
        zf.writestr("sessions/c.json", "y")
        zf.writestr("meta.json", json.dumps({"scheme": "hmac-sha256-v1", "backup_id": "x"}))
    sign_backup(foreign_zip, SigningKey(other_key_dir / "k.bin"))

    resp = authed_client.post("/v1/backups/restore", json={"zip_path": str(foreign_zip)})
    assert resp.status_code == 409  # TrustRequiredError → 409，绝不静默恢复


def test_restore_rejects_zip_slip(authed_client, tmp_path):
    # 本实例签名的包，但条目路径越界（Zip Slip）——写回应拒绝
    from neurova.backup.trust import sign_backup

    orch_zip = tmp_path / "slip.zip"
    with zipfile.ZipFile(orch_zip, "w") as zf:
        zf.writestr("sessions/../../evil.json", "pwned")
        zf.writestr("meta.json", json.dumps({"scheme": "hmac-sha256-v1", "backup_id": "s"}))
    sign_backup(orch_zip, _local_key(tmp_path))

    resp = authed_client.post("/v1/backups/restore", json={"zip_path": str(orch_zip)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["write_back"]["skipped"] >= 1
    assert not (tmp_path / "evil.json").exists()


def _local_key(tmp_path: Path):
    from neurova.api.endpoints import backup_api

    return backup_api.get_backup_orchestrator().key


def test_unauthenticated_rejected(client):
    assert client.post("/v1/backups/create").status_code in (401, 403)
