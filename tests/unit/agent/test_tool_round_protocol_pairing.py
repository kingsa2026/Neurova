# -*- coding: utf-8 -*-
"""工具轮回放协议配对红灯：续写请求必须带 assistant(tool_calls)。

实测故障（2026-09-26 kai/sensetime）：模型返回 tool_calls 后，循环把
`handle_tool_calls` 产出的 role="tool" 消息直接 extend 进消息序列再发续写，
中间没有落一条声明这些调用的 assistant 消息。OpenAI 协议要求 tool 结果必须
紧跟在声明它的 assistant.tool_calls 之后；商汤网关严格校验，续写请求被整体
拒为 `400 inference request is invalid (400001)`，而 amd/modelscope 网关容忍
同一畸形序列——所以断链只在换服务商后暴露。

窗口侧已有 context/recovery.py::repair_tool_turns 收口这套配对，但它只覆盖
首轮上下文组装，循环内续写绕过了它。本文件钉住续写侧的同一契约。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMResponse


async def drainEvents(gen):
    return [event async for event in gen]


class ChunkLLM:
    """按轮次依次产出预设 chunk 的假流式客户端，并记录每次收到的消息序列。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []

    async def chat_stream(self, messages, **kwargs):
        self.calls.append(list(messages))
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        for chunk in self.rounds[idx]:
            yield chunk


def makeLoop():
    agent = MagicMock()
    agent._tool_messages_list = []
    agent.skill_registry = None
    agent.tool_router = SimpleNamespace(
        execute=lambda **kw: SimpleNamespace(success=True, result={"ok": 1}, error=None)
    )
    return OpenAILoop(agent)


def _toolCallChunks(calls):
    """把 (id, name) 列表编成流式 tool_calls 首片序列。"""
    return [
        LLMResponse(
            tool_calls=[
                {
                    "index": i,
                    "id": callId,
                    "type": "function",
                    "function": {"name": name, "arguments": "{}"},
                }
                for i, (callId, name) in enumerate(calls)
            ],
            finish_reason="tool_calls",
        )
    ]


def orphanToolCallIds(messages):
    """列出没有 assistant.tool_calls 声明的孤儿 tool 结果 id。

    判据：每条 role="tool" 消息的 tool_call_id 必须属于其紧邻前一条
    assistant.tool_calls 声明的 id 集；遇到其它角色消息该声明段即失效。
    """
    declared: set = set()
    orphans: list = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            declared = {c.get("id") for c in msg["tool_calls"] if isinstance(c, dict)}
        elif msg.get("role") == "tool":
            callId = msg.get("tool_call_id")
            if callId not in declared:
                orphans.append(callId)
        else:
            declared = set()
    return orphans


class TestStreamToolRoundPairing:
    def test_stream_continuation_declares_assistant_tool_calls(self):
        loop = makeLoop()
        llm = ChunkLLM(
            [
                _toolCallChunks([("call_1", "probe_read")]),
                [LLMResponse(content="续写完成。", finish_reason="stop")],
            ]
        )
        loop.llm_client = llm
        loop.agent.llm_client = llm

        asyncio.run(
            drainEvents(
                loop._predict_stream(
                    {"messages": [{"role": "user", "content": "读一下"}], "stream": True}
                )
            )
        )

        assert len(llm.calls) == 2, "工具执行后应发起续写调用"
        continuation = llm.calls[1]
        assert orphanToolCallIds(continuation) == [], (
            "续写请求存在孤儿 tool 结果（缺 assistant.tool_calls 声明）："
            f"{orphanToolCallIds(continuation)}，roles={[m.get('role') for m in continuation]}"
        )


