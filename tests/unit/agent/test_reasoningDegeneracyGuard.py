# -*- coding: utf-8 -*-
"""思考流退化守卫·环侧行为（2026-10-22 default 会话「思考过程 lock 连发」事故）。

事故读数（`data/default/sessions/_timeline/kai-dialog-20260509.jsonl`）：同一次调用的
reasoning 通道连发 88 个分片、共 **16384 字符**，内容只有一个词 `lock` 的重复；正文 0 字、
`finish_reason=length`。整整 3 分 58 秒垃圾原样流进前端思考面板，一条判据都没咬。

现有四道门都拦不到它：`IterationGate`/`TokenBudgetGate`/`GoalGate` 按轮与预算判定，
`DoomLoopGate` 只看**工具调用签名**重复（`gates.py:170-219`）——退化发生在**一次调用内部**
的 token 流上，门控要到轮末才求值，那时预算早被吃光了。

本档只钉**既有两条环 + 存储面**的可观测行为，不 import 任何待建模块（红要红在行为断言上，
不是 collection error）。阈值刻意取「任何合理策略下都成立」的形状：作废样本连发 4000 次
（事故同量级），正常样本等长但逐句不同。
"是否真的不再读这一次调用"用**哨兵片**判：它只在被读到流末尾时出现。

连发如何识别、前缀如何剥，由单源判据自己那份档钉：
`tests/unit/agent/test_reasoningDegeneracyDetector.py`。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from neurova.agent.loops.anthropic_loop import AnthropicLoop
from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMResponse

ANTHROPIC_MODEL = "claude-3-5-sonnet"

# 作废样本：一个 4 字符单元连发 4000 次 = 16000 字符（事故实测 16384 字符的同形量级）
GARBAGE_UNIT = "lock"
GARBAGE_REPEATS = 4000
GARBAGE_CHUNK = 50  # 每片 50 个单元 ≈ 200 字符，与事故网关的分片形状一致
# 只有真读到流末尾才会出现的片：判"是否停止了读取"，不判实现细节
TAIL_SENTINEL = "⟦tail-reached⟧"
# 正常样本：与作废样本等量但逐句不同——任何合理的守卫都不该拦下（误杀判据）
LEGIT_TARGET_CHARS = 16000


def garbageChunks() -> list:
    return [
        LLMResponse(reasoning_content=GARBAGE_UNIT * GARBAGE_CHUNK)
        for _ in range(GARBAGE_REPEATS // GARBAGE_CHUNK)
    ] + [LLMResponse(reasoning_content=TAIL_SENTINEL)]


def legitChunks() -> list:
    parts = []
    size = 0
    step = 0
    while size < LEGIT_TARGET_CHARS:
        sentence = f"第{step}步：先核对上一轮的输出，再决定要不要换一种检索方式，编号{step}各不相同。"
        parts.append(sentence)
        size += len(sentence)
        step += 1
    joined = "".join(parts) + TAIL_SENTINEL
    return [LLMResponse(reasoning_content=joined[i : i + 200]) for i in range(0, len(joined), 200)]


class FakeStreamClient:
    """假流式客户端：按轮产出预设 chunk，并记录是否读到了流末尾与每轮 kwargs。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []
        self.tailReached = False

    async def chat_stream(self, messages, **kwargs):
        self.calls.append({"messages": list(messages), "kwargs": dict(kwargs)})
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        chunks = self.rounds[idx]
        for position, chunk in enumerate(chunks):
            if position == len(chunks) - 1:
                self.tailReached = True
            yield chunk


def makeOpenAiLoop(client):
    agent = MagicMock()
    agent._tool_messages_list = []
    agent._round_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    agent.skill_registry = None
    agent.tool_router = SimpleNamespace(
        execute=lambda **kw: SimpleNamespace(success=True, result={"ok": 1}, error=None)
    )
    loop = OpenAILoop(agent)
    loop.llm_client = client
    loop.agent.llm_client = client
    return loop


