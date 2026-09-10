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
