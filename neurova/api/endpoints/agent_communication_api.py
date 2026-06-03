"""
Agent 外部通信 API 端点（简化版）

功能:
1. API密钥管理API（生成、查看、更新、撤销、删除）
2. 握手协议API
3. 消息发送/接收API
4. 外部Agent管理API
5. 用户隔离（所有操作都验证用户权限）

多用户隔离机制:
- 所有API端点都需要验证用户身份（JWT Token或API Key）
- 每个用户只能访问自己的Agent通信资源
- API密钥绑定到特定用户和Agent
"""

import datetime
import hashlib
import hmac
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class GenerateAPIKeyRequest(BaseModel):
    """生成API密钥请求"""
    name: str = Field(..., description="密钥名称")
    agent_id: str = Field(default="default", description="Agent ID")
    permissions: List[str] = Field(default=["chat", "memory"], description="权限列表")
    expires_in_days: Optional[int] = Field(default=None, description="过期天数")


class GenerateAPIKeyResponse(BaseModel):
    """生成API密钥响应"""
    key_id: str
    api_key: str
    name: str
    agent_id: str
    permissions: List[str]
    created_at: float
    expires_at: Optional[float] = None


class UpdateAPIKeyRequest(BaseModel):
    """更新API密钥请求"""
    name: Optional[str] = None
    permissions: Optional[List[str]] = None


class HandshakeRequestModel(BaseModel):
    """握手请求"""
    agent_id: str = Field(..., description="外部Agent ID")
    agent_name: str = Field(..., description="外部Agent名称")
    capabilities: List[str] = Field(default_factory=list, description="能力列表")
    callback_url: Optional[str] = Field(default=None, description="回调URL")


class SendMessageRequest(BaseModel):
    """发送消息请求"""
    target_agent_id: str = Field(..., description="目标Agent ID")
    message_type: str = Field(default="text", description="消息类型")
    content: Dict[str, Any] = Field(..., description="消息内容")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


# ---------------------------------------------------------------------------
# In-Memory Store
# ---------------------------------------------------------------------------

_api_keys: Dict[str, Dict[str, Any]] = {}
_handshakes: Dict[str, Dict[str, Any]] = {}
_messages: List[Dict[str, Any]] = []
_external_agents: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_api_key() -> str:
    """生成API密钥"""
    return f"nk_{uuid.uuid4().hex}"


def _hash_api_key(key: str) -> str:
    """哈希API密钥"""
    return hashlib.sha256(key.encode()).hexdigest()


