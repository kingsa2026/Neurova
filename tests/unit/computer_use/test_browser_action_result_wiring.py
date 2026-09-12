"""R1-2 接线：BrowserResult 后端自报 route → tool_executor 归一化附加 action_result

- PlaywrightBackend click_role/navigate 与 CamofoxServerBackend click_role 在
  BrowserResult 上自报 route（知识在后端，不在消费方）
- _normalize_browser_result 消费 derive_from_browser_result：成功→confirmed、
  失败→精确拒绝码；历史路径（无 route）不附加（不编造）
- computer_click/type/scroll（pyautogui 全局输入）→ unverifiable + foreground 诚实档
"""

from unittest.mock import MagicMock

import pytest

from neurova.computer_use.browser_manager import BrowserResult
from neurova.tool_executor import ToolExecutor


@pytest.fixture
def executor(monkeypatch):
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None

    emit_calls = []

    async def fake_emit(self, tool_name, params, result, screenshot_base64=None):
        emit_calls.append(result)

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)

    async def noop_sleep(delay):
        return None

    import neurova.tool_executor as te

    monkeypatch.setattr(te.asyncio, "sleep", noop_sleep)
    return inst, emit_calls


class FakeBrowser:
    def __init__(self, result):
        self._result = result

    async def browser_click_role(self, role, name=None, generation=None):
        return self._result


class TestBrowserWiring:
    @pytest.mark.asyncio
    async def test_click_role_success_gets_action_result(self, executor, monkeypatch):
        inst, emit_calls = executor
        raw = BrowserResult(success=True, route="playwright_role", url="http://x")
        monkeypatch.setattr(
            "neurova.computer_use.get_computer_use_manager", lambda: FakeBrowser(raw)
        )
        result = await inst._execute_browser_click_role({"role": "button", "name": "登录"})
        ar = result.get("action_result")
        assert ar and ar["effect"] == "confirmed" and ar["route"] == "playwright_role"
        assert emit_calls[0].get("action_result") == ar, "事件 payload 携带契约"

    @pytest.mark.asyncio
    async def test_click_role_ref_not_found_gets_refusal(self, executor, monkeypatch):
        inst, _ = executor
        raw = BrowserResult(success=False, route="camofox_ref", error="快照中未找到 role='button' 的可交互元素")
        monkeypatch.setattr(
            "neurova.computer_use.get_computer_use_manager", lambda: FakeBrowser(raw)
        )
        result = await inst._execute_browser_click_role({"role": "button"})
        assert result["action_result"]["refusal_code"] == "ref_not_found"

    def test_legacy_result_without_route_untouched(self):
        inst = ToolExecutor.__new__(ToolExecutor)
        normalized = inst._normalize_browser_result(BrowserResult(success=True, url="http://x"))
        assert "action_result" not in normalized


class TestPyautoguiHonesty:
    @pytest.mark.asyncio
    async def test_computer_click_is_unverifiable_foreground(self, executor, monkeypatch):
        """pyautogui 点击无回执 → unverifiable + foreground（诚实档，非假 confirmed）"""

        class FakeManager:
            def click_screenshot_point(self, x, y, button="left"):
                return True

            def screenshot(self, region=None):
                return b"png"

        monkeypatch.setattr(
            "neurova.computer_use.get_computer_use_manager", lambda: FakeManager()
        )
        inst, _ = executor
        result = await inst._execute_computer_click({"x": 5, "y": 6})
        ar = result["action_result"]
        assert ar == {
            "route": "global_input",
            "effect": "unverifiable",
            "delivery": "foreground",
        }


def _coro(value):
    import asyncio

    async def _inner():
        return value

    return _inner()
