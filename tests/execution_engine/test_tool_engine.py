import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from neurova.execution_engine.tool_engine import (
    ToolEngine,
    ToolStatus,
    ToolParameter,
)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _fresh():
    return ToolEngine()


class TestToolEngineInit:
    def test_empty_registry(self):
        e = _fresh()
        assert len(e._tools) == 0
        assert len(e._tool_funcs) == 0
        assert len(e._invocations) == 0


class TestRegisterTool:
    def test_register_and_get(self):
        e = _fresh()
        e.register_tool("echo", lambda text: text, description="echo tool")
        t = e.get_tool("echo")
        assert t is not None
        assert t.name == "echo"
        assert t.status == ToolStatus.AVAILABLE

    def test_unregister(self):
        e = _fresh()
        e.register_tool("temp", lambda: None)
        ok = e.unregister_tool("temp")
        assert ok is True
        assert e.get_tool("temp") is None

    def test_unregister_nonexistent(self):
        e = _fresh()
        ok = e.unregister_tool("nope")
        assert ok is False


class TestDispatchTool:
    def test_sync_execute(self):
        import asyncio
        e = _fresh()
        e.register_tool("add", lambda a, b: a + b)
        result = _run_async(
            e.execute("add", {"a": 3, "b": 4})
        )
        assert result == 7

    def test_async_execute(self):
        import asyncio

        async def greet(name):
            return f"hello {name}"

        e = _fresh()
        e.register_tool("greet", greet)
        result = _run_async(
            e.execute("greet", {"name": "world"})
        )
        assert result == "hello world"

    def test_execute_unregistered(self):
        e = _fresh()
        try:
            _run_async(
                e.execute("missing", {})
            )
            assert False, "should have raised"
        except ValueError as exc:
            assert "未注册" in str(exc)


class TestListToolsByTag:
    def test_list_by_tag(self):
        e = _fresh()
        e.register_tool("web_search", lambda q: q, tags=["search", "web"])
        e.register_tool("calc", lambda x: x, tags=["math"])
        results = e.list_tools(tags=["search"])
        assert len(results) == 1
        assert results[0].name == "web_search"


class TestGetStatistics:
    def test_statistics(self):
        import asyncio
        e = _fresh()
        e.register_tool("ok", lambda: 1)
        e.register_tool("fail", lambda: 1 / 0)
        _run_async(e.execute("ok", {}))
        try:
            _run_async(e.execute("fail", {}))
        except Exception:
            pass
        stats = e.get_statistics()
        assert stats["total_tools"] == 2
        assert stats["total_invocations"] == 2
        assert stats["successful_invocations"] == 1
        assert stats["failed_invocations"] == 1


class TestToolHistory:
    def test_history(self):
        import asyncio
        e = _fresh()
        e.register_tool("tool_a", lambda x: x)
        _run_async(e.execute("tool_a", {"x": 1}))
        history = e.get_tool_history("tool_a")
        assert len(history) == 1
        assert history[0].tool_name == "tool_a"
        assert history[0].success is True
