# -*- coding: utf-8 -*-
"""L5：尾帧通道（先画后动）——protocols/video 端点/facade keyframe。

Seedance i2v 官方支持 first_frame/last_frame 角色（先画后动插值）；
WAN 无尾帧通道 → 参数进 ignored_params 显式标注（对齐 R2 能力路由教义，
不静默丢弃不假生效）。facade keyframe_to_video 从「诚实 unsupported」升级为
Seedance 双帧真实通道。
"""
from __future__ import annotations

import pytest

from neurova.llm.generators.protocols import (
    ProtocolCredentials, submit_video,
)

pytestmark = pytest.mark.timeout(60)


class TestSeedanceLastFrame:
    @pytest.mark.asyncio
    async def test_last_frame_role_appended(self, monkeypatch):
        captured = {}

        async def fake_post(url, headers, body, timeout=60.0):
            captured["body"] = body
            return 200, {"id": "t1"}

        from neurova.llm.generators import protocols as p
        monkeypatch.setattr(p, "_post_json", fake_post)
        creds = ProtocolCredentials(api_key="k", base_url="https://ark.test",
                                    model="seedance-2-0", protocol="seedance2")
        out = await submit_video(creds, "p", ref_images=["http://f/a.png"],
                                 last_frame="http://f/z.png")
        roles = [c.get("role") for c in captured["body"]["content"] if c.get("role")]
        assert roles == ["first_frame", "last_frame"]
        assert "ignored_params" not in out or not out.get("ignored_params")

    @pytest.mark.asyncio
    async def test_first_frame_semantics_unchanged(self, monkeypatch):
        # 回归：不传 last_frame 时行为与批次0 一致（首帧 + 其余 reference_image）
        captured = {}

        async def fake_post(url, headers, body, timeout=60.0):
            captured["body"] = body
            return 200, {"id": "t1"}

        from neurova.llm.generators import protocols as p
        monkeypatch.setattr(p, "_post_json", fake_post)
        creds = ProtocolCredentials(api_key="k", base_url="https://ark.test",
                                    model="seedance", protocol="seedance2")
        await submit_video(creds, "p", ref_images=["http://a.png", "http://b.png"])
        roles = [c.get("role") for c in captured["body"]["content"] if c.get("role")]
        assert roles == ["first_frame", "reference_image"]


class TestWanLastFrameHonest:
    @pytest.mark.asyncio
    async def test_wan_reports_ignored_last_frame(self, monkeypatch):
        async def fake_post(url, headers, body, timeout=60.0):
            return 200, {"output": {"task_id": "t1"}}

        from neurova.llm.generators import protocols as p
        monkeypatch.setattr(p, "_post_json", fake_post)
        creds = ProtocolCredentials(api_key="k", base_url="https://dashscope.test",
                                    model="wan2.2-i2v", protocol="wan")
        out = await submit_video(creds, "p", ref_images=["http://a.png"],
                                 last_frame="http://z.png")
        assert out.get("ignored_params") == ["last_frame"]  # 显式标注，提交照常
        assert out["task_id"] == "t1"


class TestVideoEndpointLastFrame:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.endpoints import generation as gen_ep
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import task_ledger as ledger_mod
        from neurova.llm.generators.task_ledger import GenerationTaskLedger

        app = FastAPI()
        app.include_router(gen_ep.router, prefix="/api/v1/generation")
        from neurova.api.deps import get_current_user as _gcu
        app.dependency_overrides[_gcu] = lambda: {
            "user_id": "tuser", "username": "t", "role": "admin", "neuser_id": "t"}
        led = GenerationTaskLedger(path=str(tmp_path / "led.json"))
        monkeypatch.setattr(ledger_mod, "_ledger", led)
        monkeypatch.setattr(
            gen_runtime, "resolve_generation_creds",
            lambda hint, model, pid, ak, bu, db: gen_runtime.ProtocolCredentials(
                api_key="k", base_url="https://dashscope", model="wan", protocol=hint))

        async def fake_submit(creds, prompt, **kw):
            return {"task_id": "r1", "poll_url": "https://x/tasks/r1", "raw": {},
                    "ignored_params": ["last_frame"]}

        monkeypatch.setattr(proto_mod, "submit_video", fake_submit)
        client = TestClient(app)
        return client, led

    def test_endpoint_accepts_and_records_ignored(self, client):
        c, led = client
        r = c.post("/api/v1/generation/video", json={
            "prompt": "p", "ref_images": ["http://f/a.png"], "last_frame": "http://f/z.png"})
        assert r.status_code == 200
        assert r.json()["data"]["ignored_params"] == "last_frame"
        rec = led.list()[0]
        assert rec.ignored_params == "last_frame"


class TestFacadeKeyframe:
    @pytest.mark.asyncio
    async def test_keyframe_dispatches_seedance(self, monkeypatch):
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators.protocols import ProtocolCredentials
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators.base import GenerationConfig, GeneratorType

        monkeypatch.setattr(
            gen_runtime, "resolve_generation_creds",
            lambda hint, model, pid, ak, bu, db: ProtocolCredentials(
                api_key="k", base_url="https://ark.test", model="seedance",
                protocol="seedance2"))

        seen = {}

        async def fake_wait(creds, prompt, duration=5, resolution="1080p",
                            ref_images=None, audio=None, poll_interval=10.0,
                            max_wait=900.0, last_frame=None):
            seen["refs"] = ref_images
            seen["last_frame"] = last_frame
            return {"status": "succeeded", "video_url": "http://v/out.mp4", "raw": {}}

        monkeypatch.setattr(proto_mod, "generate_video_wait", fake_wait)

        async def fake_persist(url, kind, task_id, index, out_dir=None):
            return "/tmp/out.mp4"

        monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)

        gen = gen_runtime.ProtocolGenerator(GeneratorType.KEYFRAME_TO_VIDEO)
        cfg = GenerationConfig(
            type=GeneratorType.KEYFRAME_TO_VIDEO, model="seedance",
            start_image_url="http://f/a.png", end_image_url="http://f/z.png")
        result = await gen.generate(cfg)
        assert result.success, result.error
        assert seen["refs"] == ["http://f/a.png"]
        assert seen["last_frame"] == "http://f/z.png"
