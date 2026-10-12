# -*- coding: utf-8 -*-
"""工具轮回放闭环：凡已执行并已让出 `tool_result` 的调用，必须落进消息历史。

实测缺陷形态（2026-10-08 长任务与工具调用闭环审计）：流式路径把「执行工具」
与「回放进历史」拆成了两处，而三条终止判定（轮次上限 / 门控 TERMINATE / 连续停滞）
都在回放**之前** `return`。于是长任务越接近上限越容易出现：工具真的跑了、
结果也发给客户端了，但模型侧永远看不到那次结果——下一轮的上下文里没有它的
下文。非流式同形：上限/门控在 `handle_tool_calls` **之前**判定，那一轮的调用
直接悬置，既没跑也没下文。

根因不是「某条分支忘了 append」，而是**终止判定被放在回放之前**：判定本该只决定
「要不要开下一轮」，现在它同时否决了「这一轮的结果是否进历史」。故本文件钉的是
那条不变量，而不是三条分支各自的形状。

判据面：
1. 流式轮次上限出口：已让出的每个 `tool_result` 都能在历史里找到配对的声明+结果；
2. 流式死循环门控 TERMINATE 出口：同上；
3. 流式连续停滞出口：同上；
4. 非流式上限/门控出口：被判终止那一轮的调用仍要有下文；
5. 并行批里一个执行体抛出非工具异常：siblings 的结果不得一起丢，失败者须以
   诚实的 tool 错误正文回环（不是整批蒸发后回退 legacy）。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMResponse

import neurova.security.agent_limits_settings as als


async def driveStream(loop, messages):
    """按生产契约驱动流式环：`predict_step` 是 `async def`，先 await 取生成器，
    再逐事件消费（与 `chat_pipeline._call_loop_stream` 同一形态）。"""
    gen = await loop.predict_step(messages, tools=None, stream=True)
    return [event async for event in gen]


class ChunkLLM:
    """按轮次依次产出预设 chunk 的假流式客户端，并记录每次收到的消息序列。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []
        # 入口会按 `agent.llm_client.config` 的采样键逐项透传；给一份空 config，
        # 免得红落在装配噪声（AttributeError）而不是行为断言上。
        self.config = SimpleNamespace()

    async def chat_stream(self, messages, **kwargs):
        self.calls.append(list(messages))
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        for chunk in self.rounds[idx]:
            yield chunk


