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
    CollaborationTemplate,
    TemplateType,
    AgentRole,
    TaskStep,
    WorkflowDefinition,
    TemplateManager,
    get_template_manager,
)
from .preset_templates import (
    PRESET_TEMPLATES,
    CODE_REVIEW_TEMPLATE,
    PAIR_PROGRAMMING_TEMPLATE,
    DIAGNOSTIC_TEMPLATE,
    KNOWLEDGE_SHARING_TEMPLATE,
)
from .personality_templates import PersonalityTemplate

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
    # 人格模板
    "PersonalityTemplate",
]
