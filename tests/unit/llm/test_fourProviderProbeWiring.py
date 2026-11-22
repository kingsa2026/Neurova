# -*- coding: utf-8 -*-
"""卡 L4（多模态追平 M7 遗留）：anthropic/openrouter/ollama/lm_studio 四家
probe_model_multimodal 接入 multimodal_prober 真图探测矩阵。

现状（红灯）：四家仍是名称启发式（supported 恒 True、detection_method=
name_heuristic），不发任何探测请求——声明与实测无从对齐。

判据（红→绿，对齐 M7 gemini 接线测试形态）：
1. 桩 transport 答红 → 四家 probe 真发请求且返回 vision=True、
   probe_source=probed（名称启发式不发请求 → 红）；
2. 媒体拒绝样例 → 不支持（vision 被剥除）；
3. 网关错 → inconclusive 如实透传，不拿启发式冒充实测。
"""

from __future__ import annotations

import importlib

import pytest

from neurova.llm.providers import multimodal_prober as prober


# ── aiohttp 桩（HTTP 层打桩，与 test_multimodal_probe_matrix 同一形态） ────

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


_RED_BODIES = {
    "openai": {"choices": [{"message": {"content": "The dominant color is red."}}]},
    "anthropic": {"content": [{"type": "text", "text": "The color is red."}]},
}

# (类名, providerType, 协议族, 测试 base_url)
_PROVIDERS = [
    ("AnthropicProvider", "anthropic", "anthropic", "https://ant.test.example"),
    ("OpenRouterProvider", "openrouter", "openai", "https://or.test.example/v1"),
    ("OllamaProvider", "ollama", "openai", "http://ol.test.example:11434"),
    ("LMStudioProvider", "lm_studio", "openai", "http://ls.test.example:1234/v1"),
]

_MODULES = {
    "AnthropicProvider": "neurova.llm.providers.anthropic_provider",
    "OpenRouterProvider": "neurova.llm.providers.openrouter_provider",
    "OllamaProvider": "neurova.llm.providers.ollama_provider",
    "LMStudioProvider": "neurova.llm.providers.lm_studio_provider",
}


def _provider(className: str, base_url: str):
    cls = getattr(importlib.import_module(_MODULES[className]), className)
    return cls(provider_id="p", api_key="k", base_url=base_url)


def _capabilityNames(result) -> list:
    return [c.value if hasattr(c, "value") else str(c) for c in result.capabilities]


@pytest.mark.asyncio
class TestFourProviderProbeWiring:
    @pytest.mark.parametrize("className,providerType,protocol,base_url", _PROVIDERS)
    async def test_redAnswerMeansProbedVision(
        self, monkeypatch, className, providerType, protocol, base_url
    ):
        _patch_http(monkeypatch, body=_RED_BODIES[protocol])
        provider = _provider(className, base_url)

        result = await provider.probe_model_multimodal("m-1")

        assert _FakeSession.last_post is not None, f"{className} 探测必须真发请求，不许只看名字"
        assert result.supported is True
        assert "vision" in _capabilityNames(result)
        assert result.metadata.get("probe_source") == "probed"
        assert result.metadata.get("protocol") == protocol

    @pytest.mark.parametrize("className,providerType,protocol,base_url", _PROVIDERS)
    async def test_mediaRejectionMeansNotSupported(
        self, monkeypatch, className, providerType, protocol, base_url
    ):
        _patch_http(monkeypatch, status=400, text="this model does not support image input")
        provider = _provider(className, base_url)

        result = await provider.probe_model_multimodal("m-1")

        assert result.supported is False
        assert result.metadata.get("probe_source") == "probed"
        assert result.metadata.get("probe_detail") == "media_rejected"
        assert "vision" not in _capabilityNames(result)

    @pytest.mark.parametrize("className,providerType,protocol,base_url", _PROVIDERS)
    async def test_gatewayErrorIsInconclusiveNotHeuristic(
        self, monkeypatch, className, providerType, protocol, base_url
    ):
        _patch_http(monkeypatch, status=500, text="internal server error")
        provider = _provider(className, base_url)

        result = await provider.probe_model_multimodal("m-1")

        assert result.metadata.get("probe_source") == "inconclusive"
        assert result.supported is False
        assert "detection_method" not in result.metadata, "不再拿名称启发式冒充实测"

    @pytest.mark.parametrize("className,providerType,protocol,base_url", _PROVIDERS)
    async def test_probeRequestCarriesRealImageAndQuestion(
        self, monkeypatch, className, providerType, protocol, base_url
    ):
        """探测请求必须真带红图与提问（openai 兼容族 image_url / anthropic image 块）。"""
        _patch_http(monkeypatch, body=_RED_BODIES[protocol])
        provider = _provider(className, base_url)

        await provider.probe_model_multimodal("m-1")

        sent = _FakeSession.last_post
        assert sent is not None
        if protocol == "anthropic":
            blocks = sent["json"]["messages"][0]["content"]
            assert any(
                isinstance(b, dict) and b.get("type") == "image" for b in blocks
            ), "anthropic 探测必须带原生 image source 块"
        else:
            content = sent["json"]["messages"][0]["content"]
            assert any(
                isinstance(p, dict) and p.get("type") == "image_url" for p in content
            ), "openai 兼容族探测必须带 image_url 部件"
            assert sent["url"].endswith("/chat/completions")
