"""
移动设备配对 API

端点:
- POST /mobile/pairing/generate   — 生成配对记录（高熵 `ref` ＋ 6 位手输短码）
- GET  /mobile/pairing/qrcode/{code} — 二维码图（文本是 `neurova://pair?ref=…`，**不含 host**）
- POST /mobile/pairing/resolve    — 扫码后换取回连地址（`ref` 一次性消费）
- POST /mobile/pairing/confirm    — 确认配对 → 一次性接入凭证 ＋ 长期设备身份
- POST /mobile/pairing/cancel     — 属主主动撤码（不等 TTL 到点）
- POST /mobile/pairing/refresh    — 接入凭证过期后由设备身份续签（不必回屏幕前重扫）
- GET  /mobile/pairing/status/{code} — 轮询配对状态（只给登录本人读）
- GET  /mobile/pairing/list       — 列出在册设备（读持久注册表）
- DELETE /mobile/pairing/{pairing_id} — 解除配对（递增 epoch ⇒ 旧凭证立即失效）
- WS   /mobile/ws                 — 凭证走 header／子协议；`?token=` 只兼容一版

设计事实源：`docs/04-plans/2026-10-24-移动端扫码经中继连接无固定IP服务端设计方案.md`
（凭据与地址分离、四条状态机、S0/S1a/S1b 的分期与判据都在那里）。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import threading

from neurova.core import config
from neurova.core import mobile_device_store
from neurova.core.logger import get_logger
from neurova.tunnel import protocol
import secrets
import time
import uuid
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter()
security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class GeneratePairingRequest(BaseModel):
    """生成配对请求"""

    device_name: Optional[str] = Field(default=None, description="设备名称")
    device_type: str = Field(default="mobile", description="设备类型")


class GeneratePairingResponse(BaseModel):
    """生成配对响应

    `ref` 是给手机的那一份（进二维码）；`code` 是**同一条记录**的手输入口，
    不是第二个凭据体系（设计方案 §4.1）。
    """

    code: str
    ref: str
    qr_code_url: str
    expires_in: int
    pairing_id: str


class ResolvePairingRequest(BaseModel):
    """手机端扫码后换取回连地址的请求（匿名口，只凭一次性 `ref`）"""

    ref: str = Field(..., description="二维码里的高熵一次性引用")


class ResolvePairingResponse(BaseModel):
    """回连地址——**不含任何凭证**：地址可以进日志，凭据不行（§4.2）"""

    ws_url: str
    pairing_id: str
    expires_in: int
    status: str


class ConfirmPairingRequest(BaseModel):
    """确认配对请求

    `ref`（扫码来）与 `code`（手输来）二选一；两个入口指向同一条配对记录。
    """

    ref: Optional[str] = Field(default=None, description="二维码里的 ref")
    code: Optional[str] = Field(default=None, description="手输的 6 位配对码")
    device_name: Optional[str] = Field(default=None, description="设备名称")
    device_id: Optional[str] = Field(default=None, description="设备 ID")


class ConfirmPairingResponse(BaseModel):
    """确认配对响应

    `device_secret` 只在这一次回出（库里存的是它的摘要）：它是"这台设备是谁"的凭据，
    之后每次续签用它换**短时效**的 `connect_ticket`，不再需要回到屏幕前扫码。
    """

    success: bool
    connect_ticket: Optional[str] = None
    ws_url: Optional[str] = None
    device_secret: Optional[str] = None
    pairing_id: Optional[str] = None
    message: str
    expires_in: int = protocol.CONNECT_TICKET_TTL_SECONDS


class CancelPairingRequest(BaseModel):
    """面板主动撤码（§5.1 的 `aborted`：误扫/换码不必干等 300 秒）"""

    code: str = Field(..., description="要撤回的配对码")


class RefreshPairingRequest(BaseModel):
    """接入凭证续签：设备身份（`pairing_id` + `device_secret`）＋一次性 `challenge`"""

    pairing_id: str
    device_secret: str
    challenge: str = Field(default="", description="与本张 ticket 绑定的随机数")


class RefreshPairingResponse(BaseModel):
    """续签只换凭证，**不动在册状态**（§5.1b 判据）"""

    connect_ticket: str
    pairing_id: str
    expires_in: int
    message: str = "已续签"


class PairingStatusResponse(BaseModel):
    """配对状态响应"""

    code: str
    status: str  # pending, confirmed, expired, revoked
    device_name: Optional[str] = None
    confirmed_at: Optional[float] = None


class PairedDeviceResponse(BaseModel):
    """已配对设备响应"""

    pairing_id: str
    device_name: str
    device_type: str
    device_id: Optional[str] = None
    paired_at: float
    last_active: Optional[float] = None
    is_online: bool = False


# ---------------------------------------------------------------------------
# 配对码（一次性）与在册设备（长期）分两处存
# ---------------------------------------------------------------------------

_pairing_codes: Dict[str, Dict[str, Any]] = {}  # code -> pairing info

# WebSocket 连接管理：pairing_id -> **当下**这条活连接。
# 在册设备本身不在这里——它是 `mobile_device_store` 的持久权威（§4.8）。
# 这一份只承担"现在有没有活连接"的读数，进程重启后必然为 0 条，那正是它的语义。
_ws_connections: Dict[str, WebSocket] = {}  # pairing_id -> WebSocket

# 接入凭证的两本账（§4.2：一次性）：
#   _outstanding_tickets: 发出去、还没被兑现的 ticket -> 过期时刻
#   _spent_tickets:      已兑现过的 ticket -> 兑现时刻（防第二次重放）
# 刻意**不**落库：这两本账的有效期是 60 秒量级，为它建一张表等于把"重启后所有设备失联"
# 那种故障再复制一遍，而重启本来就会让在途票据自然失效（内存态即正确语义）。
_outstanding_tickets: Dict[str, float] = {}
_spent_tickets: Dict[str, float] = {}

# ---------------------------------------------------------------------------
# 在册设备注册表（DCL 单例，AGENTS §3）
# ---------------------------------------------------------------------------

_deviceRegistry: Optional["mobile_device_store.MobileDeviceStore"] = None
_deviceRegistryLock = threading.RLock()


def deviceStorePath() -> str:
    """在册库落点（单点解析；判据按这一条换路径，不另写第二份 env 拼接）。"""
    return mobile_device_store.dbPathForNewStore()


def getDeviceRegistry() -> "mobile_device_store.MobileDeviceStore":
    global _deviceRegistry
    if _deviceRegistry is None:
        with _deviceRegistryLock:
            if _deviceRegistry is None:
                _deviceRegistry = mobile_device_store.MobileDeviceStore(deviceStorePath())
    return _deviceRegistry


def resetDeviceRegistry() -> None:
    """释放并清空单例——「进程重启」语义的唯一可测形态（先例 `reset_config_manager()`）。

    必须连连接一起关：留着旧句柄，下一个用例以为自己在重启后的进程里跑，
    其实读的还是上一份状态——那是一条假绿。
    """
    global _deviceRegistry
    with _deviceRegistryLock:
        if _deviceRegistry is not None:
            _deviceRegistry.close()
        _deviceRegistry = None


# 审计修复 (P1-8): confirm_pairing 每 IP 速率限制 —— 6 位配对码 300s TTL
# 无限流时可在窗口内枚举 (10^6/300s)。滑窗: 同 IP 5 分钟内最多 5 次尝试。
_CONFIRM_RATE_LIMIT = protocol.CONFIRM_RATE_LIMIT
_CONFIRM_RATE_WINDOW_SECONDS = protocol.CONFIRM_RATE_WINDOW_SECONDS
_confirm_attempts: Dict[str, List[float]] = {}  # ip -> [timestamp, ...]

# 旧 token 的绝对有效期。S1b 用「短时效 ticket ＋ challenge 续签」取代它；
# 在撤销真正生效之前，它仍是唯一在起作用的失效手段（§10.2 的根因）。
_LEGACY_WS_TOKEN_TTL_SECONDS = 86400

# 审计修复 (P2-12): 单用户 WS 连接上限（口径出处在 protocol，此处只是本地别名）
MAX_CONNECTIONS_PER_USER = protocol.MAX_CONNECTIONS_PER_USER

# HMAC 密钥（用于生成 WS Token）
_DEFAULT_WS_SECRET = "neurova-ws-secret-key-2026"


def _get_ws_secret() -> str:
    """获取 WS HMAC 密钥

    生产环境必须配置 NEUROVA_WS_SECRET，否则拒绝启动（安全设计）。
    开发环境允许使用默认弱密钥（便于本地调试）。
    """
    import os

    env = os.environ.get("NEUROVA_ENV", config.get("NEUROVA_ENV", "development"))
    secret = os.environ.get("NEUROVA_WS_SECRET") or config.get("NEUROVA_WS_SECRET")

    if not secret:
        if env in ("production", "prod"):
            raise HTTPException(
                status_code=500,
                detail="NEUROVA_WS_SECRET 未配置，生产环境必须设置此环境变量",
            )
        secret = _DEFAULT_WS_SECRET

    return secret


# 取消标记（资源修复 #3, 台账 2026-09-11）：仅在对应 chat:send 流式执行生命周期内
# 有效——_handle_chat_send 开始时消费残留标记（孤儿取消不误杀下一次发送）、
# 流终态弹出；无在流会话消费的孤儿标记按 _CANCELLED_SESSIONS_MAX 封顶逐出最旧。
_CANCELLED_SESSIONS_MAX = 512
_cancelled_sessions: Dict[str, bool] = {}

# B-6 (台账 2026-09-11): chat:send spawn 的独立流式 task 引用集
# （参照 multi_model_client._pending_tasks 姿势）——持强引用防 GC 回收
# 未完成 task，done_callback 自动 discard。
_chat_tasks: Set["asyncio.Task"] = set()


async def _run_chat_stream(ws, data: dict, user_id: str):
    """B-6: 独立 task 执行 chat:send 流式回复。

    任务被 cancel（chat:cancel 中途取消 / 连接断开收尸）时 CancelledError
    不经 _handle_chat_send 的 except Exception（BaseException 不被捕获），
    在此补发 chat:cancelled 保持客户端取消事件契约，再原样上抛。
    """
    sid = data.get("session_id", "")
    try:
        await _handle_chat_send(ws, data, user_id)
    except asyncio.CancelledError:
        try:
            await ws.send_json({"type": "chat:cancelled", "session_id": sid})
        except Exception:
            pass  # 连接已断，通知失败不影响收尸
        raise


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _advertisedBaseUrl() -> str:
    """对外地址的**唯一**读处（设计方案 §7）。空串＝没配，退回按入站请求出地址。

    为什么需要它：服务端无固定 IP 时，入站请求那个 Host 是中继/反代的地址或局域网地址，
    照它出回连地址，手机在网外就连不上。这一条也是「一台固定域名的反代机 + DDNS」
    那条最朴素路线今天就能跑通的前提。
    """
    raw = (config.get("NEUROVA_ADVERTISED_BASE_URL") or "").strip()
    return raw.rstrip("/")


def _wsOrigin(request) -> tuple:
    """出地址时 `(scheme, netloc, pathPrefix)` 的来源，优先级单点在此。

    隧道 route > advertised > 入站请求（经代理时后者已由 uvicorn 的代理中间件修正）。
    为什么隧道第一：无固定 IP 场景里，只有注册上的那条 route 是手机一定够得着的入口；
    advertised 往往是家里那条会漂的地址。

    **不自己解析 `X-Forwarded-*`**：那是第二份事实源，且绕过 uvicorn 已做的受信判定
    （`forwarded_allow_ips`）——任何人都能靠塞一个头伪造来源 IP，把每 IP 限流绕成没有。
    """
    from urllib.parse import urlsplit

    from neurova.tunnel.agent import getTunnelAgent

    status = getTunnelAgent().tunnelStatus()
    if status["configured"] and status["state"] == "via_relay" and status["route_id"]:
        relayUrl = getTunnelAgent().relayUrl
        normalized = relayUrl if "://" in relayUrl else "https://" + relayUrl
        parts = urlsplit(normalized)
        wsScheme = "wss" if parts.scheme in ("https", "wss") else "ws"
        prefix = (parts.path.rstrip("/")
                  + f"{protocol.RELAY_ROUTE_PREFIX}{status['route_id']}")
        return wsScheme, parts.netloc, prefix

    advertised = _advertisedBaseUrl()
    if advertised:
        if "://" not in advertised:
            advertised = "http://" + advertised
        parts = urlsplit(advertised)
        secure = parts.scheme in ("https", "wss")
        return ("wss" if secure else "ws"), parts.netloc, parts.path
    parts = urlsplit(str(request.url_for("mobile_websocket")))
    secure = getattr(request.url, "scheme", "http") == "https"
    return ("wss" if secure else "ws"), parts.netloc, ""


def _build_ws_url(request) -> str:
    """设备回连地址：**路径**向路由表要，**对外口径**向 advertised 要（§6-172 批 26 ＋ §7）。

    原先这里把 `/mobile/ws` **抄在函数里**（BE-MOB-001 那次只改了 host/scheme 的来处），
    而本模块的挂载前缀由注册表给：`/api` + `/v1/mobile`（`endpoints/__init__.py:345`）。
    抄出来的那条路径在真实路由表里根本不存在——`POST /pairing/confirm` 回的 `ws_url`
    与批 25 那张"终于能扫"的二维码，发的都是同一个连不上的地址：扫完只能失败一次。

    参数面刻意收窄成"只有 request"：它不再接受任何凭证或配对码拼进 query（§4.2）。
    这条 URL 会原样进中继的访问日志，历史上 `?token=`／`?code=` 都挂在这里，
    等于让每一次中转都替我们记一次凭据。
    """
    routePath = urlsplit(str(request.url_for("mobile_websocket"))).path
    scheme, netloc, prefix = _wsOrigin(request)
    return f"{scheme}://{netloc}{prefix}{routePath}"


def _generate_pairing_code() -> str:
    """生成 6 位数字配对码——形状与熵源的**唯一出处**在 `protocol.generateShortCode()`。

    原先这里自己写了一遍 `secrets.randbelow` 循环；配对码是认证凭据，
    它的熵源形态不允许有第二份（教义第 6 条：发现第二份定义时收口，不留并行）。
    """
    return protocol.generateShortCode()


def _prune_expired_pairing_codes() -> None:
    """P2-8: 清除已过期的配对码（原实现过期只改 status 从不 pop，dict 只增不清）。

    expires_at 已过的条目无论 pending/confirmed/expired 均回收：
    - pending 过期 → 早已不可确认；
    - confirmed 过期 → 设备已在在册注册表（`mobile_device_store`），码条目本身冗余。
    """
    now = time.time()
    expired = [code for code, p in _pairing_codes.items() if now > p.get("expires_at", 0)]
    for code in expired:
        del _pairing_codes[code]


def _check_confirm_rate_limit(ip: str) -> None:
    """confirm_pairing 每 IP 滑动窗口限流, 超限抛 429"""
    now = time.time()
    # P2-8: 时间线整条滑出窗口的 IP 连键删除, 防 _confirm_attempts 只增不清
    stale_ips = [
        k for k, ts in _confirm_attempts.items()
        if not ts or now - max(ts) >= _CONFIRM_RATE_WINDOW_SECONDS
    ]
    for k in stale_ips:
        del _confirm_attempts[k]
    attempts = _confirm_attempts.setdefault(ip, [])
    # 剔除窗口外记录
    attempts[:] = [t for t in attempts if now - t < _CONFIRM_RATE_WINDOW_SECONDS]
    if len(attempts) >= _CONFIRM_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Too many pairing attempts. Please try again later.",
        )
    attempts.append(now)


def _generate_ws_token(user_id: str, pairing_id: str) -> str:
    """生成 WebSocket Token（HMAC 签名）"""
    message = f"{user_id}:{pairing_id}:{int(time.time())}"
    signature = hmac.new(_get_ws_secret().encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}:{signature}"


def _issueConnectTicket(user_id: str, pairing_id: str, token_epoch: int) -> str:
    """接入凭证（短时效、**单次消费**）。

    与旧 `ws_token` 的区别不是"期限更短"这一个字：
    - 旧形态把可重放的 24h 凭证挂在 URL query 上，经中继后必然落进中继的访问日志；
    - 这里回的是**一次性**票据，用过即焚（`_consumeConnectTicket`），
      且只经 header／子协议传输（§4.2）。
    签名覆盖里带上在册 `token_epoch`，撤销后旧票一起失效（§4.8）。
    """
    message = f"{user_id}:{pairing_id}:{token_epoch}:{int(time.time())}"
    signature = hmac.new(_get_ws_secret().encode(), message.encode(), hashlib.sha256).hexdigest()
    ticket = f"{message}:{signature}"
    _outstanding_tickets[ticket] = time.time() + protocol.CONNECT_TICKET_TTL_SECONDS
    _pruneTickets()
    return ticket


def _consumeConnectTicket(ticket: str) -> Optional[Dict[str, str]]:
    """校验并**消费**一张 ticket。

    三步都过才算数：签名自洽、未过期、且此前没被消费过。
    第三步是这张票与旧 token 的实质差别——旧 token 在有效期内可以无限次重放。
    """
    now = time.time()
    spent = _spent_tickets.get(ticket)
    if spent is not None and now - spent < protocol.CONNECT_TICKET_TTL_SECONDS * 2:
        return None                       # 已经用过了：一次性凭据不能第二次兑现
    info = _verify_ws_token(ticket)
    if not info:
        return None
    issuedAt = _outstanding_tickets.pop(ticket, None)
    if issuedAt is None or now - issuedAt > protocol.CONNECT_TICKET_TTL_SECONDS:
        return None
    _spent_tickets[ticket] = now
    return info


def _pruneTickets() -> None:
    """回收既没在用、也没在"已消费"名单里的条目——两本账都会只增不清（P2-8 同族）。"""
    now = time.time()
    horizon = now - protocol.CONNECT_TICKET_TTL_SECONDS * 2
    for spentKey in [k for k, v in _spent_tickets.items() if v < horizon]:
        _spent_tickets.pop(spentKey, None)
    for outstandingKey in [k for k, issuedAt in _outstanding_tickets.items() if issuedAt < now]:
        _outstanding_tickets.pop(outstandingKey, None)


def _verify_ws_token(token: str) -> Optional[Dict[str, str]]:
    """验证 WebSocket Token，并回出它携带的在册 epoch。

    注意这条**只验凭据自洽**，不判设备是否还在册；在册判定在
    `getDeviceRegistry().isAdmissible()`，两半都要过才放行（§4.8 第 1 条）。
    """
    try:
        parts = token.split(":")
        if len(parts) != 5:
            return None

        user_id, pairing_id, epoch, timestamp, signature = parts
        message = f"{user_id}:{pairing_id}:{epoch}:{timestamp}"
        expected_signature = hmac.new(_get_ws_secret().encode(), message.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            return None

        # 检查是否过期（旧形态的绝对期；S1b 由短时效 ticket + 续签取代）
        if time.time() - float(timestamp) > _LEGACY_WS_TOKEN_TTL_SECONDS:
            return None

        return {"user_id": user_id, "pairing_id": pairing_id, "token_epoch": epoch}
    except Exception:
        return None


async def _get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """从 JWT Token 提取 user_id（真正的 JWT 解析）"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization")

    try:
        from neurova.api.auth import decode_token

        payload = decode_token(credentials.credentials)
        if payload is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        uid = payload.get("sub")
        if not uid:
            raise HTTPException(status_code=401, detail="Token missing subject")
        return uid
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ---------------------------------------------------------------------------
# MobileConnectionManager
# ---------------------------------------------------------------------------


