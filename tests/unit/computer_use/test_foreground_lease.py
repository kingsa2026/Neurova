"""P2-5（电脑操控对照评测）：跨会话前台输入互斥（controller_busy）。

对齐参照系 CONTROLLER_BUSY：鼠标/键盘是全局单例，另一会话正持前台输入时，
第二会话的前台桌面动作必须被拒（retry=never），不得并发互踩。
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from neurova.core import turn_context as tc
from neurova.tool_executor import ToolExecutor


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


@pytest.fixture(autouse=True)
def sessions(monkeypatch):
    monkeypatch.setattr(tc, "_session_id_var", tc.ContextVar("t_session", default=None))


class TestForegroundLease:
    @pytest.mark.asyncio
    async def test_second_session_refused_while_first_holds(self, monkeypatch, quiet):
        """会话 A 点击执行期间，会话 B 的点击被拒 controller_busy（retry=never）。"""
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow_click(self, params):
            entered.set()
            try:
                await asyncio.wait_for(release.wait(), timeout=2)
            except asyncio.TimeoutError:
                return {"success": True}  # 未被租约拦截（红灯形态）：超时自放行
            return {"success": True}

        monkeypatch.setattr(ToolExecutor, "_execute_computer_click", slow_click)
        tc._session_id_var.set("s1")
        e1 = _executor()
        task1 = asyncio.ensure_future(e1._execute_builtin_tool("computer_click", {"x": 1, "y": 2}))
        await entered.wait()

        tc._session_id_var.set("s2")
        e2 = _executor()
        out2 = await e2._execute_builtin_tool("computer_click", {"x": 3, "y": 4})
        assert out2["success"] is False
        assert out2.get("action_result", {}).get("refusal_code") == "controller_busy"
        assert out2.get("action_result", {}).get("retry") == "never"

        release.set()
        out1 = await task1
        assert out1["success"] is True

    @pytest.mark.asyncio
    async def test_lease_released_after_action(self, monkeypatch, quiet):
        """动作结束租约即释放：随后其它会话可正常执行。"""
        tc._session_id_var.set("s1")

        async def click(self, params):
            return {"success": True}

        monkeypatch.setattr(ToolExecutor, "_execute_computer_click", click)
        assert (await _executor()._execute_builtin_tool("computer_click", {"x": 1, "y": 2}))["success"]
        tc._session_id_var.set("s2")
        assert (await _executor()._execute_builtin_tool("computer_click", {"x": 1, "y": 2}))["success"]

    @pytest.mark.asyncio
    async def test_same_session_reentrant(self, monkeypatch, quiet):
        """同会话连发不自我互斥（顺序执行各自持锁即放）。"""
        tc._session_id_var.set("s1")

        async def click(self, params):
            return {"success": True}

        monkeypatch.setattr(ToolExecutor, "_execute_computer_click", click)
        e = _executor()
        assert (await e._execute_builtin_tool("computer_click", {"x": 1, "y": 2}))["success"]
        assert (await e._execute_builtin_tool("computer_click", {"x": 2, "y": 3}))["success"]

    @pytest.mark.asyncio
    async def test_observation_tools_not_blocked(self, monkeypatch, quiet):
        """观察面（截图）不走租约——互斥只管前台输入注入。"""

        async def slow_click(self, params):
            await asyncio.sleep(0.05)
            return {"success": True}

        async def shot(self, params):
            return {"success": True}

        monkeypatch.setattr(ToolExecutor, "_execute_computer_click", slow_click)
        monkeypatch.setattr(ToolExecutor, "_execute_computer_screenshot", shot)
        tc._session_id_var.set("s1")
        task1 = asyncio.ensure_future(
            _executor()._execute_builtin_tool("computer_click", {"x": 1, "y": 2})
        )
        await asyncio.sleep(0.01)
        tc._session_id_var.set("s2")
        out = await _executor()._execute_builtin_tool("computer_screenshot", {})
        assert out["success"] is True, "截图（观察面）不得被前台租约挡住"
        del task1
