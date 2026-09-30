# -*- coding: utf-8 -*-
"""同族扫荡 · "取不到页面事实"必须在产出侧就是可分诊的形态（T-12 同根因的第二批出口）。

## 病灶（2026-09-30 活体量出，见工单集 §13.3）

`smart-click` 在无活动 tab 时**已经**正确落到 502（不再谎报成功），但 detail 里给模型的
原因是内部英文裸串：

```
502 无法取得页面快照事实，语义点击未执行：Not initialized
```

`Not initialized` 既没点名"没 tab"还是"浏览器进程没起"，也没给下一步动作 —— 模型拿到它
只能瞎猜。这与 T-12 修掉的"空快照被当成功"是同一根因（**取不到事实这一状态在产出侧没有
被命名**），只是不同的出口：

| 出口 | 落点 | 现形态 |
|---|---|---|
| Playwright 无活动 tab | `browser_manager.py:479/514/543/583/600` 五处 raise | `"Not initialized"` |
| Playwright generation 校验 | `browser_manager.py:357` | `"无活动浏览器 tab"`（无补救动作） |
| Playwright 未初始化 context | `browser_manager.py:394`（open_target） | `"Not initialized"` |
| camofox 无活动 tab | `camofox_server_backend.py:180/206` | `"无活动浏览器 tab"`（无补救动作） |
| camofox 无 client | `camofox_server_backend.py:539`（screenshot） | `"not initialized"` |

三处三种措辞，且两种是英文 —— 典型的双源/多源未收口。修法是**单源两个带 marker 的常量**，
两后端共用，而不是各写一句中文。

## 判据取向

- 只断"失败与否"不够（早就失败了对吧）：断的是**可分诊性**——错误里要点名状态、给出下一步动作；
- 两个状态必须可区分：`no-active-tab`（打开页面即可）与 `browser-not-started`（后端没起来，
  重试动作也不同），混成一个 marker 就是把两种病写成同一种；
- parity 用**整句相等**判，不用前缀判 —— 前缀相同、措辞不同正是双源的形态。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from neurova.computer_use.browser_manager import (
    BROWSER_NOT_STARTED_MARKER,
    NO_ACTIVE_TAB_MARKER,
    PlaywrightBackend,
)
from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

# 错误文案必须含的"下一步动作"词：模型据此能直接动作，而不是拿英文词猜
REMEDY_HINTS = ("browser_navigate", "browser_open_target")


def _playwright() -> PlaywrightBackend:
    """未经 initialize、无 tab 的后端 —— 即"取不到事实"的真实形态。"""
    return PlaywrightBackend({"headless": True})


def _camofox() -> CamofoxServerBackend:
    return CamofoxServerBackend({"base_url": "http://127.0.0.1:1"})


def _assertTriageable(res, marker: str) -> None:
    assert res.success is False, f"取不到事实却回了成功: {res}"
    err = res.error or ""
    assert err.startswith(marker), f"错误未点名状态（应 {marker} 前缀）：{err!r}"
    assert any(h in err for h in REMEDY_HINTS), f"错误未给下一步动作：{err!r}"


class TestNoActiveTabIsTriageable:

    @pytest.mark.asyncio
    async def test_playwrightReadSideNamesTheStateAndAction(self):
        b = _playwright()
        _assertTriageable(await b.dom_snapshot(), NO_ACTIVE_TAB_MARKER)
        _assertTriageable(await b.screenshot(), NO_ACTIVE_TAB_MARKER)
        _assertTriageable(await b.navigate("https://example.com"), NO_ACTIVE_TAB_MARKER)

    @pytest.mark.asyncio
    async def test_playwrightActionSideNamesTheStateAndAction(self):
        """动作侧更要紧：拿不到事实时的"失败"必须让模型知道该重快照还是该开页面。"""
        b = _playwright()
        _assertTriageable(await b.click_role("button", "提交"), NO_ACTIVE_TAB_MARKER)
        _assertTriageable(
            await b.fill_role("textbox", name="用户名", text="abc"), NO_ACTIVE_TAB_MARKER)

    @pytest.mark.asyncio
    async def test_staleGenerationCheckUsesTheSameWording(self):
        """generation 校验的无 tab 分支与主路径不得各写一句（同一状态只许一种说法）。"""
        b = _playwright()
        res = await b.dom_snapshot(generation=7)
        _assertTriageable(res, NO_ACTIVE_TAB_MARKER)

    @pytest.mark.asyncio
    async def test_unstartedContextIsADifferentStateNotTheSameOne(self):
        """browser context 不存在 ≠ 没有 tab：两者补救动作不同，必须用不同 marker。"""
        b = _playwright()
        res = await b.open_target("https://example.com")
        assert res.success is False
        assert (res.error or "").startswith(BROWSER_NOT_STARTED_MARKER), res.error


class TestCamofoxParity:

    @pytest.mark.asyncio
    async def test_camofoxNoTabReadsMatchPlaywrightVerbatim(self):
        """整句相等判 parity：前缀同、措辞异就是双源的形态。

        只比"按当前事实读/动作"这两条（dom_snapshot、click_role）；`navigate` 不比，
        因为两后端在无 tab 时的语义本来就不同：Playwright 报"没 tab"，
        camofox 会去 POST /tabs 新开一个。
        """
        pw, cf = _playwright(), _camofox()
        for call in (
            lambda b: b.dom_snapshot(),
            lambda b: b.click_role("button", "提交"),
        ):
            a = await call(pw)
            c = await call(cf)
            _assertTriageable(c, NO_ACTIVE_TAB_MARKER)
            assert c.error == a.error, f"两后端措辞分叉：{c.error!r} ≠ {a.error!r}"

    @pytest.mark.asyncio
    async def test_camofoxUnstartedClientIsNotReportedAsNoTab(self):
        cf = _camofox()
        res = await cf.screenshot()
        assert res.success is False
        assert (res.error or "").startswith(BROWSER_NOT_STARTED_MARKER), res.error


class TestBareEnglishIsNotRevived:

    def test_noBareNotInitializedLiteralRemainsInEitherBackend(self):
        """反证：内部英文裸串不得作为错误文本回潮（AST 判字符串常量，不判注释）。

        匹配 `not initialized` 这个**词组**而不是整串相等——因为真实形态是
        `"CamofoxServerBackend not initialized"`：把类名一起吐给模型，既不可分诊
        又把实现细节当事实说了出去。
        """
        import re

        import neurova.computer_use.browser_manager as bm
        import neurova.computer_use.camofox_server_backend as cb

        for mod in (bm, cb):
            tree = ast.parse(pathlib.Path(mod.__file__).read_text(encoding="utf-8"))
            bare = [
                node.lineno
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and re.search(r"\bnot initialized\b", node.value, re.I)
            ]
            assert not bare, f"{mod.__name__} 仍有把内部状态词直接给模型的落点（行 {bare}）"