class MobileConnectionManager:
    """移动设备 WebSocket 连接管理器"""

    _instance: Optional["MobileConnectionManager"] = None
    # 懒建单例的双检锁（AGENTS.md §3）：RLock 允许构造链回落到同一入口
    _instanceLock = threading.RLock()

    def __init__(self):
        if MobileConnectionManager._instance is not None:
            raise RuntimeError("Use get_instance() instead")
        self._connections: Dict[str, WebSocket] = {}
        self._user_connections: Dict[str, Set[str]] = {}  # user_id -> set of connection_ids

    @classmethod
    def get_instance(cls) -> "MobileConnectionManager":
        if cls._instance is None:
            with cls._instanceLock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def connect(self, websocket: WebSocket, user_id: str, connection_id: str) -> bool:
        """建立连接

        审计修复 (P2-12): 单用户连接数超 MAX_CONNECTIONS_PER_USER 时拒绝
        （不 accept），返回 False 由调用方关闭, 防止单用户耗尽连接资源。
        """
        if len(self._user_connections.get(user_id, set())) >= MAX_CONNECTIONS_PER_USER:
            logger.warning("用户 %s 连接数已达上限 %s, 拒绝新连接", user_id, MAX_CONNECTIONS_PER_USER)
            return False

        await websocket.accept()
        self._connections[connection_id] = websocket

        if user_id not in self._user_connections:
            self._user_connections[user_id] = set()
        self._user_connections[user_id].add(connection_id)

        logger.info("Mobile WebSocket connected: %s for user %s", connection_id, user_id)
        return True

    def disconnect(self, connection_id: str, user_id: str):
        """断开连接"""
        self._connections.pop(connection_id, None)
        if user_id in self._user_connections:
            self._user_connections[user_id].discard(connection_id)
            if not self._user_connections[user_id]:
                del self._user_connections[user_id]

        logger.info("Mobile WebSocket disconnected: %s", connection_id)

    async def send_to_user(self, user_id: str, message: dict):
        """向指定用户的所有连接发送消息"""
        if user_id not in self._user_connections:
            return

        connection_ids = list(self._user_connections[user_id])
        for conn_id in connection_ids:
            ws = self._connections.get(conn_id)
            if ws:
                try:
                    await ws.send_json(message)
                except Exception:
                    self.disconnect(conn_id, user_id)

    async def broadcast(self, message: dict):
        """向所有连接广播消息"""
        for conn_id, ws in list(self._connections.items()):
            try:
                await ws.send_json(message)
            except Exception:
                # 清理断开的连接
                user_id = None
                for uid, conn_ids in self._user_connections.items():
                    if conn_id in conn_ids:
                        user_id = uid
                        break
                if user_id:
                    self.disconnect(conn_id, user_id)

    def get_online_count(self) -> int:
        """获取在线连接数"""
        return len(self._connections)


