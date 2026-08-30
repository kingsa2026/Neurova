"""
Shared Config API - 共享配置管理接口
"""

import datetime
from neurova.core.logger import get_logger
from neurova.api.endpoints._pydantic_compat import safe_model_dump  # s9: pydantic v1 兼容
import typing

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user

logger = get_logger(__name__)
# P0 安全修复: 共享配置包含 LLM API Key 与 MCP 命令，读写均必须认证
# （此前未认证即可读取明文密钥并整体接管配置）。
router = APIRouter(dependencies=[Depends(get_current_user)])

_MASKED = "***REDACTED***"


def _masked_provider(provider: dict) -> dict:
    """返回掩码后的 provider 副本（不修改原始存储）"""
    import copy

    data = copy.deepcopy(provider)
    if data.get("api_key"):
        data["api_key"] = _MASKED
    return data


def _masked_mcp_server(server: dict) -> dict:
    """返回掩码后的 MCP server 副本（env 值可能含密钥）"""
    import copy

    data = copy.deepcopy(server)
    env = data.get("env")
    if isinstance(env, dict):
        data["env"] = {k: (_MASKED if v else v) for k, v in env.items()}
    return data


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
    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}


def _get_request_id(request) -> str:
    return getattr(request.state, "request_id", "unknown")


# ── Config endpoints ───────────────────────────────────


@router.get("/")
async def get_shared_config():
    """获取完整的共享配置（API Key 等敏感字段掩码返回）"""
    import copy

    data = copy.deepcopy(_shared_config)
    data["llm_providers"] = {
        name: _masked_provider(p) for name, p in data.get("llm_providers", {}).items()
    }
    data["mcp_servers"] = {
        name: _masked_mcp_server(s) for name, s in data.get("mcp_servers", {}).items()
    }
    return {"code": 0, "message": "success", "data": data}


