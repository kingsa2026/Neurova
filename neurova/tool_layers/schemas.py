"""
Tool Layers Schemas — 统一工具层数据模型

提供工具层的核心数据结构，包括：
- ToolType: 工具类型枚举
- MCPConnection: MCP 连接配置
"""

import time
import typing
from dataclasses import dataclass, field
from enum import Enum


class ToolType(str, Enum):
    """工具类型枚举"""

    BUILTIN = "builtin"  # 内置工具
    MCP = "mcp"  # MCP 工具
    PLUGIN = "plugin"  # 插件工具
    EXTERNAL = "external"  # 外部工具
    CUSTOM = "custom"  # 自定义工具


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
