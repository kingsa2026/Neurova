"""
上下文系统 - 向后兼容层

此文件提供向后兼容性，所有实际实现已迁移到 neurova.context 包中。
建议使用新的导入路径：
    from neurova.context import ContextBuilder, UnifiedContextInjector, ...

保留此文件是为了确保现有代码继续工作。
"""

# 从新的包中导入所有内容
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

# 重新导出，保持向后兼容
__all__ = [
    "ContextPriority",
    "TokenBudget",
    "ContextEntry",
    "ContextBuildResult",
    "UnifiedContextInjector",
    "ContextBuilder",
    "ContextOrchestrator",
    "create_unified_context_injector",
]
