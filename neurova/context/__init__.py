"""
上下文系统 - Context System

统一的上下文构建、注入和管理系统。

模块结构:
- models: 数据模型 (ContextPriority, TokenBudget, ContextEntry, ContextBuildResult)
- injector: 统一上下文注入器 (UnifiedContextInjector)
- builder: 上下文构建器 (ContextBuilder)
- orchestrator: 上下文编排器 (ContextOrchestrator)

使用方式:
    from neurova.context import (
        ContextPriority,
        TokenBudget,
        ContextEntry,
        ContextBuildResult,
        UnifiedContextInjector,
        ContextBuilder,
        ContextOrchestrator,
        create_unified_context_injector,
    )
"""

from .builder import ContextBuilder
from .injector import UnifiedContextInjector, create_unified_context_injector
from .models import ContextBuildResult, ContextEntry, ContextPriority, TokenBudget
from .orchestrator import ContextOrchestrator

__all__ = [
    # 数据模型
    "ContextPriority",
    "TokenBudget",
    "ContextEntry",
    "ContextBuildResult",
    # 核心组件
    "UnifiedContextInjector",
    "ContextBuilder",
    "ContextOrchestrator",
    # 工厂函数
    "create_unified_context_injector",
]
