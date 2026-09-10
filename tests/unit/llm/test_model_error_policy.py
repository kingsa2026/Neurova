# -*- coding: utf-8 -*-
"""B1-1/B1-2：模型错误分类单源 + 回退资格门控（对齐 QwenPaw
providers/model_error_policy.py 与 model_capability_cache.py）。

锁定契约：
1. classify_model_error 八类：authentication / bad_request / context_overflow /
   content_safety / model_not_found / rate_limited / transient / unknown。
2. 回退资格：仅 rate_limited / transient / model_not_found 允许跨模型回退——
   auth/bad_request/context_overflow/content_safety 换模型无意义，不回退。
3. MultiModelClient：transient（超时/连接/5xx）必须触发 auto failover
   （旧行为只认 rate_limit/not_found，网络抖动整轮失败）。
4. ModelCapabilityCache：learn/get/forget/clear + TTL 过期。
"""
from __future__ import annotations

import asyncio

import pytest

from neurova.llm.model_error_policy import classify_model_error


class TestClassifyModelError:
    def test_authentication_401_not_fallback_eligible(self):
        d = classify_model_error("Error code: 401 - invalid api key")
        assert d.kind == "authentication"
        assert d.fallback_eligible is False

    def test_model_not_found_fallback_eligible(self):
        d = classify_model_error("Error code: 404 - model gpt-x does not exist")
        assert d.kind == "model_not_found"
        assert d.fallback_eligible is True

    def test_rate_limited_fallback_eligible(self):
        d = classify_model_error("Error code: 429 - too many requests")
        assert d.kind == "rate_limited"
        assert d.retryable is True
        assert d.fallback_eligible is True

    def test_timeout_is_transient_and_fallback_eligible(self):
        d = classify_model_error("Request timed out after 60s")
        assert d.kind == "transient"
        assert d.fallback_eligible is True

    def test_connection_error_is_transient(self):
        d = classify_model_error("Connection error: peer closed connection")
        assert d.kind == "transient"
        assert d.fallback_eligible is True

    def test_server_5xx_is_transient(self):
        d = classify_model_error("Error code: 503 - service unavailable")
        assert d.kind == "transient"
        assert d.fallback_eligible is True

    def test_context_overflow_not_fallback_eligible(self):
        d = classify_model_error("This model's maximum context length is 8192 tokens")
        assert d.kind == "context_overflow"
        assert d.fallback_eligible is False

    def test_content_safety_not_fallback_eligible(self):
        d = classify_model_error("Error: content policy violation detected")
        assert d.kind == "content_safety"
        assert d.fallback_eligible is False

    def test_bad_request_400_not_fallback_eligible(self):
        d = classify_model_error("Error code: 400 - invalid parameter temperature")
        assert d.kind == "bad_request"
        assert d.fallback_eligible is False

    def test_exception_input_accepted(self):
        d = classify_model_error(TimeoutError("operation timed out"))
        assert d.kind == "transient"

    def test_unknown(self):
        d = classify_model_error("something weird happened")
        assert d.kind == "unknown"
        assert d.fallback_eligible is False


class TestMultiModelClientFailoverGate:
    """transient 必须触发跨模型回退；auth 不触发（旧行为缺 transient）。"""

    def _make_client(self):
        from neurova.llm.multi_model_client import MultiModelLLMClient

        client = object.__new__(MultiModelLLMClient)
        client._clients = {"a": object(), "b": object(), "c": object()}
        return client

    def _wire_two_models(self, client, errors):
        """first 模型按 errors 顺序失败，second 模型成功。"""
        calls = {"n": 0}

        async def fake_attempt(cl, messages, **kw):
            if getattr(cl, "model", "") == "first":
                err = errors[min(calls["n"], len(errors) - 1)]
                calls["n"] += 1
                return {"success": False, "error": err, "model": "first", "provider": "p1"}
            return {"success": True, "response": "ok", "model": "second", "provider": "p2"}

        client._get_client_for_request = lambda model, provider_id: _FakeClient("first")
        client._chat_single_attempt = fake_attempt
        client._next_failover_client = lambda failed, excluded: _FakeClient("second")
        return calls

    def test_transient_error_triggers_failover(self):
        client = self._make_client()
        self._wire_two_models(client, ["Request timed out after 60s"])

        async def scenario():
            result = await client.chat([{"role": "user", "content": "hi"}])
            assert result.get("success") is True
            assert result.get("model") == "second"

        asyncio.run(scenario())

    def test_connection_error_triggers_failover(self):
        client = self._make_client()
        self._wire_two_models(client, ["Connection error: refused"])

        async def scenario():
            result = await client.chat([{"role": "user", "content": "hi"}])
            assert result.get("success") is True
            assert result.get("model") == "second"

        asyncio.run(scenario())

    def test_auth_error_does_not_failover(self):
        client = self._make_client()
        calls = self._wire_two_models(client, ["Error code: 401 - invalid api key"])

        async def scenario():
            result = await client.chat([{"role": "user", "content": "hi"}])
            assert result.get("success") is False
            assert calls["n"] == 1  # 没有切模型

        asyncio.run(scenario())

    def test_rate_limit_still_failover(self):
        client = self._make_client()
        self._wire_two_models(client, ["Error code: 429 - too many requests"])

        async def scenario():
            result = await client.chat([{"role": "user", "content": "hi"}])
            assert result.get("success") is True

        asyncio.run(scenario())


