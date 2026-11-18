"""P2-7（电脑操控对照评测）：computer_key / computer_paste / computer_drag。

对齐参照系 CUA 的 key（组合键+repeat）/ paste（剪贴板写入+粘贴）/ left_click_drag
三动词——Neurova 桌面面此前缺组合键、剪贴板与拖拽。
"""

from unittest.mock import MagicMock

import pytest

from neurova.tool_executor import ToolExecutor


class RecordingManager:
    def __init__(self):
        self.calls = []

    def press_key(self, key, repeat=1, interval=0.05):
        self.calls.append(("press_key", key, repeat, interval))
        return True

    def paste_text(self, text):
        self.calls.append(("paste_text", text))
        return True

    def drag(self, sx, sy, ex, ey, duration=0.5, button="left"):
        self.calls.append(("drag", sx, sy, ex, ey, duration, button))
        return True


def _executor():
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None
    return inst


@pytest.fixture
def quiet(monkeypatch):
    async def fake_emit(self, *a, **k):
        return None

    async def fake_refresh(self, *a, **k):
        return None

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
    monkeypatch.setattr(ToolExecutor, "_emit_action_refreshed_screenshot", fake_refresh)


class TestRegistration:
    def test_tools_registered(self):
        from neurova.builtin_tools import get_registered_tool_names

        for name in ("computer_key", "computer_paste", "computer_drag"):
            assert name in get_registered_tool_names(), name

    def test_medium_risk(self):
        from neurova.computer_use.runtime_policy import classify_risk

        for name in ("computer_key", "computer_paste", "computer_drag"):
            assert classify_risk(name) == "medium", name

    def test_param_whitelists(self):
        from neurova.tool_executor import _COMPUTER_TOOL_PARAM_KEYS

        assert _COMPUTER_TOOL_PARAM_KEYS["computer_key"] == frozenset(
            {"key", "repeat", "interval"}
        )
        assert _COMPUTER_TOOL_PARAM_KEYS["computer_paste"] == frozenset({"text"})
        assert _COMPUTER_TOOL_PARAM_KEYS["computer_drag"] == frozenset(
            {"start_x", "start_y", "end_x", "end_y", "duration", "button"}
        )


class TestDispatch:
    @pytest.mark.asyncio
    async def test_key_dispatch(self, monkeypatch, quiet):
        mgr = RecordingManager()
        monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: mgr)
        out = await _executor()._execute_builtin_tool("computer_key", {"key": "ctrl+s"})
        assert out["success"] is True
        assert mgr.calls[0][:2] == ("press_key", "ctrl+s")

    @pytest.mark.asyncio
    async def test_paste_dispatch(self, monkeypatch, quiet):
        mgr = RecordingManager()
        monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: mgr)
        out = await _executor()._execute_builtin_tool("computer_paste", {"text": "你好"})
        assert out["success"] is True
        assert mgr.calls[0][:2] == ("paste_text", "你好")

    @pytest.mark.asyncio
    async def test_drag_dispatch(self, monkeypatch, quiet):
        mgr = RecordingManager()
        monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: mgr)
        out = await _executor()._execute_builtin_tool(
            "computer_drag",
            {"start_x": 1, "start_y": 2, "end_x": 30, "end_y": 40},
        )
        assert out["success"] is True
        assert mgr.calls[0][0] == "drag"
        assert mgr.calls[0][1:5] == (1, 2, 30, 40)

    @pytest.mark.asyncio
    async def test_drag_missing_params_refused(self, monkeypatch, quiet):
        mgr = RecordingManager()
        monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: mgr)
        out = await _executor()._execute_builtin_tool("computer_drag", {"start_x": 1})
        assert out.get("success") is not True
        assert "error" in out
        assert not mgr.calls, "缺参不得触达管理器"


