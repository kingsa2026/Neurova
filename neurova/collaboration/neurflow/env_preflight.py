"""节点环境/凭据预检（N5）。

只返回变量名与来源，不读取、不回显任何凭据值。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Union

from neurova.core.logger import get_logger

from .node_registry import get_node_registry

logger = get_logger(__name__)


def _asTypeList(types: Union[str, List[str], None]) -> List[str]:
    if types is None:
        return []
    if isinstance(types, str):
        return [types.strip()] if types.strip() else []
    return [str(item).strip() for item in types if str(item).strip()]


def _definitionOf(nodeType: str, registry, customNodeService):
    if nodeType.startswith("custom:"):
        service = customNodeService
        if service is None:
            from .custom_nodes import get_custom_node_service

            service = get_custom_node_service()
        return service.get_node(nodeType)
    if registry is None:
        registry = get_node_registry()
        registry.ensure_builtin()
    return registry.get(nodeType)


def _providerHint(name: str) -> str:
    upper = name.upper()
    if "AMAZON" in upper:
        return "亚马逊广告/店铺凭据：设置 → 凭据（SecretStore），或对应 StoreConnection"
    if "TAOBAO" in upper or "JD" in upper or "PDD" in upper or "DOUYIN" in upper:
        return "国内电商凭据：设置 → 店铺连接（StoreConnection）或 SecretStore"
    if "MCP" in upper or "OAUTH" in upper:
        return "MCP 配置/OAuth 授权：设置 → MCP 或对应连接器"
    return "环境变量或 SecretStore（设置 → 凭据）"


def _secretKeys(secretStore) -> set:
    store = secretStore
    if store is None:
        try:
            from neurova.llm.providers.secret_store_clean import get_secret_store

            store = get_secret_store()
        except Exception as exc:  # noqa: BLE001 - 预检失败不阻断，按无密钥处理
            logger.warning("SecretStore 不可用（预检按无密钥处理）: %s", exc)
            return set()
    try:
        return {str(key) for key in (store.list_keys() or [])}
    except Exception as exc:  # noqa: BLE001
        logger.warning("SecretStore 键名读取失败（预检按无密钥处理）: %s", exc)
        return set()


def preflightNodeEnv(
    types: Union[str, List[str]],
    *,
    registry=None,
    customNodeService=None,
    secretStore=None,
) -> Dict[str, Any]:
    """检查节点类型声明的环境变量是否可用。

    返回 ``declared / sources / missing / providers / unknown_types /
    inactive_types / ready``；``sources`` 只含来源标签（env / secret_store），
    不含任何值。
    """
    requested = _asTypeList(types)
    if not requested:
        return {
            "success": False,
            "code": "invalid_params",
            "error": "types 不能为空",
            "ready": False,
            "declared": {},
            "sources": {},
            "missing": [],
            "providers": {},
            "unknown_types": [],
            "inactive_types": [],
        }

    declared: Dict[str, List[str]] = {}
    unknown: List[str] = []
    inactive: List[str] = []
    for nodeType in requested:
        definition = _definitionOf(nodeType, registry, customNodeService)
        if definition is None:
            unknown.append(nodeType)
            continue
        status = str(getattr(definition, "status", "active") or "active")
        if nodeType.startswith("custom:") and status != "active":
            inactive.append(nodeType)
        declared[nodeType] = [
            str(item)
            for item in (getattr(definition, "env_requirements", None) or [])
            if str(item).strip()
        ]

    secretKeys = _secretKeys(secretStore)
    allNames = sorted({name for names in declared.values() for name in names})
    sources: Dict[str, List[str]] = {}
    for name in allNames:
        found: List[str] = []
        if str(os.environ.get(name) or "").strip():
            found.append("env")
        if name in secretKeys:
            found.append("secret_store")
        sources[name] = found

    missing = [name for name in allNames if not sources[name]]
    providers = {name: _providerHint(name) for name in missing}

    result = {
        "success": not unknown,
        "ready": not missing and not unknown and not inactive,
        "declared": declared,
        "sources": sources,
        "missing": missing,
        "providers": providers,
        "unknown_types": unknown,
        "inactive_types": inactive,
    }
    if unknown:
        result["code"] = "unknown_node_type"
        result["error"] = f"未注册的节点类型: {', '.join(unknown)}"
    elif inactive:
        result["code"] = "inactive_node_type"
        result["error"] = f"未激活的自定义节点: {', '.join(inactive)}"
    return result


__all__ = ["preflightNodeEnv"]
