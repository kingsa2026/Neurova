"""
Tool Layers API

MCP Client、Tool Router 管理接口:
- GET    /v1/tool-layers/mcp-servers              列出 MCP Server
- POST   /v1/tool-layers/mcp-servers              连接 MCP Server
- DELETE /v1/tool-layers/mcp-servers/{server_id}  断开 MCP Server
- POST   /v1/tool-layers/mcp-servers/{server_id}/oauth/authorize  OAuth2 授权码流（P3-d）
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
    oauth_grant: Optional[str] = None  # config.oauth.grant_type 暴露（前端条件渲染"OAuth 授权"按钮）


class MCPServerConnectRequest(BaseModel):
    name: str = Field(..., description="Server 名称")
    url: str = Field(default="", description="Server URL")
    transport: str = Field(default="stdio", description="传输类型: stdio/http/sse")
    command: Optional[str] = Field(default=None, description="stdio 模式的命令")
    args: List[str] = Field(default_factory=list, description="stdio 模式的参数")
    env: Dict[str, str] = Field(default_factory=dict, description="环境变量")
    # http/sse 传输的附加请求头（Bearer token 走 {"Authorization": "Bearer <tok>"}）。
    # 协议层 _open_session 已消费 config.headers（httpx/sse_client），本字段补通
    # connect 请求体断点（2026-09-12 复核修复：register 弹窗 auth_token 此前无处安放）
    headers: Dict[str, str] = Field(default_factory=dict, description="http/sse 请求头")


class MCPOAuthAuthorizeRequest(BaseModel):
    timeout_s: float = Field(default=300.0, gt=0, le=3600, description="等待用户完成浏览器授权的超时（秒）")


class ToolInfo(BaseModel):
    tool_id: str
    name: str
    description: str = ""
    source: str = "builtin"
    parameters: Dict[str, Any] = {}
    server_id: Optional[str] = None
    # P2-15 声明位：True=工具声明必须沙箱执行（前端徽标数据源）；
    # None=未声明（存量行为，前端不显示徽标）
    sandbox_required: Optional[bool] = None


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
        oauth_grant=((entry.get("config") or {}).get("oauth") or {}).get("grant_type"),
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
    """注册（持久化）并连接 MCP Server；失败原因可经 GET /mcp-servers 查询。

    安全门与 catalog 安装共用 _register_mcp_server（P0-2 抽取，防两条注册路径
    漂移）：stdio 需 admin / schema+shell 校验 / 非 admin 私网 URL 拒绝。
    """
    import re

    role = str(current_user.get("role") or "user")
    sid = re.sub(r"\W+", "_", body.name or "").strip("_") or str(uuid.uuid4())
    config_raw = {
        "id": sid,
        "name": body.name,
        "transport": body.transport or "",
        "url": body.url,
        "command": body.command or "",
        "args": body.args,
        "env": body.env,
        "headers": body.headers,
        "enabled": True,
    }

    result = await _register_mcp_server(config_raw, role)
    config, ok, status = result["config"], result["connected"], result["status"]
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


async def _register_mcp_server(config_raw: Dict[str, Any], role: str) -> Dict[str, Any]:
    """MCP server 注册唯一入口（P0-2 抽取）：schema 校验 + 角色门 + 私网门 + 持久化 + 连接。

    与 connect / catalog-install 共用，避免两条平行注册路径漂移（同 schema↔分派
    表历史根因教训）。安全序（P0-1 原样迁移）：
    1. 归一化校验（未知键/shell/字段非法 → 400，指名字段）
    2. stdio = 本机进程派生面 → 仅 admin（403）
    3. 非 admin 的 http/sse 私网/环回 URL 拒绝（400）——admin 豁免保自托管
    4. 持久化（重复/非法 → 400）→ 连接（失败也返回 error 态，原因可查）
    """
    from neurova.shared_config import get_shared_config_manager
    from neurova.tool_layers.mcp_client import get_mcp_client

    try:
        config = validate_mcp_server_config(config_raw)
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

    sid = config["id"]
    if not get_shared_config_manager().add_mcp_server(config):
        if get_shared_config_manager().get_mcp_server(sid) is None:
            raise HTTPException(status_code=400, detail="MCP Server 配置非法或已存在")

    client = get_mcp_client()
    ok = await client.connect_server(sid, config)
    status = client.get_server_status(sid)
    if not ok:
        logger.warning("MCP Server %s 连接失败: %s", sid, status.get("last_error"))

    return {"config": config, "connected": ok, "status": status}


@router.get("/mcp-catalog")
async def list_mcp_catalog():
    """MCP 白名单目录（P0-2）：精选能力包清单（不触发安装）。"""
    from neurova.tool_layers.mcp_catalog import list_catalog

    return list_catalog()


class MCPCatalogInstallRequest(BaseModel):
    secrets: Dict[str, str] = Field(default_factory=dict, description="目录条目所需密钥（进 env，不落 args/日志）")


@router.post("/mcp-catalog/{entry_id}/install", response_model=MCPServerInfo)
async def install_mcp_catalog_server(
    entry_id: str,
    body: MCPCatalogInstallRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """一键安装白名单 MCP server（P0-2）。

    目录条目 → build_server_config → 与 connect 端点同一注册入口
    （_register_mcp_server）：stdio 需 admin、schema/私网门、持久化、连接。
    """
    from neurova.tool_layers.mcp_catalog import build_server_config

    role = str(current_user.get("role") or "user")
    try:
        config_raw = build_server_config(entry_id, body.secrets)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"目录中不存在: {entry_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = await _register_mcp_server(config_raw, role)
    except HTTPException as e:
        if e.status_code == 400 and "已存在" in str(e.detail):
            raise HTTPException(status_code=409, detail="该工具包已安装，请先卸载或改用手动配置")
        raise

    config, ok, status = result["config"], result["connected"], result["status"]
    return MCPServerInfo(
        server_id=config["id"],
        name=config["name"],
        url=config.get("url", ""),
        transport=config["transport"],
        status="connected" if ok else "error",
        tools_count=int(status.get("tool_count", 0)),
        user_id="default",
        created_at=time.time(),
    )


@router.post("/mcp-servers/{server_id}/oauth/authorize")
async def authorize_mcp_oauth(server_id: str, body: Optional[MCPOAuthAuthorizeRequest] = None):
    """MCP OAuth2 授权码流：打开浏览器完成授权 → 环回回调换 token → 入缓存。

    仅支持 config.oauth.grant_type=authorization_code 的 server；
    client_credentials 流无需浏览器（call_tool 时自动按需取 token）。
    """
    from neurova.shared_config import get_shared_config_manager
    from neurova.tool_layers.mcp_oauth import (
        OAuthTokenError,
        run_authorization_code_flow,
    )

    entry = get_shared_config_manager().get_mcp_server(server_id)
    if not entry:
        raise HTTPException(status_code=404, detail="MCP Server not found")

    oauth_config = (entry.get("config") or {}).get("oauth") or {}
    if not oauth_config:
        raise HTTPException(
            status_code=400,
            detail="该 server 未配置 OAuth（config.oauth 缺失）；仅 authorization_code 流需要浏览器授权",
        )
    if (oauth_config.get("grant_type") or "client_credentials") != "authorization_code":
        raise HTTPException(
            status_code=400,
            detail="仅 grant_type=authorization_code 需要浏览器授权；client_credentials 由工具调用时自动获取",
        )

    timeout_s = body.timeout_s if body else 300.0
    try:
        token = await run_authorization_code_flow(server_id, oauth_config, timeout_s=timeout_s)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OAuthTokenError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info("MCP OAuth 授权完成: server=%s", server_id)
    return {"status": "authorized", "server_id": server_id, "token_hint": (token[:6] + "...") if token else ""}


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


@router.post("/mcp-servers/{server_id}/test", response_model=MCPServerInfo)
async def test_mcp_server(server_id: str):
    """连接测试：对持久化配置重新连接并返回实时状态（前端"刷新"按钮的真实语义）。

    复核补全 2026-09-12：前端 ToolLayerPage 一直在调用本端点，后端从未实现
    （404 静默）——契约错位属预存缺陷，纳入本批闭环。
    """
    from neurova.shared_config import get_shared_config_manager
    from neurova.tool_layers.mcp_client import get_mcp_client

    entry = get_shared_config_manager().get_mcp_server(server_id)
    if not entry:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    try:
        config = validate_mcp_server_config(entry)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"持久化配置已非法: {e}")

    client = get_mcp_client()
    ok = await client.connect_server(server_id, config)
    status = client.get_server_status(server_id)
    if not ok:
        logger.warning("MCP Server %s 连接测试失败: %s", server_id, status.get("last_error"))
    return MCPServerInfo(
        server_id=server_id,
        name=config["name"],
        url=config.get("url", ""),
        transport=config["transport"],
        status="connected" if ok else "error",
        tools_count=int(status.get("tool_count", 0)),
        user_id="default",
        created_at=time.time(),
    )


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
                            sandbox_required=getattr(builtin_tool, "sandbox_required", None),
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
