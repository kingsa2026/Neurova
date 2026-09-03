"""
Test cases for neurova.tool_layers.tool_router
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from neurova.tool_layers.tool_router import ToolRouter


class TestToolRouter:
    """Test cases for ToolRouter class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.router = ToolRouter()
    
    def test_tool_router_creation(self):
        """Test creating a ToolRouter instance."""
        assert self.router is not None
        assert hasattr(self.router, 'register_builtin')
        assert hasattr(self.router, 'execute')
    
    def test_register_builtin(self):
        """Test registering a builtin tool."""
        mock_tool = Mock()
        mock_tool.name = "test_tool"
        
        self.router.register_builtin("test_tool", mock_tool)
        
        tools = self.router.get_all_tools()
        assert "test_tool" in tools
    
    def test_register_builtin_batch(self):
        """Test registering multiple builtin tools."""
        tools = {
            "tool1": Mock(),
            "tool2": Mock(),
            "tool3": Mock(),
        }
        
        self.router.register_builtin_batch(tools)
        
        all_tools = self.router.get_all_tools()
        assert "tool1" in all_tools
        assert "tool2" in all_tools
        assert "tool3" in all_tools
    
    def test_set_skill_manager(self):
        """Test setting skill manager."""
        mock_manager = Mock()
        self.router.set_skill_manager(mock_manager)
        
        # Verify the manager was set
        assert self.router._skill_manager == mock_manager
    
    def test_set_execution_engine(self):
        """Test setting execution engine."""
        mock_engine = Mock()
        self.router.set_execution_engine(mock_engine)
        
        # Verify the engine was set
        assert self.router._execution_engine == mock_engine
    
    @pytest.mark.asyncio
    async def test_execute_builtin_tool(self):
        """Test executing a builtin tool.

        契约更新：execute() 返回 ToolResult（test_tool_router_routing.py 定义的有效契约），
        原断言期望裸 dict 已过期。
        """
        mock_tool = AsyncMock()
        mock_tool.execute.return_value = {"result": "success"}

        self.router.register_builtin("test_tool", mock_tool)

        result = await self.router.execute("test_tool", {"param": "value"})

        assert result.success is True
        assert result.result == {"result": "success"}
        mock_tool.execute.assert_called_once_with({"param": "value"})

    @pytest.mark.asyncio
    async def test_execute_nonexistent_tool(self):
        """Test executing a nonexistent tool.

        契约更新：未找到工具返回 ToolResult(success=False) 而非抛 KeyError。
        """
        result = await self.router.execute("nonexistent_tool", {})

        assert result.success is False
        assert "nonexistent_tool" in result.error
    
    @pytest.mark.asyncio
    async def test_execute_mcp_tool(self):
        """Test executing an MCP tool."""
        mock_mcp_client = AsyncMock()
        mock_mcp_client.call_tool.return_value = {"result": "mcp_result"}
        
        self.router._mcp_clients = {"mcp_server": mock_mcp_client}
        
        # Mock the tool to be an MCP tool
        mock_tool = Mock()
        mock_tool.source = "mcp_server"
        mock_tool.is_mcp = True
        
        self.router.register_builtin("mcp_tool", mock_tool)
        
        result = await self.router.execute("mcp_tool", {"param": "value"})
        
        # Should call MCP client
        mock_mcp_client.call_tool.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_skill_tool(self):
        """Test executing a skill tool."""
        mock_skill_manager = AsyncMock()
        mock_skill_manager.execute_skill.return_value = {"result": "skill_result"}
        
        self.router.set_skill_manager(mock_skill_manager)
        
        # Mock the tool to be a skill tool
        mock_tool = Mock()
        mock_tool.is_skill = True
        mock_tool.skill_name = "test_skill"
        
        self.router.register_builtin("skill_tool", mock_tool)
        
        result = await self.router.execute("skill_tool", {"param": "value"})
        
        # Should call skill manager
        mock_skill_manager.execute_skill.assert_called_once()
    
    def test_get_all_tools(self):
        """Test getting all tools."""
        tools = {
            "tool1": Mock(),
            "tool2": Mock(),
        }
        
        self.router.register_builtin_batch(tools)
        
        all_tools = self.router.get_all_tools()
        assert len(all_tools) == 2
        assert "tool1" in all_tools
        assert "tool2" in all_tools
    
    def test_get_or_create_mcp(self):
        """Test getting or creating MCP client."""
        # First call should create
        client1 = self.router.get_or_create_mcp("test_server", {"transport": "stdio"})
        
        # Second call should return same client
        client2 = self.router.get_or_create_mcp("test_server", {"transport": "stdio"})
        
        assert client1 is client2
    
    def test_tool_router_has_proper_attributes(self):
        """Test that ToolRouter has all required attributes."""
        assert hasattr(self.router, '_builtin_tools')
        assert hasattr(self.router, '_skill_manager')
        assert hasattr(self.router, '_execution_engine')
        assert hasattr(self.router, '_mcp_clients')
        assert hasattr(self.router, '_mcp_configs')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])