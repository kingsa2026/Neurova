# -*- coding: utf-8 -*-
"""M1（多模态追平批一）：/generation/music + /generation/music/status 端点契约。

对齐既有 /video 两段式范式：提交落账本（kind=music），轮询收口诚实回传。
鉴权沿用 /generation/* 路由级 get_current_user（P0-2 凭据盗刷面收口）。
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


class TestMusicAuthGate:
    def test_music_submit_requires_auth(self):
        """无登录令牌 → 401（/generation/* 路由级鉴权，与 /video 同口径）。"""
        app = FastAPI()
        app.include_router(generation_ep.router, prefix="/api/v1/generation")
        with TestClient(app) as client:
            resp = client.post("/api/v1/generation/music", json={"prompt": "p"})
        assert resp.status_code == 401

    def test_music_status_requires_auth(self):
        app = FastAPI()
        app.include_router(generation_ep.router, prefix="/api/v1/generation")
        with TestClient(app) as client:
            resp = client.get("/api/v1/generation/music/status/some-task")
        assert resp.status_code == 401


class TestMusicSubmitEndpoint:
    def test_submit_returns_task_and_lands_ledger(
        self, client, monkeypatch, tmp_ledger,
    ):
        captured = {}

        def fake_resolve(protocol_hint, model, provider_id, api_key, base_url, default_base):
            captured["protocol"] = protocol_hint
            captured["model"] = model
            captured["default_base"] = default_base
            return ProtocolCredentials(api_key=api_key or "k",
                                       base_url=base_url or "https://queue.fal.run",
                                       model=model or "fal-ai/musicgen",
                                       protocol=protocol_hint)

        async def fake_submit(creds, prompt, duration=30, timeout=60.0):
            captured["prompt"] = prompt
            captured["duration"] = duration
            return {"task_id": "req-9",
                    "poll_url": "https://queue.fal.run/fal-ai/musicgen/requests/req-9/status",
                    "result_url": "https://queue.fal.run/fal-ai/musicgen/requests/req-9",
                    "raw": {"request_id": "req-9"}}

        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import protocols as proto_mod
        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        monkeypatch.setattr(proto_mod, "submit_music", fake_submit)

        resp = client.post("/api/v1/generation/music", json={
            "prompt": "轻快的钢琴曲", "model": "fal-ai/musicgen",
            "duration": 20, "api_key": "fal-k", "base_url": "https://queue.fal.run",
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["status"] == "submitted"
        assert data["protocol"] == "fal"
        assert captured["prompt"] == "轻快的钢琴曲"
        assert captured["duration"] == 20
        assert captured["default_base"] == "https://queue.fal.run"

        rec = tmp_ledger.get(data["task_id"])
        assert rec is not None
        assert rec.kind == "music"
        assert rec.status == "submitted"
        assert rec.remote_task_id == "req-9"
        assert rec.owner_user_id == "tuser"

    def test_submit_provider_failure_is_honest_502(self, client, monkeypatch):
        def fake_resolve(*a, **k):
            return ProtocolCredentials(api_key="k", base_url="https://queue.fal.run",
                                       model="fal-ai/musicgen", protocol="fal")

        async def boom(creds, prompt, **kw):
            raise RuntimeError("上游 402 余额不足")

        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import protocols as proto_mod
        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        monkeypatch.setattr(proto_mod, "submit_music", boom)

        resp = client.post("/api/v1/generation/music", json={"prompt": "p"})
        assert resp.status_code == 502
        assert "余额不足" in resp.json()["detail"]


class TestMusicStatusEndpoint:
    def _seed_task(self, tmp_ledger, **kw):
        from neurova.llm.generators.task_ledger import TaskRecord

        fields = dict(kind="music", protocol="fal", model="fal-ai/musicgen",
                      base_url="https://queue.fal.run", status="submitted",
                      remote_task_id="req-7",
                      poll_url="https://queue.fal.run/fal-ai/musicgen/requests/req-7/status",
                      owner_user_id="tuser")
        fields.update(kw)
        return tmp_ledger.add(TaskRecord(**fields))

    def test_status_running(self, client, monkeypatch, tmp_ledger):
        rec = self._seed_task(tmp_ledger)

        async def fake_poll(creds, task_id, poll_url=""):
            assert task_id == "req-7"
            assert poll_url.endswith("/requests/req-7/status")
            return {"status": "running", "raw": {"status": "IN_QUEUE"}}

        from neurova.llm.generators import protocols as proto_mod
        monkeypatch.setattr(proto_mod, "poll_music", fake_poll)

        resp = client.get(f"/api/v1/generation/music/status/{rec.task_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "running"

    def test_status_succeeded_returns_local_url(
        self, client, monkeypatch, tmp_ledger, tmp_path,
    ):
        rec = self._seed_task(tmp_ledger)

        async def fake_poll(creds, task_id, poll_url=""):
            return {"status": "succeeded", "audio_url": "https://cdn.fal.ai/out.mp3",
                    "raw": {}}

        async def fake_persist(url_or_data, kind, task_id, index, out_dir=None):
            assert kind == "audio"
            p = tmp_path / f"{task_id}_0.mp3"
            p.write_bytes(b"MP3BYTES")
            return str(p)

        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import recovery as recovery_mod
        monkeypatch.setattr(proto_mod, "poll_music", fake_poll)
        # recovery 以 from-import 直连 persist_media，patch 必须打在其绑定点
        monkeypatch.setattr(recovery_mod, "persist_media", fake_persist)

        resp = client.get(f"/api/v1/generation/music/status/{rec.task_id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["status"] == "succeeded"
        assert data["url"].startswith("/api/v1/generation/files/")
        assert tmp_ledger.get(rec.task_id).status == "succeeded"

    def test_status_failed_is_honest(self, client, monkeypatch, tmp_ledger):
        rec = self._seed_task(tmp_ledger)

        async def fake_poll(creds, task_id, poll_url=""):
            return {"status": "failed", "error": "model runtime crashed", "raw": {}}

        from neurova.llm.generators import protocols as proto_mod
        monkeypatch.setattr(proto_mod, "poll_music", fake_poll)

        resp = client.get(f"/api/v1/generation/music/status/{rec.task_id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["status"] == "failed"
        assert "model runtime crashed" in data["error"]
        assert tmp_ledger.get(rec.task_id).status == "failed"

    def test_status_unknown_task_404(self, client, tmp_ledger):
        resp = client.get("/api/v1/generation/music/status/no-such-task")
        assert resp.status_code == 404

    def test_status_forbidden_for_other_owner(self, client, tmp_ledger, monkeypatch):
        rec = self._seed_task(tmp_ledger, owner_user_id="someone-else")
        app = FastAPI()
        app.include_router(generation_ep.router, prefix="/api/v1/generation")
        from neurova.api.deps import get_current_user as _gcu_deps

        app.dependency_overrides[_gcu_deps] = lambda: {
            "user_id": "tuser", "username": "tuser", "role": "user", "neuser_id": "tuser",
        }
        monkeypatch.setattr(ledger_mod, "_ledger", tmp_ledger)
        with TestClient(app) as c:
            resp = c.get(f"/api/v1/generation/music/status/{rec.task_id}")
        assert resp.status_code == 403
