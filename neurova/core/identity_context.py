"""请求级身份 ContextVar —— **全仓唯一那条"这一轮是谁"**（§6-163 裁定甲）

- set_request_user_id: 由**请求边界**设置（HTTP `/v1/chat`、`/v1/chat/stream`、
  `console` REST 与 `/ws`、`mobile_pairing`、`computer`、渠道路由、工具与 MCP 侧入口）
- get_request_user_id: 池化/配额/归属/凭据等消费方读取
- 模块级 ContextVar,值绑定在请求任务/线程上下文,并发安全,不污染单例

沿革：这里原先只服务浏览器身份注入，`core/turn_context.py` 另有一条
`neurova_turn_user_id` 同答"这一轮是谁"——两条通道各自派生就是 §6-121 的病灶，
而它们在渠道路径上确实装不同的人（属主 vs 发送者）。合并后的口径是：
**这条通道装发送者**，会话记录的可见性改由 `meta["session_owner_id"]` 显式传参
（取法单点在 `post_chat_pipeline`），不再靠环境捎带。

兜底不在这层：各消费方的缺省语义本就不同（属主＝空即共享、用量＝`anonymous`、
profile 池＝`default`、配额＝无身份即不判），在读写口里兜一层就是第二个事实源。

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