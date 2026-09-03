"""
generation 端点 model=auto 自动路由测试（2026-09-03）

锁定契约：
1. POST /api/v1/generation/text，model 缺省或 "auto" 时 → LLMRouter 按
   RequestType.CHAT 自动选模型，选中结果记录在响应 data.routed_model /
   data.routed_provider，供前端"ato(LLMRouter 自动路由)"选项回显;
2. 显式指定 model 时行为不变（body.model 直接透传 agent.chat，不走路由）;
3. 路由失败（无任何注册 provider）→ 降级走 agent.chat（不 500）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import generation as generation_ep
from neurova.llm import llm_router


@pytest.fixture
def routed_router():
    """注册两个带能力标记的模型到全局 router。"""
    llm_router._router_instance = None
    llm_router.LLMRouter._instance = None
    llm_router.register_provider_from_config(
        "prov-a",
        "Prov A",
        ["deepseek-chat", "deepseek-r1", "flux.1-dev"],
        {
            "deepseek-chat": {"capabilities": ["text"]},
            "deepseek-r1": {"capabilities": ["text", "reasoning"]},
            "flux.1-dev": {"capabilities": ["image_generation"]},
        },
    )
    yield llm_router.get_llm_router()
    llm_router._router_instance = None
    llm_router.LLMRouter._instance = None


@pytest.fixture
def client(routed_router):
    """最小 FastAPI 只挂 generation router，agent 用桩。"""
    app = FastAPI()
    app.include_router(generation_ep.router, prefix="/api/v1/generation")

    class FakeAgent:
        async def chat(self, user_input, session_id=None, metadata=None):
            return f"echo:{user_input}"

    original = generation_ep.get_agent_instance
    generation_ep.get_agent_instance = lambda agent_id="default": FakeAgent()
    with TestClient(app) as c:
        yield c
    generation_ep.get_agent_instance = original


class TestAutoRouting:
    def test_default_model_routes_via_router(self, client):
        resp = client.post("/api/v1/generation/text", json={"prompt": "你好"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["routed"] is True
        assert data["routed_model"] in ("deepseek-chat", "deepseek-r1")
        assert data["routed_provider"] == "Prov A"

    def test_explicit_model_skips_router(self, client):
        resp = client.post(
            "/api/v1/generation/text", json={"prompt": "你好", "model": "my-model"}
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["routed"] is False
        assert data["routed_model"] is None
        assert data["model"] == "my-model"

    def test_no_chat_capable_model_degrades_gracefully(self, client):
        # 重建仅含纯生成模型的 router：无 CHAT 能力模型 → 路由返回 None → 降级
        llm_router._router_instance = None
        llm_router.LLMRouter._instance = None
        llm_router.register_provider_from_config(
            "gen-only",
            "GenOnly",
            ["flux.1-dev"],
            {"flux.1-dev": {"capabilities": ["image_generation"]}},
        )
        resp = client.post("/api/v1/generation/text", json={"prompt": "hi"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["routed"] is False
        assert data["text"] == "echo:hi"
