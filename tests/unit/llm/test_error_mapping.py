"""_invoke_error_mapping 五类标准错误（TDD — Dify 对标补课 §3.3）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §2.5 / §3.3）：
- 五类：connection_failed（连接失败）/ service_unavailable（服务不可用）/
  rate_limited（限频）/ auth_failed（鉴权）/ bad_request（坏请求）
- 每类携带 retryable 标志（连接/不可用/限频可重试；鉴权/坏请求不可重试）
  与用户可行动提示（user_hint）——前端据此给可行动错误
- 归一入口 normalize_provider_error(exc)：按异常类型/HTTP 状态码归一，
  未识别异常 → bad_request 兜底（不丢原信息）
- openai SDK 异常族映射（APIConnectionError/RateLimitError/AuthenticationError/
  APIStatusError/NotFoundError...），openai 未安装时降级字符串模式匹配
- ConnectionResult 扩展：error_category 字段（base.check_connection 消费）
"""

import pytest

from neurova.llm.providers.error_mapping import (
    ErrorCategory,
    ProviderError,
    normalize_provider_error,
)


class TestFiveCategories:
    def test_five_categories_exist(self):
        assert ErrorCategory.CONNECTION.value == "connection_failed"
        assert ErrorCategory.UNAVAILABLE.value == "service_unavailable"
        assert ErrorCategory.RATE_LIMIT.value == "rate_limited"
        assert ErrorCategory.AUTH.value == "auth_failed"
        assert ErrorCategory.BAD_REQUEST.value == "bad_request"

    def test_retryable_flags(self):
        assert ErrorCategory.CONNECTION.retryable
        assert ErrorCategory.UNAVAILABLE.retryable
        assert ErrorCategory.RATE_LIMIT.retryable
        assert not ErrorCategory.AUTH.retryable
        assert not ErrorCategory.BAD_REQUEST.retryable

    def test_user_hints_actionable(self):
        for cat in ErrorCategory:
            assert cat.user_hint, f"{cat} 缺少用户提示"


class TestNormalizeByExceptionType:
    def test_connection_errors(self):
        for exc in (ConnectionError(), TimeoutError(), OSError("network down")):
            err = normalize_provider_error(exc)
            assert err.category is ErrorCategory.CONNECTION, (type(exc), err.category)

    def test_llm_error_subclasses_preserved(self):
        from neurova.llm_client import (
            LLMAuthError,
            LLMBadRequestError,
            LLMConnectionError,
            LLMRateLimitError,
        )

        assert normalize_provider_error(LLMRateLimitError("429")).category is ErrorCategory.RATE_LIMIT
        assert normalize_provider_error(LLMAuthError("401")).category is ErrorCategory.AUTH
        assert normalize_provider_error(LLMBadRequestError("bad")).category is ErrorCategory.BAD_REQUEST
        assert normalize_provider_error(LLMConnectionError("conn")).category is ErrorCategory.CONNECTION

    def test_unknown_exception_falls_to_bad_request(self):
        err = normalize_provider_error(ValueError("weird"))
        assert err.category is ErrorCategory.BAD_REQUEST
        assert "weird" in err.message, "原始信息不丢失"


class TestNormalizeByHttpStatus:
    """按 HTTP 状态码归一（aiohttp/httpx/litellm 等抛自定义异常时以状态码为准）"""

    class HttpLike(Exception):
        def __init__(self, status_code: int, message: str = ""):
            super().__init__(message or f"HTTP {status_code}")
            self.status_code = status_code

    def _norm(self, code):
        return normalize_provider_error(self.HttpLike(code))

    def test_401_403_auth(self):
        assert self._norm(401).category is ErrorCategory.AUTH
        assert self._norm(403).category is ErrorCategory.AUTH

    def test_429_rate_limit(self):
        assert self._norm(429).category is ErrorCategory.RATE_LIMIT

    def test_404_bad_request(self):
        assert self._norm(404).category is ErrorCategory.BAD_REQUEST

    def test_5xx_service_unavailable(self):
        for code in (500, 502, 503, 504):
            assert self._norm(code).category is ErrorCategory.UNAVAILABLE, code

    def test_bad_request_4xx(self):
        for code in (400, 402, 422):
            assert self._norm(code).category is ErrorCategory.BAD_REQUEST, code

    def test_provider_error_passthrough(self):
        """已是 ProviderError 的直接返回（幂等）"""
        original = ProviderError(ErrorCategory.RATE_LIMIT, "429 too many")
        assert normalize_provider_error(original) is original


class TestOpenAiSdkMapping:
    def _sdk_exc(self, cls, message="err"):
        """构造 openai SDK 异常（httpx.Response 链需要 mock）"""
        from unittest.mock import MagicMock

        response = MagicMock()
        response.status_code = 500
        response.request = MagicMock()
        if cls.__name__ == "APIConnectionError":
            return cls(request=response.request)
        return cls(message, response=response, body=None)

    def test_openai_exceptions_mapped(self):
        """openai SDK 异常按真实异常类映射"""
        import openai

        rate = getattr(openai, "RateLimitError", None)
        auth = getattr(openai, "AuthenticationError", None)
        conn = getattr(openai, "APIConnectionError", None)
        unavailable = getattr(openai, "InternalServerError", None)
        not_found = getattr(openai, "NotFoundError", None)

        assert normalize_provider_error(self._sdk_exc(rate, "429 rl")).category is ErrorCategory.RATE_LIMIT
        assert normalize_provider_error(self._sdk_exc(auth, "401")).category is ErrorCategory.AUTH
        assert normalize_provider_error(self._sdk_exc(conn)).category is ErrorCategory.CONNECTION
        assert normalize_provider_error(self._sdk_exc(unavailable, "boom")).category is ErrorCategory.UNAVAILABLE
        assert normalize_provider_error(self._sdk_exc(not_found, "no model")).category is ErrorCategory.BAD_REQUEST


class TestStringFallback:
    def test_message_patterns(self):
        """无类型/状态码可依时按消息关键词兜底（litellm/网关自定义异常）"""
        assert normalize_provider_error(RuntimeError("401 unauthorized")).category is ErrorCategory.AUTH
        assert normalize_provider_error(RuntimeError("rate limit exceeded")).category is ErrorCategory.RATE_LIMIT
        assert normalize_provider_error(RuntimeError("connection refused")).category is ErrorCategory.CONNECTION
        assert normalize_provider_error(RuntimeError("service unavailable")).category is ErrorCategory.UNAVAILABLE

    def test_sensitive_material_masked(self):
        """鉴权错误不得在 user_hint 里回显 key 片段"""
        err = normalize_provider_error(RuntimeError("401 invalid api key sk-abc123secret"))
        assert "sk-abc123secret" not in err.user_hint


class TestConnectionResultIntegration:
    def test_base_provider_attaches_category(self):
        """BaseProvider.check_connection 消费归一结果（error_category 字段）"""
        import asyncio

        from neurova.llm.providers.types import ConnectionResult

        class StubProvider:
            # 借用 BaseProvider.check_connection 的 unbound 方法
            from neurova.llm.providers.base import BaseProvider

            check_connection = BaseProvider.check_connection

            def __init__(self):
                self.logger = __import__("logging").getLogger("stub")

            async def get_available_models(self):
                raise self.HttpLike(429, "too many requests")

            class HttpLike(Exception):
                def __init__(self, code, msg):
                    super().__init__(msg)
                    self.status_code = code

        result = asyncio.run(StubProvider().check_connection())
        assert result.success is False
        assert result.error_category == "rate_limited", f"应归一为限频: {result.error_category}"
        assert result.metadata.get("retryable") is True
