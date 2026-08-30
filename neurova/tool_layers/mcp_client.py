"""
MCP Client — Agent 作为 MCP 消费者

基于官方 mcp Python SDK（运行时可选依赖）：
- stdio / sse / streamable_http 三种传输
- initialize 握手由 SDK ClientSession 完成（Windows 兼容，无手写 JSON-RPC）
- 每 server 一个 AsyncExitStack 持有会话生命周期
- 连接/调用均受 per-server timeout_ms 约束，失败原因记录在 server["last_error"]

隔离层级: 用户层 (按 user_id 硬隔离，经 core.firewall 校验)
"""

import asyncio
import contextlib
import datetime
from neurova.core.logger import get_logger
import threading
import typing

from neurova.tool_layers.mcp_config import validate_mcp_server_config

logger = get_logger(__name__)

# 官方 mcp SDK 为可选依赖；缺失时连接失败并给出安装提示，不崩溃
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamable_http_client

    _SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - 取决于环境是否安装 mcp
    _SDK_AVAILABLE = False


class ToolNotFoundError(Exception):
    """工具未找到异常"""


class MCPToolClient:
    """
    MCP 工具客户端

    作为 MCP 协议的消费者，负责：
    - 连接和管理 MCP 服务器（stdio/sse/http）
    - 发现和调用 MCP 工具
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
        self._sessions: typing.Dict[str, typing.Any] = {}
        self._stacks: typing.Dict[str, typing.Any] = {}
        self._firewall: typing.Optional[typing.Any] = None
        self._lock = threading.RLock()

    # ── 会话生命周期（SDK 接缝，测试在此边界 mock） ──

    async def _open_session(self, server_id: str, config: typing.Dict[str, typing.Any]) -> typing.Any:
        """建立传输连接并完成 initialize 握手，返回 ClientSession。

        Raises:
            RuntimeError: mcp SDK 未安装
            Exception: 传输/握手失败（由调用方记录为 last_error）
        """
        if not _SDK_AVAILABLE:
            raise RuntimeError("mcp SDK 未安装，请执行: pip install mcp")

        stack = contextlib.AsyncExitStack()
        transport = config.get("transport", "stdio")
        try:
            if transport == "stdio":
                server_params = StdioServerParameters(
                    command=config["command"],
                    args=list(config.get("args") or []),
                    env=dict(config["env"]) if config.get("env") else None,
                    cwd=config.get("cwd"),
                )
                read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
            elif transport == "sse":
                read_stream, write_stream = await stack.enter_async_context(
                    sse_client(config["url"], headers=config.get("headers") or {})
                )
            elif transport == "http":
                import httpx

                http_client = httpx.AsyncClient(headers=config.get("headers") or {})
                await stack.enter_async_context(http_client)
                read_stream, write_stream, _ = await stack.enter_async_context(
                    streamable_http_client(config["url"], http_client)
                )
            else:
                raise ValueError(f"不支持的 transport: {transport}")

            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise

        self._stacks[server_id] = stack
        return session

    async def connect_server(self, server_id: str, config: typing.Dict[str, typing.Any]) -> bool:
        """
        连接到 MCP 服务器

        统一返回 bool：失败原因记录到 server["last_error"]（可经 get_server_status 查询），
        配置非法同样返回 False 并记录原因，不抛异常。

        Args:
            server_id: 服务器 ID
            config: 服务器配置

        Returns:
            是否连接成功
        """
        with self._lock:
            self._servers[server_id] = {
                "config": {},
                "connected": False,
                "tools": [],
                "last_error": None,
                "last_connected": None,
            }
        server = self._servers[server_id]

        try:
            cfg = validate_mcp_server_config(config)
        except ValueError as e:
            server["last_error"] = str(e)
            logger.error("MCP server %s 配置非法: %s", server_id, e)
            return False

        server["config"] = cfg
        if not _SDK_AVAILABLE:
            server["last_error"] = "mcp SDK 未安装，请执行: pip install mcp"
            logger.error("MCP server %s: %s", server_id, server["last_error"])
            return False

        try:
            timeout_s = cfg["timeout_ms"] / 1000
            session = await asyncio.wait_for(self._open_session(server_id, cfg), timeout=timeout_s)
        except Exception as e:
            server["last_error"] = f"{type(e).__name__}: {e}"
            self._stacks.pop(server_id, None)
            logger.error("Failed to connect to MCP server %s: %s", server_id, e)
            return False

        self._sessions[server_id] = session
        server["connected"] = True
        server["last_connected"] = datetime.datetime.now().isoformat()

        # 连接即发现：拉取工具清单并缓存（失败不视为连接失败）
        try:
            server["tools"] = await asyncio.wait_for(self._fetch_tools(server_id), timeout=timeout_s)
        except Exception as e:
            logger.warning("MCP server %s 连接成功但工具发现失败: %s", server_id, e)

        self._sync_tools_to_engine(server_id, server["tools"])
        logger.info("Connected to MCP server: %s (%d tools)", server_id, len(server["tools"]))
        return True

    async def disconnect_server(self, server_id: str) -> bool:
        """
        断开与 MCP 服务器的连接

        Args:
            server_id: 服务器 ID

        Returns:
            是否断开成功
        """
        with self._lock:
            if server_id not in self._servers:
                logger.warning("Server not found: %s", server_id)
                return False

        stack = self._stacks.pop(server_id, None)
        self._sessions.pop(server_id, None)
        del self._servers[server_id]

        if stack is not None:
            try:
                await stack.aclose()
            except Exception as e:
                logger.warning("Error closing MCP session for %s: %s", server_id, e)

        logger.info("Disconnected from MCP server: %s", server_id)
        return True

    async def disconnect_all(self) -> None:
        """断开所有服务器连接"""
        for server_id in list(self._servers.keys()):
            await self.disconnect_server(server_id)

    # ── 工具发现 ──

    @staticmethod
    def _tool_to_dict(tool: typing.Any) -> typing.Dict[str, typing.Any]:
        """SDK 工具对象 → 可序列化 dict（inputSchema 映射为 parameters）"""
        if isinstance(tool, dict):
            return tool
        return {
            "name": getattr(tool, "name", None) or str(tool),
            "description": getattr(tool, "description", "") or "",
            "parameters": getattr(tool, "inputSchema", None)
            or getattr(tool, "parameters", None)
            or {},
        }

    async def _fetch_tools(self, server_id: str) -> typing.List[typing.Dict[str, typing.Any]]:
        """通过已建立的会话拉取工具清单"""
        session = self._sessions.get(server_id)
        if session is None:
            return []
        result = await session.list_tools()
        raw = getattr(result, "tools", None)
        if raw is None:
            raw = result if isinstance(result, list) else []
        return [self._tool_to_dict(t) for t in raw]

    async def get_available_tools(self, server_id: str) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        获取 MCP 服务器上可用的工具

        缓存优先：server["tools"] 非空时直接返回，不再询问会话；
        为空且已连接时经会话拉取并入缓存。

        Args:
            server_id: 服务器 ID

        Returns:
            工具列表
        """
        server = self._servers.get(server_id)
        if server is None:
            raise ValueError(f"Server not found: {server_id}")

        if not server.get("connected"):
            return []

        if server.get("tools"):
            return list(server["tools"])

        try:
            cfg = server.get("config") or {}
            tools = await asyncio.wait_for(
                self._fetch_tools(server_id), timeout=cfg.get("timeout_ms", 30000) / 1000
            )
        except Exception as e:
            logger.error("Failed to get tools from server %s: %s", server_id, e)
            return []

        server["tools"] = tools
        self._sync_tools_to_engine(server_id, tools)
        return list(tools)

    async def get_server_tools(self, server_id: str) -> typing.List[typing.Dict[str, typing.Any]]:
        """获取服务器工具（别名方法）"""
        return await self.get_available_tools(server_id)

    def list_tools(self) -> typing.List[typing.Dict[str, typing.Any]]:
        """同步列出所有已缓存工具（附 server_id）。

        ToolRouter 工具发现与 neurflow 适配器的硬需求：调用方为同步上下文。
        """
        tools: typing.List[typing.Dict[str, typing.Any]] = []
        for server_id, server in self._servers.items():
            for tool in server.get("tools") or []:
                item = self._tool_to_dict(tool)
                item.setdefault("server_id", server_id)
                tools.append(item)
        return tools

    def list_servers(self) -> typing.Dict[str, typing.Dict]:
        """
        列出所有服务器

        Returns:
            {server_id: server 信息} 字典
        """
        return dict(self._servers)

    def get_server_status(self, server_id: str) -> typing.Dict[str, typing.Any]:
        """查询服务器状态（含失败原因，供 API/诊断使用）"""
        server = self._servers.get(server_id)
        if server is None:
            return {
                "server_id": server_id,
                "connected": False,
                "last_error": "not registered",
                "tool_count": 0,
                "transport": None,
            }
        config = server.get("config") or {}
        return {
            "server_id": server_id,
            "connected": bool(server.get("connected")),
            "last_error": server.get("last_error"),
            "tool_count": len(server.get("tools") or []),
            "transport": config.get("transport"),
        }

    # ── 工具执行 ──

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        params: typing.Dict[str, typing.Any],
        user_id: typing.Optional[str] = None,
    ) -> typing.Any:
        """
        调用 MCP 工具（唯一执行入口，无存在性校验）

        P0-2（评测 M3）：防火墙校验收敛在此——ToolRouter 主路径优先走
        call_tool，检查若只放 execute_tool 会被整体绕过。
        P0-3（评测 M5）：user_id 是请求级身份（多用户共享同一 client 连接），
        未传时回退 client 构造身份——调用方应始终显式传递。

        Args:
            server_id: 服务器 ID
            tool_name: 工具名
            params: 工具参数
            user_id: 请求级用户身份（防火墙校验用）

        Returns:
            执行结果（SDK 结果已序列化；普通值原样透传）

        Raises:
            PermissionError: 防火墙拒绝
            ValueError: 服务器未注册或未连接
            TimeoutError: 超出 timeout_ms
        """
        await self._check_firewall(tool_name, user_id=user_id)

        server = self._servers.get(server_id)
        if server is None or not server.get("connected"):
            raise ValueError(f"Server not connected: {server_id}")

        session = self._sessions.get(server_id)
        if session is None:
            raise ValueError(f"MCP session not available: {server_id}")

        timeout_s = (server.get("config") or {}).get("timeout_ms", 30000) / 1000
        result = await asyncio.wait_for(session.call_tool(tool_name, params), timeout=timeout_s)
        serialized = self._serialize_result(result)
        logger.info("Executed MCP tool: %s/%s", server_id, tool_name)
        return serialized

    @staticmethod
    def _serialize_result(result: typing.Any) -> typing.Any:
        """SDK CallToolResult → 可序列化 dict；普通值原样透传"""
        content = getattr(result, "content", None)
        if content is None and not hasattr(result, "isError"):
            return result
        items = []
        for item in content or []:
            text = getattr(item, "text", None)
            if text is not None:
                items.append({"type": getattr(item, "type", "text"), "text": text})
            else:
                items.append(str(item))
        return {"content": items, "isError": bool(getattr(result, "isError", False))}

    async def execute_tool(
        self,
        server_id: str,
        tool_name: str,
        params: typing.Dict[str, typing.Any],
        user_id: typing.Optional[str] = None,
    ) -> typing.Any:
        """
        执行 MCP 工具（存在性校验 + call_tool）

        校验语义（与既有测试契约一致）：server["tools"] 键存在时校验工具存在性，
        键缺失时跳过（视为未发现清单，交由服务端裁决）。

        P0-2（评测 M3）：防火墙检查已收敛到 call_tool，此处经末尾委托
        恰好触发一次，不再重复检查。

        Args:
            server_id: 服务器 ID
            tool_name: 工具名
            params: 工具参数
            user_id: 请求级用户身份（防火墙校验用，经 call_tool）

        Returns:
            工具执行结果

        Raises:
            ToolNotFoundError: 工具不存在（仅当 "tools" 键存在时）
            PermissionError: 防火墙拒绝（经 call_tool）
            ValueError: 服务器未注册或未连接
        """
        server = self._servers.get(server_id)
        if server is None:
            raise ValueError(f"Server not found: {server_id}")

        if not server.get("connected"):
            raise ValueError(f"Server not connected: {server_id}")

        if "tools" in server:
            tool_names = {
                t.get("name") if isinstance(t, dict) else getattr(t, "name", None)
                for t in server.get("tools") or []
            }
            if tool_name not in tool_names:
                raise ToolNotFoundError(f"Tool '{tool_name}' not found on server '{server_id}'")

        return await self.call_tool(server_id, tool_name, params, user_id=user_id)

    async def _check_firewall(self, tool_name: str, user_id: typing.Optional[str] = None) -> None:
        """防火墙用户层校验（不可用时跳过，不伪造放行对象）

        P0-3：user_id 为请求级身份，优先于 client 构造身份——多用户共享
        同一 client 连接，防火墙必须按发起请求的用户裁决。
        """
        effective_user = user_id or self._user_id
        if self._firewall is None:
            try:
                from neurova.core.firewall import Firewall

                self._firewall = Firewall()
            except ImportError:
                logger.debug("Firewall not available, skipping MCP permission check")
                return
        try:
            if not self._firewall.check_permission(effective_user, "mcp_tool", tool_name):
                raise PermissionError(
                    f"User {effective_user} does not have permission to execute tool {tool_name}"
                )
        except PermissionError:
            raise
        except Exception as e:
            logger.warning("Firewall check failed for tool %s: %s", tool_name, e)

    # ── ToolEngine 同步 ──

    def _sync_tools_to_engine(
        self,
        server_id: str,
        tools: typing.List[typing.Dict[str, typing.Any]],
        engine: typing.Optional[typing.Any] = None,
    ) -> None:
        """将 MCP 工具同步注册到 ToolEngine

        命名约定 mcp.{server_id}.{tool_name}（tests/integration/test_tool_engine_integration.py 硬约束）。

        Args:
            server_id: MCP 服务器 ID
            tools: 工具定义列表
            engine: 可选的 ToolEngine 实例；为 None 时懒获取 API 层单例
                （get_tool_engine）——P0-5（M8）修复：此前新建 ToolEngine
                即弃，工具注册后被 GC，API 永远看不到 MCP 工具
        """
        try:
            from neurova.execution_engine.tool_engine import ToolEngine, ToolStatus

            if engine is None:
                # P0-5（M8）：延迟导入 API 层单例（避免模块级循环依赖），
                # 使 GET /tool-layers/tools 能列出 MCP 工具
                from neurova.api.endpoints.tool_layers import get_tool_engine

                engine = get_tool_engine()
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


_mcp_client_instance: typing.Optional[MCPToolClient] = None


def get_mcp_client(user_id: typing.Optional[str] = None) -> MCPToolClient:
    """获取进程级 MCP 客户端单例（neurflow 等模块的统一入口）"""
    global _mcp_client_instance
    if _mcp_client_instance is None:
        _mcp_client_instance = MCPToolClient(user_id=user_id)
    return _mcp_client_instance


def reset_mcp_client() -> None:
    """重置单例（测试用）"""
    global _mcp_client_instance
    _mcp_client_instance = None
