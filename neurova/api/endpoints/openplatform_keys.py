"""
开放平台API密钥管理端点

存储实现不再自持一份：统一走 `neurova.api.api_key_manager.APIKeyManager`
（教义第 7 条——同一功能仓内只留一处实现）。本模块只保留 HTTP 面与开放平台特有的
**语义**：`nrv_` 命名空间、创建幂等（`creation_request_id` + 意图指纹）、撤销
tombstone 拒绝同请求重放复活。这三项机制原先长在私有存储里，现已并入管理器，
因此原子写（temp + `os.replace`）与损坏文件备份留证两处也共用同一份实现。
明文只在创建成功响应中出现一次；存储面只有 SHA-256 哈希（不降）。

存量兼容：部署侧可能已有旧实现写下的扁平 `{key_id: {...}}` 形状文件，管理器的
装载读侧同时接受该形状——合并不得把用户已签发的密钥读丢。

登记在案（需产品拍板）：`nrv_` 密钥当前**全仓无验证消费方**——签发吊销链完整但
"用键调 API"的认证入口未接线。外部 Agent 通信域那道门已接好（同一个类的另一个
实例 + JWT/密钥合一），要不要让开放平台密钥也走那道门属产品口径。
"""

import datetime
import hashlib
import json
import os
import threading
import typing
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from neurova.api.api_key_manager import APIKey, APIKeyManager
from neurova.api.auth import get_current_user
from neurova.core.data_root import callerPath
from neurova.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)],)


class CreateApiKeyRequest(BaseModel):
    name: str
    scopes: typing.List[str] = Field(default_factory=list)
    expires_in_days: int = Field(default=90, ge=1, le=365)
    description: str = ""
    # 幂等键（客户端生成 UUID）：同键重放返回同一密钥，不产生第二把
    creation_request_id: typing.Optional[str] = None


class UpdateApiKeyRequest(BaseModel):
    name: typing.Optional[str] = None
    scopes: typing.Optional[typing.List[str]] = None
    enabled: typing.Optional[bool] = None


_AVAILABLE_SCOPES = [
    {"id": "read", "name": "Read", "description": "Read-only access"},
    {"id": "write", "name": "Write", "description": "Create and update"},
    {"id": "delete", "name": "Delete", "description": "Delete resources"},
    {"id": "agent:chat", "name": "Agent Chat", "description": "Chat with agents"},
    {"id": "memory:read", "name": "Memory Read", "description": "Read memories"},
]

_KEY_MANAGER: typing.Optional[APIKeyManager] = None
_MANAGER_LOCK = threading.RLock()


def _db_path() -> Path:
    return callerPath(os.environ.get("NEUROVA_OPENPLATFORM_KEYS_DB"), "openplatform_keys.json")


def get_openplatformKeyManager() -> APIKeyManager:
    """开放平台密钥管理器单例：同一份实现，按命名空间与存储文件分区。

    与 agent 域共用类实现，但**不共用那一本账**——两条产品线的签发口径不同，
    混进同一文件会让"撤掉一条线的键影响另一条线"成为默认行为。
    """
    global _KEY_MANAGER

    if _KEY_MANAGER is None:
        with _MANAGER_LOCK:
            if _KEY_MANAGER is None:
                _KEY_MANAGER = APIKeyManager(
                    storage_path=_db_path(),
                    key_namespace="nrv_",
                    default_expiry_days=90,
                )
    return _KEY_MANAGER


def reset_openplatform_keys_store() -> None:
    """丢开进程内实例、下次访问重新装载（重启等价；亦为测试隔离入口）。"""
    global _KEY_MANAGER

    with _MANAGER_LOCK:
        _KEY_MANAGER = None


