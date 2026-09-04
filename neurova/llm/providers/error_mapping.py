"""Provider 错误归一（P0 补课 — Dify `_invoke_error_mapping` 对标）。

五类标准错误（docs/Neurova_Dify代码级对比_2026-09-03.md §2.5）：
connection_failed / service_unavailable / rate_limited / auth_failed /
bad_request，每类带 retryable 与 user_hint（前端可行动提示）。

归一优先级（normalize_provider_error）：
1. 已是 ProviderError → 原样返回（幂等）
2. neurova LLM 异常族（llm_client 的 4 类 LLMError 子类）
3. openai SDK 异常族（可选依赖，try/except 包裹）
4. HTTP 状态码（status_code 属性：aiohttp/httpx/litellm 自定义异常）
5. 消息关键词兜底（网关自定义异常只有 str 可依）
6. bad_request 兜底（不丢原始信息）

与 MultiModelLLMClient._RETRYABLE 的关系：重试集合消费
ErrorCategory.retryable 的异常类（connection/unavailable/rate_limit），
auth/bad_request 不可重试——单一事实源，避免双处维护漂移。
"""

from __future__ import annotations

import enum
import re
import typing

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class ErrorCategory(enum.Enum):
    """五类标准错误（值对齐 Dify `_invoke_error_mapping` 语义）"""

    CONNECTION = "connection_failed"
    UNAVAILABLE = "service_unavailable"
    RATE_LIMIT = "rate_limited"
    AUTH = "auth_failed"
    BAD_REQUEST = "bad_request"

    @property
    def retryable(self) -> bool:
        """连接/不可用/限频可重试；鉴权/坏请求不可重试（换 key / 改参数才有意义）"""
        return self in (ErrorCategory.CONNECTION, ErrorCategory.UNAVAILABLE, ErrorCategory.RATE_LIMIT)

    @property
    def user_hint(self) -> str:
        """用户可行动提示（中文，前端直接展示；不回显敏感材料）"""
        return {
            ErrorCategory.CONNECTION: "无法连接到模型服务商，请检查网络或服务地址（base_url）后重试",
            ErrorCategory.UNAVAILABLE: "模型服务暂不可用（服务端错误），请稍后重试",
            ErrorCategory.RATE_LIMIT: "请求频率过高或配额用尽，请稍后重试或检查套餐配额",
            ErrorCategory.AUTH: "认证失败，请检查 API Key 是否正确或有对应模型权限",
            ErrorCategory.BAD_REQUEST: "请求被拒绝，请检查模型名称与参数是否有效",
        }[self]


class ProviderError(Exception):
    """归一后的标准 Provider 错误

    Attributes:
        category: 五类之一
        message: 原始错误信息（日志用，可能含技术细节）
        user_hint: 用户可行动提示（脱敏，前端展示用）
        cause: 原始异常（保留完整堆栈语义）
    """

    def __init__(self, category: ErrorCategory, message: str = "", cause: typing.Optional[BaseException] = None):
        self.category = category
        self.message = message or category.value
        self.user_hint = category.user_hint
        self.cause = cause
        super().__init__(f"[{category.value}] {self.message}")

    @property
    def retryable(self) -> bool:
        return self.category.retryable


# ── openai SDK 异常族（可选依赖；未安装时映射退化为消息模式） ──

try:  # noqa: SIM105 — 映射表需要真实类对象，try/except 是唯一形态
    import openai as _openai_sdk

    _OPENAI_CONN = getattr(_openai_sdk, "APIConnectionError", None)
    _OPENAI_RATE = getattr(_openai_sdk, "RateLimitError", None)
    _OPENAI_AUTH = getattr(_openai_sdk, "AuthenticationError", None)
    _OPENAI_API = getattr(_openai_sdk, "APIError", None)
    _OPENAI_NOT_FOUND = getattr(_openai_sdk, "NotFoundError", None)
    _OPENAI_BAD = getattr(_openai_sdk, "BadRequestError", None)
    _OPENAI_UNAVAILABLE = getattr(_openai_sdk, "InternalServerError", None)
except ImportError:
    _OPENAI_CONN = _OPENAI_RATE = _OPENAI_AUTH = None
    _OPENAI_API = _OPENAI_NOT_FOUND = _OPENAI_BAD = _OPENAI_UNAVAILABLE = None


