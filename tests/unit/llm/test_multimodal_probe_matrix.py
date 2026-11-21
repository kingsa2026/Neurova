# -*- coding: utf-8 -*-
"""M7（多模态追平批一）：视觉探测矩阵扩容到全部声明 vision 的 provider。

契约：
1. `multimodal_prober.buildImageProbeRequest` 按 provider 协议族产出正确的
   真图探测请求——openai 兼容族（openrouter/ollama/lm_studio/opencode）、
   anthropic 原生 /v1/messages、gemini 原生 generateContent(inline_data)；
2. `probeProviderVision` 走同一评估口径（红图答出红色系才算 vision），
   HTTP 层经本模块 aiohttp 打桩可进 CI；错误归一 inconclusive 不炸链；
3. `gemini_provider.probe_model_multimodal` 接矩阵真探测，不再恒 True；
4. 探测结果变更 → model_metadata → llm_router 候选与目录展示同源联动
   （对齐路由专项 R7 口径）。
"""
import pytest

from neurova.llm.providers import multimodal_prober as prober


# ── aiohttp 桩（HTTP 层打桩，与 test_multimodal_real_probe 同一形态） ──────

class _FakeResponse:
    def __init__(self, status=200, body=None, text=""):
        self.status = status
        self._body = body if body is not None else {}
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        if self.status >= 400:
            raise RuntimeError("error body")
        return self._body

    async def text(self):
        return self._text


class _FakeSession:
    post_response = None
    last_post = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, **kwargs):
        type(self).last_post = {"url": url, **kwargs}
        return type(self).post_response


def _patch_http(monkeypatch, body=None, status=200, text=""):
    class _AiohttpStub:
        ClientSession = _FakeSession
        ClientTimeout = dict
        ClientError = Exception

    monkeypatch.setattr(prober, "aiohttp", _AiohttpStub)
    _FakeSession.post_response = _FakeResponse(status=status, body=body, text=text)
    _FakeSession.last_post = None


# 各协议族的"答出红色"响应体
_RED_BODIES = {
    "openai": {"choices": [{"message": {"content": "The dominant color is red."}}]},
    "anthropic": {"content": [{"type": "text", "text": "The color is red."}]},
    "gemini": {"candidates": [{"content": {"parts": [{"text": "red"}], "role": "model"}}]},
}


