"""
MCPToolClient 行为级契约测试

基于官方 mcp SDK 的重写后契约：
- connect_server 统一返回 bool，失败原因记录在 server["last_error"]（可经 get_server_status 查询）
- _open_session 是 SDK 会话接缝，测试在该边界 mock，不触碰 subprocess/协议细节
- execute_tool 保留旧校验语义："tools" 键存在才校验存在性，缺失则跳过
- list_tools() 为同步方法（ToolRouter 发现与 neurflow 适配器的硬需求）
"""
import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from neurova.tool_layers.mcp_client import MCPToolClient, ToolNotFoundError, get_mcp_client


def _make_tool(name, description="d", parameters=None):
    """SDK 形态的工具对象（tools/list 返回项）"""
    return SimpleNamespace(name=name, description=description,
                           inputSchema=parameters if parameters is not None else {"type": "object"})


def _make_session(tools=None):
    """已握手完成的 ClientSession mock"""
    session = AsyncMock()
    session.list_tools.return_value = SimpleNamespace(tools=tools or [])
    return session


def _stdio_config():
    return {"id": "srv", "transport": "stdio", "command": "python", "args": ["-m", "srv"]}


class TestMCPToolClientCreation:
    def test_creation(self):
        client = MCPToolClient()
        assert client is not None
        assert hasattr(client, "connect_server")
        assert hasattr(client, "execute_tool")
        assert hasattr(client, "call_tool")
        assert hasattr(client, "list_tools")

    def test_has_core_attributes(self):
        client = MCPToolClient()
        assert hasattr(client, "_servers")
        assert hasattr(client, "_sessions")
        assert hasattr(client, "_firewall")

    def test_get_mcp_client_singleton(self):
        assert get_mcp_client() is get_mcp_client()


class TestConnectDisconnect:
    @pytest.mark.asyncio
    async def test_connect_server_stdio_success(self):
        client = MCPToolClient()
        session = _make_session([_make_tool("t1", "工具1"), _make_tool("t2")])
        client._open_session = AsyncMock(return_value=session)

        result = await client.connect_server("srv", _stdio_config())

        assert result is True
        assert client._servers["srv"]["connected"] is True
        assert client._sessions["srv"] is session
        # 连接时已拉取并缓存工具（dict 形态）
        tools = client._servers["srv"]["tools"]
        assert [t["name"] for t in tools] == ["t1", "t2"]
        assert tools[0]["description"] == "工具1"
        assert tools[0]["parameters"] == {"type": "object"}

    @pytest.mark.asyncio
    async def test_connect_failure_records_last_error(self):
        client = MCPToolClient()

        async def boom(sid, cfg):
            raise ConnectionError("process exited: 1")

        client._open_session = AsyncMock(side_effect=boom)

        result = await client.connect_server("srv", _stdio_config())

        assert result is False
        assert client._servers["srv"]["connected"] is False
        assert "process exited: 1" in client._servers["srv"]["last_error"]

    @pytest.mark.asyncio
    async def test_connect_invalid_config_rejected(self):
        client = MCPToolClient()
        client._open_session = AsyncMock()

        result = await client.connect_server("srv", {"id": "srv", "commnd": "python"})

        assert result is False
        assert "commnd" in client._servers["srv"]["last_error"]
        client._open_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_connect_without_sdk_records_install_hint(self):
        client = MCPToolClient()
        with patch("neurova.tool_layers.mcp_client._SDK_AVAILABLE", False):
            result = await client.connect_server("srv", _stdio_config())
        assert result is False
        assert "mcp" in client._servers["srv"]["last_error"].lower()

    @pytest.mark.asyncio
    async def test_disconnect_server(self):
        client = MCPToolClient()
        stack = AsyncMock()
        client._servers["srv"] = {"config": {}, "connected": True, "tools": [], "last_error": None}
        client._sessions["srv"] = AsyncMock()
        client._stacks["srv"] = stack

        result = await client.disconnect_server("srv")

        assert result is True
        assert "srv" not in client._servers
        assert "srv" not in client._sessions
        stack.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_unknown_server_returns_false(self):
        client = MCPToolClient()
        assert await client.disconnect_server("ghost") is False

    @pytest.mark.asyncio
    async def test_disconnect_all(self):
        client = MCPToolClient()
        for sid in ("s1", "s2"):
            client._servers[sid] = {"config": {}, "connected": True, "tools": [], "last_error": None}
            client._sessions[sid] = AsyncMock()
            client._stacks[sid] = AsyncMock()

        await client.disconnect_all()

        assert len(client._servers) == 0
        assert len(client._sessions) == 0


