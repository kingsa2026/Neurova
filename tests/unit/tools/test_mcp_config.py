"""
MCP server 配置严格 schema 验证测试

参照 ZCode 配置模式：
- 未知键 → 显式拒绝（fail fast，不静默丢弃）
- transport 推断：command→stdio，url→http，显式声明优先
- 缺必需字段 → 拒绝并指名缺什么
"""
import pytest

from neurova.tool_layers.mcp_config import validate_mcp_server_config


class TestValidConfigs:
    """合法配置应通过并返回规范化副本"""

    def test_valid_stdio_config(self):
        cfg = validate_mcp_server_config({
            "id": "filesystem",
            "name": "文件系统",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            "enabled": True,
            "description": "文件系统访问",
        })
        assert cfg["id"] == "filesystem"
        assert cfg["transport"] == "stdio"
        assert cfg["command"] == "npx"
        assert cfg["args"] == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        assert cfg["enabled"] is True
        assert cfg["timeout_ms"] == 30000
        assert cfg["env"] == {}

    def test_valid_http_config(self):
        cfg = validate_mcp_server_config({
            "id": "remote",
            "url": "http://localhost:9000/mcp",
        })
        assert cfg["transport"] == "http"
        assert cfg["url"] == "http://localhost:9000/mcp"

    def test_valid_sse_config(self):
        cfg = validate_mcp_server_config({
            "id": "sse1",
            "transport": "sse",
            "url": "http://localhost:9000/sse",
            "headers": {"Authorization": "Bearer x"},
        })
        assert cfg["transport"] == "sse"
        assert cfg["headers"] == {"Authorization": "Bearer x"}

    def test_defaults_filled(self):
        cfg = validate_mcp_server_config({"id": "s", "command": "python"})
        assert cfg["name"] == "s"
        assert cfg["description"] == ""
        assert cfg["enabled"] is True
        assert cfg["args"] == []
        assert cfg["cwd"] is None
        assert cfg["headers"] == {}

    def test_returns_normalized_copy_not_mutating_input(self):
        raw = {"id": "s", "command": "python"}
        validate_mcp_server_config(raw)
        assert raw == {"id": "s", "command": "python"}


class TestTransportInference:
    """transport 推断：显式声明优先，否则 command→stdio / url→http"""

    def test_infer_stdio_from_command(self):
        cfg = validate_mcp_server_config({"id": "s", "command": "python"})
        assert cfg["transport"] == "stdio"

    def test_infer_http_from_url(self):
        cfg = validate_mcp_server_config({"id": "s", "url": "http://x/mcp"})
        assert cfg["transport"] == "http"

    def test_explicit_transport_wins(self):
        cfg = validate_mcp_server_config({
            "id": "s", "transport": "sse", "url": "http://x/sse",
        })
        assert cfg["transport"] == "sse"


class TestStrictSchema:
    """未知键显式拒绝（ZCode 模式：fail fast，不静默丢弃）"""

    def test_unknown_key_rejected_with_name(self):
        with pytest.raises(ValueError, match="commnd"):
            validate_mcp_server_config({"id": "s", "commnd": "python"})

    def test_typo_in_timeout_rejected(self):
        with pytest.raises(ValueError):
            validate_mcp_server_config({"id": "s", "command": "x", "timeout": 5})


class TestRequiredFields:
    """缺必需字段 → 拒绝并指名"""

    def test_missing_id_rejected(self):
        with pytest.raises(ValueError, match="id"):
            validate_mcp_server_config({"command": "python"})

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError, match="id"):
            validate_mcp_server_config({"id": "", "command": "python"})

    def test_stdio_without_command_rejected(self):
        with pytest.raises(ValueError, match="command"):
            validate_mcp_server_config({"id": "s", "transport": "stdio"})

    def test_http_without_url_rejected(self):
        with pytest.raises(ValueError, match="url"):
            validate_mcp_server_config({"id": "s", "transport": "http"})

    def test_invalid_transport_rejected(self):
        with pytest.raises(ValueError, match="transport"):
            validate_mcp_server_config({"id": "s", "transport": "carrier-pigeon", "command": "x"})


class TestFieldTypes:
    """字段类型与取值范围"""

    def test_args_must_be_list(self):
        with pytest.raises(ValueError, match="args"):
            validate_mcp_server_config({"id": "s", "command": "x", "args": "-y"})

    def test_args_items_must_be_str(self):
        with pytest.raises(ValueError, match="args"):
            validate_mcp_server_config({"id": "s", "command": "x", "args": [1, 2]})

    def test_env_must_be_dict(self):
        with pytest.raises(ValueError, match="env"):
            validate_mcp_server_config({"id": "s", "command": "x", "env": ["A=1"]})

    def test_negative_timeout_rejected(self):
        with pytest.raises(ValueError, match="timeout_ms"):
            validate_mcp_server_config({"id": "s", "command": "x", "timeout_ms": -1})

    def test_string_timeout_rejected(self):
        with pytest.raises(ValueError, match="timeout_ms"):
            validate_mcp_server_config({"id": "s", "command": "x", "timeout_ms": "30"})

    def test_disabled_server_still_valid(self):
        cfg = validate_mcp_server_config({"id": "s", "command": "x", "enabled": False})
        assert cfg["enabled"] is False

    def test_custom_timeout_preserved(self):
        cfg = validate_mcp_server_config({"id": "s", "command": "x", "timeout_ms": 120000})
        assert cfg["timeout_ms"] == 120000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
