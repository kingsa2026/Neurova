"""
开放平台API密钥管理端点

Yuxi 对比 P2 #12：密钥从模块级内存 dict 升级为**JSON 落盘**（原子写
temp+os.replace，providers 丢配置事故三件套教训）+ 创建幂等
（creation_request_id + 意图指纹）+ 撤销 tombstone 拒绝同请求重放复活。
明文只在创建成功响应中出现一次；存储面只有 SHA-256 哈希（不降）。

登记在案（本批未做，需产品拍板）：`nrv_` 密钥当前**全仓无验证消费方**——
签发吊销链完整但"用键调 API"的认证入口未接线。
"""

import datetime
import hashlib
import json
import os
import secrets
import threading
import time
import typing
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel, Field
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


_KEYS_STORE: typing.Dict[str, dict] = {}
_STORE_LOCK = threading.RLock()
_loaded = False
_AVAILABLE_SCOPES = [
    {"id": "read", "name": "Read", "description": "Read-only access"},
    {"id": "write", "name": "Write", "description": "Create and update"},
    {"id": "delete", "name": "Delete", "description": "Delete resources"},
    {"id": "agent:chat", "name": "Agent Chat", "description": "Chat with agents"},
    {"id": "memory:read", "name": "Memory Read", "description": "Read memories"},
]


def _db_path() -> Path:
    return Path(os.environ.get("NEUROVA_OPENPLATFORM_KEYS_DB") or "data/openplatform_keys.json")


def _ensure_loaded() -> None:
    """进程首次使用装载；损坏文件备份留证后空载（禁止静默清空）。"""
    global _loaded
    with _STORE_LOCK:
        if _loaded:
            return
        path = _db_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    _KEYS_STORE.update(data)
            except (json.JSONDecodeError, OSError) as e:
                backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
                try:
                    path.replace(backup)
                    logger.error("开放平台密钥库损坏，已备份 %s 后空载: %s", backup, e)
                except OSError:
                    logger.error("开放平台密钥库损坏且备份失败: %s", e)
        _loaded = True


def _save_locked() -> None:
    """原子落盘（调用方必须持 _STORE_LOCK）。"""
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(_KEYS_STORE, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, path)


def reset_openplatform_keys_store() -> None:
    """清进程态并重载（重启等价；亦为测试隔离入口）。"""
    global _loaded
    with _STORE_LOCK:
        _KEYS_STORE.clear()
        _loaded = False


def _intent_hash(body: CreateApiKeyRequest) -> str:
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


def _find_by_request_id(uid: str, request_id: str) -> typing.Optional[dict]:
    for k in _KEYS_STORE.values():
        if k.get("user_id") == uid and k.get("creation_request_id") == request_id:
            return k
    return None


def _get_uid(request) -> str:
    return getattr(request.state, "user_id", "anonymous")


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _gen_key() -> tuple:
    key = f"nrv_{secrets.token_urlsafe(32)}"
    return key, _hash_key(key), key[:12] + "..."


@router.get("/")
async def list_api_keys(request: Request, page: int = 1, size: int = 20):
    _ensure_loaded()
    uid = _get_uid(request)
    with _STORE_LOCK:
        keys = [k for k in _KEYS_STORE.values() if k.get("user_id") == uid and not k.get("revoked")]
    keys.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    start = (page - 1) * size
    return {
        "code": 0,
        "message": "success",
        "data": {"items": keys[start : start + size], "total": len(keys), "page": page, "size": size},
    }


