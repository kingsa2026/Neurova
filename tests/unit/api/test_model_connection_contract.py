"""

锁定契约：
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
# 七态派生
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
# 回归守卫（2026-10-08）：create_chat_model 链的两处失效
#
# 用户可见症状是模型管理「测试模型连接」恒报「langchain_openai 未安装，无法创建
# 模型实例」。根因链有两环，本类各钉一条，缺一不可：
#
#   1) 依赖缺口 —— langchain-openai/anthropic/google-genai/ollama 从未写进
#      依赖单一事实源 requirements.txt（也不在任何锁里），生产与本地按清单装完
#      必缺 → 模块级 try/except 把 ChatOpenAI 置 None → create_chat_model 抛
#      ImportError。同形态先例见 tests/unit/test_dev_path_and_runtime_dep_guards.py
#      的 TestMcpSdkDeclaredForRuntime（Issue #62）。
#   2) 构造签名冲突 —— 补上声明后同链立刻暴露第二环：六处 create_chat_model 把
#      get_llm_config() 返回值里**已含**的 model/api_key/base_url 再显式传一遍，
#      Python 在进 pydantic 之前即 TypeError: got multiple values for keyword
#      argument；且该字典还塞着 provider_id/provider_type/model_id/provider
#      这些非 langchain 字段。
#
# 判据只锁「这条链能真正产出一个模型实例」。**构造成功不等于连通**：这五个
# provider 的模型级验证仍是本地构造（verification 如实为 unverified），与本文件
# 顶部契约第 1 条要求的真实请求差一整段；该缺口已登记台账，不得把本判据当作
# 「模型级连接测试已真实化」的证据。
# ---------------------------------------------------------------------------

# (工厂导入路径, 工厂名, 位置参数) —— 用各 provider 自己的便捷函数构造，
# 不手工拼 provider_type/阈值，避开「绕过生产装配点」的假绿。
_CHAT_MODEL_FACTORIES = (
    ("neurova.llm.providers.openai_provider", "create_openai_provider", ("sk-test-1234567890",)),
    ("neurova.llm.providers.openrouter_provider", "create_openrouter_provider", ("sk-or-test",)),
    ("neurova.llm.providers.anthropic_provider", "create_anthropic_provider", ("sk-ant-test",)),
    ("neurova.llm.providers.gemini_provider", "create_gemini_provider", ("gck-test",)),
    ("neurova.llm.providers.lm_studio_provider", "create_lm_studio_provider", ()),
    ("neurova.llm.providers.ollama_provider", "create_ollama_provider", ()),
)

# check_model_connection 委托给 create_chat_model 的 provider（openai 已迁真实
# HTTP 探测，不在此列——它走网络，判据落上面 TestOpenAIModelConnectionReal）。
_LC_DELEGATING_MODULES = (
    "neurova.llm.providers.openrouter_provider",
    "neurova.llm.providers.anthropic_provider",
    "neurova.llm.providers.gemini_provider",
    "neurova.llm.providers.lm_studio_provider",
    "neurova.llm.providers.ollama_provider",
)

_CHAT_MODEL_CASE_IDS = [m.rsplit(".", 1)[-1] for m, _, _ in _CHAT_MODEL_FACTORIES]


def _make_chat_model_provider(import_path: str, factory_name: str, args):
    import importlib

    provider = getattr(importlib.import_module(import_path), factory_name)(*args)
    # 构造不发网络请求，但 base_url 一律钉到不可路由域名：万一某 provider 的
    # 构造期偷偷拨号，判据要红成超时而不是绿成「碰巧连上了」。
    provider.base_url = "http://127.0.0.1:1/v1"
    return provider


class TestProviderChatModelChainIntact:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "import_path,factory_name,args", _CHAT_MODEL_FACTORIES, ids=_CHAT_MODEL_CASE_IDS
    )
    async def test_create_chat_model_yields_instance(self, import_path, factory_name, args):
        """无依赖缺口、无重复关键字实参：构造必须真产出实例。"""
        provider = _make_chat_model_provider(import_path, factory_name, args)

        instance = await provider.create_chat_model("probe-model")

        assert instance is not None, f"{import_path} 未产出模型实例"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("module_name", _LC_DELEGATING_MODULES)
    async def test_model_connection_free_of_dependency_and_signature_failure(self, module_name):
        """用户可见面：这五个 provider 的模型级连接检查不再报「未安装」。"""
        import importlib

        factory_name = {
            "neurova.llm.providers.openrouter_provider": "create_openrouter_provider",
            "neurova.llm.providers.anthropic_provider": "create_anthropic_provider",
            "neurova.llm.providers.gemini_provider": "create_gemini_provider",
            "neurova.llm.providers.lm_studio_provider": "create_lm_studio_provider",
            "neurova.llm.providers.ollama_provider": "create_ollama_provider",
        }[module_name]
        args = () if factory_name in ("create_lm_studio_provider", "create_ollama_provider") else ("sk-test-1234567890",)
        provider = _make_chat_model_provider(module_name, factory_name, args)

        result = await provider.check_model_connection("probe-model")

        for forbidden in ("未安装", "multiple values for keyword argument", "unexpected keyword"):
            assert forbidden not in result.error, (
                f"{module_name} 模型级连接检查仍带失效签名 {forbidden!r}: {result.error}"
            )
        assert result.success is True, f"{module_name} 连接检查应成功: {result.error}"


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
