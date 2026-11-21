# -*- coding: utf-8 -*-
"""neurova.contracts —— wire 契约派生单源包（E2 契约单源层）。

契约形状的**唯一读侧入口**。事实源仍在各代码声明位（builtin_tools 声明位、
SubAgentRun.to_dict、swarm 事件写入调用点），本包只做**派生投影**，
不定义、不复制任何契约形状（教义第 6 条：单一事实源，不新造平行体系）。

本包保持空壳：公开读侧经模块级 ``__getattr__`` 惰性转发到
``neurova.contracts.wire``——import 本包不触发任何事实源模块装载，
派生函数被调用时才 import 事实源（与仓内深模块惰性装配惯例一致）。
"""

__all__ = [
    "toolCatalogSnapshot",
    "toolCatalogEntries",
    "runProjectionKeys",
    "eventTypes",
    "continueSubagentModes",
]

_WIRE_EXPORTS = frozenset(__all__)


def __getattr__(name: str):
    """惰性转发：公开读侧名首次访问时才装载 wire 派生层。"""
    if name in _WIRE_EXPORTS:
        from neurova.contracts import wire

        return getattr(wire, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
