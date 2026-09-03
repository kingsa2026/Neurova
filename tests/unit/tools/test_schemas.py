"""
Test cases for neurova.tool_layers.schemas
"""
import pytest
import time
import datetime
from unittest.mock import Mock, patch

# Mock the openai_schema import
import sys
sys.modules['neurova.tool_layers.openai_schema'] = Mock()

# Now import the module
from neurova.tool_layers.schemas import (
    ToolSource,
    ToolParameter,
    ToolSchema,
    MCPConnection,
    ToolExecutionResult,
)


class TestToolSource:
    """Test cases for ToolSource class."""
    
    def test_tool_source_creation(self):
        """Test creating a ToolSource instance."""
        source = ToolSource(
            name="test_tool",
            description="A test tool",
            version="1.0.0",
            author="test_author",
            tool_type="builtin",
            enabled=True,
        )
        assert source.name == "test_tool"
        assert source.description == "A test tool"
        assert source.version == "1.0.0"
        assert source.author == "test_author"
        assert source.tool_type == "builtin"
        assert source.enabled is True
    
    def test_tool_source_defaults(self):
        """Test ToolSource default values."""
        source = ToolSource(name="test_tool")
        assert source.name == "test_tool"
        assert source.description == ""
        assert source.version == "1.0.0"
        assert source.author == ""
        assert source.tool_type == "builtin"
        assert source.enabled is True
        assert source.metadata == {}
        assert source.tags == []
    
    def test_tool_source_to_dict(self):
        """Test converting ToolSource to dictionary."""
        source = ToolSource(
            name="test_tool",
            description="A test tool",
            version="2.0.0",
            author="test_author",
            tool_type="custom",
            enabled=False,
            tags=["test", "demo"],
        )
        data = source.to_dict()
        assert data["name"] == "test_tool"
        assert data["description"] == "A test tool"
        assert data["version"] == "2.0.0"
        assert data["author"] == "test_author"
        assert data["tool_type"] == "custom"
        assert data["enabled"] is False
        assert data["tags"] == ["test", "demo"]
    
    def test_tool_source_from_dict(self):
        """Test creating ToolSource from dictionary."""
        data = {
            "name": "test_tool",
            "description": "A test tool",
            "version": "1.0.0",
            "author": "test_author",
            "tool_type": "builtin",
            "enabled": True,
            "tags": ["test"],
        }
        source = ToolSource.from_dict(data)
        assert source.name == "test_tool"
        assert source.description == "A test tool"
        assert source.tags == ["test"]


class TestToolParameter:
    """Test cases for ToolParameter class."""
    
    def test_tool_parameter_creation(self):
        """Test creating a ToolParameter instance."""
        param = ToolParameter(
            name="location",
            param_type="string",
            description="City name",
            required=True,
            default=None,
        )
        assert param.name == "location"
        assert param.param_type == "string"
        assert param.description == "City name"
        assert param.required is True
        assert param.default is None
    
    def test_tool_parameter_defaults(self):
        """Test ToolParameter default values."""
        param = ToolParameter(name="test_param")
        assert param.name == "test_param"
        assert param.param_type == "string"
        assert param.description == ""
        assert param.required is False
        assert param.default is None
        assert param.enum_values is None
    
    def test_tool_parameter_to_schema(self):
        """Test converting ToolParameter to JSON Schema format."""
        param = ToolParameter(
            name="temperature",
            param_type="number",
            description="Temperature value",
            required=True,
            default=0.7,
            enum_values=[0.0, 0.5, 1.0],
        )
        schema = param.to_schema()
        assert schema["type"] == "number"
        assert schema["description"] == "Temperature value"
        assert schema["default"] == 0.7
        assert schema["enum"] == [0.0, 0.5, 1.0]
    
    def test_tool_parameter_from_dict(self):
        """Test creating ToolParameter from dictionary."""
        data = {
            "name": "location",
            "type": "string",
            "description": "City name",
            "required": True,
        }
        param = ToolParameter.from_dict(data)
        assert param.name == "location"
        assert param.param_type == "string"
        assert param.required is True