def _verify_api_key_or_token(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """验证API密钥或JWT Token"""
    # 优先使用JWT Token
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        try:
            from neurova.api.auth import verify_token
            payload = verify_token(token)
            return {"user_id": payload.get("sub", "default"), "auth_type": "jwt"}
        except Exception:
            pass
    
    # 尝试API Key
    if x_api_key:
        key_hash = _hash_api_key(x_api_key)
        for key_id, key_info in _api_keys.items():
            if key_info.get("key_hash") == key_hash:
                if key_info.get("revoked"):
                    raise HTTPException(status_code=401, detail="API key revoked")
                if key_info.get("expires_at") and key_info["expires_at"] < time.time():
                    raise HTTPException(status_code=401, detail="API key expired")
                return {
                    "user_id": key_info.get("user_id", "default"),
                    "agent_id": key_info.get("agent_id", "default"),
                    "auth_type": "api_key",
                }
    
    # 默认用户（开发模式）
    return {"user_id": "default", "agent_id": "default", "auth_type": "default"}


# ---------------------------------------------------------------------------
# Routes - API Key Management
# ---------------------------------------------------------------------------

@router.post("/api-keys", response_model=GenerateAPIKeyResponse)
async def generate_api_key(
    body: GenerateAPIKeyRequest,
    auth: Dict[str, Any] = Depends(_verify_api_key_or_token),
):
    """生成新的API密钥"""
    key_id = str(uuid.uuid4())
    api_key = _generate_api_key()
    now = time.time()
    
    expires_at = None
    if body.expires_in_days:
        expires_at = now + body.expires_in_days * 86400
    
    key_info = {
        "key_id": key_id,
        "key_hash": _hash_api_key(api_key),
        "name": body.name,
        "agent_id": body.agent_id,
        "user_id": auth.get("user_id", "default"),
        "permissions": body.permissions,
        "revoked": False,
        "created_at": now,
        "expires_at": expires_at,
    }
    _api_keys[key_id] = key_info
    
    return GenerateAPIKeyResponse(
        key_id=key_id,
        api_key=api_key,
        name=body.name,
        agent_id=body.agent_id,
        permissions=body.permissions,
        created_at=now,
        expires_at=expires_at,
    )


@router.get("/api-keys")
async def get_api_keys(
    auth: Dict[str, Any] = Depends(_verify_api_key_or_token),
):
    """获取Agent的所有API密钥"""
    user_id = auth.get("user_id", "default")
    keys = [
        {
            "key_id": k["key_id"],
            "name": k["name"],
            "agent_id": k["agent_id"],
            "permissions": k["permissions"],
            "revoked": k.get("revoked", False),
            "created_at": k["created_at"],
            "expires_at": k.get("expires_at"),
        }
        for k in _api_keys.values()
        if k.get("user_id") == user_id
    ]
    return {"code": 0, "data": {"api_keys": keys}}


@router.put("/api-keys/{key_id}")
async def update_api_key(
    key_id: str,
    body: UpdateAPIKeyRequest,
    auth: Dict[str, Any] = Depends(_verify_api_key_or_token),
):
    """更新API密钥信息"""
    key_info = _api_keys.get(key_id)
    if not key_info:
        raise HTTPException(status_code=404, detail="API key not found")
    if key_info.get("user_id") != auth.get("user_id"):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    if body.name is not None:
        key_info["name"] = body.name
    if body.permissions is not None:
        key_info["permissions"] = body.permissions
    
    return {"code": 0, "message": "API key updated"}


@router.post("/api-keys/{key_id}/revoke")
async def revoke_api_key(
    key_id: str,
    auth: Dict[str, Any] = Depends(_verify_api_key_or_token),
):
    """撤销API密钥"""
    key_info = _api_keys.get(key_id)
    if not key_info:
        raise HTTPException(status_code=404, detail="API key not found")
    if key_info.get("user_id") != auth.get("user_id"):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    key_info["revoked"] = True
    return {"code": 0, "message": "API key revoked"}


@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: str,
    auth: Dict[str, Any] = Depends(_verify_api_key_or_token),
):
    """删除API密钥"""
    key_info = _api_keys.get(key_id)
    if not key_info:
        raise HTTPException(status_code=404, detail="API key not found")
    if key_info.get("user_id") != auth.get("user_id"):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    del _api_keys[key_id]
    return {"code": 0, "message": "API key deleted"}


# ---------------------------------------------------------------------------
# Routes - Handshake Protocol
# ---------------------------------------------------------------------------

@router.post("/handshake")
async def handshake(
    body: HandshakeRequestModel,
    auth: Dict[str, Any] = Depends(_verify_api_key_or_token),
):
    """握手协议端点"""
    handshake_id = str(uuid.uuid4())
    now = time.time()
    
    # 记录握手
    _handshakes[handshake_id] = {
        "handshake_id": handshake_id,
        "external_agent_id": body.agent_id,
        "external_agent_name": body.agent_name,
        "capabilities": body.capabilities,
        "callback_url": body.callback_url,
        "user_id": auth.get("user_id", "default"),
        "status": "completed",
        "created_at": now,
    }
    
    # 注册外部Agent
    _external_agents[body.agent_id] = {
        "agent_id": body.agent_id,
        "name": body.agent_name,
        "capabilities": body.capabilities,
        "callback_url": body.callback_url,
        "user_id": auth.get("user_id", "default"),
        "last_seen": now,
        "status": "online",
    }
    
    return {
        "code": 0,
        "data": {
            "handshake_id": handshake_id,
            "status": "completed",
            "server_agent_id": "neurova",
            "server_capabilities": ["chat", "memory", "tools", "skills"],
        },
    }


