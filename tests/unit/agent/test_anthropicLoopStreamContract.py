# -*- coding: utf-8 -*-
"""AnthropicLoop 的流式契约（2026-10-08 长任务闭环审计 A 批）。

实测形态：`chat_pipeline._call_loop_stream` 按 `gen = await loop.predict_step(..., stream=True)`
再 `async for event in gen` 消费（`chat_pipeline.py:2412/2428`）——这是**两条环共同的流式契约**。
`OpenAILoop.predict_step` 在 `stream=True` 时返回 `_predict_stream(...)` 异步生成器，而
`AnthropicLoop.predict_step`（anthropic_loop.py:35-37）把 `**kwargs` 里的 `stream` 整个吞掉，
只会返回 `LLMResponse`。于是对 claude 系模型：

    async for event in <LLMResponse>  →  TypeError
    →  `chat_pipeline.py:2377-2389` 判它不是供应商错误 → 落 `_call_legacy`
    →  `_call_legacy_stream` 调 `chat_stream(ctx.context)`，**tools 参数根本不传**

后果不是一处小退化，而是整条原生工具环对 claude **从未生效**：原生 function-calling、
门控（死循环/轮次/token 预算）、主出口假完成判定、邮箱与插话排空、工具事件 SSE 全部不参与；
只剩 `_call_legacy` 之后那句文本正则工具通道（`chat_pipeline.py:2303`）。单元测试看不见：
既有 claude 侧判据都是直接驱动 `handle_tool_calls` / `_convert_*`（`test_tool_bugs_v3.py`、
`test_anthropic_loop_batch_handoff.py`），从没经由流式入口走过一次。

根因是**契约只写在另一条环的实现里**：`BaseAgentLoop.predict_step` 的签名是 `-> Any`
（base.py:322），"流式=异步生成器、事件形状有哪些"没有任何跨实现点的约束，也没有装配
Anthropic 侧门控的公共入口（`gateRunnerForExit` 在基类恒回 None，base.py:317-319）。
故本批同时把门控装配上移到基类（单一实现点，两条环同取），不在 Anthropic 侧另拼一份门清单。

判据（每条都要求改前实测不成立、改后成立）：
1. `stream=True` 返回的是异步生成器，且事件流里有 content 分片与恰好一个 done；
2. 流式工具轮：调用被执行、`tool_result` 事件让出、且 assistant 声明与 tool 结果成对进历史；
3. 轮次上限那一轮不得悬置调用（与 B 批同一条规则：判定后置，执行与回放先行）；
4. Anthropic 环的门控装配与 OpenAI 环同一份清单（不是"另一条环没门控"）；
5. 经真消费点 `ChatPipeline._call_agent_loop(stream=True)` 走 claude 模型：不回退 legacy、
   工具事件按 emit_tool_events 转发到 emitter。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.agent.loops.anthropic_loop import AnthropicLoop
from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMResponse

MODEL = "claude-3-5-sonnet"


class StreamClient:
    """按轮次产出 chunk 的假流式客户端；同时记录收到的消息序列与 kwargs。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []

    async def chat_stream(self, messages=None, **kwargs):
        self.calls.append({"messages": list(messages or []), "kwargs": kwargs})
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        for chunk in self.rounds[idx]:
            yield chunk

    async def chat(self, messages=None, **kwargs):
        self.calls.append({"messages": list(messages or []), "kwargs": kwargs})
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        last = self.rounds[idx][-1]
        return last


def makeLoop(client, *, streamRounds=None):
    agent = MagicMock()
    agent._tool_messages_list = []
    agent.skill_registry = None
    agent.config.name = "anthropic-probe"
    agent.config.agent_id = "anthropic-probe-id"
    agent.config.llm_model = MODEL
    loop = AnthropicLoop(agent)
    loop.llm_client = client
    agent.llm_client = client
    return loop


def toolCallChunks(callId, name="probe_read", arguments='{"p": "a"}'):
    return [
        LLMResponse(content="先看一眼。"),
        LLMResponse(
            tool_calls=[{
                "index": 0, "id": callId, "type": "function",
                "function": {"name": name, "arguments": arguments},
            }],
            finish_reason="tool_calls",
        ),
    ]


