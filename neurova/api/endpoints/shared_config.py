"""
Shared Config API - 共享配置管理接口
"""

import datetime
import logging
import typing

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from pydantic import BaseModel
from pydantic import Field

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Models ─────────────────────────────────────────────

class LLMProviderRequest(BaseModel):
    name: str
    provider_type: str = "openai"  # openai, anthropic, gemini, ollama, etc.
    api_key: typing.Optional[str] = None
    base_url: typing.Optional[str] = None
    models: typing.List[str] = Field(default_factory=list)
    default_model: typing.Optional[str] = None
    enabled: bool = True
    extra: typing.Optional[dict] = None


class MCPServerRequest(BaseModel):
    name: str
    command: str
    args: typing.List[str] = Field(default_factory=list)
    env: typing.Optional[dict] = None
    enabled: bool = True
    description: str = ""


class ImportConfigRequest(BaseModel):
    config: dict
    overwrite: bool = False


# ── In-memory store ────────────────────────────────────

_shared_config: dict = {
    "llm_providers": {},
    "mcp_servers": {},
    "general": {"debug": False, "log_level": "info", "max_tokens": 4096},
    "updated_at": datetime.datetime.utcnow().isoformat(),
}


def _get_request_id(request) -> str:
    return getattr(request.state, "request_id", "unknown")


# ── Config endpoints ───────────────────────────────────

@router.get("/")
async def get_shared_config():
    """获取完整的共享配置"""
    return {"code": 0, "message": "success", "data": _shared_config}


@router.put("/")
async def update_shared_config(body: dict):
    """更新共享配置（完整替换）"""
    global _shared_config
    body["updated_at"] = datetime.datetime.utcnow().isoformat()
    _shared_config = body
    return {"code": 0, "message": "Config updated", "data": _shared_config}


# ── LLM Provider endpoints ─────────────────────────────

@router.get("/llm-providers")
async def list_llm_providers():
    """获取所有 LLM 提供商配置"""
    providers = list(_shared_config["llm_providers"].values())
    return {"code": 0, "message": "success", "data": {"providers": providers, "total": len(providers)}}


@router.post("/llm-providers")
async def add_llm_provider(body: LLMProviderRequest):
    """添加新的 LLM 提供商配置"""
    name = body.name
    if name in _shared_config["llm_providers"]:
        raise HTTPException(status_code=409, detail=f"Provider '{name}' already exists")

    provider = body.model_dump()
    provider["created_at"] = datetime.datetime.utcnow().isoformat()
    provider["updated_at"] = provider["created_at"]
    _shared_config["llm_providers"][name] = provider
    _shared_config["updated_at"] = datetime.datetime.utcnow().isoformat()

    logger.info("Added LLM provider: %s", name)
    return {"code": 0, "message": "Provider added", "data": provider}


@router.get("/llm-providers/{name}")
async def get_llm_provider(name: str):
    """获取指定 LLM 提供商的详细配置"""
    provider = _shared_config["llm_providers"].get(name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")
    return {"code": 0, "message": "success", "data": provider}


@router.put("/llm-providers/{name}")
async def update_llm_provider(name: str, body: LLMProviderRequest):
    """更新 LLM 提供商配置"""
    if name not in _shared_config["llm_providers"]:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    provider = body.model_dump()
    provider["updated_at"] = datetime.datetime.utcnow().isoformat()
    provider["created_at"] = _shared_config["llm_providers"][name].get("created_at", provider["updated_at"])
    _shared_config["llm_providers"][name] = provider
    _shared_config["updated_at"] = datetime.datetime.utcnow().isoformat()

    return {"code": 0, "message": "Provider updated", "data": provider}


@router.delete("/llm-providers/{name}")
async def delete_llm_provider(name: str):
    """删除 LLM 提供商配置"""
    if name not in _shared_config["llm_providers"]:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")
    del _shared_config["llm_providers"][name]
    _shared_config["updated_at"] = datetime.datetime.utcnow().isoformat()
    return {"code": 0, "message": "Provider deleted"}


# ── MCP Server endpoints ───────────────────────────────

@router.get("/mcp-servers")
async def list_mcp_servers():
    """获取所有 MCP 服务器配置"""
    servers = list(_shared_config["mcp_servers"].values())
    return {"code": 0, "message": "success", "data": {"servers": servers, "total": len(servers)}}


@router.post("/mcp-servers")
async def add_mcp_server(body: MCPServerRequest):
    """添加新的 MCP 服务器配置"""
    name = body.name
    if name in _shared_config["mcp_servers"]:
        raise HTTPException(status_code=409, detail=f"MCP server '{name}' already exists")

    server = body.model_dump()
    server["created_at"] = datetime.datetime.utcnow().isoformat()
    server["updated_at"] = server["created_at"]
    _shared_config["mcp_servers"][name] = server
    _shared_config["updated_at"] = datetime.datetime.utcnow().isoformat()

    logger.info("Added MCP server: %s", name)
    return {"code": 0, "message": "MCP server added", "data": server}


@router.get("/mcp-servers/{name}")
async def get_mcp_server(name: str):
    """获取指定 MCP 服务器的详细配置"""
    server = _shared_config["mcp_servers"].get(name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")
    return {"code": 0, "message": "success", "data": server}


@router.put("/mcp-servers/{name}")
async def update_mcp_server(name: str, body: MCPServerRequest):
    """更新 MCP 服务器配置"""
    if name not in _shared_config["mcp_servers"]:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    server = body.model_dump()
    server["updated_at"] = datetime.datetime.utcnow().isoformat()
    server["created_at"] = _shared_config["mcp_servers"][name].get("created_at", server["updated_at"])
    _shared_config["mcp_servers"][name] = server
    _shared_config["updated_at"] = datetime.datetime.utcnow().isoformat()

    return {"code": 0, "message": "MCP server updated", "data": server}


@router.delete("/mcp-servers/{name}")
async def delete_mcp_server(name: str):
    """删除 MCP 服务器配置"""
    if name not in _shared_config["mcp_servers"]:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")
    del _shared_config["mcp_servers"][name]
    _shared_config["updated_at"] = datetime.datetime.utcnow().isoformat()
    return {"code": 0, "message": "MCP server deleted"}


# ── Export/Import ──────────────────────────────────────

@router.get("/export")
async def export_config():
    """导出完整的共享配置"""
    import copy
    config = copy.deepcopy(_shared_config)
    # Mask API keys in export
    for provider in config.get("llm_providers", {}).values():
        if provider.get("api_key"):
            provider["api_key"] = "***REDACTED***"
    return {"code": 0, "message": "Config exported", "data": config}


@router.post("/import")
async def import_config(body: ImportConfigRequest):
    """导入完整的共享配置"""
    global _shared_config
    if body.overwrite:
        body.config["updated_at"] = datetime.datetime.utcnow().isoformat()
        _shared_config = body.config
    else:
        # Merge
        for key in ["llm_providers", "mcp_servers"]:
            if key in body.config:
                _shared_config[key].update(body.config[key])
        if "general" in body.config:
            _shared_config["general"].update(body.config["general"])
        _shared_config["updated_at"] = datetime.datetime.utcnow().isoformat()

    return {"code": 0, "message": "Config imported", "data": {"overwrite": body.overwrite}}
