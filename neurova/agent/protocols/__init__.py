# -*- coding: utf-8 -*-
"""
Agent 协作能力模块

本模块提供 Agent 间协作所需的核心功能：
1. 通信协议 - 标准化的消息格式、优先级、死信队列
2. 协作模板 - 预设的 Agent 协作模式
3. 能力矩阵 - Agent 能力可视化和任务分配

使用方式:
    from neurova.agent.protocols import AgentMessage, MessagePriority
    from neurova.agent.templates import CollaborationTemplate, TemplateManager
    from neurova.agent.matrix import CapabilityMatrix, AgentCapability
"""

from .capability_discovery import AgentCapability, CapabilityDiscovery, CapabilityMatch
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
    # 能力发现
    "CapabilityDiscovery",
    "AgentCapability",
    "CapabilityMatch",
]
