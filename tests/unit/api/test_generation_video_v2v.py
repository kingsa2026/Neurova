# -*- coding: utf-8 -*-
"""M2（多模态追平批一）：/generation/video 的 video_url（视频生视频源）参数面。

鉴权/审计/租户段与既有 /video 完全同源；本地路径校验沿用 _validate_ref_images
白名单（防任意本地文件外泄），http(s)/data 直传。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import generation as generation_ep
from neurova.llm.generators import task_ledger as ledger_mod
from neurova.llm.generators.protocols import ProtocolCredentials
from neurova.llm.generators.task_ledger import GenerationTaskLedger


@pytest.fixture()
def tmp_ledger(tmp_path, monkeypatch):
    led = GenerationTaskLedger(path=str(tmp_path / "tasks.json"))
    monkeypatch.setattr(ledger_mod, "_ledger", led)
    yield led
    monkeypatch.setattr(ledger_mod, "_ledger", None)


@pytest.fixture()
def client(tmp_ledger, tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(generation_ep.router, prefix="/api/v1/generation")
    from neurova.api.deps import get_current_user as _gcu_deps

    app.dependency_overrides[_gcu_deps] = lambda: {
        "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
    }
    monkeypatch.setattr(generation_ep, "_GENERATION_OUTPUT_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


class TestVideoV2VEndpoint:
    def test_video_url_reaches_protocol_submit(self, client, monkeypatch, tmp_ledger):
        captured = {}

        def fake_resolve(protocol_hint, model, provider_id, api_key, base_url, default_base):
            return ProtocolCredentials(api_key="k", base_url=base_url or "https://x",
                                       model=model or "wan2.7-videoedit",
                                       protocol=protocol_hint)

        async def fake_submit(creds, prompt, **kw):
            captured["video_url"] = kw.get("video_url")
            captured["ref_images"] = kw.get("ref_images")
            captured["last_frame"] = kw.get("last_frame")
            return {"task_id": "remote-v2v", "poll_url": "https://x/tasks/remote-v2v"}

        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import protocols as proto_mod
        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        monkeypatch.setattr(proto_mod, "submit_video", fake_submit)

        resp = client.post("/api/v1/generation/video", json={
            "prompt": "把白天改成夜景", "video_url": "https://x/source.mp4",
            "ref_images": ["https://x/first.png"], "last_frame": "https://x/end.png",
            "api_key": "k", "base_url": "https://x",
        })
        assert resp.status_code == 200, resp.text
        assert captured["video_url"] == "https://x/source.mp4"
        assert captured["ref_images"] == ["https://x/first.png"]
        assert captured["last_frame"] == "https://x/end.png"
        rec = tmp_ledger.get(resp.json()["data"]["task_id"])
        assert rec.kind == "video" and rec.owner_user_id == "tuser"

    def test_local_video_url_outside_allowed_roots_rejected(self, client):
        """本地源视频路径必须落在允许目录内（与 ref_images 同一白名单纪律）。"""
        resp = client.post("/api/v1/generation/video", json={
            "prompt": "p", "video_url": "C:/Windows/system.ini",
            "api_key": "k", "base_url": "https://x",
        })
        assert resp.status_code == 400
        assert "允许目录" in resp.json()["detail"] or "ref_images" in resp.json()["detail"]
