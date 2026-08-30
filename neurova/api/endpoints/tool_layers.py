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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user
from neurova.execution_engine.tool_engine import ToolEngine, ToolStatus
from neurova.security.url_guard import assert_public_url
from neurova.tool_layers.mcp_config import validate_mcp_server_config

logger = get_logger(__name__)

# P0-1：路由级鉴权——本路由可注册 stdio MCP server（本机进程派生面），
# 未认证访问等于未认证 RCE，必须整体挂 get_current_user
router = APIRouter(dependencies=[Depends(get_current_user)])

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
    transport: str = Field(default="stdio", description="传输类型: stdio/http/sse")
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


def _get_client_for(server_id: str):
    """获取 server 对应的真实客户端（bootstrap 表优先，回退进程级单例）"""
    from neurova.tool_layers.mcp_bootstrap import get_bootstrapped_clients
    from neurova.tool_layers.mcp_client import get_mcp_client

    return get_bootstrapped_clients().get(server_id) or get_mcp_client()


def _server_info_from_config(entry: Dict[str, Any], status: Dict[str, Any]) -> MCPServerInfo:
    """SharedConfigManager 配置项 + 客户端实时状态 → MCPServerInfo"""
    connected = bool(status.get("connected"))
    return MCPServerInfo(
        server_id=entry.get("id", ""),
        name=entry.get("name", entry.get("id", "")),
        url=entry.get("url", ""),
        transport=entry.get("transport", "stdio"),
        status="connected" if connected else ("error" if status.get("last_error") else "disconnected"),
        tools_count=int(status.get("tool_count", 0)),
        user_id="default",
        created_at=0,
    )


@router.get("/mcp-servers", response_model=List[MCPServerInfo])
async def list_mcp_servers():
    """列出 MCP Server（持久化配置 + 实时连接状态）"""
    from neurova.shared_config import get_shared_config_manager

    entries = get_shared_config_manager().list_mcp_servers() or []
    infos = []
    for entry in entries:
        client = _get_client_for(entry.get("id", ""))
        status = client.get_server_status(entry.get("id", ""))
        infos.append(_server_info_from_config(entry, status))
    return infos


