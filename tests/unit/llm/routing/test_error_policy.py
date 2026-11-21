# -*- coding: utf-8 -*-
"""R1（参照系 ad 追平批一）：路由错误语义表封闭集。

契约（源自 docs/04-plans/2026-11-22-reference-ad-llm-routing-catchup-
implementation-plan.md R1 卡，对齐专项细拆轴 4/5 的对方语义）：

- rate_limited → RETRY_SAME：同模型等待重试（429 预算内）；预算耗尽后
  仍可 FALLBACK（is_fallback_eligible 对 429 恒 True，消费方先重试后切换）。
- transient（超时/连接/5xx，及 408/409/423/425 这类"换家可活"的网关态）
  / model_not_found / authentication → FALLBACK。
  **契约变更（2026-11-22）**：authentication 由「不回退」（B1-2 旧约，
  理由"换模型同样 401"）改为「可回退」——该理由只在单 provider 内成立；
  多服务商各持独立 key 时换家能真解决 key 失效，且 auto_failover 本就
  仅作用于未显式钉死 provider 的请求，存量钉死行为不变。
- context_overflow / content_safety / bad_request / insufficient_balance /
  unknown → STOP：换模型无意义或应诚实失败。

全仓消费方（教义第 5 条全命中点）：chat() 跨模型回退与 chat_stream()
切换容错两条路径都读本表，不再各持一份。
"""

import pytest

from neurova.llm.routing.error_policy import (
    RouteDecision,
    decideRoute,
    is_fallback_eligible,
    retry_same_model,
)


class TestRouteDecisionTable:
    def test_rate_limited_recommends_retry_same_then_fallback(self):
        err = "Error code: 429 - too many requests"
        assert decideRoute(err) is RouteDecision.RETRY_SAME
        assert retry_same_model(err) is True
        # 预算耗尽后仍允许切换：429 恒为可回退
        assert is_fallback_eligible(err) is True

    def test_auth_401_403_fallback(self):
        """契约变更：auth 由 STOP 改 FALLBACK（多服务商独立 key，换家可解）。"""
        assert is_fallback_eligible("Error code: 401 - invalid api key") is True
        assert is_fallback_eligible("Error code: 403 - forbidden") is True
        assert decideRoute("unauthorized: bad key") is RouteDecision.FALLBACK

    def test_gateway_transient_states_fallback(self):
        """408/409/423/425：对方语义里"换家可活"的网关态，本仓旧判归 bad_request 不切。"""
        for code in (408, 409, 423, 425):
            err = f"Error code: {code} - transient gateway state"
            assert is_fallback_eligible(err) is True, code
            assert decideRoute(err) is RouteDecision.FALLBACK, code

    def test_timeout_and_connection_fallback(self):
        assert is_fallback_eligible("Request timed out after 60s") is True
        assert is_fallback_eligible("Connection error: peer closed connection") is True
        assert is_fallback_eligible(TimeoutError("operation timed out")) is True

    def test_model_not_found_fallback(self):
        assert is_fallback_eligible("Error code: 404 - model gpt-x does not exist") is True

    def test_context_overflow_stop(self):
        err = "This model's maximum context length is 8192 tokens"
        assert is_fallback_eligible(err) is False
        assert decideRoute(err) is RouteDecision.STOP

    def test_content_safety_stop(self):
        assert is_fallback_eligible("Error: content policy violation detected") is False

    def test_insufficient_balance_stop(self):
        assert is_fallback_eligible("Error code: 402 - insufficient balance, please top up") is False

    def test_bad_request_stop(self):
        assert is_fallback_eligible("Error code: 400 - invalid parameter temperature") is False

    def test_unknown_stop(self):
        assert is_fallback_eligible("something weird happened") is False


class TestSingleSource:
    """教义第 6 条：分类与路由决策互为单源，不得各持一份。"""

    def test_classification_and_policy_agree(self):
        from neurova.llm.model_error_policy import classify_model_error

        for err in (
            "Error code: 401 - invalid api key",
            "Error code: 429 - too many requests",
            "Error code: 409 - conflict",
            "This model's maximum context length is 8192 tokens",
            "Error code: 404 - model gpt-x does not exist",
        ):
            d = classify_model_error(err)
            assert d.fallback_eligible is is_fallback_eligible(err), err

    def test_stream_and_chat_share_the_table(self):
        """流式切换与 chat 回退读同一张表：凡 chat 判可切的，流式也切。"""
        from neurova.llm.routing.error_policy import (
            FALLBACK_ELIGIBLE_KINDS,
            RETRY_SAME_KIND,
        )

        assert "rate_limited" in FALLBACK_ELIGIBLE_KINDS
        assert RETRY_SAME_KIND == "rate_limited"


