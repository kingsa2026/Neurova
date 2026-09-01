# -*- coding: utf-8 -*-
"""请求级 trace_id ContextVar（对齐 identity_context 模式）。

logger 只读本模块——禁止反向 import trace_recorder（循环依赖）。
trace_recorder 在 start_trace 成功后 set，end_trace 成功 pop 后 clear。
"""
from contextvars import ContextVar
from typing import Optional

_trace_id_var: ContextVar = ContextVar("neurova_trace_id", default=None)


def set_trace_id(trace_id: Optional[str]):
    """设置当前请求的 trace_id（trace_recorder.start_trace 调用）。"""
    return _trace_id_var.set(trace_id)


def get_trace_id() -> Optional[str]:
    """读取当前请求 trace_id（logger formatter 只读入口；无则 None）。"""
    return _trace_id_var.get()


def clear_trace_id() -> None:
    """teardown / end_trace 用。"""
    _trace_id_var.set(None)
