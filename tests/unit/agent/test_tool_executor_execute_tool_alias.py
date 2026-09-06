"""认知三链路巡检 P0-1 防回归：ToolExecutor 必须提供 execute_tool。

根因：ToolExecutionManager._execute_strict/_elastic/_infinite 三处调
executor.execute_tool(tool_name, params, user_input)，但注入的
ToolExecutor 只有 execute(tool_name, params)——AttributeError 被上游
except Exception 吞成 FAILED，肌肉记忆"命中→自动执行"每次必败，
且 _record_tool_failure 会清零已固化条目的晋升计数（负反馈污染）。
"""
import asyncio

import pytest

from neurova.tool_executor import ToolExecutor


def test_tool_executor_has_execute_tool():
    executor = ToolExecutor.__new__(ToolExecutor)  # 不触发重依赖初始化
    assert hasattr(executor, "execute_tool"), (
        "ToolExecutionManager 的三条超时策略都调 execute_tool；缺失即肌肉记忆自动执行全断"
    )


def test_execute_tool_delegates_and_tolerates_user_input(monkeypatch):
    executor = ToolExecutor.__new__(ToolExecutor)
    captured = {}

    async def fake_single(tool_name, params, skip_governance=False):
        captured["tool_name"] = tool_name
        captured["params"] = params
        return {"success": True, "result": "ok"}

    monkeypatch.setattr(executor, "_execute_single_tool", fake_single)

    result = asyncio.run(
        executor.execute_tool("weather_query", {"city": "北京"}, "北京天气怎么样")
    )
    assert result == {"success": True, "result": "ok"}
    assert captured == {"tool_name": "weather_query", "params": {"city": "北京"}}
