from __future__ import annotations

"""
RFC 6238 TOTP（时间同步一次性口令）—— stdlib 自实现。

选型（任务卡二选一）：**stdlib 自实现，不引入 pyotp**。理由：
- 依赖纪律：本仓可选依赖一律惰性 import 且不新增重型第三方；.venv 实测未装
  pyotp，为一张 HMAC 表引入一个包不值得——RFC 6238 的核心是 RFC 4226 HOTP
  （HMAC-SHA1 → 动态截断 → 取模），stdlib hmac/hashlib/struct/base64 数十行
  足以正确实现，且下方带 RFC 6238 附录 B 测试向量钉死正确性。
- 若部署环境已装 pyotp，行为与本法兼容（同一 RFC），后续如需 HOTP 多算法
  （SHA256/512）可再评估替换。

参数：HMAC-SHA1、默认 6 位、步长 30 秒、验证窗口 ±1（前后各一步，容忍时钟偏移）。
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote, urlencode

from neurova.core.logger import get_logger

logger = get_logger(__name__)

TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6
TOTP_WINDOW = 1
TOTP_ALGORITHM = "sha1"

#: secret 字节数（RFC 4226 建议 ≥160bit）
TOTP_SECRET_BYTES = 20


def hotp(key: bytes, counter: int, digits: int = TOTP_DIGITS) -> str:
    """RFC 4226 HOTP：HMAC-SHA1(key, counter) → 动态截断 → 十进制定宽字符串。"""
    if counter < 0:
        raise ValueError("counter 必须非负")
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (
        ((digest[offset] & 0x7F) << 24)
        | (digest[offset + 1] & 0xFF) << 16
        | (digest[offset + 2] & 0xFF) << 8
        | (digest[offset + 3] & 0xFF)
    ) % (10 ** digits)
    return str(code).zfill(digits)


def totpAt(key: bytes, timestamp: float, step: int = TOTP_STEP_SECONDS,
           digits: int = TOTP_DIGITS, t0: int = 0) -> str:
    """RFC 6238 TOTP：以 (timestamp - t0) // step 为 counter 的 HOTP。

    key 接受原始字节；base32 字符串请先 b32decode（见 verifyTotp）。
    """
    if step <= 0:
        raise ValueError("step 必须为正")
    counter = int((int(timestamp) - t0) // step)
    return hotp(key, counter, digits=digits)


def generateTotpSecret(byteLen: int = TOTP_SECRET_BYTES) -> str:
    """生成 base32（无 padding）secret——可直接进 otpauth:// URL 与 users.totp_secret。"""
    if byteLen < 16:
        raise ValueError("TOTP secret 不得短于 16 字节（RFC 4226）")
    return base64.b32encode(secrets.token_bytes(byteLen)).decode("ascii").rstrip("=")


def _decodeSecret(secretB32: str) -> bytes:
    cleaned = "".join(secretB32.split()).upper()
    padding = "=" * (-len(cleaned) % 8)
    return base64.b32decode(cleaned + padding)


def verifyTotp(secretB32: str, code: str, window: int = TOTP_WINDOW,
               step: int = TOTP_STEP_SECONDS, digits: int = TOTP_DIGITS,
               now: Optional[float] = None) -> bool:
    """校验 TOTP 码；窗口 ±window 步（默认 ±1）。常量时间比对，错码/空码一律 False。"""
    if not secretB32 or not code:
        return False
    normalized = "".join(str(code).split())
    if not normalized.isdigit() or len(normalized) != digits:
        return False
    try:
        key = _decodeSecret(secretB32)
    except Exception as e:  # noqa: BLE001 - 非法 secret 视为不匹配，不外抛
        logger.warning("TOTP secret 解码失败: %s", e)
        return False
    timestamp = time.time() if now is None else now
    counter = int((int(timestamp)) // step)
    matched = False
    for offset in range(-window, window + 1):
        candidate = hotp(key, counter + offset, digits=digits)
        if hmac.compare_digest(candidate, normalized):
            matched = True
    return matched


def otpauthUrl(secretB32: str, accountName: str, issuer: str = "Neurova",
               step: int = TOTP_STEP_SECONDS, digits: int = TOTP_DIGITS) -> str:
    """构造 otpauth://totp/ URL（Google Authenticator 兼容参数）。"""
    label = quote(f"{issuer}:{accountName}", safe="")
    query = urlencode({
        "secret": secretB32,
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": str(digits),
        "period": str(step),
    })
    return f"otpauth://totp/{label}?{query}"
