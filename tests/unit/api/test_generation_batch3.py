# -*- coding: utf-8 -*-
"""批次3：参考图链路 + OPENAI_COMPAT 图生图 + 产物文件鉴权。

锁定：
1. _validate_ref_images 允许根补 storage 上传目录（/files/upload 产物 path 可直接
   作参考图，前端上传→引用闭环）；
2. protocols._openai_image_generate 带参考图时走 images/edits multipart
   （文件头注释承诺过、代码从未实现——OPENAI_COMPAT i2i 静默丢参考图的根因）；
3. /generation/files/{name} 不再是匿名 StaticFiles：无凭证 401、?access_token=
   可访问（<img> 无法带 Bearer header）、账本属主 403、未知文件 404、防穿越。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from neurova.api.endpoints import generation as gen_ep
from neurova.llm.generators import protocols as proto_mod
from neurova.llm.generators import task_ledger as ledger_mod
from neurova.llm.generators.protocols import ProtocolCredentials
from neurova.llm.generators.task_ledger import GenerationTaskLedger, TaskRecord

pytestmark = pytest.mark.timeout(60)


class TestRefImageAllowedRoots:
    def test_storage_upload_root_allowed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gen_ep, "PROJECT_ROOT", tmp_path)
        up = tmp_path / "storage" / "users" / "u1" / "agents" / "default" / "images" / "f.png"
        up.parent.mkdir(parents=True)
        up.write_bytes(b"P")
        # 不抛异常即通过
        gen_ep._validate_ref_images([str(up)])

    def test_outside_roots_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gen_ep, "PROJECT_ROOT", tmp_path)
        outside = tmp_path.parent / "elsewhere.png"
        outside.write_bytes(b"x")
        with pytest.raises(HTTPException) as ei:
            gen_ep._validate_ref_images([str(outside)])
        assert ei.value.status_code == 400

    def test_missing_file_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gen_ep, "PROJECT_ROOT", tmp_path)
        ghost = tmp_path / "storage" / "users" / "u1" / "ghost.png"
        with pytest.raises(HTTPException):
            gen_ep._validate_ref_images([str(ghost)])


class TestOpenAIEditsMultipart:
    def test_edits_url_pure_function(self):
        assert proto_mod.openai_images_edits_url("https://a.example/v1") == \
            "https://a.example/v1/images/edits"
        assert proto_mod.openai_images_edits_url("") == \
            "https://api.openai.com/v1/images/edits"

    @pytest.mark.asyncio
    async def test_refs_route_to_edits_multipart(self, tmp_path, monkeypatch):
        ref = tmp_path / "ref.png"
        ref.write_bytes(b"REFPNG")
        captured = {}

        async def fake_post_form(url, headers, fields, files, timeout=60.0):
            captured["url"] = url
            captured["fields"] = fields
            captured["files"] = files
            return 200, {"data": [{"b64_json": "QUJD"}]}

        async def fake_post_json(url, headers, body, timeout=60.0):
            captured["json_url"] = url
            return 200, {"data": []}

        monkeypatch.setattr(proto_mod, "_post_form", fake_post_form)
        monkeypatch.setattr(proto_mod, "_post_json", fake_post_json)

        creds = ProtocolCredentials(api_key="k", base_url="https://a.example/v1",
                                    model="gpt-image-1", protocol="openai_compat")
        out = await proto_mod._openai_image_generate(
            creds, "p", "1024x1024", 1, [str(ref)], 60.0)

        assert captured.get("url", "").endswith("/images/edits")
        assert "json_url" not in captured, "带参考图不得再走 generations JSON 通道"
        field_names = [f[0] for f in captured["files"]]
        assert field_names and field_names[0] in ("image", "image[]")
        assert captured["files"][0][2] == b"REFPNG"
        assert out["images"] == ["data:image/png;base64,QUJD"]

    @pytest.mark.asyncio
    async def test_no_refs_keeps_generations_json(self, monkeypatch):
        seen = {}

        async def fake_post_json(url, headers, body, timeout=60.0):
            seen["url"] = url
            return 200, {"data": [{"url": "http://cdn/i.png"}]}

        monkeypatch.setattr(proto_mod, "_post_json", fake_post_json)
        creds = ProtocolCredentials(api_key="k", base_url="https://a/v1",
                                    model="dall-e-3", protocol="openai_compat")
        out = await proto_mod._openai_image_generate(creds, "p", "1024x1024", 1, [], 60.0)
        assert seen["url"].endswith("/images/generations")
        assert out["images"] == ["http://cdn/i.png"]


# ── 产物文件鉴权路由 ────────────────────────────────────────────────────────


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    from neurova.api import deps as deps_mod

    app = FastAPI()
    app.include_router(gen_ep.router, prefix="/api/v1/generation")

    monkeypatch.setattr(gen_ep, "GENERATION_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(gen_ep, "_GENERATION_OUTPUT_DIR", str(tmp_path))
    led = GenerationTaskLedger(path=str(tmp_path / "t.json"))
    monkeypatch.setattr(ledger_mod, "_ledger", led)

    payload = {"sub": "u1"}
    monkeypatch.setattr(deps_mod, "verify_access_token", lambda tok: payload if tok == "good" else None)
    monkeypatch.setattr(deps_mod, "_user_identity",
                        lambda p: {"user_id": "u1", "username": "u1", "role": "user", "neuser_id": "u1"})
    return TestClient(app), led, tmp_path


class TestGenerationFileAuth:
    def test_anonymous_rejected(self, auth_client):
        client, _, _ = auth_client
        resp = client.get("/api/v1/generation/files/art.png")
        assert resp.status_code == 401

    def test_query_token_serves_owned_file(self, auth_client):
        client, led, tmp = auth_client
        art = tmp / "art.png"
        art.write_bytes(b"PNG")
        led.add(TaskRecord(kind="image", status="succeeded", local_path=str(art),
                           owner_user_id="u1"))
        resp = client.get("/api/v1/generation/files/art.png?access_token=good")
        assert resp.status_code == 200
        assert resp.content == b"PNG"

    def test_other_users_task_forbidden(self, auth_client, monkeypatch):
        client, led, tmp = auth_client
        art = tmp / "priv.png"
        art.write_bytes(b"X")
        led.add(TaskRecord(kind="image", status="succeeded", local_path=str(art),
                           owner_user_id="someone-else"))
        resp = client.get("/api/v1/generation/files/priv.png?access_token=good")
        assert resp.status_code == 403

    def test_unknown_file_404_not_leak(self, auth_client):
        client, _, _ = auth_client
        resp = client.get("/api/v1/generation/files/nope.png?access_token=good")
        assert resp.status_code == 404

    def test_path_traversal_rejected(self, auth_client):
        client, _, _ = auth_client
        resp = client.get("/api/v1/generation/files/..%2F..%2Fetc%2Fpasswd?access_token=good")
        assert resp.status_code in (400, 404)

    def test_bad_token_401(self, auth_client):
        client, _, _ = auth_client
        resp = client.get("/api/v1/generation/files/art.png?access_token=bad")
        assert resp.status_code == 401


class TestTasksExpiredDisplay:
    """C3：保留清理删除文件后账本行不删——/tasks 须以 file_missing 显式标注，
    历史面板据此显示「已过期」，不得继续给必 404 的 url 装作可用。"""

    def test_missing_file_after_purge_flagged(self, auth_client):
        import time
        led = auth_client[1]
        gone = str(auth_client[2] / "purged.png")
        led.add(TaskRecord(kind="image", task_id="px1", status="done",
                           local_path=gone, owner_user_id="u1",
                           submitted_at=time.time(), updated_at=time.time()))
        resp = auth_client[0].get("/api/v1/generation/tasks?kind=image",
                                  headers={"Authorization": "Bearer good"})
        row = resp.json()["data"]["tasks"][0]
        assert row["file_missing"] is True
        assert row["url"] == ""
        assert row["status"] == "done"  # 账本原状态不篡改

    def test_present_file_not_flagged(self, auth_client):
        led = auth_client[1]
        art = auth_client[2] / "live.png"
        art.write_bytes(b"X")
        led.add(TaskRecord(kind="image", task_id="px2", status="done",
                           local_path=str(art), owner_user_id="u1"))
        resp = auth_client[0].get("/api/v1/generation/tasks?kind=image",
                                  headers={"Authorization": "Bearer good"})
        row = next(x for x in resp.json()["data"]["tasks"] if x["task_id"] == "px2")
        assert row.get("file_missing") is False
        assert row["url"].startswith("/api/v1/generation/files/")
