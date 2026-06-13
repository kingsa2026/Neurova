"""
MCP Client — Agent 作为 MCP 消费者

基于 Neurova 三层防火墙（L0入口/L1隔离/L2输出），
在现有 execution_engine/mcp_manager.py 基础上封装。

隔离层级: 用户层 (按 user_id 硬隔离)
"""

import asyncio
import datetime
import logging
import subprocess
import typing

logger = logging.getLogger(__name__)


class ToolNotFoundError(Exception):
    """工具未找到异常"""



class MCPToolClient:
    """
    MCP 工具客户端

    作为 MCP 协议的消费者，负责：
    - 连接和管理 MCP 服务器
    - 发现和调用 MCP 工具
    - 处理 MCP 协议通信
    - 实现安全隔离（用户层硬隔离）
    """

    def __init__(self, user_id: typing.Optional[str] = None):
        """
        初始化 MCP 工具客户端

        Args:
            user_id: 用户 ID，用于安全隔离
        """
        self._user_id = user_id or "default"
        self._servers: typing.Dict[str, typing.Dict] = {}
        self._mcp_manager: typing.Optional[typing.Any] = None
        self._firewall: typing.Optional[typing.Any] = None
        self._tool_cache: typing.Dict[str, typing.List] = {}

    def _get_mcp_manager(self) -> typing.Any:
        """
        获取 MCP 管理器（延迟加载）

        Returns:
            MCP 管理器实例
        """
        if self._mcp_manager is None:
            try:
                from neurova.execution_engine.mcp_manager import MCPManager

                self._mcp_manager = MCPManager()
            except ImportError:
                logger.warning("MCPManager not available, using mock")
                self._mcp_manager = MockMCPManager()
        return self._mcp_manager

    def _get_firewall(self) -> typing.Any:
        """
        获取防火墙（延迟加载）

        Returns:
            防火墙实例
        """
        if self._firewall is None:
            try:
                from neurova.core.firewall import Firewall

                self._firewall = Firewall()
            except ImportError:
                logger.warning("Firewall not available, using mock")
                self._firewall = MockFirewall()
        return self._firewall

    async def connect_server(self, server_id: str, config: typing.Dict[str, typing.Any]) -> bool:
        """
        连接到 MCP 服务器

        Args:
            server_id: 服务器 ID
            config: 服务器配置

        Returns:
            是否连接成功
        """
        transport = config.get("transport", "stdio")

        try:
            if transport == "stdio":
                success = await self._connect_stdio(server_id, config)
            elif transport == "sse":
                success = await self._connect_sse(server_id, config)
            elif transport == "websocket":
                success = await self._connect_websocket(server_id, config)
            else:
                raise ValueError(f"Unsupported transport: {transport}")

            if success:
                self._servers[server_id] = {
                    "config": config,
                    "connected": True,
                    "tools": [],
                    "last_connected": datetime.datetime.now().isoformat(),
                }
                logger.info("Connected to MCP server: %s", server_id)

            return success

        except Exception as e:
            logger.error("Failed to connect to MCP server %s: %s", server_id, e)
            return False

    async def _connect_stdio(self, server_id: str, config: typing.Dict[str, typing.Any]) -> bool:
        """
        通过 stdio 连接到 MCP 服务器

        Args:
            server_id: 服务器 ID
            config: 服务器配置

        Returns:
            是否连接成功
        """
        command = config.get("command")
        args = config.get("args", [])

        if not command:
            raise ValueError("Command is required for stdio transport")

        try:
            # 启动子进程
            process = subprocess.Popen(
                [command] + args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # 等待连接建立
            await asyncio.sleep(0.1)

            if process.poll() is None:
                # 进程正在运行
                self._servers[server_id] = {
                    "config": config,
                    "process": process,
                    "connected": True,
                    "tools": [],
                }
                return True
            else:
                logger.error("MCP server process exited with code: %s", process.returncode)
                return False

        except Exception as e:
            logger.error("Failed to start MCP server process: %s", e)
            return False

    async def _connect_sse(self, server_id: str, config: typing.Dict[str, typing.Any]) -> bool:
        """
        通过 SSE 连接到 MCP 服务器

        Args:
            server_id: 服务器 ID
            config: 服务器配置

        Returns:
            是否连接成功
        """
        url = config.get("url")
        if not url:
            raise ValueError("URL is required for SSE transport")

        try:
            # 这里应该实现 SSE 连接逻辑
            # 暂时使用模拟实现
            logger.info("Connecting to MCP server via SSE: %s", url)

            self._servers[server_id] = {
                "config": config,
                "connected": True,
                "tools": [],
            }

            return True

        except Exception as e:
            logger.error("Failed to connect to MCP server via SSE: %s", e)
            return False

    async def _connect_websocket(self, server_id: str, config: typing.Dict[str, typing.Any]) -> bool:
        """
        通过 WebSocket 连接到 MCP 服务器

        Args:
            server_id: 服务器 ID
            config: 服务器配置

        Returns:
            是否连接成功
        """
        url = config.get("url")
        if not url:
            raise ValueError("URL is required for WebSocket transport")

        try:
            # 这里应该实现 WebSocket 连接逻辑
            # 暂时使用模拟实现
            logger.info("Connecting to MCP server via WebSocket: %s", url)

            self._servers[server_id] = {
                "config": config,
                "connected": True,
                "tools": [],
            }

            return True

        except Exception as e:
            logger.error("Failed to connect to MCP server via WebSocket: %s", e)
            return False

    async def disconnect_server(self, server_id: str) -> bool:
        """
        断开与 MCP 服务器的连接

        Args:
            server_id: 服务器 ID

        Returns:
            是否断开成功
        """
        if server_id not in self._servers:
            logger.warning("Server not found: %s", server_id)
            return False

        server = self._servers[server_id]

        try:
            # 如果有进程，终止它
            if "process" in server:
                process = server["process"]
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()

            # 从服务器列表中移除
            del self._servers[server_id]

            # 清除工具缓存
            if server_id in self._tool_cache:
                del self._tool_cache[server_id]

            logger.info("Disconnected from MCP server: %s", server_id)
            return True

        except Exception as e:
            logger.error("Failed to disconnect from MCP server %s: %s", server_id, e)
            return False

    async def disconnect_all(self) -> None:
        """断开所有服务器连接"""
        server_ids = list(self._servers.keys())
        for server_id in server_ids:
            await self.disconnect_server(server_id)

    async def get_available_tools(self, server_id: str) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        获取 MCP 服务器上可用的工具

        Args:
            server_id: 服务器 ID

        Returns:
            工具列表
        """
        if server_id not in self._servers:
            raise ValueError(f"Server not found: {server_id}")

        server = self._servers[server_id]

        if not server.get("connected"):
            raise ValueError(f"Server not connected: {server_id}")

        # 如果有缓存的工具列表，直接返回
        if server_id in self._tool_cache:
            return self._tool_cache[server_id]

        # 否则，获取工具列表
        try:
            mcp_manager = self._get_mcp_manager()
            tools = await mcp_manager.list_tools(server_id)

            # 缓存工具列表
            self._tool_cache[server_id] = tools
            server["tools"] = tools

            # 同步 MCP 工具到 ToolEngine
            self._sync_tools_to_engine(server_id, tools)

            return tools

        except Exception as e:
            logger.error("Failed to get tools from server %s: %s", server_id, e)
            return []

    def _sync_tools_to_engine(
        self,
        server_id: str,
        tools: typing.List[typing.Dict[str, typing.Any]],
        engine: typing.Optional[typing.Any] = None,
    ) -> None:
        """将 MCP 工具同步注册到 ToolEngine

        Args:
            server_id: MCP 服务器 ID
            tools: 工具定义列表
            engine: 可选的 ToolEngine 实例，为 None 时自动创建
        """
        try:
            from neurova.execution_engine.tool_engine import ToolEngine, ToolStatus

            if engine is None:
                engine = ToolEngine()
            for tool_def in tools:
                tool_name = f"mcp.{server_id}.{tool_def.get('name', '')}"
                if not engine.get_tool(tool_name):
                    # 创建一个闭包函数作为 MCP 工具的执行函数
                    _server_id = server_id
                    _tool_name = tool_def.get("name", "")

                    # 使用 **kwargs 接收任意参数
                    # ToolEngine 会自动从函数签名推断参数定义
                    # 由于 MCP 工具的参数是动态的，我们使用 **kwargs 来接收所有参数
                    async def _mcp_executor(**kwargs) -> typing.Any:
                        # kwargs 包含 ToolEngine 准备的参数
                        # 对于 MCP 工具，我们将所有参数传递给 execute_tool
                        # 注意：如果 kwargs 为空，说明 ToolEngine 没有匹配到任何参数
                        # 这种情况下，我们传递空字典给 execute_tool
                        return await self.execute_tool(_server_id, _tool_name, kwargs)

                    engine.register_tool(
                        tool_name=tool_name,
                        tool_func=_mcp_executor,
                        description=tool_def.get("description", f"MCP tool: {_tool_name}"),
                        tags=["mcp", server_id],
                        status=ToolStatus.AVAILABLE,
                    )
                    logger.debug("Synced MCP tool to ToolEngine: %s", tool_name)
        except Exception as e:
            logger.debug("Failed to sync MCP tools to ToolEngine: %s", e)

    def list_servers(self) -> typing.List[str]:
        """
        列出所有服务器

        Returns:
            服务器 ID 列表
        """
        return list(self._servers.keys())

    async def get_server_tools(self, server_id: str) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        获取服务器工具（别名方法）

        Args:
            server_id: 服务器 ID

        Returns:
            工具列表
        """
        return await self.get_available_tools(server_id)

    async def execute_tool(self, server_id: str, tool_name: str, params: typing.Dict[str, typing.Any]) -> typing.Any:
        """
        执行 MCP 工具

        Args:
            server_id: 服务器 ID
            tool_name: 工具名称
            params: 工具参数

        Returns:
            工具执行结果

        Raises:
            ToolNotFoundError: 工具不存在
            ValueError: 服务器未连接
        """
        if server_id not in self._servers:
            raise ValueError(f"Server not found: {server_id}")

        server = self._servers[server_id]

        if not server.get("connected"):
            raise ValueError(f"Server not connected: {server_id}")

        # 检查工具是否存在
        tools = server.get("tools", [])
        tool_names = [t.get("name") for t in tools]

        if tool_name not in tool_names:
            raise ToolNotFoundError(f"Tool '{tool_name}' not found on server '{server_id}'")

        try:
            # 安全检查
            firewall = self._get_firewall()
            if firewall:
                # 检查用户权限
                if not firewall.check_permission(self._user_id, "mcp_tool", tool_name):
                    raise PermissionError(f"User {self._user_id} does not have permission to execute tool {tool_name}")

            # 执行工具
            mcp_manager = self._get_mcp_manager()
            result = await mcp_manager.execute_tool(server_id, tool_name, params)

            logger.info("Executed MCP tool: %s/%s", server_id, tool_name)
            return result

        except Exception as e:
            logger.error("Failed to execute MCP tool %s/%s: %s", server_id, tool_name, e)
            raise

    async def _execute_independent(
        self, server_id: str, tool_name: str, params: typing.Dict[str, typing.Any]
    ) -> typing.Any:
        """
        独立执行 MCP 工具（绕过管理器）

        Args:
            server_id: 服务器 ID
            tool_name: 工具名称
            params: 工具参数

        Returns:
            工具执行结果
        """
        # 这里应该实现独立的 MCP 协议执行逻辑
        # 暂时抛出 NotImplementedError
        raise NotImplementedError("Independent MCP execution not implemented")


class MockMCPManager:
    """模拟 MCP 管理器"""

    async def list_tools(self, server_id: str) -> typing.List[typing.Dict[str, typing.Any]]:
        """模拟列出工具"""
        return [
            {"name": "mock_tool_1", "description": "Mock tool 1"},
            {"name": "mock_tool_2", "description": "Mock tool 2"},
        ]

    async def execute_tool(self, server_id: str, tool_name: str, params: typing.Dict[str, typing.Any]) -> typing.Any:
        """模拟执行工具"""
        return {"result": f"Mock result for {tool_name}", "params": params}


class MockFirewall:
    """模拟防火墙"""

    def check_permission(self, user_id: str, resource_type: str, resource_id: str) -> bool:
        """模拟检查权限"""
        return True
