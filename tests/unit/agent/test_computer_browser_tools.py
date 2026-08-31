"""电脑操作 / 浏览器操作内置工具单元测试

覆盖：
1. browser_* 工具 schema 注册（LLM 工具列表单一事实源）
2. ToolExecutor 的 browser_* 执行器（委托 ComputerUseManager → BrowserManager）
3. computer/browser 工具执行后的 computer_action 实时事件广播（驱动前端分屏面板）
4. 截图类工具不把 base64 大对象塞进 LLM/会话消息（上下文膨胀防护）
5. /computer/* REST 端点接入真实 ComputerUseManager（替换占位符）
6. console.py SSE 工具事件构造
"""

import importlib.util
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.builtin_tools import BuiltinToolRegistry, _BUILTIN_SCHEMAS
from neurova.tool_executor import ToolExecutor


BROWSER_TOOLS = (
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_screenshot",
    "browser_extract_text",
    "browser_dom_snapshot",
    "browser_click_role",
    "browser_fill_role",
)

DESKTOP_TOOLS = ("computer_screenshot", "computer_click", "computer_type", "computer_scroll", "computer_shell")


def _make_browser_result(success=True, **kwargs):
    """构造 BrowserResult 形状的对象（与 neurova.computer_use.browser_manager.BrowserResult 对齐）"""
    from types import SimpleNamespace

    result = SimpleNamespace(
        success=success,
        data=kwargs.get("data"),
        error=kwargs.get("error"),
        screenshot=kwargs.get("screenshot"),
        url=kwargs.get("url"),
        title=kwargs.get("title"),
        duration_ms=1.0,
        to_dict=lambda: {
            "success": success,
            "data": kwargs.get("data"),
            "error": kwargs.get("error"),
            "has_screenshot": kwargs.get("screenshot") is not None,
            "url": kwargs.get("url"),
            "title": kwargs.get("title"),
            "duration_ms": 1.0,
        },
    )
    return result


@pytest.fixture
def executor():
    agent = MagicMock()
    agent.current_session_id = "sess-abc"  # P3-c 收窄：tool_executor 经显式 property 读取
    return ToolExecutor(agent), agent


@pytest.fixture
def fake_mgr():
    mgr = MagicMock()
    mgr.browser_navigate = AsyncMock(return_value=_make_browser_result(url="https://example.com", title="Example"))
    mgr.browser_screenshot = AsyncMock(
        return_value=_make_browser_result(url="https://example.com", title="Example", screenshot="QUJD")
    )
    mgr.browser_click = AsyncMock(return_value=_make_browser_result(url="https://example.com"))
    mgr.browser_type = AsyncMock(return_value=_make_browser_result(url="https://example.com"))
    mgr.browser_extract_text = AsyncMock(return_value=_make_browser_result(data="页面正文内容"))
    mgr.browser_dom_snapshot = AsyncMock(
        return_value=_make_browser_result(url="https://example.com", data='- button "登录"\n- textbox "用户名"')
    )
    mgr.browser_click_role = AsyncMock(return_value=_make_browser_result(url="https://example.com"))
    mgr.browser_fill_role = AsyncMock(return_value=_make_browser_result(url="https://example.com"))
    return mgr


class TestBrowserToolSchemas:
    """browser_* schema 注册即对 LLM 可见"""

    def test_browser_schemas_registered(self):
        for name in BROWSER_TOOLS:
            assert name in _BUILTIN_SCHEMAS, f"{name} 未注册 schema"
            assert _BUILTIN_SCHEMAS[name].get("description"), f"{name} 缺少描述"

    def test_desktop_schemas_still_registered(self):
        for name in DESKTOP_TOOLS:
            assert name in _BUILTIN_SCHEMAS

    def test_registry_exposes_openai_format(self):
        registry = BuiltinToolRegistry.__new__(BuiltinToolRegistry)
        registry._tools = {}
        from neurova.builtin_tools import BuiltinTool

        for name, spec in _BUILTIN_SCHEMAS.items():
            registry._tools[name] = BuiltinTool(
                name=name, description=spec["description"], parameters=spec["parameters"]
            )
        names = {t["function"]["name"] for t in registry.get_openai_tools()}
        assert set(BROWSER_TOOLS) <= names

    def test_navigate_schema_requires_url(self):
        params = _BUILTIN_SCHEMAS["browser_navigate"]["parameters"]
        assert "url" in params.get("required", [])