@router.post("/mcp-servers", response_model=MCPServerInfo)
async def connect_mcp_server(
    body: MCPServerConnectRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """注册（持久化）并连接 MCP Server；失败原因可经 GET /mcp-servers 查询

    P0-1 安全门（按序裁决）：
    1. stdio 传输 = 本机进程派生面，仅限 admin 角色（403）
    2. 配置 schema 校验 + shell 拒绝表（400，指名字段）
    3. 非 admin 的 http/sse 拒绝私网/环回 URL（400）——admin 豁免，
       保住自托管 localhost MCP server 场景
    """
    import re

    from neurova.shared_config import get_shared_config_manager
    from neurova.tool_layers.mcp_client import get_mcp_client

    role = str(current_user.get("role") or "user")
    sid = re.sub(r"\W+", "_", body.name or "").strip("_") or str(uuid.uuid4())
    config = {
        "id": sid,
        "name": body.name,
        "transport": body.transport or "",
        "url": body.url,
        "command": body.command or "",
        "args": body.args,
        "env": body.env,
        "enabled": True,
    }

    # P0-4 修正：先校验拿归一化 transport，门禁按归一化值裁决——transport
    # 省略时按 command/url 推断为 stdio，查原始字符串会漏掉推断路径
    try:
        config = validate_mcp_server_config(config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if config["transport"] == "stdio" and role != "admin":
        raise HTTPException(
            status_code=403,
            detail="stdio 传输需要管理员角色（stdio MCP server 由本机派生进程执行）",
        )

    if role != "admin" and config.get("transport") in ("http", "sse"):
        try:
            assert_public_url(config.get("url") or "")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"MCP server url 被拒绝: {e}")

    # 持久化（内部做严格 schema 校验，非法返回 False）
    if not get_shared_config_manager().add_mcp_server(config):
        if get_shared_config_manager().get_mcp_server(sid) is None:
            raise HTTPException(status_code=400, detail="MCP Server 配置非法或已存在")

    client = get_mcp_client()
    ok = await client.connect_server(sid, config)
    status = client.get_server_status(sid)
    if not ok:
        logger.warning("MCP Server %s 连接失败: %s", sid, status.get("last_error"))

    return MCPServerInfo(
        server_id=sid,
        name=body.name,
        url=body.url,
        transport=config["transport"],
        status="connected" if ok else "error",
        tools_count=int(status.get("tool_count", 0)),
        user_id="default",
        created_at=time.time(),
    )


@router.delete("/mcp-servers/{server_id}")
async def disconnect_mcp_server(server_id: str):
    """断开 MCP Server 并移除持久化配置"""
    from neurova.shared_config import get_shared_config_manager

    client = _get_client_for(server_id)
    removed = await client.disconnect_server(server_id)
    get_shared_config_manager().remove_mcp_server(server_id)
    if not removed:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    return {"code": 0, "message": "MCP Server disconnected"}


@router.get("/mcp-servers/{server_id}/tools", response_model=List[ToolInfo])
async def list_mcp_tools(server_id: str):
    """查看 MCP Server 提供的工具（真实工具清单）"""
    client = _get_client_for(server_id)
    status = client.get_server_status(server_id)
    if status.get("last_error") == "not registered":
        raise HTTPException(status_code=404, detail="MCP Server not found")

    tools = await client.get_available_tools(server_id)
    return [
        ToolInfo(
            tool_id=f"mcp.{server_id}.{t.get('name', '')}",
            name=t.get("name", ""),
            description=t.get("description", ""),
            source="mcp",
            parameters=t.get("parameters") or {},
            server_id=server_id,
        )
        for t in tools
    ]


@router.get("/tools", response_model=List[ToolInfo])
async def list_all_tools(source: Optional[str] = Query(default=None)):
    """列出所有可用工具

    聚合多源工具：ToolEngine（动态注册）+ agent._builtin_tools（内置工具）。
    支持按来源过滤。ToolEngine 为空时仍返回内置工具列表。
    """
    engine = get_tool_engine()
    tools = []
    seen_tool_ids = set()  # 按 tool_id 去重

    # 源 1：从 ToolEngine 获取动态注册的工具
    tool_definitions = engine.list_tools(status=ToolStatus.AVAILABLE)
    for tool_def in tool_definitions:
        # 确定工具来源
        tool_source = "builtin"
        if tool_def.is_public:
            tool_source = "public"
        elif tool_def.owner:
            tool_source = "user"

        if tool_def.name not in seen_tool_ids:
            seen_tool_ids.add(tool_def.name)
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

    # 源 2：从 agent._builtin_tools 获取内置工具（BuiltinToolRegistry）
    # 当 ToolEngine 未注册内置工具时，这是唯一的工具来源
    try:
        from neurova.api.endpoints import get_agent_instance

        agent = get_agent_instance()
        if agent and hasattr(agent, "_builtin_tools") and agent._builtin_tools:
            for builtin_tool in agent._builtin_tools.list_tools():
                if builtin_tool.name not in seen_tool_ids:
                    seen_tool_ids.add(builtin_tool.name)
                    tools.append(
                        ToolInfo(
                            tool_id=builtin_tool.name,
                            name=builtin_tool.name,
                            description=builtin_tool.description,
                            source="builtin",
                            parameters=builtin_tool.parameters,
                            server_id=None,
                        )
                    )
    except Exception as e:
        logger.debug("获取 agent 内置工具列表失败: %s", e)

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
            # 检查执行结果是否包含 error 字段（工具执行失败）
            # 避免把 {error: ...} 当作成功结果返回 code:0，导致前端误显示成功
            if isinstance(result, dict) and "error" in result:
                return {
                    "code": 1,
                    "error": result["error"],
                    "data": {"execution_time": time.time() - start},
                }
            return {"code": 0, "data": {"result": result, "execution_time": time.time() - start}}
    except Exception as e:
        logger.warning("Tool execution via agent failed: %s", e)

    # 所有执行路径失败 → 返回明确错误（不再返回 simulated 假成功）
    return {
        "code": 1,
        "error": f"工具 '{body.tool_name}' 执行失败：未找到可用执行路径",
        "data": {"execution_time": time.time() - start},
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
