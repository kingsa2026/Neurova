# -*- coding: utf-8 -*-
"""legacy 流式回落那条路也得认思考退化（§6-397 批 H 遗留的第二命中点，§6-403 收尾）。

`_call_legacy_stream` 只取 `chunk.content`、根本不读思考——所以退化**不会**刷屏，
这是它当初被搁下的理由。但同一轮里发生的事是：思考连发把输出预算吃满 → 正文一个字没有
→ 这一路既没有环侧的退化守卫、也没有恢复轮，于是它比主路更安静地交付一个**空回复**，
而上游那 2048 段连发还在继续被消费（每分钟都在花钱）。

主路的判据（§6-397 批 H · B）早就收成一份了：`ReasoningStreamGuard`。这里把它接到
第二条路上——**同一份判定，不同处置**：主路截断思考后继续走恢复轮，这条没有恢复轮，
就停止消费并给一句非空交代（空气泡禁令不分路径）。

四条判据的方向：退化 ⇒ 提前收尾＋非空正文；健康长思考 ⇒ 一字不动；未达阈值 ⇒ 不掐；
思考内容 ⇒ 任何情况下都不许混进正文通道。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.agent.loops.reasoning_degeneracy import (
    MIN_DEGENERACY_CHARS,
    ReasoningStreamGuard,
)

GARBAGE_UNIT = "lock"
GARBAGE_CHUNK = 50
# 阈值之上留足余量：任何合理实现都会在正文出现之前判定退化
GARBAGE_CHUNKS = (MIN_DEGENERACY_CHARS // GARBAGE_CHUNK) + 20


def _chunk(content=None, reasoning=None, finish=None):
    return SimpleNamespace(content=content, reasoning_content=reasoning,
                           usage=None, tool_calls=None, finish_reason=finish)


def degenerateThenLength() -> list:
    return ([_chunk(reasoning=GARBAGE_UNIT * GARBAGE_CHUNK) for _ in range(GARBAGE_CHUNKS)]
            + [_chunk(finish="length")])


def healthyStream() -> list:
    return [
        _chunk(reasoning="先想一下条件。" * 8),
        _chunk(content="第 11 天铺满一半。"),
        _chunk(content="因为每天翻倍。"),
        _chunk(finish="stop"),
    ]


def shortThinkingThenEmpty() -> list:
    """未达退化阈值、但也没正文：不许借"退化"这条判据提前掐。"""
    return [_chunk(reasoning="普通思考。" * 6), _chunk(finish="length")]


class FakeClient:
    """只当网络出口：按脚本产出 chunk，并记录自己是被走完还是被提前关闭。"""

    def __init__(self, chunks):
        self.chunks = chunks
        self.finishedNormally = False
        self.closedEarly = False

    async def chat_stream(self, messages, **kwargs):
        try:
            for chunk in self.chunks:
                yield chunk
            self.finishedNormally = True
        except GeneratorExit:
            self.closedEarly = True
            raise


def runLegacy(chunks):
    client = FakeClient(chunks)
    pipeline = ChatPipeline.__new__(ChatPipeline)
    agent = MagicMock()
    agent.llm_client = client
    pipeline._agent = agent

    emitted = []

    def emitter(event, data):
        emitted.append((event, data))

    ctx = ChatContext(
        user_input="池塘问题", stream=True,
        context=[{"role": "user", "content": "池塘问题"}],
        event_emitter=emitter, metadata={"emit_status_events": True},
    )
    body = asyncio.run(pipeline._call_legacy_stream(ctx))
    return client, body, emitted


class TestDegenerateThinkingIsCut:
    def testStreamIsAbandonedBeforeItBurnsTheRestOfTheBudget(self):
        client, _body, _emitted = runLegacy(degenerateThenLength())

        assert client.closedEarly is True, (
            "退化段还在继续消费＝每一秒都在为一段永远不会成文的连发付费"
        )
        assert client.finishedNormally is False

    def testEmptyReplyIsReplacedByAVisibleReason(self):
        _client, body, emitted = runLegacy(degenerateThenLength())

        assert (body or "").strip(), "空气泡禁令不分路径：这一路也不能交空正文"
        assert GARBAGE_UNIT * 3 not in body, body
        contents = [d for e, d in emitted if e == "content"]
        assert any((d or "").strip() for d in contents), emitted

    def testGuardIsTheSameSingleSourceAsTheMainLoop(self):
        """判据不许在第二条路上另拼一份：阈值与连发判定都归 `ReasoningStreamGuard`。

        守卫的实现住在 `agent/legacy_stream_turn.py`（`chat_pipeline.py` 是每轮对话必经的
        热路径，perf-gate 的 `hot-path-file-size` 要求新逻辑抽出去），所以判据跟着钉到那个
        模块：钉的是**同一个对象**，不是"哪个文件里出现了这个名字"——它换了住处没换身份。
        """
        import neurova.agent.legacy_stream_turn as legacyTurn

        assert getattr(legacyTurn, "ReasoningStreamGuard", None) is ReasoningStreamGuard, (
            "legacy 路没有引用那份共享守卫（或另造了一份）＝同一件事两个事实源"
        )


class TestHealthyStreamsAreUntouched:
    def testNormalThinkingAndContentPassThroughInFull(self):
        client, body, emitted = runLegacy(healthyStream())

        assert client.finishedNormally is True and client.closedEarly is False
        assert body == "第 11 天铺满一半。因为每天翻倍。", body
        assert "".join(d for e, d in emitted if e == "content") == body

    def testThinkingNeverLeaksIntoTheContentChannel(self):
        _client, body, emitted = runLegacy(degenerateThenLength())

        for event, data in emitted:
            if event == "content":
                assert GARBAGE_UNIT * 2 not in (data or ""), data

    def testBelowThresholdThinkingDoesNotTriggerTheCut(self):
        client, _body, _emitted = runLegacy(shortThinkingThenEmpty())

        assert client.finishedNormally is True and client.closedEarly is False, (
            "没到退化阈值就提前掐＝把健康的短思考也一起杀了"
        )
