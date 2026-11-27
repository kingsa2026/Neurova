# -*- coding: utf-8 -*-
"""neurova.tool_executor —— 公共 façade。

实现已下沉到 neurova.tool_layers.tool_executor_impl；
保持 `neurova.tool_executor.ToolExecutor`、`_builtin_dispatch`、`_execute_*`、
`_result_is_success`、`_agent_identity`、`on_tool_executed`、
`_execute_single_tool*`、`_execute_tool_core`、`_execute_builtin_tool`
与 `neurova.tool_executor.X` 旧导入路径不变。

neurova.agent.__init__ 从本模块 re-export ToolExecutor；
neurova.tool_layers.* 不在顶层 import 本模块。
"""
from neurova.tool_layers import tool_executor_impl as _impl
from neurova.tool_layers.tool_executor_impl import *  # noqa: F401,F403

ToolExecutor = _impl.ToolExecutor


def __getattr__(name):
    return getattr(_impl, name)
