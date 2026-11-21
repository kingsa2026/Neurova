# -*- coding: utf-8 -*-
"""M2（多模态追平批一）：video_to_video + 首尾帧（imageUrl/endImageUrl）协议补全。

三家已拍板全做、用户自由选择：dashscope-wan / 火山 Seedance / Google Veo。
v2v 请求体字段按各家既有异步任务形态落地（源视频 + 首帧/尾帧角色）；
契约按桩锁定，官方文档待核（与 M1 同一标注纪律——不虚构、诚实待验）。
facade 按用户传入模型/协议分派；未指定默认 dashscope-wan 先验证。
"""
from __future__ import annotations

import base64

import pytest

from neurova.llm.generators import protocols as proto_mod
from neurova.llm.generators.protocols import (
    ProtocolCredentials,
    VideoProtocol,
    generate_video_wait,
    submit_video,
)


def _creds(protocol: str, model: str) -> ProtocolCredentials:
    return ProtocolCredentials(api_key="k", base_url="", model=model, protocol=protocol)


class TestWanVideoToVideo:
    @pytest.mark.asyncio
    async def test_submit_carries_source_video_and_first_frame(self, monkeypatch):
        captured = {}

        async def fake_post_json(url, headers, body, timeout=60.0):
            captured.update(url=url, body=body)
            return 200, {"output": {"task_id": "wan-1"}}

        monkeypatch.setattr(proto_mod, "_post_json", fake_post_json)
        out = await submit_video(
            _creds("wan", "wan2.7-videoedit"), "把白天改成夜景",
            video_url="https://x/source.mp4",
            ref_images=["https://x/first.png"],
            last_frame="https://x/end.png",
        )
        assert captured["url"].endswith("/services/aigc/video-generation/video-synthesis")
        assert captured["body"]["input"]["video_url"] == "https://x/source.mp4"
        # 首帧（imageUrl）照常走 input.media；WAN 无尾帧通道 → 显式忽略标注
        assert captured["body"]["input"]["media"] == ["https://x/first.png"]
        assert "last_frame" in (out.get("ignored_params") or [])
        assert out["task_id"] == "wan-1"

    @pytest.mark.asyncio
    async def test_submit_without_video_keeps_legacy_body(self, monkeypatch):
        """不传 video_url 时请求体与既有文生/图生视频完全一致（向后兼容）。"""
        captured = {}

        async def fake_post_json(url, headers, body, timeout=60.0):
            captured.update(body=body)
            return 200, {"output": {"task_id": "wan-2"}}

        monkeypatch.setattr(proto_mod, "_post_json", fake_post_json)
        await submit_video(_creds("wan", "wan3.0-t2v-bundle"), "p")
        assert "video_url" not in captured["body"]["input"]


class TestSeedanceVideoToVideo:
    @pytest.mark.asyncio
    async def test_submit_content_roles_video_first_last(self, monkeypatch):
        captured = {}

        async def fake_post_json(url, headers, body, timeout=60.0):
            captured.update(url=url, body=body)
            return 200, {"id": "sd-1"}

        monkeypatch.setattr(proto_mod, "_post_json", fake_post_json)
        out = await submit_video(
            _creds("seedance2", "doubao-seedance-1-0-lite"), "镜头推进",
            video_url="https://x/source.mp4",
            ref_images=["https://x/first.png"],
            last_frame="https://x/end.png",
        )
        assert captured["url"].endswith("/api/v3/contents/generations/tasks")
        content = captured["body"]["content"]
        by_type = {item.get("type"): item for item in content}
        # 源视频：type=video_url（role=reference_video）
        assert by_type["video_url"]["role"] == "reference_video"
        assert by_type["video_url"]["video_url"]["url"] == "https://x/source.mp4"
        # 首帧/尾帧（imageUrl/endImageUrl）角色语义
        assert by_type["image_url"]["role"] in ("first_frame", "last_frame")
        roles = [item.get("role") for item in content if item.get("type") == "image_url"]
        assert roles == ["first_frame", "last_frame"]
        assert out["task_id"] == "sd-1"


class TestVeoVideoToVideo:
    @pytest.mark.asyncio
    async def test_submit_instance_carries_video_and_frames(self, monkeypatch):
        captured = {}

        async def fake_post_json(url, headers, body, timeout=60.0):
            captured.update(url=url, body=body)
            return 200, {"name": "op-1"}

        async def fake_binary(url, headers=None, timeout=30.0):
            return b"VIDEOBYTES"

        monkeypatch.setattr(proto_mod, "_post_json", fake_post_json)
        monkeypatch.setattr(proto_mod, "_get_binary", fake_binary)
        out = await submit_video(
            _creds("veo", "veo-3.1-generate-preview"), "extend the shot",
            video_url="https://x/source.mp4",
            ref_images=["https://x/first.png"],
            last_frame="https://x/end.png",
        )
        assert captured["url"].endswith("/models/veo-3.1-generate-preview:predictLongRunning")
        instance = captured["body"]["instances"][0]
        # 源视频 → instance.video（base64 字节 + mime）
        assert instance["video"]["bytesBase64Encoded"] == base64.b64encode(b"VIDEOBYTES").decode()
        assert instance["video"]["mimeType"] == "video/mp4"
        # 首帧/尾帧（imageUrl/endImageUrl）→ image / lastFrame
        assert "bytesBase64Encoded" in instance["image"]
        assert "bytesBase64Encoded" in instance["lastFrame"]
        assert out["task_id"] == "op-1"


