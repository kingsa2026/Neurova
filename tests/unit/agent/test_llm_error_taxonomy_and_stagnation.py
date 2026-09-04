"""LLM 错误分类学 + 停滞检测闭环 + token 预算闸门（TDD 红绿）

来源：docs/openmanus-comparison.md P2/P3/P4。

实测缺陷链（2026-08-29）：modelscope 限流 → llm_client 包装 RuntimeError →
_call_agent_loop 静默 fallback → legacy 再炸 → 用户拿到空回复。
三个结构性修复：
A. 错误分类学：限流/认证/连接/token 四类异常不被异化、不被 fallback 吞掉；
B. 停滞检测：激活 agent_loop_detection 死代码，检测→注入提示→终止闭环；
C. token 计数：tiktoken 精确计数替代 len*1.5 估算 + max_input_tokens 闸门。

凭据纪律：测试一律用 LLMConfig() 默认空配置，客户端在用例内替换为 mock。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMClient, LLMConfig, LLMResponse


def make_loop():
    agent = MagicMock()
    agent._tool_messages_list = []
    agent.skill_registry = None
    agent.tool_router = SimpleNamespace(
        execute=lambda **kw: SimpleNamespace(success=True, result={"ok": 1}, error=None)
    )
    return OpenAILoop(agent)


class ChunkLLM:
    """按轮次依次产出预设 chunk 的假流式客户端。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []

    async def chat_stream(self, messages, **kwargs):
        self.calls.append({"messages": list(messages), "kwargs": dict(kwargs)})
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        for chunk in self.rounds[idx]:
            yield chunk


async def collect(gen):
    return [event async for event in gen]


def _tool_call_chunk(name="search", args="{}"):
    return LLMResponse(
        content="",
        tool_calls=[{"id": "c1", "type": "function", "function": {"name": name, "arguments": args}}],
        finish_reason="tool_calls",
    )


# ══════════════════════════════════════════════════════════════
# A. 错误分类学
# ══════════════════════════════════════════════════════════════


def _openai_error(cls, status: int):
    req = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    resp = httpx.Response(status, request=req)
    return cls(f"error-{status}", response=resp, body=None)


def _generic_api_error():
    """openai v1 基类 APIError 签名是 (message, request, *, body)，与子类不同"""
    from openai import APIError

    req = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    return APIError("error-500", req, body=None)


class TestErrorTaxonomy:
    def test_exception_classes_exist_and_hierarchy(self):
        from neurova.llm_client import (
            LLMError,
            LLMRateLimitError,
            LLMAuthError,
            LLMConnectionError,
            TokenLimitExceeded,
        )

        for cls in (LLMRateLimitError, LLMAuthError, LLMConnectionError, TokenLimitExceeded):
            assert issubclass(cls, LLMError)
        # 向后兼容：既有 except RuntimeError 处理器仍能接住
        assert issubclass(LLMError, RuntimeError)

    def test_wrap_llm_error_classifies(self):
        from openai import APIConnectionError, AuthenticationError, RateLimitError
        from neurova.llm_client import (
            LLMRateLimitError,
            LLMAuthError,
            LLMConnectionError,
            TokenLimitExceeded,
        )

        assert isinstance(LLMClient._wrap_llm_error(_openai_error(RateLimitError, 429)), LLMRateLimitError)
        assert isinstance(LLMClient._wrap_llm_error(_openai_error(AuthenticationError, 401)), LLMAuthError)
        assert isinstance(
            LLMClient._wrap_llm_error(
                APIConnectionError(request=httpx.Request("POST", "https://api.example.com"))
            ),
            LLMConnectionError,
        )
        token_err = TokenLimitExceeded("over budget")
        assert LLMClient._wrap_llm_error(token_err) is token_err
        # P0 补课：五类标准错误——5xx APIError 归一为服务不可用（可重试）
        from neurova.llm_client import LLMServiceUnavailableError

        generic = LLMClient._wrap_llm_error(_generic_api_error())
        assert isinstance(generic, LLMServiceUnavailableError) and "error-500" in str(generic)
        # 未知异常（无类型/状态码/关键词命中）原样透传，不篡改类型
        weird = ValueError("totally unknown")
        assert LLMClient._wrap_llm_error(weird) is weird

    @pytest.mark.asyncio
    async def test_stream_async_surfaces_classified_error(self):
        """流式路径抛出的必须是分类异常，而非裸 RuntimeError"""
        from openai import RateLimitError
        from neurova.llm_client import LLMRateLimitError

        client = LLMClient(LLMConfig())
        client.async_client = MagicMock()
        client.async_client.chat.completions.create = AsyncMock(
            side_effect=_openai_error(RateLimitError, 429)
        )

        with pytest.raises(LLMRateLimitError):
            async for _ in client.chat_stream_async([{"role": "user", "content": "hi"}]):
                pass

    def test_dict_error_with_type_maps_to_classified_exception(self):
        """错误 dict（流式内部路径）携带 error_type 时必须抛分类异常"""
        from neurova.llm_client import LLMRateLimitError, TokenLimitExceeded

        loop = make_loop()
        loop.llm_client = ChunkLLM([[{"error": "请求频率过高", "error_type": "rate_limit"}]])

        with pytest.raises(LLMRateLimitError):
            asyncio.run(collect(loop._predict_stream({"messages": [], "stream": True})))

        loop2 = make_loop()
        loop2.llm_client = ChunkLLM([[{"error": "超预算", "error_type": "token_limit"}]])
        with pytest.raises(TokenLimitExceeded):
            asyncio.run(collect(loop2._predict_stream({"messages": [], "stream": True})))