class TestBrowserToolExecution:
    @pytest.mark.asyncio
    async def test_navigate_delegates_to_manager(self, executor, fake_mgr):
        exe, _ = executor
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            result = await exe._execute_builtin_tool("browser_navigate", {"url": "https://example.com"})

        fake_mgr.browser_navigate.assert_awaited_once_with("https://example.com")
        assert result["success"] is True
        assert result["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_navigate_requires_url(self, executor):
        exe, _ = executor
        result = await exe._execute_builtin_tool("browser_navigate", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_click_with_text_fallback_selector(self, executor, fake_mgr):
        exe, _ = executor
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            await exe._execute_builtin_tool("browser_click", {"text": "登录"})
        # 仅提供 text 时应转成 playwright 的 text= 选择器
        fake_mgr.browser_click.assert_awaited_once_with("text=登录")

    @pytest.mark.asyncio
    async def test_click_requires_target(self, executor):
        exe, _ = executor
        result = await exe._execute_builtin_tool("browser_click", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_type_delegates(self, executor, fake_mgr):
        exe, _ = executor
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            result = await exe._execute_builtin_tool(
                "browser_type", {"selector": "#username", "text": "alice"}
            )
        fake_mgr.browser_type.assert_awaited_once_with("#username", "alice")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_type_requires_selector_and_text(self, executor):
        exe, _ = executor
        assert "error" in await exe._execute_builtin_tool("browser_type", {"selector": "#a"})
        assert "error" in await exe._execute_builtin_tool("browser_type", {"text": "hi"})

    @pytest.mark.asyncio
    async def test_extract_text_returns_data(self, executor, fake_mgr):
        exe, _ = executor
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            result = await exe._execute_builtin_tool("browser_extract_text", {})
        assert result["success"] is True
        assert result["data"] == "页面正文内容"

    @pytest.mark.asyncio
    async def test_backend_error_propagates(self, executor, fake_mgr):
        exe, _ = executor
        fake_mgr.browser_navigate = AsyncMock(
            return_value=_make_browser_result(success=False, error="No browser backend available")
        )
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            result = await exe._execute_builtin_tool("browser_navigate", {"url": "https://x.com"})
        assert result["success"] is False
        assert "backend" in result.get("error", "")


class TestAriaRoleTools:
    """可访问性快照 + role 定位工具（观察优先协议的执行层契约）"""

    @pytest.mark.asyncio
    async def test_dom_snapshot_returns_tree(self, executor, fake_mgr):
        exe, _ = executor
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            result = await exe._execute_builtin_tool("browser_dom_snapshot", {})
        assert result["success"] is True
        assert 'button "登录"' in result["data"]

    @pytest.mark.asyncio
    async def test_dom_snapshot_truncates_long_tree(self, executor, fake_mgr):
        exe, _ = executor
        fake_mgr.browser_dom_snapshot = AsyncMock(return_value=_make_browser_result(data="x" * 9000))
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            result = await exe._execute_builtin_tool("browser_dom_snapshot", {})
        assert result["truncated"] is True
        assert len(result["data"]) <= 8010

    @pytest.mark.asyncio
    async def test_click_role_delegates_with_name(self, executor, fake_mgr):
        exe, _ = executor
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            result = await exe._execute_builtin_tool("browser_click_role", {"role": "button", "name": "登录"})
        fake_mgr.browser_click_role.assert_awaited_once_with("button", "登录", generation=None)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_click_role_requires_role(self, executor):
        exe, _ = executor
        result = await exe._execute_builtin_tool("browser_click_role", {"name": "登录"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fill_role_delegates(self, executor, fake_mgr):
        exe, _ = executor
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            result = await exe._execute_builtin_tool(
                "browser_fill_role", {"role": "textbox", "name": "用户名", "text": "uitest"}
            )
        fake_mgr.browser_fill_role.assert_awaited_once_with("textbox", "用户名", "uitest", generation=None)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_fill_role_requires_text(self, executor):
        exe, _ = executor
        result = await exe._execute_builtin_tool("browser_fill_role", {"role": "textbox", "name": "搜索"})
        assert "error" in result


class TestScreenshotContextSafety:
    """截图结果不得把 base64 塞进 LLM 面向的工具消息（防止上下文/存储膨胀）"""

    @pytest.mark.asyncio
    async def test_computer_screenshot_compact_result(self, executor):
        exe, _ = executor
        fake_mgr = MagicMock()
        fake_mgr.screenshot = MagicMock(return_value=b"\x89PNG-fake")
        with (
            patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr),
            patch.object(ToolExecutor, "_emit_computer_event", new_callable=AsyncMock) as emit,
        ):
            result = await exe._execute_single_tool("computer_screenshot", {})

        assert result["success"] is True
        assert "image_base64" not in json.dumps(result)
        # 完整截图经事件通道发给前端
        emit.assert_called_once()
        assert emit.call_args.kwargs.get("screenshot_base64") or emit.call_args.args

    @pytest.mark.asyncio
    async def test_browser_screenshot_compact_result(self, executor, fake_mgr):
        exe, _ = executor
        with (
            patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr),
            patch.object(ToolExecutor, "_emit_computer_event", new_callable=AsyncMock) as emit,
        ):
            result = await exe._execute_single_tool("browser_screenshot", {})

        assert result["success"] is True
        dumped = json.dumps(result, default=str)
        assert "QUJD" not in dumped  # base64 不进工具消息
        assert result.get("url") == "https://example.com"


class TestComputerActionBroadcast:
    """电脑/浏览器操作实时广播 computer_action 事件（驱动聊天页分屏）"""

    @pytest.mark.asyncio
    async def test_broadcast_on_desktop_action(self, executor):
        exe, agent = executor
        fake_mgr = MagicMock()
        fake_mgr.click = MagicMock(return_value=True)
        broadcasted = []

        fake_sync = MagicMock()
        fake_sync.register_or_create_session = MagicMock()
        fake_sync.broadcast_event = AsyncMock(side_effect=lambda sid, ev: broadcasted.append(ev))

        with (
            patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr),
            patch("neurova.sync.session_sync_manager.get_session_sync_manager", return_value=fake_sync),
        ):
            await exe._execute_single_tool("computer_click", {"x": 100, "y": 200})

        assert len(broadcasted) == 1
        event = broadcasted[0]
        payload = event.to_dict()["payload"]
        assert payload["tool"] == "computer_click"
        assert payload["params"] == {"x": 100, "y": 200}
        assert payload["success"] is True
        assert event.to_dict()["event_type"] == "computer_action"
        assert event.to_dict()["session_id"] == "sess-abc"

    @pytest.mark.asyncio
    async def test_broadcast_carries_screenshot(self, executor, fake_mgr):
        exe, _ = executor
        broadcasted = []
        fake_sync = MagicMock()
        fake_sync.register_or_create_session = MagicMock()
        fake_sync.broadcast_event = AsyncMock(side_effect=lambda sid, ev: broadcasted.append(ev))

        with (
            patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr),
            patch("neurova.sync.session_sync_manager.get_session_sync_manager", return_value=fake_sync),
        ):
            await exe._execute_single_tool("browser_screenshot", {})

        assert len(broadcasted) == 1
        payload = broadcasted[0].to_dict()["payload"]
        assert payload["screenshot"] == "QUJD"

    @pytest.mark.asyncio
    async def test_no_session_no_crash(self, executor, fake_mgr):
        exe, agent = executor
        agent.current_session_id = None
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            result = await exe._execute_single_tool("browser_navigate", {"url": "https://x.com"})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_broadcast_failure_does_not_break_tool(self, executor, fake_mgr):
        exe, _ = executor
        fake_sync = MagicMock()
        fake_sync.register_or_create_session = MagicMock()
        fake_sync.broadcast_event = AsyncMock(side_effect=RuntimeError("ws down"))

        with (
            patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr),
            patch("neurova.sync.session_sync_manager.get_session_sync_manager", return_value=fake_sync),
        ):
            result = await exe._execute_single_tool("browser_navigate", {"url": "https://x.com"})
        assert result["success"] is True

    def test_computer_action_event_type_registered(self):
        from neurova.sync.session_sync_manager import EventType

        assert EventType.COMPUTER_ACTION.value == "computer_action"


