"""
OpenAI Tool Schema 兼容层

提供标准 OpenAI Tool Schema 的定义、验证和转换功能。
支持与 OpenAI、Anthropic、Google 等主流 LLM 的 Tool Schema 互转。

OpenAI Tool Schema 标准格式:
{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get weather information",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name"
                }
            },
            "required": ["location"]
        }
    }
}
"""

import json
from neurova.core.logger import get_logger
import typing
from dataclasses import dataclass, field

logger = get_logger(__name__)


@dataclass
class OpenAIFunctionSchema:
    """OpenAI 函数 Schema"""

    name: str
    description: str = ""
    parameters: typing.Dict[str, typing.Any] = field(default_factory=lambda: {"type": "object", "properties": {}})

    def to_openai_format(self) -> typing.Dict[str, typing.Any]:
        """转换为 OpenAI 格式"""
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "OpenAIFunctionSchema":
        """从字典创建"""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            parameters=data.get("parameters", {"type": "object", "properties": {}}),
        )


@dataclass
class AnthropicToolSchema:
    """Anthropic 工具 Schema"""

    name: str
    description: str = ""
    input_schema: typing.Dict[str, typing.Any] = field(default_factory=lambda: {"type": "object", "properties": {}})

    def to_anthropic_format(self) -> typing.Dict[str, typing.Any]:
        """转换为 Anthropic 格式"""
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}

    @classmethod
    def from_openai(cls, openai_schema: OpenAIFunctionSchema) -> "AnthropicToolSchema":
        """从 OpenAI 格式转换"""
        return cls(
            name=openai_schema.name, description=openai_schema.description, input_schema=openai_schema.parameters
        )

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "AnthropicToolSchema":
        """从字典创建"""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            input_schema=data.get("input_schema", {"type": "object", "properties": {}}),
        )


@dataclass
class GoogleToolSchema:
    """Google 工具 Schema"""

    name: str
    description: str = ""
    parameters: typing.Dict[str, typing.Any] = field(default_factory=lambda: {"type": "object", "properties": {}})

    def to_google_format(self) -> typing.Dict[str, typing.Any]:
        """转换为 Google 格式"""
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    @classmethod
    def from_openai(cls, openai_schema: OpenAIFunctionSchema) -> "GoogleToolSchema":
        """从 OpenAI 格式转换"""
        return cls(name=openai_schema.name, description=openai_schema.description, parameters=openai_schema.parameters)

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "GoogleToolSchema":
        """从字典创建"""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            parameters=data.get("parameters", {"type": "object", "properties": {}}),
        )


