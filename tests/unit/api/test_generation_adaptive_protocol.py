# -*- coding: utf-8 -*-
"""2026-09-15 AIGC 图/视频模型选择自适应推导（推导顺序根因修）。

真实缺陷：REST 端点在凭据解析**之前**推导协议，推导入参 base_url 恒为
body.base_url——前端从不传它（服务商经 provider_id 上报）——于是 OpenAI 的
Sora 2 Pro、火山豆包视频等具名模型全部落入默认支（视频→WAN、图像→
OPENAI_COMPAT），请求发错端点。

修复单源：runtime.derive_generation_protocol(kind, model, provider_id,
protocol_label, base_url) → (provider_id, protocol)：
provider_id→其 base_url 参与推导；pid 缺省按模型反查含该模型的启用服务商；
显式协议标签最优先。/image、/video、auto 路由、facade（画布/渠道）、
前端展示端点 /generation/resolve 全部走此单源。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import generation as generation_ep
from neurova.llm import provider_manager as provider_manager_mod
from neurova.llm.generators import protocols as proto_mod
from neurova.llm.generators import runtime as gen_runtime
from neurova.llm.generators import task_ledger as ledger_mod
from neurova.llm.generators.task_ledger import GenerationTaskLedger

pytestmark = pytest.mark.timeout(60)


class FakeModel:
    def __init__(self, id_, name=""):
        self.id = id_
        self.name = name or id_


class FakeProvider:
    def __init__(self, pid, base_url, models):
        self.id = pid
        self.base_url = base_url
        self.enabled = True
        self.api_key = f"sk-{pid}"  # 非密文 → decrypt_api_key 异常分支回退原值
        self.default_model = models[0] if models else ""
        self.models = [FakeModel(m) for m in models]


class FakeManager:
    def __init__(self, providers):
        self._providers = {p.id: p for p in providers}

    def get_provider(self, pid):
        return self._providers.get(pid)

    def list_providers(self, enabled_only=True):
        return list(self._providers.values())


PROVIDERS = [
    FakeProvider("openai", "https://api.openai.com/v1", ["sora-2-pro", "gpt-image-1"]),
    FakeProvider("dash", "https://dashscope.aliyuncs.com/api/v1", ["wan3.0-t2v", "qwen-image-plus"]),
    FakeProvider("volces", "https://ark.cn-beijing.volces.com/api/v3", ["doubao-video", "doubao-image"]),
]


@pytest.fixture()
def manager(monkeypatch):
    monkeypatch.setattr(provider_manager_mod, "get_provider_manager", lambda: FakeManager(PROVIDERS))
    return FakeManager(PROVIDERS)


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
    # 用量统计隔离（image 成功路径会 record，不打真实使用库）
    stub_usage = SimpleNamespace(record=lambda **kw: None)
    monkeypatch.setattr("neurova.core.aigc_usage.get_aigc_usage", lambda: stub_usage)
    with TestClient(app) as c:
        yield c


def _capture_submit(monkeypatch):
    captured = {}

    async def fake_submit(creds, prompt, **kw):
        captured["creds"] = creds
        return {"task_id": "remote_1", "poll_url": "https://x/poll"}

    monkeypatch.setattr(proto_mod, "submit_video", fake_submit)
    return captured


class TestDeriveSingleSource:
    def test_video_by_provider_base(self, manager):
        assert gen_runtime.derive_generation_protocol(
            "video", "doubao-video", "volces") == ("volces", "seedance2")
        assert gen_runtime.derive_generation_protocol(
            "video", "wan3.0-t2v", "dash") == ("dash", "wan")
        assert gen_runtime.derive_generation_protocol(
            "video", "sora-2-pro", "openai") == ("openai", "sora")

    def test_video_model_reverse_lookup_without_provider(self, manager):
        # pid 缺省（API 消费方不传）→ 按模型反查含它的启用服务商 → 其 base 推导
        assert gen_runtime.derive_generation_protocol(
            "video", "sora-2-pro", None) == ("openai", "sora")
        assert gen_runtime.derive_generation_protocol(
            "video", "doubao-video", "") == ("volces", "seedance2")

    def test_image_by_provider_base(self, manager):
        assert gen_runtime.derive_generation_protocol(
            "image", "qwen-image-plus", "dash") == ("dash", "dashscope")
        assert gen_runtime.derive_generation_protocol(
            "image", "gpt-image-1", "openai") == ("openai", "openai_compat")

    def test_explicit_protocol_label_wins(self, manager):
        # 显式指定协议（旧请求/画布透传）→ 不被推导覆盖
        assert gen_runtime.derive_generation_protocol(
            "video", "sora-2-pro", "openai", "wan") == ("openai", "wan")

    def test_unknown_model_keeps_default_branch(self, manager):
        # 反查不到且无显式标签 → 维持矩阵默认支语义（视频 wan / 图像 openai_compat）
        assert gen_runtime.derive_generation_protocol("video", "mystery-model", None)[1] == "wan"
        assert gen_runtime.derive_generation_protocol("image", "mystery-model", None)[1] == "openai_compat"

    def test_creds_provider_match_sora_hint(self, manager):
        # auto 路由无 provider_id 时协议↔host 匹配环也要认 sora
        creds = gen_runtime.resolve_generation_creds(
            "sora", "sora-2", None, None, None, "https://api.openai.com/v1")
        assert creds.base_url == "https://api.openai.com/v1"
        assert creds.api_key == "sk-openai"


class TestVideoEndpointAdaptive:
    def test_named_sora_model_derives_sora_protocol(self, client, manager, monkeypatch, tmp_ledger):
        captured = _capture_submit(monkeypatch)
        resp = client.post("/api/v1/generation/video", json={
            "prompt": "雨中柴犬", "model": "sora-2-pro", "provider_id": "openai"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["protocol"] == "sora"
        creds = captured["creds"]
        assert creds.protocol == "sora"
        assert creds.base_url == "https://api.openai.com/v1"
        assert creds.api_key == "sk-openai"
        rec = [t for t in tmp_ledger.list() if t.kind == "video"][0]
        assert rec.protocol == "sora"
        assert rec.provider_id == "openai"

    def test_named_model_without_provider_id_reverse_lookup(self, client, manager, monkeypatch, tmp_ledger):
        captured = _capture_submit(monkeypatch)
        resp = client.post("/api/v1/generation/video", json={
            "prompt": "p", "model": "doubao-video"})
        assert resp.status_code == 200, resp.text
        assert captured["creds"].protocol == "seedance2"
        assert captured["creds"].base_url == "https://ark.cn-beijing.volces.com/api/v3"
        rec = [t for t in tmp_ledger.list() if t.kind == "video"][0]
        assert rec.provider_id == "volces"  # 轮询按 provider_id 重取凭据，反查值必须落账

    def test_explicit_protocol_still_wins(self, client, manager, monkeypatch):
        captured = _capture_submit(monkeypatch)
        resp = client.post("/api/v1/generation/video", json={
            "prompt": "p", "model": "sora-2-pro", "provider_id": "openai", "protocol": "wan"})
        assert resp.status_code == 200, resp.text
        assert captured["creds"].protocol == "wan"

    def test_auto_route_routed_provider_adaptive(self, client, manager, monkeypatch):
        # 自动路由：routed provider 的 base_url 同样参与推导（用户口述「自动路由也能自适应协议」）
        captured = _capture_submit(monkeypatch)
        monkeypatch.setattr(
            generation_ep, "_route_selection",
            lambda request_type: SimpleNamespace(model="doubao-video", provider_id="volces"))
        resp = client.post("/api/v1/generation/video", json={"prompt": "p", "model": "auto"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["protocol"] == "seedance2"
        assert captured["creds"].protocol == "seedance2"
        assert captured["creds"].base_url == "https://ark.cn-beijing.volces.com/api/v3"


class TestImageEndpointAdaptive:
    def test_named_dashscope_image_model_derives_dashscope(self, client, manager, monkeypatch):
        captured = {}

        async def fake_generate(creds, prompt, **kw):
            captured["creds"] = creds
            return {"images": ["data:image/png;base64,AAAA"], "ignored_params": []}

        monkeypatch.setattr(proto_mod, "generate_image", fake_generate)
        resp = client.post("/api/v1/generation/image", json={
            "prompt": "猫", "model": "qwen-image-plus", "provider_id": "dash"})
        assert resp.status_code == 200, resp.text
        # 根因修前：base_url 恒空 → 模型名无 dashscope 关键词 → 误落 OPENAI_COMPAT
        assert captured["creds"].protocol == "dashscope"
        assert captured["creds"].base_url == "https://dashscope.aliyuncs.com/api/v1"


class TestResolveEndpoint:
    def test_resolve_video_with_provider(self, client, manager):
        resp = client.get("/api/v1/generation/resolve",
                          params={"kind": "video", "model": "sora-2-pro", "provider_id": "openai"})
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data == {"kind": "video", "model": "sora-2-pro",
                        "provider_id": "openai", "protocol": "sora"}

    def test_resolve_without_provider_reverse_lookup(self, client, manager):
        resp = client.get("/api/v1/generation/resolve",
                          params={"kind": "video", "model": "doubao-video"})
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["provider_id"] == "volces"
        assert data["protocol"] == "seedance2"

    def test_resolve_bad_kind_rejected(self, client, manager):
        resp = client.get("/api/v1/generation/resolve",
                          params={"kind": "bogus", "model": "m"})
        assert resp.status_code in (400, 422)

    def test_resolve_auto_returns_auto_marker(self, client, manager):
        # 前端 auto 态询问推导 → 无模型无服务商，返回默认支（诚实，不假称精确）
        resp = client.get("/api/v1/generation/resolve", params={"kind": "video"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["protocol"] == "wan"


class TestFacadeAdaptive:
    @pytest.mark.asyncio
    async def test_facade_video_uses_provider_base_for_protocol(self, manager, monkeypatch):
        captured = {}

        async def fake_wait(creds, *a, **kw):
            captured["creds"] = creds
            return {"status": "failed", "error": "止于此——只验凭据/协议推导入参"}

        monkeypatch.setattr(proto_mod, "generate_video_wait", fake_wait)
        cfg = gen_runtime.GenerationConfig(
            type="text_to_video", prompt="p", model="doubao-video")
        res = await gen_runtime.ProtocolGenerator().generate(cfg)
        creds = captured["creds"]
        assert creds.protocol == "seedance2"
        assert creds.base_url == "https://ark.cn-beijing.volces.com/api/v3"
        assert not res.success  # 失败路径本身不影响推导断言

    @pytest.mark.asyncio
    async def test_facade_image_uses_provider_base_for_protocol(self, manager, monkeypatch):
        captured = {}

        async def fake_generate(creds, prompt, **kw):
            captured["creds"] = creds
            raise RuntimeError("止于此")

        monkeypatch.setattr(proto_mod, "generate_image", fake_generate)
        cfg = gen_runtime.GenerationConfig(
            type="text_to_image", prompt="p", model="qwen-image-plus")
        res = await gen_runtime.ProtocolGenerator().generate(cfg)
        assert captured["creds"].protocol == "dashscope"
        assert not res.success