def _intent_hash(body: CreateApiKeyRequest) -> str:
    """创建意图指纹：同幂等键换意图 = 客户端 bug 或竞态，必须显式拒绝"""
    payload = json.dumps(
        {
            "name": body.name,
            "scopes": sorted(body.scopes or []),
            "expires_in_days": body.expires_in_days,
            "description": body.description,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _iso(value: typing.Any) -> typing.Optional[str]:
    """时间字段对外仍是 ISO 字符串（旧私有存储的形状）；管理器内部可能是 epoch"""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(float(value), datetime.timezone.utc).isoformat()
    return str(value)


def _toFace(
    apiKey: APIKey, plaintext: typing.Optional[str] = None
) -> typing.Dict[str, typing.Any]:
    """APIKey → 本端点既有响应形状（字段名与旧实现逐一对齐，不改对外契约）。

    与旧形状的有意差异两处：`key_hash` 不再出现在响应里（旧实现把整条记录直出，
    连哈希都吐出去了）；`key_prefix` 用管理器的 8 位口径（旧为 12 位 + 省略号）。
    """
    face = {
        "id": apiKey.key_id,
        "name": apiKey.name,
        "description": apiKey.description,
        "key_prefix": apiKey.key_prefix,
        "scopes": list(apiKey.permissions),
        "enabled": apiKey.is_active,
        # 两个口径都给：旧契约里 enabled 与 revoked 同时存在，撤销行不进列表
        "revoked": not apiKey.is_active,
        "user_id": apiKey.user_id,
        "created_at": _iso(apiKey.created_at),
        "expires_at": _iso(apiKey.expires_at),
        "last_used_at": _iso(apiKey.last_used_at),
        "usage_count": apiKey.usage_count,
        "creation_request_id": apiKey.creation_request_id,
    }
    if apiKey.revoked_at is not None:
        face["revoked_at"] = _iso(apiKey.revoked_at)
    if plaintext:
        face["key"] = plaintext
    return face


def _requireOwnedKey(manager: APIKeyManager, keyId: str, uid: str) -> APIKey:
    """按 id 取回并校验归属；不存在或非本人一律 404（不泄漏他人密钥是否存在）"""
    apiKey = manager.get_key_by_id(keyId)
    if not apiKey or apiKey.user_id != uid:
        raise HTTPException(status_code=404, detail="Key not found")
    return apiKey


@router.get("/")
async def list_api_keys(
    page: int = 1,
    size: int = 20,
    user: typing.Dict[str, typing.Any] = Depends(get_current_user),
):
    # 身份只来自路由级那道门的返回值（`request.state.user_id` 全仓无人写入）
    uid = user.get("user_id", "")
    activeKeys = [k for k in get_openplatformKeyManager().get_user_keys(uid) if k.is_active]
    activeKeys.sort(key=lambda k: k.created_at or 0, reverse=True)
    items = [_toFace(k) for k in activeKeys]
    start = (page - 1) * size
    return {
        "code": 0,
        "message": "success",
        "data": {"items": items[start : start + size], "total": len(items), "page": page, "size": size},
    }


@router.post("/")
async def create_api_key(
    body: CreateApiKeyRequest,
    user: typing.Dict[str, typing.Any] = Depends(get_current_user),
):
    uid = user.get("user_id", "")
    manager = get_openplatformKeyManager()
    fingerprint = _intent_hash(body)

    # 幂等分支：同 creation_request_id 重放不产生第二把，也不第二次吐明文
    if body.creation_request_id:
        existing = manager.find_by_creation_request_id(uid, body.creation_request_id)
        if existing is not None:
            if not existing.is_active:
                # tombstone：撤销后不得复活重放
                raise HTTPException(
                    status_code=409,
                    detail="该创建请求的密钥已撤销，不允许复活重放；请使用新的 creation_request_id",
                )
            if existing.intent_hash != fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail="同一 creation_request_id 携带了不同的创建意图（客户端 bug 或竞态）",
                )
            return {"code": 0, "message": "Key replayed", "data": {**_toFace(existing), "replayed": True}}

    plaintext, apiKey = manager.generate_key(
        agent_id=uid,  # 开放平台密钥不绑定 agent，占位用归属者本人
        user_id=uid,
        name=body.name,
        permissions=list(body.scopes or []),
        expires_in_days=body.expires_in_days,
        description=body.description,
        creation_request_id=body.creation_request_id,
        intent_hash=fingerprint,
    )
    return {"code": 0, "message": "Key created", "data": _toFace(apiKey, plaintext=plaintext)}


@router.get("/{key_id}")
async def get_api_key(
    key_id: str,
    user: typing.Dict[str, typing.Any] = Depends(get_current_user),
):
    uid = user.get("user_id", "")
    face = _toFace(_requireOwnedKey(get_openplatformKeyManager(), key_id, uid))
    return {"code": 0, "message": "success", "data": face}


@router.put("/{key_id}")
async def update_api_key(
    key_id: str,
    body: UpdateApiKeyRequest,
    user: typing.Dict[str, typing.Any] = Depends(get_current_user),
):
    uid = user.get("user_id", "")
    manager = get_openplatformKeyManager()
    _requireOwnedKey(manager, key_id, uid)
    updated = manager.update_key(
        key_id,
        name=body.name,
        permissions=body.scopes,
        is_active=body.enabled,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"code": 0, "message": "Key updated", "data": _toFace(updated)}


@router.post("/{key_id}/revoke")
async def revoke_api_key(
    key_id: str,
    user: typing.Dict[str, typing.Any] = Depends(get_current_user),
):
    uid = user.get("user_id", "")
    manager = get_openplatformKeyManager()
    _requireOwnedKey(manager, key_id, uid)
    manager.revoke_key(key_id)
    return {"code": 0, "message": "Key revoked"}


@router.delete("/{key_id}")
async def delete_api_key(
    key_id: str,
    user: typing.Dict[str, typing.Any] = Depends(get_current_user),
):
    uid = user.get("user_id", "")
    manager = get_openplatformKeyManager()
    _requireOwnedKey(manager, key_id, uid)
    # tombstone 化删除：物理删会让同 creation_request_id 的重放绕过"已撤销不得复活"
    # 这道检查再造密钥——所以只标撤销、行保留（对外列表与详情均不可见）
    manager.revoke_key(key_id)
    return {"code": 0, "message": "Key deleted"}


@router.get("/{key_id}/usage")
async def get_key_usage(
    key_id: str,
    user: typing.Dict[str, typing.Any] = Depends(get_current_user),
):
    uid = user.get("user_id", "")
    apiKey = _requireOwnedKey(get_openplatformKeyManager(), key_id, uid)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "key_id": key_id,
            "usage_count": apiKey.usage_count,
            "last_used_at": _iso(apiKey.last_used_at),
        },
    }


@router.get("/scopes")
async def get_available_scopes():
    return {"code": 0, "message": "success", "data": {"scopes": _AVAILABLE_SCOPES}}