class TestPlaywrightDetection:
    """HAS_PLAYWRIGHT 必须真实探测，不得恒为 True（否则无 Playwright 环境误报可用）"""

    def test_flag_matches_environment(self):
        from neurova.computer_use import browser_manager

        installed = importlib.util.find_spec("playwright") is not None
        assert browser_manager.HAS_PLAYWRIGHT == installed

    def test_status_reflects_backends(self):
        from neurova.computer_use.browser_manager import BrowserManager

        status = BrowserManager().get_status()
        assert isinstance(status["available_backends"], list)


class TestComputerRestEndpoints:
    """/computer/* REST 端点必须走真实 ComputerUseManager（替换占位符实现）"""

    @pytest.mark.asyncio
    async def test_screenshot_endpoint_real_backend(self):
        from neurova.api.endpoints.computer import ScreenshotRequest, screenshot

        fake_mgr = MagicMock()
        fake_mgr.screenshot = MagicMock(return_value=b"\x89PNG-data")
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            resp = await screenshot(ScreenshotRequest())

        assert resp["code"] == 0
        assert resp["data"]["base64"]  # 非 placeholder 空串
        fake_mgr.screenshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_click_endpoint_real_backend(self):
        from neurova.api.endpoints.computer import ClickRequest, click

        fake_mgr = MagicMock()
        fake_mgr.click = MagicMock(return_value=True)
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            resp = await click(ClickRequest(x=10, y=20))

        assert resp["code"] == 0
        fake_mgr.click.assert_called_once_with(10, 20, "left")

    @pytest.mark.asyncio
    async def test_browser_navigate_endpoint_real_backend(self):
        from neurova.api.endpoints.computer import BrowserNavigateRequest, browser_navigate

        fake_mgr = MagicMock()
        fake_mgr.browser_navigate = AsyncMock(
            return_value=_make_browser_result(url="https://example.com", title="Example")
        )
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            resp = await browser_navigate(
                BrowserNavigateRequest(url="https://example.com"),
                current_user={"user_id": "1", "username": "test"},
            )

        assert resp["code"] == 0
        assert resp["data"].get("title") == "Example"

    @pytest.mark.asyncio
    async def test_status_endpoint_reports_availability(self):
        from neurova.api.endpoints.computer import get_status

        resp = await get_status()
        assert resp["code"] == 0
        # 状态必须来自真实探测，而非硬编码 False 占位
        assert "desktop_available" in resp["data"]
        assert "browser_backends" in resp["data"]


