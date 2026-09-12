"""R0-1 scroll 方向单源根修（CUA 升级方案 Phase 0）

病根（修复前）：
- HTTP /v1/computer/scroll 用 abs(int(dy)) 丢弃符号 → dy=-3（向下）被翻转成向上
- agent 路径 scroll_x（水平）整体被忽略 → 水平滚动永远不发生
- 两处消费方各自拼换算，语义漂移无单源

验收：
- scroll_semantics 纯函数保留符号：正 y=上、负 y=下、正 x=右、负 x=左
- 两轴全 0 时回退默认档（保持旧行为）
- ComputerUseManager.scroll 新签名向后兼容（不传 horizontal_clicks 行为不变）
- 水平滚动走 pyautogui.hscroll
"""

import sys
from unittest.mock import MagicMock

import pytest

from neurova.computer_use import scroll_semantics


class TestScrollSemantics:
    def test_positive_y_is_up(self):
        """正 scroll_y = 向上（pyautogui.scroll 正=上 同向）"""
        vertical, horizontal = scroll_semantics(0, 3)
        assert (vertical, horizontal) == (3, 0)

    def test_negative_y_is_down_keeps_sign(self):
        """负 scroll_y 必须保留符号向下——修复前 abs() 会翻转成向上（根因）"""
        vertical, horizontal = scroll_semantics(0, -3)
        assert (vertical, horizontal) == (-3, 0)

    def test_positive_x_is_right(self):
        vertical, horizontal = scroll_semantics(5, 0)
        assert (vertical, horizontal) == (0, 5)

    def test_negative_x_is_left_keeps_sign(self):
        vertical, horizontal = scroll_semantics(-5, 0)
        assert (vertical, horizontal) == (0, -5)

    def test_both_zero_falls_back_to_default(self):
        """两轴全 0 回退默认档（旧行为：int(dy) or 3 → 3）"""
        vertical, horizontal = scroll_semantics(0, 0)
        assert (vertical, horizontal) == (3, 0)
        vertical, horizontal = scroll_semantics(0, 0, default_clicks=5)
        assert (vertical, horizontal) == (5, 0)

    def test_both_axes_simultaneously(self):
        vertical, horizontal = scroll_semantics(2, -10)
        assert (vertical, horizontal) == (-10, 2)

    def test_string_inputs_coerced(self):
        """LLM 参数可能是字符串数字——强转后语义一致"""
        vertical, horizontal = scroll_semantics("2", "-4")
        assert (vertical, horizontal) == (-4, 2)


class TestManagerScroll:
    """ComputerUseManager.scroll 消费语义：垂直 scroll + 水平 hscroll"""

    @pytest.fixture
    def fake_pyautogui(self, monkeypatch):
        fake = MagicMock()
        monkeypatch.setitem(sys.modules, "pyautogui", fake)
        return fake

    def test_vertical_only_backward_compatible(self, fake_pyautogui):
        """旧调用签名 (x, y, clicks) 行为完全不变"""
        from neurova.computer_use import ComputerUseManager

        manager = ComputerUseManager()
        assert manager.scroll(None, None, -3) is True
        fake_pyautogui.scroll.assert_called_once_with(-3)
        fake_pyautogui.hscroll.assert_not_called()

    def test_vertical_with_position(self, fake_pyautogui):
        from neurova.computer_use import ComputerUseManager

        manager = ComputerUseManager()
        assert manager.scroll(100, 200, 2) is True
        fake_pyautogui.scroll.assert_called_once_with(2, 100, 200)

    def test_horizontal_clicks_forwarded(self, fake_pyautogui):
        """水平滚动走 hscroll（修复前 dx 整体被忽略）"""
        from neurova.computer_use import ComputerUseManager

        manager = ComputerUseManager()
        assert manager.scroll(None, None, 0, horizontal_clicks=-2) is True
        fake_pyautogui.hscroll.assert_called_once_with(-2)
        fake_pyautogui.scroll.assert_not_called()

    def test_both_axes_at_position(self, fake_pyautogui):
        from neurova.computer_use import ComputerUseManager

        manager = ComputerUseManager()
        assert manager.scroll(10, 20, -1, horizontal_clicks=1) is True
        fake_pyautogui.hscroll.assert_called_once_with(1, 10, 20)
        fake_pyautogui.scroll.assert_called_once_with(-1, 10, 20)


class TestHttpScrollConsumer:
    """HTTP /scroll 消费方不再丢符号（契约锁死，防回归）"""

    @pytest.mark.asyncio
    async def test_scroll_endpoint_keeps_direction(self, monkeypatch):
        from neurova.api.endpoints import computer as computer_api

        recorded = {}

        class FakeManager:
            # 真实 ComputerUseManager.scroll 是同步方法（to_thread 调用）——
            # 替身必须忠实契约，async def 会让 to_thread 拿到未 await 的协程对象
            def scroll(self, x, y, clicks, horizontal_clicks=0):
                recorded["clicks"] = clicks
                recorded["horizontal"] = horizontal_clicks
                return True

        monkeypatch.setattr(computer_api, "_get_manager", lambda: FakeManager())
        resp = await computer_api.scroll(computer_api.ScrollRequest(dx=0, dy=-3))
        assert resp["data"]["success"] is True
        assert recorded["clicks"] == -3, "dy=-3（向下）不得被 abs() 翻转成向上"
        assert recorded["horizontal"] == 0

    @pytest.mark.asyncio
    async def test_scroll_endpoint_horizontal(self, monkeypatch):
        from neurova.api.endpoints import computer as computer_api

        recorded = {}

        class FakeManager:
            def scroll(self, x, y, clicks, horizontal_clicks=0):
                recorded["clicks"] = clicks
                recorded["horizontal"] = horizontal_clicks
                return True

        monkeypatch.setattr(computer_api, "_get_manager", lambda: FakeManager())
        await computer_api.scroll(computer_api.ScrollRequest(dx=4, dy=0))
        assert recorded["horizontal"] == 4, "dx 必须被消费（水平滚动）"
        assert recorded["clicks"] == 0


class TestAgentScrollConsumer:
    """agent 路径 scroll_x 必须被消费"""

    @pytest.mark.asyncio
    async def test_tool_executor_scroll_consumes_dx(self, monkeypatch):
        import asyncio as _asyncio

        from neurova.tool_executor import ToolExecutor

        recorded = {}

        class FakeManager:
            def screenshot(self):
                return None

            def scroll(self, x, y, clicks, horizontal_clicks=0):
                recorded["clicks"] = clicks
                recorded["horizontal"] = horizontal_clicks
                return True

        monkeypatch.setattr(
            "neurova.computer_use.get_computer_use_manager", lambda: FakeManager()
        )

        executor = ToolExecutor.__new__(ToolExecutor)
        executor._agent = MagicMock()
        executor._agent.current_session_id = None

        real_to_thread = _asyncio.to_thread

        async def spy_to_thread(func, *args, **kwargs):
            recorded.setdefault("func", func.__qualname__)
            return await real_to_thread(func, *args, **kwargs)

        monkeypatch.setattr(_asyncio, "to_thread", spy_to_thread)

        result = await executor._execute_computer_scroll({"scroll_x": 4, "scroll_y": -2})
        assert result.get("success") is True
        assert recorded["clicks"] == -2, "负 scroll_y 保留符号"
        assert recorded["horizontal"] == 4, "scroll_x 必须被消费"
