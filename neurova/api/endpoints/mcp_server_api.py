"""MCP server HTTP 面（P1-5）——运输层由官方 SDK 的 streamable-http 承载（§6-339 乙案）。

`NeurovaMCPServer`（协议无关核心）仍是工具清单与调用的**唯一实现源**；本模块只负责把它
接到 HTTP 上：`mcp.server.lowlevel.Server` 的两个 handler ＋ `StreamableHTTPSessionManager`
以 `stateless=True` ＋ `json_response=True` 跑"单请求单 JSON 响应"。原先手写的那份
JSON-RPC 分派链（四方法 if/elif、自造信封、`include_router` 登记）随本批退役——
同一功能在仓内只留一处实现（教义第 7 条）。

保留的对外承诺（§6-302，由 `tests/unit/api/testMcpFaceRidesSdkTransport.py` 逐条钉住）：
协议版本协商回声/反提案、`ping` 必答、坏 Accept → 406、通知 → 202、未知方法 → -32601。
两条**改过**的语义按 §6-340 裁定执行：`initialize` 的 params 三件齐（缺则 -32602），
非信封体走 HTTP 400 但 JSON-RPC 码收成正码 -32600。

鉴权与身份：本面仍在**请求边界**写一次 `neurova_request_user_id`（§6-334 裁定甲）。
`app.mount()` 出来的子应用**不会**被父应用带 lifespan（本机 Starlette 1.7.0 现场读数：
父 app 进出 lifespan 两次，子 app 的 enter/exit 轨迹恒空），所以 `mountFace` 把 manager 的
启停挂到宿主 app 的事件上——运输形态归模块自述，装配层只问"挂上去"。
"""

from __future__ import annotations

import json
import typing

from fastapi import HTTPException
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS as SUPPORTED_HANDSHAKE_VERSIONS
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from neurova.api.auth import get_current_user_or_service, security
from neurova.core.identity_context import set_request_user_id
from neurova.core.logger import get_logger
from neurova.tool_layers.mcp_server import McpCaller

logger = get_logger(__name__)

_SERVER_NAME = "neurova"
_SERVER_VERSION = "1.0.0"

#: 本面只产 JSON 响应体；除这两个方法外的动词一律拒（见 `_McpFaceAsgi` 里那条 405）。
#: GET 必须拒的理由是实测出来的：stateless + json_response 下 GET 会开一条不结束的流，
#: 挂起面从"没有"变成"有一条"就是新缺陷。DELETE 交给 SDK 自己答 405。
_ALLOWED_METHODS = ("POST", "DELETE")


def _get_mcp_server():
    """MCP server 核心单例（测试可 patch）"""
    from neurova.tool_layers.mcp_server import NeurovaMCPServer

    global _MCP_SERVER
    if "_MCP_SERVER" not in globals() or _MCP_SERVER is None:
        try:
            from neurova.api.endpoints.neurflow_api import _get_storage

            storage = _get_storage()
        except Exception:  # noqa: BLE001 — storage 不可用时不暴露工作流面
            storage = None
        # 惰性 provider（首次 MCP 调用时 agent 可能尚未就绪，每次现取 default agent；
        # 导出默认关，无 agent 时清单既不含 computer_* 也不含 skill:*）
        def _agent_provider():
            try:
                from neurova.api.endpoints import defaultAgentId, get_agent_instance

                return get_agent_instance(defaultAgentId())
            except Exception:  # noqa: BLE001
                return None

        # 技能面不再注入第二份注册表：清单源与执行源都是上面那个 provider 现取的 agent
        # 自带的那一份（`agent._skill_registry`），构造期再给一份全局单例就是那次双源的入口
        # （台账 §6-352 的乙，判据见 tests/unit/workflow/test_mcp_server_face.py）。
        _MCP_SERVER = NeurovaMCPServer(storage=storage, agent_provider=_agent_provider)
    return _MCP_SERVER


_MCP_SERVER = None


