# -*- coding: utf-8 -*-
"""browser_back/forward/reload/wait/scroll/press 六工具接线守卫（P2 批A）。

## 背景

agent-browser 对照（见 test_browser_tab_eval_tools.py 同批工作）P2 缺口的第一块：
页面级动作——导航补全（后退/前进/刷新）、等待条件、滚动、键盘按键。底层
PlaywrightBackend 此前只有 goto 一条导航路径，历史/刷新/等待/滚动/按键全部
缺失，模型只能靠 eval 绕（绕不开 wait_for_selector 这类带自动重试的等待）。

## 面位

与 tab/eval 批同构：schema / 派生 / 治理 / 参数 / 权限 / 能力声明 / 重放轴。
重放轴口径：back/forward/reload/scroll/press 重放会制造新页面状态（导航、
相对滚动、重复按键），进 _NON_REPRODUCIBLE_TOOLS；wait 是同参数同效果的
纯等待，**可重现**（与 browser_read 游标族同判据）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.tool_executor import (
    _COMPUTER_TOOL_PARAM_KEYS,
    COMPUTER_USE_TOOLS,
    ToolExecutor,
    describe_computer_action,
)

NEW_TOOLS = (
    "browser_back",
    "browser_forward",
    "browser_reload",
    "browser_wait",
    "browser_scroll",
    "browser_press",
)
NON_REPRODUCIBLE = {"browser_back", "browser_forward", "browser_reload", "browser_scroll", "browser_press"}


# ── 五面登记 ──────────────────────────────────────────────

class TestToolFaces:
    def test_schemasRegistered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        missing = [n for n in NEW_TOOLS if n not in _BUILTIN_SCHEMAS]
        assert not missing, f"schema 面缺登记: {missing}"

    def test_dispatchable(self):
        missing = [n for n in NEW_TOOLS if n not in ToolExecutor._builtin_dispatch]
        assert not missing, f"派生面缺登记: {missing}"

    def test_inGovernanceSurface(self):
        missing = [n for n in NEW_TOOLS if n not in COMPUTER_USE_TOOLS]
        assert not missing, f"治理面缺登记: {missing}"

    def test_paramKeysDeclaredAndMatchSchema(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        for name in NEW_TOOLS:
            assert name in _COMPUTER_TOOL_PARAM_KEYS, f"{name} 缺参数白名单"
            props = set(_BUILTIN_SCHEMAS[name]["parameters"].get("properties", {}))
            declared = set(_COMPUTER_TOOL_PARAM_KEYS[name])
            assert declared == props, f"{name} 参数面 {sorted(declared)} != schema {sorted(props)}"

    def test_permissionCategoryNetwork(self):
        from neurova.skills.permissions import tool_categories

        unclassified = [n for n in NEW_TOOLS if "network" not in tool_categories(n)]
        assert not unclassified, f"权限面未归类: {unclassified}"

    def test_capabilityDeclared(self):
        from neurova.agent.tool_coordinator import resolveToolCapability

        undeclared = [n for n in NEW_TOOLS if resolveToolCapability(n) is None]
        assert not undeclared, f"未声明并行能力: {undeclared}"

    def test_reproducibleAxis(self):
        """导航/滚动/按键重放制造新状态 ⇒ 不可重现；wait 纯等待 ⇒ 可重现。"""
        from neurova.builtin_tools import _NON_REPRODUCIBLE_TOOLS

        leaked = sorted(NON_REPRODUCIBLE - set(_NON_REPRODUCIBLE_TOOLS))
        assert not leaked, f"重放会制造新状态的工具漏出不可重现名单: {leaked}"
        assert "browser_wait" not in _NON_REPRODUCIBLE_TOOLS, (
            "wait 是同参数同效果的纯等待，属可重现（与游标族同判据）"
        )

    def test_notInteractiveDesktop(self):
        from neurova.builtin_tools import get_builtin_tool_flags

        for name in NEW_TOOLS:
            assert get_builtin_tool_flags(name).get("interactive_desktop") is not True

    def test_humanReadableActionDescription(self):
        assert "后退" in describe_computer_action("browser_back", {})
        assert "前进" in describe_computer_action("browser_forward", {})
        assert "刷新" in describe_computer_action("browser_reload", {})
        assert "等待" in describe_computer_action("browser_wait", {"ms": 1000})
        assert "滚动" in describe_computer_action("browser_scroll", {"scroll_y": 300})
        assert "按键" in describe_computer_action("browser_press", {"key": "Enter"})


# ── PlaywrightBackend 底层行为（fake page，不起真浏览器） ──

class TestPlaywrightBackend:
    @staticmethod
    def _backend():
        from neurova.computer_use.browser_manager import PlaywrightBackend

        b = PlaywrightBackend({})
        page = MagicMock()
        page.url = "data:text/html,<title>t</title>"
        page.title = AsyncMock(return_value="t")
        page.go_back = AsyncMock(return_value=MagicMock())  # 非None=有历史
        page.go_forward = AsyncMock(return_value=MagicMock())
        page.reload = AsyncMock(return_value=MagicMock())
        page.wait_for_timeout = AsyncMock(return_value=None)
        page.wait_for_selector = AsyncMock(return_value=MagicMock())
        page.wait_for_load_state = AsyncMock(return_value=None)
        page.mouse = MagicMock()
        page.mouse.wheel = AsyncMock(return_value=None)
        page.keyboard = MagicMock()
        page.keyboard.press = AsyncMock(return_value=None)
        page.evaluate = AsyncMock(return_value={"x": 0, "y": 300})
        tab = {"page": page, "generation": 1}
        b._tabs = {"tab_t": tab}
        b._active_target_id = "tab_t"
        return b, page, tab

    @pytest.mark.asyncio
    async def test_goBackNavigatesAndBumpsGeneration(self):
        b, page, tab = self._backend()
        page.url = "http://x/b"

        async def fake_go_back():
            page.url = "http://x/a"  # 后退成功 = URL 变化
            return MagicMock()

        page.go_back = AsyncMock(side_effect=fake_go_back)
        result = await b.go_back()
        assert result.success and page.go_back.await_count == 1
        assert tab["generation"] == 2 and result.generation == 2

    @pytest.mark.asyncio
    async def test_goBackWithoutHistoryIsHonest(self):
        """无历史 = go_back 后 URL 不变（返回值不可靠：data: URL 成功导航也返回 None）"""
        b, page, _ = self._backend()
        page.url = "http://x/only"
        page.go_back = AsyncMock(return_value=MagicMock())
        result = await b.go_back()
        assert not result.success and "后退" in result.error

    @pytest.mark.asyncio
    async def test_goForwardNavigatesAndBumpsGeneration(self):
        b, page, tab = self._backend()
        page.url = "http://x/a"

        async def fake_go_forward():
            page.url = "http://x/b"
            return MagicMock()

        page.go_forward = AsyncMock(side_effect=fake_go_forward)
        result = await b.go_forward()
        assert result.success and page.go_forward.await_count == 1
        assert tab["generation"] == 2

    @pytest.mark.asyncio
    async def test_reloadBumpsGeneration(self):
        b, page, tab = self._backend()
        result = await b.reload_page()
        assert result.success and page.reload.await_count == 1
        assert tab["generation"] == 2

    @pytest.mark.asyncio
    async def test_waitMsUsesTimeoutCap(self):
        b, page, _ = self._backend()
        result = await b.wait_for(ms=999_999)  # 超上限须被夹到 30s，防呆不防君子
        assert result.success
        assert page.wait_for_timeout.await_args.args[0] == 30_000

    @pytest.mark.asyncio
    async def test_waitSelectorAndState(self):
        b, page, _ = self._backend()
        result = await b.wait_for(selector="#ok", state="networkidle", ms=1500)
        assert result.success
        assert page.wait_for_selector.await_args.args[0] == "#ok"
        page.wait_for_load_state.assert_awaited_once_with("networkidle")
        assert set(result.data["waited"]) == {"1500ms", "selector=#ok", "state=networkidle"}

    @pytest.mark.asyncio
    async def test_waitWithoutConditionRefuses(self):
        b, _, _ = self._backend()
        result = await b.wait_for()
        assert not result.success and "至少" in result.error

    @pytest.mark.asyncio
    async def test_scrollWheelsAndReportsPosition(self):
        b, page, _ = self._backend()
        result = await b.scroll_by(scroll_x=0, scroll_y=300)
        assert result.success
        page.mouse.wheel.assert_awaited_once_with(0, 300)
        assert result.data == {"x": 0, "y": 300}

    @pytest.mark.asyncio
    async def test_scrollAllZeroRefuses(self):
        b, _, _ = self._backend()
        result = await b.scroll_by(scroll_x=0, scroll_y=0)
        assert not result.success and "非零" in result.error

    @pytest.mark.asyncio
    async def test_pressKeyAndBumpsGeneration(self):
        b, page, tab = self._backend()
        result = await b.press_key("Enter", delay=120)
        assert result.success
        page.keyboard.press.assert_awaited_once_with("Enter", delay=120)
        assert tab["generation"] == 2

    @pytest.mark.asyncio
    async def test_pressEmptyKeyRefuses(self):
        b, _, _ = self._backend()
        result = await b.press_key("  ")
        assert not result.success and "key" in result.error


# ── 执行链路（fake manager） ─────────────────────────────

class FakeNavManager:
    def __init__(self):
        self.calls = []
        from neurova.computer_use.browser_manager import BrowserResult

        self._result = BrowserResult(success=True)

    def _mk(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        return self._result

    async def browser_back(self, generation=None):
        return self._mk("browser_back", generation=generation)

    async def browser_forward(self, generation=None):
        return self._mk("browser_forward", generation=generation)

    async def browser_reload(self, generation=None):
        return self._mk("browser_reload", generation=generation)

    async def browser_wait(self, ms=None, selector=None, state=None, generation=None):
        return self._mk("browser_wait", ms=ms, selector=selector, state=state, generation=generation)

    async def browser_scroll(self, scroll_x=0, scroll_y=0, generation=None):
        return self._mk("browser_scroll", scroll_x=scroll_x, scroll_y=scroll_y, generation=generation)

    async def browser_press(self, key, delay=None, generation=None):
        return self._mk("browser_press", key, delay=delay, generation=generation)


@pytest.fixture
def executor(monkeypatch):
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None

    async def fake_emit(self, tool_name, params, result, screenshot_base64=None):
        return None

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
    fake = FakeNavManager()
    monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: fake)
    return inst, fake


class TestExecutorWiring:
    @pytest.mark.asyncio
    async def test_backForwardsReloadNoArgs(self, executor):
        inst, fake = executor
        for tool, method in (
            ("browser_back", "_execute_browser_back"),
            ("browser_forward", "_execute_browser_forward"),
            ("browser_reload", "_execute_browser_reload"),
        ):
            result = await getattr(inst, method)({"generation": 2})
            assert result["success"] is True, tool
        assert [c[0] for c in fake.calls] == ["browser_back", "browser_forward", "browser_reload"]
        assert all(c[2].get("generation") == 2 for c in fake.calls)

    @pytest.mark.asyncio
    async def test_waitPassesTriple(self, executor):
        inst, fake = executor
        await inst._execute_browser_wait({"ms": 1500, "selector": "#ok", "state": "load"})
        assert fake.calls[0][0] == "browser_wait"
        kw = fake.calls[0][2]
        assert (kw["ms"], kw["selector"], kw["state"]) == (1500, "#ok", "load")

    @pytest.mark.asyncio
    async def test_waitWithoutAnyConditionRefuses(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_wait({})
        assert "error" in result and fake.calls == []

    @pytest.mark.asyncio
    async def test_scrollPassesDeltas(self, executor):
        inst, fake = executor
        await inst._execute_browser_scroll({"scroll_x": 0, "scroll_y": 300})
        assert fake.calls[0][0] == "browser_scroll"
        assert (fake.calls[0][2]["scroll_x"], fake.calls[0][2]["scroll_y"]) == (0, 300)

    @pytest.mark.asyncio
    async def test_scrollAllZeroRefuses(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_scroll({})
        assert "error" in result and fake.calls == []

    @pytest.mark.asyncio
    async def test_pressPassesKeyAndDelay(self, executor):
        inst, fake = executor
        await inst._execute_browser_press({"key": "Enter", "delay": 120})
        assert fake.calls[0][0] == "browser_press"
        assert fake.calls[0][1] == ("Enter",)
        assert fake.calls[0][2]["delay"] == 120

    @pytest.mark.asyncio
    async def test_pressRequiresKey(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_press({})
        assert "error" in result and fake.calls == []
