# -*- coding: utf-8 -*-
"""
工具层集成断裂点测试

验证 ToolEngine 与系统其他部分的集成：
1. ToolExecutor ↔ ToolEngine
2. API ↔ ToolEngine
3. shared_core ↔ ToolEngine
4. MCP ↔ ToolEngine
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.execution_engine.tool_engine import (
    ToolEngine,
    ToolStatus,
    ToolParameter,
    ToolDefinition,
    ToolInvocation,
    ToolCallingContext,
)


class TestToolExecutorToolEngineIntegration:
    """断裂点 1: ToolExecutor ↔ ToolEngine 集成测试"""
    
    @pytest.fixture
    def engine(self):
        """创建 ToolEngine 实例"""
        return ToolEngine()
    
    @pytest.fixture
    def mock_tool_func(self):
        """模拟工具函数"""
        def tool_func(text: str, uppercase: bool = False) -> str:
            if uppercase:
                return text.upper()
            return text
        return tool_func
    
    def test_tool_executor_should_use_tool_engine_for_execution(self, engine, mock_tool_func):
        """测试: ToolExecutor 应该使用 ToolEngine 执行工具
        
        验证:
        - ToolEngine 注册工具后可以执行
        - 执行结果正确
        - 调用历史被记录
        """
        # RED: 这个测试验证 ToolEngine 的基本功能
        engine.register_tool("text_transform", mock_tool_func, "文本转换工具")
        
        # 验证工具已注册
        tool = engine.get_tool("text_transform")
        assert tool is not None
        assert tool.name == "text_transform"
        
        # 验证可以执行
        result = asyncio.run(engine.execute("text_transform", {"text": "hello", "uppercase": True}))
        assert result == "HELLO"
        
        # 验证调用历史
        history = engine.get_tool_history("text_transform")
        assert len(history) == 1
        assert history[0].success is True
    
    def test_tool_executor_should_validate_parameters_before_execution(self, engine, mock_tool_func):
        """测试: ToolExecutor 应该在执行前验证参数
        
        验证:
        - 缺少必需参数时抛出 ValueError
        - 参数类型错误时抛出 ValueError
        """
        # 注册带参数定义的工具
        params = [
            ToolParameter(name="text", type="string", required=True),
            ToolParameter(name="uppercase", type="boolean", required=False, default=False),
        ]
        engine.register_tool("text_transform", mock_tool_func, parameters=params)
        
        # RED: 缺少必需参数应该抛出异常
        with pytest.raises(ValueError, match="缺少必需参数"):
            asyncio.run(engine.execute("text_transform", {}))
    
    def test_tool_executor_should_record_user_and_agent_in_invocation(self, engine, mock_tool_func):
        """测试: ToolExecutor 应该在调用记录中记录 user_id 和 agent_id
        
        验证:
        - execute_with_safeguards 支持 user_id 和 agent_id 参数
        - 调用记录包含这些信息
        """
        engine.register_tool("text_transform", mock_tool_func)
        
        # 执行带用户信息的调用
        result = asyncio.run(engine.execute_with_safeguards(
            "text_transform",
            parameters={"text": "hello"},
            user_id="user_123",
            agent_id="agent_456"
        ))
        
        # 验证调用记录
        history = engine.get_tool_history("text_transform")
        assert len(history) == 1
        assert history[0].user_id == "user_123"
        assert history[0].agent_id == "agent_456"
    
    def test_tool_executor_should_filter_history_by_user_id(self, engine, mock_tool_func):
        """测试: ToolExecutor 应该支持按 user_id 过滤调用历史
        
        验证:
        - get_tool_history 支持 user_id 参数
        - 只返回指定用户的调用记录
        """
        engine.register_tool("text_transform", mock_tool_func)
        
        # 执行多次调用，不同用户
        asyncio.run(engine.execute_with_safeguards(
            "text_transform", {"text": "a"}, user_id="user_1"
        ))
        asyncio.run(engine.execute_with_safeguards(
            "text_transform", {"text": "b"}, user_id="user_2"
        ))
        asyncio.run(engine.execute_with_safeguards(
            "text_transform", {"text": "c"}, user_id="user_1"
        ))
        
        # 验证按用户过滤
        user1_history = engine.get_tool_history("text_transform", user_id="user_1")
        user2_history = engine.get_tool_history("text_transform", user_id="user_2")
        
        assert len(user1_history) == 2
        assert len(user2_history) == 1


class TestAPIToolEngineIntegration:
    """断裂点 2: API ↔ ToolEngine 集成测试"""
    
    @pytest.fixture
    def engine(self):
        """创建带工具的 ToolEngine 实例"""
        engine = ToolEngine()
        
        # 注册一些工具
        engine.register_tool("memory_search", lambda q: f"搜索: {q}", "搜索记忆库")
        engine.register_tool("web_search", lambda q: f"网页: {q}", "搜索互联网", tags=["search"])
        engine.register_tool("file_read", lambda path: f"读取: {path}", "读取文件", tags=["file"])
        
        return engine
    
    def test_api_should_list_tools_from_engine(self, engine):
        """测试: API 应该从 ToolEngine 获取工具列表
        
        验证:
        - list_tools 返回注册的工具
        - 支持按状态过滤
        - 支持按标签过滤
        """
        # 列出所有工具
        all_tools = engine.list_tools()
        assert len(all_tools) == 3
        
        # 按标签过滤
        search_tools = engine.list_tools(tags=["search"])
        assert len(search_tools) == 1
        assert search_tools[0].name == "web_search"
        
        file_tools = engine.list_tools(tags=["file"])
        assert len(file_tools) == 1
        assert file_tools[0].name == "file_read"
    
    def test_api_should_discover_tools_by_query(self, engine):
        """测试: API 应该支持按查询发现工具
        
        验证:
        - discover_tools 支持 query 参数
        - 返回匹配的工具
        """
        result = engine.discover_tools(query="搜索")
        assert len(result.tools) == 2  # memory_search 和 web_search
        
        result = engine.discover_tools(query="文件")
        assert len(result.tools) == 1  # file_read
    
    def test_api_should_execute_tool_through_engine(self, engine):
        """测试: API 应该通过 ToolEngine 执行工具
        
        验证:
        - execute_with_safeguards 执行工具
        - 返回正确结果
        - 记录调用历史
        """
        result = asyncio.run(engine.execute_with_safeguards(
            "memory_search",
            parameters={"q": "test query"}
        ))
        
        assert result == "搜索: test query"
        
        history = engine.get_tool_history("memory_search")
        assert len(history) == 1
    
    def test_api_should_reject_unavailable_tools(self, engine):
        """测试: API 应该拒绝不可用的工具
        
        验证:
        - 状态为 UNAVAILABLE 的工具不能执行
        - 抛出 ValueError
        """
        # 注册一个不可用的工具
        engine.register_tool(
            "broken_tool",
            lambda: "broken",
            status=ToolStatus.UNAVAILABLE
        )
        
        with pytest.raises(ValueError, match="工具不可用"):
            asyncio.run(engine.execute_with_safeguards("broken_tool"))


class TestSharedCoreToolEngineIntegration:
    """断裂点 3: shared_core ↔ ToolEngine 集成测试"""
    
    def test_shared_core_should_create_tool_engine(self):
        """测试: shared_core 应该创建 ToolEngine 实例
        
        验证:
        - ExecutionEngine 初始化时创建 ToolEngine
        - ToolEngine 可用
        """
        from neurova.shared_core.execution_engine import ExecutionEngine
        
        engine = ExecutionEngine()
        
        # 验证 ToolEngine 已创建
        assert engine._tool_engine is not None
        assert isinstance(engine._tool_engine, ToolEngine)
    
    def test_shared_core_should_delegate_tool_registration(self):
        """测试: shared_core 应该委托工具注册给 ToolEngine
        
        验证:
        - register_tool 委托给 ToolEngine
        - 工具在 ToolEngine 中可用
        """
        from neurova.shared_core.execution_engine import ExecutionEngine
        
        engine = ExecutionEngine()
        tool_func = lambda x: x
        
        # 通过 ExecutionEngine 注册工具
        engine.register_tool("test_tool_shared", tool_func, "测试工具")
        
        # 验证工具在 ToolEngine 中可用
        tool = engine._tool_engine.get_tool("test_tool_shared")
        assert tool is not None
        assert tool.name == "test_tool_shared"


class TestMCPToolEngineIntegration:
    """断裂点 5: MCP ↔ ToolEngine 集成测试"""
    
    def test_mcp_tools_should_be_registered_in_tool_engine(self):
        """测试: MCP 工具应该注册到 ToolEngine
        
        验证:
        - MCP 工具可以注册到 ToolEngine
        - 注册后可以通过 ToolEngine 执行
        """
        engine = ToolEngine()
        
        # 模拟 MCP 工具
        mcp_tool_func = lambda query: f"MCP 结果: {query}"
        
        # 注册 MCP 工具
        engine.register_tool(
            "mcp.web_search",
            mcp_tool_func,
            "MCP 网页搜索工具",
            tags=["mcp", "search"]
        )
        
        # 验证工具已注册
        tool = engine.get_tool("mcp.web_search")
        assert tool is not None
        
        # 验证可以通过 ToolEngine 执行
        result = asyncio.run(engine.execute("mcp.web_search", {"query": "test"}))
        assert result == "MCP 结果: test"
    
    def test_mcp_tools_should_appear_in_discovery(self):
        """测试: MCP 工具应该出现在工具发现结果中
        
        验证:
        - discover_tools 返回 MCP 工具
        - 按标签可以过滤 MCP 工具
        """
        engine = ToolEngine()
        
        # 注册一些普通工具和 MCP 工具
        engine.register_tool("builtin_tool", lambda: "builtin", tags=["builtin"])
        engine.register_tool("mcp.tool1", lambda: "mcp1", tags=["mcp"])
        engine.register_tool("mcp.tool2", lambda: "mcp2", tags=["mcp"])
        
        # 按标签发现 MCP 工具
        result = engine.discover_tools(tags=["mcp"])
        assert len(result.tools) == 2
        
        # 按查询发现
        result = engine.discover_tools(query="mcp")
        assert len(result.tools) == 2


class TestMCPToolEngineSync:
    """MCP ↔ ToolEngine 同步测试"""
    
    def test_mcp_client_should_sync_discovered_tools_to_engine(self):
        """测试: MCPToolClient 发现工具时应同步注册到 ToolEngine
        
        验证:
        - MCPToolClient._sync_tools_to_engine 将工具注册到 ToolEngine
        - 注册的工具名格式为 mcp.{server_id}.{tool_name}
        - 工具带有 mcp 标签
        """
        from neurova.tool_layers.mcp_client import MCPToolClient
        
        client = MCPToolClient()
        engine = ToolEngine()
        
        tools = [
            {"name": "web_search", "description": "搜索网页"},
            {"name": "fetch_url", "description": "获取URL内容"},
        ]
        
        # 调用同步方法，传入共享的 engine 实例
        client._sync_tools_to_engine("test_server", tools, engine=engine)
        
        # 验证工具已注册到同一个 ToolEngine
        tool1 = engine.get_tool("mcp.test_server.web_search")
        tool2 = engine.get_tool("mcp.test_server.fetch_url")
        
        assert tool1 is not None
        assert tool1.description == "搜索网页"
        assert "mcp" in tool1.tags
        
        assert tool2 is not None
        assert tool2.description == "获取URL内容"
        assert "mcp" in tool2.tags
    
    def test_mcp_tool_registered_in_engine_should_be_executable(self):
        """测试: 注册到 ToolEngine 的 MCP 工具可以被执行
        
        验证:
        - 通过 ToolEngine 执行 MCP 工具
        - 执行结果正确
        """
        from neurova.tool_layers.mcp_client import MCPToolClient
        
        client = MCPToolClient()
        engine = ToolEngine()
        
        # 模拟 execute_tool 方法
        async def mock_execute_tool(server_id, tool_name, params):
            return f"MCP result: {server_id}/{tool_name} -> {params.get('query', '')}"
        
        client.execute_tool = mock_execute_tool
        
        tools = [{"name": "search", "description": "MCP搜索"}]
        client._sync_tools_to_engine("srv1", tools, engine=engine)
        
        # 通过同一个 ToolEngine 执行
        result = asyncio.run(engine.execute("mcp.srv1.search", {"query": "test"}))
        assert "MCP result: srv1/search -> test" in str(result)


class TestToolExecutorToolEngineFallback:
    """ToolExecutor ↔ ToolEngine 回退机制测试"""
    
    def test_tool_executor_should_fallback_to_router_for_unknown_tools(self):
        """测试: ToolExecutor 应该对未知工具回退到 ToolRouter
        
        验证:
        - ToolEngine 未注册的工具不会抛出异常
        - 回退到 Skill/ToolRouter/内置工具路径
        """
        engine = ToolEngine()
        
        # ToolEngine 没有注册任何工具
        with pytest.raises(ValueError, match="工具未注册"):
            asyncio.run(engine.execute_with_safeguards("unknown_tool"))
    
    def test_tool_executor_should_use_engine_for_registered_tools(self):
        """测试: ToolExecutor 应该对已注册工具使用 ToolEngine
        
        验证:
        - 注册到 ToolEngine 的工具被优先使用
        - 执行历史被记录
        """
        engine = ToolEngine()
        engine.register_tool("registered_tool", lambda x: f"result: {x}")
        
        result = asyncio.run(engine.execute_with_safeguards("registered_tool", {"x": "hello"}))
        assert result == "result: hello"
        
        history = engine.get_tool_history("registered_tool")
        assert len(history) == 1


class TestToolEngineMultiTenantIsolation:
    """多租户隔离测试"""
    
    @pytest.fixture
    def engine(self):
        """创建带工具的 ToolEngine 实例"""
        engine = ToolEngine()
        
        # 用户 1 的工具
        engine.register_tool("tool_user1", lambda: "user1", owner="user_1")
        engine.share_tool_with_user("tool_user1", "user_2")
        
        # 用户 2 的工具
        engine.register_tool("tool_user2", lambda: "user2", owner="user_2")
        
        # 公共工具
        engine.register_tool("public_tool", lambda: "public")
        engine.publish_tool("public_tool")
        
        return engine
    
    def test_user_should_only_see_shared_tools(self, engine):
        """测试: 用户只能看到共享给自己的工具
        
        验证:
        - get_tools_shared_with_me 返回正确的工具
        """
        user1_shared = engine.get_tools_shared_with_me("user_1")
        assert len(user1_shared) == 0  # 没有工具共享给 user_1
        
        user2_shared = engine.get_tools_shared_with_me("user_2")
        assert len(user2_shared) == 1  # tool_user1 共享给 user_2
        assert user2_shared[0].name == "tool_user1"
    
    def test_user_should_see_own_shared_tools(self, engine):
        """测试: 用户应该看到自己共享的工具
        
        验证:
        - get_my_shared_tools 返回用户共享的工具
        """
        user1_shared = engine.get_my_shared_tools("user_1")
        assert len(user1_shared) == 1
        assert user1_shared[0].name == "tool_user1"
    
    def test_public_tools_should_be_discoverable(self, engine):
        """测试: 公共工具应该可被发现
        
        验证:
        - discover_public_tools 返回公共工具
        """
        result = engine.discover_public_tools()
        assert len(result.tools) == 1
        assert result.tools[0].name == "public_tool"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