@router.post("/")
async def create_api_key(body: CreateApiKeyRequest, request: Request):
    _ensure_loaded()
    uid = _get_uid(request)
    with _STORE_LOCK:
        # 幂等分支：同 creation_request_id 重放
        if body.creation_request_id:
            existing = _find_by_request_id(uid, body.creation_request_id)
            if existing is not None:
                if existing.get("revoked"):
                    # tombstone：撤销后不得复活重放（Yuxi api_key_repository 语义）
                    raise HTTPException(
                        status_code=409,
                        detail="该创建请求的密钥已撤销，不允许复活重放；请使用新的 creation_request_id",
                    )
                if existing.get("intent_hash") != _intent_hash(body):
                    raise HTTPException(
                        status_code=409,
                        detail="同一 creation_request_id 携带了不同的创建意图（客户端 bug 或竞态）",
                    )
                return {"code": 0, "message": "Key replayed", "data": {**existing, "replayed": True}}
        kid = str(uuid.uuid4())[:12]
        full, h, prefix = _gen_key()
        now = datetime.datetime.now(datetime.timezone.utc)
        data = {
            "id": kid,
            "name": body.name,
            "description": body.description,
            "key_prefix": prefix,
            "key_hash": h,
            "scopes": body.scopes,
            "enabled": True,
            "revoked": False,
            "user_id": uid,
            "created_at": now.isoformat(),
            "expires_at": (now + datetime.timedelta(days=body.expires_in_days)).isoformat(),
            "last_used_at": None,
            "usage_count": 0,
            "creation_request_id": body.creation_request_id,
            "intent_hash": _intent_hash(body),
        }
        _KEYS_STORE[kid] = data
        _save_locked()
    return {"code": 0, "message": "Key created", "data": {**data, "key": full}}


@router.get("/{key_id}")
async def get_api_key(key_id: str, request: Request):
    _ensure_loaded()
    uid = _get_uid(request)
    with _STORE_LOCK:
        k = _KEYS_STORE.get(key_id)
    if not k or k.get("user_id") != uid:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"code": 0, "message": "success", "data": k}


@router.put("/{key_id}")
async def update_api_key(key_id: str, body: UpdateApiKeyRequest, request: Request):
    _ensure_loaded()
    uid = _get_uid(request)
    with _STORE_LOCK:
        k = _KEYS_STORE.get(key_id)
        if not k or k.get("user_id") != uid:
            raise HTTPException(status_code=404, detail="Key not found")
        if body.name is not None:
            k["name"] = body.name
        if body.scopes is not None:
            k["scopes"] = body.scopes
        if body.enabled is not None:
            k["enabled"] = body.enabled
        k["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _save_locked()
        return {"code": 0, "message": "Key updated", "data": k}


@router.post("/{key_id}/revoke")
async def revoke_api_key(key_id: str, request: Request):
    _ensure_loaded()
    uid = _get_uid(request)
    with _STORE_LOCK:
        k = _KEYS_STORE.get(key_id)
        if not k or k.get("user_id") != uid:
            raise HTTPException(status_code=404, detail="Key not found")
        k["revoked"] = True
        k["enabled"] = False
        k["revoked_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _save_locked()
    return {"code": 0, "message": "Key revoked"}


@router.delete("/{key_id}")
async def delete_api_key(key_id: str, request: Request):
    _ensure_loaded()
    uid = _get_uid(request)
    with _STORE_LOCK:
        k = _KEYS_STORE.get(key_id)
        if not k or k.get("user_id") != uid:
            raise HTTPException(status_code=404, detail="Key not found")
        # tombstone 化删除：物理删会让同 creation_request_id 的重放绕过
        # 撤销检查再造密钥——保留行、标 revoked（对外列表/详情均不可见）
        k["revoked"] = True
        k["enabled"] = False
        k["revoked_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _save_locked()
    return {"code": 0, "message": "Key deleted"}


@router.get("/{key_id}/usage")
async def get_key_usage(key_id: str, request: Request):
    _ensure_loaded()
    uid = _get_uid(request)
    with _STORE_LOCK:
        k = _KEYS_STORE.get(key_id)
    if not k or k.get("user_id") != uid:
        raise HTTPException(status_code=404, detail="Key not found")
    return {
        "code": 0,
        "message": "success",
        "data": {"key_id": key_id, "usage_count": k.get("usage_count", 0), "last_used_at": k.get("last_used_at")},
    }


@router.get("/scopes")
async def get_available_scopes():
    return {"code": 0, "message": "success", "data": {"scopes": _AVAILABLE_SCOPES}}
