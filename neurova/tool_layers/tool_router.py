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
        logger.debug(f"Registered builtin tool: {name}")
    
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
            logger.debug(f"Created MCP client for server: {server_id}")
        
        return self._mcp_clients[server_id]
    
    def get_all_tools(self) -> typing.Dict[str, typing.Any]:
        """
        获取所有工具
        
        Returns:
            工具字典 {name: tool_instance}
        """
        return self._builtin_tools.copy()
    
    async def execute(
        self, 
        tool_name: str, 
        params: typing.Dict[str, typing.Any],
        agent_id: typing.Optional[str] = None,
        user_id: typing.Optional[str] = None,
    ) -> typing.Any:
        """
        执行工具
        
        Args:
            tool_name: 工具名称
            params: 工具参数
            agent_id: Agent ID（用于多租户隔离，可选）
            user_id: 用户 ID（用于多租户隔离，可选）
            
        Returns:
            工具执行结果
            
        Returns:
            ToolResult: 执行结果
        """
        logger.debug(f"Executing tool: {tool_name} (agent_id={agent_id}, user_id={user_id})")
        
        # 检查工具是否存在
        if tool_name not in self._builtin_tools:
            return ToolResult(
                success=False,
                error=f"Tool not found: {tool_name}",
                metadata={"tool_name": tool_name, "agent_id": agent_id, "user_id": user_id},
            )
        
        tool = self._builtin_tools[tool_name]
        
        # 注入隔离上下文到参数（如果工具支持）
        if agent_id or user_id:
            params = params.copy()
            if agent_id:
                params["_agent_id"] = agent_id
            if user_id:
                params["_user_id"] = user_id
        
        try:
            # 根据工具类型选择执行方式
            if hasattr(tool, 'is_mcp') and tool.is_mcp:
                result = await self._execute_mcp(tool, params)
            elif hasattr(tool, 'is_skill') and tool.is_skill:
                result = await self._execute_skill(tool, params)
            elif self._execution_engine:
                result = await self._execute_engine(tool, params)
            else:
                result = await self._execute_builtin(tool, params)
            
            return ToolResult(
                success=True,
                result=result,
                metadata={"tool_name": tool_name, "agent_id": agent_id, "user_id": user_id},
            )
        except KeyError as e:
            logger.error(f"Tool not found: {tool_name}")
            return ToolResult(
                success=False,
                error=f"Tool not found: {tool_name}",
                metadata={"tool_name": tool_name, "agent_id": agent_id, "user_id": user_id},
            )
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name}, {e}")
            return ToolResult(
                success=False,
                error=str(e),
                metadata={"tool_name": tool_name, "agent_id": agent_id, "user_id": user_id},
            )
    
    async def _execute_mcp(self, tool: typing.Any, params: typing.Dict[str, typing.Any]) -> typing.Any:
        """
        执行 MCP 工具
        
        Args:
            tool: MCP 工具实例
            params: 工具参数
            
        Returns:
            执行结果
        """
        server_id = tool.source
        if server_id not in self._mcp_clients:
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
        if hasattr(tool, 'execute') and callable(tool.execute):
            if asyncio.iscoroutinefunction(tool.execute):
                return await tool.execute(params)
            else:
                return tool.execute(params)
        else:
            raise ValueError(f"Tool {tool.name} does not have an execute method")
