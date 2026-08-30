"""
Webhook 入站安全（P1 Step 3；P0-7 增加时间戳重放防护）

HMAC-SHA256 签名计算与常量时间校验（GitHub X-Hub-Signature-256 风格）。
独立纯函数模块：无 I/O、无状态，便于单测与复用。

重放防护（P0-7/N3）：签名覆盖 "<timestamp>." 前缀 + payload，
配合 X-Neurova-Timestamp 头做时效校验——旧签名过期即失效。
"""

import hashlib
import hmac
import time
from typing import Optional, Tuple

_SIGNATURE_PREFIX = "sha256="
TIMESTAMP_HEADER = "X-Neurova-Timestamp"
_DEFAULT_MAX_AGE_S = 300.0


def compute_signature(payload: bytes, secret: str) -> str:
    """计算 payload 的 HMAC-SHA256 签名，返回 "sha256=<hex>" 格式。"""
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return _SIGNATURE_PREFIX + digest


def compute_signed_payload_signature(
    timestamp: str, payload: bytes, secret: str
) -> str:
    """计算带时间戳的签名：HMAC 覆盖 "<timestamp>." + payload。"""
    return compute_signature(f"{timestamp}.".encode("utf-8") + payload, secret)


def verify_signature(payload: bytes, secret: str, header_value: str | None) -> bool:
    """校验入站请求的签名头（不带时间戳的旧约定，保留兼容）。

    规则：
    - 使用 hmac.compare_digest 常量时间比较（防时序侧信道）
    - header 缺失 / 空串 / 前缀非 sha256= / secret 为空 → False（不抛异常）
    - hex 大小写不敏感
    """
    if not header_value or not secret:
        return False
    received = header_value.strip().lower()
    if not received.startswith(_SIGNATURE_PREFIX):
        return False
    expected = compute_signature(payload, secret)
    return hmac.compare_digest(expected.encode("utf-8"), received.encode("utf-8"))


def verify_request(
    payload: bytes,
    secret: str,
    signature_header: Optional[str],
    timestamp_header: Optional[str],
    *,
    now_s: Optional[float] = None,
    max_age_s: float = _DEFAULT_MAX_AGE_S,
) -> Tuple[bool, str]:
    """校验入站请求：签名 + 时间戳时效（P0-7/N3 重放防护）。

    签名约定：发送方对 "<timestamp>." + payload 计算 HMAC（见
    compute_signed_payload_signature），时间戳为 Unix 秒字符串。

    Returns:
        (ok, reason)：reason ∈ OK / MISSING_SIGNATURE / MISSING_TIMESTAMP /
        BAD_TIMESTAMP / SIGNATURE_STALE / INVALID_SIGNATURE
    """
    if not signature_header or not secret:
        return False, "MISSING_SIGNATURE"
    if not timestamp_header:
        return False, "MISSING_TIMESTAMP"

    try:
        ts = int(str(timestamp_header).strip())
    except (TypeError, ValueError):
        return False, "BAD_TIMESTAMP"

    now = now_s if now_s is not None else time.time()
    if abs(now - ts) > max_age_s:
        return False, "SIGNATURE_STALE"

    expected = compute_signed_payload_signature(str(ts), payload, secret)
    received = signature_header.strip().lower()
    if not received.startswith(_SIGNATURE_PREFIX):
        return False, "INVALID_SIGNATURE"
    if not hmac.compare_digest(expected.encode("utf-8"), received.encode("utf-8")):
        return False, "INVALID_SIGNATURE"
    return True, "OK"
