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
from neurova.core.logger import get_logger
import typing
from dataclasses import dataclass, field

logger = get_logger(__name__)


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
        self._tool_executor: typing.Optional[typing.Any] = None
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

    def _unpack_skill(self, value: typing.Any) -> typing.Any:
        """从可能包装的值中提取 Skill 对象（委托到共享函数）。

        原私有逻辑已提升为 neurova.skill_system.compat.unpack_skill 自由函数，
        此方法保留为薄委托以保持调用方签名不变（lines 217/428）。
        """
        from neurova.skill_system.compat import unpack_skill
        return unpack_skill(value)

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

    def set_tool_executor(self, tool_executor: typing.Any) -> None:
        """
        设置工具执行器（用于内置工具的委托执行）

        Args:
            tool_executor: ToolExecutor 实例
        """
        self._tool_executor = tool_executor
        logger.debug("Tool executor set")

    def register_mcp_client(self, server_id: str, client: typing.Any) -> None:
        """
        显式注册 MCP 客户端（bootstrap 的统一入口）

        Args:
            server_id: MCP 服务器 ID
            client: MCPToolClient 实例（需提供同步 list_tools 与 call_tool/execute_tool）
        """
        self._mcp_clients[server_id] = client
        logger.debug("Registered MCP client for server: %s", server_id)

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
                    logger.exception("list_skills() 调用失败")

        if skills and isinstance(skills, dict):
            for skill_name, skill in skills.items():
                # 候选 2: 元组解包收敛到 _unpack_skill helper(原 V2-2 内联逻辑)
                skill = self._unpack_skill(skill)
                if skill_name not in self._builtin_tools:
                    desc = getattr(skill, "description", "") or ""
                    params = getattr(skill, "parameters", {}) or {}
                    tools[skill_name] = _SkillToolProxy(
                        name=skill_name,
                        skill_name=skill_name,
                        description=desc,
                        parameters=params,
                    )
        elif skills and isinstance(skills, list):
            # Bug V2-2 修复:类 A SkillRegistry.list_skills() 返回 List[SkillInfo](列表),
            # 原实现只检查 isinstance(skills, dict),list 路径完全跳过,
            # Skill 工具的第二条发现路径也断。
            for skill in skills:
                # SkillInfo 对象有 name 属性
                skill_name = getattr(skill, "name", None)
                if not skill_name or skill_name in self._builtin_tools:
                    continue
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
        """从 MCP 客户端发现 MCP 工具

        命名空间名 mcp.{server_id}.{tool} 恒注册（无跨服务器冲突）；
        裸名仅在与 builtin/Skill/其他 MCP 工具无冲突时注册（不覆盖已有条目）。
        """
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
                            desc = getattr(t, "description", "") or ""
                            params = getattr(t, "parameters", {}) or {}
                            namespace_name = f"mcp.{server_id}.{tool_name}"
                            tools[namespace_name] = _MCPToolProxy(
                                name=namespace_name,
                                server_id=server_id,
                                description=desc,
                                parameters=params,
                            )
                            if tool_name not in self._builtin_tools and tool_name not in tools:
                                tools[tool_name] = _MCPToolProxy(
                                    name=tool_name,
                                    server_id=server_id,
                                    description=desc,
                                    parameters=params,
                                )
                except Exception:
                    logger.exception("Failed to list MCP tools from %s", server_id)
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

        # 注入隔离上下文到参数（builtin/skill/engine 源）。MCP 除外——
        # _user_id 是内部键，注入会泄漏给外部 server（严格 schema 会拒收）；
        # MCP 的身份经 _execute_mcp 显式穿透到防火墙（P0-3）
        if (agent_id or user_id) and getattr(tool, "is_mcp", False) is not True:
            params = params.copy()
            if agent_id:
                params["_agent_id"] = agent_id
            if user_id:
                params["_user_id"] = user_id

        try:
            # 根据工具类型选择执行方式
            # 根因修复: 严格 `is True` 判断。Mock/AsyncMock 的自动属性是 truthy Mock，
            # 旧真值判断会被击穿，把内置工具误路由到 MCP/Skill 分支。
            if getattr(tool, "is_mcp", False) is True:
                result = await self._execute_mcp(tool, params, user_id=user_id)
            elif getattr(tool, "is_skill", False) is True:
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
                logger.exception("has_skill() 检查失败: %s", tool_name)
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
            # 候选 2: 元组解包收敛到 _unpack_skill helper(原 V2-7 内联逻辑)
            skill = self._unpack_skill(skill)

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
                    # dict 容错（P0-3）：MCPToolClient.list_tools() 返回
                    # _tool_to_dict 字典，attribute-only 访问会让 bootstrap
                    # 注册的客户端在兜底解析中永远失配
                    if isinstance(t, dict):
                        t_name = t.get("name") or str(t)
                        desc = t.get("description", "") or ""
                        t_params = t.get("parameters", {}) or {}
                    else:
                        t_name = getattr(t, "name", None) or str(t)
                        desc = getattr(t, "description", "") or ""
                        t_params = getattr(t, "parameters", {}) or {}
                    # 命名空间名（mcp.{server_id}.{t_name}）或裸名均可命中；
                    # proxy.name 保存裸名——它是传给 server 的协议执行名
                    if tool_name not in (t_name, f"mcp.{server_id}.{t_name}"):
                        continue
                    return _MCPToolProxy(
                        name=t_name,
                        server_id=server_id,
                        description=desc,
                        parameters=t_params,
                    )
            except Exception:
                logger.exception("Failed to scan MCP tools from %s", server_id)

        return None

    @staticmethod
    def _accepts_kwarg(fn: typing.Any, name: str) -> bool:
        """探测可调用对象是否接受指定关键字参数（P0-3 兼容旧式客户端）。

        AsyncMock/MagicMock 无 spec 时签名为 (*args, **kwargs)——VAR_KEYWORD
        视为接受；真实旧式 bound method 无该参数则不传，避免 TypeError。
        """
        import inspect

        try:
            parameters = inspect.signature(fn).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(
            p.name == name or p.kind == inspect.Parameter.VAR_KEYWORD
            for p in parameters
        )

    async def _execute_mcp(
        self,
        tool: typing.Any,
        params: typing.Dict[str, typing.Any],
        user_id: typing.Optional[str] = None,
    ) -> typing.Any:
        """
        执行 MCP 工具

        P0-3（评测 M5）：user_id 请求级身份穿透到 client 防火墙——多用户
        共享 client 连接，防火墙必须按发起请求的用户裁决。旧式客户端不接受
        user_id 参数时按原签名调用（签名探测，不靠 TypeError 重试——那会
        造成副作用工具双重执行）。

        Args:
            tool: MCP 工具实例（需有 server_id 和 name 属性）
            params: 工具参数
            user_id: 请求级用户身份（可选）
        """
        # server_id 仅当为已注册的 str 时才采用，否则回退 source
        # 根因修复: Mock 的自动 server_id 属性是 truthy Mock 对象，旧写法直接采用导致查不到客户端
        server_id = getattr(tool, "server_id", None)
        if not isinstance(server_id, str) or server_id not in self._mcp_clients:
            server_id = getattr(tool, "source", None)
        if not server_id or server_id not in self._mcp_clients:
            raise ValueError(f"MCP client not found for server: {server_id}")

        client = self._mcp_clients[server_id]
        # 优先 call_tool(server_id, tool_name, params)（MCPToolClient 主执行入口），
        # 旧式客户端仅提供 execute_tool 时回退。
        # P0-3：仅当请求级 user_id 存在且客户端签名接受时才附加该参数——
        # 无条件传会破坏既有客户端的精确参数契约（None 也算传参）
        call_tool_fn = getattr(client, "call_tool", None)
        if callable(call_tool_fn):
            if user_id is not None and self._accepts_kwarg(call_tool_fn, "user_id"):
                return await call_tool_fn(server_id, tool.name, params, user_id=user_id)
            return await call_tool_fn(server_id, tool.name, params)
        execute_tool_fn = getattr(client, "execute_tool", None)
        if callable(execute_tool_fn):
            if user_id is not None and self._accepts_kwarg(execute_tool_fn, "user_id"):
                return await execute_tool_fn(server_id, tool.name, params, user_id=user_id)
            return await execute_tool_fn(server_id, tool.name, params)
        raise ValueError(f"MCP client for server '{server_id}' has no callable tool entry")

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

        # [BUGFIX] BuiltinTool 是纯数据类，没有 execute() 方法
        # 委托给 ToolExecutor 执行（它有完整的 builtin tool 实现）
        if self._tool_executor and hasattr(tool, "name"):
            try:
                return await self._tool_executor._execute_builtin_tool(tool.name, params)
            except Exception as e:
                logger.warning("ToolExecutor builtin 执行失败: %s, %s", tool.name, e)
                raise

        raise ValueError(f"Tool {getattr(tool, 'name', '?')} does not have an execute method and no tool_executor available")