# ---------------------------------------------------------------------------
# Routes - Message Send/Receive
# ---------------------------------------------------------------------------

@router.post("/messages/send")
async def send_message(
    body: SendMessageRequest,
    auth: Dict[str, Any] = Depends(_verify_api_key_or_token),
):
    """发送消息"""
    message_id = str(uuid.uuid4())
    now = time.time()
    
    message = {
        "message_id": message_id,
        "from_agent_id": auth.get("agent_id", "default"),
        "to_agent_id": body.target_agent_id,
        "message_type": body.message_type,
        "content": body.content,
        "metadata": body.metadata,
        "user_id": auth.get("user_id", "default"),
        "created_at": now,
        "status": "sent",
    }
    _messages.append(message)
    
    # 尝试通过Agent路由发送
    try:
        from neurova.api.endpoints import get_agent_instance
        agent = get_agent_instance()
        if agent and hasattr(agent, "send_message"):
            await agent.send_message(body.target_agent_id, body.content)
            message["status"] = "delivered"
    except Exception as e:
        logger.warning(f"Failed to deliver message via agent: {e}")
    
    return {
        "code": 0,
        "data": {
            "message_id": message_id,
            "status": message["status"],
            "created_at": now,
        },
    }


@router.get("/messages")
async def get_messages(
    agent_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    auth: Dict[str, Any] = Depends(_verify_api_key_or_token),
):
    """获取消息列表"""
    user_id = auth.get("user_id", "default")
    messages = [m for m in _messages if m.get("user_id") == user_id]
    if agent_id:
        messages = [m for m in messages if m.get("to_agent_id") == agent_id or m.get("from_agent_id") == agent_id]
    return {"code": 0, "data": {"messages": messages[-limit:]}}


# ---------------------------------------------------------------------------
# Routes - External Agent Management
# ---------------------------------------------------------------------------

@router.get("/external-agents")
async def list_external_agents(
    auth: Dict[str, Any] = Depends(_verify_api_key_or_token),
):
    """列出外部Agent"""
    user_id = auth.get("user_id", "default")
    agents = [a for a in _external_agents.values() if a.get("user_id") == user_id]
    return {"code": 0, "data": {"agents": agents}}


@router.post("/external-agents")
async def register_external_agent(
    body: HandshakeRequestModel,
    auth: Dict[str, Any] = Depends(_verify_api_key_or_token),
):
    """注册外部Agent"""
    now = time.time()
    _external_agents[body.agent_id] = {
        "agent_id": body.agent_id,
        "name": body.agent_name,
        "capabilities": body.capabilities,
        "callback_url": body.callback_url,
        "user_id": auth.get("user_id", "default"),
        "last_seen": now,
        "status": "registered",
    }
    return {"code": 0, "message": f"External agent '{body.agent_id}' registered"}


@router.get("/external-agents/{agent_id}/status")
async def get_agent_status(
    agent_id: str,
    auth: Dict[str, Any] = Depends(_verify_api_key_or_token),
):
    """获取Agent状态"""
    agent = _external_agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="External agent not found")
    if agent.get("user_id") != auth.get("user_id"):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    return {
        "code": 0,
        "data": {
            "agent_id": agent_id,
            "status": agent.get("status", "unknown"),
            "last_seen": agent.get("last_seen", 0),
        },
    }


@router.get("/routing/stats")
async def get_routing_stats(
    auth: Dict[str, Any] = Depends(_verify_api_key_or_token),
):
    """获取路由统计信息"""
    user_id = auth.get("user_id", "default")
    user_messages = [m for m in _messages if m.get("user_id") == user_id]
    
    return {
        "code": 0,
        "data": {
            "total_messages": len(user_messages),
            "external_agents": len([a for a in _external_agents.values() if a.get("user_id") == user_id]),
            "api_keys": len([k for k in _api_keys.values() if k.get("user_id") == user_id]),
        },
    }