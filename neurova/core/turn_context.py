"""轮次级请求状态 ContextVar（审计 P0-B1：Agent 单例并发互踩修复）

Agent 是进程级单例（AppState.agents 共享池），轮次级状态原挂在实例属性
（_current_user_id/_tool_messages_list 等）上——两个用户并发对同一 agent
发消息时，请求 B 的 set_request_identity 会覆盖请求 A 的身份，A 的回复
可能带上 B 的归属；工具展示消息也会跨请求串流。

本模块把轮次级状态迁到 ContextVar：
- 值绑定在请求任务/线程上下文，并发请求天然隔离
- asyncio.to_thread 会拷贝当前 context，同步降级路径同样隔离
- Agent 的轮次级显式 API（P3-c）读写这里；旧实例属性名经 __getattr__
  透传兼容（渐进收窄）

与 identity_context.py 的分工：那里只管 JWT user_id 的跨层注入；
这里管 Agent 全部轮次级展示/归属状态。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict, List, Optional

# 每个变量 default 取"未设置"安全值；Agent API 层负责兜底语义
_user_input_var: ContextVar = ContextVar("neurova_turn_user_input", default=None)
_session_id_var: ContextVar = ContextVar("neurova_turn_session_id", default=None)
_user_id_var: ContextVar = ContextVar("neurova_turn_user_id", default=None)
_reasoning_var: ContextVar = ContextVar("neurova_turn_reasoning", default=None)
_tool_messages_var: ContextVar = ContextVar("neurova_turn_tool_messages", default=None)
_tool_events_var: ContextVar = ContextVar("neurova_turn_tool_events", default=None)
_turn_count_var: ContextVar = ContextVar("neurova_turn_count", default=0)


def set_turn_identity(
    user_input: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """记录本轮请求级身份（user_id 缺省落 "default" 与原语义一致）。"""
    _user_input_var.set(user_input)
    _session_id_var.set(session_id)
    _user_id_var.set(user_id or "default")


def set_turn_user_input(value: Optional[str]) -> None:
    """单写轮次用户输入（A-04：Agent._current_user_input property 的
    setter 后端；传 None 即重置，兼容 init_conversation 的置空语义）。"""
    _user_input_var.set(value)


def get_turn_user_input() -> Optional[str]:
    return _user_input_var.get()


def get_turn_session_id() -> Optional[str]:
    return _session_id_var.get()


def get_turn_user_id() -> Optional[str]:
    return _user_id_var.get()


def set_turn_reasoning(reasoning: Optional[str]) -> None:
    _reasoning_var.set(reasoning)


def get_turn_reasoning() -> Optional[str]:
    return _reasoning_var.get()


def reset_turn_tool_messages() -> None:
    """清空本轮工具展示记录（轮次开始时调用；任务上下文内安全）。"""
    _tool_messages_var.set(None)


def append_turn_tool_messages(records: List[Dict[str, Any]]) -> None:
    """追加工具展示记录；损坏态自愈为列表（对齐原 append_tool_messages）。"""
    current = _tool_messages_var.get()
    if current is None:
        current = []
        _tool_messages_var.set(current)
    current.extend(records or [])


def get_turn_tool_messages_snapshot() -> List[Dict[str, Any]]:
    """工具展示记录快照（副本）。"""
    current = _tool_messages_var.get()
    return list(current) if current else []


def append_turn_tool_event(event: Dict[str, Any]) -> None:
    """追加工具降级/异常事件（openai_loop 降级路径）。"""
    current = _tool_events_var.get()
    if not isinstance(current, list):
        current = []
        _tool_events_var.set(current)
    current.append(event)


def get_turn_tool_events() -> List[Dict[str, Any]]:
    """工具事件列表（无则空列表）。"""
    current = _tool_events_var.get()
    return current if isinstance(current, list) else []


def increment_turn_count() -> int:
    """轮次计数 +1，返回新值（请求上下文内单调）。"""
    new_value = int(_turn_count_var.get() or 0) + 1
    _turn_count_var.set(new_value)
    return new_value


def get_turn_count() -> int:
    return int(_turn_count_var.get() or 0)


def clear_turn_state() -> None:
    """teardown/测试用：清空全部轮次级状态。"""
    for var in (
        _user_input_var,
        _session_id_var,
        _user_id_var,
        _reasoning_var,
        _tool_messages_var,
        _tool_events_var,
        _turn_count_var,
    ):
        var.set(None if var is not _turn_count_var else 0)


__all__ = [
    "set_turn_identity",
    "set_turn_user_input",
    "get_turn_user_input",
    "get_turn_session_id",
    "get_turn_user_id",
    "set_turn_reasoning",
    "get_turn_reasoning",
    "reset_turn_tool_messages",
    "append_turn_tool_messages",
    "get_turn_tool_messages_snapshot",
    "append_turn_tool_event",
    "get_turn_tool_events",
    "increment_turn_count",
    "get_turn_count",
    "clear_turn_state",
]
