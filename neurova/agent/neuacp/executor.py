# -*- coding: utf-8 -*-
"""外部执行体统一协议：ACP（NeuacpStdioExecutor）与插件（NeuacpPluginExecutor）
共同实现同一接口，供 NeuacpMemberAdapter 驱动。"""
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, runtime_checkable


@dataclass
class NeuacpSessionContext:
    """一次 swarm member 执行对应的会话上下文。"""

    member_session_id: str
    task_text: str
    cwd: str = ""
    env_keys: tuple = ()
    permission_mode: str = "chain"
    metadata: dict = field(default_factory=dict)


@dataclass
class NeuacpExecResult:
    """一轮 prompt 的执行结果。"""

    text: str = ""
    stop_reason: str = "end_of_turn"
    raw: Optional[dict] = None


# emitter(event_type, chunk)：event_type ∈ {"content", "reasoning"}
Emitter = Callable[[str, Any], None]
# on_permission(action, reason, context) -> dict（审批链应答）
PermissionAsker = Callable[[str, str, str], dict]


@runtime_checkable
class NeuacpExecutor(Protocol):
    """外部执行体最小协议（设计文档 §4.10）。"""

    async def start(self, ctx: NeuacpSessionContext) -> None:
        ...

    async def prompt(self, task_text: str, emitter: Emitter, on_permission: PermissionAsker) -> NeuacpExecResult:
        ...

    async def cancel(self) -> None:
        ...

    async def close(self) -> None:
        ...
