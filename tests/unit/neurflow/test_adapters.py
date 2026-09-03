"""
Neurflow adapters.py 测试 — TDD 垂直切片 8

测试适配器功能：
1. 参数类型映射
2. ToolEngine 工具 → 节点定义转换
3. SkillRegistry 技能 → 节点定义转换
4. MCP 工具 → 节点定义转换
5. 同步所有节点
6. 错误处理（graceful degradation）
"""
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass
from typing import Dict, List, Any, Optional

# 导入待测模块
from neurova.collaboration.neurflow.adapters import (
    TYPE_MAP,
    param_to_sub_block,
    tool_to_node,
    skill_to_node,
    mcp_tool_to_node,
    sync_all,
    sync_tools,
    sync_skills,
    sync_mcp,
)


class TestTypeMap:
    """测试参数类型映射"""

    def test_string_maps_to_input(self):
        assert TYPE_MAP["string"] == "input"

    def test_number_maps_to_slider(self):
        assert TYPE_MAP["number"] == "slider"

    def test_boolean_maps_to_switch(self):
        assert TYPE_MAP["boolean"] == "switch"

    def test_enum_maps_to_select(self):
        assert TYPE_MAP["enum"] == "select"

    def test_object_maps_to_json(self):
        assert TYPE_MAP["object"] == "json"

    def test_array_maps_to_json(self):
        assert TYPE_MAP["array"] == "json"

    def test_file_maps_to_file(self):
        assert TYPE_MAP["file"] == "file"

    def test_unknown_type_maps_to_input(self):
        """未知类型默认映射到 input"""
        assert TYPE_MAP.get("unknown", "input") == "input"


class TestParamToSubBlock:
    """测试参数转 SubBlockConfig"""

    def test_string_param(self):
        param = {"name": "query", "type": "string", "description": "搜索查询"}
        result = param_to_sub_block(param)
        assert result["id"] == "query"
        assert result["title"] == "Query"  # name.title() 转换
        assert result["type"] == "input"
        assert result["description"] == "搜索查询"

    def test_number_param_with_min_max(self):
        param = {"name": "temperature", "type": "number", "min": 0.0, "max": 2.0}
        result = param_to_sub_block(param)
        assert result["type"] == "slider"
        assert result["min"] == 0.0
        assert result["max"] == 2.0

    def test_enum_param_with_options(self):
        param = {
            "name": "mode",
            "type": "enum",
            "enum": ["fast", "balanced", "accurate"]
        }
        result = param_to_sub_block(param)
        assert result["type"] == "select"
        assert len(result["options"]) == 3

    def test_boolean_param(self):
        param = {"name": "verbose", "type": "boolean", "default": False}
        result = param_to_sub_block(param)
        assert result["type"] == "switch"
        assert result["default_value"] == False

    def test_required_param(self):
        param = {"name": "text", "type": "string", "required": True}
        result = param_to_sub_block(param)
        assert result["required"] == True

    def test_optional_param(self):
        param = {"name": "text", "type": "string"}
        result = param_to_sub_block(param)
        assert result["required"] == False


class TestToolToNode:
    """测试 ToolEngine 工具 → 节点定义"""

    def test_basic_tool_conversion(self):
        tool_def = {
            "name": "web_search",
            "description": "搜索网页内容",
            "parameters": [
                {"name": "query", "type": "string", "required": True, "description": "搜索查询"}
            ],
            "tags": ["search", "web"],
            "version": "1.0.0"
        }
        node = tool_to_node(tool_def)
        assert node.type == "tool:web_search"
        assert node.label == "web_search"
        assert node.icon == "🔧"
        assert node.category == "tools"
        assert node.description == "搜索网页内容"
        assert node.source == "tool"
        assert node.source_id == "web_search"
        assert node.version == "1.0.0"
        assert "search" in node.tags

    def test_tool_with_multiple_params(self):
        tool_def = {
            "name": "file_read",
            "description": "读取文件",
            "parameters": [
                {"name": "path", "type": "string", "required": True},
                {"name": "encoding", "type": "string", "default": "utf-8"}
            ]
        }
        node = tool_to_node(tool_def)
        assert len(node.sub_blocks) == 2
        assert node.sub_blocks[0]["id"] == "path"
        assert node.sub_blocks[0]["required"] == True
        assert node.sub_blocks[1]["id"] == "encoding"
        assert node.sub_blocks[1]["required"] == False

    def test_tool_has_output_ports(self):
        tool_def = {"name": "test_tool", "description": "测试", "parameters": []}
        node = tool_to_node(tool_def)
        assert len(node.outputs) == 2
        assert node.outputs[0]["id"] == "output"
        assert node.outputs[1]["id"] == "error"

    def test_tool_has_input_port(self):
        tool_def = {"name": "test_tool", "description": "测试", "parameters": []}
        node = tool_to_node(tool_def)
        assert len(node.inputs) == 1
        assert node.inputs[0]["id"] == "input"


class TestSkillToNode:
    """测试 SkillRegistry 技能 → 节点定义"""

    def test_basic_skill_conversion(self):
        skill_info = {
            "name": "article_writer",
            "description": "撰写文章",
            "parameters": [
                {"name": "topic", "type": "string", "required": True},
                {"name": "style", "type": "string", "default": "formal"}
            ],
            "tags": ["writing", "content"],
            "version": "2.0.0"
        }
        node = skill_to_node(skill_info)
        assert node.type == "skill:article_writer"
        assert node.label == "article_writer"
        assert node.icon == "📚"
        assert node.category == "skills"
        assert node.description == "撰写文章"
        assert node.source == "skill"
        assert node.source_id == "article_writer"
        assert node.version == "2.0.0"

    def test_skill_has_single_output(self):
        skill_info = {"name": "test_skill", "description": "测试"}
        node = skill_to_node(skill_info)
        assert len(node.outputs) == 1
        assert node.outputs[0]["id"] == "output"