# ---------------------------------------------------------------------------
# WS 消息处理函数（M0.5.2）
# ---------------------------------------------------------------------------


async def _handle_chat_send(ws, data: dict, user_id: str):
    """处理 chat:send -- 流式聊天核心"""
    content = (data.get("content") or "").strip()
    if not content:
        await ws.send_json({"type": "error", "code": "empty_content", "message": "内容不能为空"})
        return

    agent_id = data.get("agent_id", "default")
    session_id = data.get("session_id", f"mobile-{uuid.uuid4().hex[:8]}")

    # 孤儿取消标记只对在流会话生效：新流开始即消费残留标记
    _cancelled_sessions.pop(session_id, None)

    agent = None
    agentLookupFailed = False
    try:
        from neurova.api.endpoints import get_agent_instance

        agent = get_agent_instance(agent_id)
    except Exception:
        # 把故障读成"不存在"是 §6-126 那一族的又一形：装配/导入坏掉时客户端同样只收到
        # 一句 `agent_not_found`，服务端一行日志都没有——真因永远看不见。
        logger.exception("mobile 取 Agent 失败 agent=%s", agent_id)
        agentLookupFailed = True

    if agent is None:
        await ws.send_json({
            "type": "error",
            "code": "agent_lookup_failed" if agentLookupFailed else "agent_not_found",
            "message": (f"Agent '{agent_id}' 查询失败（详见服务端日志）" if agentLookupFailed
                        else f"Agent '{agent_id}' 不存在"),
        })
        return

    try:
        index = 0
        # 请求级属主（§6-154 合修的第二半）：这条面从 JWT/配对码里就拿到了人，
        # 但从不交给请求通道——`mem_core.save_to_session` 与 usage 入账读的就是这条通道，
        # 空读数的后果是 usage 记 `anonymous`、按日 LLM 配额整条不判、会话落空属主（对全员可见）。
        # 写在 `_handle_chat_send` 内：这条函数本身就跑在 `chat:send` 那条 task 上
        # （`mobile_websocket` 里 `create_task(_run_chat_stream(...))`），不存在"写在外层 task 而内层看不见"。
        from neurova.core.identity_context import set_request_user_id

        set_request_user_id(user_id)
        turnMetadata = {"user_id": user_id, "role": "user", "tenant_id": "default"}
        if hasattr(agent, "chat_stream") and callable(agent.chat_stream):
            async for chunk in agent.chat_stream(user_input=content, session_id=session_id,
                                                 metadata=turnMetadata):
                if _cancelled_sessions.get(session_id):
                    await ws.send_json({"type": "chat:cancelled", "session_id": session_id})
                    return
                await ws.send_json({"type": "chat:chunk", "content": str(chunk), "session_id": session_id, "index": index})
                index += 1
        else:
            result = await agent.chat(user_input=content, session_id=session_id,
                                      metadata=turnMetadata)
            text = result.get("text", "") if isinstance(result, dict) else str(result)
            await ws.send_json({"type": "chat:chunk", "content": text, "session_id": session_id, "index": index})
            index += 1

        await ws.send_json({"type": "chat:done", "session_id": session_id, "message_id": f"msg-{uuid.uuid4().hex[:8]}"})
    except Exception as e:
        # 原先这里只把异常文本发给客户端、服务端一行都不记——一次 `TypeError`（调用点参数名
        # 与 `Agent.chat_stream` 的真签名对不上）就这样把整个移动端对话面挂了四个月而无人可见。
        # 客户端事件契约保持不变（`chat_failed`），但根因必须留在日志里。
        logger.exception("mobile chat:send 回合失败 agent=%s session=%s", agent_id, session_id)
        await ws.send_json({"type": "error", "code": "chat_failed", "message": str(e)})
    finally:
        # 资源修复 #3: 取消标记随流终态（done/cancelled/error）回收
        _cancelled_sessions.pop(session_id, None)