class TestToolDiscovery:
    @pytest.mark.asyncio
    async def test_get_available_tools_returns_cached(self):
        """server["tools"] 非空时直接返回缓存，不再询问会话"""
        client = MCPToolClient()
        session = _make_session([_make_tool("fresh_tool")])
        client._servers["srv"] = {
            "config": {}, "connected": True, "last_error": None,
            "tools": [{"name": "tool1", "description": "Tool 1", "parameters": {}},
                      {"name": "tool2", "description": "Tool 2", "parameters": {}}],
        }
        client._sessions["srv"] = session

        tools = await client.get_available_tools("srv")

        assert [t["name"] for t in tools] == ["tool1", "tool2"]
        session.list_tools.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_available_tools_fetches_when_cache_empty(self):
        client = MCPToolClient()
        session = _make_session([_make_tool("t1", "desc", {"type": "object", "properties": {}})])
        client._servers["srv"] = {"config": {}, "connected": True, "tools": [], "last_error": None}
        client._sessions["srv"] = session

        tools = await client.get_available_tools("srv")

        assert len(tools) == 1
        assert tools[0] == {"name": "t1", "description": "desc",
                            "parameters": {"type": "object", "properties": {}}}
        # 拉取结果已入缓存
        assert client._servers["srv"]["tools"] == tools

    @pytest.mark.asyncio
    async def test_get_available_tools_not_connected_returns_empty(self):
        client = MCPToolClient()
        client._servers["srv"] = {"config": {}, "connected": False, "tools": [], "last_error": "x"}
        assert await client.get_available_tools("srv") == []

    @pytest.mark.asyncio
    async def test_get_available_tools_unknown_server_raises(self):
        client = MCPToolClient()
        with pytest.raises(ValueError, match="srv"):
            await client.get_available_tools("srv")

    @pytest.mark.asyncio
    async def test_get_server_tools_alias(self):
        client = MCPToolClient()
        client._servers["srv"] = {
            "config": {}, "connected": True, "last_error": None,
            "tools": [{"name": "tool1", "description": "Tool 1", "parameters": {}}],
        }
        tools = await client.get_server_tools("srv")
        assert len(tools) == 1 and tools[0]["name"] == "tool1"

    def test_list_tools_sync_across_servers(self):
        """同步 list_tools：ToolRouter 发现与 neurflow 适配器的硬需求"""
        client = MCPToolClient()
        client._servers = {
            "s1": {"config": {}, "connected": True, "last_error": None,
                   "tools": [{"name": "a", "description": "", "parameters": {}}]},
            "s2": {"config": {}, "connected": False, "last_error": None,
                   "tools": [{"name": "b", "description": "", "parameters": {}}]},
        }
        tools = client.list_tools()
        by_id = {t["name"]: t for t in tools}
        assert by_id["a"]["server_id"] == "s1"
        assert by_id["b"]["server_id"] == "s2"

    def test_list_servers(self):
        client = MCPToolClient()
        client._servers = {"server1": {"connected": True}, "server2": {"connected": False}}
        servers = client.list_servers()
        assert len(servers) == 2
        assert "server1" in servers and "server2" in servers


