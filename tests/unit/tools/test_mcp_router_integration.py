"""
ToolRouter MCP 路由修复 + 命名空间注册 + bootstrap 测试

根因回归测试：
- is_mcp/is_skill 必须严格 `is True`（Mock/AsyncMock 的自动属性是 truthy Mock，会击穿真值判断误路由到 MCP）
- server_id 解析必须校验 str 且已注册，否则回退 source
- _execute_mcp 优先 call_tool，缺失时回退 execute_tool
- MCP 工具以 mcp.{server}.{tool} 命名空间恒注册，裸名仅无冲突时注册
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from neurova.tool_layers.tool_router import ToolRouter


def _mcp_tool_proxy(name, server_id):
    """真实的 MCP 工具代理（dataclass，布尔标志为真值）"""
    from neurova.tool_layers.tool_router import _MCPToolProxy
    return _MCPToolProxy(name=name, server_id=server_id, description="", parameters={})


class TestStrictFlagDispatch:
    """根因修复：真值判断改为严格 `is True`"""

    @pytest.mark.asyncio
    async def test_mock_auto_attrs_not_routed_to_mcp(self):
        router = ToolRouter()
        mcp_client = AsyncMock()
        router._mcp_clients["srv"] = mcp_client

        tool = Mock()  # tool.is_mcp / tool.is_skill 是自动生成的 truthy Mock
        tool.execute = AsyncMock(return_value={"ok": 1})
        router.register_builtin("t", tool)

        result = await router.execute("t", {})

        assert result.success is True
        assert result.result == {"ok": 1}
        mcp_client.call_tool.assert_not_called()
        mcp_client.execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_asyncmock_tool_not_routed_to_mcp(self):
        router = ToolRouter()
        mcp_client = AsyncMock()
        router._mcp_clients["srv"] = mcp_client

        tool = AsyncMock()
        tool.execute.return_value = {"ok": 2}
        router.register_builtin("t2", tool)

        result = await router.execute("t2", {})

        assert result.success is True
        mcp_client.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_mock_auto_attrs_not_routed_to_skill(self):
        router = ToolRouter()
        skill_manager = AsyncMock()
        router.set_skill_manager(skill_manager)

        tool = Mock()
        tool.execute = AsyncMock(return_value={"via": "builtin"})
        router.register_builtin("t3", tool)

        result = await router.execute("t3", {})

        assert result.success is True
        skill_manager.execute_skill.assert_not_called()


class TestMCPExecution:
    """server_id 解析 + call_tool 优先契约"""

    @pytest.mark.asyncio
    async def test_execute_tool_via_real_proxy(self):
        router = ToolRouter()
        client = AsyncMock()
        client.call_tool.return_value = {"r": 1}
        router.register_mcp_client("srv", client)

        proxy = _mcp_tool_proxy("search", "srv")
        router.register_builtin("search", proxy)

        result = await router.execute("search", {"q": 1})
        assert result.success is True
        client.call_tool.assert_awaited_once_with("srv", "search", {"q": 1})

    @pytest.mark.asyncio
    async def test_server_id_falls_back_to_source_when_unregistered(self):
        router = ToolRouter()
        client = AsyncMock()
        client.call_tool.return_value = {"r": 1}
        router._mcp_clients["srv"] = client

        tool = Mock()
        tool.is_mcp = True
        tool.server_id = "ghost"  # str 但未注册
        tool.source = "srv"
        tool.name = "t"
        router.register_builtin("t", tool)

        result = await router.execute("t", {})

        assert result.success is True
        client.call_tool.assert_awaited_once()
        assert client.call_tool.call_args.args[0] == "srv"

    @pytest.mark.asyncio
    async def test_call_tool_preferred_when_both_available(self):
        router = ToolRouter()
        client = AsyncMock()
        client.call_tool.return_value = {"via": "call_tool"}
        router._mcp_clients["srv"] = client

        tool = Mock()
        tool.is_mcp = True
        tool.server_id = "srv"
        tool.name = "t"
        router.register_builtin("t", tool)

        result = await router.execute("t", {})

        assert result.success is True
        assert result.result == {"via": "call_tool"}
        client.execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_tool_fallback_when_no_call_tool(self):
        """客户端只有 execute_tool（旧契约签名）→ 回退调用"""

        class _ExecOnlyClient:
            def __init__(self):
                self.calls = []

            async def execute_tool(self, server_id, tool_name, params):
                self.calls.append((server_id, tool_name, params))
                return {"via": "execute_tool"}

        router = ToolRouter()
        client = _ExecOnlyClient()
        router._mcp_clients["srv"] = client

        tool = Mock()
        tool.is_mcp = True
        tool.server_id = "srv"
        tool.name = "t"
        router.register_builtin("t", tool)

        result = await router.execute("t", {"p": 1})

        assert result.success is True
        assert result.result == {"via": "execute_tool"}
        assert client.calls == [("srv", "t", {"p": 1})]


class TestNamespacedRegistration:
    """mcp.{server}.{tool} 命名空间恒注册；裸名仅无冲突时注册"""

    def _client_with_tools(self, *names):
        client = Mock()
        client.list_tools = Mock(return_value=[
            SimpleNamespace(name=n, description=f"{n} desc", parameters={"type": "object"})
            for n in names
        ])
        return client

    def test_register_mcp_client(self):
        router = ToolRouter()
        client = self._client_with_tools("read_file")
        router.register_mcp_client("fs", client)
        assert router._mcp_clients["fs"] is client

    def test_namespaced_and_bare_registered_when_no_collision(self):
        router = ToolRouter()
        router.register_mcp_client("fs", self._client_with_tools("read_file"))

        tools = router.get_all_tools()

        assert "mcp.fs.read_file" in tools
        assert "read_file" in tools
        ns_tool = tools["mcp.fs.read_file"]
        assert ns_tool.is_mcp is True
        assert ns_tool.server_id == "fs"
        assert ns_tool.parameters == {"type": "object"}

    def test_bare_name_collision_keeps_builtin(self):
        router = ToolRouter()
        builtin = Mock()
        router.register_builtin("read_file", builtin)
        router.register_mcp_client("fs", self._client_with_tools("read_file"))

        tools = router.get_all_tools()

        assert tools["read_file"] is builtin  # 裸名不被 MCP 覆盖
        assert "mcp.fs.read_file" in tools    # 命名空间名仍可用

    @pytest.mark.asyncio
    async def test_namespaced_tool_executes_end_to_end(self):
        """命名空间名经 _resolve_mcp_tool 解析并执行"""

        class _Client:
            async def call_tool(self, server_id, tool_name, params):
                return {"sid": server_id, "name": tool_name}

        client = _Client()
        client.list_tools = Mock(return_value=[
            SimpleNamespace(name="search", description="", parameters={})
        ])

        router = ToolRouter()
        router.register_mcp_client("fs", client)

        result = await router.execute("mcp.fs.search", {"q": 1})

        assert result.success is True
        assert result.result == {"sid": "fs", "name": "search"}


class TestMCPBootstrap:
    """bootstrap_mcp：读 SharedConfigManager → 连接 enabled → 注册（失败不阻断）"""

    def setup_method(self):
        from neurova.tool_layers import mcp_bootstrap
        mcp_bootstrap.reset_bootstrap()
        self.mcp_bootstrap = mcp_bootstrap

    def teardown_method(self):
        self.mcp_bootstrap.reset_bootstrap()

    def _config_manager(self, servers):
        cm = Mock()
        cm.list_mcp_servers.return_value = servers
        return cm

    @pytest.mark.asyncio
    async def test_bootstrap_connects_enabled_and_skips_disabled(self):
        bs = self.mcp_bootstrap
        cm = self._config_manager([
            {"id": "on1", "command": "python", "enabled": True},
            {"id": "off1", "command": "python", "enabled": False},
        ])

        with patch.object(bs.MCPToolClient, "connect_server", new_callable=AsyncMock, return_value=True):
            results = await bs.bootstrap_mcp(config_manager=cm)

        assert results == {"on1": True}
        assert "on1" in bs.get_bootstrapped_clients()
        assert "off1" not in bs.get_bootstrapped_clients()

    @pytest.mark.asyncio
    async def test_bootstrap_invalid_config_not_registered(self):
        bs = self.mcp_bootstrap
        cm = self._config_manager([{"id": "bad", "commnd": "python"}])

        with patch.object(bs.MCPToolClient, "connect_server", new_callable=AsyncMock, return_value=True):
            results = await bs.bootstrap_mcp(config_manager=cm)

        assert results == {"bad": False}
        assert "bad" not in bs.get_bootstrapped_clients()

    @pytest.mark.asyncio
    async def test_bootstrap_connect_failure_still_registers_client(self):
        """连接失败也要注册客户端，让状态可查询"""
        bs = self.mcp_bootstrap
        cm = self._config_manager([{"id": "dead", "command": "python"}])

        with patch.object(bs.MCPToolClient, "connect_server", new_callable=AsyncMock,
                          side_effect=RuntimeError("boom")):
            results = await bs.bootstrap_mcp(config_manager=cm)

        assert results == {"dead": False}
        assert "dead" in bs.get_bootstrapped_clients()

    @pytest.mark.asyncio
    async def test_attach_bootstrapped_clients_to_router(self):
        bs = self.mcp_bootstrap
        cm = self._config_manager([
            {"id": "a", "command": "python"},
            {"id": "b", "command": "python"},
        ])

        with patch.object(bs.MCPToolClient, "connect_server", new_callable=AsyncMock, return_value=True):
            await bs.bootstrap_mcp(config_manager=cm)

        router = ToolRouter()
        count = bs.attach_bootstrapped_clients(router)

        assert count == 2
        assert set(router._mcp_clients) == {"a", "b"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
