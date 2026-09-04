"""HITL surface 安全模型（P1-2 — Dify `HumanInputSurface` 对标）。

Dify 语义（docs/Neurova_Dify代码级对比_2026-09-03.md §2.3）：按调用面
裁剪接收方——SERVICE_API/OPENAPI 只能接收 STANDALONE_WEB_APP 类 web
表单请求，CONSOLE 只接收 CONSOLE/BACKSTAGE。这是对 API 安全模型的
显式声明：防"API 请求伪装成控制台审批"。

接入方式（增量约束——扩展点显式、缺省关）：
- ApprovalRequest.metadata 携带 surface/request_origin（向后兼容：
  缺省不写、不裁剪，存量审批流行为不变）
- 裁决发生在「审批面决定谁能看到/处理该请求」的消费点（前端通知、
  approvals 端点过滤），本模块只提供枚举与纯函数裁决。
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Tuple, Union

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class HumanInputSurface(str, Enum):
    """审批/人工输入的调用面（Dify HumanInputSurface 对齐）"""

    SERVICE_API = "service_api"
    CONSOLE = "console"
    OPENAPI = "openapi"


class RequestOrigin(str, Enum):
    """审批请求的来源（Dify 接收方语义：web 表单 / 控制台 / 后台任务）"""

    STANDALONE_WEB_APP = "standalone_web_app"
    CONSOLE = "console"
    BACKSTAGE = "backstage"


# 接收方裁剪表：surface → 可接收的 origin 集合（Dify 表对齐）
_ALLOWED_RECIPIENTS: dict = {
    HumanInputSurface.SERVICE_API: frozenset({RequestOrigin.STANDALONE_WEB_APP}),
    HumanInputSurface.OPENAPI: frozenset({RequestOrigin.STANDALONE_WEB_APP}),
    HumanInputSurface.CONSOLE: frozenset({RequestOrigin.CONSOLE, RequestOrigin.BACKSTAGE}),
}


def _coerce_surface(value: Union[str, HumanInputSurface]) -> HumanInputSurface:
    if isinstance(value, HumanInputSurface):
        return value
    try:
        return HumanInputSurface(str(value or "").strip().lower())
    except ValueError:
        raise ValueError(
            f"未知调用面: {value!r}（有效: {[s.value for s in HumanInputSurface]}）"
        )


def _coerce_origin(value: Union[str, RequestOrigin]) -> RequestOrigin:
    if isinstance(value, RequestOrigin):
        return value
    try:
        return RequestOrigin(str(value or "").strip().lower())
    except ValueError:
        raise ValueError(
            f"未知请求来源: {value!r}（有效: {[o.value for o in RequestOrigin]}）"
        )


def resolve_recipient(
    surface: Union[str, HumanInputSurface],
    request_origin: Union[str, RequestOrigin],
) -> Tuple[bool, str]:
    """裁决：调用面 surface 是否可接收来源为 request_origin 的审批请求。

    Returns:
        (allowed, reason)：拒绝时 reason 给出审计依据
    """
    s = _coerce_surface(surface)
    o = _coerce_origin(request_origin)
    allowed = o in _ALLOWED_RECIPIENTS[s]
    if allowed:
        return True, ""
    return False, (
        f"调用面 {s.value} 不接收来源 {o.value} 的审批请求"
        f"（允许: {sorted(x.value for x in _ALLOWED_RECIPIENTS[s])}）"
    )


def filter_requests_for_surface(requests: list, surface: Union[str, HumanInputSurface]) -> list:
    """按调用面过滤审批请求列表（消费点用：approvals 端点/通知面）。

    无 surface 声明的请求（存量）视为仅 CONSOLE 可见——历史请求的
    保守默认（它们全部由旧链路在控制台面创建）。
    """
    s = _coerce_surface(surface)
    out = []
    for r in requests or []:
        meta = getattr(r, "metadata", None) or {}
        origin_raw = meta.get("request_origin")
        if origin_raw is None:
            if s is HumanInputSurface.CONSOLE:
                out.append(r)
            continue
        allowed, _ = resolve_recipient(s, str(origin_raw))
        if allowed:
            out.append(r)
    return out


__all__ = [
    "HumanInputSurface",
    "RequestOrigin",
    "resolve_recipient",
    "filter_requests_for_surface",
]