@router.put("/")
async def update_shared_config(body: dict):
    """更新共享配置（完整替换）"""
    global _shared_config
    body["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _shared_config = body
    return {"code": 0, "message": "Config updated", "data": {"updated_at": _shared_config["updated_at"]}}


# ── LLM Provider endpoints ─────────────────────────────


@router.get("/llm-providers")
async def list_llm_providers():
    """获取所有 LLM 提供商配置（API Key 掩码）"""
    providers = [_masked_provider(p) for p in _shared_config["llm_providers"].values()]
    return {"code": 0, "message": "success", "data": {"providers": providers, "total": len(providers)}}


@router.post("/llm-providers")
async def add_llm_provider(body: LLMProviderRequest):
    """添加新的 LLM 提供商配置"""
    name = body.name
    if name in _shared_config["llm_providers"]:
        raise HTTPException(status_code=409, detail=f"Provider '{name}' already exists")

    provider = safe_model_dump(body)  # s9: pydantic v1 兼容
    provider["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    provider["updated_at"] = provider["created_at"]
    _shared_config["llm_providers"][name] = provider
    _shared_config["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    logger.info("Added LLM provider: %s", name)
    return {"code": 0, "message": "Provider added", "data": _masked_provider(provider)}


@router.get("/llm-providers/{name}")
async def get_llm_provider(name: str):
    """获取指定 LLM 提供商的详细配置（API Key 掩码）"""
    provider = _shared_config["llm_providers"].get(name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")
    return {"code": 0, "message": "success", "data": _masked_provider(provider)}


@router.put("/llm-providers/{name}")
async def update_llm_provider(name: str, body: LLMProviderRequest):
    """更新 LLM 提供商配置"""
    if name not in _shared_config["llm_providers"]:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    provider = safe_model_dump(body)  # s9: pydantic v1 兼容
    existing = _shared_config["llm_providers"][name]
    # 掩码回写保护: 前端拿到的是掩码值，未重新填写密钥时保留原密钥
    if not provider.get("api_key") or provider["api_key"] == _MASKED:
        provider["api_key"] = existing.get("api_key")
    provider["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    provider["created_at"] = existing.get("created_at", provider["updated_at"])
    _shared_config["llm_providers"][name] = provider
    _shared_config["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    return {"code": 0, "message": "Provider updated", "data": _masked_provider(provider)}


@router.delete("/llm-providers/{name}")
async def delete_llm_provider(name: str):
    """删除 LLM 提供商配置"""
    if name not in _shared_config["llm_providers"]:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")
    del _shared_config["llm_providers"][name]
    _shared_config["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {"code": 0, "message": "Provider deleted"}


# ── MCP Server endpoints ───────────────────────────────


@router.get("/mcp-servers")
async def list_mcp_servers():
    """获取所有 MCP 服务器配置（env 敏感值掩码）"""
    servers = [_masked_mcp_server(s) for s in _shared_config["mcp_servers"].values()]
    return {"code": 0, "message": "success", "data": {"servers": servers, "total": len(servers)}}


@router.post("/mcp-servers")
async def add_mcp_server(body: MCPServerRequest):
    """添加新的 MCP 服务器配置"""
    name = body.name
    if name in _shared_config["mcp_servers"]:
        raise HTTPException(status_code=409, detail=f"MCP server '{name}' already exists")

    server = safe_model_dump(body)  # s9: pydantic v1 兼容
    server["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    server["updated_at"] = server["created_at"]
    _shared_config["mcp_servers"][name] = server
    _shared_config["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    logger.info("Added MCP server: %s", name)
    return {"code": 0, "message": "MCP server added", "data": _masked_mcp_server(server)}


@router.get("/mcp-servers/{name}")
async def get_mcp_server(name: str):
    """获取指定 MCP 服务器的详细配置（env 敏感值掩码）"""
    server = _shared_config["mcp_servers"].get(name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")
    return {"code": 0, "message": "success", "data": _masked_mcp_server(server)}


@router.put("/mcp-servers/{name}")
async def update_mcp_server(name: str, body: MCPServerRequest):
    """更新 MCP 服务器配置"""
    if name not in _shared_config["mcp_servers"]:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    server = safe_model_dump(body)  # s9: pydantic v1 兼容
    existing = _shared_config["mcp_servers"][name]
    # 掩码回写保护: env 中未重新填写的掩码值保留原值
    new_env = server.get("env")
    old_env = existing.get("env") or {}
    if isinstance(new_env, dict) and isinstance(old_env, dict):
        for k, v in new_env.items():
            if not v or v == _MASKED:
                new_env[k] = old_env.get(k, v)
    server["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    server["created_at"] = existing.get("created_at", server["updated_at"])
    _shared_config["mcp_servers"][name] = server
    _shared_config["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    return {"code": 0, "message": "MCP server updated", "data": _masked_mcp_server(server)}


@router.delete("/mcp-servers/{name}")
async def delete_mcp_server(name: str):
    """删除 MCP 服务器配置"""
    if name not in _shared_config["mcp_servers"]:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")
    del _shared_config["mcp_servers"][name]
    _shared_config["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {"code": 0, "message": "MCP server deleted"}


# ── Export/Import ──────────────────────────────────────


@router.get("/export")
async def export_config():
    """导出完整的共享配置（敏感字段掩码）"""
    import copy

    config = copy.deepcopy(_shared_config)
    config["llm_providers"] = {
        name: _masked_provider(p) for name, p in config.get("llm_providers", {}).items()
    }
    config["mcp_servers"] = {
        name: _masked_mcp_server(s) for name, s in config.get("mcp_servers", {}).items()
    }
    return {"code": 0, "message": "Config exported", "data": config}


@router.post("/import")
async def import_config(body: ImportConfigRequest):
    """导入完整的共享配置"""
    global _shared_config
    if body.overwrite:
        body.config["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _shared_config = body.config
    else:
        # Merge
        for key in ["llm_providers", "mcp_servers"]:
            if key in body.config:
                _shared_config[key].update(body.config[key])
        if "general" in body.config:
            _shared_config["general"].update(body.config["general"])
        _shared_config["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    return {"code": 0, "message": "Config imported", "data": {"overwrite": body.overwrite}}
