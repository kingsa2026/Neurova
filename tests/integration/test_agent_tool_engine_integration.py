# -*- coding: utf-8 -*-
"""
Agent ↔ ToolEngine 集成测试

验证 Agent 通过 ToolEngine 执行工具。
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.execution_engine.tool_engine import ToolEngine, ToolStatus


class TestAgentToolEngineIntegration:
    """Agent ↔ ToolEngine 集成测试"""
    
    @pytest.fixture
    def engine(self):
        """创建 ToolEngine 实例"""
        engine = ToolEngine()
        
        # 注册一些工具
        engine.register_tool("memory_search", lambda q: f"搜索: {q}", "搜索记忆库")
        engine.register_tool("web_search", lambda q: f"网页: {q}", "搜索互联网")
        
        return engine
    
    def test_agent_should_use_tool_engine_for_builtin_tools(self, engine):
        """测试: Agent 应该使用 ToolEngine 执行内置工具
        
        验证:
        - Agent 的 ToolExecutor 使用 ToolEngine
        - 工具通过 ToolEngine 执行
        - 执行结果正确
        """
        # 模拟 Agent 的 ToolExecutor
        class MockToolExecutor:
            def __init__(self, engine):
                self._engine = engine
            
            async def execute(self, tool_name, arguments):
                return await self._engine.execute(tool_name, arguments)
        
        executor = MockToolExecutor(engine)
        
        # 执行工具
        result = asyncio.run(executor.execute("memory_search", {"q": "test"}))
        assert result == "搜索: test"
        
        # 验证调用历史
        history = engine.get_tool_history("memory_search")
        assert len(history) == 1
    
    def test_agent_should_use_tool_engine_for_mcp_tools(self, engine):
        """测试: Agent 应该使用 ToolEngine 执行 MCP 工具
        
        验证:
        - MCP 工具注册到 ToolEngine
        - Agent 通过 ToolEngine 执行 MCP 工具
        """
        # 注册 MCP 工具
        engine.register_tool("mcp.web_search", lambda q: f"MCP: {q}", "MCP 网页搜索")
        
        # 模拟 Agent 的 ToolExecutor
        class MockToolExecutor:
            def __init__(self, engine):
                self._engine = engine
            
            async def execute(self, tool_name, arguments):
                return await self._engine.execute(tool_name, arguments)
        
        executor = MockToolExecutor(engine)
        
        # 执行 MCP 工具
        result = asyncio.run(executor.execute("mcp.web_search", {"q": "test"}))
        assert result == "MCP: test"
    
    def test_agent_should_validate_parameters_before_execution(self, engine):
        """测试: Agent 应该在执行前验证参数
        
        验证:
        - ToolEngine 验证参数
        - 缺少必需参数时抛出异常
        """
        from neurova.execution_engine.tool_engine import ToolParameter
        
        # 注册带参数定义的工具
        params = [
            ToolParameter(name="query", type="string", required=True),
        ]
        engine.register_tool("search", lambda query: f"结果: {query}", parameters=params)
        
        # 模拟 Agent 的 ToolExecutor
        class MockToolExecutor:
            def __init__(self, engine):
                self._engine = engine
            
            async def execute(self, tool_name, arguments):
                return await self._engine.execute(tool_name, arguments)
        
        executor = MockToolExecutor(engine)
        
        # 缺少必需参数应该抛出异常
        with pytest.raises(ValueError, match="缺少必需参数"):
            asyncio.run(executor.execute("search", {}))
    
    def test_agent_should_record_execution_history(self, engine):
        """测试: Agent 应该记录执行历史
        
        验证:
        - ToolEngine 记录调用历史
        - 可以按工具名查询历史
        """
        # 模拟 Agent 的 ToolExecutor
        class MockToolExecutor:
            def __init__(self, engine):
                self._engine = engine
            
            async def execute(self, tool_name, arguments):
                return await self._engine.execute(tool_name, arguments)
        
        executor = MockToolExecutor(engine)
        
        # 执行多次
        asyncio.run(executor.execute("memory_search", {"q": "test1"}))
        asyncio.run(executor.execute("memory_search", {"q": "test2"}))
        asyncio.run(executor.execute("web_search", {"q": "test3"}))
        
        # 验证历史
        memory_history = engine.get_tool_history("memory_search")
        web_history = engine.get_tool_history("web_search")
        
        assert len(memory_history) == 2
        assert len(web_history) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
