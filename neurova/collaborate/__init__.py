# -*- coding: utf-8 -*-
"""
协作系统模块

提供 Agent 协作模板、工作流定义和管理功能。
"""

from .models import TemplateType, AgentRole, TaskStep, WorkflowDefinition
from .template import CollaborationTemplate, TemplateManager, get_template_manager

__all__ = [
    # 数据模型
    "TemplateType",
    "AgentRole",
    "TaskStep",
    "WorkflowDefinition",

    # 模板管理
    "CollaborationTemplate",
    "TemplateManager",
    "get_template_manager",
]