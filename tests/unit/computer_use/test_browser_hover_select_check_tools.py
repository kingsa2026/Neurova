# -*- coding: utf-8 -*-
"""browser_hover/select/check 三工具接线守卫（P2 批B：元素交互扩展）。

role+name 定位协议（与 click_role/fill_role 同构）补齐三类高频交互：
悬停（hover 触发菜单/提示）、下拉选择（select_option）、勾选/取消（check/uncheck）。

重放轴口径：select/check 是页面写操作（同 fill_role 轴，重放可能选错/改状态）
⇒ 不可重现；hover 同参数同效果（悬停同一元素，无 DOM 突变）⇒ 可重现。
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

NEW_TOOLS = ("browser_hover", "browser_select", "browser_check")
NON_REPRODUCIBLE = {"browser_select", "browser_check"}


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
        from neurova.builtin_tools import _NON_REPRODUCIBLE_TOOLS

        leaked = sorted(NON_REPRODUCIBLE - set(_NON_REPRODUCIBLE_TOOLS))
        assert not leaked, f"页面写操作漏出不可重现名单: {leaked}"
        assert "browser_hover" not in _NON_REPRODUCIBLE_TOOLS, (
            "hover 同参数同效果（悬停同一元素，无 DOM 突变），属可重现"
        )

    def test_humanReadableActionDescription(self):
        assert "悬停" in describe_computer_action("browser_hover", {"role": "button"})
        assert "选择" in describe_computer_action("browser_select", {"role": "combobox"})
        assert "勾选" in describe_computer_action("browser_check", {"role": "checkbox"})


class TestPlaywrightBackend:
    @staticmethod
    def _backend():
        from neurova.computer_use.browser_manager import PlaywrightBackend

        b = PlaywrightBackend({})
        page = MagicMock()
        page.url = "data:text/html,<title>t</title>"
        page.title = AsyncMock(return_value="t")
        locator = MagicMock()
        locator.hover = AsyncMock(return_value=None)
        locator.select_option = AsyncMock(return_value=["a"])
        locator.check = AsyncMock(return_value=None)
        locator.uncheck = AsyncMock(return_value=None)
        page.get_by_role = MagicMock(return_value=locator)
        tab = {"page": page, "generation": 1}
        b._tabs = {"tab_t": tab}
        b._active_target_id = "tab_t"
        return b, page, locator, tab

    @pytest.mark.asyncio
    async def test_hoverUsesRoleLocatorAndBumpsGeneration(self):
        b, page, locator, tab = self._backend()
        result = await b.hover_role("button", name="登录", generation=1)
        assert result.success and result.route == "playwright_role"
        page.get_by_role.assert_called_once_with("button", name="登录")
        locator.hover.assert_awaited_once()
        assert tab["generation"] == 2

    @pytest.mark.asyncio
    async def test_hoverMissingRoleRefuses(self):
        b, _, _, _ = self._backend()
        result = await b.hover_role("  ")
        assert not result.success and "role" in result.error

    @pytest.mark.asyncio
    async def test_selectPassesValues(self):
        b, page, locator, _ = self._backend()
        result = await b.select_role("combobox", ["bj", "sh"], name="城市", generation=1)
        assert result.success
        page.get_by_role.assert_called_once_with("combobox", name="城市")
        locator.select_option.assert_awaited_once()
        args, kwargs = locator.select_option.await_args
        assert list(args[0]) == ["bj", "sh"]
        assert result.data["selected"] == ["bj", "sh"]

    @pytest.mark.asyncio
    async def test_selectRequiresValues(self):
        b, _, _, _ = self._backend()
        result = await b.select_role("combobox", [])
        assert not result.success and "values" in result.error

    @pytest.mark.asyncio
    async def test_checkTrueChecksFalseUnchecks(self):
        b, page, locator, _ = self._backend()
        result = await b.check_role("checkbox", True, name="同意", generation=1)
        assert result.success and result.data["checked"] is True
        locator.check.assert_awaited_once()
        result2 = await b.check_role("checkbox", False, name="同意")
        assert result2.success and result2.data["checked"] is False
        locator.uncheck.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_staleGenerationRefusesBeforeAnyAction(self):
        b, page, locator, _ = self._backend()
        result = await b.hover_role("button", generation=99)
        assert not result.success and result.data.get("stale") is True
        locator.hover.assert_not_awaited()


class FakeInteractionManager:
    def __init__(self):
        self.calls = []
        from neurova.computer_use.browser_manager import BrowserResult

        self._result = BrowserResult(success=True, route="playwright_role")

    async def browser_hover(self, role, name=None, generation=None):
        self.calls.append(("browser_hover", role, name, generation))
        return self._result

    async def browser_select(self, role, values, name=None, generation=None):
        self.calls.append(("browser_select", role, list(values), name, generation))
        return self._result

    async def browser_check(self, role, checked, name=None, generation=None):
        self.calls.append(("browser_check", role, checked, name, generation))
        return self._result


@pytest.fixture
def executor(monkeypatch):
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None

    async def fake_emit(self, tool_name, params, result, screenshot_base64=None):
        return None

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
    fake = FakeInteractionManager()
    monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: fake)
    return inst, fake


class TestExecutorWiring:
    @pytest.mark.asyncio
    async def test_hoverPassesRoleNameGeneration(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_hover({"role": "button", "name": "登录", "generation": 2})
        assert result["success"] is True
        assert fake.calls[0] == ("browser_hover", "button", "登录", 2)

    @pytest.mark.asyncio
    async def test_selectPassesValuesList(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_select({"role": "combobox", "values": ["bj"], "name": "城市"})
        assert result["success"] is True
        assert fake.calls[0] == ("browser_select", "combobox", ["bj"], "城市", None)

    @pytest.mark.asyncio
    async def test_selectRequiresValues(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_select({"role": "combobox"})
        assert "error" in result and fake.calls == []

    @pytest.mark.asyncio
    async def test_checkPassesBool(self, executor):
        inst, fake = executor
        await inst._execute_browser_check({"role": "checkbox", "checked": True, "name": "同意"})
        assert fake.calls[0] == ("browser_check", "checkbox", True, "同意", None)

    @pytest.mark.asyncio
    async def test_checkRequiresRoleAndChecked(self, executor):
        inst, fake = executor
        assert "error" in await inst._execute_browser_check({"checked": True})
        assert "error" in await inst._execute_browser_check({"role": "checkbox"})
        assert fake.calls == []