def _build_exception_map() -> list:
    """异常类型 → 分类映射表（顺序敏感：子类在前）"""
    from neurova.llm_client import (
        LLMAuthError,
        LLMBadRequestError,
        LLMConnectionError,
        LLMRateLimitError,
        LLMServiceUnavailableError,
    )

    pairs: list = [
        (LLMRateLimitError, ErrorCategory.RATE_LIMIT),
        (LLMAuthError, ErrorCategory.AUTH),
        (LLMBadRequestError, ErrorCategory.BAD_REQUEST),
        (LLMConnectionError, ErrorCategory.CONNECTION),
        (LLMServiceUnavailableError, ErrorCategory.UNAVAILABLE),
    ]
    sdk = [
        (_OPENAI_RATE, ErrorCategory.RATE_LIMIT),
        (_OPENAI_AUTH, ErrorCategory.AUTH),
        (_OPENAI_NOT_FOUND, ErrorCategory.BAD_REQUEST),
        (_OPENAI_BAD, ErrorCategory.BAD_REQUEST),
        (_OPENAI_UNAVAILABLE, ErrorCategory.UNAVAILABLE),
        (_OPENAI_CONN, ErrorCategory.CONNECTION),
        (_OPENAI_API, None),  # APIError 基类：按 status_code 二次归一
    ]
    for cls, cat in sdk:
        if cls is not None:
            pairs.append((cls, cat))
    pairs.extend([
        (ConnectionError, ErrorCategory.CONNECTION),
        (TimeoutError, ErrorCategory.CONNECTION),
        (OSError, ErrorCategory.CONNECTION),
    ])
    return pairs


_EXCEPTION_MAP: list = _build_exception_map()

# 消息关键词兜底（网关/litellm 自定义异常仅 str 可依；小写匹配）
_MESSAGE_PATTERNS: list = [
    (re.compile(r"\b(40[13]\b|unauthorized|forbidden|invalid.{0,12}api.?key|authentication)", re.I), ErrorCategory.AUTH),
    (re.compile(r"\b(429\b|rate.?limit|too many requests|quota)", re.I), ErrorCategory.RATE_LIMIT),
    (re.compile(r"\b(5\d\d\b|service.?unavailable|bad.?gateway|gateway.?timeout|overloaded|internal server)", re.I), ErrorCategory.UNAVAILABLE),
    (re.compile(r"\b(connection|timeout|timed?.?out|network|unreachable|refused|reset)", re.I), ErrorCategory.CONNECTION),
    (re.compile(r"\b(40[024]\b|bad.?request|not.?found|invalid.?model|invalid.?request|unsupported)", re.I), ErrorCategory.BAD_REQUEST),
]

# 鉴权类消息中的 key 片段脱敏（sk- 前缀等典型形态）
_KEY_PATTERN = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|nvk_[A-Za-z0-9_-]{8,}|Bearer\s+\S+)")


def _classify_by_status(status_code: typing.Optional[int]) -> typing.Optional[ErrorCategory]:
    if not isinstance(status_code, int):
        return None
    if status_code in (401, 403):
        return ErrorCategory.AUTH
    if status_code == 429:
        return ErrorCategory.RATE_LIMIT
    if 500 <= status_code <= 599:
        return ErrorCategory.UNAVAILABLE
    if 400 <= status_code <= 499:
        return ErrorCategory.BAD_REQUEST
    return None


def _classify_by_message(message: str) -> typing.Optional[ErrorCategory]:
    for pattern, cat in _MESSAGE_PATTERNS:
        if pattern.search(message):
            return cat
    return None


def _mask_secrets(text: str) -> str:
    return _KEY_PATTERN.sub("[REDACTED]", text or "")


def normalize_provider_error(exc: BaseException) -> ProviderError:
    """把任意 provider 异常归一为五类 ProviderError。

    归一优先级见模块 docstring；未识别异常兜底 bad_request（原始信息
    完整保留在 message，user_hint 恒脱敏可展示）。
    """
    if isinstance(exc, ProviderError):
        return exc

    message = str(exc) or exc.__class__.__name__

    # 1. 类型映射（含 neurova LLM 异常族与 openai SDK 族）
    for cls, cat in _EXCEPTION_MAP:
        if isinstance(exc, cls):
            if cat is not None:
                return ProviderError(cat, _mask_secrets(message), cause=exc)
            # APIError 基类：用 response.status_code 二次归一
            status = getattr(getattr(exc, "response", None), "status_code", None)
            cat = _classify_by_status(status) or _classify_by_message(message) or ErrorCategory.BAD_REQUEST
            return ProviderError(cat, _mask_secrets(message), cause=exc)

    # 2. HTTP 状态码（aiohttp/httpx/litellm 风格的自定义异常）
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    cat = _classify_by_status(status if isinstance(status, int) else None)
    if cat is not None:
        return ProviderError(cat, _mask_secrets(message), cause=exc)

    # 3. 消息关键词兜底
    cat = _classify_by_message(message)
    if cat is not None:
        return ProviderError(cat, _mask_secrets(message), cause=exc)

    # 4. 兜底：坏请求（不丢原信息）
    return ProviderError(ErrorCategory.BAD_REQUEST, message, cause=exc)


def exception_classes_for(categories: typing.Iterable[ErrorCategory]) -> tuple:
    """按分类集返回可重试异常类集合（重试装配用）。

    返回 (ProviderError,) 的子集过滤交给调用方按 category 判断——
    ProviderError 是统一载体，按类重试需要展开映射表。
    """
    classes: list = []
    for cls, cat in _EXCEPTION_MAP:
        if cat in categories and cls not in classes:
            classes.append(cls)
    classes.append(ProviderError)
    return tuple(classes)
