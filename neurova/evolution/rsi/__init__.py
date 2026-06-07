"""
递归自我进化（RSI）模块

实现递归自我改进的核心机制，包括：
- 递归棘轮剪枝器
- 工具层RSI
- 棘轮验证器
- 语义锚点
- 不可变安全层
"""

from .recursive_ratchet_pruner import RecursiveRatchetPruner, EnhancedRatchetPruner, Candidate

__all__ = [
    "RecursiveRatchetPruner",
    "EnhancedRatchetPruner",
    "Candidate",
]
