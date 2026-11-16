"""S2 安全批：media.py 属主门与 admin 门（审计 2026-11-16 P1-7）。

写入侧自 §6-172 起记录 user_id，但读/删/恢复侧从不比对——任何登录用户可按 id
读、删、恢复他人媒体；PUT /config 可改 storage_path（后续落盘根，配合可控
filename 具备任意写要件）；cache/clear 可清空全量索引。本档钉：
- 读（内容/元数据/下载）、删（单条/批量）、恢复：非属主一律 404（files_api
  `_get_owned_file` 同构，不区分"不存在"与"无权"）；
- 历史无主行（user_id 为空）仅 admin 可见——桌面单机存量不因补门对管理员消失；
- PUT /config 与 POST /cache/clear 收 admin。
"""

import io
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_media_s2_0123456789")

from neurova.api.auth import get_current_user  # noqa: E402
from neurova.api.endpoints import media as MEDIA  # noqa: E402

ALICE = {"user_id": "alice", "username": "alice", "role": "user"}
BOB = {"user_id": "bob", "username": "bob", "role": "user"}
ADMIN = {"user_id": "root", "username": "root", "role": "admin"}
PAYLOAD = b"\x89PNG\x0d\x0a\x1a\x0a" + bytes(range(32))


@pytest.fixture()
def face(tmp_path, monkeypatch):
    monkeypatch.setattr(MEDIA, "_INDEX_FILE", str(tmp_path / "media_index.json"))
    monkeypatch.setattr(MEDIA, "_CONFIG_FILE", str(tmp_path / "media_config.json"))
    MEDIA._media_store.clear()
    MEDIA._media_config["storage_path"] = str(tmp_path / "media_storage")
    app = FastAPI()
    app.include_router(MEDIA.router, prefix="/api/v1/media")
    who = {"v": ALICE}
    app.dependency_overrides[get_current_user] = lambda: dict(who["v"])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, who
    app.dependency_overrides.clear()
    MEDIA._media_store.clear()


def _upload(c, name="pic.png", agent_id="ag1"):
    r = c.post(
        "/api/v1/media/save",
        files={"file": (name, io.BytesIO(PAYLOAD), "image/png")},
        data={"media_type": "image", "agent_id": agent_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["media_id"]


class TestMediaOwnerGates:
    def test_non_owner_cannot_read_content_metadata_or_download(self, face):
        c, who = face
        mid = _upload(c)
        who["v"] = BOB
        for path in (f"/api/v1/media/{mid}", f"/api/v1/media/{mid}/metadata", f"/api/v1/media/download/{mid}"):
            r = c.get(path)
            assert r.status_code == 404, f"GET {path} 非属主应 404，实得 {r.status_code}"

    def test_non_owner_cannot_delete_single(self, face):
        c, who = face
        mid = _upload(c)
        who["v"] = BOB
        assert c.delete(f"/api/v1/media/{mid}").status_code == 404
        assert c.delete(f"/api/v1/media/{mid}?mode=trash").status_code == 404
        assert mid in MEDIA._media_store, "非属主删除仍把条目删掉了"

    def test_non_owner_cannot_restore(self, face):
        c, who = face
        mid = _upload(c)
        assert c.delete(f"/api/v1/media/{mid}?mode=trash").status_code == 200
        who["v"] = BOB
        r = c.post(f"/api/v1/media/{mid}/restore")
        assert r.status_code == 404, f"非属主恢复应 404，实得 {r.status_code}"

    def test_batch_delete_skips_foreign_ids(self, face):
        c, who = face
        foreign = _upload(c, name="foreign.png")  # ALICE 上传
        who["v"] = BOB
        mine = _upload(c, name="mine.png")  # BOB 上传
        r = c.post("/api/v1/media/batch-delete", json={"media_ids": [foreign, mine], "mode": "permanent"})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert foreign in [f["media_id"] for f in data["failed"]], "非属主 id 应落入失败清单"
        assert foreign in MEDIA._media_store, "批量删除把别人的条目删掉了"
        assert mine in data["succeeded"], "本人条目应可删除"
        assert mine not in MEDIA._media_store

    def test_ownerless_record_visible_to_admin_only(self, face):
        """历史无主行（user_id 为空）：普通用户 404，admin 可见——存量不丢、不向他人暴露。"""
        c, who = face
        mid = _upload(c)
        MEDIA._media_store[mid]["user_id"] = ""
        who["v"] = BOB
        assert c.get(f"/api/v1/media/{mid}").status_code == 404, "无主行对普通用户应 404"
        who["v"] = ADMIN
        assert c.get(f"/api/v1/media/{mid}").status_code == 200, "无主行对 admin 应可见"

    def test_owner_still_accesses_own_record(self, face):
        c, who = face
        mid = _upload(c)
        assert c.get(f"/api/v1/media/{mid}").status_code == 200
        assert c.get(f"/api/v1/media/{mid}/metadata").status_code == 200

    def test_put_config_requires_admin(self, face):
        c, who = face
        who["v"] = BOB
        r = c.put("/api/v1/media/config", json={"storage_path": "/tmp/evil-root"})
        assert r.status_code == 403, f"普通用户改 config 应 403，实得 {r.status_code}"
        assert MEDIA._media_config["storage_path"] != "/tmp/evil-root", "403 了却把配置改掉了"

    def test_put_config_allowed_for_admin(self, face):
        c, who = face
        who["v"] = ADMIN
        r = c.put("/api/v1/media/config", json={"max_file_size": 123})
        assert r.status_code == 200, r.text
        assert MEDIA._media_config["max_file_size"] == 123

    def test_cache_clear_requires_admin(self, face):
        c, who = face
        _upload(c)
        who["v"] = BOB
        r = c.post("/api/v1/media/cache/clear")
        assert r.status_code == 403, f"普通用户清空索引应 403，实得 {r.status_code}"
        assert len(MEDIA._media_store) == 1, "403 了却把索引清掉了"
        who["v"] = ADMIN
        assert c.post("/api/v1/media/cache/clear").status_code == 200
        assert len(MEDIA._media_store) == 0