async def _handle_chat_cancel(ws, data: dict):
    """处理 chat:cancel -- 取消进行中的聊天"""
    session_id = data.get("session_id", "")
    if session_id:
        _cancelled_sessions[session_id] = True
        # 资源修复 #3: 封顶兜底——孤儿标记（无在流会话弹出）超限逐出最旧
        while len(_cancelled_sessions) > _CANCELLED_SESSIONS_MAX:
            _cancelled_sessions.pop(next(iter(_cancelled_sessions)))


async def _handle_agent_switch(ws, data: dict):
    """处理 agent:switch -- 切换 Agent"""
    agent_id = data.get("agent_id", "")
    agent = None
    agentLookupFailed = False
    try:
        from neurova.api.endpoints import get_agent_instance

        agent = get_agent_instance(agent_id)
    except Exception:
        # 把故障读成"不存在"是 §6-126 那一族的又一形：装配/导入坏掉时客户端同样只收到
        # 一句 `agent_not_found`，服务端一行日志都没有——真因永远看不见。
        logger.exception("mobile 取 Agent 失败 agent=%s", agent_id)
        agentLookupFailed = True

    if agent is None:
        await ws.send_json({
            "type": "error",
            "code": "agent_lookup_failed" if agentLookupFailed else "agent_not_found",
            "message": (f"Agent '{agent_id}' 查询失败（详见服务端日志）" if agentLookupFailed
                        else f"Agent '{agent_id}' 不存在"),
        })
        return

    await ws.send_json({
        "type": "agent:switched",
        "agent_id": agent_id,
        "config": {
            "agent_id": getattr(agent, "agent_id", agent_id),
            "name": getattr(agent, "name", agent_id),
        },
    })


