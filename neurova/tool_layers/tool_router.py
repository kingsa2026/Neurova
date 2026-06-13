"""
Tool Router v1.0.0 — 统一工具路由器

职责:
- 聚合内置工具 + Skill 工具 + MCP 外购工具
- 架构 Agent 的工具调用请求
- Agent 视角下所有工具无差别

隔离层级: 全局单例（无资源由各来源的隔离层控制）
"""

import asyncio
import datetime
import logging
import typing
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class _SkillToolProxy:
    """Skill 工具代理 — 包装 Skill 使其可被 ToolRouter 路由"""

    name: str
    skill_name: str
    is_skill: bool = True
    is_mcp: bool = False
    source: str = "skill"
    description: str = ""
    parameters: typing.Dict[str, typing.Any] = field(default_factory=dict)


@dataclass
class _MCPToolProxy:
    """MCP 工具代理 — 包装 MCP 工具使其可被 ToolRouter 路由"""

    name: str
    server_id: str
    is_mcp: bool = True
    is_skill: bool = False
    source: str = "mcp"
    description: str = ""
    parameters: typing.Dict[str, typing.Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """工具执行结果"""

    success: bool
    result: typing.Any = None
    error: typing.Optional[str] = None
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.success


class ToolRouter:
    """
    统一工具路由器

    负责聚合和管理所有工具来源，包括：
    - 内置工具 (builtin)
    - Skill 工具 (skill)
    - MCP 外部工具 (mcp)

    为 Agent 提供统一的工具调用接口。
    """

    def __init__(self):
        """初始化工具路由器"""
        self._builtin_tools: typing.Dict[str, typing.Any] = {}
        self._skill_manager: typing.Optional[typing.Any] = None
        self._execution_engine: typing.Optional[typing.Any] = None
        self._mcp_clients: typing.Dict[str, typing.Any] = {}
        self._mcp_configs: typing.Dict[str, typing.Dict] = {}
        self._tool_metadata: typing.Dict[str, typing.Dict] = {}

    def register_builtin(self, name: str, tool: typing.Any) -> None:
        """
        注册内置工具

        Args:
            name: 工具名称
            tool: 工具实例
        """
        self._builtin_tools[name] = tool
        self._tool_metadata[name] = {
            "source": "builtin",
            "registered_at": datetime.datetime.now().isoformat(),
        }
        logger.debug("Registered builtin tool: %s", name)

    def register_builtin_batch(self, tools: typing.Dict[str, typing.Any]) -> None:
        """
        批量注册内置工具

        Args:
            tools: 工具字典 {name: tool_instance}
        """
        for name, tool in tools.items():
            self.register_builtin(name, tool)

    def set_skill_manager(self, skill_manager: typing.Any) -> None:
        """
        设置 Skill 管理器

        Args:
            skill_manager: Skill 管理器实例
        """
        self._skill_manager = skill_manager
        logger.debug("Skill manager set")

    def set_execution_engine(self, execution_engine: typing.Any) -> None:
        """
        设置执行引擎

        Args:
            execution_engine: 执行引擎实例
        """
        self._execution_engine = execution_engine
        logger.debug("Execution engine set")

    def get_or_create_mcp(self, server_id: str, config: typing.Dict[str, typing.Any]) -> typing.Any:
        """
        获取或创建 MCP 客户端

        Args:
            server_id: MCP 服务器 ID
            config: MCP 配置

        Returns:
            MCP 客户端实例
        """
        if server_id not in self._mcp_clients:
            from neurova.tool_layers.mcp_client import MCPToolClient

            client = MCPToolClient()
            self._mcp_clients[server_id] = client
            self._mcp_configs[server_id] = config
            logger.debug("Created MCP client for server: %s", server_id)

        return self._mcp_clients[server_id]

    def get_all_tools(
        self,
        agent_id: typing.Optional[str] = None,
        user_id: typing.Optional[str] = None,
    ) -> typing.Dict[str, typing.Any]:
        """
        获取所有工具（内置 + Skill + MCP）

        Args:
            agent_id: Agent ID（保留，用于未来多租户过滤）
            user_id: 用户 ID（保留，用于未来多租户过滤）

        Returns:
            工具字典 {name: tool_instance}
        """
        result = self._builtin_tools.copy()

        # 聚合 Skill 工具
        result.update(self._discover_skill_tools())

        # 聚合 MCP 工具
        result.update(self._discover_mcp_tools())

        return result

    def _discover_skill_tools(self) -> typing.Dict[str, _SkillToolProxy]:
        """从 Skill 管理器发现 Skill 工具"""
        tools: typing.Dict[str, _SkillToolProxy] = {}
        if not self._skill_manager:
            return tools

        # 尝试从 skill_manager 获取已注册的 skill 列表
        skills = getattr(self._skill_manager, "skills", None)
        if skills is None:
            # 尝试 list_skills() 方法
            list_fn = getattr(self._skill_manager, "list_skills", None)
            if callable(list_fn):
                try:
                    skills = list_fn()
                except Exception:
                    pass

        if skills and isinstance(skills, dict):
            for skill_name, skill in skills.items():
                if skill_name not in self._builtin_tools:
                    desc = getattr(skill, "description", "") or ""
                    params = getattr(skill, "parameters", {}) or {}
                    tools[skill_name] = _SkillToolProxy(
                        name=skill_name,
                        skill_name=skill_name,
                        description=desc,
                        parameters=params,
                    )
        return tools

    def _discover_mcp_tools(self) -> typing.Dict[str, _MCPToolProxy]:
        """从 MCP 客户端发现 MCP 工具"""
        tools: typing.Dict[str, _MCPToolProxy] = {}
        for server_id, client in self._mcp_clients.items():
            # 尝试从 MCP 客户端获取工具列表
            list_tools_fn = getattr(client, "list_tools", None)
            if callable(list_tools_fn):
                try:
                    import inspect

                    if inspect.iscoroutinefunction(list_tools_fn):
                        # 异步方法，跳过（在 execute 时按需解析）
                        continue
                    mcp_tools = list_tools_fn()
                    if isinstance(mcp_tools, list):
                        for t in mcp_tools:
                            tool_name = getattr(t, "name", None) or str(t)
                            if tool_name not in self._builtin_tools:
                                desc = getattr(t, "description", "") or ""
                                params = getattr(t, "parameters", {}) or {}
                                tools[tool_name] = _MCPToolProxy(
                                    name=tool_name,
                                    server_id=server_id,
                                    description=desc,
                                    parameters=params,
                                )
                except Exception as e:
                    logger.debug("Failed to list MCP tools from %s: %s", server_id, e)
        return tools

    async def route(
        self,
        tool_name: str,
        params: typing.Dict[str, typing.Any],
        agent_id: typing.Optional[str] = None,
        user_id: typing.Optional[str] = None,
    ) -> typing.Any:
        """
        路由工具调用（execute 的别名，保持向后兼容）

        Args:
            tool_name: 工具名称
            params: 工具参数
            agent_id: Agent ID（可选）
            user_id: 用户 ID（可选）

        Returns:
            工具执行结果
        """
        result = await self.execute(tool_name, params, agent_id=agent_id, user_id=user_id)
        if result.success:
            return result.result
        else:
            raise ValueError(result.error or f"Tool execution failed: {tool_name}")

    async def execute(
        self,
        tool_name: str,
        params: typing.Dict[str, typing.Any],
        agent_id: typing.Optional[str] = None,
        user_id: typing.Optional[str] = None,
    ) -> typing.Any:
        """
        执行工具

        按优先级从三个来源解析工具:
        1. 内置工具 (_builtin_tools)
        2. Skill 工具 (_skill_manager)
        3. MCP 工具 (_mcp_clients)

        Args:
            tool_name: 工具名称
            params: 工具参数
            agent_id: Agent ID（用于多租户隔离，可选）
            user_id: 用户 ID（用于多租户隔离，可选）

        Returns:
            ToolResult: 执行结果
        """
        logger.debug("Executing tool: %s (agent_id=%s, user_id=%s)", tool_name, agent_id, user_id)

        # ── 从三个来源解析工具 ──
        tool = None
        source = None

        # 1. 内置工具
        if tool_name in self._builtin_tools:
            tool = self._builtin_tools[tool_name]
            source = "builtin"

        # 2. Skill 工具
        if tool is None and self._skill_manager:
            tool = await self._resolve_skill_tool(tool_name)
            if tool:
                source = "skill"

        # 3. MCP 工具
        if tool is None and self._mcp_clients:
            tool = await self._resolve_mcp_tool(tool_name)
            if tool:
                source = "mcp"

        # 所有来源均未找到
        if tool is None:
            return ToolResult(
                success=False,
                error=f"Tool not found: {tool_name}",
                metadata={"tool_name": tool_name, "agent_id": agent_id, "user_id": user_id},
            )

        # 注入隔离上下文到参数（如果工具支持）
        if agent_id or user_id:
            params = params.copy()
            if agent_id:
                params["_agent_id"] = agent_id
            if user_id:
                params["_user_id"] = user_id

        try:
            # 根据工具类型选择执行方式
            if hasattr(tool, "is_mcp") and tool.is_mcp:
                result = await self._execute_mcp(tool, params)
            elif hasattr(tool, "is_skill") and tool.is_skill:
                result = await self._execute_skill(tool, params)
            elif self._execution_engine:
                result = await self._execute_engine(tool, params)
            else:
                result = await self._execute_builtin(tool, params)

            return ToolResult(
                success=True,
                result=result,
                metadata={"tool_name": tool_name, "source": source, "agent_id": agent_id, "user_id": user_id},
            )
        except KeyError as e:
            logger.error("Tool not found during execution: %s", tool_name)
            return ToolResult(
                success=False,
                error=f"Tool not found: {tool_name}",
                metadata={"tool_name": tool_name, "source": source, "agent_id": agent_id, "user_id": user_id},
            )
        except Exception as e:
            logger.error("Tool execution failed: %s, %s", tool_name, e)
            return ToolResult(
                success=False,
                error=str(e),
                metadata={"tool_name": tool_name, "source": source, "agent_id": agent_id, "user_id": user_id},
            )

    async def _resolve_skill_tool(self, tool_name: str) -> typing.Optional[_SkillToolProxy]:
        """
        从 Skill 管理器解析工具

        Args:
            tool_name: 工具名称

        Returns:
            Skill 工具代理，未找到返回 None
        """
        if not self._skill_manager:
            return None

        # 尝试 has_skill() 检查
        has_skill_fn = getattr(self._skill_manager, "has_skill", None)
        if callable(has_skill_fn):
            try:
                if not has_skill_fn(tool_name):
                    return None
            except Exception:
                return None
        else:
            # 回退：检查 skills 字典
            skills = getattr(self._skill_manager, "skills", None)
            if not skills or tool_name not in skills:
                return None

        # 获取 skill 详情
        skill = None
        skills = getattr(self._skill_manager, "skills", {})
        if skills and tool_name in skills:
            skill = skills[tool_name]

        desc = ""
        params = {}
        if skill:
            desc = getattr(skill, "description", "") or ""
            params = getattr(skill, "parameters", {}) or {}

        return _SkillToolProxy(
            name=tool_name,
            skill_name=tool_name,
            description=desc,
            parameters=params,
        )

    async def _resolve_mcp_tool(self, tool_name: str) -> typing.Optional[_MCPToolProxy]:
        """
        从 MCP 客户端解析工具

        逐个扫描已连接的 MCP 服务器，查找匹配的工具。

        Args:
            tool_name: 工具名称

        Returns:
            MCP 工具代理，未找到返回 None
        """
        for server_id, client in self._mcp_clients.items():
            list_tools_fn = getattr(client, "list_tools", None)
            if not callable(list_tools_fn):
                continue

            try:
                import inspect

                if inspect.iscoroutinefunction(list_tools_fn):
                    mcp_tools = await list_tools_fn()
                else:
                    mcp_tools = list_tools_fn()

                if not isinstance(mcp_tools, list):
                    continue

                for t in mcp_tools:
                    t_name = getattr(t, "name", None) or str(t)
                    if t_name == tool_name:
                        desc = getattr(t, "description", "") or ""
                        params = getattr(t, "parameters", {}) or {}
                        return _MCPToolProxy(
                            name=tool_name,
                            server_id=server_id,
                            description=desc,
                            parameters=params,
                        )
            except Exception as e:
                logger.debug("Failed to scan MCP tools from %s: %s", server_id, e)

        return None

    async def _execute_mcp(self, tool: typing.Any, params: typing.Dict[str, typing.Any]) -> typing.Any:
        """
        执行 MCP 工具

        Args:
            tool: MCP 工具实例（需有 server_id 和 name 属性）
            params: 工具参数

        Returns:
            执行结果
        """
        server_id = getattr(tool, "server_id", None) or getattr(tool, "source", None)
        if not server_id or server_id not in self._mcp_clients:
            raise ValueError(f"MCP client not found for server: {server_id}")

        client = self._mcp_clients[server_id]
        # MCPToolClient 使用 execute_tool(server_id, tool_name, params)
        return await client.execute_tool(server_id, tool.name, params)

    async def _execute_skill(self, tool: typing.Any, params: typing.Dict[str, typing.Any]) -> typing.Any:
        """
        执行 Skill 工具

        Args:
            tool: Skill 工具实例
            params: 工具参数

        Returns:
            执行结果
        """
        if not self._skill_manager:
            raise ValueError("Skill manager not set")

        return await self._skill_manager.execute_skill(tool.skill_name, params)

    async def _execute_engine(self, tool: typing.Any, params: typing.Dict[str, typing.Any]) -> typing.Any:
        """
        通过执行引擎执行工具

        Args:
            tool: 工具实例
            params: 工具参数

        Returns:
            执行结果
        """
        if not self._execution_engine:
            raise ValueError("Execution engine not set")

        return await self._execution_engine.execute(tool, params)

    async def _execute_builtin(self, tool: typing.Any, params: typing.Dict[str, typing.Any]) -> typing.Any:
        """
        执行内置工具

        Args:
            tool: 内置工具实例
            params: 工具参数

        Returns:
            执行结果
        """
        if hasattr(tool, "execute") and callable(tool.execute):
            if asyncio.iscoroutinefunction(tool.execute):
                return await tool.execute(params)
            else:
                return tool.execute(params)
        else:
            raise ValueError(f"Tool {tool.name} does not have an execute method")
