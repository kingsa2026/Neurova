# -*- coding: utf-8 -*-
"""browser_cookies/storage/console 三工具接线守卫（P2/P3 批C：页面状态面）。

cookies 走 BrowserContext（get/set/clear）；storage 走页面 localStorage/
sessionStorage（get/set/remove/clear）；console 读会话内 console/pageerror
事件环形缓冲。三者是登录态保持、页面态检查、排障读数的基础面。

重放轴口径：三者全部进 _NON_REPRODUCIBLE_TOOLS——cookies/storage 是写状态
（重放制造新状态），console 是瞬时缓冲读数（重放时缓冲可能已追加，与
screenshot 同属"只读也不可重放"反例族）。
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

NEW_TOOLS = ("browser_cookies", "browser_storage", "browser_console")


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

    def test_reproducibleAxisAllNonReproducible(self):
        from neurova.builtin_tools import _NON_REPRODUCIBLE_TOOLS

        missing = sorted(set(NEW_TOOLS) - set(_NON_REPRODUCIBLE_TOOLS))
        assert not missing, (
            f"cookies/storage 是状态写、console 是瞬时缓冲读数，均不可重放: {missing}"
        )

    def test_humanReadableActionDescription(self):
        assert "Cookie" in describe_computer_action("browser_cookies", {"action": "get"})
        assert "存储" in describe_computer_action("browser_storage", {"kind": "local"})
        assert "控制台" in describe_computer_action("browser_console", {})


class TestPlaywrightBackend:
    @staticmethod
    def _backend():
        from neurova.computer_use.browser_manager import PlaywrightBackend

        b = PlaywrightBackend({})
        page = MagicMock()
        page.url = "https://example.com/page"
        page.title = AsyncMock(return_value="t")
        page.evaluate = AsyncMock(return_value={"k": "v"})
        context = MagicMock()
        context.cookies = AsyncMock(return_value=[{"name": "a", "value": "1"}])
        context.add_cookies = AsyncMock(return_value=None)
        context.clear_cookies = AsyncMock(return_value=None)
        b._context = context
        tab = {"page": page, "generation": 1}
        b._tabs = {"tab_t": tab}
        b._active_target_id = "tab_t"
        return b, page, context, tab

    @pytest.mark.asyncio
    async def test_cookiesGetReturnsList(self):
        b, _, context, _ = self._backend()
        result = await b.cookies(action="get")
        assert result.success and result.data == [{"name": "a", "value": "1"}]
        context.cookies.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cookiesSetRequiresNameAndValue(self):
        b, _, context, _ = self._backend()
        result = await b.cookies(action="set", name="a", value="1", url="https://x.com")
        assert result.success
        context.add_cookies.assert_awaited_once()
        assert context.add_cookies.await_args.args[0] == [{"name": "a", "value": "1", "url": "https://x.com"}]
        missing = await b.cookies(action="set", name="a")
        assert not missing.success and "value" in missing.error

    @pytest.mark.asyncio
    async def test_cookiesClear(self):
        b, _, context, _ = self._backend()
        result = await b.cookies(action="clear")
        assert result.success and result.data == {"cleared": True}
        context.clear_cookies.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cookiesUnknownActionRefuses(self):
        b, _, _, _ = self._backend()
        result = await b.cookies(action="wipe")
        assert not result.success and "action" in result.error

    @pytest.mark.asyncio
    async def test_storageGetAllAndSet(self):
        b, page, _, tab = self._backend()
        got = await b.storage(kind="local", action="get")
        assert got.success and got.data == {"k": "v"}
        set_result = await b.storage(kind="local", action="set", key="k", value="v2")
        assert set_result.success
        args, _ = page.evaluate.await_args
        assert args[1] == ["local", "set", "k", "v2"]
        assert tab["generation"] == 2, "set 改页面态须使快照事实失效"

    @pytest.mark.asyncio
    async def test_storageSetRequiresKeyAndValue(self):
        b, _, _, _ = self._backend()
        result = await b.storage(kind="local", action="set", key="k")
        assert not result.success and "value" in result.error

    @pytest.mark.asyncio
    async def test_storageRemoveRequiresKey(self):
        b, _, _, _ = self._backend()
        result = await b.storage(kind="session", action="remove")
        assert not result.success and "key" in result.error

    @pytest.mark.asyncio
    async def test_storageUnknownKindRefuses(self):
        b, _, _, _ = self._backend()
        result = await b.storage(kind="cookie", action="get")
        assert not result.success and "kind" in result.error

    @pytest.mark.asyncio
    async def test_consoleReadsBufferWithLimit(self):
        b, _, _, _ = self._backend()
        b._consoleLog = [{"type": "console", "text": "a"}, {"type": "console", "text": "b"}, {"type": "pageerror", "text": "boom"}]
        result = await b.console_messages(limit=2)
        assert result.success
        assert [m["text"] for m in result.data] == ["b", "boom"], "取最近 limit 条"

    @pytest.mark.asyncio
    async def test_consoleEmptyBufferIsHonestEmpty(self):
        b, _, _, _ = self._backend()
        result = await b.console_messages()
        assert result.success and result.data == []


class FakeStateManager:
    def __init__(self):
        self.calls = []
        from neurova.computer_use.browser_manager import BrowserResult

        self._result = BrowserResult(success=True)

    async def browser_cookies(self, action="get", name=None, value=None, url=None, domain=None, path=None, generation=None):
        self.calls.append(("browser_cookies", action, name, value, url, domain, path, generation))
        return self._result

    async def browser_storage(self, kind="local", action="get", key=None, value=None, generation=None):
        self.calls.append(("browser_storage", kind, action, key, value, generation))
        return self._result

    async def browser_console(self, limit=50):
        self.calls.append(("browser_console", limit))
        return self._result


@pytest.fixture
def executor(monkeypatch):
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None

    async def fake_emit(self, tool_name, params, result, screenshot_base64=None):
        return None

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
    fake = FakeStateManager()
    monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: fake)
    return inst, fake


class TestExecutorWiring:
    @pytest.mark.asyncio
    async def test_cookiesPassesFields(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_cookies({"action": "set", "name": "a", "value": "1", "url": "https://x.com"})
        assert result["success"] is True
        assert fake.calls[0][:4] == ("browser_cookies", "set", "a", "1")

    @pytest.mark.asyncio
    async def test_cookiesRequiresAction(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_cookies({})
        assert "error" in result and fake.calls == []

    @pytest.mark.asyncio
    async def test_storagePassesFields(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_storage({"kind": "session", "action": "set", "key": "k", "value": "v"})
        assert result["success"] is True
        assert fake.calls[0][:5] == ("browser_storage", "session", "set", "k", "v")

    @pytest.mark.asyncio
    async def test_storageRequiresKindAndAction(self, executor):
        inst, fake = executor
        assert "error" in await inst._execute_browser_storage({"action": "get"})
        assert "error" in await inst._execute_browser_storage({"kind": "local"})
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_consolePassesLimit(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_console({"limit": 10})
        assert result["success"] is True
        assert fake.calls[0] == ("browser_console", 10)
