# -*- coding: utf-8 -*-
"""B2-a/b/c 生成协议/账本/端点测试（QwenPaw Creator 实测矩阵对齐）。

锁定契约：
1. URL 拼接规则（6 协议，禁止虚构端点）。
2. 协议解析：显式标签（含中文）→ model/base_url 探测 → 默认。
3. 请求体结构（wan/seedance2/veo 提交体、dashscope 图像体）。
4. 任务账本：add/update/get/list/unfinished + 原子落盘 + 重启恢复。
5. REST：/generation/image 与 /video 不再 501；参数面齐全；
   video 提交走账本，status 端点轮询。
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from neurova.llm.generators.task_ledger import TaskRecord
from neurova.llm.generators.protocols import (
    ImageProtocol,
    ProtocolCredentials,
    VideoProtocol,
    agnes_poll_url,
    agnes_video_body,
    agnes_videos_url,
    ark_images_url,
    dashscope_tasks_url,
    openai_images_url,
    resolve_image_protocol,
    resolve_video_protocol,
    seedance_poll_url,
    seedance_submit_url,
    veo_submit_url,
    wan_submit_url,
    _dashscope_image_body,
)


class TestImageUrlRules:
    def test_openai_base_with_v1(self):
        assert openai_images_url("https://api.openai.com/v1") == "https://api.openai.com/v1/images/generations"

    def test_openai_base_without_v1(self):
        assert openai_images_url("https://gw.example.com") == "https://gw.example.com/v1/images/generations"

    def test_ark_base(self):
        assert ark_images_url("https://ark.cn-beijing.volces.com") == "https://ark.cn-beijing.volces.com/api/v3/images/generations"

    def test_ark_base_with_api_v3(self):
        assert ark_images_url("https://ark.cn-beijing.volces.com/api/v3") == "https://ark.cn-beijing.volces.com/api/v3/images/generations"

    def test_dashscope_poll(self):
        assert dashscope_tasks_url("https://dashscope.aliyuncs.com/api/v1", "t1") == \
            "https://dashscope.aliyuncs.com/api/v1/tasks/t1"


class TestVideoUrlRules:
    def test_wan_submit(self):
        assert wan_submit_url("https://dashscope.aliyuncs.com/api/v1") == \
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
        assert wan_submit_url("") == \
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"

    def test_seedance(self):
        base = "https://ark.cn-beijing.volces.com"
        assert seedance_submit_url(base) == f"{base}/api/v3/contents/generations/tasks"
        assert seedance_poll_url(base, "t9") == f"{base}/api/v3/contents/generations/tasks/t9"

    def test_veo_submit_autocompletes_v1beta(self):
        url = veo_submit_url("https://generativelanguage.googleapis.com", "veo-3.1-generate-preview")
        assert url == "https://generativelanguage.googleapis.com/v1beta/models/veo-3.1-generate-preview:predictLongRunning"

    def test_veo_submit_with_base_containing_v1beta(self):
        base = "https://generativelanguage.googleapis.com/v1beta"
        assert veo_submit_url(base, "veo-x") == f"{base}/models/veo-x:predictLongRunning"

    # ── Agnes 视频（2026-09-14 官方仓 AgnesAI-Labs/AgnesAI-Models 实核）──

    def test_agnes_videos_url_gw_base_and_root_base(self):
        """提交 POST {root}/v1/videos——base 已含 /v1 时不重复拼。"""
        assert agnes_videos_url("https://apihub.agnes-ai.com/v1") == \
            "https://apihub.agnes-ai.com/v1/videos"
        assert agnes_videos_url("https://apihub.agnes-ai.com") == \
            "https://apihub.agnes-ai.com/v1/videos"

    def test_agnes_poll_url_uses_root_agnesapi_video_id(self):
        """轮询走独立端点 GET {root}/agnesapi?video_id=…（不在 /v1 下，
        官方明示勿用 task_id）——与 WAN/Seedance 的 tasks 形态全不同。"""
        assert agnes_poll_url("https://apihub.agnes-ai.com/v1", "vid123") == \
            "https://apihub.agnes-ai.com/agnesapi?video_id=vid123"

    def test_agnes_video_body_pixel_frames(self):
        """请求体=像素尺寸+帧数，无 OpenAI Sora 的 mode 字段
        （此前按 mode 形态探测恒报 invalid mode 的根因）；
        num_frames 换算以官方示例为准：5s@24fps → 121。"""
        body = agnes_video_body(
            model="agnes-video-v2.0", prompt="p", duration=5, resolution="1080p",
        )
        assert body["model"] == "agnes-video-v2.0"
        assert body["prompt"] == "p"
        assert body["frame_rate"] == 24
        assert body["num_frames"] == 121
        assert "mode" not in body
        assert (body["width"], body["height"]) == (1920, 1080)

    def test_agnes_video_body_default_resolution_matches_official_example(self):
        body = agnes_video_body(model="m", prompt="p", duration=5, resolution="")
        assert (body["width"], body["height"]) == (1152, 768)

    def test_agnes_protocol_resolution(self):
        assert resolve_video_protocol("agnes") is VideoProtocol.AGNES
        assert resolve_video_protocol("", "agnes-video-v2.0") is VideoProtocol.AGNES
        assert resolve_video_protocol("", "t2v", "https://apihub.agnes-ai.com/v1") is VideoProtocol.AGNES


class TestProtocolResolution:
    def test_image_explicit_labels(self):
        assert resolve_image_protocol("dashscope") is ImageProtocol.DASHSCOPE
        assert resolve_image_protocol("百炼") is ImageProtocol.DASHSCOPE
        assert resolve_image_protocol("ark") is ImageProtocol.ARK
        assert resolve_image_protocol("火山") is ImageProtocol.ARK
        assert resolve_image_protocol("openai") is ImageProtocol.OPENAI_COMPAT

    def test_image_model_probe(self):
        assert resolve_image_protocol("", "doubao-seedream-4.0", "") is ImageProtocol.ARK
        assert resolve_image_protocol("", "qwen-image-plus", "") is ImageProtocol.DASHSCOPE
        assert resolve_image_protocol("", "", "https://volces.com/api/v3") is ImageProtocol.ARK

    def test_image_default(self):
        assert resolve_image_protocol() is ImageProtocol.OPENAI_COMPAT

    def test_video_explicit(self):
        assert resolve_video_protocol("wan") is VideoProtocol.WAN
        assert resolve_video_protocol("seedance2") is VideoProtocol.SEEDANCE2
        assert resolve_video_protocol("veo") is VideoProtocol.VEO

    def test_video_model_probe(self):
        assert resolve_video_protocol("", "wan3.0-t2v-bundle") is VideoProtocol.WAN
        assert resolve_video_protocol("", "doubao-seedance-1-0-lite") is VideoProtocol.SEEDANCE2
        assert resolve_video_protocol("", "veo-3.1") is VideoProtocol.VEO


class TestRequestBodyRules:
    def test_dashscope_image_body_structure(self):
        body = _dashscope_image_body("qwen-image-plus", "一只猫", "1024x1024", 2, [])
        assert body["model"] == "qwen-image-plus"
        assert body["input"]["messages"][0]["content"][-1] == {"text": "一只猫"}
        assert body["parameters"] == {"n": 2, "size": "1024x1024"}

    def test_dashscope_ref_image_order(self):
        body = _dashscope_image_body("m", "p", "", 1, ["https://x/a.png"])
        content = body["input"]["messages"][0]["content"]
        assert content == [{"image": "https://x/a.png"}, {"text": "p"}]


class TestTaskLedger:
    @pytest.fixture
    def ledger(self, tmp_path, monkeypatch):
        from neurova.llm.generators import task_ledger as mod
        from neurova.llm.generators.task_ledger import TaskRecord

        monkeypatch.setattr(mod, "DEFAULT_LEDGER_PATH", tmp_path / "tasks.json")
        mod.reset_generation_task_ledger()
        return mod.get_generation_task_ledger()

    def test_add_assigns_id_and_persists(self, ledger, tmp_path):
        rec = ledger.add(TaskRecord(kind="video", provider_id="p1", protocol="wan", remote_task_id="r1"))
        assert rec.task_id
        data = json.loads((tmp_path / "tasks.json").read_text(encoding="utf-8"))
        assert data[rec.task_id]["remote_task_id"] == "r1"

    def test_update_status(self, ledger):
        rec = ledger.add(TaskRecord(kind="video", remote_task_id="r2"))
        ledger.update(rec.task_id, status="running")
        assert ledger.get(rec.task_id).status == "running"

    def test_unfinished_for_restart_recovery(self, ledger):
        a = ledger.add(TaskRecord(kind="video", remote_task_id="ra"))
        b = ledger.add(TaskRecord(kind="video", remote_task_id="rb"))
        ledger.update(a.task_id, status="succeeded")
        unfinished = ledger.unfinished()
        assert [t.task_id for t in unfinished] == [b.task_id]

    def test_list_filter_by_status(self, ledger):
        a = ledger.add(TaskRecord(kind="video", remote_task_id="ra"))
        ledger.add(TaskRecord(kind="video", remote_task_id="rb"))
        ledger.update(a.task_id, status="failed")
        assert len(ledger.list(status="failed")) == 1

    def test_corrupt_file_boots_empty(self, tmp_path, monkeypatch):
        from neurova.llm.generators import task_ledger as mod
        from neurova.llm.generators.task_ledger import TaskRecord

        bad = tmp_path / "bad.json"
        bad.write_text("{corrupt", encoding="utf-8")
        monkeypatch.setattr(mod, "DEFAULT_LEDGER_PATH", bad)
        mod.reset_generation_task_ledger()
        led = mod.get_generation_task_ledger()
        assert led.list() == []


class TestGenerationEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from neurova.api.app import create_app

        app = create_app()
        # generation 路由已加路由级鉴权（凭据盗刷面收口，见 generation.py
        # P0-2 注释，用的是 neurova.api.deps.get_current_user）——
        # 单测 override 后专注端点契约本身
        from neurova.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {"user_id": "t"}
        return TestClient(app)

    def test_image_endpoint_no_longer_501(self, client):
        """B2-c：图像端点必须脱离 501（无凭据时诚实 400）。"""
        resp = client.post("/api/v1/generation/image", json={"prompt": "a cat"})
        assert resp.status_code in (200, 400, 502)

    def test_video_endpoint_no_longer_501(self, client):
        resp = client.post("/api/v1/generation/video", json={"prompt": "a cat runs"})
        assert resp.status_code in (200, 400, 502)

    def test_video_request_params_accepted(self, client):
        """参数面契约：protocol/provider_id/ref_images/audio 字段可接收。"""
        resp = client.post("/api/v1/generation/video", json={
            "prompt": "p", "protocol": "wan", "provider_id": "nope",
            "ref_images": ["https://x/a.png"], "audio": True, "duration": 5,
            "resolution": "1080p",
        })
        # provider_id 不存在 → 凭据缺失 400（契约：诚实报错而非 422 参数拒绝）
        assert resp.status_code == 400
        assert "凭据" in resp.json()["detail"]


class TestDialogueSync:
    """B2-d（#7167）：脚本对白带入提示词 + 逐字校验守卫。"""

    def test_dialogue_appended_verbatim(self):
        from neurova.llm.generators.protocols import build_video_prompt_with_dialogue

        prompt = build_video_prompt_with_dialogue("雨夜街道，主角奔跑", ["他回来了。", "别跟着我。"])
        assert "他回来了。" in prompt
        assert "别跟着我。" in prompt
        assert "逐字" in prompt

    def test_empty_dialogue_returns_original(self):
        from neurova.llm.generators.protocols import build_video_prompt_with_dialogue

        assert build_video_prompt_with_dialogue("p", []) == "p"

    def test_guard_detects_missing_dialogue(self):
        from neurova.llm.generators.protocols import check_dialogue_presence

        result = check_dialogue_presence("prompt without dialogue", ["关键台词。"])
        assert result["ok"] is False
        assert result["missing_narrative_dialogue"] == ["关键台词。"]

    def test_guard_passes_when_present(self):
        from neurova.llm.generators.protocols import (
            build_video_prompt_with_dialogue,
            check_dialogue_presence,
        )

        prompt = build_video_prompt_with_dialogue("场景", ["台词一。"])
        result = check_dialogue_presence(prompt, ["台词一。"])
        assert result["ok"] is True


