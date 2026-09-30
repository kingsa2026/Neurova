# -*- coding: utf-8 -*-
"""T-12 · 空快照不得算成功观察（与 T-06b 同族：把"取不到"谎报成"没有"）。

## 病灶（2026-09-30 活体反证时撞出来）

给 `smart-click` 做三态活体时，想验证"快照取不到要回 502、不得谎报已点击"，
该分支**根本没被触发**：关掉活动 tab 后 `dom_snapshot()` 仍回 `success=True`
且正文为空 ⇒ 语义解析在空候选上得到 `unresolved` ⇒ 端点回 404。

两种"空"被压成同一形态：

| 实况 | 应有读数 | 现状 |
|---|---|---|
| 未取得任何页面事实（无活动 tab、页面未加载、渲染前） | 失败，且可与下一种区分 | `success=True` + 空正文 |
| 页面确实没有可交互元素（纯静态文档） | 成功，正文非空但可交互项为 0 | 同上，无从区分 |

第二行必须仍然是成功——否则就是过度捕获，把"空页面"也判成故障。

## 为什么这是根因而非兜底

在调用方补 `if not data: 报错` 是把症状挪走：每个消费点都要再判一次，
且新消费点一定会漏。修在**产出快照的那一处**：空正文即观察失败。
"""

from __future__ import annotations

import pytest


class _TreePage:
    """真数据假驱动：只控制 aria 文本，判据打的是我们自己的成功/失败语义。"""

    def __init__(self, tree: str):
        self.url = "http://fake/"
        self._tree = tree

    def locator(self, _selector):
        page = self

        class _L:
            async def aria_snapshot(self):
                return page._tree

        return _L()

    async def title(self):
        return "fake"


def _playwright(tree: str):
    import neurova.computer_use.browser_manager as bmm

    be = bmm.PlaywrightBackend({"headless": True})
    be._initialized = True
    page = _TreePage(tree)
    be._register_tab(page)
    return be


class TestEmptySnapshotIsNotSuccess:
    @pytest.mark.asyncio
    async def test_emptyTreeIsReportedAsFailure(self):
        res = await _playwright("").dom_snapshot()
        assert res.success is False, "空正文仍被当成功观察"
        assert res.error, "失败必须点名原因"

    @pytest.mark.asyncio
    async def test_whitespaceOnlyTreeIsAlsoFailure(self):
        res = await _playwright("   \n\t \n").dom_snapshot()
        assert res.success is False

    @pytest.mark.asyncio
    async def test_failureReasonIsStableNotProseOnly(self):
        """消费方要能按稳定标记分诊，不能靠匹配中文措辞。"""
        from neurova.computer_use.browser_manager import EMPTY_SNAPSHOT_MARKER

        res = await _playwright("").dom_snapshot()
        assert EMPTY_SNAPSHOT_MARKER in (res.error or ""), (
            f"失败原因未带可分诊标记：{res.error!r}"
        )


class TestStaticPageIsStillSuccess:
    """反面对照：页面有结构、只是没有可交互元素 —— 这是成功观察，不得判成故障。"""

    @pytest.mark.asyncio
    async def test_treeWithoutInteractiveIsSuccess(self):
        tree = "- document:\n  - paragraph: 这是一段纯文字，没有链接也没有按钮。"
        res = await _playwright(tree).dom_snapshot()
        assert res.success is True
        assert res.data == tree

    @pytest.mark.asyncio
    async def test_minimalNonEmptyTreeIsSuccess(self):
        res = await _playwright("- document").dom_snapshot()
        assert res.success is True


class TestCamofoxParity:
    """两后端同一语义（T-03 的教训：形状分叉就是判据分叉）。"""

    @staticmethod
    async def _camofox(snapshot: str):
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend
        from tests.unit.computer_use.test_camofox_server_backend import (
            _http_response,
            _make_backend,
            _seed_tab,
        )

        b, _c = _make_backend(request_return=_http_response(
            {"snapshot": snapshot, "refsCount": 0, "url": "https://x"}))
        _seed_tab(b)
        return await b.dom_snapshot()

    @pytest.mark.asyncio
    async def test_camofoxEmptySnapshotAlsoFails(self):
        from neurova.computer_use.browser_manager import EMPTY_SNAPSHOT_MARKER

        res = await self._camofox("")
        assert res.success is False
        assert EMPTY_SNAPSHOT_MARKER in (res.error or "")

    @pytest.mark.asyncio
    async def test_camofoxStaticPageStillSucceeds(self):
        res = await self._camofox("- document:\n  - paragraph: 纯文字")
        assert res.success is True


class TestEndpointNoLongerMasksIt:
    @pytest.mark.asyncio
    async def test_smartClickReturns502WhenFactsUnavailable(self, monkeypatch):
        """502 此前不可达：生产者谎报成功 ⇒ 空候选 ⇒ 误报 404「没找到」。

        这里不造假信封（修好生产者后那种状态不再可能），而是把**真生产者**接上：
        空 aria 树的 Playwright 后端 → 端点必须按"未取得事实"分诊。
        """
        from fastapi import HTTPException

        from neurova.api.endpoints import computer as ep
        import neurova.computer_use as cu

        backend = _playwright("")

        class M:
            async def browser_dom_snapshot(self, generation=None, max_nodes=None, max_depth=None):
                return await backend.dom_snapshot(generation, max_nodes, max_depth)

            async def browser_click_role(self, role, name=None, generation=None):
                raise AssertionError("未取得事实时不得执行点击")

        monkeypatch.setattr(cu, "get_computer_use_manager", lambda: M())
        with pytest.raises(HTTPException) as caught:
            await ep.smart_click(ep.SmartClickRequest(target="任意按钮"))
        assert caught.value.status_code == 502, (
            f"未取得事实被降级成 404「没找到」，状态码={caught.value.status_code}"
        )


class TestGuardIsNotVacuous:
    def test_successEnvelopeWithEmptyDataIsTheBug(self):
        """正对照：若实现只是"空正文也回 success=True"，本判据必须能抓出来。"""
        from neurova.computer_use.browser_manager import BrowserResult

        bad = BrowserResult(success=True, data="")
        assert bad.success is True and not (bad.data or "").strip()
        assert _looksLikeEmptySuccess(bad) is True

    def test_realFailureIsNotMistakenForEmptySuccess(self):
        from neurova.computer_use.browser_manager import BrowserResult

        assert _looksLikeEmptySuccess(BrowserResult(success=False, error="x")) is False
        ok = BrowserResult(success=True, data="- document:\n  - paragraph: 文字")
        assert _looksLikeEmptySuccess(ok) is False


def _looksLikeEmptySuccess(res) -> bool:
    """扫描判据：成功信封 + 空白正文（含 dict 载荷里的 snapshot）。"""
    if not getattr(res, "success", False):
        return False
    data = getattr(res, "data", None)
    if isinstance(data, dict):
        data = data.get("snapshot", "")
    return not str(data or "").strip()
