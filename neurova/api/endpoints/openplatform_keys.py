"""
开放平台API密钥管理端点
"""

import datetime
import hashlib
import logging
import secrets
import typing
import uuid

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from pydantic import BaseModel
from pydantic import Field

logger = logging.getLogger(__name__)
router = APIRouter()


class CreateApiKeyRequest(BaseModel):
    name: str
    scopes: typing.List[str] = Field(default_factory=list)
    expires_in_days: int = Field(default=90, ge=1, le=365)
    description: str = ""

class UpdateApiKeyRequest(BaseModel):
    name: typing.Optional[str] = None
    scopes: typing.Optional[typing.List[str]] = None
    enabled: typing.Optional[bool] = None


_KEYS_STORE: typing.Dict[str, dict] = {}
_AVAILABLE_SCOPES = [
    {"id": "read", "name": "Read", "description": "Read-only access"},
    {"id": "write", "name": "Write", "description": "Create and update"},
    {"id": "delete", "name": "Delete", "description": "Delete resources"},
    {"id": "agent:chat", "name": "Agent Chat", "description": "Chat with agents"},
    {"id": "memory:read", "name": "Memory Read", "description": "Read memories"},
]


def _get_uid(request) -> str:
    return getattr(request.state, "user_id", "anonymous")

def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

def _gen_key() -> tuple:
    key = f"nrv_{secrets.token_urlsafe(32)}"
    return key, _hash_key(key), key[:12] + "..."


@router.get("/")
async def list_api_keys(request: Request, page: int = 1, size: int = 20):
    uid = _get_uid(request)
    keys = [k for k in _KEYS_STORE.values() if k.get("user_id") == uid and not k.get("revoked")]
    keys.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    start = (page - 1) * size
    return {"code": 0, "message": "success", "data": {"items": keys[start:start+size], "total": len(keys), "page": page, "size": size}}


@router.post("/")
async def create_api_key(body: CreateApiKeyRequest, request: Request):
    uid = _get_uid(request)
    kid = str(uuid.uuid4())[:12]
    full, h, prefix = _gen_key()
    now = datetime.datetime.utcnow()
    data = {
        "id": kid, "name": body.name, "description": body.description, "key_prefix": prefix,
        "key_hash": h, "scopes": body.scopes, "enabled": True, "revoked": False,
        "user_id": uid, "created_at": now.isoformat(),
        "expires_at": (now + datetime.timedelta(days=body.expires_in_days)).isoformat(),
        "last_used_at": None, "usage_count": 0,
    }
    _KEYS_STORE[kid] = data
    return {"code": 0, "message": "Key created", "data": {**data, "key": full}}


@router.get("/{key_id}")
async def get_api_key(key_id: str, request: Request):
    uid = _get_uid(request)
    k = _KEYS_STORE.get(key_id)
    if not k or k.get("user_id") != uid:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"code": 0, "message": "success", "data": k}


@router.put("/{key_id}")
async def update_api_key(key_id: str, body: UpdateApiKeyRequest, request: Request):
    uid = _get_uid(request)
    k = _KEYS_STORE.get(key_id)
    if not k or k.get("user_id") != uid:
        raise HTTPException(status_code=404, detail="Key not found")
    if body.name is not None: k["name"] = body.name
    if body.scopes is not None: k["scopes"] = body.scopes
    if body.enabled is not None: k["enabled"] = body.enabled
    k["updated_at"] = datetime.datetime.utcnow().isoformat()
    return {"code": 0, "message": "Key updated", "data": k}


@router.post("/{key_id}/revoke")
async def revoke_api_key(key_id: str, request: Request):
    uid = _get_uid(request)
    k = _KEYS_STORE.get(key_id)
    if not k or k.get("user_id") != uid:
        raise HTTPException(status_code=404, detail="Key not found")
    k["revoked"] = True
    k["enabled"] = False
    k["revoked_at"] = datetime.datetime.utcnow().isoformat()
    return {"code": 0, "message": "Key revoked"}


@router.delete("/{key_id}")
async def delete_api_key(key_id: str, request: Request):
    uid = _get_uid(request)
    k = _KEYS_STORE.get(key_id)
    if not k or k.get("user_id") != uid:
        raise HTTPException(status_code=404, detail="Key not found")
    del _KEYS_STORE[key_id]
    return {"code": 0, "message": "Key deleted"}


@router.get("/{key_id}/usage")
async def get_key_usage(key_id: str, request: Request):
    uid = _get_uid(request)
    k = _KEYS_STORE.get(key_id)
    if not k or k.get("user_id") != uid:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"code": 0, "message": "success", "data": {"key_id": key_id, "usage_count": k.get("usage_count", 0), "last_used_at": k.get("last_used_at")}}


@router.get("/scopes")
async def get_available_scopes():
    return {"code": 0, "message": "success", "data": {"scopes": _AVAILABLE_SCOPES}}