class TestBrowserExecuteEndpoint:
    """POST /browser/execute 命令总线：判别联合严格 schema + 单一入口分发"""

    def test_schema_rejects_unknown_command(self):
        import pydantic

        from neurova.api.endpoints import computer

        with pytest.raises(pydantic.ValidationError):
            computer.BrowserCommandAdapter.validate_python({"command": "hack_the_planet"})

    def test_schema_rejects_extra_fields(self):
        import pydantic

        from neurova.api.endpoints import computer

        with pytest.raises(pydantic.ValidationError) as exc:
            computer.BrowserCommandAdapter.validate_python({"command": "click_role", "role": "button", "bogus": 1})
        assert "extra_forbidden" in str(exc.value)

    def test_schema_rejects_missing_required_field(self):
        import pydantic

        from neurova.api.endpoints import computer

        with pytest.raises(pydantic.ValidationError):
            computer.BrowserCommandAdapter.validate_python({"command": "navigate"})  # 缺 url

    @pytest.mark.asyncio
    async def test_execute_dispatches_navigate(self):
        from neurova.api.endpoints import computer

        fake_mgr = MagicMock()
        fake_mgr.browser_navigate = AsyncMock(
            return_value=_make_browser_result(url="https://example.com", title="Example")
        )
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            cmd = computer.BrowserCommandAdapter.validate_python({"command": "navigate", "url": "https://example.com"})
            resp = await computer.browser_execute(cmd, current_user={"user_id": "1"})

        assert resp["code"] == 0
        fake_mgr.browser_navigate.assert_awaited_once_with("https://example.com", generation=None)

    @pytest.mark.asyncio
    async def test_execute_dispatches_click_role_with_generation(self):
        from neurova.api.endpoints import computer

        fake_mgr = MagicMock()
        fake_mgr.browser_click_role = AsyncMock(return_value=_make_browser_result(url="https://example.com"))
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            cmd = computer.BrowserCommandAdapter.validate_python(
                {"command": "click_role", "role": "button", "name": "登录", "generation": 3}
            )
            resp = await computer.browser_execute(cmd, current_user={"user_id": "1"})

        assert resp["code"] == 0
        fake_mgr.browser_click_role.assert_awaited_once_with("button", "登录", generation=3)

    @pytest.mark.asyncio
    async def test_execute_dispatches_dom_snapshot(self):
        from neurova.api.endpoints import computer

        fake_mgr = MagicMock()
        fake_mgr.browser_dom_snapshot = AsyncMock(
            return_value=_make_browser_result(url="https://example.com", data='- button "x"')
        )
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            cmd = computer.BrowserCommandAdapter.validate_python({"command": "dom_snapshot"})
            resp = await computer.browser_execute(cmd, current_user={"user_id": "1"})

        assert resp["code"] == 0
        assert resp["data"]["data"] == '- button "x"'
        fake_mgr.browser_dom_snapshot.assert_awaited_once_with(generation=None)

    @pytest.mark.asyncio
    async def test_execute_dispatches_list_targets(self):
        from neurova.api.endpoints import computer

        fake_mgr = MagicMock()
        fake_mgr.browser_list_targets = AsyncMock(
            return_value=_make_browser_result(data=[{"target_id": "t1", "generation": 1, "active": True}])
        )
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            cmd = computer.BrowserCommandAdapter.validate_python({"command": "list_targets"})
            resp = await computer.browser_execute(cmd, current_user={"user_id": "1"})

        assert resp["code"] == 0
        assert resp["data"]["data"][0]["target_id"] == "t1"

    @pytest.mark.asyncio
    async def test_execute_dispatches_switch_target(self):
        from neurova.api.endpoints import computer

        fake_mgr = MagicMock()
        fake_mgr.browser_switch_target = AsyncMock(return_value=_make_browser_result(url="https://b.com"))
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            cmd = computer.BrowserCommandAdapter.validate_python(
                {"command": "switch_target", "target_id": "t2", "generation": 4}
            )
            resp = await computer.browser_execute(cmd, current_user={"user_id": "1"})

        assert resp["code"] == 0
        fake_mgr.browser_switch_target.assert_awaited_once_with("t2", 4)

    @pytest.mark.asyncio
    async def test_execute_failure_raises_502(self):
        from fastapi import HTTPException

        from neurova.api.endpoints import computer

        fake_mgr = MagicMock()
        fake_mgr.browser_click_role = AsyncMock(
            return_value=_make_browser_result(success=False, error="target generation 过期")
        )
        with patch("neurova.computer_use.get_computer_use_manager", return_value=fake_mgr):
            cmd = computer.BrowserCommandAdapter.validate_python({"command": "click_role", "role": "button"})
            with pytest.raises(HTTPException) as exc:
                await computer.browser_execute(cmd, current_user={"user_id": "1"})

        assert exc.value.status_code == 502