# ── R1 live-verify 根因固化为用例 ──────────────────────────────────────
# 真管线 live-verify 实测：语义表放行切换后，_next_failover_client 仍可能
# 无候选可切——生产装配只初始化默认 provider，而候选解析只在已初始化的
# _clients 里找、且按「模型名」排除（两服务商同名模型时互相顶掉）。
# 期望：跨服务商、同名模型也能懒建候选完成回退。

import asyncio  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch  # noqa: E402

import neurova.llm.multi_model_client as _mmc_mod  # noqa: E402
from neurova.llm.multi_model_client import (  # noqa: E402
    ModelClient,
    MultiModelLLMClient,
)


class _ScriptedInner:
    """非流式内层桩：按脚本出牌（真实 _chat_single_attempt 消费）。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        behavior = self.script.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


class _ScriptedStreamInner:
    """流式内层桩：脚本项 Exception→立即抛；list→逐个 yield（末项 Exception=中流断）。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def chat_stream_async(self, messages, **kwargs):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        for piece in item:
            if isinstance(piece, Exception):
                raise piece
            yield piece


def _chunk(text):
    return SimpleNamespace(content=text, reasoning_content=None, usage=None,
                           tool_calls=None, finish_reason=None)


def _two_provider_pm(tmp_path):
    """真实 ProviderManager（tmp 配置）：bad(优先级高) + good，同名模型。"""
    from neurova.llm.provider_manager import LLMProviderManager

    pm = LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
    pm.add_provider(name="ad-bad", provider="openai", base_url="http://127.0.0.1:1/v1",
                    api_key="sk-bad", models=["stub-model"], default_model="stub-model",
                    priority=20)
    pm.add_provider(name="ad-good", provider="openai", base_url="http://127.0.0.1:2/v1",
                    api_key="sk-good", models=["stub-model"], default_model="stub-model",
                    priority=10)
    return pm


class TestFailoverCandidateResolution:
    def test_chat_auth_failover_across_providers_same_model(self, tmp_path):
        """401 后应懒建另一服务商的同名模型候选并回退成功（旧实现无候选可切）。"""
        from neurova.llm_client import LLMResponse

        pm = _two_provider_pm(tmp_path)
        inners = {
            "ad-bad": _ScriptedInner([Exception("Error code: 401 - invalid api key")]),
            "ad-good": _ScriptedInner([LLMResponse(content="fallback-ok")]),
        }

        def fake_create(self, provider, model):
            # 与生产 _create_model_client 同契约：创建即登记进 _clients
            mc = ModelClient(inners[provider.id], provider, model)
            self._clients[f"{provider.id}/{model}"] = mc
            return mc

        with patch.object(MultiModelLLMClient, "_create_model_client", fake_create):
            mmc = MultiModelLLMClient(provider_manager=pm)
            result = asyncio.run(mmc.chat([{"role": "user", "content": "hi"}]))

        assert result.get("success") is True, result
        assert result.get("provider") == "ad-good"
        assert inners["ad-bad"].calls == 1 and inners["ad-good"].calls == 1

    def test_stream_auth_failover_across_providers_same_model(self, tmp_path):
        """流式同样：401 后懒建候选切换，消费方拿到好服务商的完整输出。"""
        pm = _two_provider_pm(tmp_path)
        inners = {
            "ad-bad": _ScriptedStreamInner([Exception("Error code: 401 - invalid api key")]),
            "ad-good": _ScriptedStreamInner([[_chunk("b-ok")]]),
        }

        def fake_create(self, provider, model):
            # 与生产 _create_model_client 同契约：创建即登记进 _clients
            mc = ModelClient(inners[provider.id], provider, model)
            self._clients[f"{provider.id}/{model}"] = mc
            return mc

        with patch.object(MultiModelLLMClient, "_create_model_client", fake_create):
            mmc = MultiModelLLMClient(provider_manager=pm)

            async def collect(agen):
                return [c async for c in agen]

            items = asyncio.run(collect(mmc.chat_stream([{"role": "user", "content": "hi"}])))

        chunks = [c for c in items if not isinstance(c, dict)]
        errors = [c for c in items if isinstance(c, dict) and c.get("error")]

        assert [c.content for c in chunks] == ["b-ok"]
        assert errors == []
