"""遥测脱敏（P2-13）。

原则：遥测是给外部观测面的——敏感值一律打码、超长截断、深嵌套截断。
- 敏感键（password/token/secret/api key/cookie/authorization/credential 等）
  的值替换为 ``[REDACTED]``，不区分大小写、容忍分隔符变体；
- 字符串超过 ``MAX_STR`` 截断并留 ``…(truncated)`` 尾标；
- 嵌套超过 ``MAX_DEPTH`` 的层级丢弃（不留占位，避免结构噪音）。
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
TRUNCATED_SUFFIX = "…(truncated)"
MAX_STR = 512
MAX_DEPTH = 8

_SENSITIVE = re.compile(
    r"(password|passwd|token|secret|api[-_]?key|apikey|cookie|authorization|credential|session[-_]?id)",
    re.IGNORECASE,
)


def _isSensitiveKey(key: str) -> bool:
    return bool(_SENSITIVE.search(str(key or "")))


def sanitizeValue(value: Any, maxStr: int = MAX_STR, maxDepth: int = MAX_DEPTH) -> Any:
    """递归脱敏：敏感键打码、超长截断、超深截断；标量原样返回。"""
    return _sanitize(value, maxStr, maxDepth, 0)


def _sanitize(value: Any, maxStr: int, maxDepth: int, depth: int) -> Any:
    if depth > maxDepth:
        return None
    if isinstance(value, dict):
        out: dict = {}
        for key, item in value.items():
            if _isSensitiveKey(key):
                out[str(key)] = REDACTED
            else:
                out[str(key)] = _sanitize(item, maxStr, maxDepth, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, maxStr, maxDepth, depth + 1) for item in value]
    if isinstance(value, str):
        if len(value) > maxStr:
            return value[:maxStr] + TRUNCATED_SUFFIX
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:maxStr]