class TestProbeRequestMatrix:
    def test_openai_family_wire_shape(self):
        req = prober.buildImageProbeRequest("openai", "gpt-4o", "https://api.test.example/v1", "sk-k")

        assert req.protocol == "openai"
        assert req.url == "https://api.test.example/v1/chat/completions"
        assert req.headers["Authorization"] == "Bearer sk-k"
        content = req.payload["messages"][0]["content"]
        image = [p for p in content if p.get("type") == "image_url"]
        assert image and image[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert any(p.get("type") == "text" and p.get("text") for p in content)

    @pytest.mark.parametrize("providerType", ["openrouter", "ollama", "lm_studio", "opencode"])
    def test_openaiCompatibleProviders_shareOpenaiFamily(self, providerType):
        req = prober.buildImageProbeRequest(providerType, "m-1", "https://gw.test.example/v1", "k")

        assert req.protocol == "openai", f"{providerType} 应归入 openai 兼容族"
        assert req.url.endswith("/chat/completions")

    def test_anthropic_native_wire_shape(self):
        req = prober.buildImageProbeRequest("anthropic", "claude-sonnet-4", "https://ant.test.example", "k")

        assert req.protocol == "anthropic"
        assert req.url.endswith("/v1/messages")
        assert req.headers["x-api-key"] == "k"
        blocks = req.payload["messages"][0]["content"]
        image = [b for b in blocks if b.get("type") == "image"]
        assert image, "anthropic 探测必须带原生 image source 块"
        source = image[0]["source"]
        assert source["type"] == "base64" and source["media_type"] == "image/png" and source["data"]

    def test_gemini_native_wire_shape(self):
        req = prober.buildImageProbeRequest(
            "gemini", "gemini-2.5-flash", "https://gen.test.example/v1beta", "g-k"
        )

        assert req.protocol == "gemini"
        assert ":generateContent" in req.url and "gemini-2.5-flash" in req.url
        assert req.headers["x-goog-api-key"] == "g-k"
        parts = req.payload["contents"][0]["parts"]
        inlines = [p for p in parts if "inline_data" in p]
        assert inlines, "gemini 探测必须带 inline_data 原生形态"
        assert inlines[0]["inline_data"]["mime_type"] == "image/png"
        assert inlines[0]["inline_data"]["data"]
        assert any("text" in p for p in parts)


@pytest.mark.asyncio
class TestProbeSendMatrix:
    @pytest.mark.parametrize("providerType,protocol", [
        ("openai", "openai"),
        ("openrouter", "openai"),
        ("anthropic", "anthropic"),
        ("gemini", "gemini"),
    ])
    async def test_red_answer_means_vision(self, monkeypatch, providerType, protocol):
        _patch_http(monkeypatch, body=_RED_BODIES[protocol])

        result = await prober.probeProviderVision(
            providerType, "m-1", "https://p.test.example", "k"
        )

        assert result.supported is True, providerType
        assert "vision" in [c.value if hasattr(c, "value") else str(c) for c in result.capabilities]
        assert result.metadata["probe_source"] == "probed"
        assert result.metadata["protocol"] == protocol

    async def test_gemini_probe_actuallySendsInlineData(self, monkeypatch):
        _patch_http(monkeypatch, body=_RED_BODIES["gemini"])

        await prober.probeProviderVision("gemini", "gemini-2.5-flash", "https://p.test.example", "k")

        sent = _FakeSession.last_post
        assert sent is not None and "generateContent" in sent["url"]
        parts = sent["json"]["contents"][0]["parts"]
        assert any("inline_data" in p for p in parts), "gemini 探测请求必须真带 inline_data"

    async def test_media_rejection_means_no_vision(self, monkeypatch):
        _patch_http(monkeypatch, status=400, text="this model does not support image input")

        result = await prober.probeProviderVision("openai", "text-only", "https://p.test.example", "k")

        assert result.supported is False
        assert result.metadata["probe_source"] == "probed"
        assert result.metadata["probe_detail"] == "media_rejected"

    async def test_other_api_error_is_inconclusive(self, monkeypatch):
        _patch_http(monkeypatch, status=500, text="internal server error")

        result = await prober.probeProviderVision("gemini", "m-1", "https://p.test.example", "k")

        assert result.metadata["probe_source"] == "inconclusive"
        assert result.supported is False

    async def test_text_answer_without_color_is_inconclusive(self, monkeypatch):
        """答非所问（no_marker）→ 下不了结论：与 openai_provider 同一评估口径。"""
        _patch_http(monkeypatch, body={"choices": [{"message": {"content": "Hello! How can I help?"}}]})

        result = await prober.probeProviderVision("openai", "m-1", "https://p.test.example", "k")

        assert result.capabilities == []
        assert result.metadata["probe_source"] == "inconclusive"


@pytest.mark.asyncio
class TestGeminiProviderWiring:
    async def test_probe_usesRealImageMatrix(self, monkeypatch):
        from neurova.llm.providers.gemini_provider import GeminiProvider

        _patch_http(monkeypatch, body=_RED_BODIES["gemini"])
        provider = GeminiProvider(provider_id="g", api_key="k", base_url="https://gen.test.example/v1beta")

        result = await provider.probe_model_multimodal("gemini-2.5-flash")

        assert result.metadata.get("probe_source") == "probed"
        assert "vision" in [c.value if hasattr(c, "value") else str(c) for c in result.capabilities]

    async def test_probe_mediaRejection_stripsDeclaredVision(self, monkeypatch):
        from neurova.llm.providers.gemini_provider import GeminiProvider

        _patch_http(monkeypatch, status=400, text="this model does not support image input")
        provider = GeminiProvider(provider_id="g", api_key="k", base_url="https://gen.test.example/v1beta")

        # gemini-1.5-pro 名称启发式含 vision；实测拒绝后必须剥掉
        result = await provider.probe_model_multimodal("gemini-1.5-pro")

        assert result.metadata.get("probe_detail") == "media_rejected"
        assert "vision" not in [c.value if hasattr(c, "value") else str(c) for c in result.capabilities]

    async def test_probe_error_isInconclusive_notNameHeuristic(self, monkeypatch):
        from neurova.llm.providers.gemini_provider import GeminiProvider

        _patch_http(monkeypatch, status=500, text="internal server error")
        provider = GeminiProvider(provider_id="g", api_key="k", base_url="https://gen.test.example/v1beta")

        result = await provider.probe_model_multimodal("gemini-2.5-flash")

        assert result.metadata.get("probe_source") == "inconclusive"
        assert "detection_method" not in result.metadata, "不再拿名称启发式冒充实测"


class TestSameSourceLinkage:
    """探测结果变更 → model_metadata → 路由候选与目录展示同源联动（R7 口径）。"""

    def test_probeResult_flowsToRouterAndCatalog(self, monkeypatch, tmp_path):
        import asyncio

        from neurova.llm.llm_router import (
            LLMRouter,
            RequestType,
            get_llm_router,
            register_provider_from_config,
        )
        from neurova.llm.provider_manager import LLMProviderManager, reset_provider_manager

        _patch_http(monkeypatch, body=_RED_BODIES["gemini"])
        reset_provider_manager()
        original_router = LLMRouter._instance
        LLMRouter._instance = None
        try:
            mgr = LLMProviderManager(config={"config_path": str(tmp_path / "p.json")})
            provider = mgr.add_provider(
                name="G",
                provider="gemini",
                base_url="https://gen.test.example/v1beta",
                api_key="g-k",
                models=["gemini-2.5-flash-probe"],
            )

            result = asyncio.run(mgr.probe_model_multimodal("gemini-2.5-flash-probe", force=True))
            assert result.metadata.get("probe_source") == "probed"

            meta = (provider.model_metadata or {}).get("gemini-2.5-flash-probe", {})
            assert meta.get("probe_source") == "probed", "探测结论必须持久化进 model_metadata"
            assert "vision" in [str(c) for c in meta.get("capabilities", [])]

            # 同源消费 1：llm_router 视觉候选
            register_provider_from_config(
                provider.id, "G", ["gemini-2.5-flash-probe"],
                {"gemini-2.5-flash-probe": meta}, scope="admin",
            )
            selected = get_llm_router().select_model(RequestType.IMAGE_UNDERSTANDING, scope="admin")
            assert selected is not None and selected.model == "gemini-2.5-flash-probe", (
                "探测出的 vision 必须让模型进视觉轮路由候选"
            )

            # 同源消费 2：目录展示（model.py 能力出口）
            from neurova.api.endpoints.model import _response_capabilities

            display_caps = _response_capabilities("gemini-2.5-flash-probe", list(meta.get("capabilities")))
            assert "vision" in display_caps, "目录展示必须与路由读同一份能力位"
        finally:
            LLMRouter._instance = original_router
            reset_provider_manager()
