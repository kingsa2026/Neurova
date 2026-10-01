"""Anthropic 环的截图装配必须与 OpenAI 环**同闸门同判据**（T-09 · 🔒Q-3 拍"同形"）。

## 为什么会红

改前的形状：`anthropic_loop.py:320` 那条图片通路是它自己的原生 computer 工具内容块，
不经我们的轮级槽与闸门。走 Anthropic 服务商时，槽被生产者填、装配侧无人消费——
能力在那条路上"尚未生效"，而这事只活在工单集 §24.5 的散文里。

拍板选同形装配之后，**闸门只能有一份**：两环各写一份三闸，迟早漂移成
"某环给图某环不给"的分裂读数（教义第 6 条）。所以本文件不只测 Anthropic 的形状，
还把两环的**放行判定表逐条比对**，并把共享闸门打桩成"不放行"验 nobody 自带一份。

## 判据口径

- 形状各环断言各自的（Anthropic 内容块是 `{"type":"image","source":{"type":"base64",…}}`）；
- 图用真 PNG 字节：装配口过 `normalize_image_for_llm`，假字节只会撞进异常分支；
- 断言的是发出去的**参数**与原始 `messages` 是否被改写，不是替身被调了几次。
"""
import asyncio
import base64
import io
import typing

import pytest
from PIL import Image

from neurova.core import turn_context as tc


def _makeRealPng() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (12, 34, 56)).save(buf, format="PNG")
    return buf.getvalue()


REAL_PNG = _makeRealPng()
FAKE_PNG = base64.b64encode(REAL_PNG).decode("ascii")


class _EventSink:
    def __init__(self) -> None:
        self.events: typing.List[dict] = []

    def append_tool_event(self, event: dict) -> None:
        self.events.append(event)


def _openaiLoop():
    from neurova.agent.loops.openai_loop import OpenAILoop

    loop = OpenAILoop.__new__(OpenAILoop)
    loop.agent = _EventSink()
    return loop


def _anthropicLoop():
    from neurova.agent.loops.anthropic_loop import AnthropicLoop

    loop = AnthropicLoop.__new__(AnthropicLoop)
    loop.agent = _EventSink()
    return loop


def _openaiParams() -> dict:
    return {"messages": [{"role": "user", "content": "点一下登录按钮"}], "tools": []}


def _anthropicParams() -> dict:
    return {
        "system": "你是 Neurova",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "点一下登录按钮"}]}],
        "tools": [],
    }


def _available():
    from neurova.computer_use import capability_state

    return capability_state.CapabilityReading(
        "vision", capability_state.CAP_AVAILABLE, capability_state.OWNER_AGENT, "判据造的可用量")


def _blockedReading(state: str):
    from neurova.computer_use import capability_state

    return capability_state.CapabilityReading(
        "vision", state, capability_state.OWNER_OPERATOR, "判据造的状态")


def _imageBlocks(params: dict) -> list:
    parts = []
    for msg in params.get("messages") or []:
        content = msg.get("content")
        if isinstance(content, list):
            parts += [c for c in content if isinstance(c, dict) and c.get("type") == "image"]
    return parts


def _openaiImageParts(params: dict) -> list:
    parts = []
    for msg in params.get("messages") or []:
        content = msg.get("content")
        if isinstance(content, list):
            parts += [c for c in content if isinstance(c, dict) and c.get("type") == "image_url"]
    return parts


@pytest.fixture(autouse=True)
def _freshRound():
    tc.resetTurnPerceptionImage()
    yield
    tc.resetTurnPerceptionImage()


class TestAnthropicAssembly:
    def test_gapPlusVisionAttachesImageBlockToTheRequestCopyOnly(self, monkeypatch):
        """闸门全开时 Anthropic 环必须挂上内容块，且只挂在**副本**上。"""
        from neurova.computer_use import capability_state

        monkeypatch.setattr(capability_state, "reading", lambda name, **kw: _available())
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")
        params = _anthropicParams()
        before = [dict(m) for m in params["messages"]]

        sent = _anthropicLoop()._attachPerceptionImage(params)

        assert sent is not params, "必须交副本——原 messages 是跨轮活的那份"
        blocks = _imageBlocks(sent)
        assert len(blocks) == 1, f"该挂一张，实际挂了 {len(blocks)} 张"
        source = blocks[0]["source"]
        assert source["type"] == "base64" and source["media_type"] == "image/png"
        assert Image.open(io.BytesIO(base64.b64decode(source["data"]))).format == "PNG", \
            "挂上去的字节解不开成 PNG：装配口没走归一化"
        assert params["messages"] == before, "原始 messages 被改写 = base64 进历史"
        assert FAKE_PNG not in repr(params["messages"])
        assert tc.turnPerceptionGivenCount() == 1

    def test_noGapMeansNoImageEvenThoughAScreenshotExists(self, monkeypatch):
        """分层兜底与 OpenAI 环同判据：感知没缺口就不给图。"""
        from neurova.computer_use import capability_state

        monkeypatch.setattr(capability_state, "reading", lambda name, **kw: _available())
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")

        sent = _anthropicLoop()._attachPerceptionImage(_anthropicParams())

        assert not _imageBlocks(sent), "没缺口也附图 = 这条环没闸门"
        assert tc.turnPerceptionGivenCount() == 0
        assert tc.takeTurnPerceptionImage() is not None, "没给出去就不该把图偷消费掉"

    def test_atMostOneImagePerRound(self, monkeypatch):
        from neurova.computer_use import capability_state

        monkeypatch.setattr(capability_state, "reading", lambda name, **kw: _available())
        loop = _anthropicLoop()
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")

        first = loop._attachPerceptionImage(_anthropicParams())
        second = loop._attachPerceptionImage(_anthropicParams())

        assert len(_imageBlocks(first)) == 1
        assert not _imageBlocks(second), "同轮放了第二张图，成本闸门在这条环上失效"
        assert tc.turnPerceptionGivenCount() == 1

    @pytest.mark.parametrize("blockedState", ["not-configured", "unknown", "configured-unreachable"])
    def test_visionReadingBlocksEveryNonAvailableState(self, monkeypatch, blockedState):
        from neurova.computer_use import capability_state

        monkeypatch.setattr(capability_state, "reading",
                            lambda name, **kw: _blockedReading(blockedState))
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")

        sent = _anthropicLoop()._attachPerceptionImage(_anthropicParams())

        assert not _imageBlocks(sent), f"{blockedState} 也附图，闸门形同虚设"
        assert tc.turnPerceptionGivenCount() == 0

    def test_whyIsRecordedOnTheEventSurface(self, monkeypatch):
        """给了图要在事件面留痕，且口径与 OpenAI 环同一份字段名。"""
        from neurova.computer_use import capability_state

        monkeypatch.setattr(capability_state, "reading", lambda name, **kw: _available())
        loop = _anthropicLoop()
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")

        loop._attachPerceptionImage(_anthropicParams())

        events = [e for e in loop.agent.events if e.get("type") == "perception_image"]
        assert len(events) == 1, loop.agent.events
        assert events[0]["gapTool"] == "browser_dom_snapshot"
        assert events[0]["imageTool"] == "computer_screenshot"
        assert events[0].get("reason")


