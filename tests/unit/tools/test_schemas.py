"""
Test cases for neurova.tool_layers.schemas
"""
import pytest
import time
import datetime
from unittest.mock import Mock, patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_openai_schema_mock():
    """隔离桩：schemas 模块顶层 import openai_schema（依赖可能缺失），
    仅在本测试文件进程内以 Mock 顶替，退出后恢复——模块级 sys.modules
    Mock 会永久毒化合跑进程内后续 import（审计台账登记的污染源）。"""
    import sys
    from unittest.mock import Mock

    saved = {k: sys.modules.get(k) for k in ("neurova.tool_layers.openai_schema",)}
    sys.modules["neurova.tool_layers.openai_schema"] = Mock()
    yield
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


# Now import the module
from neurova.tool_layers.schemas import MCPConnection


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])