class TestManagerKey:
    def test_chord_normalizes_aliases(self, monkeypatch):
        """cmd→win 别名归一；组合键走 hotkey。"""
        from neurova.computer_use import ComputerUseManager

        calls = []
        monkeypatch.setattr("pyautogui.hotkey", lambda *k: calls.append(k))
        assert ComputerUseManager().press_key("cmd+shift+s") is True
        assert calls and calls[0] == ("win", "shift", "s")

    def test_single_key_uses_press(self, monkeypatch):
        from neurova.computer_use import ComputerUseManager

        calls = []
        monkeypatch.setattr("pyautogui.press", lambda k, **kw: calls.append((k, kw)))
        assert ComputerUseManager().press_key("enter", repeat=3, interval=0.01) is True
        assert calls and calls[0][0] == "enter"

    def test_unknown_key_refused(self):
        from neurova.computer_use import ComputerUseManager

        assert ComputerUseManager().press_key("no_such_key_xyz") is False
        assert ComputerUseManager().press_key("") is False

    def test_key_aliases_single_source(self):
        from neurova.computer_use import KEY_ALIASES

        assert KEY_ALIASES["cmd"] == "win"
        assert KEY_ALIASES["esc"] == "escape"


class TestManagerPaste:
    def test_paste_writes_clipboard_then_ctrl_v(self, monkeypatch):
        from neurova.computer_use import ComputerUseManager

        wrote = {}
        hot = []
        monkeypatch.setattr(
            ComputerUseManager, "_setClipboardText", staticmethod(lambda t: wrote.setdefault("t", t) or True)
        )
        monkeypatch.setattr("pyautogui.hotkey", lambda *k: hot.append(k))
        assert ComputerUseManager().paste_text("hello") is True
        assert wrote["t"] == "hello"
        assert hot and hot[0] == ("ctrl", "v")

    def test_paste_clipboard_failure_aborts(self, monkeypatch):
        from neurova.computer_use import ComputerUseManager

        monkeypatch.setattr(
            ComputerUseManager, "_setClipboardText", staticmethod(lambda t: False)
        )
        assert ComputerUseManager().paste_text("x") is False

    def test_paste_empty_text_refused(self):
        from neurova.computer_use import ComputerUseManager

        assert ComputerUseManager().paste_text("") is False


class TestManagerDrag:
    def test_drag_converts_and_drags(self, monkeypatch):
        from neurova.computer_use import ComputerUseManager

        mgr = ComputerUseManager()
        seq = []

        def fake_convert(px, py):
            seq.append((px, py))
            return (px * 2, py * 2)

        moved = []
        monkeypatch.setattr(mgr, "convert_screenshot_point", fake_convert)
        monkeypatch.setattr("pyautogui.moveTo", lambda x, y: moved.append(("move", x, y)))
        monkeypatch.setattr(
            "pyautogui.dragTo",
            lambda x, y, duration=0.5, button="left": moved.append(("drag", x, y, button)),
        )
        assert mgr.drag(10, 20, 30, 40, duration=0.2) is True
        assert moved[0] == ("move", 20, 40)
        assert moved[1] == ("drag", 60, 80, "left")

    def test_drag_bad_button_refused(self):
        from neurova.computer_use import ComputerUseManager

        assert ComputerUseManager().drag(1, 2, 3, 4, button="up") is False


class TestRemoteAndGuest:
    def test_remote_manager_proxies_three_verbs(self):
        from neurova.computer_use.remote_backend import RemoteComputerUseManager

        seen = []

        class FakeClient:
            def action(self, kind, params=None):
                seen.append((kind, params))
                return {"success": True}

        m = RemoteComputerUseManager(FakeClient())
        assert m.press_key("enter") is True
        assert m.paste_text("t") is True
        assert m.drag(1, 2, 3, 4) is True
        assert [s[0] for s in seen] == ["key", "paste", "drag"]

    def test_guest_agent_handles_three_verbs(self):
        from fastapi.testclient import TestClient

        from neurova.guest_agent.server import create_app

        app = create_app(manager=RecordingManager(), uia_manager=object(), token=None)
        client = TestClient(app)
        for kind, params in (
            ("key", {"key": "enter"}),
            ("paste", {"text": "t"}),
            ("drag", {"start_x": 1, "start_y": 2, "end_x": 3, "end_y": 4}),
        ):
            r = client.post("/action", json={"kind": kind, "params": params})
            assert r.status_code == 200 and r.json().get("success") is True, kind