class ScriptedChatLLM:
    """非流式假客户端：按轮次依次返回预设 LLMResponse，并记录消息序列。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append(list(messages))
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        return self.rounds[idx]


class TestNonStreamToolRoundPairing:
    def test_non_stream_continuation_declares_assistant_tool_calls(self):
        loop = makeLoop()
        llm = ScriptedChatLLM(
            [
                LLMResponse(content="", tool_calls=[
                    {"id": "call_9", "type": "function",
                     "function": {"name": "probe_read", "arguments": "{}"}}
                ]),
                LLMResponse(content="续写完成。"),
            ]
        )
        loop.llm_client = llm

        asyncio.run(
            loop._predict_normal(
                {"messages": [{"role": "user", "content": "读一下"}], "stream": False}
            )
        )

        assert len(llm.calls) == 2, "工具执行后应发起续写调用"
        continuation = llm.calls[1]
        assert orphanToolCallIds(continuation) == [], (
            "非流式续写请求存在孤儿 tool 结果："
            f"{orphanToolCallIds(continuation)}，roles={[m.get('role') for m in continuation]}"
        )


def _declaredAndResultIds(messages):
    """从消息序列里取出 assistant 声明的 id 序列与 tool 结果的 id 序列。"""
    declared = [
        c.get("id")
        for m in messages
        if m.get("role") == "assistant" and m.get("tool_calls")
        for c in m["tool_calls"]
    ]
    results = [m.get("tool_call_id") for m in messages if m.get("role") == "tool"]
    return declared, results


class TestCallIdSingleSource:
    def test_missing_provider_call_id_is_synthesized_not_none(self):
        """provider 首片不带 id（兼容网关实测）→ 循环必须合成有效 id，且声明侧与
        结果侧同源。id=None 两侧一致也只是"同样非法"，协议仍判孤儿。"""
        loop = makeLoop()
        llm = ChunkLLM(
            [
                [
                    LLMResponse(
                        tool_calls=[
                            {
                                "index": 0,
                                "id": None,
                                "type": "function",
                                "function": {"name": "probe_read", "arguments": "{}"},
                            }
                        ],
                        finish_reason="tool_calls",
                    )
                ],
                [LLMResponse(content="续写完成。", finish_reason="stop")],
            ]
        )
        loop.llm_client = llm
        loop.agent.llm_client = llm

        asyncio.run(
            drainEvents(
                loop._predict_stream(
                    {"messages": [{"role": "user", "content": "读一下"}], "stream": True}
                )
            )
        )

        declared, results = _declaredAndResultIds(llm.calls[1])
        assert declared == results, "assistant 声明的 id 与 tool 结果的 id 必须逐一对应"
        assert all(declared), f"调用 id 不得为 None/空：{declared}"


class TestReasoningReplaySharesOneDeclaration:
    """防回归守卫：回放开关开启时，思考链必须挂在同一条 assistant 声明消息上。

    续写序列里只允许存在一份 tool_calls 声明——平行造第二条 assistant 会让
    tool 结果只与其中一条配对，另一条成了空声明。
    """

    def test_replay_on_carries_reasoning_on_the_declaring_message(self, monkeypatch):
        from neurova.agent.loops import reasoning_replay

        monkeypatch.setattr(reasoning_replay, "should_replay_reasoning", lambda _m: True)

        loop = makeLoop()
        loop.agent.config.llm_model = "any-reasoning-model"
        llm = ChunkLLM(
            [
                [
                    LLMResponse(content="我先读一下。", reasoning_content="思考过程。"),
                    *_toolCallChunks([("call_7", "probe_read")]),
                ],
                [LLMResponse(content="续写完成。", finish_reason="stop")],
            ]
        )
        loop.llm_client = llm
        loop.agent.llm_client = llm

        asyncio.run(
            drainEvents(
                loop._predict_stream(
                    {"messages": [{"role": "user", "content": "读一下"}], "stream": True}
                )
            )
        )

        declaring = [
            m for m in llm.calls[1] if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        assert len(declaring) == 1, f"续写序列出现多份 tool_calls 声明：{len(declaring)}"
        assert declaring[0]["reasoning_content"] == "思考过程。"
        assert declaring[0]["content"] == "我先读一下。"
        assert orphanToolCallIds(llm.calls[1]) == []


def unpairedToolResultBlocks(anthropicMessages):
    """在 Anthropic 载荷里找出没有前置 tool_use 声明的 tool_result 块。

    Anthropic 协议要求 tool_result 必须紧跟在含对应 tool_use 的 assistant 消息
    之后，判据与 OpenAI 侧的 assistant.tool_calls 完全同构。
    """
    declared: set = set()
    orphans: list = []
    for msg in anthropicMessages:
        blocks = msg.get("content")
        if not isinstance(blocks, list):
            declared = set()
            continue
        if msg.get("role") == "assistant":
            declared = {b.get("id") for b in blocks if b.get("type") == "tool_use"}
        elif msg.get("role") == "user":
            for block in blocks:
                if block.get("type") == "tool_result" and block.get("tool_use_id") not in declared:
                    orphans.append(block.get("tool_use_id"))
            declared = set()
    return orphans


class TestAnthropicToolRoundPairing:
    def test_anthropic_continuation_declares_tool_use_before_tool_result(self):
        from neurova.agent.loops.anthropic_loop import AnthropicLoop

        agent = MagicMock()
        agent._tool_messages_list = []
        agent.skill_registry = None
        loop = AnthropicLoop(agent)

        class ChatLLM:
            def __init__(self, rounds):
                self.rounds = rounds
                self.calls = []

            async def chat(self, **kwargs):
                self.calls.append(kwargs.get("messages") or [])
                idx = min(len(self.calls) - 1, len(self.rounds) - 1)
                return self.rounds[idx]

        llm = ChatLLM(
            [
                LLMResponse(content="", tool_calls=[
                    {"id": "call_a", "type": "function",
                     "function": {"name": "probe_read", "arguments": "{}"}}
                ]),
                LLMResponse(content="完成。"),
            ]
        )
        loop.llm_client = llm

        asyncio.run(loop.predict_step([{"role": "user", "content": "读一下"}]))

        assert len(llm.calls) == 2, "工具执行后应发起续写调用"
        assert unpairedToolResultBlocks(llm.calls[1]) == [], (
            f"Anthropic 续写出现无 tool_use 前置的 tool_result："
            f"{unpairedToolResultBlocks(llm.calls[1])}"
        )
