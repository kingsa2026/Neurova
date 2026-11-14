# -*- coding: utf-8 -*-
"""browser_tab_* 四工具 + browser_eval 接线守卫（P1 断点收口）。

## 背景

多标签页管理（`BrowserManager.open_target/list_targets/switch_target/close_target`，
`browser_manager.py` PlaywrightBackend）与页面脚本执行（`execute_js`，同文件
`PlaywrightBackend.execute_js`）在底层早已实装，`ComputerUseManager` 也有
`browser_open_target` 等包装，但 LLM 工具面只登记了 12 个 `browser_*` 工具——
**模型看不到 tab 管理与 eval**，属于"底层有能力、工具面断线"的断点。

## 本文件钉住的面

| 面 | 落点 |
|----|------|
| schema 面 | `builtin_tools._BUILTIN_SCHEMAS` |
| 派生面 | `tool_executor.ToolExecutor._builtin_dispatch` |
| 治理面 | `tool_executor.COMPUTER_USE_TOOLS` |
| 参数面 | `tool_executor._COMPUTER_TOOL_PARAM_KEYS` |
| 权限面 | `skills.permissions.tool_categories`（network 类，漏登记走"未归类即放行"） |
| 能力声明 | `agent.tool_coordinator.resolveToolCapability` |
| 行为链路 | `_execute_browser_tab_*` / `_execute_browser_eval` → ComputerUseManager 包装 |

`browser_eval` 执行任意页面 JS，属任意命令执行语义（`arbitrary_command` 高危档），
与 `computer_shell` 同档声明。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from neurova.computer_use import ComputerUseManager
from neurova.computer_use.browser_manager import BrowserResult
from neurova.tool_executor import (
    _COMPUTER_TOOL_PARAM_KEYS,
    COMPUTER_USE_TOOLS,
    ToolExecutor,
    describe_computer_action,
)

NEW_TOOLS = (
    "browser_tab_open",
    "browser_tab_list",
    "browser_tab_switch",
    "browser_tab_close",
    "browser_eval",
)


# ── 五面登记 ──────────────────────────────────────────────

class TestToolFaces:
    def test_schemasRegistered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        missing = [n for n in NEW_TOOLS if n not in _BUILTIN_SCHEMAS]
        assert not missing, f"schema 面缺登记（模型看不到）: {missing}"

    def test_dispatchable(self):
        missing = [n for n in NEW_TOOLS if n not in ToolExecutor._builtin_dispatch]
        assert not missing, f"派生面缺登记（调用走'未知工具'回落）: {missing}"

    def test_inGovernanceSurface(self):
        missing = [n for n in NEW_TOOLS if n not in COMPUTER_USE_TOOLS]
        assert not missing, f"治理面缺登记（参数准入/审计/事件被跳过）: {missing}"

    def test_paramKeysDeclared(self):
        missing = [n for n in NEW_TOOLS if n not in _COMPUTER_TOOL_PARAM_KEYS]
        assert not missing, f"参数面缺登记（未知键被无声放行）: {missing}"

    def test_paramKeysMatchSchemaProperties(self):
        """参数白名单与 schema properties 逐名一致（双向：不多不少）。"""
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        for name in NEW_TOOLS:
            props = set(_BUILTIN_SCHEMAS[name]["parameters"].get("properties", {}))
            declared = set(_COMPUTER_TOOL_PARAM_KEYS[name])
            assert declared == props, f"{name} 参数面 {sorted(declared)} != schema 面 {sorted(props)}"

    def test_permissionCategoryNetwork(self):
        """browser_* 同族归 network 类；漏登记会被 allows_tool 的'未归类即放行'放走。"""
        from neurova.skills.permissions import tool_categories

        unclassified = [n for n in NEW_TOOLS if "network" not in tool_categories(n)]
        assert not unclassified, f"权限面未归类（会走未归类即放行）: {unclassified}"

    def test_capabilityDeclared(self):
        from neurova.agent.tool_coordinator import resolveToolCapability

        undeclared = [n for n in NEW_TOOLS if resolveToolCapability(n) is None]
        assert not undeclared, f"未声明并行能力（按串行处置且无从审计）: {undeclared}"

    def test_evalDeclaresArbitraryCommand(self):
        """browser_eval 是任意 JS 执行语义，必须进 arbitrary_command 高危档。"""
        from neurova.builtin_tools import get_builtin_tool_flags

        flags = get_builtin_tool_flags("browser_eval")
        assert flags.get("arbitrary_command") is True, (
            "browser_eval 未声明 arbitrary_command——任意 JS 执行必须与 computer_shell 同档受裁决面约束"
        )

    def test_tabToolsNotInteractiveDesktop(self):
        """tab 管理不改变共享桌面画面，不进动作后补拍面（与既有 browser_* 同口径）。"""
        from neurova.builtin_tools import get_builtin_tool_flags

        for name in ("browser_tab_open", "browser_tab_switch", "browser_tab_close"):
            assert get_builtin_tool_flags(name).get("interactive_desktop") is not True

    def test_humanReadableActionDescription(self):
        """新工具的动作描述必须是人话，不许回落成裸工具名。"""
        assert "标签页" in describe_computer_action("browser_tab_open", {"url": "http://x"})
        assert "标签页" in describe_computer_action("browser_tab_list", {})
        assert "切换" in describe_computer_action("browser_tab_switch", {"target_id": "tab_ab12"})
        assert "关闭" in describe_computer_action("browser_tab_close", {"target_id": "tab_ab12"})
        assert "脚本" in describe_computer_action("browser_eval", {"script": "1+1"})


# ── ComputerUseManager 包装层 ─────────────────────────────

class TestManagerWrappers:
    def test_browserExecuteJsWrapperExists(self):
        assert hasattr(ComputerUseManager, "browser_execute_js"), (
            "ComputerUseManager 缺 browser_execute_js 包装——browser_eval 无从落地"
        )


# ── 执行链路（fake manager，不打真浏览器） ─────────────────

class FakeBrowserManager:
    """记录调用并回放预设 BrowserResult（与 ComputerUseManager 包装同名的方法）。"""

    def __init__(self, result=None):
        self._result = result or BrowserResult(success=True)
        self.calls = []

    async def browser_open_target(self, url=None):
        self.calls.append(("browser_open_target", url))
        return self._result

    async def browser_list_targets(self):
        self.calls.append(("browser_list_targets",))
        return self._result

    async def browser_switch_target(self, target_id, generation=None):
        self.calls.append(("browser_switch_target", target_id, generation))
        return self._result

    async def browser_close_target(self, target_id, generation=None):
        self.calls.append(("browser_close_target", target_id, generation))
        return self._result

    async def browser_execute_js(self, script):
        self.calls.append(("browser_execute_js", script))
        return self._result


@pytest.fixture
def executor(monkeypatch):
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None

    async def fake_emit(self, tool_name, params, result, screenshot_base64=None):
        return None

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)

    import neurova.tool_executor as te

    async def noop_sleep(delay):
        return None

    monkeypatch.setattr(te.asyncio, "sleep", noop_sleep)
    return inst


def _install(executor, monkeypatch, result=None):
    fake = FakeBrowserManager(result)
    monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: fake)
    return fake


class TestTabToolBehaviors:
    @pytest.mark.asyncio
    async def test_tabOpenPassesUrlAndNormalizes(self, executor, monkeypatch):
        raw = BrowserResult(success=True, data={"target_id": "tab_ab12", "generation": 1}, url="http://x")
        fake = _install(executor, monkeypatch, raw)
        result = await executor._execute_browser_tab_open({"url": "http://x"})
        assert fake.calls == [("browser_open_target", "http://x")]
        assert result["success"] is True
        assert result["data"]["target_id"] == "tab_ab12"

    @pytest.mark.asyncio
    async def test_tabOpenWithoutUrlPassesNone(self, executor, monkeypatch):
        fake = _install(executor, monkeypatch)
        await executor._execute_browser_tab_open({})
        assert fake.calls == [("browser_open_target", None)]

    @pytest.mark.asyncio
    async def test_tabListNormalized(self, executor, monkeypatch):
        raw = BrowserResult(success=True, data=[{"target_id": "tab_ab12", "active": True}])
        fake = _install(executor, monkeypatch, raw)
        result = await executor._execute_browser_tab_list({})
        assert fake.calls == [("browser_list_targets",)]
        assert result["data"][0]["target_id"] == "tab_ab12"

    @pytest.mark.asyncio
    async def test_tabSwitchPassesTargetAndGeneration(self, executor, monkeypatch):
        fake = _install(executor, monkeypatch)
        await executor._execute_browser_tab_switch({"target_id": "tab_ab12", "generation": 3})
        assert fake.calls == [("browser_switch_target", "tab_ab12", 3)]

    @pytest.mark.asyncio
    async def test_tabSwitchRequiresTargetId(self, executor, monkeypatch):
        fake = _install(executor, monkeypatch)
        result = await executor._execute_browser_tab_switch({})
        assert "error" in result and fake.calls == []

    @pytest.mark.asyncio
    async def test_tabClosePassesTargetAndGeneration(self, executor, monkeypatch):
        fake = _install(executor, monkeypatch)
        await executor._execute_browser_tab_close({"target_id": "tab_ab12", "generation": 2})
        assert fake.calls == [("browser_close_target", "tab_ab12", 2)]

    @pytest.mark.asyncio
    async def test_tabCloseRequiresTargetId(self, executor, monkeypatch):
        fake = _install(executor, monkeypatch)
        result = await executor._execute_browser_tab_close({})
        assert "error" in result and fake.calls == []


class TestEvalBehavior:
    @pytest.mark.asyncio
    async def test_evalPassesScriptAndNormalizes(self, executor, monkeypatch):
        raw = BrowserResult(success=True, data="42")
        fake = _install(executor, monkeypatch, raw)
        result = await executor._execute_browser_eval({"script": "1+1"})
        assert fake.calls == [("browser_execute_js", "1+1")]
        assert result["success"] is True and result["data"] == "42"

    @pytest.mark.asyncio
    async def test_evalRequiresScript(self, executor, monkeypatch):
        fake = _install(executor, monkeypatch)
        result = await executor._execute_browser_eval({})
        assert "error" in result and fake.calls == []

    @pytest.mark.asyncio
    async def test_evalFailureIsHonest(self, executor, monkeypatch):
        raw = BrowserResult(success=False, error="SyntaxError: unexpected token")
        _install(executor, monkeypatch, raw)
        result = await executor._execute_browser_eval({"script": "((("})
        assert result["success"] is False
        assert "SyntaxError" in result.get("error", "")
