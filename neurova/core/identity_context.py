"""请求级身份 ContextVar(对齐 MemoryManager._scope_var 模式)

- set_request_user_id: 入口处设置当前请求 userId
- get_request_user_id: CamofoxServerBackend / Supervisor 读取
- 模块级 ContextVar,值绑定在请求任务/线程上下文,并发安全,不污染单例

为什么不复用 MemoryManager._scope_var:
- MemoryManager 那个是私有的(模块级 _scope_var),不导出
- 隔离关注点分离:browser/identity 是新维度
- 后续 tool_executor 其它工具(MCP / social_search)也可读
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_user_id_var: ContextVar = ContextVar("neurova_request_user_id", default=None)


def set_request_user_id(user_id: Optional[str]) -> None:
    """设置当前请求的 userId(从 JWT 提取的 sub / neuser_id)"""
    _user_id_var.set(user_id)


def get_request_user_id() -> Optional[str]:
    """读取当前请求 userId(无则返回 None,调用方需自行兜底 default)"""
    return _user_id_var.get()


def clear_request_user_id() -> None:
    """测试/teardown 用"""
    _user_id_var.set(None)