class ScriptedChatLLM:
    """非流式假客户端：按轮次依次返回预设 LLMResponse，并记录消息序列。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []
        self.config = SimpleNamespace()

    async def chat(self, messages, **kwargs):
        self.calls.append(list(messages))
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        return self.rounds[idx]


def makeLoop(client):
    agent = MagicMock()
    agent._tool_messages_list = []
    agent.skill_registry = None
    agent.tool_router = SimpleNamespace(
        execute=lambda **kw: SimpleNamespace(success=True, result={"ok": 1}, error=None)
    )
    loop = OpenAILoop(agent)
    loop.llm_client = client
    agent.llm_client = client
    return loop


def toolCallRound(arguments, callIndex, content: str = ""):
    """一轮「正文 + 一次工具调用」的流式分片（参数各异以避开死循环签名重复）。"""
    return [
        LLMResponse(content=content) if content else LLMResponse(content=""),
        LLMResponse(
            tool_calls=[
                {
                    "index": 0,
                    "id": f"call_{callIndex}",
                    "type": "function",
                    "function": {"name": "probe_read", "arguments": arguments},
                }
            ],
            finish_reason="tool_calls",
        ),
    ]


def stopRound(content: str = "收口。"):
    return [LLMResponse(content=content, finish_reason="stop")]


def orphanToolCallIds(messages):
    """没有 assistant.tool_calls 声明的孤儿 tool 结果 id（与协议配对判据同源）。"""
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


def replayedCallIds(events, messages):
    """(已让出 tool_result 的调用 id 集合, 历史里已回放的 tool 结果 id 集合)。"""
    streamed = {
        event["data"].get("tool_call_id")
        for event in events
        if isinstance(event, dict) and event.get("type") == "tool_result"
        and isinstance(event.get("data"), dict)
    }
    replayed = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
    return streamed, replayed


def withLimits(limits: dict):
    """按生产单源取数：只改配置键，不手工把阈值传进循环内部。"""

    class _Limits:
        def __enter__(self):
            self.original = dict(als.DEFAULTS)
            als.DEFAULTS.update(limits)
            return self

        def __exit__(self, *exc):
            als.DEFAULTS.clear()
            als.DEFAULTS.update(self.original)
            return False

    return _Limits()


class TestStreamReplaysBeforeTerminating:
    def test_iterationLimitExit_keepsExecutedRoundInHistory(self):
        """轮次上限那一轮：工具已跑、结果已让出，就必须能在历史里读到下文。"""
        rounds = [
            toolCallRound('{"p": "a"}', 1),
            toolCallRound('{"p": "b"}', 2),
            toolCallRound('{"p": "c"}', 3),
            stopRound(),
        ]
        llm = ChunkLLM(rounds)
        loop = makeLoop(llm)
        messages = [{"role": "user", "content": "连续读三个文件"}]

        with withLimits({"max_loop_rounds": 2, "goal_round_budget": None}):
            events = asyncio.run(driveStream(loop, messages))

        assert any(
            isinstance(e, dict) and e.get("gate") == "iteration"
            and e.get("type") == "gate_terminate"
            for e in events
        ), "本用例要钉的是轮次上限出口，iteration 门控未开火则前提不成立"
        streamed, replayed = replayedCallIds(events, messages)
        assert streamed, "已让出过 tool_result 事件（否则本判据空转）"
        assert streamed - replayed == set(), (
            f"已执行并让出结果的调用没有进历史：{sorted(streamed - replayed)}"
            "——终止判定否决了回放，模型侧那一轮永无下文"
        )
        assert orphanToolCallIds(messages) == [], "历史里存在孤儿 tool 结果"

    def test_doomLoopGateTerminate_keepsExecutedRoundInHistory(self):
        """死循环门控 TERMINATE 那一轮：同样必须已回放，不能只发不收。

        三轮**参数相同、调用 id 各异**：签名按「工具名+参数」算，故死循环门照样
        开火；id 各异才让「哪一次结果没进历史」可被集合差看见——同 id 复用会把
        孤儿掩在已回放的集合里（本用例第一版就这么假绿过一轮）。
        """
        llm = ChunkLLM(
            [
                toolCallRound('{"p": "same"}', 1),
                toolCallRound('{"p": "same"}', 2),
                toolCallRound('{"p": "same"}', 3),
                stopRound(),
            ]
        )
        loop = makeLoop(llm)
        messages = [{"role": "user", "content": "反复读同一个文件"}]

        events = asyncio.run(driveStream(loop, messages))

        assert any(
            isinstance(e, dict) and e.get("gate") == "doom_loop"
            and e.get("type") == "gate_terminate"
            for e in events
        ), "本用例要钉的是死循环门 TERMINATE 出口，该门未开火则前提不成立"
        streamed, replayed = replayedCallIds(events, messages)
        assert streamed - replayed == set(), (
            f"门控终止那一轮的结果未入历史：{sorted(streamed - replayed)}"
        )

    def test_stagnationExit_keepsExecutedRoundInHistory(self):
        """连续停滞出口（与门控不同的另一条 return）：同样不得裸退。"""
        reply = "我先把文件读一遍再回答。"
        llm = ChunkLLM(
            [
                toolCallRound('{"p": "x1"}', 1, content=reply),
                toolCallRound('{"p": "x2"}', 2, content=reply),
                toolCallRound('{"p": "x3"}', 3, content=reply),
                stopRound(),
            ]
        )
        loop = makeLoop(llm)
        messages = [{"role": "user", "content": "读一下"}]

        events = asyncio.run(driveStream(loop, messages))

        stagnantExit = any(
            isinstance(e, dict)
            and e.get("type") == "reasoning"
            and "已停止工具循环" in str(e.get("data") or "")
            for e in events
        )
        assert stagnantExit, "本用例要钉的是停滞出口，停滞未开火则前提不成立"
        streamed, replayed = replayedCallIds(events, messages)
        assert streamed - replayed == set(), (
            f"停滞终止那一轮的结果未入历史：{sorted(streamed - replayed)}"
        )


class TestNonStreamReplaysBeforeTerminating:
    def test_terminatingRound_stillAnswersItsToolCall(self):
        """非流式：被判终止那一轮的调用不得悬置（既没跑也没下文）。"""
        rounds = [
            LLMResponse(
                content="先读。",
                tool_calls=[
                    {"id": "call_1", "type": "function",
                     "function": {"name": "probe_read", "arguments": '{"p": "a"}'}}
                ],
            ),
            LLMResponse(
                content="再读。",
                tool_calls=[
                    {"id": "call_2", "type": "function",
                     "function": {"name": "probe_read", "arguments": '{"p": "b"}'}}
                ],
            ),
            LLMResponse(content="不该走到这里。"),
        ]
        llm = ScriptedChatLLM(rounds)
        loop = makeLoop(llm)
        messages = [{"role": "user", "content": "连续读两个文件"}]

        with withLimits({"max_loop_rounds": 2, "goal_round_budget": None}):
            asyncio.run(loop.predict_step(messages, tools=None, stream=False))

        results = [m.get("tool_call_id") for m in messages if m.get("role") == "tool"]
        assert results.count("call_2") == 1, (
            f"上限那一轮的工具调用没有下文，历史里的 tool 结果={results}"
            "——模型声明了调用却永远收不到回应"
        )
        assert orphanToolCallIds(messages) == [], (
            f"存在孤儿 tool 结果：{orphanToolCallIds(messages)}"
        )


class TestParallelBatchDoesNotLoseSiblings:
    def test_oneWorkerRaisingKeepsOtherResultsAndAnswersTheFailure(self, monkeypatch):
        """并行批中一个执行体抛出非工具异常：整批不得一起蒸发。

        失败者须以诚实的 tool 错误正文回环（协议上仍是配对的一次结果），
        成功者的结果必须照常回给模型——不是靠上游回退 legacy 兜住。
        """
        from neurova.agent import tool_coordinator as tc
        from neurova.core import tool_capability as cap_mod
        from neurova.core import tool_offload

        loop = makeLoop(ScriptedChatLLM([LLMResponse(content="unused")]))
        parallelCap = cap_mod.ToolCapability(
            readOnly=True,
            concurrentSafe=True,
            writeScopes=frozenset({cap_mod.WriteScope.NONE}),
        )
        calls = [
            {"id": "call_a", "type": "function",
             "function": {"name": "probe_ok", "arguments": "{}"}},
            {"id": "call_b", "type": "function",
             "function": {"name": "probe_boom", "arguments": "{}"}},
        ]
        realResolve = tc.resolveBatchCapabilities
        realOffload = tool_offload.apply_offload_policy

        def fakeResolve(tool_calls):
            resolved = realResolve(tool_calls)
            for key in list(resolved):
                resolved[key] = parallelCap
            return resolved

        def fakeOffload(**kwargs):
            if kwargs.get("tool_name") == "probe_boom":
                raise RuntimeError("溢出分层炸了")
            return realOffload(**kwargs)

        monkeypatch.setattr(tc, "resolveBatchCapabilities", fakeResolve)
        monkeypatch.setattr(tool_offload, "apply_offload_policy", fakeOffload)

        escaped = None
        newMessages: list = []
        try:
            newMessages = asyncio.run(loop.handle_tool_calls(calls, []))
        except Exception as exc:  # noqa: BLE001 - 要抓的就是「异常整批上抛」这个事实
            escaped = exc

        assert escaped is None, (
            f"一个执行体的异常把整批调用掀掉并上抛（{escaped!r}）"
            "——同批其它调用一并失去下文，故障被挪给上游回退 legacy 兜"
        )
        ids = [m.get("tool_call_id") for m in newMessages]
        assert ids.count("call_a") == 1, (
            f"同批另一个工具的结果被连带丢弃：{ids}"
            "——一个执行体抛异常即整批蒸发，故障被挪给上游兜底"
        )
        assert ids.count("call_b") == 1, (
            f"抛异常的那次调用没有回环（协议上缺一条 tool 结果）：{ids}"
        )
        boom = next(m for m in newMessages if m.get("tool_call_id") == "call_b")
        assert "溢出分层炸了" in json.loads(boom["content"]).get("error", ""), (
            f"失败正文未如实回传给模型：{boom.get('content')!r}"
        )
        records = [
            rec
            for call in loop.agent.append_tool_messages.call_args_list
            for rec in (call.args[0] if call.args else [])
        ]
        boomRecord = next(
            (
                r for r in records
                if r.get("tool_call_id") == "call_b" and r.get("type") == "tool_result"
            ),
            None,
        )
        assert boomRecord is not None and boomRecord.get("success") is False, (
            f"失败的那条没进取证记录或成败被记反：{boomRecord}"
            "——前端与落盘会把这次异常读成没发生过"
        )