def makeAnthropicLoop(client):
    agent = MagicMock()
    agent._tool_messages_list = []
    agent._round_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    agent.skill_registry = None
    agent.config.name = "degeneracy-probe"
    agent.config.agent_id = "degeneracy-probe-id"
    agent.config.llm_model = ANTHROPIC_MODEL
    loop = AnthropicLoop(agent)
    loop.llm_client = client
    loop.agent.llm_client = client
    return loop


def collect(gen_factory):
    """`gen_factory()` 可为协程（Anthropic 的 `predict_step` 要先 await 再 `async for`）。"""

    async def go():
        gen = gen_factory()
        if not hasattr(gen, "__aiter__"):
            gen = await gen
        return [e async for e in gen]

    return asyncio.run(go())


def storedReasoning(loop):
    return [
        str(call.args[0])
        for call in loop.agent.set_current_reasoning.call_args_list
        if call.args
    ]


def reasoningText(events):
    return "".join(e["data"] for e in events if e.get("type") == "reasoning")


def openAiEvents(rounds, *, withBudgetKnobs=True):
    client = FakeStreamClient(rounds)
    loop = makeOpenAiLoop(client)
    params = {"messages": [{"role": "user", "content": "继续任务"}], "stream": True}
    if withBudgetKnobs:
        # 恢复路径只在"确有旋钮可动"时重试（`_resumeAfterLengthEmpty` 既有语义）；
        # 要单独看截断本身是否可见，就得把旋钮摘掉，让恢复整条不进场。
        params.update({"max_tokens": 4096, "thinking_enabled": True})
    return client, loop, collect(lambda: loop._predict_stream(params))


class TestOpenAiStreamCutsCollapse:
    def testGarbageStopsBeingForwarded(self):
        _client, _loop, events = openAiEvents([garbageChunks()])
        forwarded = reasoningText(events)
        assert GARBAGE_UNIT * GARBAGE_REPEATS not in forwarded, (
            "整条退化流原样转发就是事故本体（4 分钟垃圾糊在思考面板上）"
        )
        assert len(forwarded) < GARBAGE_REPEATS * len(GARBAGE_UNIT), len(forwarded)

    def testReadingStopsAtTheCut(self):
        """判定退化即终止这一次调用：继续读=继续按秒烧时间与配额。"""
        client, _loop, events = openAiEvents([garbageChunks()])
        assert not client.tailReached, "读到流末尾了 = 没截断，哨兵不该被取到"
        assert TAIL_SENTINEL not in reasoningText(events)

    def testTruncationIsNotSilent(self):
        """截断要在既有可见通道上留一条"环自己说的"提示（摘掉预算旋钮，恢复不进场）。"""
        _client, _loop, events = openAiEvents([garbageChunks()], withBudgetKnobs=False)
        fed = {c.reasoning_content for c in garbageChunks()}
        own = [e["data"] for e in events if e.get("type") == "reasoning" and e["data"] not in fed]
        assert len(own) == 1, f"截断必须点名一次且不静默：{own}"
        assert GARBAGE_UNIT * 3 not in own[0], own[0]

    def testCollapsedRoundHandsOffToExistingBudgetRecovery(self):
        """交出 length 空正文 ⇒ 复用既有的"思考吃满预算"单次恢复，不新造第二套恢复。"""
        client, _loop, events = openAiEvents(
            [
                garbageChunks(),
                [LLMResponse(content="已改用单条命令。"), LLMResponse(content="", finish_reason="stop")],
            ]
        )
        assert len(client.calls) == 2, f"退化截断后应发起那一次恢复重试：{len(client.calls)} 次调用"
        assert client.calls[1]["kwargs"].get("thinking_enabled") is False, (
            "恢复轮必须把思考关停，否则同一堵墙再撞一次"
        )
        done = [e for e in events if e.get("type") == "done"]
        assert len(done) == 1 and (done[0].get("reply") or "").strip(), done

    def testGarbageNeverReachesStoredReasoning(self):
        _client, loop, _events = openAiEvents([garbageChunks()])
        assert all(GARBAGE_UNIT * 3 not in s for s in storedReasoning(loop)), (
            f"作废思考不该进展示/记忆落点：{[s[:60] for s in storedReasoning(loop)]}"
        )

    def testLegitimateLongThinkingIsNotCut(self):
        """误杀判据：等长但不周期的思考要整条转完、不额外开口、不触发恢复。"""
        client, _loop, events = openAiEvents(
            [legitChunks() + [LLMResponse(content="好。"), LLMResponse(content="", finish_reason="stop")]]
        )
        assert reasoningText(events) == "".join(c.reasoning_content for c in legitChunks())
        assert client.tailReached and TAIL_SENTINEL in reasoningText(events), "正常长思考被拦了"
        assert len(client.calls) == 1, f"不该触发恢复：{len(client.calls)} 次调用"
        done = [e for e in events if e.get("type") == "done"]
        assert len(done) == 1 and done[0].get("reply") == "好。", done


