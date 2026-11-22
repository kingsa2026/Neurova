"""资源治理 P1-1：解析层/执行层 clamp 接线（红→绿）。

- get_tool_timeout：表值越界（合成 1e6 秒条目）必须被钳到 800
- _resolveToolTimeoutSeconds：回落表路径同样过闸
- _execute_run_code：用户参 timeout 直通运行时前必须过闸（红：10**9 原样直通）
"""

from types import SimpleNamespace

import pytest

from neurova.tool_executor import ToolExecutor


def _make_executor() -> ToolExecutor:
    agent = SimpleNamespace(
        _current_user_id="u1",
        config=SimpleNamespace(user_id="u1", agent_id="a1", name="t"),
        context_orchestrator=None,
        skill_registry=None,
    )
    return ToolExecutor(agent)


class TestResolveLayerClamp:
    def test_table_value_over_maximum_is_clamped(self, monkeypatch):
        from neurova.agent import tool_coordinator

        monkeypatch.setitem(tool_coordinator.TOOL_TIMEOUTS_S, "__probe_huge__", 10**6)
        executor = _make_executor()
        assert executor._resolveToolTimeoutSeconds("__probe_huge__") == 800.0

    def test_table_value_below_minimum_is_clamped(self, monkeypatch):
        from neurova.agent import tool_coordinator

        monkeypatch.setitem(tool_coordinator.TOOL_TIMEOUTS_S, "__probe_tiny__", 0.01)
        executor = _make_executor()
        assert executor._resolveToolTimeoutSeconds("__probe_tiny__") == 1.0

    def test_unknown_tool_falls_back_to_default_within_bounds(self):
        executor = _make_executor()
        assert executor._resolveToolTimeoutSeconds("__no_such_tool__") == 60.0


class _StubRuntime:
    def __init__(self, captured: dict):
        self._captured = captured

    async def exec(self, **kwargs):
        self._captured["timeout"] = kwargs.get("timeout")
        return SimpleNamespace(success=True, stdout="", stderr="", exit_code=0, error=None)

    async def stop(self):
        return True


class _StubManager:
    def __init__(self, captured: dict):
        self._captured = captured

    def list_active(self):
        return [{"runtime_type": "local", "status": "running", "runtime_id": "stub"}]

    def get_runtime(self, runtime_id):
        return _StubRuntime(self._captured)


class TestRunCodeUserTimeoutClamp:
    @pytest.mark.asyncio
    async def test_user_timeout_over_maximum_is_clamped_before_runtime(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            "neurova.execution_layers.get_runtime_manager", lambda: _StubManager(captured)
        )

        executor = _make_executor()
        result = await executor._execute_run_code({"code": "pass", "timeout": 10**9})

        assert result["success"] is True
        assert captured["timeout"] == 800.0

    @pytest.mark.asyncio
    async def test_user_timeout_below_minimum_is_clamped(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            "neurova.execution_layers.get_runtime_manager", lambda: _StubManager(captured)
        )

        executor = _make_executor()
        result = await executor._execute_run_code({"code": "pass", "timeout": 0})

        assert result["success"] is True
        assert captured["timeout"] == 1.0

    @pytest.mark.asyncio
    async def test_user_timeout_in_range_passes_through(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            "neurova.execution_layers.get_runtime_manager", lambda: _StubManager(captured)
        )

        executor = _make_executor()
        result = await executor._execute_run_code({"code": "pass", "timeout": 120})

        assert result["success"] is True
        assert captured["timeout"] == 120.0

    @pytest.mark.asyncio
    async def test_missing_timeout_uses_default(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(
            "neurova.execution_layers.get_runtime_manager", lambda: _StubManager(captured)
        )

        executor = _make_executor()
        result = await executor._execute_run_code({"code": "pass"})

        assert result["success"] is True
        assert captured["timeout"] == 60.0
