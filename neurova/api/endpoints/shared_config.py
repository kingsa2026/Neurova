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
# P0-4（M10）：headers 按敏感键名掩码（env 维持全掩既有语义）
_SENSITIVE_HEADER_KEYS = ("authorization", "token", "secret", "key", "password", "cookie")


def _masked_provider(provider: dict) -> dict:
    """返回掩码后的 provider 副本（不修改原始存储）"""
    import copy

    data = copy.deepcopy(provider)
    if data.get("api_key"):
        data["api_key"] = _MASKED
    return data


def _mask_sensitive_headers(headers: dict) -> dict:
    """headers 敏感键掩码：键名含 authorization/token/secret/key/password/cookie"""
    lowered = {k: k.lower() for k in headers}
    return {
        k: (_MASKED if any(s in lowered[k] for s in _SENSITIVE_HEADER_KEYS) and v else v)
        for k, v in headers.items()
    }


def _masked_mcp_server(server: dict) -> dict:
    """返回掩码后的 MCP server 副本（env 全掩；headers 掩敏感键）"""
    import copy

    data = copy.deepcopy(server)
    env = data.get("env")
    if isinstance(env, dict):
        data["env"] = {k: (_MASKED if v else v) for k, v in env.items()}
    headers = data.get("headers")
    if isinstance(headers, dict):
        data["headers"] = _mask_sensitive_headers(headers)
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
    """MCP server 配置（P0-4：与 tool-layers 对齐的完整字段集，command 放宽
    为可选以支持 http/sse 服务器；校验统一走 validate_mcp_server_config）"""

    name: str
    command: typing.Optional[str] = None
    args: typing.List[str] = Field(default_factory=list)
    env: typing.Optional[dict] = None
    headers: typing.Optional[dict] = None
    url: typing.Optional[str] = None
    transport: typing.Optional[str] = None
    cwd: typing.Optional[str] = None
    timeout_ms: typing.Optional[int] = None
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
    """获取完整的共享配置（API Key 等敏感字段掩码返回）

    P0-4：mcp_servers 与 Manager 同源（收敛后内存 dict 不再是 MCP 数据源）
    """
    import copy

    from neurova.shared_config import get_shared_config_manager

    data = copy.deepcopy(_shared_config)
    data["llm_providers"] = {
        name: _masked_provider(p) for name, p in data.get("llm_providers", {}).items()
    }
    data["mcp_servers"] = {
        s.get("id", "?"): _masked_mcp_server(s)
        for s in get_shared_config_manager().list_mcp_servers()
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
#
# P0-4（M7 收敛）：MCP server CRUD 统一走 SharedConfigManager（持久化到
# data/shared_config.json，与 tool-layers 端点同一存储）——此前纯内存 dict
# 分叉导致通过本界面添加的 server 对 bootstrap 完全不可见。
# 校验/角色门/私网 URL 门与 tool-layers 对齐（P0-1/P0-2 语义一致）。


def _mcp_sid_from_name(name: str) -> str:
    import re
    import uuid

    return re.sub(r"\W+", "_", name or "").strip("_") or str(uuid.uuid4())


def _mcp_config_from_body(body: "MCPServerRequest") -> dict:
    config = {
        "id": _mcp_sid_from_name(body.name),
        "name": body.name,
        "transport": body.transport or "",
        "url": body.url or "",
        "command": body.command or "",
        "args": list(body.args or []),
        "cwd": body.cwd,
        "env": dict(body.env or {}),
        "headers": dict(body.headers or {}),
        "enabled": body.enabled,
        "description": body.description,
    }
    if body.timeout_ms:
        config["timeout_ms"] = body.timeout_ms
    return config


def _mcp_role_of(current_user: typing.Optional[dict]) -> str:
    return str((current_user or {}).get("role") or "user")


def _validate_and_gate_mcp_config(config: dict, role: str) -> dict:
    """schema 校验 + 角色门/私网门（与 tool_layers.connect_mcp_server 同语义）

    P0-4 修正：门禁基于归一化后的 transport——transport 省略时按
    command/url 推断为 stdio，若检查原始字符串，推断路径会绕过角色门。
    Returns:
        归一化后的配置（调用方应以此为准）
    Raises:
        HTTPException: 400（schema/URL）或 403（角色）
    """
    from fastapi import HTTPException

    from neurova.security.url_guard import assert_public_url
    from neurova.tool_layers.mcp_config import validate_mcp_server_config

    try:
        cfg = validate_mcp_server_config(config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if cfg.get("transport") == "stdio" and role != "admin":
        raise HTTPException(
            status_code=403,
            detail="stdio 传输需要管理员角色（stdio MCP server 由本机派生进程执行）",
        )
    if role != "admin" and cfg.get("transport") in ("http", "sse"):
        try:
            assert_public_url(cfg.get("url") or "")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"MCP server url 被拒绝: {e}")
    return cfg


@router.get("/mcp-servers")
async def list_mcp_servers():
    """获取所有 MCP 服务器配置（env 全掩 + headers 敏感键掩码）"""
    from neurova.shared_config import get_shared_config_manager

    servers = [
        _masked_mcp_server(s) for s in get_shared_config_manager().list_mcp_servers()
    ]
    return {"code": 0, "message": "success", "data": {"servers": servers, "total": len(servers)}}


@router.post("/mcp-servers")
async def add_mcp_server(
    body: MCPServerRequest,
    current_user: typing.Optional[dict] = Depends(get_current_user),
):
    """添加新的 MCP 服务器配置（持久化进 SharedConfigManager）"""
    from neurova.shared_config import get_shared_config_manager

    manager = get_shared_config_manager()
    config = _mcp_config_from_body(body)
    config = _validate_and_gate_mcp_config(config, _mcp_role_of(current_user))

    if manager.get_mcp_server(config["id"]) is not None:
        raise HTTPException(status_code=409, detail=f"MCP server '{config['id']}' already exists")
    if not manager.add_mcp_server(config):
        raise HTTPException(status_code=400, detail="MCP server 配置非法或已存在")

    logger.info("Added MCP server: %s", config["id"])
    return {
        "code": 0,
        "message": "MCP server added",
        "data": _masked_mcp_server(manager.get_mcp_server(config["id"]) or config),
    }


@router.get("/mcp-servers/{name}")
async def get_mcp_server(name: str):
    """获取指定 MCP 服务器的详细配置（掩码返回）"""
    from neurova.shared_config import get_shared_config_manager

    server = get_shared_config_manager().get_mcp_server(name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")
    return {"code": 0, "message": "success", "data": _masked_mcp_server(server)}


@router.put("/mcp-servers/{name}")
async def update_mcp_server(
    name: str,
    body: MCPServerRequest,
    current_user: typing.Optional[dict] = Depends(get_current_user),
):
    """更新 MCP 服务器配置（掩码回写保护：未重填的掩码值保留原值）"""
    from neurova.shared_config import get_shared_config_manager

    manager = get_shared_config_manager()
    existing = manager.get_mcp_server(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    config = _mcp_config_from_body(body)
    config["id"] = name  # 路径名为准，不允许改 id
    config = _validate_and_gate_mcp_config(config, _mcp_role_of(current_user))

    # 掩码回写保护：env 全掩语义 + headers 敏感键，未重填的掩码值保留原值
    new_env = config.get("env") or {}
    old_env = existing.get("env") or {}
    for k, v in new_env.items():
        if not v or v == _MASKED:
            new_env[k] = old_env.get(k, v)
    new_headers = config.get("headers") or {}
    old_headers = existing.get("headers") or {}
    for k, v in new_headers.items():
        if v == _MASKED:
            new_headers[k] = old_headers.get(k, v)

    if not manager.update_mcp_server(name, config):
        raise HTTPException(status_code=400, detail="MCP server 配置非法")

    return {
        "code": 0,
        "message": "MCP server updated",
        "data": _masked_mcp_server(manager.get_mcp_server(name) or config),
    }


@router.delete("/mcp-servers/{name}")
async def delete_mcp_server(name: str):
    """删除 MCP 服务器配置"""
    from neurova.shared_config import get_shared_config_manager

    if not get_shared_config_manager().remove_mcp_server(name):
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")
    return {"code": 0, "message": "MCP server deleted"}


# ── Export/Import ──────────────────────────────────────


@router.get("/export")
async def export_config():
    """导出完整的共享配置（敏感字段掩码）

    P0-4：mcp_servers 与 Manager 同源
    """
    import copy

    from neurova.shared_config import get_shared_config_manager

    config = copy.deepcopy(_shared_config)
    config["llm_providers"] = {
        name: _masked_provider(p) for name, p in config.get("llm_providers", {}).items()
    }
    config["mcp_servers"] = {
        s.get("id", "?"): _masked_mcp_server(s)
        for s in get_shared_config_manager().list_mcp_servers()
    }
    return {"code": 0, "message": "Config exported", "data": config}


def _import_mcp_servers_into_manager(config: dict) -> None:
    """把导入配置里的 mcp_servers best-effort 写入 Manager（已存在/非法跳过）

    P0-4：导入是管理操作，逐条 add 的失败不阻断其余条目。
    """
    from neurova.shared_config import get_shared_config_manager

    raw = config.get("mcp_servers")
    entries = list(raw.values()) if isinstance(raw, dict) else (raw or [])
    manager = get_shared_config_manager()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            manager.add_mcp_server(entry)
        except Exception as e:
            logger.warning("导入 MCP server 失败（跳过）: %s", e)


@router.post("/import")
async def import_config(body: ImportConfigRequest):
    """导入完整的共享配置

    P0-4：mcp_servers 部分收敛进 Manager（merge 语义：已存在/非法条目跳过）
    """
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

    _import_mcp_servers_into_manager(body.config)
    return {"code": 0, "message": "Config imported", "data": {"overwrite": body.overwrite}}
