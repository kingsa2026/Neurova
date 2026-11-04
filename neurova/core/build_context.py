"""构建会话的请求级上下文。

Agent 的一轮请求如果是由 BuildSession 发起的，请求边界把 `build_session_id`
写进 ContextVar；画布写工具据此做服务端就绪门检查。手动编辑画布不设置该值，
保持现有行为。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_currentBuildSessionId: ContextVar[Optional[str]] = ContextVar(
    "neurova_build_session_id", default=None
)


def setCurrentBuildSessionId(sessionId: Optional[str]) -> None:
    _currentBuildSessionId.set(str(sessionId or "").strip() or None)


def getCurrentBuildSessionId() -> Optional[str]:
    return _currentBuildSessionId.get()


def resetCurrentBuildSessionId() -> None:
    _currentBuildSessionId.set(None)


__all__ = [
    "setCurrentBuildSessionId",
    "getCurrentBuildSessionId",
    "resetCurrentBuildSessionId",
]
