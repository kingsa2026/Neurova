# -*- coding: utf-8 -*-
"""T-09：截图进模型上下文的三段判据——槽的生命周期、装配闸门、生产者接缝。

## 为什么每条都值得常驻

这条链的三个失败形态都不是"图没进去"，而是**进去了但进错了地方**：

1. `request_params["messages"]` 是**跨轮活的列表**（`openai_loop` 每轮就地
   `extend/append`）。图要是直接挂上去，就等于把 base64 写进历史——正是
   2026-09-09 图片串台事故的形状（历史里遗留的"请结合图片回答"对后续文本轮
   是一条无图可依的指令）。所以判据断言的是**原列表一字未变**。
2. 截图产出发生在 `asyncio.to_thread` / `asyncio.gather` 的**子任务**里。
   不可变 ContextVar 的 `set()` 落不到父轮次（`turn_context` 里耗时累加器
   就为这事留了实测记录），所以槽必须是轮首绑定的**共享对象**——
   这条用真子任务跑，不用手工往父上下文里塞。
3. 成本闸门与分层兜底：一轮至多一张、且**只在感知缺口出现后**才给；
   视觉读数不可用（`not-configured` / `unknown`）时不给。
   "每次感知都附一张图"会把工具轮的成本推到模型服务商的 413 闸门上。
"""

from __future__ import annotations

import asyncio
import base64
import typing

import pytest

from neurova.core import turn_context as tc

def _makeRealPng() -> bytes:
    """真 PNG 字节：装配口会过 `normalize_image_for_llm`（挡 provider 413 的那道），
    拿一串假字节只能测到异常分支，闸门主路径就没被走过。"""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


FAKE_PNG = base64.b64encode(_makeRealPng()).decode("ascii")


class _EventSink:
    """事件面的最小替身：只替"往哪记"，闸门判定全走生产码。"""

    def __init__(self) -> None:
        self.events: typing.List[dict] = []

    def append_tool_event(self, event: dict) -> None:
        self.events.append(event)


def _loop():
    from neurova.agent.loops.openai_loop import OpenAILoop

    loop = OpenAILoop.__new__(OpenAILoop)
    loop.agent = _EventSink()
    return loop


def _requestParams() -> dict:
    return {
        "messages": [
            {"role": "user", "content": "点一下登录按钮"},
            {"role": "assistant", "content": "我看不到页面", "tool_calls": []},
        ],
        "tools": [],
    }


@pytest.fixture(autouse=True)
def _freshRound():
    tc.resetTurnPerceptionImage()
    yield
    tc.resetTurnPerceptionImage()


class TestSlotLifecycle:
    def test_resetRebindsSoLastRoundCannotLeakIntoThisOne(self):
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")
        tc.resetTurnPerceptionImage()
        assert tc.takeTurnPerceptionImage() is None
        assert tc.turnPerceptionGivenCount() == 0

    def test_offerFromChildTaskReachesTheParentRound(self):
        """生产形状：截图在 `to_thread` 里产出。不可变 ContextVar 会在这条上红。"""

        async def run():
            await asyncio.to_thread(tc.offerTurnPerceptionImage, FAKE_PNG, "browser_screenshot")
            return tc.takeTurnPerceptionImage()

        taken = asyncio.run(run())
        assert taken is not None, "子任务的 offer 落不到父轮次——槽没做成共享对象"
        assert taken["base64"] == FAKE_PNG
        assert taken["toolName"] == "browser_screenshot"

    def test_takeIsOneShot(self):
        """取走即清：同一张图被两轮请求重复付费是最隐蔽的成本泄漏。"""
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")
        assert tc.takeTurnPerceptionImage() is not None
        assert tc.takeTurnPerceptionImage() is None