def _listToolsHandler(caller):
    """清单逐字段交给核心——运输侧不攒第二份（教义第 6 条）。

    `caller` 从外面递进来，不在这里现取：这一发的身份是 per-request 的，
    挂到跨请求共享的核心单例上就是把上一发的授权漏进下一发。
    """

    async def _onListTools(_ctx, _params) -> ListToolsResult:
        entries = _get_mcp_server().list_tools(caller=caller)
        return ListToolsResult(tools=[
            Tool(
                name=str(entry["name"]),
                description=str(entry.get("description", "")),
                inputSchema=dict(entry.get("inputSchema") or {"type": "object", "properties": {}}),
            )
            for entry in entries
        ])

    return _onListTools


def _callToolHandler(caller):
    async def _onCallTool(_ctx, params) -> CallToolResult:
        outcome = await _get_mcp_server().call_tool(str(params.name), dict(params.arguments or {}), caller=caller)
        if outcome.get("isError"):
            return CallToolResult(
                content=[TextContent(type="text", text=str(outcome.get("error", "tool error")))],
                isError=True,
            )
        payload = outcome.get("result") if "result" in outcome else outcome
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))],
            isError=False,
        )

    return _onCallTool


def _callerPrincipal(current_user) -> McpCaller:
    """把"这一发能不能驱动这个 agent"算成**一个布尔**交给核心，口径不在这文件里定义。

    判定用的是平台唯一那份属主源 `agent_access`（admin 全量／owner 匹配／无主仅 admin），
    与 `chat` 的执行门同源——两处各写一份就必然漂移（§6-355 末那张票要的就是这个）。
    agent 身份经 `defaultAgentId()` 现取，与核心的 agent provider 同一个读点。
    """
    from neurova.api.agent_access import can_access_agent, resolve_agent_owner
    # `neurova.agent` 包 __init__ 链回 tool_executor，端点模块级 import 会拉循环（AGENTS.md §3）
    from neurova.api.endpoints import defaultAgentId
    from neurova.tool_layers.mcp_server import McpCaller

    user = current_user or {}
    userId = str(user.get("user_id") or "")
    role = str(user.get("role") or "user")
    agentId = defaultAgentId()
    return McpCaller(
        userId=userId,
        mayDriveAgent=can_access_agent(userId, role, resolve_agent_owner(agentId)),
    )


def _invalidRequestCode(body: bytes) -> bytes:
    """把 SDK 对"没构成信封"的 -32602 收成 JSON-RPC 正码 -32600（§6-340 裁定乙）。

    改写只在 HTTP 400 这条路上发生：实测 params 类 -32602 全部以 200 返回，
    所以这里**不可能**碰到裁定甲要保的那条 -32602。`data` 原样留着——JSON-RPC
    明写 data 可携带实现细节，不作诊断泄漏处理。
    """
    try:
        parsed = json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001 — 读不动就原样吐回去，不替 SDK 编造响应
        return body
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict) and error.get("code") == -32602:
        error["code"] = -32600
        error["message"] = "Invalid Request"
        return json.dumps(parsed, ensure_ascii=False).encode("utf-8")
    return body


