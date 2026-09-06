"""模型连接测试对齐 QwenPaw — 契约测试（红绿灯 TDD）

锁定契约（对齐 QwenPaw providers.py / provider_model_availability.py）：
1. 模型级连接测试发真实请求（chat ping），而非仅本地构造实例（恒成功的假实现）；
2. ConnectionResult 结构化：http_status / retryable / checked_at / verification
   （live = 真实请求验证；provider_only = 仅验证服务商连通；
   unverified = 本地构造校验，未发请求）；
3. 可用性七态派生（availability_status_of）：
   available / permission_denied / model_not_found / incompatible_api /
   rate_limited / transient_error / unverified；
4. 管理器把检查结果持久化进 model_metadata[model_id]["availability"]；
5. POST /api/v1/models/check-connection 透传全部结构化字段。
"""
import pytest

from neurova.llm.providers.error_mapping import availability_status_of
from neurova.llm.providers.types import ConnectionResult


# ---------------------------------------------------------------------------
# 七态派生（单一事实源：五类 ErrorCategory → QwenPaw 风格七态）
# ---------------------------------------------------------------------------

class TestAvailabilityStatusDerivation:
    def test_success_is_available(self):
        assert availability_status_of(success=True) == "available"

    def test_auth_failed_maps_permission_denied(self):
        status = availability_status_of(
            success=False, error_category="auth_failed",
        )
        assert status == "permission_denied"

    def test_rate_limited_is_retryable(self):
        status = availability_status_of(
            success=False, error_category="rate_limited",
        )
        assert status == "rate_limited"

    def test_connection_and_unavailable_map_transient(self):
        for cat in ("connection_failed", "service_unavailable"):
            assert availability_status_of(
                success=False, error_category=cat,
            ) == "transient_error"

    def test_http_404_message_maps_model_not_found(self):
        status = availability_status_of(
            success=False,
            error_category="bad_request",
            message="Model 'gpt-9' not found",
        )
        assert status == "model_not_found"

    def test_model_not_exist_keyword_maps_model_not_found(self):
        status = availability_status_of(
            success=False,
            error_category="bad_request",
            message="模型不存在或未开通",
        )
        assert status == "model_not_found"

    def test_no_chat_support_maps_incompatible_api(self):
        status = availability_status_of(
            success=False,
            error_category="bad_request",
            message="this model does not support chat completions",
        )
        assert status == "incompatible_api"

    def test_unknown_category_maps_unverified(self):
        assert availability_status_of(success=False, error_category=None) == "unverified"


# ---------------------------------------------------------------------------
# ConnectionResult 结构化字段
# ---------------------------------------------------------------------------

class TestConnectionResultFields:
    def test_new_fields_exist_with_defaults(self):
        result = ConnectionResult(success=True)
        assert result.http_status is None
        assert result.checked_at is None
        assert result.verification == "unverified"

    def test_checked_at_iso_format_when_filled(self):
        import datetime as dt

        result = ConnectionResult(success=True, checked_at=dt.datetime.now(dt.timezone.utc).isoformat())
        assert "T" in result.checked_at


# ---------------------------------------------------------------------------
# openai_provider.check_model_connection — 真实请求探测
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status=200, payload=None, raise_for_status=False):
        self.status = status
        self._payload = payload if payload is not None else {}
        self._raise = raise_for_status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        if self._raise:
            raise RuntimeError("response body is not json")
        return self._payload

    @property
    def ok(self):
        return 200 <= self.status < 300

    async def text(self):
        return str(self._payload)


class _FakeSession:
    """记录 POST/GET 调用的 aiohttp.ClientSession 替身。"""

    last_post_kwargs = None
    post_response = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, **kwargs):
        type(self).last_post_kwargs = {"url": url, **kwargs}
        return type(self).post_response

    def get(self, url, **kwargs):
        return _FakeResponse(status=200, payload={"data": []})


def _patch_aiohttp(monkeypatch, response):
    import neurova.llm.providers.openai_provider as mod

    class _AiohttpStub:
        ClientSession = _FakeSession
        ClientTimeout = dict
        ClientError = Exception

    monkeypatch.setattr(mod, "aiohttp", _AiohttpStub)
    _FakeSession.post_response = response
    _FakeSession.last_post_kwargs = None


