"""
Tool Layers Schemas — 统一工具层数据模型

提供工具层的核心数据结构，包括：
- ToolSource: 工具来源描述
- ToolParameter: 工具参数定义
- ToolSchema: 工具 Schema 定义
- MCPConnection: MCP 连接配置
- ToolExecutionResult: 工具执行结果
"""

import time
import typing
from dataclasses import dataclass, field
from enum import Enum

# tool_layers imports
try:
    from neurova.tool_layers.openai_schema import OpenAIFunctionSchema
except ImportError:
    # 创建一个占位符，避免循环导入
    OpenAIFunctionSchema = None


class ToolType(str, Enum):
    """工具类型枚举"""

    BUILTIN = "builtin"  # 内置工具
    MCP = "mcp"  # MCP 工具
    PLUGIN = "plugin"  # 插件工具
    EXTERNAL = "external"  # 外部工具
    CUSTOM = "custom"  # 自定义工具


@dataclass
class ToolSource:
    """工具来源描述

    描述一个工具的基本信息、来源和状态。
    """

    name: str
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    tool_type: str = ToolType.BUILTIN.value
    enabled: bool = True
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)
    tags: typing.List[str] = field(default_factory=list)
    created_at: typing.Optional[float] = None
    updated_at: typing.Optional[float] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.updated_at is None:
            self.updated_at = self.created_at

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "tool_type": self.tool_type,
            "enabled": self.enabled,
            "metadata": self.metadata,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "ToolSource":
        """从字典创建"""
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            tool_type=data.get("tool_type", ToolType.BUILTIN.value),
            enabled=data.get("enabled", True),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def touch(self):
        """更新时间戳"""
        self.updated_at = time.time()


@dataclass
class ToolParameter:
    """工具参数定义

    定义工具的一个参数，包括类型、描述、默认值等。
    """

    name: str
    param_type: str = "string"
    description: str = ""
    required: bool = False
    default: typing.Any = None
    enum_values: typing.Optional[typing.List[typing.Any]] = None
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def to_schema(self) -> typing.Dict[str, typing.Any]:
        """转换为 JSON Schema 格式"""
        schema = {
            "type": self.param_type,
            "description": self.description,
        }

        if self.default is not None:
            schema["default"] = self.default

        if self.enum_values is not None:
            schema["enum"] = self.enum_values

        return schema

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "ToolParameter":
        """从字典创建"""
        return cls(
            name=data.get("name", ""),
            param_type=data.get("type", data.get("param_type", "string")),
            description=data.get("description", ""),
            required=data.get("required", False),
            default=data.get("default"),
            enum_values=data.get("enum", data.get("enum_values")),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ToolSchema:
    """工具 Schema 定义

    定义一个工具的完整 Schema，包括名称、描述、参数等。
    """

    name: str
    description: str = ""
    parameters: typing.List[ToolParameter] = field(default_factory=list)
    source: typing.Optional[ToolSource] = None
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)
    return_type: str = "object"

    def to_openai_format(self) -> typing.Dict[str, typing.Any]:
        """转换为 OpenAI 函数调用格式"""
        properties = {}
        required = []

        for param in self.parameters:
            properties[param.name] = param.to_schema()
            if param.required:
                required.append(param.name)

        parameters_schema = {
            "type": "object",
            "properties": properties,
        }

        if required:
            parameters_schema["required"] = required

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters_schema,
            },
        }

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "ToolSchema":
        """从字典创建"""
        parameters = []
        for param_data in data.get("parameters", []):
            if isinstance(param_data, dict):
                parameters.append(ToolParameter.from_dict(param_data))
            elif isinstance(param_data, ToolParameter):
                parameters.append(param_data)

        source = None
        if "source" in data and isinstance(data["source"], dict):
            source = ToolSource.from_dict(data["source"])
        elif "source" in data and isinstance(data["source"], ToolSource):
            source = data["source"]

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            parameters=parameters,
            source=source,
            metadata=data.get("metadata", {}),
            return_type=data.get("return_type", "object"),
        )

    def add_parameter(
        self,
        name: str,
        param_type: str = "string",
        description: str = "",
        required: bool = False,
        default: typing.Any = None,
    ) -> ToolParameter:
        """添加参数"""
        param = ToolParameter(
            name=name,
            param_type=param_type,
            description=description,
            required=required,
            default=default,
        )
        self.parameters.append(param)
        return param


@dataclass
class MCPConnection:
    """MCP 连接配置

    描述与 MCP 服务器的连接配置。
    """

    server_id: str
    transport: str = "stdio"  # stdio, sse, websocket
    command: typing.Optional[str] = None
    args: typing.List[str] = field(default_factory=list)
    env: typing.Dict[str, str] = field(default_factory=dict)
    url: typing.Optional[str] = None
    enabled: bool = True
    timeout: float = 30.0
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        result = {
            "server_id": self.server_id,
            "transport": self.transport,
            "args": self.args,
            "env": self.env,
            "enabled": self.enabled,
            "timeout": self.timeout,
            "metadata": self.metadata,
        }

        if self.command is not None:
            result["command"] = self.command

        if self.url is not None:
            result["url"] = self.url

        return result

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "MCPConnection":
        """从字典创建"""
        return cls(
            server_id=data.get("server_id", ""),
            transport=data.get("transport", "stdio"),
            command=data.get("command"),
            args=data.get("args", []),
            env=data.get("env", {}),
            url=data.get("url"),
            enabled=data.get("enabled", True),
            timeout=data.get("timeout", 30.0),
            metadata=data.get("metadata", {}),
        )

    def is_stdio(self) -> bool:
        """是否为 stdio 传输"""
        return self.transport == "stdio"

    def is_sse(self) -> bool:
        """是否为 SSE 传输"""
        return self.transport == "sse"

    def is_websocket(self) -> bool:
        """是否为 WebSocket 传输"""
        return self.transport == "websocket"


@dataclass
class ToolExecutionResult:
    """工具执行结果

    记录工具执行的结果、耗时、错误等信息。
    """

    tool_name: str
    success: bool = False
    output: typing.Optional[typing.Dict[str, typing.Any]] = None
    duration_ms: float = 0.0
    error: typing.Optional[str] = None
    error_code: typing.Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        result = {
            "tool_name": self.tool_name,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

        if self.output is not None:
            result["output"] = self.output

        if self.error is not None:
            result["error"] = self.error

        if self.error_code is not None:
            result["error_code"] = self.error_code

        return result

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "ToolExecutionResult":
        """从字典创建"""
        return cls(
            tool_name=data.get("tool_name", ""),
            success=data.get("success", False),
            output=data.get("output"),
            duration_ms=data.get("duration_ms", 0.0),
            error=data.get("error"),
            error_code=data.get("error_code"),
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def success_result(
        cls, tool_name: str, output: typing.Dict[str, typing.Any], duration_ms: float = 0.0
    ) -> "ToolExecutionResult":
        """创建成功结果"""
        return cls(
            tool_name=tool_name,
            success=True,
            output=output,
            duration_ms=duration_ms,
        )

    @classmethod
    def error_result(
        cls, tool_name: str, error: str, error_code: typing.Optional[str] = None, duration_ms: float = 0.0
    ) -> "ToolExecutionResult":
        """创建错误结果"""
        return cls(
            tool_name=tool_name,
            success=False,
            error=error,
            error_code=error_code,
            duration_ms=duration_ms,
        )

    def is_expired(self, max_age_seconds: float = 3600) -> bool:
        """检查结果是否过期"""
        return time.time() - self.timestamp > max_age_seconds
