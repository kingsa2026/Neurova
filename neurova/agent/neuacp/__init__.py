# -*- coding: utf-8 -*-
"""neuacp：外部编码代理接入层（ACP v1 / 插件形态）。

命名说明：本包与仓内 ``neurova/agent/protocols/acp_runtime.py``（进程内
AgentMessage 总线）无关——neuacp 专指「外部编码代理经 Agent Client
Protocol / 插件协议编入 swarm 团队」的接入层。
"""
from neurova.agent.neuacp.acp_client import (
    NeuacpClient,
    NeuacpError,
    NeuacpProtocolError,
    NeuacpTimeoutError,
)
from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
from neurova.agent.neuacp.acp_member import NeuacpMemberAdapter
from neurova.agent.neuacp.executor import (
    NeuacpExecResult,
    NeuacpExecutor,
    NeuacpSessionContext,
)
from neurova.agent.neuacp.plugin_executor import NeuacpPluginExecutor

__all__ = [
    "NeuacpClient",
    "NeuacpError",
    "NeuacpProtocolError",
    "NeuacpTimeoutError",
    "NeuacpStdioExecutor",
    "NeuacpMemberAdapter",
    "NeuacpPluginExecutor",
    "NeuacpExecResult",
    "NeuacpExecutor",
    "NeuacpSessionContext",
]