async def _handle_session_list(ws, data: dict, user_id: str):
    """处理 session:list -- 列出会话

    审计修复 (P0-4): 原实现调 get_sessions(agent_id) 返回该 agent 下
    所有用户的完整会话（含全部消息），任何已配对手机可拉取全员对话。
    现按 WS 身份的 user_id 过滤, 且只返回摘要而非全文。
    """
    agent_id = data.get("agent_id", "default")
    try:
        from neurova.session_manager import get_session_manager

        sm = get_session_manager()
        sessions = sm.list_sessions(agent_id=agent_id, user_id=user_id)
        await ws.send_json({"type": "session:list", "sessions": sessions})
    except Exception as e:
        logger.exception("mobile session:list 失败")
        await ws.send_json({"type": "error", "code": "session_list_failed", "message": str(e)})


async def _handle_session_create(ws, data: dict, user_id: str):
    """处理 session:create -- 创建新会话

    审计修复 (P0-4): 会话必须绑定创建者 user_id, 否则无归属。
    """
    agent_id = data.get("agent_id", "default")
    try:
        from neurova.session_manager import get_session_manager

        sm = get_session_manager()
        session_id = sm.create_session(agent_id, user_id=user_id)
        await ws.send_json({"type": "session:created", "session": {"session_id": session_id, "agent_id": agent_id}})
    except Exception as e:
        logger.exception("mobile session:create 失败 agent=%s", agent_id)
        await ws.send_json({"type": "error", "code": "session_create_failed", "message": str(e)})


async def _handle_ws_message(ws, data: dict, user_id: str, pairing_id: str):
    """WS 消息分发器

    任务4（台账第五节登记③，双路径归一）：chat:send/chat:cancel 由
    mobile_websocket 的 receive 循环统一拦截（B-6 在流 task 路径），
    分发器不再内联承载平行分支——两类消息唯一处理入口为连接循环。
    """
    msg_type = data.get("type", "")
    handlers = {
        "agent:switch": lambda: _handle_agent_switch(ws, data),
        "session:list": lambda: _handle_session_list(ws, data, user_id),
        "session:create": lambda: _handle_session_create(ws, data, user_id),
    }
    handler = handlers.get(msg_type)
    if handler is None:
        await ws.send_json({"type": "error", "code": "unknown_type", "message": f"Unknown message type: {msg_type}"})
        return
    try:
        await handler()
    except Exception as e:
        logger.exception("mobile WS 分发器处理 %s 失败", msg_type)
        await ws.send_json({"type": "error", "code": "handler_error", "message": str(e)})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/pairing/tunnel/status")
async def get_tunnel_status(user_id: str = Depends(_get_current_user_id)):
    """通道此刻的状态（设计方案 §5.2／§6.1）——面板徽标的唯一读处。

    为什么要有这一口：`relay_down` 时发出去的二维码是一张**扫不出的图**（手机连不上那个
    入口）。没有这条读数，面板只能在"等待扫码"上一直挂着，用户等满 300 秒才知道坏了——
    这正是 AGENTS §2 说的"把故障渲染成进行中"。
    """
    from neurova.tunnel.agent import getTunnelAgent

    status = getTunnelAgent().tunnelStatus()
    status["address_source"] = _addressSource()
    return {"code": 0, "data": status}


def _addressSource() -> str:
    """本次会用的地址来源（`direct` / `via_relay`）——与隧道态**可并存**，见 §5.2。"""
    return "via_relay" if _relayRouteIsUsable() else "direct"


def _relayRouteIsUsable() -> bool:
    """配了中继，且此刻真的注册上了。

    没配中继（`relayUrl` 为空）时回 False，但**这不代表不能配对**：局域网与
    「一台固定域名的反代机」两条路照走（设计方案 §7 的 advertised 优先级）。
    所以这一条只用来 gate"配了中继却没连上"那种**必然失败**的发码。
    """
    from neurova.tunnel.agent import getTunnelAgent

    status = getTunnelAgent().tunnelStatus()
    return bool(status["configured"]) and status["state"] == "via_relay"


def _requireScannableChannel() -> None:
    """发码前的通道判定：配了中继又没注册上 ⇒ 显式 503，并点名原因。

    刻意**不**把"没配中继"也拒掉：那样会把已经跑通的局域网/自建反代配对一起打死，
    而那一面有在册判据（`test_mobile_pairing_endpoints.py`）。设计文档 §5.5 第 6 条
    写的是"M2=disabled 时拒发"，落地时收窄成"配了中继且未注册才拒"——
    差异已回写文档，不以规则的字面为准把功能杀掉（AGENTS 核心原则：规则与行为不符时改规则）。
    """
    from neurova.tunnel.agent import getTunnelAgent

    status = getTunnelAgent().tunnelStatus()
    if status["configured"] and status["state"] != "via_relay":
        raise HTTPException(
            status_code=503,
            detail={
                "code": protocol.TUNNEL_ERROR_CODES[0],
                "message": ("中继已配置但未注册成功（当前 %s），现在生成的二维码手机扫了也连不上；"
                            "请检查中继可达性与准入凭据" % status["state"]),
                "tunnel_state": status["state"],
            },
        )


