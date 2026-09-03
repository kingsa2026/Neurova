"""
模型能力端点 + LLMRouter 自动路由测试（2026-09-03）

锁定契约：
1. GET /api/v1/models — 每个模型带 capabilities 标记（六类核心能力），
   元数据缺失时服务端即时推断兜底（响应永不缺 capabilities 字段）；
2. POST /api/v1/models/detect-capabilities — 显式批量检测并持久化；
3. GET /api/v1/models/by-capability?cap=vision — 按能力过滤（AIGC 下拉数据源）；
4. LLMRouter 消费持久化的元数据 capabilities（而非仅名称推断）；
   select_model_for_request("text_to_image") 应选中带 image_generation 的模型。

注意：LLMProviderManager 构造时会自动种子内置服务商（openrouter/opencode/
kilo-code/github-models/sensetime），测试一律用 fixture 返回的 provider.id 定位，
绝不假设 list_providers()[0] 是测试商。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import model as model_ep
from neurova.llm import llm_router
from neurova.llm.llm_router import (
    RequestType,
    select_model_for_request,
)
from neurova.llm.provider_manager import LLMProviderManager, reset_provider_manager


def _reset_router_singleton() -> None:
    """重置 LLMRouter 双层单例（类级 + 模块级），防跨用例污染。"""
    llm_router._router_instance = None
    llm_router.LLMRouter._instance = None


@pytest.fixture
def mgr(tmp_path):
    """tmp 配置的 ProviderManager（隔离真实用户配置）+ 重置 router 单例。"""
    reset_provider_manager()
    _reset_router_singleton()
    m = LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
    provider = m.add_provider(
        name="TestVision",
        provider="openai",
        base_url="https://example.test/v1",
        api_key="sk-test-1234567890",
        models=["qwen-vl-max", "deepseek-chat", "deepseek-r1", "flux.1-dev", "wan2.2-t2v-a14b"],
    )
    m._test_provider = provider
    yield m
    reset_provider_manager()
    _reset_router_singleton()


@pytest.fixture
def client(mgr):
    """最小 FastAPI 只挂 model router，provider manager 注入 fixture 实例。"""
    app = FastAPI()
    app.include_router(model_ep.router, prefix="/api/v1/models")
    original = model_ep._get_provider_manager
    model_ep._get_provider_manager = lambda current_user=None: mgr
    with TestClient(app) as c:
        yield c
    model_ep._get_provider_manager = original


class TestListModelsCapabilities:
    """GET /models：能力标记自动补全。"""

    def test_capabilities_always_present(self, client):
        models = client.get("/api/v1/models").json()
        assert models, "应有模型列表"
        for m in models:
            assert isinstance(m.get("capabilities"), list)
            assert len(m["capabilities"]) > 0, f"{m['model_id']} 不应缺能力标记"

    def test_limit_triple_carried_in_response(self, client):
        """/models 响应携带预埋限额（context_window/max_tokens），4096 占位不外发。"""
        models = {m["model_id"]: m for m in client.get("/api/v1/models").json()}
        # minimax-m1 族不在 fixture 商内 → 用目录内已知模型验证预埋兜底
        for m in models.values():
            if m["capabilities"] and "vision" in m["capabilities"]:
                # 已知视觉模型不应是 4096 占位外发（None 允许:未预埋的合法）
                if m["model_id"].startswith(("qwen-vl", "qwen2.5-vl", "glm-4v")):
                    assert m["context_window"] not in (4096,), m
        # 字段必须存在（契约）
        for m in models.values():
            assert "context_window" in m
            assert "max_tokens" in m

    def test_vision_and_reasoning_detected(self, client):
        models = {m["model_id"]: m for m in client.get("/api/v1/models").json()}
        assert "vision" in models["qwen-vl-max"]["capabilities"]
        assert "reasoning" in models["deepseek-r1"]["capabilities"]

    def test_generation_caps_detected(self, client):
        models = {m["model_id"]: m for m in client.get("/api/v1/models").json()}
        assert "image_generation" in models["flux.1-dev"]["capabilities"]
        assert "video_generation" in models["wan2.2-t2v-a14b"]["capabilities"]


class TestDetectCapabilitiesEndpoint:
    """POST /models/detect-capabilities：批量检测 + 持久化。"""

    def test_detect_and_persist(self, client, mgr):
        resp = client.post("/api/v1/models/detect-capabilities", json={"provider_id": None})
        assert resp.status_code == 200
        data = resp.json().get("data", {})
        assert data.get("detected", 0) >= 5

        # 持久化：测试商元数据已写入 capabilities
        provider = mgr.get_provider(mgr._test_provider.id)
        meta = provider.model_metadata["deepseek-r1"]
        assert "reasoning" in meta["capabilities"]

        # 持久化落盘：重载后仍在
        reloaded = LLMProviderManager(config={"config_path": str(mgr._config_path)})
        meta2 = reloaded.get_provider(provider.id).model_metadata["deepseek-r1"]
        assert "reasoning" in meta2["capabilities"]

    def test_detect_single_provider(self, client, mgr):
        resp = client.post(
            "/api/v1/models/detect-capabilities",
            json={"provider_id": mgr._test_provider.id},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["detected"] >= 5

    def test_detect_unknown_provider_404(self, client):
        resp = client.post(
            "/api/v1/models/detect-capabilities", json={"provider_id": "nope"}
        )
        assert resp.status_code == 404


class TestByCapabilityEndpoint:
    """GET /models/by-capability：AIGC 下拉数据源。"""

    def test_filter_vision(self, client):
        resp = client.get("/api/v1/models/by-capability", params={"cap": "vision"})
        assert resp.status_code == 200
        ids = [m["model_id"] for m in resp.json()]
        assert ids == ["qwen-vl-max"]

    def test_filter_image_generation(self, client):
        resp = client.get("/api/v1/models/by-capability", params={"cap": "image_generation"})
        ids = [m["model_id"] for m in resp.json()]
        assert ids == ["flux.1-dev"]

    def test_filter_unknown_cap_400(self, client):
        resp = client.get("/api/v1/models/by-capability", params={"cap": "telepathy"})
        assert resp.status_code == 400


class TestRouterConsumesPersistedCaps:
    """LLMRouter 自动路由消费持久化元数据能力。"""

    def test_register_from_config_uses_metadata(self, mgr):
        # 先持久化检测
        mgr.detect_and_persist_capabilities()
        from neurova.llm.llm_router import register_provider_from_config

        provider = mgr.get_provider(mgr._test_provider.id)
        register_provider_from_config(provider.id, provider.name, provider.models)
        router = llm_router.get_llm_router()
        models = {m["name"]: m for m in router._providers[provider.id]["models"]}
        assert "reasoning" in models["deepseek-r1"]["capabilities"]
        assert "image_generation" in models["flux.1-dev"]["capabilities"]

    def test_select_for_text_to_image(self, mgr):
        mgr.detect_and_persist_capabilities()
        from neurova.llm.llm_router import register_provider_from_config

        provider = mgr.get_provider(mgr._test_provider.id)
        register_provider_from_config(provider.id, provider.name, provider.models)
        result = select_model_for_request(RequestType.TEXT_TO_IMAGE)
        assert result is not None, "image_generation 模型应可被自动路由"
        assert result.model == "flux.1-dev"

    def test_select_for_chat(self, mgr):
        mgr.detect_and_persist_capabilities()
        from neurova.llm.llm_router import register_provider_from_config

        provider = mgr.get_provider(mgr._test_provider.id)
        register_provider_from_config(provider.id, provider.name, provider.models)
        result = select_model_for_request(RequestType.CHAT)
        assert result is not None
        # 文本聊天不应路由到纯生成模型
        assert result.model in ("deepseek-chat", "deepseek-r1", "qwen-vl-max")

    def test_select_video_generation(self, mgr):
        mgr.detect_and_persist_capabilities()
        from neurova.llm.llm_router import register_provider_from_config

        provider = mgr.get_provider(mgr._test_provider.id)
        register_provider_from_config(provider.id, provider.name, provider.models)
        result = select_model_for_request(RequestType.TEXT_TO_VIDEO)
        assert result is not None
        assert result.model == "wan2.2-t2v-a14b"
