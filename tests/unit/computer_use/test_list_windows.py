"""P2-6（ZCode 电脑操控对照评测）：computer_list_windows 窗口枚举工具。

ZCode 有 list_windows/list_apps 应用/窗口枚举面；Neurova 此前只能靠 dom_snapshot
按标题猜窗口。补 computer_list_windows（UIA 枚举顶层窗口，只读）+
窗口管理 docstring 诚实化（包声明里"窗口管理-模拟实现"是无实现的自述，删）。
"""

from unittest.mock import MagicMock

import pytest

from neurova.tool_executor import ToolExecutor


class TestRegistration:
    def test_tool_registered(self):
        from neurova.builtin_tools import get_registered_tool_names

        assert "computer_list_windows" in get_registered_tool_names()

    def test_in_computer_use_tool_set(self):
        from neurova.tool_executor import COMPUTER_USE_TOOLS

        assert "computer_list_windows" in COMPUTER_USE_TOOLS

    def test_readonly_low_risk(self):
        from neurova.computer_use.runtime_policy import classify_risk

        assert classify_risk("computer_list_windows") == "low"

    def test_param_whitelist_empty(self):
        from neurova.tool_executor import _COMPUTER_TOOL_PARAM_KEYS

        assert _COMPUTER_TOOL_PARAM_KEYS["computer_list_windows"] == frozenset()


class _StubUia:
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


def _executor():
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None
    return inst


@pytest.fixture
def quiet_emit(monkeypatch):
    async def fake_emit(self, *a, **k):
        return None

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)


class TestExecutor:
    @pytest.mark.asyncio
    async def test_list_windows_dispatch(self, monkeypatch, quiet_emit):
        monkeypatch.setattr(ToolExecutor, "_desktop_uia", lambda self: _StubUia())
        out = await _executor()._execute_builtin_tool("computer_list_windows", {})
        assert out["success"] is True and out["count"] == 2
        assert out["windows"][0]["title"] == "记事本"

    @pytest.mark.asyncio
    async def test_unavailable_refused(self, monkeypatch, quiet_emit):
        from neurova.computer_use.desktop_uia import DesktopUIAManager

        monkeypatch.setattr(
            ToolExecutor, "_desktop_uia", lambda self: DesktopUIAManager(backend=None)
        )
        out = await _executor()._execute_builtin_tool("computer_list_windows", {})
        assert out["success"] is False
        assert out.get("action_result", {}).get("refusal_code") == "unsupported_method"


class TestRemoteProxy:
    def test_remote_manager_proxies_list_windows(self):
        from neurova.computer_use.remote_backend import RemoteComputerUseManager

        class FakeClient:
            def action(self, kind, params=None):
                assert kind == "list_windows"
                return {"success": True, "count": 1, "windows": [{"title": "w"}]}

        out = RemoteComputerUseManager(FakeClient()).list_windows()
        assert out["success"] is True


class TestGuestAgent:
    def test_guest_action_list_windows(self):
        from fastapi.testclient import TestClient

        from neurova.guest_agent.server import create_app

        class StubUia:
            def list_windows(self, limit=50):
                return {"success": True, "count": 0, "windows": []}

        app = create_app(manager=object(), uia_manager=StubUia(), token=None)
        client = TestClient(app)
        r = client.post("/action", json={"kind": "list_windows", "params": {}})
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestDocstringHonesty:
    def test_no_fake_window_management_claim(self):
        """包 docstring 曾声称"窗口管理-模拟实现"——全包无任何窗口管理实现。

        现补了窗口**枚举**（list_windows），声明必须跟事实走：不得再写"模拟实现"。
        """
        import neurova.computer_use as cu

        doc = cu.__doc__ or ""
        assert "模拟实现" not in doc, "包 docstring 不得保留虚假的模拟实现声明"
        assert "list_windows" in doc, "包 docstring 应如实声明窗口枚举能力"
