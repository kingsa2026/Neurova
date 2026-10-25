"""MCP 信息源 API（B 方案）：外部 MCP server 作为知识库信息源的登记/拉取面。

写面仅管理员；endpoint 走 SSRF 校验（url_guard 单源）；拉取链的
fetchViaSession/openSourceSession 经模块级引用注入 pullFromSource——
测试 patch 本模块命名空间即可打穿，不需要起真 HTTP server。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service
from neurova.core.logger import get_logger
from neurova.knowledge.mcp_source import (
    McpSourceStore,
    fetchViaSession,
    openSourceSession,
    probeTools,
    pullFromSource,
)
from neurova.knowledge.url_guard import validate_public_http_url

logger = get_logger(__name__)
router = APIRouter()


def _store() -> McpSourceStore:
    from neurova.knowledge.foundation import get_knowledge_fact_store

    return McpSourceStore(get_knowledge_fact_store())


def get_repository() -> Any:
    from neurova.knowledge.repository import get_knowledge_repository

    return get_knowledge_repository()


def _requireAdmin(current_user: Dict[str, Any]) -> None:
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(
            status_code=403, detail="MCP 信息源是治理动作，仅管理员可管理")


class McpSourceSpec(BaseModel):
    name: str = Field(..., min_length=1)
    endpoint: str = Field(..., min_length=1)
    auth_token: str = ""
    tool_name: str = ""
    tool_args: Dict[str, Any] = Field(default_factory=dict)
    agent_id: str = "default"
    tenant_id: str = "default"


def _checkEndpoint(endpoint: str) -> None:
    if not validate_public_http_url(endpoint):
        raise HTTPException(
            status_code=400, detail="Invalid URL: only public http(s) allowed")


@router.get("/mcp/sources")
async def list_mcp_sources(
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    items = _store().list()
    return {"code": 0, "message": "success",
            "data": {"items": items, "total": len(items)}}


@router.post("/mcp/sources")
async def register_mcp_source(
    body: McpSourceSpec, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    _requireAdmin(current_user)
    _checkEndpoint(body.endpoint)
    sourceId = _store().register(body.model_dump(),
                                 created_by=str(current_user.get("user_id") or ""))["source_id"]
    return {"code": 0, "message": "success", "data": {"source_id": sourceId}}


@router.put("/mcp/sources/{source_id}")
async def update_mcp_source(
    source_id: str, body: McpSourceSpec, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    _requireAdmin(current_user)
    _checkEndpoint(body.endpoint)
    updated = _store().update(source_id, body.model_dump())
    if updated is None:
        raise HTTPException(status_code=404, detail="信息源未登记: %s" % source_id)
    return {"code": 0, "message": "success", "data": {"source_id": source_id}}


@router.delete("/mcp/sources/{source_id}")
async def delete_mcp_source(
    source_id: str, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    _requireAdmin(current_user)
    _store().delete(source_id)
    return {"code": 0, "message": "success", "data": {"source_id": source_id}}


@router.post("/mcp/sources/{source_id}/pull")
async def pull_mcp_source(
    source_id: str, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """手动拉取：连外部 server 调工具 → 文本入知识库（dedupe/租户全链）。"""
    _requireAdmin(current_user)
    source = _store().get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="信息源未登记: %s" % source_id)
    if not source.get("tool_name"):
        raise HTTPException(
            status_code=400, detail="信息源未设置 tool_name（先做工具探测再拉取）")
    try:
        outcome = await pullFromSource(
            _store(), source, get_repository(),
            fetcher=fetchViaSession, sessionOpener=openSourceSession)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - 连接失败如实 502
        logger.warning("MCP 信息源拉取失败: %s", exc)
        raise HTTPException(status_code=502, detail="MCP 拉取失败: %s" % exc)
    return {"code": 0, "message": "success", "data": outcome}


class McpProbeRequest(BaseModel):
    endpoint: str = Field(..., min_length=1)
    auth_token: str = ""
    tool_args: Dict[str, Any] = Field(default_factory=dict)


@router.post("/mcp/sources/tools")
async def probe_mcp_tools(
    body: McpProbeRequest, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """探测远端 server 的工具清单（登记前选 tool_name）。"""
    _requireAdmin(current_user)
    _checkEndpoint(body.endpoint)
    try:
        tools = await probeTools({
            "endpoint": body.endpoint, "auth_token": body.auth_token,
        })
    except Exception as exc:  # noqa: BLE001 - 连接失败如实 502
        raise HTTPException(status_code=502, detail="MCP 探测失败: %s" % exc)
    return {"code": 0, "message": "success", "data": {"tools": tools}}