def stopChunks(text="收口。"):
    return [LLMResponse(content=text, finish_reason="stop")]


def declaredCallIds(messages):
    return {
        c.get("id")
        for m in messages
        if m.get("role") == "assistant" and m.get("tool_calls")
        for c in m["tool_calls"]
    }


def resultCallIds(messages):
    return [m.get("tool_call_id") for m in messages if m.get("role") == "tool"]


class TestStreamContract:
    def test_streamTrueReturnsAsyncGenerator(self):
        """流式入口必须返回异步生成器——返回 LLMResponse 会被消费方判成 TypeError。"""
        client = StreamClient([stopChunks("你好。")])
        loop = makeLoop(client)
        messages = [{"role": "user", "content": "你好"}]

        gen = asyncio.run(loop.predict_step(messages, tools=None, stream=True))

        assert inspect.isasyncgen(gen), (
            f"predict_step(stream=True) 返回了 {type(gen).__name__}，而消费方 "
            "chat_pipeline.py:2428 要 `async for` —— claude 因此每次都在流式下抛 "
            "TypeError 并回退 legacy，原生工具环从未参与"
        )

    def test_streamEventsCarryContentAndExactlyOneDone(self):
        client = StreamClient([
            [LLMResponse(content="你"), LLMResponse(content="好", finish_reason="stop")],
        ])
        loop = makeLoop(client)
        messages = [{"role": "user", "content": "你好"}]

        async def go():
            gen = await loop.predict_step(messages, tools=None, stream=True)
            return [e async for e in gen]

        events = asyncio.run(go())
        contents = [e.get("data") for e in events if isinstance(e, dict) and e.get("type") == "content"]
        dones = [e for e in events if isinstance(e, dict) and e.get("type") == "done"]

        assert contents == ["你", "好"], f"token 分片未逐块让出（流式 UX 退化）：{events}"
        assert len(dones) == 1, f"done 事件必须恰好一个：{len(dones)} 个 —— 多个会让消费方重复收尾"
        assert dones[0].get("reply") == "你好", dones[0]

    def test_streamToolRoundExecutesReplaysAndContinues(self):
        client = StreamClient([
            toolCallChunks("call_1"),
            stopChunks("读完了。"),
        ])
        loop = makeLoop(client)
        messages = [{"role": "user", "content": "读一下"}]

        async def go():
            gen = await loop.predict_step(messages, tools=None, stream=True)
            return [e async for e in gen]

        events = asyncio.run(go())

        toolResults = [
            e["data"].get("tool_call_id")
            for e in events
            if isinstance(e, dict) and e.get("type") == "tool_result"
        ]
        assert toolResults == ["call_1"], f"工具结果事件没让出：{events}"
        assert len(client.calls) == 2, "工具执行后应发起续写（改前根本不走这条环）"
        assert resultCallIds(messages) == ["call_1"], (
            f"tool 结果未进历史：{resultCallIds(messages)}"
        )
        assert declaredCallIds(messages) >= {"call_1"}, (
            "历史里缺声明该调用的 assistant.tool_calls —— Anthropic 协议会把续写判非法"
        )


class TestRoundLimitStillAnswers:
    def test_terminatingRound_getsItsToolResult(self):
        """与 B 批同一条规则：轮次上限只裁定要不要开下一轮，不否决这一轮的下文。"""
        import neurova.security.agent_limits_settings as als

        client = StreamClient([
            toolCallChunks("call_a", arguments='{"p": "1"}'),
            toolCallChunks("call_b", arguments='{"p": "2"}'),
            toolCallChunks("call_c", arguments='{"p": "3"}'),
            stopChunks(),
        ])
        loop = makeLoop(client)
        messages = [{"role": "user", "content": "连续读三个"}]

        original = dict(als.DEFAULTS)
        als.DEFAULTS.update({"max_loop_rounds": 2, "goal_round_budget": None})
        try:
            async def go():
                gen = await loop.predict_step(messages, tools=None, stream=True)
                return [e async for e in gen]

            events = asyncio.run(go())
        finally:
            als.DEFAULTS.clear()
            als.DEFAULTS.update(original)

        streamed = [
            e["data"].get("tool_call_id")
            for e in events
            if isinstance(e, dict) and e.get("type") == "tool_result"
        ]
        assert streamed, "本用例要钉的是超限出口，未让出过 tool_result 则前提不成立"
        missing = set(streamed) - set(resultCallIds(messages))
        assert missing == set(), f"已执行并让出结果的调用没进历史：{sorted(missing)}"