def _make_openai_provider():
    from neurova.llm.providers.openai_provider import OpenAIProvider

    return OpenAIProvider(
        provider_id="test-openai",
        api_key="sk-test-1234567890",
        base_url="https://api.test.example/v1",
    )


class TestOpenAIModelConnectionReal:
    @pytest.mark.asyncio
    async def test_success_sends_real_chat_request_live(self, monkeypatch):
        _patch_aiohttp(
            monkeypatch,
            _FakeResponse(status=200, payload={"choices": [{"message": {"content": "pong"}}]}),
        )
        provider = _make_openai_provider()
        result = await provider.check_model_connection("gpt-4o")

        assert result.success is True
        assert result.verification == "live"
        sent = _FakeSession.last_post_kwargs
        assert sent is not None and sent["url"].endswith("/chat/completions")
        body = sent["json"]
        assert body["model"] == "gpt-4o"
        assert body["messages"], "应包含 ping 消息"
        assert body.get("max_tokens"), "应限制 max_tokens 控制探测成本"

    @pytest.mark.asyncio
    async def test_auth_failure_is_permission_denied_semantics(self, monkeypatch):
        _patch_aiohttp(
            monkeypatch,
            _FakeResponse(status=401, payload={"error": {"message": "invalid api key"}}),
        )
        provider = _make_openai_provider()
        result = await provider.check_model_connection("gpt-4o")

        assert result.success is False
        assert result.error_category == "auth_failed"
        assert result.http_status == 401

    @pytest.mark.asyncio
    async def test_model_not_found_http_404(self, monkeypatch):
        _patch_aiohttp(
            monkeypatch,
            _FakeResponse(status=404, payload={"error": {"message": "The model 'x' does not exist"}}),
        )
        provider = _make_openai_provider()
        result = await provider.check_model_connection("x")

        assert result.success is False
        assert result.http_status == 404

    @pytest.mark.asyncio
    async def test_rate_limit_marks_retryable(self, monkeypatch):
        _patch_aiohttp(
            monkeypatch,
            _FakeResponse(status=429, payload={"error": {"message": "rate limit exceeded"}}),
        )
        provider = _make_openai_provider()
        result = await provider.check_model_connection("gpt-4o")

        assert result.success is False
        assert result.http_status == 429
        assert result.retryable is True

    @pytest.mark.asyncio
    async def test_non_chat_model_falls_back_provider_only(self, monkeypatch):
        """embedding/tts 类非对话模型无法走 chat 端点 → 降级 provider 级验证。"""
        provider = _make_openai_provider()
        assert provider._is_non_chat_model("text-embedding-3-small")
        assert not provider._is_non_chat_model("gpt-4o")

        result = ConnectionResult(success=True, verification="provider_only")
        async def _fake_check_connection():
            return result

        monkeypatch.setattr(provider, "check_connection", _fake_check_connection)
        out = await provider.check_model_connection("text-embedding-3-small")
        assert out.verification == "provider_only"


# ---------------------------------------------------------------------------
# 管理器层：分类 + 持久化
# ---------------------------------------------------------------------------

class TestManagerModelConnectionPersistence:
    @pytest.mark.asyncio
    async def test_check_result_persisted_in_metadata(self, tmp_path):
        from neurova.llm.provider_manager import LLMProviderManager, reset_provider_manager

        reset_provider_manager()
        try:
            mgr = LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
            provider = mgr.add_provider(
                name="T",
                provider="openai",
                base_url="https://example.test/v1",
                api_key="sk-test-1234567890",
                models=["m-1"],
            )

            class _Inst:
                async def check_model_connection(self, model_id):
                    return ConnectionResult(success=True, verification="live", http_status=200)

            mgr._get_provider_instance = lambda pid: _Inst()
            result = await mgr.check_model_connection("m-1")

            assert result.checked_at, "管理器层应填 checked_at"
            availability = (provider.model_metadata.get("m-1") or {}).get("availability")
            assert availability is not None, "检查结果应持久化进 model_metadata"
            assert availability["status"] == "available"
            assert availability["checked_at"] == result.checked_at
        finally:
            reset_provider_manager()
