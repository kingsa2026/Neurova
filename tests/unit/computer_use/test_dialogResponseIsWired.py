# -*- coding: utf-8 -*-
r"""JS 对话框的应答链必须真接上——`DialogHandler` 不是拿来摆的（§6-410 批 O-4）。

## 要补的那条断点（本批现查，全部带 file:line）

`DialogHandler` 的实装在 `neurova/computer_use/browser_manager.py:99`：`handle_dialog()`（`:106`）
记录一笔 `{type, message, accepted, timestamp}`，然后 `await dialog.accept()` 或 `.dismiss()`；
读口 `get_dialogs()`（`:121`）与 `clear_dialogs()`（`:124`）都在。

问题是**这条链两头都没接**：

- 写侧：`BrowserManager.__init__:1596` 建了 `self._dialog_handler = DialogHandler()`，而这个名字
  在全仓**只出现这一处**——没有任何读者。`tests/integration/test_browser_manager_integration.py:156`
  只断言它"不是 None"，`tests/unit/computer_use/test_snapshot_budgets.py:78` 甚至把它手工置成 None。
  ⇒ 典型的"只写不读"断点（AGENTS.md §2 协作红线点名的形态）。
- 事件侧：全仓 `neurova/computer_use/` 里**没有任何一处**注册过 dialog 监听
  （grep `\.on(` 在该目录零命中）。页面弹出 `alert/confirm/prompt` 时，Playwright 默认**自动忽略**，
  我们的处理器一次也不会被叫到。

⇒ 裁"接线对话框应答"要做的就是把这两头连上，而不是再造一个抽象。

## 接到哪：只有 `PlaywrightBackend` 拿得到这个事件

按事件源逐个核实过，不是"挑一个看着顺眼的"：

| 后端 | 有无 dialog 事件源 | 依据 |
|---|---|---|
| `PlaywrightBackend` | **有** | `initialize():930` `await self._browser.new_context()` 拿到 context；已装的 playwright 里 `BrowserContext.Events.Dialog = "dialog"`（`_impl/_browser_context.py:98`），`:175` 把 `"dialog"` 绑到 `_on_dialog` 分发，`Page.Events.Dialog` 同名（`_impl/_page.py:139`） |
| `ScraplingBackend` | 无 | `:1092` 起走 fetcher（`self._fetcher.get(url)`），没有实时页面/上下文可挂监听 |
| `CamofoxServerBackend`／`remote_backend` | 无 | 全是 `action(...)` RPC 面（`remote_backend.py:30-59`），camofox 走 REST，词汇里没有 dialog |

仓内另一处用 playwright 的地方也核实过，**不在本批接线面**：`web_reach/browser_read.py:120`
自己 `browser.new_page()` 读页面，它根本没用 `DialogHandler`，靠的是 Playwright 的默认行为
（无监听时 `alert` 被 dismiss、`confirm/prompt` 被取消，不会挂住）。给它也接一条应答，
改的是**读取语义**（页面弹 confirm 从此被 accept），属于另一件事——要动得先裁，别顺手做。

⇒ 所以本批只在 `PlaywrightBackend` 上接，另两路**如实留着不接**——判据里那条
`test_backendsWithoutADialogSourceStayUnwired` 钉的就是这个边界：以后谁给它们"顺手加个
`_attachDialogListener`"，会当场红，那属于造出第二个事件源假象。

## 为什么挂在 context 而不是 page

`_register_tab()` 给每个 tab 建一个 page（`open_target()` 里 `await self._context.new_page()`），
page 级注册要跟着 tab 生命周期到处补；context 级一处注册即覆盖该 context 内**全部**页面（含
新开 tab）。这也是本批把注册点单独抽成 `_attachDialogListener(target)` 的原因：
真 Chromium 在这台机器上没下载（`ms-playwright/chromium-1243` 不存在），launch 路径走不到，
而那层是 playwright 自己的代码——本批要证的是**我们的**注册与应答，用桩 context 才咬得住。

## 判据的对照

- **正检**：桩 context 记下 `("dialog", handler)`；把桩 dialog 打进去 ⇒ 应答发生且留档。
- **闭环**：从 `BrowserManager` 拿到的那个后端，其 handler **必须就是** manager 自己那份
  （`be._dialog_handler is mgr._dialog_handler`），否则接的是第二个空口袋，`dialogLog()` 永远为空。
- **不想象 API**：一格专门拿**已安装的** `playwright.async_api.Dialog` 比对我们真正会调的那几个成员
  （`type`/`message`/`accept`/`dismiss`），对不上就是接缝又漂了。
- **边界**：另两路后端保持"没有 dialog 事件源"这个形状。
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Tuple

import pytest

from neurova.computer_use.browser_manager import (
    BrowserManager,
    DialogHandler,
    HAS_PLAYWRIGHT,
    PlaywrightBackend,
)

#: 闭环那两格问的是「manager 交下去的后端是不是它自己那份 handler」，前提是**这台机器
#: 真能建出 playwright 后端**。精简锁刻意不含 playwright（`requirements-ci.txt` 的排除名单、
#: 以及 `tests/unit/ci/test_dev_environment_contract.py` 那句「只装精简锁得到的是薄环境」
#: 都写着同一件事），那里 `HAS_PLAYWRIGHT` 为假、`_load_config` 一条后端都不建，
#: 判据照着「本机装了」写就会红成 `KeyError: 'playwright'`——红因是环境缺件，不是接线错。
#: 故前提由本档自给：缺件时 skip 并当场点名缺什么；装了却建不出后端仍照旧红（那才是断线）。
#: 与 `TestTheSeamMatchesTheInstalledPlaywright` 同一口径——它早就在用
#: `importorskip("playwright.async_api")` 自钉前提。**不该**改用 `importorskip`：
#: 那会把整档在收集期切掉，连下面 `test_loadConfigReadsTheLiveProbeFlag`（本档自带的
#: 「在册表跟着活探测位走」那一向）一起哑掉。
_requiresPlaywright = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="本机没有可用的 playwright（精简 CI 锁刻意不含它），建不出后端无从判闭环",
)


def _managerWithPlaywrightBackend() -> BrowserManager:
    """建 manager 并断言「装了 playwright 就一定有那条后端」——这断言本身是接线判据。

    它留在辅助处而不是被 skip 掉：一旦环境里 playwright 可用却建不出后端，
    上面那条 `skipif` 放行、这里当场红——把「环境缺件」与「接线断了」分开。
    """
    manager = BrowserManager(config={})
    assert "playwright" in manager._backends, (
        "`HAS_PLAYWRIGHT` 为真而 `_load_config` 没建出 playwright 后端——接面对象不存在"
    )
    return manager


class _StubContext:
    """只记录订阅的假 context——本批要证的是**我们的**注册形状，不是 playwright 的派发。"""

    def __init__(self) -> None:
        self.subscriptions: List[Tuple[str, Any]] = []

    def on(self, event: str, handler) -> None:
        self.subscriptions.append((event, handler))


class _StubDialog:
    """按已装 playwright 的 `Dialog` 面来造：`type`／`message`／`accept()`／`dismiss()`。"""

    def __init__(self, kind: str = "alert", message: str = "确定要离开吗？") -> None:
        self.type = kind
        self.message = message
        self.calls: List[str] = []

    async def accept(self) -> None:
        self.calls.append("accept")

    async def dismiss(self) -> None:
        self.calls.append("dismiss")


class TestDialogListenerIsRegistered:
    """事件侧：后端必须把自己那份 handler 挂到 context 的 dialog 事件上。"""

    def test_backendRegistersTheDialogListenerOnTheContext(self):
        handler = DialogHandler()
        backend = PlaywrightBackend({}, dialog_handler=handler)
        context = _StubContext()

        backend._attachDialogListener(context)

        assert [name for name, _f in context.subscriptions] == ["dialog"], (
            "没往 context 上注册 `dialog` 监听——弹出 alert/confirm 时 playwright 默认直接忽略，"
            "`DialogHandler` 一次都不会被叫到（实测：改前全仓 `neurova/computer_use/` 零处 `.on(`）"
        )
        _name, registered = context.subscriptions[0]
        assert callable(registered), "注册的不是可调用对象"

    def testEventFromTheRegisteredListenerRecordsAndAccepts(self):
        """应答面：事件经**注册时交出去的那个回调**进来后，要既答了又留档。"""
        handler = DialogHandler()
        backend = PlaywrightBackend({}, dialog_handler=handler)
        context = _StubContext()
        backend._attachDialogListener(context)
        _name, listener = context.subscriptions[0]

        dialog = _StubDialog()
        asyncio.run(listener(dialog))

        assert dialog.calls == ["accept"], "对话框没被应答：`handle_dialog` 没真走到 `dialog.accept()`"
        entries = handler.get_dialogs()
        assert len(entries) == 1, "应答发生了却没留档——`_dialog_handler` 仍是只写不读的那只手"
        assert entries[0]["type"] == "alert" and entries[0]["message"] == "确定要离开吗？", entries[0]
        assert entries[0]["accepted"] is True, entries[0]

    def testAutoRejectPathDismissesInsteadOfAccepting(self):
        """`auto_accept=False` 那一支也得真走到 `dismiss()`，不能只会 accept（默认值掩盖半边实装）。"""
        handler = DialogHandler(auto_accept=False)
        backend = PlaywrightBackend({}, dialog_handler=handler)
        context = _StubContext()
        backend._attachDialogListener(context)
        _name, listener = context.subscriptions[0]

        dialog = _StubDialog(kind="confirm")
        asyncio.run(listener(dialog))

        assert dialog.calls == ["dismiss"], dialog.calls
        assert handler.get_dialogs()[0]["accepted"] is False

    def testBackendWithoutAHandlerDoesNotCrashThePage(self):
        """没给 handler（单测里手工构造后端的老写法）时，回调要么不注册，要么注册了也**不炸**：
        浏览器自动化面崩在"没有留档口袋"上是把旁路故障打进主链。"""
        backend = PlaywrightBackend({})
        context = _StubContext()
        backend._attachDialogListener(context)
        if not context.subscriptions:
            return  # 不注册也是合法的一种：没有 handler 就没有留档去处
        _name, listener = context.subscriptions[0]
        asyncio.run(listener(_StubDialog()))  # 不抛即通过


@_requiresPlaywright
class TestManagerReadFaceClosesTheLoop:
    """写侧闭环：`_dialog_handler` 不再只写不读，且后端拿的就是 manager 那一份。"""

    def testManagerSharesItsHandlerWithThePlaywrightBackend(self):
        manager = _managerWithPlaywrightBackend()
        backend = manager._backends["playwright"]
        assert getattr(backend, "_dialog_handler", None) is manager._dialog_handler, (
            "后端用的是**另一份** handler ⇒ 事件写进别的口袋，`BrowserManager.dialogLog()` 永远为空"
        )

    def testManagerExposesTheDialogLogAsANamedReadFace(self):
        manager = _managerWithPlaywrightBackend()
        assert manager.dialogLog() == [], "读口起点不为空：别的实例的留档漏进来了"

        backend = manager._backends["playwright"]
        context = _StubContext()
        backend._attachDialogListener(context)
        _name, listener = context.subscriptions[0]
        asyncio.run(listener(_StubDialog(kind="beforeunload", message="还有未保存内容")))

        log = manager.dialogLog()
        assert len(log) == 1, (
            "真链路走完后 manager 侧读不到任何对话框记录——`DialogHandler` 还是那条被实例化后"
            "无人读取的断点"
        )
        assert log[0]["type"] == "beforeunload", log[0]

    def testDialogLogIsACopyNotTheLiveList(self):
        """读口给的是快照：调用方清空/改写返回值不得动到实装内的留档（`clear_dialogs` 才是唯一清口）。"""
        manager = BrowserManager(config={})
        manager._dialog_handler.get_dialogs().append({"type": "forged"})
        assert manager.dialogLog() == [], "读口直接吐了内部列表 ⇒ 外部能伪造应答记录"


class TestTheSeamMatchesTheInstalledPlaywright:
    """不许照着想象写接缝：真正会调的那几个成员，得在**已安装的** Dialog 类上存在。"""

    def testEveryDialogMemberWeTouchExistsOnTheRealClass(self):
        import pytest

        pytest.importorskip("playwright.async_api")
        from playwright.async_api import Dialog

        for member in ("type", "message", "accept", "dismiss"):
            assert hasattr(Dialog, member), (
                "`DialogHandler` 会读/调 `dialog.%s`，而已安装的 playwright 的 `Dialog` 上没有它"
                "——升级/换后端前先让这条红，别等运行时 AttributeError" % member
            )


class TestBackendsWithoutADialogSourceStayUnwired:
    """边界控制：只有 `PlaywrightBackend` 有 dialog 事件源，另两路保持"没接"这个形状。"""

    def testNonSessionBackendsDoNotClaimADialogListener(self):
        from neurova.computer_use.browser_manager import ScraplingBackend
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

        for cls in (ScraplingBackend, CamofoxServerBackend):
            assert not hasattr(cls, "_attachDialogListener"), (
                "%s 冒出了 `_attachDialogListener`——它拿不到 dialog 事件（前者走 fetcher、后者是 "
                "REST/action RPC 面），挂上等于造一个'已应答'的假象" % cls.__name__
            )


def test_loadConfigReadsTheLiveProbeFlag(monkeypatch):
    """在册表必须跟着**模块的活属性**走：谁把 `HAS_PLAYWRIGHT` 钉住，`_load_config` 就得认。

    受保护子集里本档的闭环两格与集成档 `camofoxOnlyManager` 都靠 monkeypatch 钉这个位来造
    "只有一路后端"的在册表；脱钩时红出来的是与主题无关的 `KeyError: 'playwright'`。
    """
    from neurova.computer_use import browser_manager as bm

    monkeypatch.setattr(bm, "HAS_PLAYWRIGHT", False)
    assert "playwright" not in bm.BrowserManager()._backends, (
        "探测位被钉成 False，在册表里却仍有 playwright ⇒ `_load_config` 读的不是活属性")

    monkeypatch.setattr(bm, "HAS_PLAYWRIGHT", True)
    # 这一向问的是「读的是不是活属性」，中间夹着「真能建出那个后端吗」：`PlaywrightBackend.__init__`
    # 本身不碰 playwright，故后端对象照建；只有真用起来才需要依赖。CI 精简锁没有 playwright，
    # 那不是这条判据要裁决的事——按同一前提自给，缺件时不把环境缺件报成脱钩。
    if not HAS_PLAYWRIGHT:
        return
    assert "playwright" in bm.BrowserManager()._backends, (
        "探测位被钉成 True，在册表里却没有 playwright ⇒ `_load_config` 读的不是活属性")
