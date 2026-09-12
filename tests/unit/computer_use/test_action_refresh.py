"""R0-3 动作后自动回传刷新截图（CUA 升级方案 Phase 0）

病根（修复前）：computer_click/type/scroll 只回元数据，agent 想看结果必须
再调一次 computer_screenshot（多一轮 LLM 往返，容易放弃观察直接盲操作）。

验收（OCU 动作即观察契约，保持截图双通道——base64 只走 WS 旁路）：
- 成功动作后自动补拍并追加一条带 refreshed=True + screenshot 的事件
- LLM 结果只带轻量标记 refreshed_screenshot=True，绝不携带 base64
- 失败动作不触发刷新
"""

import sys
from unittest.mock import MagicMock

import pytest

from neurova.tool_executor import ToolExecutor

FAKE_PNG_B64 = "ZmFrZS1wbmc="  # base64("fake-png")


class FakeManager:
    """忠实契约的替身：click_screenshot_point/type_text 同步、screenshot 同步返回 PNG 字节"""

    def __init__(self, fail=False):
        self.fail = fail
        self.screenshot_calls = 0

    def click_screenshot_point(self, x, y, button="left"):
        return not self.fail

    def type_text(self, text, interval=0.05):
        return not self.fail

    def scroll(self, x, y, clicks, horizontal_clicks=0):
        return not self.fail

    def screenshot(self, region=None):
        self.screenshot_calls += 1
        return b"fake-png"


@pytest.fixture
def executor(monkeypatch):
    """不跑 __init__ 的 ToolExecutor（不依赖完整 Agent），打桩 emit 与 manager"""
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None  # None → 真实 emit 直接短路，本测试换成桩

    emit_calls = []

    async def fake_emit(self, tool_name, params, result, screenshot_base64=None):
        emit_calls.append({"tool": tool_name, "result": dict(result), "shot": screenshot_base64})

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)

    async def noop_sleep(delay):
        return None

    monkeypatch.setattr(
        __import__("neurova.tool_executor", fromlist=["asyncio"]).asyncio,
        "sleep",
        noop_sleep,
    )

    fake_manager = FakeManager()
    monkeypatch.setattr(
        "neurova.computer_use.get_computer_use_manager", lambda: fake_manager
    )
    return inst, emit_calls, fake_manager


class TestActionRefresh:
    @pytest.mark.asyncio
    async def test_click_success_emits_refreshed_screenshot(self, executor):
        inst, emit_calls, fake_manager = executor
        result = await inst._execute_computer_click({"x": 10, "y": 20})

        assert result.get("refreshed_screenshot") is True
        assert "base64" not in str(result), "LLM 结果不得携带 base64"
        assert fake_manager.screenshot_calls == 1, "成功动作后自动补拍一次"
        assert len(emit_calls) == 2, "原始事件 + 刷新事件"
        original, refreshed = emit_calls
        assert original["shot"] is None
        assert refreshed["shot"] == FAKE_PNG_B64
        assert refreshed["result"].get("refreshed") is True

    @pytest.mark.asyncio
    async def test_click_failure_skips_refresh(self, executor):
        inst, emit_calls, fake_manager = executor
        fake_manager.fail = True
        result = await inst._execute_computer_click({"x": 10, "y": 20})

        assert "refreshed_screenshot" not in result
        assert fake_manager.screenshot_calls == 0, "失败动作不补拍"
        assert len(emit_calls) == 1

    @pytest.mark.asyncio
    async def test_type_success_refreshes(self, executor):
        inst, emit_calls, _ = executor
        result = await inst._execute_computer_type({"text": "hello"})
        assert result.get("refreshed_screenshot") is True
        assert len(emit_calls) == 2 and emit_calls[1]["shot"] == FAKE_PNG_B64

    @pytest.mark.asyncio
    async def test_scroll_success_refreshes(self, executor):
        inst, emit_calls, _ = executor
        result = await inst._execute_computer_scroll({"scroll_x": 0, "scroll_y": 3})
        assert result.get("refreshed_screenshot") is True
        assert len(emit_calls) == 2 and emit_calls[1]["shot"] == FAKE_PNG_B64

    @pytest.mark.asyncio
    async def test_refresh_silent_on_screenshot_error(self, executor, monkeypatch):
        """补拍失败不得影响动作主结果"""
        inst, emit_calls, fake_manager = executor

        def broken_screenshot(region=None):
            raise RuntimeError("no screen")

        fake_manager.screenshot = broken_screenshot
        result = await inst._execute_computer_click({"x": 1, "y": 2})
        assert result.get("success") is True
        assert "error" not in result