class _FakeClient:
    def __init__(self, model):
        self.model = model
        self.provider = type("P", (), {"id": "p1"})()


class TestModelCapabilityCache:
    def test_learn_get_forget(self):
        from neurova.llm.model_capability_cache import ModelCapabilityCache

        cache = ModelCapabilityCache()
        cache.learn("p1:m1", "supports_multimodal", False)
        assert cache.get("p1:m1", "supports_multimodal") is False
        assert cache.get("p1:m1", "other", default=True) is True
        cache.forget("p1:m1", "supports_multimodal")
        assert cache.get("p1:m1", "supports_multimodal", default="unset") == "unset"

    def test_clear_scoped(self):
        from neurova.llm.model_capability_cache import ModelCapabilityCache

        cache = ModelCapabilityCache()
        cache.learn("p1:m1", "k", 1)
        cache.learn("p1:m2", "k", 2)
        cache.clear("p1:m1")
        assert cache.get("p1:m1", "k", default=0) == 0
        assert cache.get("p1:m2", "k", default=0) == 2
        cache.clear()
        assert cache.get("p1:m2", "k", default=0) == 0

    def test_ttl_expiry(self, monkeypatch):
        import neurova.llm.model_capability_cache as mod

        monkeypatch.setattr(mod, "CAPABILITY_CACHE_TTL_SECONDS", 0.01)
        cache = mod.ModelCapabilityCache()
        cache.learn("p:m", "k", "v")
        import time as _t

        _t.sleep(0.03)
        assert cache.get("p:m", "k", default="gone") == "gone"

    def test_singleton(self):
        from neurova.llm.model_capability_cache import (
            get_capability_cache,
            reset_capability_cache,
        )

        reset_capability_cache()
        assert get_capability_cache() is get_capability_cache()
        reset_capability_cache()


class TestDiscoveryErrorKinds:
    """B1-1：发现失败 error_kind 对齐 QwenPaw 细分（timeout 独立 / 403=authorization）。"""

    def test_timeout_exception_maps_to_timeout_kind(self):
        from neurova.llm.provider_manager import _classify_discovery_error_kind

        assert _classify_discovery_error_kind(asyncio.TimeoutError("timed out")) == "timeout"
        assert _classify_discovery_error_kind(TimeoutError("read timeout")) == "timeout"

    def test_403_maps_to_authorization(self):
        from neurova.llm.provider_manager import _classify_discovery_error_kind

        assert _classify_discovery_error_kind(Exception("Error code: 403 - forbidden")) == "authorization"

    def test_401_maps_to_authentication(self):
        from neurova.llm.provider_manager import _classify_discovery_error_kind

        assert _classify_discovery_error_kind(Exception("Error code: 401 - unauthorized")) == "authentication"

    def test_connection_maps_to_network(self):
        from neurova.llm.provider_manager import _classify_discovery_error_kind

        assert _classify_discovery_error_kind(Exception("connection refused")) == "network"

    def test_bare_numeric_code_429_detected(self):
        """防回归：裸 "429" 文本必须识别为 rate_limited（旧 _classify_error
        覆盖面，LLMRateLimitError("429 slow down") 消费方依赖）。"""
        d = classify_model_error("429 slow down")
        assert d.kind == "rate_limited"
        assert d.fallback_eligible is True

    def test_bare_numeric_code_not_partial_match(self):
        assert classify_model_error("error 14293 occurred").kind == "unknown"
