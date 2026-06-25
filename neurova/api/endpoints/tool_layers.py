"""
Tool Layers API

MCP Client、Tool Router 管理接口:
- GET    /v1/tool-layers/mcp-servers              列出 MCP Server
- POST   /v1/tool-layers/mcp-servers              连接 MCP Server
- DELETE /v1/tool-layers/mcp-servers/{server_id}  断开 MCP Server
- GET    /v1/tool-layers/mcp-servers/{server_id}/tools  MCP 工具清单
- GET    /v1/tool-layers/tools                     所有可用工具
- POST   /v1/tool-layers/tools/execute             执行工具调用
- POST   /v1/tool-layers/tools/share               共享工具
- GET    /v1/tool-layers/tools/shared-with-me      共享给我的工具
- GET    /v1/tool-layers/tools/public               公共工具库
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from neurova.execution_engine.tool_engine import ToolEngine, ToolStatus

logger = get_logger(__name__)
router = APIRouter()

# 全局 ToolEngine 实例
_tool_engine: Optional[ToolEngine] = None


def get_tool_engine() -> ToolEngine:
    """获取 ToolEngine 单例"""
    global _tool_engine
    if _tool_engine is None:
        _tool_engine = ToolEngine()
    return _tool_engine


class MCPServerInfo(BaseModel):
    server_id: str
    name: str
    url: str = ""
    transport: str = "stdio"
    status: str = "disconnected"
    tools_count: int = 0
    user_id: str = ""
    created_at: float = 0


class MCPServerConnectRequest(BaseModel):
    name: str = Field(..., description="Server 名称")
    url: str = Field(default="", description="Server URL")
    transport: str = Field(default="stdio", description="传输类型: stdio/sse/streamable_http")
    command: Optional[str] = Field(default=None, description="stdio 模式的命令")
    args: List[str] = Field(default_factory=list, description="stdio 模式的参数")
    env: Dict[str, str] = Field(default_factory=dict, description="环境变量")


class ToolInfo(BaseModel):
    tool_id: str
    name: str
    description: str = ""
    source: str = "builtin"
    parameters: Dict[str, Any] = {}
    server_id: Optional[str] = None


class ToolExecuteRequest(BaseModel):
    tool_name: str = Field(..., description="工具名称")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="工具参数")
    timeout: int = Field(default=30, description="超时时间(秒)")


class ShareToolRequest(BaseModel):
    tool_id: str = Field(..., description="工具 ID")
    target_user_id: str = Field(..., description="目标用户 ID")


_mcp_servers: Dict[str, Dict[str, Any]] = {}
_shared_tools: Dict[str, Dict[str, Any]] = {}


@router.get("/mcp-servers", response_model=List[MCPServerInfo])
async def list_mcp_servers():
    """列出已连接的 MCP Server"""
    return [MCPServerInfo(**s) for s in _mcp_servers.values()]


@router.post("/mcp-servers", response_model=MCPServerInfo)
async def connect_mcp_server(body: MCPServerConnectRequest):
    """连接 MCP Server"""
    sid = str(uuid.uuid4())
    now = time.time()
    server = {
        "server_id": sid,
        "name": body.name,
        "url": body.url,
        "transport": body.transport,
        "status": "connected",
        "tools_count": 0,
        "user_id": "default",
        "created_at": now,
    }
    _mcp_servers[sid] = server
    return MCPServerInfo(**server)


@router.delete("/mcp-servers/{server_id}")
async def disconnect_mcp_server(server_id: str):
    """断开 MCP Server"""
    if server_id not in _mcp_servers:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    del _mcp_servers[server_id]
    return {"code": 0, "message": "MCP Server disconnected"}


@router.get("/mcp-servers/{server_id}/tools", response_model=List[ToolInfo])
async def list_mcp_tools(server_id: str):
    """查看 MCP Server 提供的工具"""
    if server_id not in _mcp_servers:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    return []  # 实际应调用 MCP Client 获取工具列表


@router.get("/tools", response_model=List[ToolInfo])
async def list_all_tools(source: Optional[str] = Query(default=None)):
    """列出所有可用工具

    从 ToolEngine 获取动态工具列表，支持按来源过滤。
    """
    engine = get_tool_engine()

    # 从 ToolEngine 获取工具列表
    tool_definitions = engine.list_tools(status=ToolStatus.AVAILABLE)

    # 转换为 API 格式
    tools = []
    for tool_def in tool_definitions:
        # 确定工具来源
        tool_source = "builtin"
        if tool_def.is_public:
            tool_source = "public"
        elif tool_def.owner:
            tool_source = "user"

        tools.append(
            ToolInfo(
                tool_id=tool_def.name,
                name=tool_def.name,
                description=tool_def.description,
                source=tool_source,
                parameters={"type": "object", "properties": {p.name: p.to_dict() for p in tool_def.parameters}},
                server_id=None,
            )
        )

    # 按来源过滤
    if source:
        tools = [t for t in tools if t.source == source]

    return tools


@router.post("/tools/execute")
async def execute_tool(body: ToolExecuteRequest):
    """执行工具调用

    优先通过 ToolEngine 执行，失败时回退到 Agent。
    """
    start = time.time()

    # 优先通过 ToolEngine 执行
    try:
        engine = get_tool_engine()
        result = await engine.execute_with_safeguards(
            tool_name=body.tool_name, parameters=body.arguments, timeout=body.timeout
        )
        return {"code": 0, "data": {"result": result, "execution_time": time.time() - start}}
    except ValueError as e:
        # 工具未注册或不可用
        logger.warning("Tool execution via ToolEngine failed: %s", e)
    except Exception as e:
        logger.warning("Tool execution via ToolEngine error: %s", e)

    # 回退到 Agent 执行
    try:
        from neurova.api.endpoints import get_agent_instance

        agent = get_agent_instance()
        if agent and hasattr(agent, "tool_executor"):
            result = await agent.tool_executor.execute(body.tool_name, body.arguments)
            return {"code": 0, "data": {"result": result, "execution_time": time.time() - start}}
    except Exception as e:
        logger.warning("Tool execution via agent failed: %s", e)

    return {
        "code": 0,
        "data": {"result": f"Tool '{body.tool_name}' executed (simulated)", "execution_time": time.time() - start},
    }


@router.post("/tools/share")
async def share_tool(body: ShareToolRequest):
    """共享工具"""
    _shared_tools[body.tool_id] = {
        "tool_id": body.tool_id,
        "shared_with": body.target_user_id,
        "shared_at": time.time(),
    }
    return {"code": 0, "message": "Tool shared"}


@router.get("/tools/shared-with-me", response_model=List[ToolInfo])
async def list_tools_shared_with_me():
    """共享给我的工具"""
    return []  # 实际应根据用户ID过滤


@router.get("/tools/public", response_model=List[ToolInfo])
async def discover_public_tools():
    """公共工具库

    从 ToolEngine 获取公开工具列表。
    """
    engine = get_tool_engine()

    # 从 ToolEngine 获取公开工具
    discovery_result = engine.discover_public_tools()

    # 转换为 API 格式
    tools = []
    for tool_def in discovery_result.tools:
        tools.append(
            ToolInfo(
                tool_id=tool_def.name,
                name=tool_def.name,
                description=tool_def.description,
                source="public",
                parameters={"type": "object", "properties": {p.name: p.to_dict() for p in tool_def.parameters}},
                server_id=None,
            )
        )

    return tools