class TestGateAssemblyIsShared:
    def test_anthropicLoopCarriesTheSameGateSet(self):
        """两条环的门控清单必须出自同一处装配——不是 OpenAI 有、Anthropic 没有。"""
        openaiAgent = MagicMock()
        openaiAgent._tool_messages_list = []
        openaiAgent.config.name = "openai-probe"
        openaiAgent.config.agent_id = "openai-probe-id"
        openaiLoop = OpenAILoop(openaiAgent)

        anthropicLoop = makeLoop(StreamClient([stopChunks()]))

        names = lambda runner: {getattr(g, "name", "") for g in runner.gates}
        openaiRunner = openaiLoop.buildGateRunner()
        anthropicRunner = anthropicLoop.gateRunnerForExit()

        assert anthropicRunner is not None, (
            "Anthropic 环没有门控执行器（基类 gateRunnerForExit 恒回 None）——"
            "死循环/轮次/token 预算三条闸对它一律不生效"
        )
        assert names(anthropicRunner) == names(openaiRunner), (
            f"两条环的门清单分叉：OpenAI={names(openaiRunner)} Anthropic={names(anthropicRunner)}"
            "——同一契约的第二份定义"
        )


class TestProductionConsumerDoesNotFallBack:
    @pytest.mark.asyncio
    async def test_callAgentLoop_streamUsesAnthropicLoop(self, caplog):
        """经真消费点走一次 claude 流式：不得回退 legacy，工具事件要转发给 emitter。"""
        from neurova.agent.chat_pipeline import ChatContext, ChatPipeline

        client = StreamClient([
            toolCallChunks("call_x"),
            stopChunks("读完了。"),
        ])
        agent = MagicMock()
        agent._tool_messages_list = []
        agent.config.name = "anthropic-probe"
        agent.config.agent_id = "anthropic-probe-id"
        agent.config.llm_config.model = MODEL
        agent.llm_client = client
        loop = AnthropicLoop(agent)
        loop.llm_client = client
        agent.loop = loop

        pipeline = ChatPipeline(agent)

        seen = []
        ctx = ChatContext(
            user_input="读一下",
            stream=True,
            context=[{"role": "user", "content": "读一下"}],
            event_emitter=lambda etype, data: seen.append((etype, data)),
            metadata={"emit_tool_events": True},
        )

        with caplog.at_level(logging.WARNING):
            reply = await pipeline._call_agent_loop(ctx, None)

        assert "falling back to legacy" not in caplog.text, (
            f"仍回退了 legacy（claude 原生环不可达）：{caplog.text}"
        )
        assert "读完了。" in (reply or ""), f"回复文本未从流式事件里拼出：{reply!r}"
        assert any(etype == "tool_result" for etype, _ in seen), (
            f"工具事件没转发到 SSE 出口：{[e for e, _ in seen]}"
        )


class TestAnthropicStreamUsageCountedOnce:
    """同一根因的 Anthropic 命中点：usage 是本次调用的累计值，不是逐 chunk 增量。"""

    def test_duplicate_usage_chunks_are_not_summed(self):
        usage = SimpleNamespace(prompt_tokens=8, completion_tokens=2, total_tokens=10)
        client = StreamClient(
            [
                [
                    LLMResponse(content="好", usage=usage),
                    LLMResponse(content="", usage=usage, finish_reason="stop"),
                ]
            ]
        )
        loop = makeLoop(client)
        loop.agent._round_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        messages = [{"role": "user", "content": "你好"}]

        async def go():
            gen = await loop.predict_step(messages, tools=None, stream=True)
            return [e async for e in gen]

        asyncio.run(go())
        assert loop.agent._round_usage["total_tokens"] == 10, (
            f"Anthropic 环把同一调用的两个 usage chunk 累加成 "
            f"{loop.agent._round_usage['total_tokens']}"
        )