class ToolSchemaConverter:
    """
    工具 Schema 转换器

    功能：
    1. OpenAI ↔ Anthropic 转换
    2. OpenAI ↔ Google 转换
    3. 批量转换
    4. 格式自动检测
    """

    def openai_to_anthropic(self, openai_schema: OpenAIFunctionSchema) -> AnthropicToolSchema:
        """OpenAI 到 Anthropic 转换"""
        return AnthropicToolSchema.from_openai(openai_schema)

    def openai_to_google(self, openai_schema: OpenAIFunctionSchema) -> GoogleToolSchema:
        """OpenAI 到 Google 转换"""
        return GoogleToolSchema.from_openai(openai_schema)

    def anthropic_to_openai(self, anthropic_schema: AnthropicToolSchema) -> OpenAIFunctionSchema:
        """Anthropic 到 OpenAI 转换"""
        return OpenAIFunctionSchema(
            name=anthropic_schema.name,
            description=anthropic_schema.description,
            parameters=anthropic_schema.input_schema,
        )

    def google_to_openai(self, google_schema: GoogleToolSchema) -> OpenAIFunctionSchema:
        """Google 到 OpenAI 转换"""
        return OpenAIFunctionSchema(
            name=google_schema.name, description=google_schema.description, parameters=google_schema.parameters
        )

    def convert_from_dict(
        self, data: typing.Dict[str, typing.Any], format: str = "openai"
    ) -> typing.Union[OpenAIFunctionSchema, AnthropicToolSchema, GoogleToolSchema]:
        """
        从字典转换

        参数:
            data: 字典数据
            format: 源格式 ("openai", "anthropic", "google")

        返回:
            Schema 对象
        """
        if format == "openai":
            # 检查是否是 OpenAI 格式
            if "function" in data:
                function_data = data["function"]
                return OpenAIFunctionSchema(
                    name=function_data["name"],
                    description=function_data.get("description", ""),
                    parameters=function_data.get("parameters", {}),
                )
            else:
                return OpenAIFunctionSchema.from_dict(data)

        elif format == "anthropic":
            return AnthropicToolSchema.from_dict(data)

        elif format == "google":
            return GoogleToolSchema.from_dict(data)

        else:
            raise ValueError(f"Unsupported format: {format}")

    def convert_to_dict(
        self, schema: typing.Union[OpenAIFunctionSchema, AnthropicToolSchema, GoogleToolSchema], format: str = "openai"
    ) -> typing.Dict[str, typing.Any]:
        """
        转换为字典

        参数:
            schema: Schema 对象
            format: 目标格式

        返回:
            字典数据
        """
        if isinstance(schema, OpenAIFunctionSchema):
            if format == "openai":
                return schema.to_openai_format()
            elif format == "anthropic":
                return self.openai_to_anthropic(schema).to_anthropic_format()
            elif format == "google":
                return self.openai_to_google(schema).to_google_format()

        elif isinstance(schema, AnthropicToolSchema):
            if format == "openai":
                return self.anthropic_to_openai(schema).to_openai_format()
            elif format == "anthropic":
                return schema.to_anthropic_format()
            elif format == "google":
                # 先转为 OpenAI，再转为 Google
                openai_schema = self.anthropic_to_openai(schema)
                return self.openai_to_google(openai_schema).to_google_format()

        elif isinstance(schema, GoogleToolSchema):
            if format == "openai":
                return self.google_to_openai(schema).to_openai_format()
            elif format == "anthropic":
                # 先转为 OpenAI，再转为 Anthropic
                openai_schema = self.google_to_openai(schema)
                return self.openai_to_anthropic(openai_schema).to_anthropic_format()
            elif format == "google":
                return schema.to_google_format()

        raise ValueError(f"Unsupported schema type or format")

    def batch_convert(
        self,
        schemas: typing.List[typing.Union[OpenAIFunctionSchema, AnthropicToolSchema, GoogleToolSchema]],
        target_format: str = "openai",
    ) -> typing.List[typing.Union[OpenAIFunctionSchema, AnthropicToolSchema, GoogleToolSchema]]:
        """
        批量转换

        参数:
            schemas: Schema 列表
            target_format: 目标格式

        返回:
            转换后的 Schema 列表
        """
        result = []

        for schema in schemas:
            if target_format == "openai":
                if isinstance(schema, OpenAIFunctionSchema):
                    result.append(schema)
                elif isinstance(schema, AnthropicToolSchema):
                    result.append(self.anthropic_to_openai(schema))
                elif isinstance(schema, GoogleToolSchema):
                    result.append(self.google_to_openai(schema))

            elif target_format == "anthropic":
                if isinstance(schema, OpenAIFunctionSchema):
                    result.append(self.openai_to_anthropic(schema))
                elif isinstance(schema, AnthropicToolSchema):
                    result.append(schema)
                elif isinstance(schema, GoogleToolSchema):
                    openai_schema = self.google_to_openai(schema)
                    result.append(self.openai_to_anthropic(openai_schema))

            elif target_format == "google":
                if isinstance(schema, OpenAIFunctionSchema):
                    result.append(self.openai_to_google(schema))
                elif isinstance(schema, AnthropicToolSchema):
                    openai_schema = self.anthropic_to_openai(schema)
                    result.append(self.openai_to_google(openai_schema))
                elif isinstance(schema, GoogleToolSchema):
                    result.append(schema)

        return result


