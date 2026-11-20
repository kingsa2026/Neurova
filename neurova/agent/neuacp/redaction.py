# -*- coding: utf-8 -*-
"""neuacp 帧脱敏：结构级字段名命中 + 值级复用单源规则（设计文档 §3.3，拍板 D-A）。

双层对位：
- **结构级**：递归走 dict/list，字段名（lower 后）命中 :data:`CREDENTIAL_FIELD_RE`
  或恰为 ``token``/``pat`` → 值整体替换 ``"[redacted]"``。usage 计数键
  （``*_tokens``/``tokens``）与引用名（``key_ref``）**显式不命中**——计数与
  引用不是明文凭据，误伤会让帧账本不可读。
- **值级**：其余字符串值复用 ``neurova.security.sensitive_info.sanitizeSensitive``
  （单源 ``SENSITIVE_RULES``，不另造第二套正则）。惰性 import，导入/执行失败
  退化为仅结构级并 ``logger.debug``（fail-open，不阻断帧落盘）。

单源覆盖核实（2026-11-20 读 ``neurova/security/sensitive_info.py``）：
``sk-``（secret_literal）、``ghp_``/``ghu_``（github_token/user_token）、
``Bearer …``（bearer_literal）、``xoxb-``/``xapp-``/``ntn_``/``AKIA``/PEM 头
均已在 ``SENSITIVE_RULES`` 内——**无需**在本模块补 neuacp 局部值级正则；
若单源后续删某条形状，这里跟随其升级即可（补充不替代，本批零新增规则）。
"""
from __future__ import annotations

import copy
import re
from typing import Any

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 脱敏出口词汇（与任务口径一致；区别于单源默认的 "***"）。
REDACTED_TOKEN = "[redacted]"

#: 结构级凭据字段名（``search`` 语义：字段名**含**这些子串即命中）。
#: ``token``/``pat`` 是**恰等**命中，不进本正则（否则 token_count 会被误伤）。
CREDENTIAL_FIELD_RE = re.compile(
    r"api[_-]?key|apikey|secret|password|passwd|authorization|credential|"
    r"private[_-]?key|personal[_-]?access[_-]?token|access[_-]?token|"
    r"refresh[_-]?token|auth[_-]?token",
    re.IGNORECASE,
)

#: 恰等命中的短字段名。
_EXACT_CREDENTIAL_FIELDS = frozenset({"token", "pat"})

#: usage 计数键：以 ``_tokens`` 结尾或恰为 ``tokens``（模型用量统计，非凭据）。
_USAGE_COUNT_SUFFIX = "_tokens"
_USAGE_COUNT_EXACT = frozenset({"tokens"})

#: 引用名（指向凭据的键名/路径，不是明文值）。
_REFERENCE_FIELDS = frozenset({"key_ref"})


def isCredentialField(name: Any) -> bool:
    """一个字段名是否为凭据字段（结构级判据；值整体打码，不做值形状判断）。"""
    if not isinstance(name, str):
        return False
    lower = name.strip().lower()
    if not lower:
        return False
    if lower.endswith(_USAGE_COUNT_SUFFIX) or lower in _USAGE_COUNT_EXACT:
        return False
    if lower in _REFERENCE_FIELDS:
        return False
    if CREDENTIAL_FIELD_RE.search(lower):
        return True
    return lower in _EXACT_CREDENTIAL_FIELDS


def _sanitizeText(text: str) -> str:
    """值级脱敏：复用记忆层单源 ``sanitizeSensitive``；失败退化为原文（仅结构级兜底）。"""
    try:
        from neurova.security.sensitive_info import sanitizeSensitive

        return sanitizeSensitive(text, token=REDACTED_TOKEN)
    except Exception as exc:  # noqa: BLE001 - 值级退化不阻断帧落盘（fail-open）
        logger.debug("值级脱敏不可用，退化为仅结构级: %s", exc)
        return text


def _redactValue(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict = {}
        for key, item in value.items():
            if isinstance(key, str) and isCredentialField(key):
                out[key] = REDACTED_TOKEN
            else:
                out[key] = _redactValue(item)
        return out
    if isinstance(value, list):
        return [_redactValue(item) for item in value]
    if isinstance(value, str):
        return _sanitizeText(value)
    return value


def redactFrame(frame: dict) -> dict:
    """深拷贝脱敏一帧：结构级字段名命中 → ``"[redacted]"``；其余字符串值走值级单源。

    原帧不被就地修改（写盘前脱敏前置，拍板 D-A：帧账本留正文）。
    """
    if not isinstance(frame, dict):
        return frame
    return _redactValue(copy.deepcopy(frame))
