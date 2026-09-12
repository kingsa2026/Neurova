"""media 元数据/配置持久化回归（2026-09-12 P8）。

根因：_media_store 与 _media_config 纯进程内存——上传的媒体文件字节在盘上，
但索引（filename/agent_id/memory_id/metadata）重启即丢 → AgentMediaPage 列表
恒空、孤儿文件不可管；PUT /config 保存同样不落盘。

修复：JSON 索引 data/media_index.json + 配置 data/media_config.json
（env NEUROVA_MEDIA_INDEX_PATH / NEUROVA_MEDIA_CONFIG_PATH 隔离），
启动加载、save/delete/config 变更即时落盘。
"""
import io
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_media_0123456789")

from neurova.api.auth import get_current_user
from neurova.api.endpoints import media as MEDIA

ADMIN = {"user_id": "a1", "username": "a1", "role": "admin"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(MEDIA, "_INDEX_FILE", str(tmp_path / "media_index.json"))
    monkeypatch.setattr(MEDIA, "_CONFIG_FILE", str(tmp_path / "media_config.json"))
    MEDIA._media_store.clear()
    MEDIA._media_config["storage_path"] = str(tmp_path / "media_storage")
    app = FastAPI()
    app.include_router(MEDIA.router, prefix="/api/v1/media")
    app.dependency_overrides[get_current_user] = lambda: dict(ADMIN)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()
    MEDIA._media_store.clear()


def _upload(c, name="pic.png"):
    return c.post(
        "/api/v1/media/save",
        files={"file": (name, io.BytesIO(b"\x89PNG fake bytes"), "image/png")},
        data={"media_type": "image", "agent_id": "ag1", "memory_id": "m-7"},
    )


class TestMediaIndexPersistence:
    def test_upload_written_to_index(self, client):
        c, tmp = client
        r = _upload(c)
        assert r.status_code == 200, r.text
        idx = tmp / "media_index.json"
        assert idx.exists(), "媒体元数据未落盘"
        assert json.loads(idx.read_text(encoding="utf-8"))["media"]

    def test_list_survives_restart(self, client):
        c, _ = client
        _upload(c, "keep.png")
        MEDIA._media_store.clear()
        MEDIA._load_index()  # 模拟重启
        items = c.get("/api/v1/media/list", params={"agent_id": "ag1"}).json()["data"]["media"]
        assert [m["filename"] for m in items] == ["keep.png"]
        assert items[0]["memory_id"] == "m-7"

    def test_delete_updates_index(self, client):
        c, tmp = client
        mid = _upload(c, "gone.png").json()["data"]["media_id"]
        c.delete(f"/api/v1/media/{mid}")
        MEDIA._media_store.clear()
        MEDIA._load_index()
        assert c.get(f"/api/v1/media/{mid}").status_code == 404

    def test_config_persisted(self, client):
        c, tmp = client
        r = c.put("/api/v1/media/config", json={
            "max_file_size": 1048576, "allowed_types": ["image", "audio"],
            "storage_path": "media_storage", "enable_compression": True,
        })
        assert r.status_code == 200, r.text
        saved = json.loads((tmp / "media_config.json").read_text(encoding="utf-8"))
        assert saved["max_file_size"] == 1048576
