"""MCP server HTTP 面（P1-5）——JSON-RPC 2.0 端点（streamable http 最小协议面）。

NeurovaMCPServer（协议无关核心）经此挂上 HTTP：initialize / tools/list /
tools/call 三方法 + JSON-RPC 错误语义（-32601/-32600）+ 通知 202。
鉴权走平台既有 get_current_user_or_service（JWT/服务令牌）。
"""

from __future__ import annotations

import typing

from fastapi import APIRouter, Depends, Request

from neurova.api.auth import get_current_user_or_service
from neurova.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

_SERVER_NAME = "neurova"
_PROTOCOL_VERSION = "2025-03-26"


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
        _MCP_SERVER = NeurovaMCPServer(storage=storage, skill_registry=registry)
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
            result = {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": _SERVER_NAME, "version": "1.0.0"},
            }
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
