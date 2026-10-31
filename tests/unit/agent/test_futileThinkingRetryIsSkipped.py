# -*- coding: utf-8 -*-
"""退化截断后的恢复重试，在"关思考的旋钮发不出去"的网关上是空转（§6-397 批 H 实测续）。

实测读数（2026-10-22 23:24 起，真 AMD 网关、真 GLM-5.3-Flash、`thinking_effort=deep`）：
守卫在 `23:25:30` 截断一次 `lock` 连发（512 次／2048 字符）→ `[CTX_RECOVERY]` 立刻
"放宽输出预算+思考降级后单次重试" → **6 分钟后同一处又截断一次**（`23:31:28`，同样
512 次／2048 字符）。整轮 8 分钟，最后仍没有正文。

为什么"降级重试"什么都没降：恢复轮动的是两个键，而这两个键在这条链上**都到不了网关**——

1. `thinking_enabled=False` → 发送侧要 `compat.supports_thinking_toggle` 才注入
   `enable_thinking`（llm_client.py:297），而 `"amd"` 那条声明只给了
   `supports_reasoning_effort=True`（provider_compat.py:128）→ 键被丢掉；
2. `thinking_effort="light"` → 映射表 `_REASONING_EFFORT_MAP` 里 `light: None`
   （provider_compat.py:56），发送侧是 `if reasoning_effort:`（llm_client.py:288）
   → None 就是"不表态"，什么都没发。

于是重试轮带着**零思考控制**重打，网关按默认继续思考、按同样的方式退化。放宽
`max_tokens` 在这里不是救兵而是放大器：多出来的预算正好被第二段连发吃掉。

修法（只做"别空转"这一半；给这条网关补真档位属另一票，等网关稳了探测再定）：
- `ProviderCompat.thinkingReducible(request_params)` 单源回答"关掉/降低思考这个动作
  会不会真的改变发出去的字节"——判据与发送侧读的是**同一批键**，不另拼一份规则；
- 恢复路径在「本轮思考被退化守卫截断」且「旋钮到不了网关」同时成立时**不重试**，
  直接以非空正文收尾（空气泡禁令不变）；
- 三条反向判据钉住"不许扩大战果"：没退化的 length 空正文照旧重试、旋钮真能到的
  网关照旧重试。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm.provider_compat import ProviderCompat

GARBAGE_UNIT = "lock"
GARBAGE_CHUNK = 50
TAIL_SENTINEL = "⟦tail-reached⟧"
# 任何合理阈值下都会在流末尾之前触发截断（守卫阈值 2048 字符，这里给 ~8000）
GARBAGE_CHUNKS = 40


def amdCompat() -> ProviderCompat:
    """真·amd 声明的等价物：只支持 reasoning_effort，不支持 thinking 开关。"""
    from neurova.llm.provider_compat import PROVIDER_COMPAT

    return PROVIDER_COMPAT["amd"]


def garbageChunks(count: int = GARBAGE_CHUNKS) -> list:
    return [
        SimpleNamespace(content=None, reasoning_content=GARBAGE_UNIT * GARBAGE_CHUNK,
                        usage=None, tool_calls=None, finish_reason=None)
        for _ in range(count)
    ] + [SimpleNamespace(content=None, reasoning_content=TAIL_SENTINEL,
                         usage=None, tool_calls=None, finish_reason=None)]


def lengthEmptyRound() -> list:
    """未退化：什么思考都没吐，直接 length 收尾（这正是"健康长思考被预算饿死"的形状）。"""
    return [SimpleNamespace(content=None, reasoning_content=None, usage=None,
                            tool_calls=None, finish_reason="length")]


def cleanContentRound() -> list:
    return [
        SimpleNamespace(content="好。", reasoning_content=None, usage=None,
                        tool_calls=None, finish_reason=None),
        SimpleNamespace(content=None, reasoning_content=None, usage=None,
                        tool_calls=None, finish_reason="stop"),
    ]


class FakeStreamClient:
    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []
        self.config = SimpleNamespace(compat=amdCompat())

    async def chat_stream(self, messages, **kwargs):
        self.calls.append(dict(kwargs))
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        for chunk in self.rounds[idx]:
            yield chunk


def makeLoop(client):
    agent = MagicMock()
    agent._tool_messages_list = []
    agent.skill_registry = None
    agent.llm_client = client
    loop = OpenAILoop(agent)
    loop.llm_client = client
    return loop


def runTurn(rounds, *, compat=None, params=None):
    client = FakeStreamClient(rounds)
    if compat is not None:
        client.config = SimpleNamespace(compat=compat)
    loop = makeLoop(client)
    request = {
        "messages": [{"role": "user", "content": "继续任务"}],
        "stream": True,
        "max_tokens": 4096,
        "thinking_enabled": True,
        "thinking_effort": "deep",
    }
    request.update(params or {})

    async def go():
        return [e async for e in loop._predict_stream(request)]

    return client, asyncio.run(go())


def doneOf(events):
    return [e for e in events if e.get("type") == "done"]


class TestCompatAnswersOnce:
    """`thinkingReducible` 与发送侧读同一批键：三种组合各有确定答案。"""

    def testToggleSupportedIsEnough(self):
        compat = ProviderCompat(supports_thinking_toggle=True)
        assert compat.thinkingReducible({}) is True

    def testExplicitReasoningEffortWithSupportIsEnough(self):
        compat = ProviderCompat(supports_reasoning_effort=True)
        assert compat.thinkingReducible({"reasoning_effort": "high"}) is True

    def testAmdDeclarationWithOnlyThinkingEffortIsSilent(self):
        """amd 现值：thinking_effort 只能映射成 None，且没有 toggle ⇒ 旋钮到不了网关。"""
        assert amdCompat().supports_thinking_toggle is False
        assert amdCompat().map_reasoning_effort("light") is None
        assert amdCompat().thinkingReducible({"thinking_effort": "deep"}) is False


class TestFutileRetryIsSkipped:
    def testDegeneratedRoundOnSilentKnobDoesNotRetry(self):
        """本轮被退化守卫截断 + 旋钮到不了网关 ⇒ 不再发起那第二次调用。"""
        client, events = runTurn([garbageChunks()])
        assert len(client.calls) == 1, (
            f"旋钮到不了网关还重试＝再花 6 分钟撞同一堵墙（实测第二次连发同样 512 次）"
        )
        dones = doneOf(events)
        assert len(dones) == 1, dones
        assert (dones[0].get("reply") or "").strip(), "不重试也得有交代，不许空气泡"
        assert GARBAGE_UNIT * 3 not in dones[0]["reply"], dones[0]["reply"]

    def testNoticeIsSentOnContentChannel(self):
        """交代要出现在正文通道（前端气泡与落库同源），不是只进思考通道。"""
        _client, events = runTurn([garbageChunks()])
        contents = [e["data"] for e in events if e.get("type") == "content" and e.get("data")]
        assert contents, [e.get("type") for e in events]


class TestNonStreamSiteSharesTheSameGate:
    """第三处命中点：`chat_pipeline._call_loop_normal` 的"关思考+放宽预算"非流式恢复。

    同一个病在两条路径上各写一份判据迟早漂（教义第 6 条），故两处都问同一个出口。
    """

    def testDegenerateEmptyNonStreamResponseDoesNotRetry(self):
        from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
        from neurova.llm_client import LLMResponse

        degenerate = "先想一步。" + GARBAGE_UNIT * 4000
        response = LLMResponse(content="", reasoning_content=degenerate, finish_reason="length")

        pipeline = ChatPipeline.__new__(ChatPipeline)
        agent = MagicMock()
        agent.llm_client = SimpleNamespace(
            config=SimpleNamespace(max_tokens=4096, compat=amdCompat())
        )
        pipeline._agent = agent

        loop = MagicMock()

        async def predict_step(**kwargs):
            return response

        loop.predict_step = AsyncMock(side_effect=predict_step)
        agent.loop = loop

        ctx = ChatContext(user_input="q", stream=False, metadata={"thinking_effort": "deep"})
        reply = asyncio.run(pipeline._call_loop_normal(ctx, None))

        assert loop.predict_step.await_count == 1, (
            "非流式同形空转：旋钮到不了网关还重试，只是再等一次连发"
        )
        assert (reply or "").strip() and GARBAGE_UNIT * 3 not in reply, repr(reply)


class TestRetriesThatStillWorkAreKept:
    """反向判据：别把还能救自己的那条路一起关掉。"""

    def testLengthEmptyWithoutDegenerationStillRetries(self):
        client, events = runTurn([lengthEmptyRound(), cleanContentRound()])
        assert len(client.calls) == 2, f"健康长思考被预算饿死时仍该重试一次：{client.calls}"
        assert client.calls[1].get("thinking_enabled") is False
        assert json.dumps([e.get("type") for e in events]).count('"done"') == 1

    def testRetryStillHappensWhenToggleReachesGateway(self):
        """支持 enable_thinking 的网关：关思考真能发出去 ⇒ 照旧重试。"""
        client, events = runTurn(
            [garbageChunks(), cleanContentRound()],
            compat=ProviderCompat(supports_thinking_toggle=True),
        )
        assert len(client.calls) == 2, "旋钮有效时不许借本判据躲重试"

    def testRetryStillHappensWithExplicitReasoningEffort(self):
        client, events = runTurn(
            [garbageChunks(), cleanContentRound()],
            compat=ProviderCompat(supports_reasoning_effort=True),
            params={"reasoning_effort": "high"},
        )
        assert len(client.calls) == 2, "显式档位 + 声明支持 ⇒ 降档发得出去，仍该重试"