@router.post("/pairing/generate", response_model=GeneratePairingResponse)
async def generate_pairing(
    request: Request,
    body: GeneratePairingRequest,
    user_id: str = Depends(_get_current_user_id),
):
    """生成配对码 + 二维码"""
    _requireScannableChannel()
    code = _generate_pairing_code()
    ref = protocol.generatePairingRef()
    pairing_id = f"pair-{uuid.uuid4().hex[:12]}"
    expires_in = protocol.PAIRING_CODE_TTL_SECONDS  # 口径单源在 protocol，此处不写字面量

    # P2-8: 创建新码时顺带回收已过期码，防 _pairing_codes 只增不清
    _prune_expired_pairing_codes()

    _pairing_codes[code] = {
        "code": code,
        "ref": ref,
        "pairing_id": pairing_id,
        "user_id": user_id,
        "device_name": body.device_name,
        "device_type": body.device_type,
        "status": "pending",
        "created_at": time.time(),
        "expires_at": time.time() + expires_in,
    }

    # 二维码必须同源出（§6-172 批 25）：原先回的是外部渲染服务的 URL，等于把配对凭据
    # 连 ws 地址一起交给第三方，而确认后那条设备就挂到账号名下。路径由路由表自己给
    # （`url_for`），不在端点里再抄一份 `/api/v1/mobile/…`。
    qr_code_url = str(request.url_for("get_pairing_qrcode", code=code))

    return GeneratePairingResponse(
        code=code,
        ref=ref,
        qr_code_url=qr_code_url,
        expires_in=expires_in,
        pairing_id=pairing_id,
    )


@router.get("/pairing/qrcode/{code}", dependencies=[Depends(_get_current_user_id)])
async def get_pairing_qrcode(code: str):
    """配对二维码（PNG）——渲染只走渠道侧那**唯一一份** segno 实现（§6-172 批 25）。

    原先这里 `import qrcode`，而那个库**不在依赖清单**（清单里声明的是 segno），
    于是 `try` 恒定落到 `except ImportError`，回的是一张"方框里写着配对码"的 SVG 占位图：
    手机扫它扫不出任何东西，端点却承诺"获取配对二维码图片（PNG）"——失败被一张
    看着像成功的图盖住了（教义第 2 条禁止的形态）。现在渲染器全仓一处，渲染不出就显式 5xx。

    文本形状由 `protocol.pairingQrPayload()` 定（**不含 host**）：这张图拍下来贴到网上，
    读到的人拿到的是一条一次性引用，而不是"某台机器的地址＋6 位码"。
    """
    pairing = _pairing_codes.get(code)
    if not pairing:
        raise HTTPException(status_code=404, detail="Pairing code not found")

    from fastapi.responses import Response

    # 函数内 import 与渠道侧调用方同一形态（`channel_config.py:300`），也保住测试的替换面
    from neurova.channels.qrcode_auth import generate_qrcode_image

    png = base64.b64decode(generate_qrcode_image(protocol.pairingQrPayload(pairing["ref"])))
    return Response(
        content=png,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="qr-{code}.png"'},
    )


def _pairingByRef(ref: str) -> Optional[Dict[str, Any]]:
    """按 `ref` 找那条配对记录（`ref` 与 `code` 是同一条记录的两个入口，不是两套凭据）。"""
    for pairing in _pairing_codes.values():
        if pairing.get("ref") == ref:
            return pairing
    return None


def _requireLivePairing(pairing: Dict[str, Any]) -> None:
    """未过期判定（两个入口共用，不各写一遍）。"""
    if time.time() > pairing["expires_at"]:
        pairing["status"] = "expired"
        raise HTTPException(status_code=410, detail="Pairing code expired")


def _requireExchangeablePairing(pairing: Dict[str, Any]) -> None:
    """`ref` 的一次性在这里兑现：只有 `pending` 能被兑换，`scanned` 之后不再回话。

    这就是 §10.1 那条裁定的落点——不设 `scanned → pending` 回边。
    拍下那张图的人在超时后重放，拿不到第二次地址；他要么走完这次配对，要么等它过期。
    """
    _requireLivePairing(pairing)
    if pairing["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Pairing code is {pairing['status']}")


def _requireConfirmablePairing(pairing: Dict[str, Any]) -> None:
    """确认可以发生在 `pending`（手输短码，没经过 resolve）或 `scanned`（扫过码）。"""
    _requireLivePairing(pairing)
    if pairing["status"] not in ("pending", "scanned"):
        raise HTTPException(status_code=400, detail=f"Pairing code is {pairing['status']}")


@router.post("/pairing/resolve", response_model=ResolvePairingResponse)
async def resolve_pairing(request: Request, body: ResolvePairingRequest):
    """扫码后换取回连地址（手机端调用，无需 JWT）。

    这一步把「谁」翻译成「在哪」：载荷里只有 ref，地址是**现在**算出来的，
    所以服务端换了出口（DDNS 漂移、中继重注册）不影响已经发出去的那张图。
    `ref` 在此**一次性消费**——`pending → scanned`，同一张图第二次兑换必被拒（§10.1）。
    """
    _check_confirm_rate_limit(request.client.host if request.client else "unknown")

    if not protocol.isPairingRefShape(body.ref):
        raise HTTPException(status_code=404, detail="Unknown pairing reference")

    pairing = _pairingByRef(body.ref)
    if not pairing:
        raise HTTPException(status_code=404, detail="Unknown pairing reference")
    _requireExchangeablePairing(pairing)

    pairing["status"] = "scanned"
    pairing["scanned_at"] = time.time()

    return ResolvePairingResponse(
        ws_url=_build_ws_url(request),
        pairing_id=pairing["pairing_id"],
        # 剩下的窗口按原 TTL 算：不另起一个计时器，否则面板与手机看到的倒计时会分叉
        expires_in=max(0, int(pairing["expires_at"] - time.time())),
        status="scanned",
    )


