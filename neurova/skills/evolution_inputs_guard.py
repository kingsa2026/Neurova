# -*- coding: utf-8 -*-
"""进化输入护栏。

进化闭环（反射式文本改进/失败分析/审批 UI）历史上把会话原文与技能 IO 摘要
直喂 LLM——密钥随文本外流的面。本模块在**写入侧**（record_usage）根治：
落库前脱敏 + 字符预算；所有下游消费方天然拿到干净文本。

- 键名=value/冒号形态：api[_-]?key|token|authorization|cookie|secret|password|credential
- Authorization: Bearer xxx
- OpenAI 风格 sk-[A-Za-z0-9_-]{16,}
宁误报不漏报（redaction 的目的不是判定，是止损）。
"""
from __future__ import annotations

import re
from typing import List

__all__ = ["redact_secrets", "contains_secret", "bound_text"]

_EVOLUTION_INPUT_BUDGET = 2000  # 单字段字符预算

_KV_RE = re.compile(
    r"(?i)(api[_\- ]?key|token|authorization|cookie|secret|password|credential|access[_\- ]?key)"
    r"(\s*[:=]\s*)([\"']?)([^\s\"',;]{6,})"
)
_BEARER_RE = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-]{10,})")
_OPENAI_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")


def redact_secrets(text: str) -> str:
    """密钥形态脱敏（保留键名，替换值）。非字符串输入原样返回。"""
    if not isinstance(text, str) or not text:
        return text
    # Bearer/sk 先行：否则 KV 档会把 "Bearer" 本体当值吃掉、真 token 反而漏网
    out = _BEARER_RE.sub(lambda m: f"{m.group(1)}[REDACTED]", text)
    out = _OPENAI_RE.sub("[REDACTED_KEY]", out)
    out = _KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}[REDACTED]", out)
    return out


def contains_secret(text: str) -> bool:
    """是否存在未脱敏的密钥形态（提交/上传门禁的 fail-closed 判据）。"""
    if not isinstance(text, str) or not text:
        return False
    if _KV_RE.search(text) or _OPENAI_RE.search(text) or _BEARER_RE.search(text):
        return True
    return False


def bound_text(text: str, max_chars: int = _EVOLUTION_INPUT_BUDGET) -> str:
    """字符预算截断（防超长 IO 摘要灌爆进化分析上下文）。"""
    if not isinstance(text, str):
        return text
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "…[truncated]"