class TestOneGateForBothLoops:
    """闸门必须只有一份：两环在**同一初态**下的放行判定逐条对齐。

    每条场景都从"重新种一次槽"开始跑——第一次装配会把图消费掉并把本轮计数加一，
    接着跑第二次就必然不给，那测的是计数闸门而不是两环一致性（那种形状我自己先踩过）。
    """

    # (场景名, 是否有缺口, vision 状态, 本轮是否先烧掉一张, 期望给不给)
    SCENARIOS = [
        ("gapAvailable", True, None, False, True),
        ("noGap", False, None, False, False),
        ("unknown", True, "unknown", False, False),
        ("notConfigured", True, "not-configured", False, False),
        ("configuredUnreachable", True, "configured-unreachable", False, False),
        ("secondInSameRound", True, None, True, False),
    ]

    @pytest.mark.parametrize("name,hasGap,blocked,consumeFirst,expected", SCENARIOS,
                             ids=[s[0] for s in SCENARIOS])
    def test_bothLoopsAgreeOnWhetherAnImageGoesOut(
        self, monkeypatch, name, hasGap, blocked, consumeFirst, expected
    ):
        from neurova.computer_use import capability_state

        monkeypatch.setattr(
            capability_state, "reading",
            lambda key, **kw: _available() if blocked is None else _blockedReading(blocked))

        def _attach(which: str) -> dict:
            if which == "openai":
                return _openaiLoop()._attachPerceptionImage(_openaiParams())
            return _anthropicLoop()._attachPerceptionImage(_anthropicParams())

        def _gave(which: str) -> bool:
            tc.resetTurnPerceptionImage()
            tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
            if hasGap:
                tc.markTurnPerceptionGap("browser_dom_snapshot")
            if consumeFirst:
                _attach(which)          # 先烧掉本轮唯一一张（烧的是同一条环的第一次装配）
            sent = _attach(which)
            for msg in sent.get("messages") or []:
                content = msg.get("content")
                if isinstance(content, list) and any(
                    isinstance(c, dict) and c.get("type") in ("image", "image_url") for c in content
                ):
                    return True
            return False

        gaveOpenai = _gave("openai")
        gaveAnthropic = _gave("anthropic")

        assert gaveOpenai == gaveAnthropic, \
            f"{name}: 两环判定分叉 openai={gaveOpenai} anthropic={gaveAnthropic}"
        assert gaveAnthropic is expected, f"{name}: 期望 {expected}，实得 {gaveAnthropic}"

    def test_loopsHaveNoGateOfTheirOwn(self, monkeypatch):
        """把共享闸门打桩成"不放行"，两环都不许给出图——谁自带一份闸门这条就红。"""
        from neurova.agent.loops import perception_gate

        monkeypatch.setattr(perception_gate, "claimTurnPerception", lambda: None)
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")

        assert not _openaiImageParts(_openaiLoop()._attachPerceptionImage(_openaiParams()))
        assert not _imageBlocks(_anthropicLoop()._attachPerceptionImage(_anthropicParams()))


class TestSendPointIsWired:
    def test_predictAnthropicSendsAttachedCopyAndKeepsOriginalIntact(self, monkeypatch):
        """装配必须接在真发送口上：`chat(**…)` 收到带图的副本，而入参那份一字未改。"""
        from neurova.computer_use import capability_state

        monkeypatch.setattr(capability_state, "reading", lambda name, **kw: _available())
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")

        captured: typing.Dict[str, typing.Any] = {}

        class _Client:
            async def chat(self, **kwargs):
                captured.update(kwargs)
                return {"role": "assistant", "content": [{"type": "text", "text": "看到了"}]}

        loop = _anthropicLoop()
        loop.llm_client = _Client()
        params = _anthropicParams()

        asyncio.run(loop._predict_anthropic(params))

        assert len(_imageBlocks(captured)) == 1, "发送口没接上装配——闸门改了但没人调"
        assert not _imageBlocks(params), "原始 request_params 被就地改写"
        assert FAKE_PNG not in repr(params["messages"])
