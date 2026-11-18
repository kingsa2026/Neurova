# -*- coding: utf-8 -*-
"""recall_query 的受限表达式引擎（QwenPaw 对照批 B3）。

价值：recall_history 是模糊匹配、recall_context_span 是确定性下钻——
「对召回条目做组合/统计/过滤」（如"数一数上周提到过哪些文件"）没有
表达力出口。本模块用**白名单 AST 校验 + 只读数据注入**提供该表达力：

- 只允许**单个表达式**（无语句、无赋值、无 import）；
- Name 白名单（禁 exec/eval/open/getattr/import 等逃逸面）；
- 属性访问禁止下划线开头（堵 `__class__`/`__globals__` 逃逸链）；
- 数据只读注入：`items`（召回条目投影列表）；
- 结果截断，防超长输出撑爆上下文。

安全边界（诚实声明）：这不是完整沙箱——是**表达式级白名单解释器**。
数据源仅本会话召回条目（只读投影），即便被诱导构造恶意表达式，
可达面也限于对 items 的纯计算。
"""

from __future__ import annotations

import ast
import builtins as _builtins_mod
from typing import Any, Dict, List

#: 表达式环境可用的内建函数（白名单，宁少勿多）
ALLOWED_BUILTIN_NAMES = (
    "len", "sum", "min", "max", "sorted", "any", "all", "abs",
    "str", "int", "float", "bool", "list", "dict", "tuple", "set",
    "enumerate", "zip", "map", "filter", "reversed", "round",
)

#: 一律拒绝的名字（出现即拒，无论大小写变体由 Attribute 规则兜底）
FORBIDDEN_NAMES = frozenset({
    "import", "exec", "eval", "compile", "open", "getattr", "setattr",
    "delattr", "globals", "locals", "vars", "dir", "breakpoint",
    "__import__", "__builtins__",
})

#: 结果截断（字符）——防超长输出挤占上下文
MAX_RESULT_CHARS = 2000


class RecallExpressionError(ValueError):
    """表达式未通过白名单校验（语法/禁用名字/禁用属性）。"""


def validateRecallExpression(expression: str) -> ast.Expression:
    """解析并校验表达式；不合法抛 `RecallExpressionError`。"""
    if not expression or not expression.strip():
        raise RecallExpressionError("表达式为空")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        raise RecallExpressionError(f"表达式语法错误：{e}") from e

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise RecallExpressionError("禁止 import")
        if isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                raise RecallExpressionError(f"禁止使用 {node.id}")
            if node.id.startswith("__"):
                raise RecallExpressionError("禁止访问下划线开头名字")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise RecallExpressionError("禁止访问下划线开头属性")
    return tree


def runRecallExpression(expression: str, items: List[Dict[str, Any]]) -> str:
    """在白名单环境里对 `items` 求值表达式，返回截断后的字符串结果。"""
    tree = validateRecallExpression(expression)
    safe_builtins = {name: getattr(_builtins_mod, name) for name in ALLOWED_BUILTIN_NAMES}
    env = {"__builtins__": safe_builtins, "items": items}
    try:
        result = eval(compile(tree, "<recall_query>", "eval"), env)  # noqa: S307 - 白名单 AST 校验后
    except RecallExpressionError:
        raise
    except Exception as e:  # noqa: BLE001 - 求值错误如实回传给模型
        raise RecallExpressionError(f"表达式求值失败：{e}") from e
    text = result if isinstance(result, str) else repr(result)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f"…[截断，共 {len(text)} 字符]"
    return text
