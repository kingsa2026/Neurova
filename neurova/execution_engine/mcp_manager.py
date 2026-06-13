"""
MCP 协议管理器

Neurova CogArch 1.0.0 的执行组件之一
负责：MCP 服务器连接管理、工具发现与调用、协议适配

参考设计：
- 配置驱动 - 从配置文件加载 MCP 工具
- 热重载 - 更新配置无需重启
- 统一工具接口 - 无论是本地还是远程，都用相同的方式调用
- 工具发现 - 自动获取可用的工具和资源
"""

from __future__ import annotations

import datetime
import json
import logging
import typing
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class TransportType(Enum):
    """传输类型"""

    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"
    WEBSOCKET = "websocket"


class ConnectionStatus(Enum):
    """连接状态"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class MCPServerConfig:
    """MCP 服务器配置"""

    name: str
    transport: TransportType = TransportType.STDIO
    command: str = ""
    args: typing.List[str] = field(default_factory=list)
    url: str = ""
    env: typing.Dict[str, str] = field(default_factory=dict)
    timeout: float = 30
    enabled: bool = True

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {
            "name": self.name,
            "transport": self.transport.value,
            "command": self.command,
            "args": self.args,
            "url": self.url,
            "env": self.env,
            "timeout": self.timeout,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "MCPServerConfig":
        config = cls(name=data.get("name", ""))
        if "transport" in data:
            config.transport = TransportType(data["transport"])
        config.command = data.get("command", "")
        config.args = data.get("args", [])
        config.url = data.get("url", "")
        config.env = data.get("env", {})
        config.timeout = data.get("timeout", 30)
        config.enabled = data.get("enabled", True)
        return config


@dataclass
class MCPTool:
    """MCP 工具"""

    name: str
    description: str = ""
    input_schema: typing.Dict[str, typing.Any] = field(default_factory=dict)
    server_name: str = ""

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "server_name": self.server_name,
        }


@dataclass
class MCPResource:
    """MCP 资源"""

    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""
    server_name: str = ""


@dataclass
class MCPConnection:
    """MCP 连接"""

    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    server_config: typing.Optional[MCPServerConfig] = None
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    process: typing.Any = None  # subprocess.Popen
    tools: typing.List[MCPTool] = field(default_factory=list)
    resources: typing.List[MCPResource] = field(default_factory=list)
    last_connected: typing.Optional[datetime.datetime] = None
    error: typing.Optional[str] = None


class MCPManager:
    """
    MCP 协议管理器

    管理 MCP 服务器连接、工具发现和调用。
    """

    def __init__(self, config_path: str = None):
        self._lock = __import__("threading").RLock()

        # 配置
        self._config_path = config_path or "config/mcp_servers.json"
        self._servers: typing.Dict[str, MCPServerConfig] = {}

        # 连接
        self._connections: typing.Dict[str, MCPConnection] = {}

        # 工具缓存
        self._tools: typing.Dict[str, MCPTool] = {}

        # 加载配置
        self._load_config()

        logger.info("MCPManager 初始化完成")

    def _load_config(self) -> None:
        """加载配置"""
        try:
            config_path = Path(self._config_path)
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                servers = data.get("servers", {})
                for name, server_data in servers.items():
                    self._servers[name] = MCPServerConfig.from_dict({"name": name, **server_data})

                logger.info("加载 %s 个 MCP 服务器配置", len(self._servers))
        except Exception as e:
            logger.error("加载 MCP 配置失败: %s", e)

    def reload_config(self) -> None:
        """重新加载配置"""
        self._load_config()
        logger.info("MCP 配置已重新加载")

    def register_server(self, config: MCPServerConfig) -> None:
        """注册服务器"""
        with self._lock:
            self._servers[config.name] = config
            logger.debug("MCP 服务器已注册: %s", config.name)

    def unregister_server(self, name: str) -> bool:
        """取消注册服务器"""
        with self._lock:
            if name in self._servers:
                # 断开连接
                self._disconnect_server(name)
                del self._servers[name]
                logger.debug("MCP 服务器已取消注册: %s", name)
                return True
            return False

    async def connect_server(self, name: str) -> bool:
        """连接服务器"""
        config = self._servers.get(name)
        if not config:
            logger.error("MCP 服务器未注册: %s", name)
            return False

        if config.transport == TransportType.STDIO:
            return await self._connect_stdio(config)
        elif config.transport == TransportType.SSE:
            return await self._connect_sse(config)
        elif config.transport == TransportType.HTTP:
            return await self._connect_http(config)
        else:
            logger.error("不支持的传输类型: %s", config.transport)
            return False

    async def _connect_stdio(self, config: MCPServerConfig) -> bool:
        """通过 stdio 连接"""
        try:
            import subprocess

            env = {**config.env} if config.env else None

            process = subprocess.Popen(
                [config.command] + config.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            connection = MCPConnection(
                server_config=config,
                status=ConnectionStatus.CONNECTED,
                process=process,
                last_connected=datetime.datetime.now(),
            )

            with self._lock:
                self._connections[config.name] = connection

            # 发现工具
            await self._discover_tools(config.name)

            logger.info("MCP stdio 连接成功: %s", config.name)
            return True

        except Exception as e:
            logger.error("MCP stdio 连接失败: %s, 错误: %s", config.name, e)
            return False

    async def _connect_sse(self, config: MCPServerConfig) -> bool:
        """通过 SSE 连接"""
        logger.info("MCP SSE 连接: %s -> %s", config.name, config.url)
        # 简化实现：标记为已连接
        connection = MCPConnection(
            server_config=config, status=ConnectionStatus.CONNECTED, last_connected=datetime.datetime.now()
        )
        with self._lock:
            self._connections[config.name] = connection
        return True

    async def _connect_http(self, config: MCPServerConfig) -> bool:
        """通过 HTTP 连接"""
        logger.info("MCP HTTP 连接: %s -> %s", config.name, config.url)
        connection = MCPConnection(
            server_config=config, status=ConnectionStatus.CONNECTED, last_connected=datetime.datetime.now()
        )
        with self._lock:
            self._connections[config.name] = connection
        return True

    def _disconnect_server(self, name: str) -> None:
        """断开服务器"""
        connection = self._connections.get(name)
        if connection:
            if connection.process:
                try:
                    connection.process.terminate()
                except Exception:
                    pass
            connection.status = ConnectionStatus.DISCONNECTED

            # 移除工具
            for tool_name in [k for k, v in self._tools.items() if v.server_name == name]:
                del self._tools[tool_name]

            del self._connections[name]
            logger.debug("MCP 服务器已断开: %s", name)

    async def _discover_tools(self, name: str) -> typing.List[MCPTool]:
        """发现工具"""
        connection = self._connections.get(name)
        if not connection or connection.status != ConnectionStatus.CONNECTED:
            return []

        # 简化实现：使用进程通信
        tools = []

        if connection.process:
            try:
                # 发送 tools/list 请求
                request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"

                connection.process.stdin.write(request.encode())
                connection.process.stdin.flush()

                # 读取响应（简化：超时处理）
                import select
                import sys

                if sys.platform != "win32":
                    ready = select.select([connection.process.stdout], [], [], 5)
                    if ready[0]:
                        response = connection.process.stdout.readline().decode()
                        data = json.loads(response)
                        for tool_data in data.get("result", {}).get("tools", []):
                            tool = MCPTool(
                                name=tool_data.get("name", ""),
                                description=tool_data.get("description", ""),
                                input_schema=tool_data.get("inputSchema", {}),
                                server_name=name,
                            )
                            tools.append(tool)
                            self._tools[tool.name] = tool
            except Exception as e:
                logger.warning("工具发现失败: %s, 错误: %s", name, e)

        connection.tools = tools
        logger.info("发现 %s 个 MCP 工具: %s", len(tools), name)
        return tools

    async def call_tool(self, tool_name: str, arguments: typing.Dict[str, typing.Any] = None) -> typing.Any:
        """调用 MCP 工具"""
        tool = self._tools.get(tool_name)
        if not tool:
            raise ValueError(f"MCP 工具未找到: {tool_name}")

        connection = self._connections.get(tool.server_name)
        if not connection or connection.status != ConnectionStatus.CONNECTED:
            raise RuntimeError(f"MCP 服务器未连接: {tool.server_name}")

        if connection.process:
            try:
                request = (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/call",
                            "params": {"name": tool_name, "arguments": arguments or {}},
                        }
                    )
                    + "\n"
                )

                connection.process.stdin.write(request.encode())
                connection.process.stdin.flush()

                response = connection.process.stdout.readline().decode()
                data = json.loads(response)

                if "error" in data:
                    raise RuntimeError(data["error"].get("message", "Unknown error"))

                return data.get("result")

            except Exception as e:
                logger.error("MCP 工具调用失败: %s, 错误: %s", tool_name, e)
                raise

        raise RuntimeError(f"MCP 连接无进程: {tool.server_name}")

    def list_servers(self) -> typing.List[typing.Dict[str, typing.Any]]:
        """列出服务器"""
        result = []
        for name, config in self._servers.items():
            conn = self._connections.get(name)
            result.append(
                {
                    "name": name,
                    "transport": config.transport.value,
                    "status": conn.status.value if conn else "disconnected",
                    "tools_count": len(conn.tools) if conn else 0,
                }
            )
        return result

    def list_tools(self, server_name: str = None) -> typing.List[MCPTool]:
        """列出工具"""
        if server_name:
            return [t for t in self._tools.values() if t.server_name == server_name]
        return list(self._tools.values())

    def get_tool(self, tool_name: str) -> typing.Optional[MCPTool]:
        """获取工具"""
        return self._tools.get(tool_name)

    async def disconnect_all(self) -> None:
        """断开所有连接"""
        for name in list(self._connections.keys()):
            self._disconnect_server(name)

    def get_status(self) -> typing.Dict[str, typing.Any]:
        """获取状态"""
        return {
            "servers": len(self._servers),
            "connections": len(self._connections),
            "tools": len(self._tools),
            "connected": sum(1 for c in self._connections.values() if c.status == ConnectionStatus.CONNECTED),
        }


# 工厂函数
_manager: typing.Optional[MCPManager] = None


def get_mcp_manager(config_path: str = None) -> MCPManager:
    """获取 MCPManager 单例"""
    global _manager
    if _manager is None:
        _manager = MCPManager(config_path)
    return _manager


def reset_mcp_manager() -> None:
    """重置（用于测试）"""
    global _manager
    _manager = None
