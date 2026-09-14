# -*- coding: utf-8 -*-
"""R2：生成参数按服务商能力自适应路由 + /generation/voices 真实音色。

契约（用户决策 2026-09-14：对不同服务商做适配，不行做路由自动适配）：
- seed/strength 透传给支持它的协议（ARK/DASHSCOPE seed），不支持的参数
  进入返回 ignored_params（不假生效、不静默丢弃）；
- 端点把 ignored_params 写入任务账本并在 /tasks 透出，前端可见；
- GET /generation/voices 返回引擎真实音色列表（引擎不可用返回空数组——
  诚实空，不硬编码假列表；前端原 alloy/echo 列表即假列表）。
"""
from __future__ import annotations

import pytest

from neurova.llm.generators.protocols import (
    ProtocolCredentials, _ark_image_generate, _openai_image_generate,
    _dashscope_image_generate,
)

pytestmark = pytest.mark.timeout(60)


class TestSeedStrengthCapabilityRouting:
    @pytest.mark.asyncio
    async def test_ark_supports_seed_ignores_strength(self, monkeypatch):
        captured = {}

        async def fake_post(url, headers, body, timeout=60.0):
            captured["body"] = body
            return 200, {"data": [{"url": "http://cdn/a.png"}]}

        from neurova.llm.generators import protocols as p
        monkeypatch.setattr(p, "_post_json", fake_post)
        creds = ProtocolCredentials(api_key="k", base_url="https://ark.test",
                                    model="seedream-4", protocol="ark")
        out = await _ark_image_generate(creds, "p", "1024x1024", 1, [], 60.0,
                                        seed=42, strength=0.7)
        assert captured["body"].get("seed") == 42
        assert "strength" in (out.get("ignored_params") or [])

    @pytest.mark.asyncio
    async def test_dashscope_supports_seed(self, monkeypatch):
        captured = {}

        async def fake_post(url, headers, body, timeout=60.0):
            captured["body"] = body
            return 200, {"output": {"results": [{"url": "http://cdn/a.png"}]}}

        from neurova.llm.generators import protocols as p
        monkeypatch.setattr(p, "_post_json", fake_post)
        creds = ProtocolCredentials(api_key="k", base_url="https://dashscope.test",
                                    model="wan2.2-t2i", protocol="dashscope")
        out = await _dashscope_image_generate(creds, "p", "1024x1024", 1, [], 60.0,
                                              seed=7, strength=None)
        assert captured["body"].get("parameters", {}).get("seed") == 7

    @pytest.mark.asyncio
    async def test_openai_ignores_both_honestly(self, monkeypatch):
        async def fake_post(url, headers, body, timeout=60.0):
            return 200, {"data": [{"url": "http://cdn/a.png"}]}

        from neurova.llm.generators import protocols as p
        monkeypatch.setattr(p, "_post_json", fake_post)
        creds = ProtocolCredentials(api_key="k", base_url="https://a.test/v1",
                                    model="gpt-image-1", protocol="openai_compat")
        out = await _openai_image_generate(creds, "p", "1024x1024", 1, [], 60.0,
                                           seed=42, strength=0.5)
        ignored = out.get("ignored_params") or []
        assert "seed" in ignored and "strength" in ignored

    @pytest.mark.asyncio
    async def test_generate_image_unified_entry_passes_seed(self, monkeypatch):
        seen = {}

        async def fake_ark(creds, prompt, size, n, refs, timeout, seed=None, strength=None):
            seen["seed"] = seed
            seen["strength"] = strength
            return {"images": ["http://c/1.png"], "task_id": None, "raw": {}, "ignored_params": []}

        from neurova.llm.generators import protocols as p
        monkeypatch.setattr(p, "_ark_image_generate", fake_ark)
        creds = ProtocolCredentials(api_key="k", base_url="https://ark.test",
                                    model="seedream", protocol="ark")
        out = await p.generate_image(creds, "p", seed=99, strength=0.3)
        assert seen == {"seed": 99, "strength": 0.3}


class TestVoicesEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch):
        from types import SimpleNamespace

        from neurova.api.endpoints import generation as gen_ep
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(gen_ep.router, prefix="/api/v1/generation")
        from neurova.api.deps import get_current_user as _gcu
        app.dependency_overrides[_gcu] = lambda: {
            "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
        }
        return TestClient(app)

    def test_voices_normalizes_engine_list(self, client, monkeypatch):
        from types import SimpleNamespace

        from neurova.api.endpoints import generation as gen_ep

        class FakeInner:
            async def list_voices(self):
                return [{"ShortName": "zh-CN-XiaoxiaoNeural", "Gender": "Female",
                         "Locale": "zh-CN"}]

        engine = SimpleNamespace(is_available=lambda: True, _engine=FakeInner())
        monkeypatch.setattr(gen_ep, "get_app_state",
                            lambda: {"voice_engines": {"tts": engine}, "tts_manager": None})
        resp = client.get("/api/v1/generation/voices")
        assert resp.status_code == 200
        voices = resp.json()["data"]["voices"]
        assert voices == [{
            "id": "zh-CN-XiaoxiaoNeural",
            "label": "zh-CN-XiaoxiaoNeural（Female zh-CN）",
            "gender": "Female", "locale": "zh-CN",
        }]

    def test_voices_empty_when_engine_unready(self, client, monkeypatch):
        from neurova.api.endpoints import generation as gen_ep

        monkeypatch.setattr(gen_ep, "get_app_state", lambda: {})
        resp = client.get("/api/v1/generation/voices")
        assert resp.status_code == 200
        assert resp.json()["data"]["voices"] == []  # 诚实空列表，非硬编码假列表


class TestLedgerIgnoredParams:
    def test_task_record_field(self):
        from neurova.llm.generators.task_ledger import TaskRecord
        assert TaskRecord().ignored_params == ""

    def test_endpoint_to_tasks_pipeline(self, tmp_path, monkeypatch):
        """/image seed 透传 → 协议忽略标注 → 账本 → /tasks 透出（全链可见）。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.endpoints import generation as gen_ep
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import task_ledger as ledger_mod
        from neurova.llm.generators.protocols import ProtocolCredentials
        from neurova.llm.generators.task_ledger import GenerationTaskLedger

        app = FastAPI()
        app.include_router(gen_ep.router, prefix="/api/v1/generation")
        from neurova.api.deps import get_current_user as _gcu
        app.dependency_overrides[_gcu] = lambda: {
            "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
        }
        led = GenerationTaskLedger(path=str(tmp_path / "t.json"))
        monkeypatch.setattr(ledger_mod, "_ledger", led)
        monkeypatch.setattr(gen_ep, "_GENERATION_OUTPUT_DIR", str(tmp_path))

        monkeypatch.setattr(
            gen_runtime, "resolve_generation_creds",
            lambda *a, **k: ProtocolCredentials(api_key="k", base_url="https://x/v1",
                                                model="gpt-image-1", protocol="openai_compat"))

        async def fake_generate(creds, prompt, **kw):
            return {"images": ["http://cdn/a.png"], "task_id": None, "raw": {},
                    "ignored_params": ["seed", "strength"]}

        async def fake_persist(url, kind, task_id, index, out_dir=None):
            p = tmp_path / "art.png"
            p.write_bytes(b"P")
            return str(p)

        monkeypatch.setattr(proto_mod, "generate_image", fake_generate)
        monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)

        client = TestClient(app)
        resp = client.post("/api/v1/generation/image",
                           json={"prompt": "p", "seed": 42, "strength": 0.5})
        assert resp.status_code == 200
        assert resp.json()["data"]["ignored_params"] == "seed,strength"

        rec = next(t for t in led.list() if t.kind == "image")
        assert rec.ignored_params == "seed,strength"

        tasks = client.get("/api/v1/generation/tasks").json()["data"]["tasks"]
        assert tasks[0]["ignored_params"] == "seed,strength"