@router.post("/pairing/confirm", response_model=ConfirmPairingResponse)
async def confirm_pairing(request: Request, body: ConfirmPairingRequest):
    """确认配对（手机端调用，无需 JWT）——`ref`（扫码）或 `code`（手输）二选一。

    回两样东西：一次性接入凭证 `connect_ticket` 与长期设备身份 `device_secret`。
    地址里**不带任何凭证**（§4.2）：这条 URL 会进中继的访问日志，凭证不能跟着它走。
    """
    _check_confirm_rate_limit(request.client.host if request.client else "unknown")

    if body.ref:
        if not protocol.isPairingRefShape(body.ref):
            raise HTTPException(status_code=404, detail="Invalid pairing reference")
        pairing = _pairingByRef(body.ref)
    elif body.code:
        pairing = _pairing_codes.get(body.code)
    else:
        raise HTTPException(status_code=422, detail="Either ref or code is required")

    if not pairing:
        raise HTTPException(status_code=404, detail="Invalid pairing code")
    _requireConfirmablePairing(pairing)

    # 确认配对
    pairing["status"] = "confirmed"
    pairing["confirmed_at"] = time.time()
    pairing["device_name"] = body.device_name or pairing.get("device_name", "Unknown Device")
    pairing["device_id"] = body.device_id

    # 设备身份：长期密钥只在这一次回出，库里存它的摘要（§4.7）
    deviceSecret = secrets.token_urlsafe(32)
    registry = getDeviceRegistry()
    registry.register(
        pairingId=pairing["pairing_id"],
        userId=pairing["user_id"],
        deviceName=pairing["device_name"],
        deviceType=pairing.get("device_type", "mobile"),
        deviceId=body.device_id or "",
        deviceSecret=deviceSecret,
    )

    ticket = _issueConnectTicket(
        pairing["user_id"], pairing["pairing_id"],
        registry.epochOf(pairing["pairing_id"]) or 0)

    return ConfirmPairingResponse(
        success=True,
        connect_ticket=ticket,
        ws_url=_build_ws_url(request),
        device_secret=deviceSecret,
        pairing_id=pairing["pairing_id"],
        message="配对成功",
        expires_in=protocol.CONNECT_TICKET_TTL_SECONDS,
    )


@router.post("/pairing/cancel", response_model=dict, dependencies=[Depends(_get_current_user_id)])
async def cancel_pairing(body: CancelPairingRequest):
    """属主主动撤码：`pending/scanned → aborted`（§5.1）。

    没有这一口，误扫或"这张图不想再挂着了"只能干等 300 秒——
    §10.1 里"不设宽限计时器"的前提正是**人随时能撤**，两者是一套，不能只做一半。
    """
    pairing = _pairing_codes.get(body.code)
    if not pairing:
        raise HTTPException(status_code=404, detail="Pairing code not found")
    if pairing["status"] not in ("pending", "scanned"):
        raise HTTPException(status_code=409, detail=f"Pairing code is {pairing['status']}")

    pairing["status"] = "aborted"
    return {"code": 0, "message": "配对码已撤回", "status": "aborted"}


@router.post("/pairing/refresh", response_model=RefreshPairingResponse)
async def refresh_pairing(request: Request, body: RefreshPairingRequest):
    """接入凭证过期后由**设备身份**续签（§10.2 已裁＝丙）。

    这一口的存在就是为了让"关机过夜／飞行模式一天"不必回到屏幕前重扫：
    旧形态只在 `confirm` 时铸一次凭证，超窗口即永久失效，而仓内没有任何再签发路径。

    判据三条，缺一就退回旧问题：设备身份必须验、设备必须**仍在册**、
    且**不改在册状态**（改了就等于把续签做成了重新配对）。
    """
    _check_confirm_rate_limit(request.client.host if request.client else "unknown")

    registry = getDeviceRegistry()
    if not registry.verifyDeviceSecret(body.pairing_id, body.device_secret):
        raise HTTPException(status_code=403, detail="device_deregistered_or_not_this_device")
    device = registry.get(body.pairing_id)
    if not registry.isAdmissible(body.pairing_id, registry.epochOf(body.pairing_id)):
        raise HTTPException(status_code=410, detail="device_deregistered")

    ticket = _issueConnectTicket(
        device["user_id"], body.pairing_id, registry.epochOf(body.pairing_id) or 0)

    return RefreshPairingResponse(
        connect_ticket=ticket,
        pairing_id=body.pairing_id,
        expires_in=protocol.CONNECT_TICKET_TTL_SECONDS,
    )


@router.get("/pairing/status/{code}", response_model=PairingStatusResponse,
            dependencies=[Depends(_get_current_user_id)])
async def get_pairing_status(code: str):
    """轮询配对状态——**只给登录本人读**（§6-172 批 28，裁定乙）。

    这两个按码回话的读面原先无门（`s08_route_auth_baseline:787` 整节 `router_deps=[]`）：
    认码回图/状态、不认回 404，而 6 位配对码是 `_generate_pairing_code` 自陈的**唯一认证凭据**，
    只有 10^6 个取值——匿名调用方拿它当枚举预言机，探到一个存在的码就能去 `confirm` 它，
    设备随即挂到别人账号名下。`confirm` 有每 IP 限流，这两个口一个都没有。
    """
    pairing = _pairing_codes.get(code)
    if not pairing:
        raise HTTPException(status_code=404, detail="Pairing code not found")

    # 检查是否过期
    if pairing["status"] == "pending" and time.time() > pairing["expires_at"]:
        pairing["status"] = "expired"

    return PairingStatusResponse(
        code=code,
        status=pairing["status"],
        device_name=pairing.get("device_name"),
        confirmed_at=pairing.get("confirmed_at"),
    )


@router.get("/pairing/list")
async def list_paired_devices(
    user_id: str = Depends(_get_current_user_id),
):
    """列出在册设备（需 JWT 认证）——读的是**持久注册表**，不是进程记忆。

    原实现在这里做了两件不该做的事（§4.8／§4.9 实测）：

    - 「离线且配对超 24h 就删」：系统代属主删掉了他自己配的设备，且删完不吭声。
      现在长期在册，满 30 天无活动只投一个 `dormant` 提醒位，处置权在面板上。
    - 在线态只在挂载/确认/解除三个时刻快照一次，之后永不刷新：面板开着，
      「在线/离线」就是死的。现在每次读都叠加当下的活连接（`_ws_connections`）。
    """
    devices = getDeviceRegistry().listForUser(
        user_id, livePairingIds=set(_ws_connections), now=time.time())

    return {
        "code": 0,
        "data": {
            "devices": devices,
            "total": len(devices),
        },
    }


@router.delete("/pairing/{pairing_id}")
async def revoke_pairing(
    pairing_id: str,
    user_id: str = Depends(_get_current_user_id),
):
    """解除配对（需 JWT 认证）——撤销的效力落在**放行判定**上，不只落在断开连接。

    今天这一口只做到「关掉当下那条连接」：在册记录被删掉后没有任何读者，
    设备随后重连照样通过（旧 token 的 HMAC 仍然自洽）。本批补上 epoch，
    并让产生这台设备的那条码一并转 `revoked`（§2.5：那个态此前从不产生，
    面板因此把「有人解除了设备」读成 404 网络故障）。
    """
    registry = getDeviceRegistry()
    device = registry.get(pairing_id)
    if not device:
        raise HTTPException(status_code=404, detail="Pairing not found")

    if device["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not your device")

    epoch = registry.revoke(pairing_id)
    if epoch is None:
        # 走到这里说明记录在读取与撤销之间消失了；诚实报错，不假装撤销成功
        raise HTTPException(status_code=409, detail="Pairing disappeared during revoke")

    # 由这条配对产生的码转 revoked：面板要能读出"是解除"，而不是"码不存在"
    for pairing in _pairing_codes.values():
        if pairing.get("pairing_id") == pairing_id:
            pairing["status"] = "revoked"

    # 关闭当下那条活连接
    if pairing_id in _ws_connections:
        ws = _ws_connections.pop(pairing_id)
        try:
            await ws.close()
        except Exception:
            pass

    return {
        "code": 0,
        "message": f"设备 '{device['device_name']}' 已解除配对",
    }


