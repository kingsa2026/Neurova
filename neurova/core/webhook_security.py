"""
Webhook 入站安全（P1 Step 3）

HMAC-SHA256 签名计算与常量时间校验（GitHub X-Hub-Signature-256 风格）。
独立纯函数模块：无 I/O、无状态，便于单测与复用。
"""

import hashlib
import hmac

_SIGNATURE_PREFIX = "sha256="


def compute_signature(payload: bytes, secret: str) -> str:
    """计算 payload 的 HMAC-SHA256 签名，返回 "sha256=<hex>" 格式。"""
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return _SIGNATURE_PREFIX + digest


def verify_signature(payload: bytes, secret: str, header_value: str | None) -> bool:
    """校验入站请求的签名头。

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