class TestConsoleSSEToolEvents:
    """console.py SSE 工具事件构造：tool_result 携带 name，审批事件独立"""

    def test_tool_call_event_has_name_and_arguments(self):
        from neurova.api.endpoints.console import _build_tool_events

        events = _build_tool_events({"type": "tool_call", "tool_name": "computer_click", "params": {"x": 1}})
        call_events = [e for e in events if e["type"] == "tool_call"]
        assert len(call_events) == 1
        assert call_events[0]["name"] == "computer_click"
        assert json.loads(call_events[0]["arguments"]) == {"x": 1}

    def test_tool_result_event_has_name(self):
        from neurova.api.endpoints.console import _build_tool_events

        events = _build_tool_events({"type": "tool_result", "tool_name": "web_search", "result": "ok"})
        result_events = [e for e in events if e["type"] == "tool_result"]
        assert len(result_events) == 1
        assert result_events[0]["name"] == "web_search"
        assert result_events[0]["result"] == "ok"

    def test_pending_approval_emits_approval_event(self):
        from neurova.api.endpoints.console import _build_tool_events

        tm = {
            "type": "tool_result",
            "tool_name": "computer_shell",
            "result": json.dumps(
                {"pending_approval": True, "approval_id": "ap-1", "tool_name": "computer_shell", "params": {}}
            ),
        }
        events = _build_tool_events(tm)
        approvals = [e for e in events if e["type"] == "approval_required"]
        assert len(approvals) == 1
        assert approvals[0]["approval_id"] == "ap-1"

    def test_heavy_base64_not_leaked_into_sse(self):
        from neurova.api.endpoints.console import _build_tool_events

        big = "A" * 100000
        tm = {"type": "tool_result", "tool_name": "t", "result": json.dumps({"image_base64": big, "ok": True})}
        events = _build_tool_events(tm)
        raw = json.dumps(events, ensure_ascii=False)
        assert big not in raw