def _ticketFromHandshake(websocket: WebSocket) -> Optional[str]:
    """从握手取接入凭证：**header 优先**，`?token=` 只作旧客户端的兼容通道。

    为什么不能继续把凭证放在 URL：这条 URL 会原样进中继的访问日志，而日志的保留期
    和可见面都不在我们手里（§4.2）。Harmony 侧早就在发 `Authorization` 头
    （`WebSocketAdapter.ets:123-127`），浏览器侧走子协议名，两条都够用了。
    """
    header = websocket.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    subprotocol = websocket.headers.get("sec-websocket-protocol", "")
    for offered in (item.strip() for item in subprotocol.split(",")):
        if offered.startswith(protocol.NEUROVA_AUTH_SUBPROTOCOL + "."):
            return offered.split(".", 1)[1]
    return None


@router.websocket("/ws")
async def mobile_websocket(websocket: WebSocket):
    """移动设备 WebSocket 连接

    三条通道，按可信度排序：一次性接入凭证（header／子协议）→ 旧 `?token=`（兼容一版）
    → 配对码（首次连接，且 `revoke` 已把那条码写成 revoked，状态判定本身就 gate 住了它）。
    """
    code = websocket.query_params.get("code")
    legacyToken = websocket.query_params.get("token")
    ticket = _ticketFromHandshake(websocket)

    user_id = None
    pairing_id = None
    epoch = None

    if ticket:
        info = _consumeConnectTicket(ticket)
        if not info:
            # "签名对但已用过"与"签名错"回同一个 4001：不给枚举者区分"这张票存在过"的机会
            await websocket.close(code=4001, reason="Invalid, expired or already-used ticket")
            return
        user_id = info["user_id"]
        pairing_id = info["pairing_id"]
        epoch = info["token_epoch"]
    elif legacyToken:
        info = _verify_ws_token(legacyToken)
        if not info:
            await websocket.close(code=4001, reason="Invalid or expired token")
            return
        user_id = info["user_id"]
        pairing_id = info["pairing_id"]
        epoch = info["token_epoch"]
    elif code:
        pairing = _pairing_codes.get(code)
        if not pairing or pairing["status"] != "confirmed":
            await websocket.close(code=4001, reason="Invalid or unconfirmed pairing code")
            return
        user_id = pairing["user_id"]
        pairing_id = pairing["pairing_id"]

    if user_id is None:
        await websocket.close(code=4001, reason="Missing authentication")
        return

    # **在册判定**加在凭证通道上，因为"重连"就发生在这两条通道里：签名自洽只回答
    # "这枚凭证是不是我签的"，不回答"这台设备还要不要"。缺这一格时 `revoke` 写下的
    # 标记没有任何读者——解除后设备重连照样放行（§4.8）。
    # 按码通道不再查一次：`revoke` 同时把那条码写成 revoked，上面的状态判定已经在 gate
    # 它——两处 gate 同一件事就是第二个事实源（教义第 6 条）。
    if epoch is not None and not getDeviceRegistry().isAdmissible(pairing_id, epoch):
        await websocket.close(code=4001, reason="device_deregistered")
        return

    # 建立连接
    connection_id = f"ws-{uuid.uuid4().hex[:12]}"
    manager = MobileConnectionManager.get_instance()

    if not await manager.connect(websocket, user_id, connection_id):
        await websocket.close(code=4008, reason="Too many connections for this user")
        return

    _ws_connections[pairing_id] = websocket

    # 在线读数由 `_ws_connections` 叠出来（唯一的活连接源），这里只写活动时间。
    # 原实现把 `is_online` 写进一份内存 dict 又从那份 dict 读——那份 dict 现已退役。
    getDeviceRegistry().recordActivity(pairing_id)
    lastActivityFlush = time.time()

    # B-6: 在流 task 跟踪（spawn 时赋值；断开收尸/中途取消用）
    current_chat_task: Optional[asyncio.Task] = None
    current_chat_sid = ""
    try:
        # 消息循环
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            # 处理心跳
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": time.time()})
                continue

            # 最近活动时间：按**节流**落库，不逐条消息写盘（WAL 下也只是少写，但聊天
            # 场景每条都写没有意义）；终态时在 finally 里补最后一次，读数不滞后。
            if time.time() - lastActivityFlush >= protocol.DEVICE_ACTIVITY_FLUSH_SECONDS:
                getDeviceRegistry().recordActivity(pairing_id)
                lastActivityFlush = time.time()

            msg_type = message.get("type", "")

            # B-6 (台账 2026-09-11): chat:send spawn 独立 task，receive 循环
            # 继续读消息——chat:cancel 不再要等流结束才被处理。
            if msg_type == "chat:send":
                if current_chat_task is not None and not current_chat_task.done():
                    # 同一连接同时只允许一条在流回复：流式中新 send 拒绝
                    await websocket.send_json({
                        "type": "error",
                        "code": "chat_busy",
                        "message": "当前连接已有回复进行中，请等待完成或先取消",
                    })
                    continue
                current_chat_task = asyncio.create_task(
                    _run_chat_stream(websocket, message, user_id)
                )
                current_chat_sid = message.get("session_id", "")
                _chat_tasks.add(current_chat_task)
                current_chat_task.add_done_callback(_chat_tasks.discard)
                continue

            # B-6: 中途取消 = 复用 #3 取消标记 + 立即 cancel 在流 task
            if msg_type == "chat:cancel":
                sid = message.get("session_id", "")
                if (
                    sid
                    and current_chat_task is not None
                    and not current_chat_task.done()
                    and sid == current_chat_sid
                ):
                    current_chat_task.cancel()
                await _handle_chat_cancel(websocket, message)
                continue

            # 分发消息到处理函数
            await _handle_ws_message(websocket, message, user_id, pairing_id)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", connection_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        # B-6: 连接断开 → 收尸在流 task（wrapper 补发 chat:cancelled）
        if current_chat_task is not None and not current_chat_task.done():
            current_chat_task.cancel()
        # 清理连接：`_ws_connections` 弹出即"不再在线"——在线读数是叠出来的，
        # 没有第二处 `is_online` 需要回写（原实现两处写同一件事，正是漂移的温床）。
        manager.disconnect(connection_id, user_id)
        _ws_connections.pop(pairing_id, None)
        getDeviceRegistry().recordActivity(pairing_id)
