"""
P0-3 MCP 用户隔离红测（评测 M5）

原缺陷：`get_mcp_client(user_id)` 单例只记住首个 user_id → 之后所有用户
的 MCP 调用都用第一个用户的身份过防火墙。

修复语义（对评测计划"per-user client 池"方案的修正，理由见实现 commit）：
- MCP server 连接是系统共享资源，不做 per-user 进程池（N 倍 stdio spawn、
  破坏 bootstrap 语义）
- 隔离点 = 防火墙身份按请求穿透：
  executor._agent_identity() → router.route(user_id=...) →
  _execute_mcp → client.call_tool(user_id=...) → _check_firewall
- client._user_id 仅作无请求上下文时的兜底
- user_id 不注入 MCP params（_user_id 内部键会泄漏给外部 server）
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.tool_layers.mcp_client import MCPToolClient
from neurova.tool_layers.tool_router import ToolRouter


def _make_client(user_id="u_test"):
    """已连接 s1 的 MCPToolClient：假会话 + 可观测防火墙"""
    client = MCPToolClient(user_id=user_id)
    client._servers["s1"] = {
        "config": {"transport": "http", "timeout_ms": 1000},
        "connected": True,
        "tools": [{"name": "t1", "parameters": {}}],
        "last_error": None,
        "last_connected": None,
    }
    session = AsyncMock()
    session.call_tool = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")], isError=False
        )
    )
    client._sessions["s1"] = session
    firewall = MagicMock(return_value=True)
    client._firewall = firewall  # 预置，绕过懒加载
    return client, session, firewall


def _make_executor(router):
    """最小 ToolExecutor：agent 桩带请求级身份；tool_router 走 agent 属性
    （executor.tool_router property 读 self._agent.tool_router）"""
    from neurova.tool_executor import ToolExecutor

    agent = SimpleNamespace(
        _current_user_id="user_a",
        skill_registry=None,
        tool_router=router,
        config=SimpleNamespace(user_id="user_a", agent_id="a_test"),
    )
    return ToolExecutor(agent)


# ── 1. call_tool / execute_tool 接受请求级 user_id ───────────────


class TestClientUserIdThread:
    @pytest.mark.asyncio
    async def test_request_user_overrides_client_default(self):
        client, session, firewall = _make_client(user_id="u_test")
        await client.call_tool("s1", "t1", {"a": 1}, user_id="user_b")
        firewall.check_permission.assert_called_once_with("user_b", "mcp_tool", "t1")

    @pytest.mark.asyncio
    async def test_fallback_to_client_user_without_request_context(self):
        client, session, firewall = _make_client(user_id="u_test")
        await client.call_tool("s1", "t1", {"a": 1})
        firewall.check_permission.assert_called_once_with("u_test", "mcp_tool", "t1")

    @pytest.mark.asyncio
    async def test_execute_tool_threads_request_user(self):
        client, session, firewall = _make_client(user_id="u_test")
        await client.execute_tool("s1", "t1", {}, user_id="user_b")
        firewall.check_permission.assert_called_once_with("user_b", "mcp_tool", "t1")


# ── 2. router 把请求身份穿到防火墙、不污染 params ─────────────────


class TestRouterThreading:
    @pytest.mark.asyncio
    async def test_router_passes_request_user_to_firewall(self):
        router = ToolRouter()
        client, session, firewall = _make_client(user_id="u_test")
        router.register_mcp_client("s1", client)
        result = await router.execute("t1", {"a": 1}, user_id="user_b")
        assert result.success
        firewall.check_permission.assert_called_once_with("user_b", "mcp_tool", "t1")

    @pytest.mark.asyncio
    async def test_mcp_params_not_polluted_with_user_id(self):
        """_user_id 内部键不得泄漏给外部 MCP server"""
        router = ToolRouter()
        client, session, firewall = _make_client(user_id="u_test")
        router.register_mcp_client("s1", client)
        await router.execute("t1", {"a": 1}, user_id="user_b")
        sent_params = session.call_tool.call_args[0][1]
        assert "_user_id" not in sent_params
        assert sent_params == {"a": 1}

    @pytest.mark.asyncio
    async def test_router_namespace_and_bare_names_resolve(self):
        router = ToolRouter()
        client, session, firewall = _make_client(user_id="u_test")
        router.register_mcp_client("s1", client)
        result = await router.execute("mcp.s1.t1", {}, user_id="user_b")
        assert result.success
        firewall.check_permission.assert_called_once_with("user_b", "mcp_tool", "t1")


# ── 3. executor 把请求级身份传给 router ──────────────────────────


class TestExecutorWiring:
    @pytest.mark.asyncio
    async def test_executor_passes_request_user_to_router(self):
        router = MagicMock()
        router.route = AsyncMock(return_value={"ok": True})
        ex = _make_executor(router)
        await ex._execute_single_tool("totally_unknown_tool", {"x": 1})
        assert router.route.await_count == 1
        assert router.route.await_args.kwargs.get("user_id") == "user_a"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
