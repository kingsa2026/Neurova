# -*- coding: utf-8 -*-
"""
Agent 协作模板模块

提供预设的 Agent 协作模式：
1. 代码评审（reviewer-agent → author-agent）
2. 结对编程（pair-programming）
3. 问题诊断（diagnostic → solver）
4. 知识共享（teacher → learner）

模板可视化配置和动态创建功能。
"""

from .collaboration_template import (
    AgentRole,
    CollaborationTemplate,
    TaskStep,
    TemplateManager,
    TemplateType,
    WorkflowDefinition,
    get_template_manager,
)
# P1-11 退役：personality_templates（PersonalityTemplate）唯一消费方是已退役的
# agent/builder.py（AgentBuilder），随同批删除；预设模板（preset_templates）仍被
# collaboration_template 在用，保留。
from .preset_templates import (
    CODE_REVIEW_TEMPLATE,
    DIAGNOSTIC_TEMPLATE,
    KNOWLEDGE_SHARING_TEMPLATE,
    PAIR_PROGRAMMING_TEMPLATE,
    PRESET_TEMPLATES,
)

__all__ = [
    # 模板核心
    "CollaborationTemplate",
    "TemplateType",
    "AgentRole",
    "TaskStep",
    "WorkflowDefinition",
    "TemplateManager",
    "get_template_manager",
    # 预设模板
    "PRESET_TEMPLATES",
    "CODE_REVIEW_TEMPLATE",
    "PAIR_PROGRAMMING_TEMPLATE",
    "DIAGNOSTIC_TEMPLATE",
    "KNOWLEDGE_SHARING_TEMPLATE",
]
