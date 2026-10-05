"""
Agent 外部通信 API 端点（简化版）

功能:
1. API密钥管理API（生成、查看、更新、撤销、删除）
2. 握手协议API
3. 消息发送/接收API
4. 外部Agent管理API
5. 用户隔离（所有操作都验证用户权限）

多用户隔离机制:
- 所有API端点经路由级 `get_current_user_or_api_key` 一道门验身份：JWT 优先，无 JWT 时
  用 `X-API-Key`（真相源 `APIKeyManager`，持久化）；两者都不成立 → 401，不回落 default
- 每个用户只能访问自己的Agent通信资源
- API密钥绑定到特定用户和Agent；撤销或过期即刻被那道门拒认
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from neurova.api.api_key_manager import get_api_key_manager
from neurova.api.auth import get_current_user_or_api_key
from neurova.api.external_agent_protocol import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    deriveAgentStatus,
    negotiationMode,
    validateMessageSize,
    validateProtocolVersion,
)
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user_or_api_key)],)


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
    supported_versions: Optional[List[str]] = Field(
        default=None, description="客户端声明的协议版本；缺省按 legacy 放行"
    )


class SendMessageRequest(BaseModel):
    """发送消息请求"""

    target_agent_id: str = Field(..., description="目标Agent ID")
    message_type: str = Field(default="text", description="消息类型")
    content: Dict[str, Any] = Field(..., description="消息内容")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


# ---------------------------------------------------------------------------
# In-Memory Store
# ---------------------------------------------------------------------------
#
# 只放"本次进程内的会话态"（握手记录、消息、外部 Agent 在线态）。
# **密钥不在这里**：签发/存储/验证统一走 `api_key_manager.APIKeyManager`
# （持久化 + DCL 单例），原来这张进程内 `_api_keys` 与其 `_generate_api_key` /
# `_hash_api_key` 已按教义第 7 条退役——凭证的存储面与认证面必须是同一份东西。

_handshakes: Dict[str, Dict[str, Any]] = {}
_messages: List[Dict[str, Any]] = []
_external_agents: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# 身份解析单源：本域**不再自己解 Authorization，也不再自己认密钥**。
# 路由级 `APIRouter(dependencies=[Depends(get_current_user_or_api_key)])` 是唯一那道门
# （JWT 优先，其次经 APIKeyManager 验密钥；两者都不成立才 401，绝不回落 default 身份），
# 端点直接复用它的返回值——FastAPI 按请求缓存依赖结果，一处解析两处共享。
#
# 这里曾有第二份解析：`authorization.startswith("Bearer ")` 大小写敏感，而 HTTPBearer
# 不敏感——同一枚合法 token 用 `bearer` 送出能过门、却在那份解析里落到 default 租户，
# 实测这样签发的密钥在正常列表里直接看不见（红灯与取证见
# tests/unit/api/test_agent_communication_identity.py）。


def _externalQuotaRules(auth: Dict[str, Any]) -> Dict[str, Any]:
    """只读取生效规则供握手回显，**不做拦截**。

    限流的唯一执行点是 `RateLimitMiddleware`，它在 handler 之前就已拦下超限请求；
    端点里再查一次额度永远轮不到触发，属"接了不生效"的断点。回显仍取自 firewall，
    保证客户端读到的上限与中间件真正执行的是同一个数。
    """
    from neurova.core.firewall import get_firewall

    return get_firewall().get_effective_rules(auth.get("user_id", "default"))


# ---------------------------------------------------------------------------
# Routes - API Key Management
# ---------------------------------------------------------------------------


@router.post("/api-keys", response_model=GenerateAPIKeyResponse)
async def generate_api_key(
    body: GenerateAPIKeyRequest,
    auth: Dict[str, Any] = Depends(get_current_user_or_api_key),
):
    """签发 API 密钥：写进唯一真相源 `APIKeyManager`（持久化、可被那道门验证）。

    本域原来那张进程内 `_api_keys` 已退役——它既没有验证消费方，又随进程重启失效；
    而凭证与存储必须同源，否则"能签发"和"能认证"读写的不是同一份东西。
    注意管理器自带 `default_expiry_days`（未显式传 expires_in_days 时按 365 天过期），
    这是选定那份的既有策略，不是本批新加的约束。
    """
    manager = get_api_key_manager()
    rawKey, apiKey = manager.generate_key(
        agent_id=body.agent_id,
        user_id=auth.get("user_id", "default"),
        name=body.name,
        permissions=list(body.permissions),
        expires_in_days=body.expires_in_days,
    )

    return GenerateAPIKeyResponse(
        key_id=apiKey.key_id,
        api_key=rawKey,
        name=apiKey.name,
        agent_id=apiKey.agent_id,
        permissions=list(apiKey.permissions),
        created_at=float(apiKey.created_at),
        expires_at=float(apiKey.expires_at) if apiKey.expires_at else None,
    )


def _requireOwnedKey(manager, keyId: str, userId: str):
    """按 key_id 取回并校验归属：不存在 404，非本人 403（沿用既有对外语义）"""
    apiKey = manager.get_key_by_id(keyId)
    if not apiKey:
        raise HTTPException(status_code=404, detail="API key not found")
    if apiKey.user_id != userId:
        raise HTTPException(status_code=403, detail="Permission denied")
    return apiKey


@router.get("/api-keys")
async def get_api_keys(
    auth: Dict[str, Any] = Depends(get_current_user_or_api_key),
):
    """获取Agent的所有API密钥"""
    user_id = auth.get("user_id", "default")
    keys = [
        {
            "key_id": k.key_id,
            "name": k.name,
            "agent_id": k.agent_id,
            "permissions": list(k.permissions),
            # 管理器用 is_active 表达状态，对外契约仍是 revoked（前端类型不改）
            "revoked": not k.is_active,
            "created_at": float(k.created_at),
            "expires_at": float(k.expires_at) if k.expires_at else None,
        }
        for k in get_api_key_manager().get_user_keys(user_id)
    ]
    return {"code": 0, "data": {"api_keys": keys}}


@router.put("/api-keys/{key_id}")
async def update_api_key(
    key_id: str,
    body: UpdateAPIKeyRequest,
    auth: Dict[str, Any] = Depends(get_current_user_or_api_key),
):
    """更新API密钥信息"""
    manager = get_api_key_manager()
    _requireOwnedKey(manager, key_id, auth.get("user_id"))
    manager.update_key(key_id, name=body.name, permissions=body.permissions)

    return {"code": 0, "message": "API key updated"}


@router.post("/api-keys/{key_id}/revoke")
async def revoke_api_key(
    key_id: str,
    auth: Dict[str, Any] = Depends(get_current_user_or_api_key),
):
    """撤销API密钥（撤销后那道门立即拒认这把键）"""
    manager = get_api_key_manager()
    _requireOwnedKey(manager, key_id, auth.get("user_id"))
    manager.revoke_key(key_id)

    return {"code": 0, "message": "API key revoked"}


@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: str,
    auth: Dict[str, Any] = Depends(get_current_user_or_api_key),
):
    """删除API密钥"""
    manager = get_api_key_manager()
    _requireOwnedKey(manager, key_id, auth.get("user_id"))
    manager.delete_key(key_id)

    return {"code": 0, "message": "API key deleted"}


# ---------------------------------------------------------------------------
# Routes - Handshake Protocol
# ---------------------------------------------------------------------------


@router.post("/handshake")
async def handshake(
    body: HandshakeRequestModel,
    auth: Dict[str, Any] = Depends(get_current_user_or_api_key),
):
    """握手协议端点"""
    accepted, reason = validateProtocolVersion(body.supported_versions)
    if not accepted:
        raise HTTPException(status_code=400, detail=reason)

    externalRules = _externalQuotaRules(auth)

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
    }

    return {
        "code": 0,
        "data": {
            "handshake_id": handshake_id,
            "status": "completed",
            "server_agent_id": "neurova",
            "server_capabilities": ["chat", "memory", "tools", "skills"],
            "server_protocol_version": PROTOCOL_VERSION,
            "protocol_negotiation": negotiationMode(body.supported_versions),
            # 回显与拦截同源：这两个值就是本端点接下来真的会执行的判据，
            # 不是被退役模块那种"回显了但从不拦"的谎报。
            "max_message_bytes": MAX_MESSAGE_BYTES,
            "rate_limit_per_minute": externalRules["external_rate_limit_per_minute"],
        },
    }


# ---------------------------------------------------------------------------
# Routes - Message Send/Receive
# ---------------------------------------------------------------------------


@router.post("/messages/send")
async def send_message(
    body: SendMessageRequest,
    auth: Dict[str, Any] = Depends(get_current_user_or_api_key),
):
    """发送消息"""
    ok, size = validateMessageSize(body.content)
    if not ok:
        raise HTTPException(
            status_code=413,
            detail=f"消息内容超限: {size} 字节（上限 {MAX_MESSAGE_BYTES} 字节）",
        )

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
        logger.warning("Failed to deliver message via agent: %s", e)

    # 投递被受理即为活动证据：刷新目标 Agent 的 last_seen。
    # 没有这个写入点，超时判定会把所有 Agent 集体判成离线（现役只在握手/注册时写）。
    target = _external_agents.get(body.target_agent_id)
    if target is not None and target.get("user_id") == auth.get("user_id", "default"):
        target["last_seen"] = now

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
    auth: Dict[str, Any] = Depends(get_current_user_or_api_key),
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
    auth: Dict[str, Any] = Depends(get_current_user_or_api_key),
):
    """列出外部Agent"""
    user_id = auth.get("user_id", "default")
    now = time.time()
    agents = [
        {**agent, "status": deriveAgentStatus(agent.get("last_seen"), now)}
        for agent in _external_agents.values()
        if agent.get("user_id") == user_id
    ]
    return {"code": 0, "data": {"agents": agents}}


@router.post("/external-agents")
async def register_external_agent(
    body: HandshakeRequestModel,
    auth: Dict[str, Any] = Depends(get_current_user_or_api_key),
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
    }
    return {"code": 0, "message": f"External agent '{body.agent_id}' registered"}


@router.get("/external-agents/{agent_id}/status")
async def get_agent_status(
    agent_id: str,
    auth: Dict[str, Any] = Depends(get_current_user_or_api_key),
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
            "status": deriveAgentStatus(agent.get("last_seen"), time.time()),
            "last_seen": agent.get("last_seen", 0),
        },
    }


@router.get("/routing/stats")
async def get_routing_stats(
    auth: Dict[str, Any] = Depends(get_current_user_or_api_key),
):
    """获取路由统计信息"""
    user_id = auth.get("user_id", "default")
    user_messages = [m for m in _messages if m.get("user_id") == user_id]

    return {
        "code": 0,
        "data": {
            "total_messages": len(user_messages),
            "external_agents": len([a for a in _external_agents.values() if a.get("user_id") == user_id]),
            "api_keys": len(get_api_key_manager().get_user_keys(user_id)),
        },
    }