class ToolCallParser:
    """
    工具调用解析器

    功能：
    1. 解析不同格式的工具调用
    2. 自动检测格式
    3. 格式化响应
    """

    def parse_openai_tool_call(self, tool_call: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
        """
        解析 OpenAI 工具调用

        参数:
            tool_call: OpenAI 工具调用

        返回:
            解析结果
        """
        function_data = tool_call.get("function", {})
        arguments = function_data.get("arguments", "{}")

        return {
            "id": tool_call.get("id", ""),
            "name": function_data.get("name", ""),
            "arguments": self.parse_arguments(arguments),
        }

    def parse_anthropic_tool_call(self, tool_call: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
        """
        解析 Anthropic 工具调用

        参数:
            tool_call: Anthropic 工具调用

        返回:
            解析结果
        """
        return {
            "id": tool_call.get("id", ""),
            "name": tool_call.get("name", ""),
            "arguments": self.parse_arguments(tool_call.get("input", {})),
        }

    def parse_google_tool_call(self, tool_call: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
        """
        解析 Google 工具调用

        参数:
            tool_call: Google 工具调用

        返回:
            解析结果
        """
        function_call = tool_call.get("functionCall", {})

        return {"name": function_call.get("name", ""), "arguments": self.parse_arguments(function_call.get("args", {}))}

    def parse_tool_call(self, tool_call: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
        """
        自动检测格式解析工具调用

        参数:
            tool_call: 工具调用

        返回:
            解析结果
        """
        # 检测格式
        if "function" in tool_call:
            # OpenAI 格式
            return self.parse_openai_tool_call(tool_call)

        elif tool_call.get("type") == "tool_use":
            # Anthropic 格式
            return self.parse_anthropic_tool_call(tool_call)

        elif "functionCall" in tool_call:
            # Google 格式
            return self.parse_google_tool_call(tool_call)

        else:
            # 尝试通用解析
            return {
                "id": tool_call.get("id", ""),
                "name": tool_call.get("name", ""),
                "arguments": self.parse_arguments(tool_call.get("arguments", tool_call.get("input", {}))),
            }

    def parse_arguments(
        self, arguments: typing.Union[str, typing.Dict[str, typing.Any]]
    ) -> typing.Dict[str, typing.Any]:
        """
        解析参数

        参数:
            arguments: 参数（字符串或字典）

        返回:
            参数字典
        """
        if isinstance(arguments, dict):
            return arguments

        if isinstance(arguments, str):
            try:
                return json.loads(arguments)
            except json.JSONDecodeError:
                logger.warning("Failed to parse arguments as JSON: %s", arguments)
                return {}

        return {}

    def format_openai_response(self, tool_call_id: str, result: typing.Any) -> typing.Dict[str, typing.Any]:
        """
        格式化 OpenAI 响应

        参数:
            tool_call_id: 工具调用 ID
            result: 执行结果

        返回:
            格式化的响应
        """
        # 将结果转换为字符串
        if isinstance(result, dict):
            content = json.dumps(result, ensure_ascii=False)
        else:
            content = str(result)

        return {"tool_call_id": tool_call_id, "role": "tool", "content": content}

    def format_anthropic_response(self, tool_use_id: str, result: typing.Any) -> typing.Dict[str, typing.Any]:
        """
        格式化 Anthropic 响应

        参数:
            tool_use_id: 工具使用 ID
            result: 执行结果

        返回:
            格式化的响应
        """
        # 将结果转换为字符串
        if isinstance(result, dict):
            content = json.dumps(result, ensure_ascii=False)
        else:
            content = str(result)

        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}

    def batch_parse(
        self, tool_calls: typing.List[typing.Dict[str, typing.Any]]
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        批量解析工具调用

        参数:
            tool_calls: 工具调用列表

        返回:
            解析结果列表
        """
        return [self.parse_tool_call(tc) for tc in tool_calls]
