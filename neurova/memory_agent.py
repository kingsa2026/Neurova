"""
MemoryAgent — 向后兼容重导出

实际实现已迁移到 mem_core.py (MemCore)。
保留此文件以兼容旧的导入路径。

BUG 2 修复: 原文件仅有 docstring 无 import 语句,
`from neurova.memory_agent import MemoryAgent` 会 ImportError。
现添加显式重导出。
"""

from neurova.mem_core import MemCore as MemoryAgent

__all__ = ["MemoryAgent"]
