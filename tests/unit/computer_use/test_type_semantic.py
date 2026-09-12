"""R2-1 type_text 语义化（CUA 升级方案 Phase 2，OCU 智能输入契约）

病根（修复前）：computer_type = pyautogui.typewrite 盲打——焦点在哪打哪。

验收：
- 存在 focused 可编辑控件（ValuePattern）→ 直接对当前值追加写入
  （route=uia, delivery=background, evidence=value_readback），不走全局键入
- 无 focused 可编辑 → 回退 pyautogui 路径（诚实标注 global_input/foreground）
- ValuePattern 写失败（无回读）→ 回退 pyautogui
- 管理器侧：type_text_semantic 无目标返回 None（让执行方裁决回退）
"""

from unittest.mock import MagicMock

import pytest

from neurova.computer_use import desktop_uia


def make_editable(value=""):
    return {
        "role": "edit",
        "name": "输入框",
        "rect": (10, 10, 100, 20),
        "enabled": True,
        "value": value,
        "focused": True,
        "settable": True,
        "invokable": False,
        "togglable": False,
        "expandable": False,
        "legacy_default": False,
        "runtime_id": "9.1",
    }


class FakeBackend:
    """与真实后端同契约；get_focused_editable 可控"""

    def __init__(self, focused=None):
        self.focused = focused
        self.calls = []

    def available(self):
        return True

    def get_window(self, window_title=None):
        return {"title": "记事本", "rect": (0, 0, 800, 600), "pid": 1, "hwnd": 1}

    def walk(self, window, max_nodes, max_depth):
        return []

    def get_focused_editable(self):
        self.calls.append("get_focused_editable")
        return self.focused

    def set_value(self, element, value):
        self.calls.append(("set_value", element["runtime_id"], value))
        return value

    def invoke(self, element):
        return False


class TestTypeSemantic:
    def test_appends_to_current_value(self):
        backend = FakeBackend(focused=make_editable(value="你好"))
        mgr = desktop_uia.DesktopUIAManager(backend=backend)
        result = mgr.type_text_semantic("世界")
        assert result is not None and result["success"] is True
        assert ("set_value", "9.1", "你好世界") in backend.calls, "语义输入=对当前值追加"
        assert result["action_result"] == {
            "route": "uia",
            "effect": "confirmed",
            "delivery": "background",
            "evidence": ["value_readback"],
        }

    def test_empty_current_value(self):
        backend = FakeBackend(focused=make_editable(value=""))
        mgr = desktop_uia.DesktopUIAManager(backend=backend)
        result = mgr.type_text_semantic("abc")
        assert result is not None
        assert ("set_value", "9.1", "abc") in backend.calls

    def test_no_focused_editable_returns_none(self):
        mgr = desktop_uia.DesktopUIAManager(backend=FakeBackend(focused=None))
        assert mgr.type_text_semantic("x") is None

    def test_set_failure_returns_none_for_fallback(self):
        backend = FakeBackend(focused=make_editable(value=""))
        backend.set_value = lambda element, value: None  # ValuePattern 写失败
        mgr = desktop_uia.DesktopUIAManager(backend=backend)
        assert mgr.type_text_semantic("x") is None

    def test_unavailable_backend_returns_none(self):
        mgr = desktop_uia.DesktopUIAManager(backend=None)
        assert mgr.type_text_semantic("x") is None


class TestExecutorIntegration:
    @pytest.mark.asyncio
    async def test_semantic_route_skips_pyautogui(self, monkeypatch):
        """有语义目标时绝不调用全局键入（不抢焦点路径优先）"""
        from neurova.tool_executor import ToolExecutor

        pyautogui_calls = []

        class FakeCUManager:
            def type_text(self, text, interval=0.05):
                pyautogui_calls.append(text)
                return True

            def screenshot(self, region=None):
                return b"png"

        fake_uia = MagicMock()
        fake_uia.type_text_semantic = lambda text: {
            "success": True,
            "action_result": {
                "route": "uia", "effect": "confirmed",
                "delivery": "background", "evidence": ["value_readback"],
            },
        }
        import neurova.computer_use as cu
        import neurova.computer_use.desktop_uia as du

        monkeypatch.setattr(cu, "get_computer_use_manager", lambda: FakeCUManager())
        monkeypatch.setattr(du, "get_desktop_uia_manager", lambda: fake_uia)

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None})()
        emit_calls = []

        async def fake_emit(self, *args, **kwargs):
            emit_calls.append(args)

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)

        async def noop_sleep(d):
            return None

        import neurova.tool_executor as te

        monkeypatch.setattr(te.asyncio, "sleep", noop_sleep)

        result = await inst._execute_computer_type({"text": "hello"})
        assert result["success"] is True
        assert result["action_result"]["route"] == "uia"
        assert pyautogui_calls == [], "语义路径不得触达全局键入"

    @pytest.mark.asyncio
    async def test_fallback_when_no_semantic_target(self, monkeypatch):
        from neurova.tool_executor import ToolExecutor

        typed = []

        class FakeCUManager:
            def type_text(self, text, interval=0.05):
                typed.append(text)
                return True

            def screenshot(self, region=None):
                return b"png"

        import neurova.computer_use as cu
        import neurova.computer_use.desktop_uia as du

        monkeypatch.setattr(cu, "get_computer_use_manager", lambda: FakeCUManager())
        monkeypatch.setattr(du, "get_desktop_uia_manager", lambda: MagicMock(type_text_semantic=lambda t: None))

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None})()

        async def fake_emit(self, *args, **kwargs):
            return None

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)

        async def noop_sleep(d):
            return None

        import neurova.tool_executor as te

        monkeypatch.setattr(te.asyncio, "sleep", noop_sleep)

        result = await inst._execute_computer_type({"text": "fallback"})
        assert result["success"] is True
        assert typed == ["fallback"]
        assert result["action_result"]["route"] == "global_input"
