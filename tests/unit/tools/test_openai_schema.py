"""
OpenAI Tool Schema 单元测试

测试目标：
1. OpenAIFunctionSchema 数据类
2. AnthropicToolSchema 数据类
3. GoogleToolSchema 数据类
4. ToolSchemaConverter 类
5. ToolCallParser 类
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import json

# 模拟依赖模块
mock_schemas = MagicMock()
sys.modules['neurova.tool_layers.schemas'] = mock_schemas

# 导入被测模块
from neurova.tool_layers.openai_schema import (
    OpenAIFunctionSchema, AnthropicToolSchema, GoogleToolSchema,
    ToolSchemaConverter, ToolCallParser
)


class TestOpenAIFunctionSchema:
    """OpenAIFunctionSchema 数据类测试"""

    def test_creation(self):
        """测试创建"""
        schema = OpenAIFunctionSchema(
            name="get_weather",
            description="Get weather information",
            parameters={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name"
                    }
                },
                "required": ["location"]
            }
        )
        
        assert schema.name == "get_weather"
        assert schema.description == "Get weather information"
        assert "location" in schema.parameters["properties"]
        assert "location" in schema.parameters["required"]

    def test_defaults(self):
        """测试默认值"""
        schema = OpenAIFunctionSchema(name="test_function")
        
        assert schema.name == "test_function"
        assert schema.description == ""
        assert schema.parameters == {"type": "object", "properties": {}}

    def test_to_openai_format(self):
        """测试转换为 OpenAI 格式"""
        schema = OpenAIFunctionSchema(
            name="test_function",
            description="Test function",
            parameters={"type": "object", "properties": {}}
        )
        
        openai_format = schema.to_openai_format()
        
        assert openai_format["type"] == "function"
        assert openai_format["function"]["name"] == "test_function"
        assert openai_format["function"]["description"] == "Test function"
        assert openai_format["function"]["parameters"] == {"type": "object", "properties": {}}

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "name": "test_function",
            "description": "Test function",
            "parameters": {"type": "object", "properties": {}}
        }
        
        schema = OpenAIFunctionSchema.from_dict(data)
        
        assert schema.name == "test_function"
        assert schema.description == "Test function"

    def test_to_dict(self):
        """测试转换为字典"""
        schema = OpenAIFunctionSchema(
            name="test_function",
            description="Test function",
            parameters={"type": "object", "properties": {}}
        )
        
        data = schema.to_dict()
        
        assert data["name"] == "test_function"
        assert data["description"] == "Test function"
        assert data["parameters"] == {"type": "object", "properties": {}}


class TestAnthropicToolSchema:
    """AnthropicToolSchema 数据类测试"""

    def test_creation(self):
        """测试创建"""
        schema = AnthropicToolSchema(
            name="get_weather",
            description="Get weather information",
            input_schema={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name"
                    }
                },
                "required": ["location"]
            }
        )
        
        assert schema.name == "get_weather"
        assert schema.description == "Get weather information"
        assert "location" in schema.input_schema["properties"]

    def test_to_anthropic_format(self):
        """测试转换为 Anthropic 格式"""
        schema = AnthropicToolSchema(
            name="test_function",
            description="Test function",
            input_schema={"type": "object", "properties": {}}
        )
        
        anthropic_format = schema.to_anthropic_format()
        
        assert anthropic_format["name"] == "test_function"
        assert anthropic_format["description"] == "Test function"
        assert anthropic_format["input_schema"] == {"type": "object", "properties": {}}

    def test_from_openai(self):
        """测试从 OpenAI 格式转换"""
        openai_schema = OpenAIFunctionSchema(
            name="test_function",
            description="Test function",
            parameters={"type": "object", "properties": {}}
        )
        
        anthropic_schema = AnthropicToolSchema.from_openai(openai_schema)
        
        assert anthropic_schema.name == "test_function"
        assert anthropic_schema.description == "Test function"
        assert anthropic_schema.input_schema == {"type": "object", "properties": {}}


class TestGoogleToolSchema:
    """GoogleToolSchema 数据类测试"""

    def test_creation(self):
        """测试创建"""
        schema = GoogleToolSchema(
            name="get_weather",
            description="Get weather information",
            parameters={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name"
                    }
                },
                "required": ["location"]
            }
        )
        
        assert schema.name == "get_weather"
        assert schema.description == "Get weather information"
        assert "location" in schema.parameters["properties"]

    def test_to_google_format(self):
        """测试转换为 Google 格式"""
        schema = GoogleToolSchema(
            name="test_function",
            description="Test function",
            parameters={"type": "object", "properties": {}}
        )
        
        google_format = schema.to_google_format()
        
        assert google_format["name"] == "test_function"
        assert google_format["description"] == "Test function"
        assert google_format["parameters"] == {"type": "object", "properties": {}}

    def test_from_openai(self):
        """测试从 OpenAI 格式转换"""
        openai_schema = OpenAIFunctionSchema(
            name="test_function",
            description="Test function",
            parameters={"type": "object", "properties": {}}
        )
        
        google_schema = GoogleToolSchema.from_openai(openai_schema)
        
        assert google_schema.name == "test_function"
        assert google_schema.description == "Test function"
        assert google_schema.parameters == {"type": "object", "properties": {}}


class TestToolSchemaConverter:
    """ToolSchemaConverter 类测试"""

    def setup_method(self):
        """每个测试前重置"""
        self.converter = ToolSchemaConverter()

    def test_openai_to_anthropic(self):
        """测试 OpenAI 到 Anthropic 转换"""
        openai_schema = OpenAIFunctionSchema(
            name="test_function",
            description="Test function",
            parameters={"type": "object", "properties": {}}
        )
        
        anthropic_schema = self.converter.openai_to_anthropic(openai_schema)
        
        assert anthropic_schema.name == "test_function"
        assert anthropic_schema.description == "Test function"
        assert anthropic_schema.input_schema == {"type": "object", "properties": {}}

    def test_openai_to_google(self):
        """测试 OpenAI 到 Google 转换"""
        openai_schema = OpenAIFunctionSchema(
            name="test_function",
            description="Test function",
            parameters={"type": "object", "properties": {}}
        )
        
        google_schema = self.converter.openai_to_google(openai_schema)
        
        assert google_schema.name == "test_function"
        assert google_schema.description == "Test function"
        assert google_schema.parameters == {"type": "object", "properties": {}}

    def test_anthropic_to_openai(self):
        """测试 Anthropic 到 OpenAI 转换"""
        anthropic_schema = AnthropicToolSchema(
            name="test_function",
            description="Test function",
            input_schema={"type": "object", "properties": {}}
        )
        
        openai_schema = self.converter.anthropic_to_openai(anthropic_schema)
        
        assert openai_schema.name == "test_function"
        assert openai_schema.description == "Test function"
        assert openai_schema.parameters == {"type": "object", "properties": {}}

    def test_google_to_openai(self):
        """测试 Google 到 OpenAI 转换"""
        google_schema = GoogleToolSchema(
            name="test_function",
            description="Test function",
            parameters={"type": "object", "properties": {}}
        )
        
        openai_schema = self.converter.google_to_openai(google_schema)
        
        assert openai_schema.name == "test_function"
        assert openai_schema.description == "Test function"
        assert openai_schema.parameters == {"type": "object", "properties": {}}

    def test_convert_from_dict(self):
        """测试从字典转换"""
        # OpenAI 格式
        openai_dict = {
            "type": "function",
            "function": {
                "name": "test_function",
                "description": "Test function",
                "parameters": {"type": "object", "properties": {}}
            }
        }
        
        schema = self.converter.convert_from_dict(openai_dict, format="openai")
        assert isinstance(schema, OpenAIFunctionSchema)
        assert schema.name == "test_function"

    def test_convert_to_dict(self):
        """测试转换为字典"""
        schema = OpenAIFunctionSchema(
            name="test_function",
            description="Test function",
            parameters={"type": "object", "properties": {}}
        )
        
        data = self.converter.convert_to_dict(schema, format="openai")
        assert data["type"] == "function"
        assert data["function"]["name"] == "test_function"

    def test_batch_convert(self):
        """测试批量转换"""
        schemas = [
            OpenAIFunctionSchema(name="func1", description="Function 1"),
            OpenAIFunctionSchema(name="func2", description="Function 2")
        ]
        
        anthropic_schemas = self.converter.batch_convert(schemas, target_format="anthropic")
        
        assert len(anthropic_schemas) == 2
        assert anthropic_schemas[0].name == "func1"
        assert anthropic_schemas[1].name == "func2"


class TestToolCallParser:
    """ToolCallParser 类测试"""

    def setup_method(self):
        """每个测试前重置"""
        self.parser = ToolCallParser()

    def test_parse_openai_tool_call(self):
        """测试解析 OpenAI 工具调用"""
        tool_call = {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": '{"location": "Beijing"}'
            }
        }
        
        parsed = self.parser.parse_openai_tool_call(tool_call)
        
        assert parsed["id"] == "call_123"
        assert parsed["name"] == "get_weather"
        assert parsed["arguments"] == {"location": "Beijing"}

    def test_parse_anthropic_tool_call(self):
        """测试解析 Anthropic 工具调用"""
        tool_call = {
            "type": "tool_use",
            "id": "toolu_123",
            "name": "get_weather",
            "input": {"location": "Beijing"}
        }
        
        parsed = self.parser.parse_anthropic_tool_call(tool_call)
        
        assert parsed["id"] == "toolu_123"
        assert parsed["name"] == "get_weather"
        assert parsed["arguments"] == {"location": "Beijing"}

    def test_parse_google_tool_call(self):
        """测试解析 Google 工具调用"""
        tool_call = {
            "functionCall": {
                "name": "get_weather",
                "args": {"location": "Beijing"}
            }
        }
        
        parsed = self.parser.parse_google_tool_call(tool_call)
        
        assert parsed["name"] == "get_weather"
        assert parsed["arguments"] == {"location": "Beijing"}

    def test_parse_tool_call_auto_detect(self):
        """测试自动检测格式解析"""
        # OpenAI 格式
        openai_call = {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": '{"location": "Beijing"}'
            }
        }
        
        parsed = self.parser.parse_tool_call(openai_call)
        assert parsed["name"] == "get_weather"
        
        # Anthropic 格式
        anthropic_call = {
            "type": "tool_use",
            "id": "toolu_123",
            "name": "get_weather",
            "input": {"location": "Beijing"}
        }
        
        parsed = self.parser.parse_tool_call(anthropic_call)
        assert parsed["name"] == "get_weather"

    def test_parse_arguments_json(self):
        """测试解析 JSON 参数"""
        arguments = '{"location": "Beijing", "unit": "celsius"}'
        
        parsed = self.parser.parse_arguments(arguments)
        
        assert parsed["location"] == "Beijing"
        assert parsed["unit"] == "celsius"

    def test_parse_arguments_dict(self):
        """测试解析字典参数"""
        arguments = {"location": "Beijing", "unit": "celsius"}
        
        parsed = self.parser.parse_arguments(arguments)
        
        assert parsed["location"] == "Beijing"
        assert parsed["unit"] == "celsius"

    def test_parse_arguments_invalid_json(self):
        """测试解析无效 JSON 参数"""
        arguments = "invalid json"
        
        parsed = self.parser.parse_arguments(arguments)
        
        # 应该返回空字典或原始字符串
        assert isinstance(parsed, dict)

    def test_format_openai_response(self):
        """测试格式化 OpenAI 响应"""
        tool_call_id = "call_123"
        result = {"temperature": 25, "unit": "celsius"}
        
        response = self.parser.format_openai_response(tool_call_id, result)
        
        assert response["tool_call_id"] == tool_call_id
        assert response["role"] == "tool"
        assert "temperature" in response["content"]

    def test_format_anthropic_response(self):
        """测试格式化 Anthropic 响应"""
        tool_use_id = "toolu_123"
        result = {"temperature": 25, "unit": "celsius"}
        
        response = self.parser.format_anthropic_response(tool_use_id, result)
        
        assert response["type"] == "tool_result"
        assert response["tool_use_id"] == tool_use_id
        assert "temperature" in response["content"]

    def test_batch_parse(self):
        """测试批量解析"""
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "func1",
                    "arguments": '{"param1": "value1"}'
                }
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {
                    "name": "func2",
                    "arguments": '{"param2": "value2"}'
                }
            }
        ]
        
        parsed = self.parser.batch_parse(tool_calls)
        
        assert len(parsed) == 2
        assert parsed[0]["name"] == "func1"
        assert parsed[1]["name"] == "func2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])