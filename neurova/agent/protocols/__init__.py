# -*- coding: utf-8 -*-
"""Agent 通信协议门面：现役面只有消息协议与死信队列。

本门面**不再把能力发现那座岛声明成公共面**（与 §6-312 的 D19 同根因）。过去它在模块级
无条件 `from .capability_discovery import ...`，而 Python 导入子包必先执行父包 `__init__`——
`agent/team.py` 与 `api/endpoints/acp_api.py` 只是取 `AgentMessage`／`ACPRuntime`，却连带执行
那 449 行死码的模块体：既是每次启动的真实成本，也向下一个人暗示"能力发现在这里有现役实现"。

那座岛**不是引入即未接线，而是曾被接进活链路后被摘**——`collaboration_api.py` 曾有
`POST /capabilities/register`（注册表唯一的生产者）与 `/capabilities`、`/recommend`、`/matrix` 等
读面，被同仓一次"pyc 骨架恢复"的整文件重写连同端点一并摘除。按死码溯源的口径它只能"恢复接线"
或"显式承认放弃该能力"，二者都是产品裁定，所以**本批只收门面，本体一律不动**（归台账 B3 那张
需人裁票，且它与 `agent/matrix/` 必须同批裁：matrix 是它的唯一消费者）。

现役实现归属（退役时逐条验过实质，不是"存在即替代"）：
- 消息格式／优先级／死信 ＝ 本包 `message_protocol.py`、`dead_letter_queue.py`（`acp_runtime.py` 在用）。
- Agent 间投递与处理器注册 ＝ 本包 `acp_runtime.py`（`api/endpoints/acp_api.py` 在用）。
- 协作模板／角色／步骤 schema ＝ `neurova/agent/templates/collaboration_template.py`（`agent/team.py` 在用）。

使用方式:
    from neurova.agent.protocols import AgentMessage, MessagePriority
    from neurova.agent.templates import CollaborationTemplate, TemplateManager
"""
from .dead_letter_queue import DeadLetterQueue, DLQConfig
from .message_protocol import (
    AgentMessage,
    DeadLetterMessage,
    DeadLetterReason,
    MessagePriority,
    MessageType,
    ProtocolVersion,
)

__all__ = [
    # 消息协议
    "AgentMessage",
    "MessagePriority",
    "MessageType",
    "ProtocolVersion",
    "DeadLetterMessage",
    "DeadLetterReason",
    # 死信队列
    "DeadLetterQueue",
    "DLQConfig",
]
