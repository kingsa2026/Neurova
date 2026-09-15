# -*- coding: utf-8 -*-
"""批次1：AIGC 端点 P0 契约修复回归（auto 路由 / 音频 JSON / 图像落账本 / 账本路径）。

锁定契约（对标 PRINTFILM 工具中心 + 实测缺陷）：
1. /generation/image、/generation/video 的 model 空或 "auto" → LLMRouter 按
   text_to_image/image_to_video 等真实请求类型选模（原实现把 "auto" 当真实模型名
   且覆盖服务商默认模型，必然 4xx）；
2. /generation/audio 统一 JSON 契约（产物落盘 + data.url）并落账本 kind="audio"
   （原实现返回二进制而前端按 JSON 取 → 恒空）；
3. /generation/image 成功/失败均落任务账本 kind="image"（历史面板数据源）；
4. 账本默认路径与产物目录同源（仓库根绝对路径，原 CWD 相对在异目录启动下分裂）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import generation as generation_ep
from neurova.llm import llm_router
from neurova.llm.generators import runtime as gen_runtime
from neurova.llm.generators import task_ledger as ledger_mod
from neurova.llm.generators.protocols import ProtocolCredentials
from neurova.llm.generators.task_ledger import GenerationTaskLedger


@pytest.fixture()
def routed_router():
    """注册含图像/视频生成能力的模型到全局 router。"""
    llm_router._router_instance = None
    llm_router.LLMRouter._instance = None
    llm_router.register_provider_from_config(
        "prov-img",
        "ImgProv",
        ["deepseek-chat", "flux.1-dev", "wan2.2-t2v"],
        {
            "deepseek-chat": {"capabilities": ["text"]},
            "flux.1-dev": {"capabilities": ["image_generation"]},
            "wan2.2-t2v": {"capabilities": ["video_generation"]},
        },
    )
    yield llm_router.get_llm_router()
    llm_router._router_instance = None
    llm_router.LLMRouter._instance = None


@pytest.fixture()
def tmp_ledger(tmp_path, monkeypatch):
    """隔离账本单例到 tmp。"""
    led = GenerationTaskLedger(path=str(tmp_path / "tasks.json"))
    monkeypatch.setattr(ledger_mod, "_ledger", led)
    yield led
    monkeypatch.setattr(ledger_mod, "_ledger", None)


@pytest.fixture()
def client(routed_router, tmp_ledger, tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(generation_ep.router, prefix="/api/v1/generation")
    from neurova.api.deps import get_current_user as _gcu_deps

    app.dependency_overrides[_gcu_deps] = lambda: {
        "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
    }
    monkeypatch.setattr(generation_ep, "_GENERATION_OUTPUT_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


class TestImageAutoRoute:
    def test_auto_routes_to_image_capable_model(self, client, monkeypatch, tmp_ledger):
        captured = {}

        def fake_resolve(protocol_hint, model, provider_id, api_key, base_url, default_base):
            captured["model"] = model
            captured["provider_id"] = provider_id
            return ProtocolCredentials(api_key="k", base_url="https://gw.test/v1",
                                       model=model or "", protocol=protocol_hint)

        async def fake_generate_image(creds, prompt, **kw):
            return {"images": ["data:image/png;base64," + json.dumps("x").encode().hex()], "task_id": None, "raw": {}}

        async def fake_persist(url_or_data, kind, task_id, index, out_dir=None):
            p = Path(out_dir or gen_runtime.GENERATION_OUTPUT_DIR) / f"art_{index}.png"
            p.write_bytes(b"PNG")
            return str(p)

        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        from neurova.llm.generators import protocols as proto_mod
        monkeypatch.setattr(proto_mod, "generate_image", fake_generate_image)
        monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)

        resp = client.post("/api/v1/generation/image", json={"prompt": "一只猫", "model": "auto"})
        assert resp.status_code == 200, resp.text
        assert captured["model"] == "flux.1-dev", (
            f'"auto" 必须经 LLMRouter 换成真实图像模型，实得 {captured["model"]!r}')
        assert captured["provider_id"] == "prov-img"
        data = resp.json()["data"]
        assert data["images"] and data["images"][0]["url"].startswith("/api/v1/generation/files/")

        # 图像任务必须落账本（历史面板数据源）
        image_tasks = [t for t in tmp_ledger.list() if t.kind == "image"]
        assert len(image_tasks) == 1
        assert image_tasks[0].status == "succeeded"
        assert image_tasks[0].owner_user_id == "tuser"

    def test_explicit_model_skips_routing(self, client, monkeypatch, tmp_ledger, tmp_path):
        captured = {}

        def fake_resolve(protocol_hint, model, provider_id, api_key, base_url, default_base):
            captured["model"] = model
            return ProtocolCredentials(api_key=api_key or "k", base_url=base_url or "https://x",
                                       model=model, protocol=protocol_hint)

        async def fake_generate_image(creds, prompt, **kw):
            return {"images": ["http://cdn/a.png"], "task_id": None, "raw": {}}

        async def fake_persist(url_or_data, kind, task_id, index, out_dir=None):
            p = tmp_path / "art.png"
            p.write_bytes(b"P")
            return str(p)

        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        from neurova.llm.generators import protocols as proto_mod
        monkeypatch.setattr(proto_mod, "generate_image", fake_generate_image)
        monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)

        resp = client.post("/api/v1/generation/image",
                           json={"prompt": "p", "model": "my-seedream", "api_key": "sk",
                                 "base_url": "https://x/v1"})
        assert resp.status_code == 200
        assert captured["model"] == "my-seedream"

    def test_image_failure_records_ledger_failed(self, client, monkeypatch, tmp_ledger):
        def fake_resolve(*a, **k):
            return ProtocolCredentials(api_key="k", base_url="https://gw.test/v1",
                                       model="m", protocol="openai_compat")

        async def boom(creds, prompt, **kw):
            raise RuntimeError("上游 401 余额不足")

        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        from neurova.llm.generators import protocols as proto_mod
        monkeypatch.setattr(proto_mod, "generate_image", boom)

        resp = client.post("/api/v1/generation/image", json={"prompt": "p"})
        assert resp.status_code == 502  # 诚实 5xx，不伪造成功
        failed = [t for t in tmp_ledger.list() if t.kind == "image"]
        assert len(failed) == 1
        assert failed[0].status == "failed"
        assert "余额" in failed[0].error


class TestVideoAutoRoute:
    def test_video_auto_routes_to_video_capable_model(self, client, monkeypatch, tmp_ledger):
        captured = {}

        def fake_resolve(protocol_hint, model, provider_id, api_key, base_url, default_base):
            captured["model"] = model
            captured["provider_id"] = provider_id
            return ProtocolCredentials(api_key="k", base_url="https://x", model=model or "",
                                       protocol=protocol_hint)

        async def fake_submit(creds, prompt, **kw):
            return {"task_id": "remote-1", "poll_url": "https://x/tasks/remote-1"}

        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        from neurova.llm.generators import protocols as proto_mod
        monkeypatch.setattr(proto_mod, "submit_video", fake_submit)

        resp = client.post("/api/v1/generation/video", json={"prompt": "p", "model": "auto"})
        assert resp.status_code == 200, resp.text
        assert captured["model"] == "wan2.2-t2v", (
            f'video auto 必须经 LLMRouter 换成真实视频模型，实得 {captured["model"]!r}')
        assert captured["provider_id"] == "prov-img"
        rec = tmp_ledger.get(resp.json()["data"]["task_id"])
        assert rec.model == "wan2.2-t2v"
        # 轮询凭闭环：账本必须落 routed 的 provider_id（settle_video_record 凭它
        # 重取 api_key，账本不存 key）——auto 模式下漏写即轮询恒 401
        assert rec.provider_id == "prov-img"


class TestAudioJsonContract:
    def test_audio_returns_json_url_and_ledger(self, client, monkeypatch, tmp_ledger, tmp_path):
        from types import SimpleNamespace

        class FakeEngine:
            def is_available(self):
                return True

            async def process(self, input_data, operation, voice, speed):
                return SimpleNamespace(error=None, audio_data=b"RIFF-wav-bytes")

        state = {"voice_engines": {"tts": FakeEngine()}}
        monkeypatch.setattr(generation_ep, "get_app_state", lambda: state)

        resp = client.post("/api/v1/generation/audio", json={"text": "你好", "voice": "v"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        url = body["data"]["url"]
        assert url.startswith("/api/v1/generation/files/"), f"应为 JSON url 契约，实得 {body}"
        assert url.endswith(".wav")
        local = body["data"]["path"]
        assert Path(local).is_file() and Path(local).read_bytes() == b"RIFF-wav-bytes"
        aud = [t for t in tmp_ledger.list() if t.kind == "audio"]
        assert len(aud) == 1 and aud[0].status == "succeeded"

    def test_audio_unready_engine_honest_error(self, client, monkeypatch):
        monkeypatch.setattr(generation_ep, "get_app_state", lambda: {})
        resp = client.post("/api/v1/generation/audio", json={"text": "x"})
        assert resp.status_code == 200
        assert resp.json()["code"] == -1  # 诚实失败语义不变


class TestLedgerPathSingleSource:
    def test_default_ledger_path_absolute(self):
        p = Path(ledger_mod.DEFAULT_LEDGER_PATH)
        assert p.is_absolute(), f"账本路径不得 CWD 相对：{p}"
        assert p == gen_runtime.PROJECT_ROOT / "data" / "generation_tasks.json"