class TestMCPToolToNode:
    """测试 MCP 工具 → 节点定义"""

    def test_basic_mcp_conversion(self):
        tool_info = {
            "name": "read_file",
            "description": "读取文件内容",
            "parameters": [
                {"name": "path", "type": "string", "required": True}
            ]
        }
        node = mcp_tool_to_node("filesystem", tool_info)
        assert node.type == "mcp:filesystem:read_file"
        assert node.label == "read_file"
        assert node.icon == "🔌"
        assert node.category == "mcp"
        assert node.description == "读取文件内容"
        assert node.source == "mcp"
        assert node.source_id == "filesystem:read_file"

    def test_mcp_with_server_prefix(self):
        tool_info = {"name": "tool1", "description": "工具1"}
        node = mcp_tool_to_node("server1", tool_info)
        assert node.type == "mcp:server1:tool1"


class TestSyncFunctions:
    """测试同步函数"""

    def test_sync_tools_with_mock_engine(self):
        """测试同步工具（mock _get_tool_engine）"""
        mock_engine = MagicMock()
        mock_engine.list_tools.return_value = [
            {"name": "web_search", "description": "搜索网页", "parameters": []},
            {"name": "file_read", "description": "读取文件", "parameters": []}
        ]

        with patch("neurova.collaboration.neurflow.adapters._get_tool_engine", return_value=mock_engine):
            registry = MagicMock()
            count = sync_tools(registry)
            assert count == 2
            assert registry.register.call_count == 2

    def test_sync_skills_with_mock_registry(self):
        """测试同步技能（mock _get_skill_registry）"""
        mock_skill_registry = MagicMock()
        mock_skill_registry.list_skills.return_value = [
            {"name": "article_writer", "description": "撰写文章", "parameters": []}
        ]

        with patch("neurova.collaboration.neurflow.adapters._get_skill_registry", return_value=mock_skill_registry):
            registry = MagicMock()
            count = sync_skills(registry)
            assert count == 1
            assert registry.register.call_count == 1

    def test_sync_mcp_with_mock_client(self):
        """测试同步 MCP 工具（mock _get_mcp_client）"""
        mock_mcp_client = MagicMock()
        mock_mcp_client.list_tools.return_value = [
            {"name": "read_file", "description": "读取文件", "parameters": [], "server": "filesystem"}
        ]

        with patch("neurova.collaboration.neurflow.adapters._get_mcp_client", return_value=mock_mcp_client):
            registry = MagicMock()
            count = sync_mcp(registry)
            assert count == 1
            assert registry.register.call_count == 1

    def test_sync_all(self):
        """测试同步所有节点"""
        mock_engine = MagicMock()
        mock_engine.list_tools.return_value = [
            {"name": "tool1", "description": "工具1", "parameters": []}
        ]
        mock_skill_registry = MagicMock()
        mock_skill_registry.list_skills.return_value = [
            {"name": "skill1", "description": "技能1", "parameters": []}
        ]
        mock_mcp_client = MagicMock()
        mock_mcp_client.list_tools.return_value = [
            {"name": "mcp_tool1", "description": "MCP工具1", "parameters": [], "server": "default"}
        ]

        with patch("neurova.collaboration.neurflow.adapters._get_tool_engine", return_value=mock_engine), \
             patch("neurova.collaboration.neurflow.adapters._get_skill_registry", return_value=mock_skill_registry), \
             patch("neurova.collaboration.neurflow.adapters._get_mcp_client", return_value=mock_mcp_client):

            registry = MagicMock()
            result = sync_all(registry)
            assert result["tools"] == 1
            assert result["skills"] == 1
            assert result["mcp"] == 1


class TestErrorHandling:
    """测试错误处理"""

    def test_sync_tools_with_import_error(self):
        """ToolEngine 导入失败时返回 0"""
        with patch("neurova.collaboration.neurflow.adapters._get_tool_engine", return_value=None):
            registry = MagicMock()
            count = sync_tools(registry)
            assert count == 0

    def test_sync_skills_with_import_error(self):
        """SkillRegistry 导入失败时返回 0"""
        with patch("neurova.collaboration.neurflow.adapters._get_skill_registry", return_value=None):
            registry = MagicMock()
            count = sync_skills(registry)
            assert count == 0

    def test_sync_mcp_with_import_error(self):
        """MCPToolClient 导入失败时返回 0"""
        with patch("neurova.collaboration.neurflow.adapters._get_mcp_client", return_value=None):
            registry = MagicMock()
            count = sync_mcp(registry)
            assert count == 0

    def test_sync_tools_with_empty_list(self):
        """空工具列表返回 0"""
        mock_engine = MagicMock()
        mock_engine.list_tools.return_value = []

        with patch("neurova.collaboration.neurflow.adapters._get_tool_engine", return_value=mock_engine):
            registry = MagicMock()
            count = sync_tools(registry)
            assert count == 0

    def test_tool_to_node_with_missing_fields(self):
        """缺少字段时使用默认值"""
        tool_def = {"name": "minimal_tool"}
        node = tool_to_node(tool_def)
        assert node.type == "tool:minimal_tool"
        assert node.description == "工具: minimal_tool"  # 默认描述
        assert node.sub_blocks == []
