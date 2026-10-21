"""工具 trace 上下文：只在技能执行边界内记录，边界外 no-op。"""

import pytest

from neurova.core.tool_trace import (
    beginToolTrace,
    currentToolTrace,
    endToolTrace,
    recordToolTrace,
)


def test_trace_records_only_inside_boundary():
    recordToolTrace("outside", {"x": 1})
    assert currentToolTrace() == []

    token, trace = beginToolTrace()
    try:
        recordToolTrace("inner", {"q": "北京"}, success=True, duration_ms=1.5, layer="test")
        recordToolTrace("failed", success=False, error="boom", layer="test")
        assert [item["tool"] for item in trace] == ["inner", "failed"]
        assert trace[0]["success"] is True
        assert trace[1]["error"] == "boom"
        assert currentToolTrace() == trace
    finally:
        endToolTrace(token)
    assert currentToolTrace() == []


@pytest.mark.asyncio
async def test_tool_router_records_inside_trace_boundary():
    from neurova.tool_layers.tool_router import ToolRouter

    class _Tool:
        async def execute(self, params):
            return {"echo": params.get("q")}

    router = ToolRouter()
    router.register_builtin("echo", _Tool())
    token, trace = beginToolTrace()
    try:
        result = await router.execute("echo", {"q": "北京"})
        assert result.success is True
        assert trace and trace[0]["tool"] == "echo"
        assert trace[0]["layer"] == "router"
        assert trace[0]["success"] is True
    finally:
        endToolTrace(token)


def test_trace_params_are_bounded():
    token, trace = beginToolTrace()
    try:
        recordToolTrace("big", {"payload": "x" * 2000})
        assert len(trace[0]["params"]) <= 500
        assert trace[0]["params"].endswith("[truncated]")
    finally:
        endToolTrace(token)
