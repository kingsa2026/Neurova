"""
Test cases for neurova.tool_layers.unified_registry
"""
import pytest
import time
from unittest.mock import Mock, AsyncMock, patch

from neurova.tool_layers.unified_registry import UnifiedToolRegistry


class TestUnifiedToolRegistry:
    """Test cases for UnifiedToolRegistry class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.registry = UnifiedToolRegistry()
    
    def test_unified_registry_creation(self):
        """Test creating a UnifiedToolRegistry instance."""
        assert self.registry is not None
        assert hasattr(self.registry, 'register_builtin')
        assert hasattr(self.registry, 'execute_and_log')
    
    def test_register_builtin(self):
        """Test registering a builtin tool."""
        mock_tool = Mock()
        mock_tool.name = "test_tool"
        
        self.registry.register_builtin("test_tool", mock_tool)
        
        # Verify tool is registered
        assert "test_tool" in self.registry._builtin_tools
    
    def test_register_builtin_batch(self):
        """Test registering multiple builtin tools."""
        tools = {
            "tool1": Mock(),
            "tool2": Mock(),
            "tool3": Mock(),
        }
        
        self.registry.register_builtin_batch(tools)
        
        assert len(self.registry._builtin_tools) == 3
        assert "tool1" in self.registry._builtin_tools
        assert "tool2" in self.registry._builtin_tools
        assert "tool3" in self.registry._builtin_tools
    
    def test_register_to_engine(self):
        """Test registering tool to execution engine."""
        mock_engine = Mock()
        mock_tool = Mock()
        mock_tool.name = "test_tool"
        
        self.registry._execution_engine = mock_engine
        self.registry.register_builtin("test_tool", mock_tool)
        
        # Should sync to engine
        mock_engine.register_tool.assert_called_once_with("test_tool", mock_tool)
    
    def test_get_capability_graph(self):
        """Test getting capability graph."""
        graph = self.registry.get_capability_graph()
        
        assert graph is not None
        assert hasattr(graph, 'get_related_tools')
    
    def test_get_cli_executor(self):
        """Test getting CLI executor."""
        executor = self.registry.get_cli_executor()
        
        assert executor is not None
        assert hasattr(executor, 'execute_sync')
    
    def test_get_tool_logger(self):
        """Test getting tool logger."""
        logger = self.registry.get_tool_logger()
        
        assert logger is not None
        assert hasattr(logger, 'log')
    
    @pytest.mark.asyncio
    async def test_execute_and_log(self):
        """Test executing and logging a tool."""
        mock_tool = AsyncMock()
        mock_tool.execute.return_value = {"result": "success"}
        
        self.registry.register_builtin("test_tool", mock_tool)
        
        result = await self.registry.execute_and_log("test_tool", {"param": "value"})
        
        assert result.success is True
        assert result.tool_name == "test_tool"
        assert result.output == {"result": "success"}
        assert result.duration_ms > 0
    
    @pytest.mark.asyncio
    async def test_execute_and_log_failure(self):
        """Test executing and logging a failed tool."""
        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = Exception("Tool failed")
        
        self.registry.register_builtin("test_tool", mock_tool)
        
        result = await self.registry.execute_and_log("test_tool", {"param": "value"})
        
        assert result.success is False
        assert result.error == "Tool failed"
        assert result.tool_name == "test_tool"
    
    def test_unified_registry_has_proper_attributes(self):
        """Test that UnifiedToolRegistry has all required attributes."""
        assert hasattr(self.registry, '_builtin_tools')
        assert hasattr(self.registry, '_execution_engine')
        assert hasattr(self.registry, '_capability_graph')
        assert hasattr(self.registry, '_cli_executor')
        assert hasattr(self.registry, '_tool_logger')
        assert hasattr(self.registry, '_sync_to_engine')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])