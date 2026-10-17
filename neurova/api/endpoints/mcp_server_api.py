"""MCP server HTTP 面（P1-5）——JSON-RPC 2.0 端点（streamable http 最小协议面）。

NeurovaMCPServer（协议无关核心）经此挂上 HTTP：initialize / tools/list /
tools/call / ping 四方法 + JSON-RPC 错误语义（-32601/-32600）+ 通知 202。
鉴权走平台既有 get_current_user_or_service（JWT/服务令牌）。

`initialize` 做协议版本协商（支持则回声所请求版本，否则回自己支持的最新版本），
支持集取官方 SDK 的握手期版本单源——此前把 "2025-03-26" 钉成字面量无条件回声，
只支持较新版本的客户端按 spec 必须断开，本面对它们不可达。
"""

from __future__ import annotations

import typing

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS as SUPPORTED_HANDSHAKE_VERSIONS
from mcp_types.version import LATEST_HANDSHAKE_VERSION

from neurova.api.auth import get_current_user_or_service
from neurova.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

_SERVER_NAME = "neurova"


def _acceptsJson(request: Request) -> bool:
    """本面只产 JSON 响应体（无 SSE 流），故要求客户端可接受 application/json。

    通配按 RFC 7231 §5.3.2 处理（`*/*` 与 `application/*` 都算接受），与官方
    服务端 JSON 响应模式的 Accept 校验同规则。
    """
    types = [
        media.strip().split(";")[0].strip().lower()
        for media in request.headers.get("accept", "").split(",")
    ]
    return "*/*" in types or "application/*" in types or "application/json" in types


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
        try:
            from neurova.skill_system import get_skill_registry

            registry = get_skill_registry()
        except Exception:  # noqa: BLE001
            registry = None
# 惰性 provider（首次 MCP 调用时 agent 可能尚未就绪，
# 每次现取 default agent；导出默认关，无 agent 时清单不含 computer_*）
        def _agent_provider():
            try:
                from neurova.api.endpoints import defaultAgentId, get_agent_instance

                return get_agent_instance(defaultAgentId())
            except Exception:  # noqa: BLE001
                return None

        _MCP_SERVER = NeurovaMCPServer(
            storage=storage, skill_registry=registry, agent_provider=_agent_provider
        )
    return _MCP_SERVER


_MCP_SERVER = None


def _text_content(text: str) -> list:
    return [{"type": "text", "text": text}]


async def _handle_tools_call(params: dict) -> dict:
    name = str(params.get("name", ""))
    arguments = params.get("arguments") or {}
    server = _get_mcp_server()
    outcome = await server.call_tool(name, dict(arguments))
    if outcome.get("isError"):
        return {"content": _text_content(str(outcome.get("error", "tool error"))), "isError": True}
    import json as _json

    payload = outcome.get("result") if "result" in outcome else outcome
    text = _json.dumps(payload, ensure_ascii=False, default=str)
    return {"content": _text_content(text)}


@router.post("")
async def mcp_http_endpoint(request: Request, current_user: typing.Any = Depends(get_current_user_or_service)):
    """JSON-RPC 2.0 单请求入口（MCP streamable http 最小面）。"""
    if not _acceptsJson(request):
        return JSONResponse(
            status_code=406,
            content={
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "Not Acceptable: Client must accept application/json"},
            },
        )
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict) or "method" not in body:
        return {
            "jsonrpc": "2.0", "id": None,
            "error": {"code": -32600, "message": "Invalid Request"},
        }

    method = str(body.get("method", ""))
    params = body.get("params") or {}
    request_id = body.get("id")

    # 通知请求（无 id）：MCP 语义 202 空响应
    if request_id is None:
        from fastapi import Response

        return Response(status_code=202)

    try:
        if method == "initialize":
            requested = params.get("protocolVersion")
            result = {
                # spec 协商规则，与官方服务端实现同形：支持所请求版本则回声它，
                # 否则回本面支持的最新版本（不把旧字面量硬塞回去）
                "protocolVersion": (
                    requested
                    if requested in SUPPORTED_HANDSHAKE_VERSIONS
                    else LATEST_HANDSHAKE_VERSION
                ),
                # 能力声明只报实际实现的 tools——升版本号不等于升能力
                "capabilities": {"tools": {}},
                "serverInfo": {"name": _SERVER_NAME, "version": "1.0.0"},
            }
        elif method == "ping":
            # spec 要求服务端必须应答 ping（健康探测）；此前落进 -32601 分支
            result = {}
        elif method == "tools/list":
            result = {"tools": _get_mcp_server().list_tools()}
        elif method == "tools/call":
            result = await _handle_tools_call(params)
        else:
            return {
                "jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as e:  # noqa: BLE001 — 协议内错误信封，不 500
        logger.warning("MCP http %s 失败: %s", method, e)
        return {
            "jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32603, "message": str(e)[:200]},
        }


__all__ = ["router"]