class TestAnthropicStreamCutsCollapse:
    def _run(self, rounds):
        client = FakeStreamClient(rounds)
        loop = makeAnthropicLoop(client)
        return client, loop, collect(
            lambda: loop.predict_step([{"role": "user", "content": "想一下"}], tools=None, stream=True)
        )

    def testCollapseCutAndReportedWithLengthFinishReason(self):
        client, loop, events = self._run([garbageChunks()])
        assert GARBAGE_UNIT * GARBAGE_REPEATS not in reasoningText(events), "整条作废流转发"
        assert not client.tailReached, "没截断，哨兵不该被取到"
        fed = {c.reasoning_content for c in garbageChunks()}
        own = [e["data"] for e in events if e.get("type") == "reasoning" and e["data"] not in fed]
        assert own, "截断不可见"
        done = [e for e in events if e.get("type") == "done"]
        assert len(done) == 1, done
        assert str(done[0].get("finish_reason") or "").lower() in ("length", "max_tokens"), (
            f"退化截断要按输出预算耗尽交出成因，下游判据才咬得住：{done[0]}"
        )
        assert all(GARBAGE_UNIT * 3 not in s for s in storedReasoning(loop)), storedReasoning(loop)

    def testLegitimateLongThinkingIsNotCut(self):
        _client, _loop, events = self._run(
            [legitChunks() + [LLMResponse(content="好。"), LLMResponse(content="", finish_reason="stop")]]
        )
        assert reasoningText(events) == "".join(c.reasoning_content for c in legitChunks())
        assert _client.tailReached, "正常长思考被拦了"


class TestNonStreamStorageSanitized:
    def testDegenerateTailStrippedBeforeStorage(self):
        legit = "先确认任务状态，再决定从哪一步继续。"
        response = LLMResponse(
            content="收到。",
            reasoning_content=legit + GARBAGE_UNIT * GARBAGE_REPEATS,
            finish_reason="stop",
        )

        class ChatClient:
            config = SimpleNamespace(max_tokens=4096)

            async def chat(self, messages, **kwargs):
                return response

        agent = MagicMock()
        agent._tool_messages_list = []
        agent._round_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        agent.skill_registry = None
        loop = OpenAILoop(agent)
        loop.llm_client = ChatClient()
        loop.agent.llm_client = loop.llm_client
        asyncio.run(loop.predict_normal({"messages": [{"role": "user", "content": "hi"}], "stream": False}))
        stored = storedReasoning(loop)
        assert stored, "非流式路径同样要落思考过程（否则存储面成了只读不写的旁路）"
        assert all(GARBAGE_UNIT * 3 not in s for s in stored), (
            f"存储面没剥退化段：{[s[:60] for s in stored]}"
        )