class TestAssemblyGate:
    def test_gapPlusVisionAttachesToTheRequestCopyOnly(self, monkeypatch):
        from neurova.computer_use import capability_state

        monkeypatch.setattr(capability_state, "reading", lambda name, **kw: _available())
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")
        params = _requestParams()
        before = [dict(m) for m in params["messages"]]

        sent = _loop()._attachPerceptionImage(params)

        assert sent is not params, "必须交出副本，不得就地改跨轮活的那份 messages"
        assert any(p.get("type") == "image_url" for m in sent["messages"]
                   for p in (m["content"] if isinstance(m.get("content"), list) else [])), \
            "闸门全开却没挂上图——这条链根本没接"
        assert params["messages"] == before, "原 messages 被改写：base64 就此进历史"
        assert FAKE_PNG not in repr(params["messages"]), "原始请求参数里出现了图"
        assert tc.turnPerceptionGivenCount() == 1

    def test_noGapMeansNoImageEvenThoughAScreenshotExists(self, monkeypatch):
        """分层兜底：感知没缺口就不给图（模型已有 aria/SOM 文本事实可依）。"""
        from neurova.computer_use import capability_state

        monkeypatch.setattr(capability_state, "reading", lambda name, **kw: _available())
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        params = _requestParams()

        sent = _loop()._attachPerceptionImage(params)

        assert FAKE_PNG not in repr(sent["messages"]), "没有感知缺口也附图 = 无闸门"
        assert tc.turnPerceptionGivenCount() == 0, "没给图却计了数，闸门会自己饿死后面真需要的轮"
        assert tc.takeTurnPerceptionImage() is not None, "没给出去就不该把图偷消费掉"

    def test_atMostOneImagePerRound(self, monkeypatch):
        from neurova.computer_use import capability_state

        monkeypatch.setattr(capability_state, "reading", lambda name, **kw: _available())
        loop = _loop()
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")
        first = loop._attachPerceptionImage(_requestParams())
        assert FAKE_PNG in repr(first["messages"])

        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")
        second = loop._attachPerceptionImage(_requestParams())
        assert FAKE_PNG not in repr(second["messages"]), "同一轮放了第二张图，成本闸门失效"
        assert tc.turnPerceptionGivenCount() == 1

    @pytest.mark.parametrize("blockedState", ["not-configured", "unknown", "configured-unreachable"])
    def test_visionCapabilityGate(self, monkeypatch, blockedState):
        """视觉读数不可用时一张都不给——T-07 的三态在这里第一次有了消费者。"""
        from neurova.computer_use import capability_state

        monkeypatch.setattr(
            capability_state, "reading",
            lambda name, **kw: capability_state.CapabilityReading(
                "vision", blockedState, capability_state.OWNER_OPERATOR, "本轮判据造的状态"))
        tc.offerTurnPerceptionImage(FAKE_PNG, "computer_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")

        sent = _loop()._attachPerceptionImage(_requestParams())
        assert FAKE_PNG not in repr(sent["messages"]), f"{blockedState} 也附图，闸门形同虚设"
        assert tc.turnPerceptionGivenCount() == 0

    def test_whyIsRecordedOnTheEventSurface(self, monkeypatch):
        """给了图必须在事件面留痕（谁触发的、为什么给）——静默兜底最难查。"""
        from neurova.computer_use import capability_state

        monkeypatch.setattr(capability_state, "reading", lambda name, **kw: _available())
        loop = _loop()
        tc.offerTurnPerceptionImage(FAKE_PNG, "browser_screenshot")
        tc.markTurnPerceptionGap("browser_dom_snapshot")
        loop._attachPerceptionImage(_requestParams())

        kinds = [e.get("type") for e in loop.agent.events]
        assert "perception_image" in kinds, kinds
        event = [e for e in loop.agent.events if e.get("type") == "perception_image"][-1]
        assert event.get("gapTool"), event
        assert event.get("imageTool"), event


def _available():
    from neurova.computer_use import capability_state

    return capability_state.CapabilityReading(
        "vision", capability_state.CAP_AVAILABLE, capability_state.OWNER_AGENT, "判据造的可用量")


class TestProducerSeam:
    def test_emitOffersEvenWhenWsPanelIsUnavailable(self):
        """生产者接缝不能被 WS 前置条件挡掉：广播要 session_id，
        而模型侧的槽与前端在不在完全无关——早退就把图丢了。"""
        from neurova.tool_executor import ToolExecutor

        executor = ToolExecutor.__new__(ToolExecutor)
        executor._agent = object()  # 无 current_session_id：今天的实现会在这里早退

        asyncio.run(executor._emit_computer_event(
            "computer_screenshot", {}, {"success": True}, screenshot_base64=FAKE_PNG))

        assert tc.takeTurnPerceptionImage() is not None, "图没进槽：生产者被 WS 守卫挡在门外"

    def test_gapIsMarkedFromTheNamedPerceptionFailure(self):
        """感知缺口要由产出侧的具名失败决定，而不是让装配层猜"这轮大概没看清"。"""
        from neurova.tool_executor import ToolExecutor

        executor = ToolExecutor.__new__(ToolExecutor)
        executor._agent = object()

        asyncio.run(executor._emit_computer_event(
            "browser_dom_snapshot", {},
            {"success": False, "error": "snapshot-empty: 页面尚未给出可折结构——请重新快照"}))

        assert tc.turnPerceptionGapTools() == ["browser_dom_snapshot"], tc.turnPerceptionGapTools()
