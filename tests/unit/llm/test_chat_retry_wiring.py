"""
P2-2 LLM 层 — chat 请求路径 retry/circuit-breaker 装配测试

- 砌装配（评测指出 rate_limiter.py 构件齐备但零装配）：
  MultiModelLLMClient._chat_with_retry 静态方法——per-provider 熔断器 +
  指数退避重试，接入 chat() 请求路径
- 可重试集合：LLMRateLimitError / LLMConnectionError / ConnectionError /
  TimeoutError；LLMAuthError 与其他异常不重试（立即上抛由 chat() 转 error 信封）
- 熔断：同 provider 连续 5 次失败后打开，拒绝请求不触达底层；跨 provider 隔离
"""

import asyncio

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from neurova.llm_client import (
    LLMAuthError,
    LLMClient,
    LLMRateLimitError,
    LLMResponse,
)
from neurova.llm.multi_model_client import MultiModelLLMClient
from neurova.llm.providers.rate_limiter import CircuitBreakerOpen


class _ScriptedInner:
    """按脚本出牌的内层同步 chat（模拟 LLMClient.chat）。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(1)
        behavior = self.script.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def _make_client(script, provider_id="p1"):
    inner = _ScriptedInner(script)
    client = SimpleNamespace(
        client=inner,
        model="test-model",
        provider=SimpleNamespace(id=provider_id),
        increment_request=MagicMock(),
    )
    return client, inner


def _make_mmc(client):
    """构造最小 MultiModelLLMClient：绕 __init__，桩 _get_client_for_request"""
    mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)
    mmc._get_client_for_request = lambda model=None, provider_id=None: client
    return mmc


def _chat_via(client, messages=None):
    """走完整 chat() 信封路径（信封契约是 chat 的职责）"""
    mmc = _make_mmc(client)
    return mmc.chat(messages or [{"role": "user", "content": "hi"}])


@pytest.fixture(autouse=True)
def _isolate_guards():
    """每个测试独立熔断器缓存（跨测试隔离）"""
    MultiModelLLMClient._retry_guards = {}
    yield
    MultiModelLLMClient._retry_guards = {}


class TestRetryWiring:
    @pytest.mark.asyncio
    async def test_transient_failure_retried_then_success(self):
        client, inner = _make_client([LLMRateLimitError("rate limited"), LLMResponse(content="ok")])

        result = await _chat_via(client)

        assert result["success"] is True
        assert len(inner.calls) == 2  # 失败一次 + 重试成功
        assert client.increment_request.call_count == 1  # 最终结果只计一次

    @pytest.mark.asyncio
    async def test_auth_error_no_retry(self):
        client, inner = _make_client([LLMAuthError("bad key")])

        result = await _chat_via(client)

        assert result["success"] is False
        assert "bad key" in result["error"]
        assert len(inner.calls) == 1  # 认证错误不重试

    @pytest.mark.asyncio
    async def test_persistent_failure_exhausts_attempts(self):
        client, inner = _make_client([LLMRateLimitError("rl")] * 5)

        result = await _chat_via(client)

        assert result["success"] is False
        assert len(inner.calls) == 3  # 默认 max_attempts=3

    @pytest.mark.asyncio
    async def test_success_path_envelope_unchanged(self):
        resp = LLMResponse(content="hi there")
        client, inner = _make_client([resp])
        result = await _chat_via(client)
        assert result["success"] is True
        assert result["response"] is resp
        assert result["provider"] == "p1"


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self):
        """连续 5 次失败后熔断打开：第 6 次调用不触达底层"""
        client, inner = _make_client([LLMRateLimitError("rl")] * 30)

        for _ in range(5):
            await _chat_via(client)  # 5 轮 × 3 attempts = 15 次失败 → 熔断记满 5 次

        # 熔断稳态：后续调用零触达（recovery_timeout=30s 内）
        result = await _chat_via(client)
        assert result["success"] is False
        assert len(inner.calls) == 15
        assert "熔断" in result["error"] or "open" in result["error"].lower()

        result = await _chat_via(client)
        assert result["success"] is False
        assert len(inner.calls) == 15

    @pytest.mark.asyncio
    async def test_circuit_isolated_per_provider(self):
        """provider A 熔断不影响 provider B"""
        client_a, inner_a = _make_client([LLMRateLimitError("rl")] * 10, provider_id="pa")
        client_b, inner_b = _make_client([LLMResponse(content="ok")], provider_id="pb")

        for _ in range(5):
            await _chat_via(client_a)

        result = await _chat_via(client_b)
        assert result["success"] is True  # B 不受 A 熔断影响


class TestIncrementAccounting:
    @pytest.mark.asyncio
    async def test_increment_records_final_outcome_only(self):
        client, inner = _make_client([LLMRateLimitError("rl"), LLMResponse(content="ok")])
        await _chat_via(client)
        # 重试中间态不计，最终成功计 1
        client.increment_request.assert_called_once_with(success=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
