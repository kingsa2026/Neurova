"""P7 僵尸批中的两项真实修复回归（2026-09-12）。

A. settings 单键 GET/PUT /{key} 与整表 PUT 的 flat 分支只写进程内存
   `_default_settings`，不触 data/app_settings.json——保存谎报成功、重启丢，
   且单键 GET 与整表 GET 读源不一致（整表合并了持久层，单键没有）。
   修复：flat 键统一落 app_settings 的 "flat" section，读写同源。

B. memory_share_groups 端点调 get_share_group_manager() 从不传 storage_path，
   ShareGroupManager._save_to_file 对 None 直接 return——持久化能力在但未接线，
   恒内存。修复：端点缺省传 data/memory_share_groups.json（env 可隔离）。
"""
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p7_0123456789")

from neurova.api.auth import get_current_user as auth_u
from neurova.api.deps import get_current_user as deps_u
from neurova.api.endpoints import settings as SETTINGS
from neurova.api.endpoints import memory_share_groups as MSG
from neurova.cognitive_layers.memory_layer import share_group as SG
from neurova.core import app_settings as APPS

ADMIN = {"user_id": "a1", "username": "a1", "role": "admin"}


@pytest.fixture()
def settings_client(tmp_path, monkeypatch):
    monkeypatch.setattr(APPS, "_settings_path", lambda path=None: tmp_path / "app_settings.json")
    app = FastAPI()
    app.include_router(SETTINGS.router, prefix="/api")
    app.dependency_overrides[deps_u] = lambda: dict(ADMIN)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()


class TestSettingsFlatPersistence:
    def test_put_key_written_to_disk(self, settings_client):
        c, tmp = settings_client
        r = c.put("/api/v1/settings/theme", json={"value": "light"})
        assert r.status_code == 200, r.text
        f = tmp / "app_settings.json"
        assert f.exists()
        assert json.loads(f.read_text(encoding="utf-8"))["flat"]["theme"] == "light"

    def test_get_key_reads_persisted_value(self, settings_client):
        c, _ = settings_client
        c.put("/api/v1/settings/language", json={"value": "en-US"})
        got = c.get("/api/v1/settings/language").json()
        assert got["data"]["value"] == "en-US"

    def test_flat_survives_memory_reset(self, settings_client, monkeypatch):
        """重启模拟：内存默认字典恢复初始值后，持久值仍从盘回读。"""
        c, _ = settings_client
        c.put("/api/v1/settings/theme", json={"value": "light"})
        monkeypatch.setattr(SETTINGS, "_default_settings", dict(SETTINGS._default_settings))
        got = c.get("/api/v1/settings/theme").json()
        assert got["data"]["value"] == "light"
        full = c.get("/api/v1/settings").json()["settings"]
        assert full["theme"] == "light"

    def test_whole_table_flat_branch_persists(self, settings_client):
        c, tmp = settings_client
        r = c.put("/api/v1/settings", json={"settings": {"auto_save": False}})
        assert r.status_code == 200
        saved = json.loads((tmp / "app_settings.json").read_text(encoding="utf-8"))
        assert saved["flat"]["auto_save"] is False


@pytest.fixture()
def share_client(tmp_path, monkeypatch):
    monkeypatch.setattr(MSG, "_STORE_PATH", str(tmp_path / "memory_share_groups.json"))
    SG.reset_share_group_manager()
    app = FastAPI()
    app.include_router(MSG.router, prefix="/api/v1")
    app.dependency_overrides[auth_u] = lambda: dict(ADMIN)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()
    SG.reset_share_group_manager()


class TestShareGroupsPersistence:
    def test_created_group_written_to_disk(self, share_client):
        c, tmp = share_client
        r = c.post("/api/v1/memory-share-groups", json={"name": "研究组", "agent_ids": ["a1", "a2"]})
        assert r.status_code == 200, r.text
        f = tmp / "memory_share_groups.json"
        assert f.exists(), "共享组持久化能力存在但端点从不传 storage_path"
        SG.reset_share_group_manager()
        groups = c.get("/api/v1/memory-share-groups").json()
        assert [g["name"] for g in groups] == ["研究组"]