class TestExecution:
    @pytest.mark.asyncio
    async def test_execute_tool_success_without_tools_key(self):
        """server 条目无 "tools" 键 → 跳过存在性校验直接执行"""
        client = MCPToolClient()
        session = AsyncMock()
        session.call_tool.return_value = {"result": "success"}
        client._servers["srv"] = {"config": {"timeout_ms": 30000}, "connected": True, "last_error": None}
        client._sessions["srv"] = session

        result = await client.execute_tool("srv", "test_tool", {"param": "value"})

        assert result == {"result": "success"}
        session.call_tool.assert_awaited_once_with("test_tool", {"param": "value"})

    @pytest.mark.asyncio
    async def test_execute_tool_not_found_when_tools_present(self):
        client = MCPToolClient()
        client._servers["srv"] = {"config": {}, "connected": True, "last_error": None, "tools": []}
        client._sessions["srv"] = AsyncMock()

        with pytest.raises(ToolNotFoundError):
            await client.execute_tool("srv", "nonexistent_tool", {})

    @pytest.mark.asyncio
    async def test_execute_tool_found_when_listed(self):
        client = MCPToolClient()
        session = AsyncMock()
        session.call_tool.return_value = "ok"
        client._servers["srv"] = {
            "config": {}, "connected": True, "last_error": None,
            "tools": [{"name": "t1", "description": "", "parameters": {}}],
        }
        client._sessions["srv"] = session

        assert await client.execute_tool("srv", "t1", {}) == "ok"

    @pytest.mark.asyncio
    async def test_execute_tool_server_not_connected(self):
        client = MCPToolClient()
        client._servers["srv"] = {"config": {}, "connected": False, "tools": [], "last_error": "x"}
        with pytest.raises(ValueError):
            await client.execute_tool("srv", "t", {})

    @pytest.mark.asyncio
    async def test_execute_tool_unknown_server(self):
        client = MCPToolClient()
        with pytest.raises(ValueError):
            await client.execute_tool("ghost", "t", {})

    @pytest.mark.asyncio
    async def test_call_tool_enforces_timeout(self):
        client = MCPToolClient()
        session = AsyncMock()

        async def hang(name, arguments):
            await asyncio.sleep(10)

        session.call_tool.side_effect = hang
        client._servers["srv"] = {"config": {"timeout_ms": 50}, "connected": True, "last_error": None}
        client._sessions["srv"] = session

        with pytest.raises(asyncio.TimeoutError):
            await client.call_tool("srv", "t", {})

    @pytest.mark.asyncio
    async def test_call_tool_serializes_sdk_result(self):
        """SDK CallToolResult → 可序列化 dict；普通值原样透传"""
        client = MCPToolClient()
        session = AsyncMock()
        session.call_tool.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="hello")], isError=False,
        )
        client._servers["srv"] = {"config": {"timeout_ms": 30000}, "connected": True, "last_error": None}
        client._sessions["srv"] = session

        result = await client.call_tool("srv", "t", {})
        assert result == {"content": [{"type": "text", "text": "hello"}], "isError": False}


class TestServerStatus:
    def test_status_after_connect(self):
        client = MCPToolClient()
        client._servers["srv"] = {
            "config": {"transport": "stdio"}, "connected": True, "last_error": None,
            "tools": [{"name": "a", "description": "", "parameters": {}}],
        }
        status = client.get_server_status("srv")
        assert status["connected"] is True
        assert status["last_error"] is None
        assert status["tool_count"] == 1
        assert status["transport"] == "stdio"

    def test_status_unknown_server(self):
        client = MCPToolClient()
        status = client.get_server_status("ghost")
        assert status["connected"] is False


class TestToolNotFoundError:
    def test_creation(self):
        error = ToolNotFoundError("Tool not found")
        assert str(error) == "Tool not found"
        assert isinstance(error, Exception)

    def test_message_with_names(self):
        error = ToolNotFoundError("Tool 'test_tool' not found on server 'test_server'")
        assert "test_tool" in str(error)
        assert "test_server" in str(error)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
