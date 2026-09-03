"""
ToolRouter Skill/MCP 路由修复测试

验证:
1. 内置工具正常路由
2. Skill 工具通过 _skill_manager 解析并路由到 _execute_skill
3. MCP 工具通过 _mcp_clients 解析并路由到 _execute_mcp
4. 不存在的工具返回 Tool not found
5. get_all_tools() 聚合三个来源
6. route() 别名正常工作
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from neurova.tool_layers.tool_router import ToolRouter, ToolResult, _SkillToolProxy, _MCPToolProxy


# ── 测试辅助：模拟工具 ──

class _MockBuiltinTool:
    """模拟内置工具"""
    def __init__(self, name="mock_builtin"):
        self.name = name
    
    async def execute(self, params):
        return {"source": "builtin", "params": params}


class _MockSkillManager:
    """模拟 Skill 管理器"""
    def __init__(self, skills=None):
        self.skills = skills or {}
    
    def has_skill(self, name):
        return name in self.skills
    
    async def execute_skill(self, skill_name, params):
        return {"source": "skill", "skill": skill_name, "params": params}


class _MockMCPClient:
    """模拟 MCP 客户端"""
    def __init__(self, tools=None):
        self._tools = tools or []
    
    def list_tools(self):
        return self._tools
    
    async def execute_tool(self, server_id, tool_name, params):
        return {"source": "mcp", "server": server_id, "tool": tool_name, "params": params}


class _MockMCPTool:
    """模拟 MCP 工具描述"""
    def __init__(self, name, description="", parameters=None):
        self.name = name
        self.description = description
        self.parameters = parameters or {}


# ── Phase 0: 基本功能 ──

class TestBuiltinToolRouting:
    """内置工具路由测试"""
    
    @pytest.mark.asyncio
    async def test_builtin_tool_found(self):
        """内置工具能被正确路由"""
        router = ToolRouter()
        tool = _MockBuiltinTool("test_tool")
        router.register_builtin("test_tool", tool)
        
        result = await router.execute("test_tool", {"key": "value"})
        
        assert result.success is True
        assert result.result["source"] == "builtin"
        assert result.metadata["source"] == "builtin"
    
    @pytest.mark.asyncio
    async def test_builtin_tool_not_found(self):
        """不存在的工具返回 Tool not found"""
        router = ToolRouter()
        
        result = await router.execute("nonexistent", {})
        
        assert result.success is False
        assert "Tool not found" in result.error
    
    @pytest.mark.asyncio
    async def test_isolation_context_injected(self):
        """隔离上下文注入到参数"""
        router = ToolRouter()
        tool = _MockBuiltinTool()
        router.register_builtin("t", tool)
        
        result = await router.execute("t", {}, agent_id="a1", user_id="u1")
        
        assert result.success is True
        # 验证 _agent_id 和 _user_id 被注入
        assert result.result["params"]["_agent_id"] == "a1"
        assert result.result["params"]["_user_id"] == "u1"


# ── Phase 1: Skill 工具路由（核心修复验证）──

class TestSkillToolRouting:
    """Skill 工具路由测试 — 验证修复前死代码现在可达"""
    
    @pytest.mark.asyncio
    async def test_skill_tool_resolved_from_manager(self):
        """Skill 工具从 skill_manager 解析"""
        router = ToolRouter()
        skill_manager = _MockSkillManager({
            "web_search": MagicMock(description="搜索网页", parameters={}),
        })
        router.set_skill_manager(skill_manager)
        
        result = await router.execute("web_search", {"query": "test"})
        
        assert result.success is True
        assert result.result["source"] == "skill"
        assert result.result["skill"] == "web_search"
        assert result.metadata["source"] == "skill"
    
    @pytest.mark.asyncio
    async def test_skill_tool_has_skill_attribute(self):
        """解析的 Skill 工具具有 is_skill=True 属性"""
        router = ToolRouter()
        skill_manager = _MockSkillManager({
            "my_skill": MagicMock(description="desc"),
        })
        router.set_skill_manager(skill_manager)
        
        tools = router.get_all_tools()
        assert "my_skill" in tools
        assert tools["my_skill"].is_skill is True
        assert tools["my_skill"].is_mcp is False
    
    @pytest.mark.asyncio
    async def test_skill_tool_not_found(self):
        """不在 skill_manager 中的工具返回 not found"""
        router = ToolRouter()
        skill_manager = _MockSkillManager({})
        router.set_skill_manager(skill_manager)
        
        result = await router.execute("unknown_skill", {})
        
        assert result.success is False
        assert "Tool not found" in result.error
    
    @pytest.mark.asyncio
    async def test_skill_manager_has_skill_false(self):
        """has_skill() 返回 False 时不路由"""
        router = ToolRouter()
        skill_manager = MagicMock()
        skill_manager.has_skill.return_value = False
        router.set_skill_manager(skill_manager)
        
        result = await router.execute("x", {})
        
        assert result.success is False
    
    @pytest.mark.asyncio
    async def test_skill_manager_no_skills_dict(self):
        """skill_manager 没有 skills 属性时安全处理"""
        router = ToolRouter()
        skill_manager = MagicMock(spec=[])  # 空 spec，无 skills 属性
        router.set_skill_manager(skill_manager)
        
        result = await router.execute("x", {})
        
        assert result.success is False


# ── Phase 2: MCP 工具路由（核心修复验证）──

class TestMCPToolRouting:
    """MCP 工具路由测试 — 验证修复前死代码现在可达"""
    
    @pytest.mark.asyncio
    async def test_mcp_tool_resolved_from_client(self):
        """MCP 工具从 mcp_clients 解析"""
        router = ToolRouter()
        mcp_client = _MockMCPClient([
            _MockMCPTool("get_weather", "查询天气"),
        ])
        router._mcp_clients["weather_server"] = mcp_client
        
        result = await router.execute("get_weather", {"city": "Beijing"})
        
        assert result.success is True
        assert result.result["source"] == "mcp"
        assert result.result["tool"] == "get_weather"
        assert result.metadata["source"] == "mcp"
    
    @pytest.mark.asyncio
    async def test_mcp_tool_has_mcp_attribute(self):
        """解析的 MCP 工具具有 is_mcp=True 属性"""
        router = ToolRouter()
        mcp_client = _MockMCPClient([
            _MockMCPTool("my_mcp_tool"),
        ])
        router._mcp_clients["server1"] = mcp_client
        
        tools = router.get_all_tools()
        assert "my_mcp_tool" in tools
        assert tools["my_mcp_tool"].is_mcp is True
        assert tools["my_mcp_tool"].is_skill is False
    
    @pytest.mark.asyncio
    async def test_mcp_tool_not_found(self):
        """不在任何 MCP 服务器中的工具返回 not found"""
        router = ToolRouter()
        mcp_client = _MockMCPClient([])
        router._mcp_clients["server1"] = mcp_client
        
        result = await router.execute("nonexistent_mcp", {})
        
        assert result.success is False
    
    @pytest.mark.asyncio
    async def test_mcp_client_list_tools_exception(self):
        """MCP 客户端 list_tools 异常时不崩溃"""
        router = ToolRouter()
        mcp_client = MagicMock()
        mcp_client.list_tools.side_effect = RuntimeError("connection failed")
        router._mcp_clients["bad_server"] = mcp_client
        
        result = await router.execute("x", {})
        
        assert result.success is False
    
    @pytest.mark.asyncio
    async def test_mcp_client_no_list_tools(self):
        """MCP 客户端没有 list_tools 方法时不崩溃"""
        router = ToolRouter()
        mcp_client = MagicMock(spec=[])
        router._mcp_clients["server1"] = mcp_client
        
        result = await router.execute("x", {})
        
        assert result.success is False


# ── Phase 3: 优先级和聚合 ──

class TestToolPriority:
    """工具优先级测试"""
    
    @pytest.mark.asyncio
    async def test_builtin_over_skill(self):
        """内置工具优先于同名 Skill"""
        router = ToolRouter()
        builtin = _MockBuiltinTool("shared_name")
        router.register_builtin("shared_name", builtin)
        skill_manager = _MockSkillManager({
            "shared_name": MagicMock(description="skill version"),
        })
        router.set_skill_manager(skill_manager)
        
        result = await router.execute("shared_name", {})
        
        assert result.success is True
        assert result.metadata["source"] == "builtin"
    
    @pytest.mark.asyncio
    async def test_skill_over_mcp(self):
        """Skill 工具优先于同名 MCP"""
        router = ToolRouter()
        skill_manager = _MockSkillManager({
            "shared_name": MagicMock(description="skill version"),
        })
        router.set_skill_manager(skill_manager)
        mcp_client = _MockMCPClient([_MockMCPTool("shared_name")])
        router._mcp_clients["server1"] = mcp_client
        
        result = await router.execute("shared_name", {})
        
        assert result.success is True
        assert result.metadata["source"] == "skill"


# ── Phase 4: get_all_tools() 聚合 ──

class TestGetAllTools:
    """get_all_tools() 聚合测试"""
    
    def test_aggregates_all_sources(self):
        """聚合内置 + Skill + MCP 工具

        契约更新：MCP 工具按命名空间方案恒注册 mcp.{server}.{tool}，
        裸名无冲突时同时注册，因此 MCP 工具占两个条目（共 4 个）。
        """
        router = ToolRouter()
        router.register_builtin("b1", _MockBuiltinTool("b1"))
        skill_manager = _MockSkillManager({
            "s1": MagicMock(description="skill1"),
        })
        router.set_skill_manager(skill_manager)
        mcp_client = _MockMCPClient([_MockMCPTool("m1")])
        router._mcp_clients["srv"] = mcp_client

        tools = router.get_all_tools()

        assert "b1" in tools
        assert "s1" in tools
        assert "m1" in tools
        assert "mcp.srv.m1" in tools  # 命名空间名恒注册
        assert len(tools) == 4
    
    def test_get_all_tools_with_params(self):
        """get_all_tools 接受 agent_id/user_id 参数（向后兼容）"""
        router = ToolRouter()
        router.register_builtin("b1", _MockBuiltinTool())
        
        tools = router.get_all_tools(agent_id="a1", user_id="u1")
        
        assert "b1" in tools
    
    def test_empty_when_no_sources(self):
        """无工具来源时返回空字典"""
        router = ToolRouter()
        
        tools = router.get_all_tools()
        
        assert tools == {}


# ── Phase 5: route() 别名 ──

class TestRouteAlias:
    """route() 别名测试"""
    
    @pytest.mark.asyncio
    async def test_route_returns_result_directly(self):
        """route() 直接返回执行结果（非 ToolResult 包装）"""
        router = ToolRouter()
        router.register_builtin("t", _MockBuiltinTool())
        
        result = await router.route("t", {})
        
        assert result["source"] == "builtin"
    
    @pytest.mark.asyncio
    async def test_route_raises_on_failure(self):
        """route() 在工具未找到时抛出 ValueError"""
        router = ToolRouter()
        
        with pytest.raises(ValueError, match="Tool not found"):
            await router.route("nonexistent", {})
    
    @pytest.mark.asyncio
    async def test_route_with_skill(self):
        """route() 能路由 Skill 工具"""
        router = ToolRouter()
        skill_manager = _MockSkillManager({
            "s1": MagicMock(description="skill1"),
        })
        router.set_skill_manager(skill_manager)
        
        result = await router.route("s1", {"q": "test"})
        
        assert result["source"] == "skill"


# ── Phase 6: 附带修复验证 ──

class TestMCPExecuteSource:
    """MCP 执行时 source 属性正确"""
    
    @pytest.mark.asyncio
    async def test_mcp_execute_uses_server_id(self):
        """_execute_mcp 使用 tool.source 作为 server_id"""
        router = ToolRouter()
        mcp_client = _MockMCPClient([_MockMCPTool("t")])
        router._mcp_clients["my_server"] = mcp_client
        
        proxy = _MCPToolProxy(name="t", server_id="my_server")
        result = await router._execute_mcp(proxy, {"k": "v"})
        
        assert result["server"] == "my_server"
    
    @pytest.mark.asyncio
    async def test_mcp_execute_server_not_found(self):
        """MCP server 不存在时抛出 ValueError"""
        router = ToolRouter()
        
        proxy = _MCPToolProxy(name="t", server_id="missing_server")
        
        with pytest.raises(ValueError, match="MCP client not found"):
            await router._execute_mcp(proxy, {})
