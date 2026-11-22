# -*- coding: utf-8 -*-
"""统一远程执行面（W1a/W1b）：端点注册表 + 分派漏斗。

- 注册表：六形态远程端点统一落 SQLite（自然键 upsert、租户隔离、健康度、
  连接信息只存引用名）——见 ``registry.py``。
- 分派漏斗：准入（形态白名单 + 能力复验）→ 形态执行体（调用方注入）→
  统一结果信封（U3 语义）→ 离线 hold（「未执行、可安全重试」）→
  生命周期事件——见 ``dispatch.py``。

深模块边界：本包不 import tool_executor/computer_use/guest_agent/tunnel/neuacp
（避免循环依赖）；形态执行体由调用方经 ``executor`` 参数注入。
"""
from neurova.remote_exec.dispatch import (
    DEFAULT_HOLD_TIMEOUT_MS,
    HOLD_TIMEOUT_ENV,
    RemoteDispatchError,
    RemoteDispatchResult,
    dispatchRemoteCall,
)
from neurova.remote_exec.registry import (
    KIND_GUEST,
    KIND_MCP,
    KIND_NEUACP,
    KIND_SSH,
    KIND_TUNNEL,
    REMOTE_EXEC_DB_DOMAIN,
    REMOTE_KINDS,
    RemoteEndpoint,
    RemoteEndpointRegistry,
    deriveEndpointId,
    getRemoteEndpointRegistry,
)

__all__ = [
    "DEFAULT_HOLD_TIMEOUT_MS",
    "HOLD_TIMEOUT_ENV",
    "KIND_GUEST",
    "KIND_MCP",
    "KIND_NEUACP",
    "KIND_SSH",
    "KIND_TUNNEL",
    "REMOTE_EXEC_DB_DOMAIN",
    "REMOTE_KINDS",
    "RemoteDispatchError",
    "RemoteDispatchResult",
    "RemoteEndpoint",
    "RemoteEndpointRegistry",
    "deriveEndpointId",
    "dispatchRemoteCall",
    "getRemoteEndpointRegistry",
]
