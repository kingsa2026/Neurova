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

import secrets

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

FRAME_REGISTER = "register"
FRAME_REGISTERED = "registered"
FRAME_OPEN = "open"
FRAME_DATA = "data"
FRAME_HEAD = "head"
FRAME_END = "end"
FRAME_PING = "ping"
FRAME_PONG = "pong"
FRAME_ERROR = "error"

#: 手机侧一次请求等 agent 把数据通道开出来的窗口。到点必须显式 503，
#: 不许静默重发或降级成 warning（教义第 2 条）。
TUNNEL_STREAM_OPEN_TIMEOUT_SECONDS = 5.0
#: HTTP 体在隧道里**缓冲**搬运的上限；WS 帧是流式过的，不受这条限制。
#: 边界写在这里，不假装隧道什么都能流。
TUNNEL_MAX_BUFFERED_BYTES = 4 * 1024 * 1024

TUNNEL_ERROR_CODES = (
    "tunnel_not_ready",       # 数据通道没在窗口内开出来
    "enrollment_rejected",    # 准入凭据缺失或不匹配
    "route_conflict",         # 别人的 routeId 想被覆盖
    "route_unknown",          # 入口按不认识的 routeId 敲门
    "payload_too_large",
)

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


def pairingQrPayload(ref: str) -> str:
    """二维码文本——**刻意不含任何 host**。

    「谁」与「在哪」分开是本案的头号原则：地址漂移不得让已发的码作废（§3.4）。
    """
    return f"neurova://pair?ref={ref}"