class _StatusCodeFix:
    """ASGI `send` 包装：只截 HTTP 400 的那一条响应，其余原样透传。"""

    def __init__(self, send: Send):
        self._send = send
        self._heldStart: Message | None = None
        self._heldBody = b""

    async def __call__(self, message: Message) -> None:
        kind = message.get("type")
        if self._heldStart is None:
            if kind == "http.response.start":
                if message.get("status") != 400:
                    await self._send(message)
                    return
                self._heldStart = message
                return
            await self._send(message)
            return
        if kind == "http.disconnect":
            await self._send(message)
            return
        self._heldBody += message.get("body", b"") or b""
        if message.get("more_body"):
            return
        fixed = _invalidRequestCode(self._heldBody)
        start = dict(self._heldStart)
        start["headers"] = [
            (k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"
        ] + [(b"content-length", str(len(fixed)).encode("ascii"))]
        self._heldStart = None
        self._heldBody = b""
        await self._send(start)
        await self._send({"type": "http.response.body", "body": fixed})


def _newServer(caller=None) -> Server:
    """一份低层 server：两个 handler 全部现取核心单例，运输侧不攒第二份清单。

    `caller` 是 per-request 的授权凭据，随 closure 进来（不是挂到核心单例上）——
    §6-352 实测过的形状就是"任何持平台令牌者可对默认 agent 的执行池任意点名"。
    """
    return Server(
        _SERVER_NAME,
        version=_SERVER_VERSION,
        on_list_tools=_listToolsHandler(caller),
        on_call_tool=_callToolHandler(caller),
    )


class _McpFaceAsgi:
    """鉴权 → 身份边界 → 动词闸 → 现建一份 manager 跑这一发（顺序即承诺）。

    manager 是**每发请求新建**的，不是 app 级长驻。理由是实测出来的硬约束，不是省事：
    `StreamableHTTPSessionManager.run()` 一次性，且它内部是 anyio cancel scope，
    **进出必须在同一个 task**；而本仓 `create_app()` 返回的是缓存单例（`app.py:1368-1369`），
    同一 app 对象会被多个 TestClient portal 反复进出——上一轮留下的上下文在下一轮的
    shutdown task 里退出，当场炸 `RuntimeError: Attempted to exit cancel scope in a
    different task than it was entered in`（本批实测打红的就是 `test_channelWebhookAuthBeforeDispatch`
    那条飞书缺 token 的格）。stateless 模式本来就是"一发请求一条新运输"，把 manager 的
    生命周期收到同一发请求里，才是与它同构的接法；顺带也不再需要往宿主 app 上挂启停事件。

    鉴权复用平台那**同一对原语**：`security(request)` 解凭证（`HTTPBearer` 本身可调用，
    `auto_error=False` 时缺头返回 None 而非抛 403）、`get_current_user_or_service` 定身份。
    这里**不再解一次 Authorization**——`auth.py:559-567` 那段 docstring 写的正是
    "同求异解"的旧病（`bearer` 与 `Bearer` 把同一枚凭证分进两个租户）。
    """

    def __init__(self, serverFactory=_newServer):
        self._serverFactory = serverFactory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("method") not in _ALLOWED_METHODS:
            await JSONResponse(
                {
                    "jsonrpc": "2.0", "id": None,
                    "error": {"code": -32600, "message": "Method Not Allowed"},
                },
                status_code=405,
            )(scope, receive, send)
            return

        request = Request(scope, receive)
        try:
            current_user: typing.Any = await get_current_user_or_service(
                request, credentials=await security(request)
            )
        except HTTPException as exc:
            # 挂载的 ASGI 应用外面没有 ExceptionMiddleware 兜这一层，
            # 不自己翻译就会把 401 变成 500——信封也与 FastAPI 默认处理器保持一致。
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(
                scope, receive, send
            )
            return

        # §3 身份只有一条通道，且只在请求边界写一次；口径与 /v1/chat 同源（令牌的 user_id）。
        set_request_user_id((current_user or {}).get("user_id") or None)

        manager = StreamableHTTPSessionManager(
            app=self._serverFactory(_callerPrincipal(current_user)),
            stateless=True, json_response=True
        )
        async with manager.run():
            await manager.handle_request(scope, receive, _StatusCodeFix(send))


def mountFace(app, prefix: str, description: str) -> None:
    """把本面挂到 app 上——**挂载入口只有这一处**。

    注册表原先按 `hasattr(module, "router")` → `include_router` 认这一面，那是把
    "怎么挂"的事实写在装配层。运输换成 SDK 的 ASGI 应用后，形态只能由模块自述，
    装配层只问"挂上去"；`description` 交给 Mount 命名，免得挂载点变成一条没人认识的匿名路由。
    """
    app.mount(prefix, _McpFaceAsgi(), name=description)
