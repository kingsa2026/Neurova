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

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


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
        "server_id": sid, "name": body.name, "url": body.url,
        "transport": body.transport, "status": "connected",
        "tools_count": 0, "user_id": "default", "created_at": now,
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
    """列出所有可用工具"""
    tools = [
        ToolInfo(tool_id="memory_search", name="memory_search", description="搜索记忆库", source="builtin"),
        ToolInfo(tool_id="web_search", name="web_search", description="搜索互联网", source="builtin"),
        ToolInfo(tool_id="file_read", name="file_read", description="读取文件", source="builtin"),
        ToolInfo(tool_id="file_write", name="file_write", description="写入文件", source="builtin"),
        ToolInfo(tool_id="code_execution", name="code_execution", description="执行代码", source="builtin"),
    ]
    if source:
        tools = [t for t in tools if t.source == source]
    return tools


@router.post("/tools/execute")
async def execute_tool(body: ToolExecuteRequest):
    """执行工具调用"""
    start = time.time()
    # 尝试通过 Agent 执行
    try:
        from neurova.api.endpoints import get_agent_instance
        agent = get_agent_instance()
        if agent and hasattr(agent, "tool_executor"):
            result = await agent.tool_executor.execute(body.tool_name, body.arguments)
            return {"code": 0, "data": {"result": result, "execution_time": time.time() - start}}
    except Exception as e:
        logger.warning(f"Tool execution via agent failed: {e}")

    return {"code": 0, "data": {"result": f"Tool '{body.tool_name}' executed (simulated)", "execution_time": time.time() - start}}


@router.post("/tools/share")
async def share_tool(body: ShareToolRequest):
    """共享工具"""
    _shared_tools[body.tool_id] = {"tool_id": body.tool_id, "shared_with": body.target_user_id, "shared_at": time.time()}
    return {"code": 0, "message": "Tool shared"}


@router.get("/tools/shared-with-me", response_model=List[ToolInfo])
async def list_tools_shared_with_me():
    """共享给我的工具"""
    return []  # 实际应根据用户ID过滤


@router.get("/tools/public", response_model=List[ToolInfo])
async def discover_public_tools():
    """公共工具库"""
    return [
        ToolInfo(tool_id="pub_weather", name="get_weather", description="获取天气信息", source="public"),
        ToolInfo(tool_id="pub_translate", name="translate", description="翻译文本", source="public"),
    ]
