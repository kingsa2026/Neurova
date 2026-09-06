"""多模态真实探测对齐 QwenPaw — 契约测试（红绿灯 TDD）

锁定契约（对齐 QwenPaw multimodal_prober / openai_provider probe）：
1. openai_provider.probe_model_multimodal 发真实图像探测请求
   （32x32 纯红 PNG data URL + 主色调提问），不再是纯名称启发式；
2. 语义校验：答案含红色系关键词才判 vision 支持（防纯文本模型假阳性）；
   请求被媒体关键词拒绝 → 判不支持；其他 API 错误 → inconclusive；
3. probe 结果带 probe_source（probed/documentation/name_heuristic）并
   持久化到 model_metadata[model_id]["probe_source"]；
4. 管理器 probe_model_multimodal(force=True) 跳过元数据直发真实探测；
5. 激活模型时对未探测过的模型自动后台探测（maybe_probe_multimodal）。
"""
import base64
import pytest

from neurova.llm.providers.types import ConnectionResult

# 32x32 纯红 PNG（与实现共用同一常量语义）
RED_PNG_32 = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000020000000200802000000fc18eda3"
        "0000000163485201000080a00000000bf4a3720a"
    )
)


class _FakeResponse:
    def __init__(self, status=200, content="red"):
        self.status = status
        self._content = content

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        if self.status >= 400:
            raise RuntimeError("error body")
        return {"choices": [{"message": {"content": self._content}}]}

    async def text(self):
        return self._content


class _FakeSession:
    post_response = None
    last_post_json = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, **kwargs):
        type(self).last_post_json = kwargs.get("json")
        return type(self).post_response

    def get(self, url, **kwargs):
        return _FakeResponse(status=200, content="[]")


def _patch_aiohttp(monkeypatch, response):
    import neurova.llm.providers.openai_provider as mod

    class _AiohttpStub:
        ClientSession = _FakeSession
        ClientTimeout = dict
        ClientError = Exception

    monkeypatch.setattr(mod, "aiohttp", _AiohttpStub)
    _FakeSession.post_response = response
    _FakeSession.last_post_json = None


def _make_provider():
    from neurova.llm.providers.openai_provider import OpenAIProvider

    return OpenAIProvider(
        provider_id="t",
        api_key="sk-test-1234567890",
        base_url="https://api.test.example/v1",
    )


class TestRealImageProbe:
    @pytest.mark.asyncio
    async def test_red_answer_means_vision_supported(self, monkeypatch):
        _patch_aiohttp(monkeypatch, _FakeResponse(status=200, content="The dominant color is red."))
        provider = _make_provider()
        result = await provider.probe_model_multimodal("gpt-4o-unknown-probe")

        assert result.metadata.get("probe_source") == "probed"
        assert "vision" in [c.value if hasattr(c, "value") else str(c) for c in result.capabilities]

    @pytest.mark.asyncio
    async def test_sends_image_data_url(self, monkeypatch):
        _patch_aiohttp(monkeypatch, _FakeResponse(status=200, content="red"))
        provider = _make_provider()
        await provider.probe_model_multimodal("m1")

        sent = _FakeSession.last_post_json
        assert sent is not None
        content = sent["messages"][0]["content"]
        assert isinstance(content, list), "探测消息应为多段 content（图+文）"
        image_parts = [p for p in content if p.get("type") == "image_url"]
        assert image_parts, "应包含 image_url 段"
        assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_media_keyword_rejection_means_no_vision(self, monkeypatch):
        _patch_aiohttp(
            monkeypatch,
            _FakeResponse(status=400, content="this model does not support image input"),
        )
        provider = _make_provider()
        result = await provider.probe_model_multimodal("text-only-model")

        assert result.metadata.get("probe_source") == "probed"
        assert "vision" not in [c.value if hasattr(c, "value") else str(c) for c in result.capabilities]
        assert result.supported is False

    @pytest.mark.asyncio
    async def test_other_api_error_is_inconclusive(self, monkeypatch):
        _patch_aiohttp(
            monkeypatch,
            _FakeResponse(status=500, content="internal server error"),
        )
        provider = _make_provider()
        result = await provider.probe_model_multimodal("m1")

        assert result.metadata.get("probe_source") == "inconclusive"

    @pytest.mark.asyncio
    async def test_text_answer_without_color_is_not_vision(self, monkeypatch):
        """纯文本模型静默忽略图片答非所问 → 不算支持（防假阳性）。"""
        _patch_aiohttp(monkeypatch, _FakeResponse(status=200, content="Hello! How can I help you?"))
        provider = _make_provider()
        result = await provider.probe_model_multimodal("m1")

        assert "vision" not in [c.value if hasattr(c, "value") else str(c) for c in result.capabilities]


class TestProbePersistence:
    @pytest.mark.asyncio
    async def test_force_bypasses_metadata(self, tmp_path):
        from neurova.llm.provider_manager import LLMProviderManager, reset_provider_manager

        reset_provider_manager()
        try:
            mgr = LLMProviderManager(config={"config_path": str(tmp_path / "p.json")})
            provider = mgr.add_provider(
                name="T",
                provider="openai",
                base_url="https://example.test/v1",
                api_key="sk-test-1234567890",
                models=["m-1"],
            )
            # 预置元数据：非 force 时应直接命中元数据短路
            provider.model_metadata = {
                "m-1": {"capabilities": ["vision"], "probe_source": "documentation"},
            }

            probe_calls = []

            async def _fake_real_probe(pid, mid):
                probe_calls.append((pid, mid))
                from neurova.llm.providers.types import ProbeResult

                return ProbeResult(model_id=mid, supported=True, capabilities=["vision"], metadata={"probe_source": "probed"})

            mgr._probe_model_multimodal_real = _fake_real_probe
            await mgr.probe_model_multimodal("m-1", force=True)
            assert probe_calls, "force=True 应绕过元数据直发真实探测"

            probe_calls.clear()
            await mgr.probe_model_multimodal("m-1")
            assert not probe_calls, "无 force 时元数据命中应短路"
        finally:
            reset_provider_manager()


class TestAutoProbeOnActivate:
    def test_activate_schedules_background_probe_for_unprobed(self, tmp_path):
        from neurova.llm.provider_manager import LLMProviderManager, reset_provider_manager

        reset_provider_manager()
        try:
            mgr = LLMProviderManager(config={"config_path": str(tmp_path / "p.json")})
            provider = mgr.add_provider(
                name="T",
                provider="openai",
                base_url="https://example.test/v1",
                api_key="sk-test-1234567890",
                models=["m-1"],
            )
            scheduled = []
            mgr.maybe_probe_multimodal = lambda pid, mid: scheduled.append((pid, mid))

            assert mgr.activate_model(provider.id, "m-1") is True
            assert scheduled == [(provider.id, "m-1")], "激活后应调度未探测模型的自动探测"
        finally:
            reset_provider_manager()
