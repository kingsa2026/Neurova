# -*- coding: utf-8 -*-
"""模型错误分类单源。

retry / 健康检查 / 跨模型回退共用一套分类。回退资格：仅 rate_limited /
transient / model_not_found 允许切换下一模型——authentication（换模型同样
401）、bad_request（请求本身有问题）、context_overflow、content_safety
换模型无意义或不应静默换。

输入兼容 Exception 与字符串（multi_model_client 两种形态都有）。
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Optional, Union

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504, 529})

ModelErrorKind = str

_AUTHENTICATION_MARKERS = (
    "invalid api key",
    "invalid_api_key",
    "unauthorized",
    "authentication",
    "api key not valid",
    "incorrect api key",
)
_NOT_FOUND_MARKERS = (
    "model not found",
    "model_not_found",
    "does not exist",
    "not exist",
    "decommissioned",
)
_RATE_LIMIT_MARKERS = ("rate limit", "too many requests", "rate_limit")
_TIMEOUT_MARKERS = ("timeout", "timed out")
_CONNECTION_MARKERS = ("connection error", "connection refused", "connection reset",
                       "peer closed", "network error", "getaddrinfo", "ssl:")
_CONTEXT_MARKERS = ("context length", "context_length", "maximum context",
                    "too many tokens", "context window")
_SAFETY_MARKERS = ("content policy", "content_policy", "content safety",
                   "safety_filter", "moderation")


@dataclass(frozen=True)
class ModelErrorDecision:
    """稳定的模型错误策略结果。"""

    kind: ModelErrorKind
    status_code: Optional[int]
    retryable: bool
    fallback_eligible: bool


def _extract_status_code(error: Union[BaseException, str]) -> Optional[int]:
    status = getattr(error, "status", None) or getattr(error, "status_code", None)
    if status is None:
        resp = getattr(error, "response", None)
        status = getattr(resp, "status_code", None)
    if status is None:
        text = str(error)
        # "Error code: 429" / "HTTP 503" / "status 400" / "429 -" 形态
        m = re.search(r"(?:error code[:\s]*|http[:\s]*|status[:\s]*)(\d{3})", text.lower())
        if m:
            return int(m.group(1))
        m = re.search(r"\b(\d{3})\s*-\s", text)
        if m:
            return int(m.group(1))
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def _mentions_code(message: str, code: int) -> bool:
    """裸状态码词匹配（保持旧 _classify_error 的 "429" in text 覆盖面，
    词边界防 14293 之类误命中）。"""
    return re.search(rf"\b{code}\b", message) is not None


def classify_model_error(error: Union[BaseException, str]) -> ModelErrorDecision:
    """分类错误并判定可否重试 / 跨模型回退。"""
    status = _extract_status_code(error)
    message = str(error).lower()

    if (
        status in {401, 403}
        or _mentions_code(message, 401)
        or _mentions_code(message, 403)
        or any(m in message for m in _AUTHENTICATION_MARKERS)
    ):
        kind = "authentication"
    elif status == 404 or _mentions_code(message, 404) or any(m in message for m in _NOT_FOUND_MARKERS):
        kind = "model_not_found"
    elif status == 429 or _mentions_code(message, 429) or any(m in message for m in _RATE_LIMIT_MARKERS):
        kind = "rate_limited"
    elif (
        status in RETRYABLE_STATUS_CODES
        or isinstance(error, (ConnectionError, TimeoutError, asyncio.TimeoutError))
        or any(_mentions_code(message, c) for c in (500, 502, 503, 504, 529))
        or any(m in message for m in _TIMEOUT_MARKERS)
        or any(m in message for m in _CONNECTION_MARKERS)
    ):
        kind = "transient"
    elif any(m in message for m in _CONTEXT_MARKERS):
        kind = "context_overflow"
    elif any(m in message for m in _SAFETY_MARKERS):
        kind = "content_safety"
    elif status is not None and 400 <= status < 500:
        kind = "bad_request"
    else:
        kind = "unknown"

    retryable = kind in {"rate_limited", "transient"}
    fallback_eligible = retryable or kind == "model_not_found"
    return ModelErrorDecision(
        kind=kind,
        status_code=status,
        retryable=retryable,
        fallback_eligible=fallback_eligible,
    )


#: 配对非法的 provider 400 特征串（工具轮进视图的**唯一硬失败信号**，工单 §11.5）。
#: 网关措辞不一，故按"同时点出 tool_calls 与响应关系"判定，不匹配单个词。
_PAIRING_REJECT_MARKERS = (
    "must be followed by tool messages",
    "tool_call_id",
    "tool_calls",
)


def toolPairingRejectReason(error: Union[BaseException, str]) -> Optional[str]:
    """判定一个 provider 错误是否为**工具轮配对非法**导致的 400；是则返回点名串。

    为什么单独一个判定：灰度期"provider 400 必须归零"是本能力的唯一硬判据，
    而 400 的成因很多（未知字段、参数越界、内容策略……）。把全部 400 计进去，
    判据会被无关错误顶红；只判"400 且两处特征同时在场"，才叫咬合。
    非 400 一律返回 `None`（429/5xx 与配对无关）。
    """
    decision = classify_model_error(error)
    if decision.status_code != 400 and decision.kind != "bad_request":
        return None
    message = str(error).lower()
    hits = [m for m in _PAIRING_REJECT_MARKERS if m in message]
    if len(hits) < 2:
        return None
    return "ToolPairingReject"


def is_retryable_same_model(error: Union[BaseException, str]) -> bool:
    """同一模型是否值得重试。"""
    return classify_model_error(error).retryable


def is_fallback_eligible(error: Union[BaseException, str]) -> bool:
    """是否允许尝试下一个配置模型。"""
    return classify_model_error(error).fallback_eligible
