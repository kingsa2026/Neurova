"""
P1 工具执行成败判定修复测试（2026-08 代码审计）

覆盖 bug:
1. ToolExecutor._execute_single_tool 在 builtin/skill/router 路径无条件 success=True，
   即使结果是 {"error": ...} → on_tool_executed 把失败记成成功，
   污染肌肉记忆晋升与生命周期学习信号
2. ClosedLoop.on_after_tool_execution 调用 tool_lifecycle.touch(tool_name)
   漏传 success → touch 默认 success=True，失败计入 success_calls，
   损坏的工具会被重新激活
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import neurova.tool_executor as tool_executor_module
from neurova.tool_executor import ToolExecutor


def _make_executor(monkeypatch, tool_memory=None):
    agent = SimpleNamespace(
        tool_memory=tool_memory if tool_memory is not None else MagicMock(),
        tool_lifecycle=None,
        _skill_registry=None,
        tool_router=None,
        _current_user_input="do the thing",
    )
    executor = ToolExecutor(agent)
    monkeypatch.setattr(ToolExecutor, "tool_engine", property(lambda self: None))
    monkeypatch.setattr(
        tool_executor_module,
        "get_builtin_tool_params",
        lambda name: {"type": "object"} if name == "fake_builtin" else None,
    )
    return executor, agent


class TestToolExecutorSuccessFlag:
    @pytest.mark.asyncio
    async def test_builtin_error_result_records_failure(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)

        async def fake_builtin(name, params):
            return {"error": "boom"}

        monkeypatch.setattr(executor, "_execute_builtin_tool", fake_builtin)

        result = await executor.execute("fake_builtin", {"x": 1})

        assert result == {"error": "boom"}
        kwargs = agent.tool_memory.record_tool_usage.call_args.kwargs
        assert kwargs["success"] is False, "结果为 error 时不得记为成功"

    @pytest.mark.asyncio
    async def test_builtin_ok_result_records_success(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)

        async def fake_builtin(name, params):
            return {"result": "ok"}

        monkeypatch.setattr(executor, "_execute_builtin_tool", fake_builtin)

        await executor.execute("fake_builtin", {"x": 1})

        kwargs = agent.tool_memory.record_tool_usage.call_args.kwargs
        assert kwargs["success"] is True

    @pytest.mark.asyncio
    async def test_skill_error_result_records_failure(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)
        registry = MagicMock()
        registry.has_skill.return_value = True
        executor._agent._skill_registry = registry

        async def fake_skill(name, params, context=None):
            return {"error": "skill exploded"}

        monkeypatch.setattr(executor, "execute_skill_tool", fake_skill)

        result = await executor.execute("some_skill", {})

        assert result == {"error": "skill exploded"}
        kwargs = agent.tool_memory.record_tool_usage.call_args.kwargs
        assert kwargs["success"] is False

    @pytest.mark.asyncio
    async def test_router_error_result_records_failure(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)
        router = MagicMock()

        # P0-3：route 契约新增可选 user_id（请求级身份穿透到 MCP 防火墙），
        # 桩签名同步更新
        async def fake_route(name, params, user_id=None):
            return {"error": "router says no"}

        router.route = fake_route
        executor._agent.tool_router = router

        result = await executor.execute("routed_tool", {})

        assert result == {"error": "router says no"}
        kwargs = agent.tool_memory.record_tool_usage.call_args.kwargs
        assert kwargs["success"] is False

    @pytest.mark.asyncio
    async def test_unknown_tool_records_failure(self, monkeypatch):
        executor, agent = _make_executor(monkeypatch)

        result = await executor.execute("no_such_tool", {})

        assert "error" in result
        kwargs = agent.tool_memory.record_tool_usage.call_args.kwargs
        assert kwargs["success"] is False


class TestClosedLoopLifecycleTouch:
    def test_touch_receives_success_flag(self):
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        loop = object.__new__(EvolutionOrchestrator)
        loop.tool_weights = MagicMock()
        loop.tool_lifecycle = MagicMock()
        loop._maybe_evaluate_lifecycle = MagicMock()

        loop.on_after_tool_execution("tool_a", success=False, latency=0.5)

        loop.tool_lifecycle.touch.assert_called_once()
        args, kwargs = loop.tool_lifecycle.touch.call_args
        passed_success = kwargs.get("success", args[1] if len(args) > 1 else None)
        assert passed_success is False, "失败执行必须把 success=False 传给 lifecycle.touch"

    def test_touch_receives_success_true(self):
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        loop = object.__new__(EvolutionOrchestrator)
        loop.tool_weights = MagicMock()
        loop.tool_lifecycle = MagicMock()
        loop._maybe_evaluate_lifecycle = MagicMock()

        loop.on_after_tool_execution("tool_a", success=True, latency=0.1)

        args, kwargs = loop.tool_lifecycle.touch.call_args
        passed_success = kwargs.get("success", args[1] if len(args) > 1 else None)
        assert passed_success is True
