# -*- coding: utf-8 -*-
"""CORE-17：新标签入口（open_target）必须与 navigate 同过导航护栏与车道互斥。

根因：`navigate()` 走 `runNavigation`（护栏复核 + browser:<session> 车道），
`open_target()` 直接调后端 `open_target`——新标签携带任意 URL 可绕过 URL
复核与车道互斥。修法：open_target 也收口到同一车道包装（新开 tab 会激活并
占据操作面，必须与桌面车道互斥；URL 非空时同样过 navigationRefusal）。
"""
from __future__ import annotations

import pytest

from neurova.computer_use import guardrail
from neurova.computer_use.browser_manager import BrowserManager, BrowserResult
from neurova.computer_use.lane_mutex import get_lane_mutex, reset_lane_mutex


class _StubBackend:
    _initialized = True

    def __init__(self, current_url: str = "https://portal.example.com/inbox"):
        self._url = current_url
        self.openTargetCalls: list = []

    async def open_target(self, url):
        self.openTargetCalls.append(url)
        return BrowserResult(success=True, url=url or "about:blank")

    def currentUrl(self):
        return self._url


def _makeManager():
    manager = BrowserManager(config={})
    stub = _StubBackend()
    manager._backends["playwright"] = stub
    manager._active_backend = stub
    return manager, stub


@pytest.fixture(autouse=True)
def guardrailClean(monkeypatch):
    monkeypatch.delenv("NEUROVA_CUA_GUARDRAIL", raising=False)
    guardrail.resetReviewer()
    reset_lane_mutex()
    yield
    guardrail.resetReviewer()
    reset_lane_mutex()


@pytest.mark.asyncio
async def testOpenTargetCrossSiteIsReviewedAndDenied():
    """跨站新标签在复核 deny 时必须被拒，后端零调用。"""
    manager, stub = _makeManager()

    async def deny(action, params, context):
        return "deny"

    guardrail.setReviewer(deny)

    result = await manager.open_target("https://stranger.org/landing")

    assert result.success is False
    assert (result.data or {}).get("guardrail", {}).get("code") == "guardrail_denied"
    assert stub.openTargetCalls == [], "护栏拒绝后仍开了新标签"


@pytest.mark.asyncio
async def testOpenTargetHoldsBrowserLaneAgainstDesktop():
    """桌面车道在用时新标签必须被车道拒绝，后端零调用。"""
    manager, stub = _makeManager()

    async def allow(action, params, context):
        return "allow"

    guardrail.setReviewer(allow)

    with get_lane_mutex().hold("desktop"):
        result = await manager.open_target("https://portal.example.com/new")

    assert result.success is False
    assert (result.data or {}).get("guardrail", {}).get("code") == "lane_busy"
    assert stub.openTargetCalls == [], "车道拒绝后仍开了新标签"


@pytest.mark.asyncio
async def testOpenTargetAllowedUrlStillOpensAndNotesSeen():
    """放行路径不改变原行为：开 tab 成功后把目标 URL 记入已见链接册。"""
    manager, stub = _makeManager()

    async def allow(action, params, context):
        return "allow"

    guardrail.setReviewer(allow)

    result = await manager.open_target("https://portal.example.com/new")

    assert result.success is True
    assert stub.openTargetCalls == ["https://portal.example.com/new"]
    assert "https://portal.example.com/new" in guardrail.guardrailSeenLinks(manager)