class TestToolSchema:
    """Test cases for ToolSchema class."""
    
    def test_tool_schema_creation(self):
        """Test creating a ToolSchema instance."""
        schema = ToolSchema(
            name="get_weather",
            description="Get weather information",
            parameters=[
                ToolParameter(name="location", param_type="string", required=True),
            ],
            source=ToolSource(name="weather_api"),
        )
        assert schema.name == "get_weather"
        assert schema.description == "Get weather information"
        assert len(schema.parameters) == 1
        assert schema.parameters[0].name == "location"
        assert schema.source.name == "weather_api"
    
    def test_tool_schema_defaults(self):
        """Test ToolSchema default values."""
        schema = ToolSchema(name="test_tool")
        assert schema.name == "test_tool"
        assert schema.description == ""
        assert schema.parameters == []
        assert schema.source is None
        assert schema.metadata == {}
    
    def test_tool_schema_to_openai_format(self):
        """Test converting ToolSchema to OpenAI function calling format."""
        schema = ToolSchema(
            name="get_weather",
            description="Get weather information",
            parameters=[
                ToolParameter(name="location", param_type="string", required=True),
            ],
        )
        openai_format = schema.to_openai_format()
        assert openai_format["type"] == "function"
        assert openai_format["function"]["name"] == "get_weather"
        assert openai_format["function"]["description"] == "Get weather information"
        assert "location" in openai_format["function"]["parameters"]["properties"]
    
    def test_tool_schema_from_dict(self):
        """Test creating ToolSchema from dictionary."""
        data = {
            "name": "get_weather",
            "description": "Get weather information",
            "parameters": [
                {"name": "location", "type": "string", "required": True},
            ],
        }
        schema = ToolSchema.from_dict(data)
        assert schema.name == "get_weather"
        assert len(schema.parameters) == 1


class TestMCPConnection:
    """Test cases for MCPConnection class."""
    
    def test_mcp_connection_creation(self):
        """Test creating an MCPConnection instance."""
        conn = MCPConnection(
            server_id="test_server",
            transport="stdio",
            command="python",
            args=["-m", "mcp_server"],
            env={"DEBUG": "1"},
        )
        assert conn.server_id == "test_server"
        assert conn.transport == "stdio"
        assert conn.command == "python"
        assert conn.args == ["-m", "mcp_server"]
        assert conn.env == {"DEBUG": "1"}
    
    def test_mcp_connection_defaults(self):
        """Test MCPConnection default values."""
        conn = MCPConnection(server_id="test_server")
        assert conn.server_id == "test_server"
        assert conn.transport == "stdio"
        assert conn.command is None
        assert conn.args == []
        assert conn.env == {}
        assert conn.enabled is True
    
    def test_mcp_connection_to_dict(self):
        """Test converting MCPConnection to dictionary."""
        conn = MCPConnection(
            server_id="test_server",
            transport="sse",
            url="http://localhost:8080",
        )
        data = conn.to_dict()
        assert data["server_id"] == "test_server"
        assert data["transport"] == "sse"
        assert data["url"] == "http://localhost:8080"
    
    def test_mcp_connection_from_dict(self):
        """Test creating MCPConnection from dictionary."""
        data = {
            "server_id": "test_server",
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "mcp_server"],
        }
        conn = MCPConnection.from_dict(data)
        assert conn.server_id == "test_server"
        assert conn.command == "python"


class TestToolExecutionResult:
    """Test cases for ToolExecutionResult class."""
    
    def test_tool_execution_result_creation(self):
        """Test creating a ToolExecutionResult instance."""
        result = ToolExecutionResult(
            tool_name="get_weather",
            success=True,
            output={"temperature": 25.5},
            duration_ms=150.0,
            error=None,
        )
        assert result.tool_name == "get_weather"
        assert result.success is True
        assert result.output == {"temperature": 25.5}
        assert result.duration_ms == 150.0
        assert result.error is None
    
    def test_tool_execution_result_defaults(self):
        """Test ToolExecutionResult default values."""
        result = ToolExecutionResult(tool_name="test_tool")
        assert result.tool_name == "test_tool"
        assert result.success is False
        assert result.output is None
        assert result.duration_ms == 0.0
        assert result.error is None
        assert result.metadata == {}
    
    def test_tool_execution_result_to_dict(self):
        """Test converting ToolExecutionResult to dictionary."""
        result = ToolExecutionResult(
            tool_name="get_weather",
            success=True,
            output={"temperature": 25.5},
            duration_ms=150.0,
        )
        data = result.to_dict()
        assert data["tool_name"] == "get_weather"
        assert data["success"] is True
        assert data["output"] == {"temperature": 25.5}
        assert data["duration_ms"] == 150.0
        assert "timestamp" in data
    
    def test_tool_execution_result_from_dict(self):
        """Test creating ToolExecutionResult from dictionary."""
        data = {
            "tool_name": "get_weather",
            "success": True,
            "output": {"temperature": 25.5},
            "duration_ms": 150.0,
            "timestamp": time.time(),
        }
        result = ToolExecutionResult.from_dict(data)
        assert result.tool_name == "get_weather"
        assert result.success is True
    
    def test_tool_execution_result_error_case(self):
        """Test ToolExecutionResult with error."""
        result = ToolExecutionResult(
            tool_name="test_tool",
            success=False,
            error="Tool not found",
            error_code="TOOL_NOT_FOUND",
        )
        assert result.success is False
        assert result.error == "Tool not found"
        assert result.error_code == "TOOL_NOT_FOUND"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])