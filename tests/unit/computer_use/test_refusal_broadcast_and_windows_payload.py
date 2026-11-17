"""增强项②③（ZCode 电脑操控对照评测收尾）：

② 门控拒绝（前台互斥 controller_busy / 运行档 sandbox_session_required /
审核 permission_required）也广播 computer_action——分屏面板看得见"为什么没动"，
不再只有模型知道。与 stale_frame（帧权威拒绝，已在执行体内广播）同一面。
③ computer_list_windows 的事件载荷携带 windows 清单——前端窗口表格的数据源。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.tool_executor import ToolExecutor


def _executor(session_id: str = "sess-cua") -> ToolExecutor:
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = session_id
    inst._agent._current_user_id = "u1"
    return inst


def _capture_sync(broadcasted: list):
    fake_sync = MagicMock()
    fake_sync.register_or_create_session = MagicMock()
    fake_sync.broadcast_event = AsyncMock(side_effect=lambda sid, ev: broadcasted.append(ev))
    return fake_sync


def _payloads(broadcasted: list) -> list:
    return [ev.to_dict()["payload"] for ev in broadcasted]


@pytest.fixture(autouse=True)
def isolated_sessions(monkeypatch):
    from neurova.core import turn_context as tc

    monkeypatch.setattr(tc, "_session_id_var", tc.ContextVar("t_sess", default=None))


class TestGateRefusalBroadcast:
    @pytest.mark.asyncio
    async def test_controller_busy_refusal_broadcasts(self, monkeypatch):
        """它会话持有前台租约时的拒绝必须广播——面板显示"另一会话正在操控"。"""
        from neurova.core import turn_context as tc

        entered = asyncio.Event()

        async def slow_click(self, params):
            entered.set()
            await asyncio.sleep(0.05)
            return {"success": True}

        monkeypatch.setattr(ToolExecutor, "_execute_computer_click", slow_click)
        broadcasted = []
        fake_sync = _capture_sync(broadcasted)

        tc._session_id_var.set("s1")
        e1 = _executor()
        with patch("neurova.sync.session_sync_manager.get_session_sync_manager", return_value=fake_sync):
            task1 = asyncio.ensure_future(
                e1._execute_builtin_tool("computer_click", {"x": 1, "y": 2})
            )
            await entered.wait()
            tc._session_id_var.set("s2")
            out2 = await _executor()._execute_builtin_tool("computer_click", {"x": 3, "y": 4})
            await task1

        assert out2["success"] is False
        busy = [
            p
            for p in _payloads(broadcasted)
            if p.get("action_result", {}).get("refusal_code") == "controller_busy"
        ]
        assert busy, "controller_busy 拒绝未广播到 computer_action 通道"
        assert busy[0]["tool"] == "computer_click"
        assert busy[0]["success"] is False
        assert "前台输入" in busy[0]["error"]

    @pytest.mark.asyncio
    async def test_sandbox_gate_refusal_broadcasts(self, monkeypatch):
        """运行档门拒绝（无沙箱会话）也广播——与帧权威拒绝同面。"""
        from neurova.computer_use import runtime_policy as rp

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "sandbox")
        monkeypatch.setattr("neurova.computer_use.get_active_remote_desktop", lambda: None)
        broadcasted = []
        fake_sync = _capture_sync(broadcasted)

        with patch("neurova.sync.session_sync_manager.get_session_sync_manager", return_value=fake_sync):
            out = await _executor()._execute_builtin_tool("computer_click", {"x": 1, "y": 2})

        assert out["success"] is False
        payloads = _payloads(broadcasted)
        assert any(
            p.get("action_result", {}).get("refusal_code") == "sandbox_session_required"
            for p in payloads
        ), f"运行档门拒绝未广播：{[p.get('tool') for p in payloads]}"

    @pytest.mark.asyncio
    async def test_approval_pending_refusal_broadcasts(self, monkeypatch):
        """审核档待批也广播（面板与审批 SSE 双通道可见）。"""

        class _Req:
            request_id = "appr-live-1"

        class _Mgr:
            def create_approval_request(self, **kwargs):
                return _Req()

        monkeypatch.setattr(
            "neurova.security.approval_manager.get_approval_manager", lambda: _Mgr()
        )
        from neurova.computer_use import runtime_policy as rp

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "review")
        broadcasted = []
        fake_sync = _capture_sync(broadcasted)

        with patch("neurova.sync.session_sync_manager.get_session_sync_manager", return_value=fake_sync):
            out = await _executor()._execute_builtin_tool("computer_click", {"x": 1, "y": 2})

        assert out.get("pending_approval") is True
        payloads = _payloads(broadcasted)
        assert any(
            p.get("action_result", {}).get("refusal_code") == "permission_required"
            for p in payloads
        ), "审核待批拒绝未广播"


class TestWindowsPayload:
    @pytest.mark.asyncio
    async def test_list_windows_event_carries_windows(self, monkeypatch):
        """增强③：窗口清单进 computer_action 载荷（前端窗口表格数据源）。"""

        class StubUia:
            def list_windows(self):
                return {
                    "success": True,
                    "count": 2,
                    "windows": [
                        {"title": "记事本", "class_name": "Notepad", "pid": 1, "hwnd": 10,
                         "rect": {"x": 0, "y": 0, "w": 800, "h": 600}, "focused": True},
                        {"title": "浏览器", "class_name": "Chrome", "pid": 2, "hwnd": 11,
                         "rect": {"x": 0, "y": 0, "w": 800, "h": 600}, "focused": False},
                    ],
                }

        inst = _executor()
        monkeypatch.setattr(ToolExecutor, "_desktop_uia", lambda self: StubUia())
        broadcasted = []
        fake_sync = _capture_sync(broadcasted)

        with patch("neurova.sync.session_sync_manager.get_session_sync_manager", return_value=fake_sync):
            out = await inst._execute_builtin_tool("computer_list_windows", {})

        assert out["success"] is True
        payloads = _payloads(broadcasted)
        assert payloads, "list_windows 未广播事件"
        windows = payloads[0].get("windows")
        assert isinstance(windows, list) and len(windows) == 2
        assert windows[0]["title"] == "记事本" and windows[0]["focused"] is True

    @pytest.mark.asyncio
    async def test_other_tools_payload_has_no_windows_key(self, monkeypatch):
        """载荷键按需出现：非窗口工具的广播不带 windows 键（不掺噪音）。"""

        def fake_click(manager, x, y, button="left"):
            return {"success": True, "x": x, "y": y}

        monkeypatch.setattr("neurova.computer_use.actions.click_screenshot_point", fake_click)
        monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: MagicMock())

        async def no_refresh(self, *a, **k):
            return None

        monkeypatch.setattr(ToolExecutor, "_emit_action_refreshed_screenshot", no_refresh)
        broadcasted = []
        fake_sync = _capture_sync(broadcasted)

        with patch("neurova.sync.session_sync_manager.get_session_sync_manager", return_value=fake_sync):
            await _executor()._execute_builtin_tool("computer_click", {"x": 1, "y": 2})

        payloads = _payloads(broadcasted)
        assert payloads and "windows" not in payloads[0]