# ── 2026-09-15 SORA 协议补录（OpenAI 官方 SDK videos.py 实核契约）──────────────
# POST {base}/videos multipart（prompt/model/seconds∈{4,8,12}/size/input_reference）
# → GET {base}/videos/{id}（queued/in_progress/completed/failed + progress）
# → GET {base}/videos/{id}/content 二进制下载（无公开产物 URL →
#   轮询成功转 data URL 交 persist_media 落盘）。事实源：openai-python
#   src/openai/resources/videos.py + types/video.py（sora-2/sora-2-pro）。
from neurova.llm.generators import protocols as proto


class TestSoraProtocolMatrix:
    def test_resolve_sora_by_model_name(self):
        assert proto.resolve_video_protocol("", "sora-2-pro", "") == proto.VideoProtocol.SORA
        assert proto.resolve_video_protocol("", "Sora 2 Pro", "") == proto.VideoProtocol.SORA

    def test_resolve_sora_explicit_label(self):
        assert proto.resolve_video_protocol("sora", "", "") == proto.VideoProtocol.SORA

    def test_openai_base_alone_not_sora(self):
        # openai 域名单独不足以判 Sora（兼容网关多用该域名）——以模型名为准
        assert proto.resolve_video_protocol("", "my-video", "https://api.openai.com/v1") \
            == proto.VideoProtocol.WAN

    def test_sora_urls(self):
        assert proto.sora_videos_url("https://api.openai.com/v1") == \
            "https://api.openai.com/v1/videos"
        assert proto.sora_videos_url("https://gw.example.com") == \
            "https://gw.example.com/v1/videos"
        assert proto.sora_video_poll_url("https://api.openai.com/v1", "vid_1") == \
            "https://api.openai.com/v1/videos/vid_1"
        assert proto.sora_video_content_url("https://api.openai.com/v1", "vid_1") == \
            "https://api.openai.com/v1/videos/vid_1/content"

    def test_sora_seconds_snap_size_map(self):
        assert proto.sora_seconds(5) == "4"    # 官方 4/8/12 三档就近取整
        assert proto.sora_seconds(10) == "8"   # 平距取低档
        assert proto.sora_seconds(30) == "12"
        assert proto.sora_size("1080p") == "1792x1024"
        assert proto.sora_size("720p") == "1280x720"
        assert proto.sora_size("") == "1280x720"

    @pytest.mark.asyncio
    async def test_submit_sora_multipart_fields_and_ignored(self, monkeypatch):
        captured = {}

        async def fake_post_form(url, headers, fields, files, timeout=60.0):
            captured.update(url=url, fields=dict(fields), files=list(files))
            return 200, {"id": "vid_9", "status": "queued"}

        async def fake_binary(url, headers=None, timeout=30.0):
            return b"PNG-BYTES"

        monkeypatch.setattr(proto, "_post_form", fake_post_form)
        monkeypatch.setattr(proto, "_get_binary", fake_binary)
        creds = ProtocolCredentials(api_key="k", base_url="https://api.openai.com/v1",
                                    model="sora-2-pro", protocol="sora")
        out = await proto.submit_video(
            creds, "cat in rain", duration=5, resolution="1080p",
            ref_images=["https://cdn/x.png"], audio=True, last_frame="C:/tmp/end.png")
        assert out["task_id"] == "vid_9"
        assert out["poll_url"] == "https://api.openai.com/v1/videos/vid_9"
        assert captured["url"] == "https://api.openai.com/v1/videos"
        assert captured["fields"] == {"model": "sora-2-pro", "prompt": "cat in rain",
                                      "seconds": "4", "size": "1792x1024"}
        # Sora 参考图仅一个槽位 input_reference；http 引用服务端取字节进 multipart
        assert captured["files"][0][0] == "input_reference"
        assert captured["files"][0][2] == b"PNG-BYTES"
        ignored = out.get("ignored_params") or []
        assert "audio" in ignored and "last_frame" in ignored

    @pytest.mark.asyncio
    async def test_submit_sora_local_ref_file_bytes(self, tmp_path, monkeypatch):
        p = tmp_path / "ref.png"
        p.write_bytes(b"LOCALPNG")
        captured = {}

        async def fake_post_form(url, headers, fields, files, timeout=60.0):
            captured["files"] = list(files)
            return 200, {"id": "v"}

        monkeypatch.setattr(proto, "_post_form", fake_post_form)
        creds = ProtocolCredentials(api_key="k", base_url="https://api.openai.com/v1",
                                    model="sora-2", protocol="sora")
        await proto.submit_video(creds, "p", ref_images=[str(p)])
        assert captured["files"][0][0] == "input_reference"
        assert captured["files"][0][2] == b"LOCALPNG"

    @pytest.mark.asyncio
    async def test_poll_sora_completed_downloads_content_as_data_url(self, monkeypatch):
        seen = {}

        async def fake_get_json(url, headers, timeout=30.0):
            seen["poll"] = url
            return 200, {"id": "vid_1", "status": "completed", "progress": 100}

        async def fake_binary(url, headers=None, timeout=30.0):
            seen["content"] = url
            return b"MP4-BYTES"

        monkeypatch.setattr(proto, "_get_json", fake_get_json)
        monkeypatch.setattr(proto, "_get_binary", fake_binary)
        creds = ProtocolCredentials(api_key="k", base_url="https://api.openai.com/v1",
                                    model="sora-2", protocol="sora")
        r = await proto.poll_video(creds, "vid_1")
        assert r["status"] == "succeeded"
        assert r["video_url"].startswith("data:video/mp4;base64,")
        assert seen["poll"] == "https://api.openai.com/v1/videos/vid_1"
        assert seen["content"] == "https://api.openai.com/v1/videos/vid_1/content"

    @pytest.mark.asyncio
    async def test_poll_sora_in_progress_running(self, monkeypatch):
        async def fake_get_json(url, headers, timeout=30.0):
            return 200, {"status": "in_progress", "progress": 33}

        monkeypatch.setattr(proto, "_get_json", fake_get_json)
        creds = ProtocolCredentials(api_key="k", base_url="https://api.openai.com/v1",
                                    model="sora-2", protocol="sora")
        r = await proto.poll_video(creds, "vid_1")
        assert r["status"] == "running"

    @pytest.mark.asyncio
    async def test_poll_sora_failed_carries_error(self, monkeypatch):
        async def fake_get_json(url, headers, timeout=30.0):
            return 200, {"status": "failed", "error": {"message": "safety violation"}}

        monkeypatch.setattr(proto, "_get_json", fake_get_json)
        creds = ProtocolCredentials(api_key="k", base_url="https://api.openai.com/v1",
                                    model="sora-2", protocol="sora")
        r = await proto.poll_video(creds, "vid_1")
        assert r["status"] == "failed"
        assert "safety violation" in r["error"]