class TestNoSilentFallback:
    @staticmethod
    def _pipeline_with_loop(side_effect):
        """loop 是只读 property（代理 agent.loop），通过 mock agent 注入"""
        agent = MagicMock()
        agent.loop.predict_step = AsyncMock(side_effect=side_effect)
        return ChatPipeline(agent), agent

    @pytest.mark.asyncio
    async def test_provider_errors_bypass_fallback(self):
        """LLM 供应商错误必须直接上抛，不得静默 fallback 到 legacy"""
        from neurova.llm_client import LLMRateLimitError

        pipeline, _ = self._pipeline_with_loop(LLMRateLimitError("请求频率过高"))
        pipeline._call_legacy = AsyncMock(return_value="swallowed")

        ctx = ChatContext(user_input="hi", stream=False)
        with pytest.raises(LLMRateLimitError):
            await pipeline._call_agent_loop(ctx, None)

        pipeline._call_legacy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_loop_implementation_errors_still_fallback(self):
        """Loop 自身实现错误仍走 fallback（保留既有行为）"""
        pipeline, agent = self._pipeline_with_loop(ValueError("loop bug"))
        agent.llm_client = SimpleNamespace(
            chat=AsyncMock(return_value=SimpleNamespace(content="legacy ok"))
        )

        ctx = ChatContext(user_input="hi", stream=False)
        reply = await pipeline._call_agent_loop(ctx, None)

        assert reply == "legacy ok"


# ══════════════════════════════════════════════════════════════
# B. 停滞检测闭环
# ══════════════════════════════════════════════════════════════


class TestStagnationDetection:
    def test_assess_stagnation_content_and_call_signature(self):
        loop = make_loop()
        loop._round_replies = ["我搜索一下 A。"]
        # 内容相似 + 调用签名相同 → 停滞
        assert loop._assess_stagnation("我搜索一下 A。", [("search", "{}")], [("search", "{}")]) is True
        # 内容不同但调用签名重复 → 停滞
        assert loop._assess_stagnation("完全不同的回复内容。", [("search", "{}")], [("search", "{}")]) is True
        # 都不同 → 非停滞
        assert loop._assess_stagnation("完全不同的回复内容。", [("search", "{}")], [("browse", "{}")]) is False
        # 空回复（纯工具轮）不算内容停滞，签名不同 → 非停滞
        assert loop._assess_stagnation("", [("search", "{}")], [("search", "{other}")]) is False

    def test_stagnation_flow_injects_then_stops(self):
        """时间线：round1 首轮非停滞 → round2 停滞#1 注入提示 →
        round3 仍停滞 → 停滞#2 终止（第 4 轮请求不发生）"""
        loop = make_loop()
        same_reply = "我搜索一下。"
        rounds = [
            [LLMResponse(content=same_reply), _tool_call_chunk()],
            [LLMResponse(content=same_reply), _tool_call_chunk()],
            [LLMResponse(content=same_reply), _tool_call_chunk()],
            [LLMResponse(content="不应被执行")],
        ]
        llm = ChunkLLM(rounds)
        loop.llm_client = llm
        loop.handle_tool_calls = AsyncMock(
            return_value=[{"role": "tool", "tool_call_id": "c1", "content": "r"}]
        )

        events = asyncio.run(
            collect(loop._predict_stream({"messages": [{"role": "user", "content": "hi"}], "stream": True}))
        )

        # P2-5 DoomLoopGate 新契约：比旧停滞机制更快反应——
        # round2 请求即含注入提示（第 1 次重复 → INTERRUPT），
        # round3 终止（第 2 次重复 → count>=max_interrupts=2 → TERMINATE）
        assert len(llm.calls) == 3, f"round3 应终止: {len(llm.calls)} 轮"
        injected = lambda msgs: [  # noqa: E731
            m for m in msgs if m.get("role") == "user" and "策略" in str(m.get("content", ""))
        ]
        assert injected(llm.calls[0]["messages"]) == [], "round1 请求不应含注入（首次通过）"
        assert injected(llm.calls[1]["messages"]) == [], "round2 请求不含注入（gate 在轮末触发，注入落 round3）"
        assert injected(llm.calls[2]["messages"]), "round3 请求应含 round2 末注入的换策略提示"
        # 终止以可见 reasoning 事件告知用户
        assert any(
            e.get("type") == "reasoning" and ("换策略" in str(e.get("data", "")) or "停止工具循环" in str(e.get("data", "")))
            for e in events
        )