class TestVideoWaitPassthrough:
    @pytest.mark.asyncio
    async def test_generate_video_wait_passes_video_url(self, monkeypatch):
        captured = {}

        async def fake_submit(creds, prompt, duration=5, resolution="1080p",
                              ref_images=None, audio=None, timeout=60.0,
                              last_frame=None, video_url=None):
            captured.update(video_url=video_url, ref_images=ref_images,
                            last_frame=last_frame)
            return {"task_id": "t-1", "poll_url": "https://x/tasks/t-1"}

        async def fake_poll(creds, task_id, poll_url=""):
            return {"status": "succeeded", "video_url": "https://x/out.mp4", "raw": {}}

        monkeypatch.setattr(proto_mod, "submit_video", fake_submit)
        monkeypatch.setattr(proto_mod, "poll_video", fake_poll)
        result = await generate_video_wait(
            _creds("wan", "wan2.7-videoedit"), "p",
            video_url="https://x/source.mp4",
            ref_images=["https://x/first.png"],
            last_frame="https://x/end.png",
        )
        assert result["status"] == "succeeded"
        assert captured["video_url"] == "https://x/source.mp4"
        assert captured["ref_images"] == ["https://x/first.png"]
        assert captured["last_frame"] == "https://x/end.png"


class TestFacadeV2VDispatch:
    """facade 按用户传入模型/协议分派；未指定默认 dashscope-wan 先验证。"""

    async def _run(self, monkeypatch, tmp_path, model="", extra_params=None):
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators.base import GenerationConfig, GeneratorType
        from neurova.llm.generators.runtime import ProtocolGenerator

        captured = {}

        def fake_resolve(protocol_hint, model, provider_id, api_key, base_url, default_base):
            captured["protocol"] = protocol_hint
            captured["model"] = model
            return ProtocolCredentials(api_key="k", base_url="https://x",
                                       model=model or "", protocol=protocol_hint)

        async def fake_wait(creds, prompt, duration=5, resolution="1080p",
                            ref_images=None, audio=None, max_wait=900.0,
                            last_frame=None, video_url=None):
            captured["ref_images"] = ref_images
            captured["last_frame"] = last_frame
            captured["video_url"] = video_url
            return {"status": "succeeded", "video_url": "https://x/out.mp4", "raw": {}}

        async def fake_persist(url_or_data, kind, task_id, index, out_dir=None):
            p = tmp_path / f"art_{index}.mp4"
            p.write_bytes(b"MP4")
            return str(p)

        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        monkeypatch.setattr(gen_runtime.protocols, "generate_video_wait", fake_wait)
        monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)

        config = GenerationConfig(
            type=GeneratorType.VIDEO_TO_VIDEO,
            prompt="镜头推进",
            model=model,
            video_url="https://x/source.mp4",
            image_url="https://x/first.png",
            end_image_url="https://x/end.png",
            extra_params=extra_params or {},
        )
        result = await ProtocolGenerator().generate(config)
        return result, captured

    @pytest.mark.asyncio
    async def test_seedance_model_dispatches_seedance2(self, monkeypatch, tmp_path):
        result, captured = await self._run(
            monkeypatch, tmp_path, model="doubao-seedance-1-0-lite")
        assert result.success, result.error
        assert captured["protocol"] == "seedance2"
        assert captured["video_url"] == "https://x/source.mp4"
        assert captured["ref_images"] == ["https://x/first.png"]
        assert captured["last_frame"] == "https://x/end.png"

    @pytest.mark.asyncio
    async def test_veo_model_dispatches_veo(self, monkeypatch, tmp_path):
        result, captured = await self._run(
            monkeypatch, tmp_path, model="veo-3.1-generate-preview")
        assert result.success, result.error
        assert captured["protocol"] == "veo"

    @pytest.mark.asyncio
    async def test_protocol_label_overrides_dispatch(self, monkeypatch, tmp_path):
        result, captured = await self._run(
            monkeypatch, tmp_path, model="", extra_params={"protocol": "veo"})
        assert result.success, result.error
        assert captured["protocol"] == "veo"

    @pytest.mark.asyncio
    async def test_unspecified_defaults_to_dashscope_wan(self, monkeypatch, tmp_path):
        result, captured = await self._run(monkeypatch, tmp_path, model="")
        assert result.success, result.error
        assert captured["protocol"] == "wan"

    @pytest.mark.asyncio
    async def test_v2v_is_no_longer_rejected_as_unsupported(self, monkeypatch, tmp_path):
        """改前 facade 对 video_to_video 恒回「无实测协议支撑」——现在必须真提交。"""
        result, captured = await self._run(
            monkeypatch, tmp_path, model="wan2.7-videoedit")
        assert result.success, result.error
        assert result.urls and result.metadata["protocol"] == "wan"
        assert captured["video_url"] == "https://x/source.mp4"
