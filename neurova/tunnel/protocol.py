# -*- coding: utf-8 -*-
"""移动端配对与隧道的线格式**单源**（设计方案 §4.1／§5.6）。

为什么要这一份：状态词与尺度今天散在端点里（`expires_in = 300` 字面量、
`MAX_CONNECTIONS_PER_USER`、`_WS_TOKEN_TTL_SECONDS`），而 Web 徽标、Harmony 徽标、
服务端回话读的是**同一批词**。任一处漂了，表现不是报错，是「面板显示等待扫码、
其实已解除」这类看不见故障（本卷形态 403：判据读的对象与真装配点不同形）。

纪律：本文件只放**口径**（状态字面量、尺度常量、错误码、形状生成）。
数据库、HTTP、WS 行为都不在这里——放它们各自的模块，别把这里长成第二套实现。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any, Dict, Optional, Sequence

# ---------------------------------------------------------------------------
# 尺度与序（唯一出处）
# ---------------------------------------------------------------------------

#: 配对码/引用有效期。原为端点里的字面量 `expires_in = 300`。
PAIRING_CODE_TTL_SECONDS = 300

#: 面板轮询间隔（毫秒）。与前端 `POLL_MS` 同一口径，改动须三处同批。
PANEL_POLL_INTERVAL_MS = 2000

#: 接入凭证有效期（秒）。§10.2 已裁：短时效＋可续签，续签不改在册状态。
CONNECT_TICKET_TTL_SECONDS = 60

#: 设备无活动满这么多天 ⇒ 只给属主一条提醒位，**不代删**（§4.9）。
DEVICE_DORMANT_AFTER_DAYS = 30

#: 在册设备的「最近活动时间」落库节流（秒）。逐条消息写盘在聊天场景没有意义，
#: 而终态会补一次，所以读数最多滞后这一个窗口，不会停在连接开始的那一刻。
DEVICE_ACTIVITY_FLUSH_SECONDS = 60

#: 单用户 WS 连接上限。
MAX_CONNECTIONS_PER_USER = 5

#: 短码确认的每 IP 滑窗限流（10^6 取值面必须有闸）。
CONFIRM_RATE_LIMIT = 5
CONFIRM_RATE_WINDOW_SECONDS = 300

#: 配对码手输形态：6 位数字（10^6，靠 CSPRNG + 限流，不靠长度）。
SHORT_CODE_DIGITS = 6

#: 高熵一次性引用 `ref` 的字符数（base62，约 2^131）。
PAIRING_REF_LENGTH = 22

_REF_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

# ---------------------------------------------------------------------------
# 认证通道形状
# ---------------------------------------------------------------------------

#: 浏览器 WS 发不出 Authorization 头时的回落通道（子协议名）。
NEUROVA_AUTH_SUBPROTOCOL = "neurova.auth"

WS_CLOSE_INVALID_CREDENTIAL = 4001
WS_CLOSE_TOO_MANY_CONNECTIONS = 4008
WS_CLOSE_TUNNEL_NOT_READY = 4003

# ---------------------------------------------------------------------------
# M1 · 配对码生命周期（一次性）
# ---------------------------------------------------------------------------

PAIRING_CODE_STATES = (
    "pending",     # 已发出，未有人扫
    "scanned",     # ref 已被 resolve（观测态，非软锁）
    "confirmed",   # 手机已确认，设备入册
    "used",        # 接入凭证已兑换，这条码的使命结束
    "expired",     # TTL 到点
    "revoked",     # 属主解除了由它配上的设备（§2.5：今天这个态从不产生）
    "aborted",     # 属主在面板上主动换码/取消
)

PAIRING_CODE_TERMINAL_STATES = ("used", "expired", "revoked", "aborted")

#: 合法边集合。**刻意不含 `scanned → pending`**：`ref` 一经消费即死，
#: 任何"超时把码退回待扫"的实现都等于把一次性凭据改成可重放（§10.1 已裁）。
PAIRING_CODE_TRANSITIONS = {
    "pending": ("scanned", "confirmed", "expired", "aborted"),
    "scanned": ("confirmed", "expired", "aborted"),
    "confirmed": ("used", "revoked", "expired"),
    "used": ("revoked",),
    "expired": (),
    "revoked": (),
    "aborted": (),
}

# ---------------------------------------------------------------------------
# M1b · 在册设备生命周期（长期；与 M1 严格分开）
# ---------------------------------------------------------------------------

DEVICE_REGISTRY_STATES = (
    "unpaired",   # 尚无此设备
    "paired",     # 已入册，还没连上过
    "online",     # 有活连接
    "offline",    # 连过，现在没有
    "dormant",    # 长期无活动——**提醒位，不是删除位**
    "revoked",    # 终态：要再用必须重新扫码
)

#: `dormant` 刻意不在终态里：它是信息，不是处置结果（§4.9）。
DEVICE_REGISTRY_TERMINAL_STATES = ("revoked",)

DEVICE_REGISTRY_TRANSITIONS = {
    "paired": ("online", "offline", "dormant", "revoked"),
    "online": ("offline", "revoked"),
    "offline": ("online", "dormant", "revoked"),
    "dormant": ("online", "revoked"),
    "revoked": (),
}

# ---------------------------------------------------------------------------
# M2 · 通道/隧道
# ---------------------------------------------------------------------------

TUNNEL_STATES = ("disabled", "probing", "via_relay", "relay_down", "evicted")

#: 地址来源与隧道态**可并存**：局域网内 direct 与 via_relay 同时成立是常态。
#: 「本次发码用哪个来源」才是投影对象，不是「通道唯一」（§5.2）。
ADDRESS_SOURCES = ("direct", "via_relay")

TUNNEL_HEARTBEAT_INTERVAL_SECONDS = 15
TUNNEL_MISSES_BEFORE_DOWN = 3
TUNNEL_RECONNECT_MAX_BACKOFF_SECONDS = 30

# ---------------------------------------------------------------------------
# 隧道线格式（控制面／数据面共用；中继与 agent 两侧都从这里取）
# ---------------------------------------------------------------------------

RELAY_CONTROL_PATH = "/agent/control"
RELAY_DATA_PATH = "/agent/data"
#: 客户端侧的入口前缀：`https://<relay>/t/<routeId>/api/v1/mobile/ws`。
#: 用路径前缀而不是子域名——已裁「中继终结 TLS」，就不需要泛域名与每实例证书（§3.3）。
RELAY_ROUTE_PREFIX = "/t/"

ENROLLMENT_TOKEN_PARAM = "enrollmentToken"
ENROLLMENT_TOKEN_ENV = "NEUROVA_TUNNEL_ENROLLMENT_TOKEN"
RELAY_URL_ENV = "NEUROVA_TUNNEL_RELAY_URL"
#: U9.1 兼容开关：`NEUROVA_TUNNEL_URL_TOKEN=1` 时中继临时回退「URL 携 token」旧形态。
#: 默认关（fail-closed：URL 带令牌的连接一律拒绝）。回滚时**两端同开**。
URL_TOKEN_COMPAT_ENV = "NEUROVA_TUNNEL_URL_TOKEN"

FRAME_REGISTER = "register"
FRAME_REGISTERED = "registered"
FRAME_OPEN = "open"
FRAME_DATA = "data"
FRAME_HEAD = "head"
FRAME_END = "end"
FRAME_PING = "ping"
FRAME_PONG = "pong"
FRAME_ERROR = "error"
#: U9.1：连接建立后的**首条**消息 `{"type":"auth","token":...,"tokenType":...}`。
FRAME_AUTH = "auth"
#: 数据面 auth 成功回执（控制面用既有 `registered` 兼任，不再多发一条）。
FRAME_AUTH_OK = "auth_ok"
#: U9.2 newest-wins：同 routeId 新连接顶替时，旧连接收到的通知帧，随后服务端断开。
FRAME_SUPERSEDED = "superseded"

# ---------------------------------------------------------------------------
# 设备桥帧族（移动端执行端，2026-11-23 计划 §4；单源在此，端上按字面量对齐）
# 方向：hello/result/event 是手机 → 后端；execute/cancel 是后端 → 手机；
# hello_ok 是后端对 hello 的确认。命令幂等键 = (pairing_id, command_id)，
# 记账复用 mobile_ws_ledger 的 mobile_ws_commands（先登记 running，回执收敛终态）。
# ---------------------------------------------------------------------------
FRAME_DEVICE_HELLO = "device:hello"          # 手机 → 后端：能力快照 + 运行态
FRAME_DEVICE_HELLO_OK = "device:hello_ok"    # 后端 → 手机：hello 受理回执
FRAME_DEVICE_EXECUTE = "device:execute"      # 后端 → 手机：单条设备命令
FRAME_DEVICE_CANCEL = "device:cancel"        # 后端 → 手机：取消在途命令
FRAME_DEVICE_RESULT = "device:result"        # 手机 → 后端：命令终态回执
FRAME_DEVICE_EVENT = "device:event"          # 手机 → 后端：主动事件上报（P1 消费）

DEVICE_FRAME_TYPES = (
    FRAME_DEVICE_HELLO, FRAME_DEVICE_HELLO_OK, FRAME_DEVICE_EXECUTE,
    FRAME_DEVICE_CANCEL, FRAME_DEVICE_RESULT, FRAME_DEVICE_EVENT,
)

#: 设备能力词表（封闭集）：手机端在 device:hello 里宣称的子集；后端运行前
#: 按它过滤 device_* 工具目录（能力协商）。新能力先加这里，两端再对齐。
DEVICE_CAPABILITIES = (
    "open_url", "open_app",
    "clipboard_read", "clipboard_write",
    "app_list", "device_env",
    "notification_read",
    "screen_observe", "screen_gesture",
    "calendar_read", "calendar_write", "contacts_read",
)

#: 设备桥结构化错误码（诚实失败面；与 TUNNEL_ERROR_CODES 同风格的封闭集）。
DEVICE_ERROR_OFFLINE = "device_offline"                       # 无在线设备可派发
DEVICE_ERROR_TIMEOUT = "device_timeout"                       # 命令在窗口内未回执
DEVICE_ERROR_BRIDGE_DISABLED = "device_bridge_disabled"       # 总闸未开（默认关）
DEVICE_ERROR_UNKNOWN_CAPABILITY = "unknown_capabilities"      # hello 宣称了未知能力
DEVICE_BRIDGE_ERROR_CODES = (
    DEVICE_ERROR_OFFLINE, DEVICE_ERROR_TIMEOUT,
    DEVICE_ERROR_BRIDGE_DISABLED, DEVICE_ERROR_UNKNOWN_CAPABILITY,
)

#: 手机侧一次请求等 agent 把数据通道开出来的窗口。到点必须显式 503，
#: 不许静默重发或降级成 warning（教义第 2 条）。
TUNNEL_STREAM_OPEN_TIMEOUT_SECONDS = 5.0
#: HTTP 体在隧道里**缓冲**搬运的上限；WS 帧是流式过的，不受这条限制。
#: 边界写在这里，不假装隧道什么都能流。
TUNNEL_MAX_BUFFERED_BYTES = 4 * 1024 * 1024

#: U9/U16 追加的错误码（命名常量先立，元组引用之——不另立第二份字面量）。
TUNNEL_ERROR_AUTH_REJECTED = "auth_rejected"           # auth 缺失/首帧不是 auth/签名不成立/声明型不符
TUNNEL_ERROR_TOKEN_TYPE_REJECTED = "token_type_rejected"  # 令牌型进错通道（U16 通道校验型）
TUNNEL_ERROR_AUTH_TIMEOUT = "auth_timeout"             # 连接建立后窗口内没收到合格 auth
TUNNEL_ERROR_URL_TOKEN_REJECTED = "url_token_rejected"  # URL 携 token 旧形态在默认（fail-closed）下被拒

TUNNEL_ERROR_CODES = (
    "tunnel_not_ready",       # 数据通道没在窗口内开出来
    "enrollment_rejected",    # 准入凭据缺失或不匹配
    "route_conflict",         # 别人的 routeId 想被覆盖
    "route_unknown",          # 入口按不认识的 routeId 敲门
    "payload_too_large",
    # U9/U16 追加（只增不改，既有下标语义不动）
    TUNNEL_ERROR_AUTH_REJECTED,
    TUNNEL_ERROR_TOKEN_TYPE_REJECTED,
    TUNNEL_ERROR_AUTH_TIMEOUT,
    TUNNEL_ERROR_URL_TOKEN_REJECTED,
)

# ---------------------------------------------------------------------------
# U9/U16 · 隧道认证口径（token 后置 + 多型 + newest-wins + 全窗 watchdog）
# ---------------------------------------------------------------------------

#: 准入令牌分型（U16）：签发时定型，通道校验型。
TOKEN_TYPE_AGENT = "agent"        # 数据面
TOKEN_TYPE_USER = "user"          # 管理面
TOKEN_TYPE_SERVICE = "service"    # 运维面（agent 的控制连接即此型）
TUNNEL_TOKEN_TYPES = (TOKEN_TYPE_AGENT, TOKEN_TYPE_USER, TOKEN_TYPE_SERVICE)

#: 通道 → 允许的令牌型：控制面仅 user/service；数据面仅 agent/service。
CONTROL_PLANE_TOKEN_TYPES = (TOKEN_TYPE_USER, TOKEN_TYPE_SERVICE)
DATA_PLANE_TOKEN_TYPES = (TOKEN_TYPE_AGENT, TOKEN_TYPE_SERVICE)

#: 定型令牌的信封版本前缀：`nv1:{type}:{issuedAt}:{nonce}:{hmac}`。
#: 无此前缀的令牌 = legacy（旧裸密钥），按 agent 型降级处理（放行数据面、拒绝控制面，
#: 并在日志标注 legacy）。
TUNNEL_TOKEN_ENVELOPE = "nv1"

#: U9.1 auth 交换窗：连接建立后 5s 内收不到合格 auth ⇒ 断开。
TUNNEL_AUTH_TIMEOUT_SECONDS = 5.0
#: U9.3 全窗 watchdog：拨号→TLS→握手→auth 整窗 15s，到点强制放弃并按退避重试。
TUNNEL_CONNECT_WINDOW_SECONDS = 15.0


def urlTokenCompatEnabled() -> bool:
    """URL 携 token 旧形态的兼容开关（默认关）。中继与 agent 同读这份口径。"""
    import os

    return os.environ.get(URL_TOKEN_COMPAT_ENV, "").strip() == "1"


def signTunnelToken(secret: str, tokenType: str, issuedAt: Optional[float] = None,
                    nonce: Optional[str] = None) -> str:
    """定型签发准入令牌（U16 签发点）：HMAC 机制不变，payload 增 `type` 字段。

    信封 `nv1:{type}:{issuedAt}:{nonce}` + HMAC-SHA256(secret, 信封)。
    原始密钥只参与签名、不再上线——新形态下凭据全文不出进程（URL 兼容形态除外）。
    """
    if tokenType not in TUNNEL_TOKEN_TYPES:
        raise ValueError(f"未知令牌型 {tokenType!r}（须为 {'/'.join(TUNNEL_TOKEN_TYPES)}）")
    if not secret:
        raise ValueError("签发定型令牌必须提供密钥（空密钥等于任何人都能自签）")
    stamp = int(issuedAt if issuedAt is not None else time.time())
    nonce = nonce or secrets.token_hex(8)
    message = f"{TUNNEL_TOKEN_ENVELOPE}:{tokenType}:{stamp}:{nonce}"
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"),
                         hashlib.sha256).hexdigest()
    return f"{message}:{signature}"


def parseTunnelToken(token: str) -> Optional[Dict[str, Any]]:
    """解析定型令牌信封；非信封形态（含空值）回 `None`＝legacy，由验签方降级处置。"""
    if not isinstance(token, str) or not token.startswith(TUNNEL_TOKEN_ENVELOPE + ":"):
        return None
    parts = token.split(":")
    if len(parts) != 5:
        return None
    _, tokenType, issuedAt, nonce, signature = parts
    if tokenType not in TUNNEL_TOKEN_TYPES or not issuedAt.isdigit() or not nonce or not signature:
        return None
    return {"type": tokenType, "issuedAt": int(issuedAt),
            "nonce": nonce, "signature": signature}


def verifyTunnelToken(token: str, secret: str, allowedTypes: Sequence[str]) -> Dict[str, Any]:
    """通道校验型（U16）：验签 ＋ 校验令牌型是否允许进这条通道。

    回 `{"ok", "type", "legacy", "reason"}`：
    - 定型令牌：HMAC 验签后比对 `allowedTypes`，错型 `reason=token_type_rejected`；
    - legacy（无信封旧令牌）：按 **agent 型**降级——数据面放行、控制面按错型拒绝；
    - 签名不成立：`reason=auth_rejected`。调用方对 `ok=False` 必须给明确拒绝帧＋审计。
    """
    verdict = {"ok": False, "type": "", "legacy": False,
               "reason": TUNNEL_ERROR_AUTH_REJECTED}
    if not secret:
        return verdict
    parsed = parseTunnelToken(token)
    if parsed is None:
        verdict["legacy"] = True
        if isinstance(token, str) and token and hmac.compare_digest(token, secret):
            verdict["type"] = TOKEN_TYPE_AGENT
            if TOKEN_TYPE_AGENT in allowedTypes:
                verdict["ok"] = True
                verdict["reason"] = ""
            else:
                verdict["reason"] = TUNNEL_ERROR_TOKEN_TYPE_REJECTED
        return verdict
    message = ":".join([TUNNEL_TOKEN_ENVELOPE, parsed["type"],
                        str(parsed["issuedAt"]), parsed["nonce"]])
    expected = hmac.new(secret.encode("utf-8"), message.encode("utf-8"),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(parsed["signature"], expected):
        return verdict
    verdict["type"] = parsed["type"]
    if parsed["type"] not in allowedTypes:
        verdict["reason"] = TUNNEL_ERROR_TOKEN_TYPE_REJECTED
        return verdict
    verdict["ok"] = True
    verdict["reason"] = ""
    return verdict

# ---------------------------------------------------------------------------
# M3 · 设备连接会话（App 侧字面量；服务端也用它回话，故在此单源）
# ---------------------------------------------------------------------------

DEVICE_CONNECTION_STATES = (
    "idle", "reauthing", "connecting", "authed", "streaming",
    "reconnecting", "failed", "closed",
)

#: 会话失败的分型原因（面板/App 文案按这些取词，不各自意译）。
CONNECTION_FAILURE_REASONS = (
    "auth_credential_mismatch",   # 带的不是配对凭证
    "device_deregistered",        # 已解除——唯一需要重扫的路径
    "network_unreachable",
    "relay_not_registered",
    "tunnel_not_ready",
    "max_reconnect_exhausted",
)

# ---------------------------------------------------------------------------
# 形状生成（配对凭据只在这里造，端点不各自拼）
# ---------------------------------------------------------------------------


def generatePairingRef() -> str:
    """高熵一次性引用 `ref`。

    用 CSPRNG：这是确认后要把设备挂到别人账号名下的凭据，可预测即越权。
    """
    return "".join(secrets.choice(_REF_ALPHABET) for _ in range(PAIRING_REF_LENGTH))


def generateShortCode() -> str:
    """`SHORT_CODE_DIGITS` 位数字短码（手输路径用）。

    原 `_generate_pairing_code` 的 `random.randint` 形态已退役——梅森旋转可预测，
    而它是唯一的认证凭据（P3-18 的结论随迁到这里，不散成第二处）。
    """
    return "".join(str(secrets.randbelow(10)) for _ in range(SHORT_CODE_DIGITS))


def isPairingRefShape(value: str) -> bool:
    """形状校验（不当授权用：授权仍然只有「命中一条 pending 记录」这一条路）。"""
    return bool(value) and len(value) == PAIRING_REF_LENGTH and all(
        ch in _REF_ALPHABET for ch in value)


def isShortCodeShape(value: str) -> bool:
    return len(value) == SHORT_CODE_DIGITS and value.isdigit()


def pairingQrPayload(ref: str, host: str = "") -> str:
    """二维码文本：一次性 `ref` ＋ 服务器对外地址 `host`（扫码即完成服务器配置）。

    host 为空时退化为只带 `ref` 的旧形状（地址需另行录入）。2026-11-16 按用户裁定
    升级：原「刻意不含任何 host」（§3.4 地址漂移不废码）改为**一扫配全**——
    手机扫到 ref＋host 后自行建档并配对，地址漂移由用户改档案兜底。
    """
    if host:
        from urllib.parse import quote

        return f"neurova://pair?ref={ref}&host={quote(host, safe='')}"
    return f"neurova://pair?ref={ref}"