# ══════════════════════════════════════════════════════════════
# C. token 计数 + 预算闸门
# ══════════════════════════════════════════════════════════════


class TestTokenCounting:
    def test_count_tokens_uses_tiktoken_for_chinese(self):
        """中文文本必须用分词器精确计数，而非 len*1.5 粗估"""
        client = LLMClient(LLMConfig())
        text = "这是一段用于测试的中文文本，长度适中。"
        counted = client.count_tokens(text)
        rough = int(len(text) * 1.5)
        assert counted > 0
        assert counted != rough, "仍是 len*1.5 粗估"

    def test_count_message_tokens_counts_tools(self):
        client = LLMClient(LLMConfig())
        messages = [
            {"role": "system", "content": "你是助手。"},
            {"role": "user", "content": "你好"},
        ]
        base = client.count_message_tokens(messages)
        with_tools = client.count_message_tokens(
            messages, tools=[{"type": "function", "function": {"name": "x", "description": "a" * 200}}]
        )
        assert base > 0
        assert with_tools > base

    @pytest.mark.asyncio
    async def test_budget_gate_blocks_before_api_call(self):
        """超预算必须在调用 API 之前抛 TokenLimitExceeded"""
        from neurova.llm_client import TokenLimitExceeded

        client = LLMClient(LLMConfig(max_input_tokens=10))
        client.async_client = MagicMock()
        create_mock = AsyncMock()
        client.async_client.chat.completions.create = create_mock

        with pytest.raises(TokenLimitExceeded):
            async for _ in client.chat_stream_async([{"role": "user", "content": "这段内容远超 10 token 预算"}]):
                pass

        create_mock.assert_not_awaited()


class TestProviderDefaultBudget:
    """max_input_tokens 未配置时，按模型上下文窗口推导默认输入预算"""

    def test_context_window_lookup(self):
        from neurova.llm.model_limits import get_model_context_window

        assert get_model_context_window("gpt-4o") == 128_000
        assert get_model_context_window("deepseek-chat") == 64_000
        # 前缀匹配：带日期后缀的快照名
        assert get_model_context_window("gpt-4o-2024-11-20") == 128_000
        # 未知模型返回 None（不设闸门，fail-open）
        assert get_model_context_window("totally-unknown-model") is None

    def test_effective_budget_explicit_wins(self):
        """显式配置优先于模型默认"""
        from neurova.llm.model_limits import get_model_context_window

        client = LLMClient(LLMConfig(model="gpt-4o", max_input_tokens=1000))
        assert client._get_effective_input_budget() == 1000
        assert get_model_context_window("gpt-4o") != 1000  # 前置：模型默认存在但被显式覆盖

    def test_effective_budget_derived_from_context_window(self):
        """未配置时：预算 = 上下文窗口 - 输出预留（不小于下限）"""
        client = LLMClient(LLMConfig(model="gpt-4", max_tokens=4096))
        budget = client._get_effective_input_budget()
        # gpt-4 窗口 8192，输出预留 4096 → 输入预算 4096
        assert budget == 8192 - 4096

    def test_effective_budget_unknown_model_no_gate(self):
        """未知模型不设闸门（避免误杀合法请求）"""
        client = LLMClient(LLMConfig(model="totally-unknown-model"))
        assert client._get_effective_input_budget() is None

    @pytest.mark.asyncio
    async def test_provider_default_gate_blocks_oversized_input(self):
        """未显式配置时，已知小窗口模型 + 超大输入同样被闸门拦截"""
        from neurova.llm_client import TokenLimitExceeded

        client = LLMClient(LLMConfig(model="gpt-4", max_tokens=4096))  # 输入预算 8192-4096=4096
        client.async_client = MagicMock()
        create_mock = AsyncMock()
        client.async_client.chat.completions.create = create_mock

        big_text = "长文本内容。" * 3000  # 远超 4096 token
        with pytest.raises(TokenLimitExceeded):
            async for _ in client.chat_stream_async([{"role": "user", "content": big_text}]):
                pass

        create_mock.assert_not_awaited()
