"""工具调用 trace：技能执行边界内的逐工具证据（名称/参数摘要/成败/错误/耗时/顺序）。

ContextVar 缓冲只活在一次技能执行内；执行结束后由 POST_EXECUTE 事件带走，
失败证据落盘、成功只留摘要。无 trace 上下文时记录是 no-op。
"""

from __future__ import annotations

import json
from contextvars import ContextVar, Token
from typing import Any, List, Optional, Tuple

_MAX_ENTRIES = 100
_MAX_PARAMS = 500

_current: ContextVar[Optional[List[dict]]] = ContextVar(
    "neurova_tool_trace", default=None
)


def beginToolTrace() -> Tuple[Token, List[dict]]:
    trace: List[dict] = []
    return _current.set(trace), trace


def endToolTrace(token: Token) -> None:
    try:
        _current.reset(token)
    except ValueError:
        pass


def currentToolTrace() -> List[dict]:
    trace = _current.get()
    return list(trace) if trace else []


def _summarizeParams(params: Any) -> str:
    try:
        text = json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = repr(params)
    if len(text) > _MAX_PARAMS:
        return text[: _MAX_PARAMS - 12] + "…[truncated]"
    return text


def _artifactRefs(tool: str, result: Any) -> List[dict]:
    if result is None:
        return []
    try:
        from neurova.api.endpoints.artifacts_api import artifact_refs_from_result

        if isinstance(result, str):
            text = result
        else:
            text = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        return artifact_refs_from_result(str(tool or ""), text)
    except Exception:  # noqa: BLE001 - 产物引用失败不影响 trace
        return []


def recordToolTrace(
    tool: str,
    params: Any = None,
    *,
    success: Optional[bool] = None,
    error: str = "",
    duration_ms: float = 0.0,
    layer: str = "",
    result: Any = None,
) -> None:
    trace = _current.get()
    if trace is None or len(trace) >= _MAX_ENTRIES:
        return
    entry = {
        "tool": str(tool or ""),
        "layer": str(layer or ""),
        "params": _summarizeParams(params),
        "success": None if success is None else bool(success),
        "error": str(error or "")[:300],
        "duration_ms": round(float(duration_ms), 2),
    }
    refs = _artifactRefs(tool, result)
    if refs:
        entry["artifacts"] = refs
    trace.append(entry)
