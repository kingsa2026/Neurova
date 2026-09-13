"""
安全表达式求值 —— 阻断 eval() 沙箱逃逸 (安全审计 H3)

背景:
    工作流/数据转换节点使用 ``eval(expr, {"__builtins__": {}}, safe_globals)``
    做表达式求值。仅清空 ``__builtins__`` 并不构成沙箱——攻击者可通过
    属性链遍历到任意对象并触达危险类，例如::

        (1).__class__.__mro__[1].__subclasses__()

    （实测可拿到 147 个子类，进而 os.system / subprocess 完成 RCE）。

设计:
    先做 AST 白名单校验，杜绝一切逃逸语法后再求值：
      - 属性访问只允许普通名（``input.upper()`` 放行），
        但拒绝任何下划线开头的属性（``__class__``/``__globals__``/
        ``__subclasses__``/``_module`` …）——这是沙箱逃逸的唯一主通道
      - 禁止 Lambda / 推导式 / 海象 / 星号展开 / f-string / import 等
      - 调用点仅允许白名单函数名（str/int/float/len/…）或对
        “非下划线属性”的方法调用（``s.upper()`` 放行，``x.__class__()`` 拒绝）
      - 名称禁止下划线开头（``__builtins__``/``__import__``）
      - 表达式长度上限，防 DoS

用法::

    from neurova.security.safe_expr import safe_eval

    safe_eval("len(input) + 1", {"input": [1, 2, 3]})   # -> 4
    safe_eval("input.upper()", {"input": "hi"})          # -> "HI"
    safe_eval("(1).__class__")                           # -> 抛 SafeExprError
"""

from __future__ import annotations

import ast
from typing import Any, Dict, Mapping, Optional

__all__ = ["SafeExprError", "safe_eval", "is_safe_expression", "MAX_EXPRESSION_LENGTH"]

# 表达式最大长度（防超长串 DoS）
MAX_EXPRESSION_LENGTH = 2000

# 允许被直接调用的内建函数白名单
_ALLOWED_CALLABLES = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "len": len,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "round": round,
    "sorted": sorted,
}

# AST 节点白名单：纯计算 + 普通属性/方法调用所需最小集合
_ALLOWED_NODES = (
    ast.Expression,
    ast.Constant,
    # 容器
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    # 运算
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    # 运算符
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Not,
    ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Is, ast.IsNot,
    # 下标 / 切片
    ast.Subscript,
    ast.Slice,
    # 属性 / 调用 / 名字
    ast.Attribute,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.keyword,
)
if hasattr(ast, "Index"):
    _ALLOWED_NODES = _ALLOWED_NODES + (ast.Index,)  # py<3.9 兼容


class SafeExprError(ValueError):
    """表达式被安全策略拒绝。"""


def _check_node(node: ast.AST) -> None:
    """递归校验 AST 中每个节点与属性/名称是否在白名单内。"""
    if not isinstance(node, _ALLOWED_NODES):
        raise SafeExprError(f"不允许的语法: {type(node).__name__}")

    # 属性访问：禁一切下划线开头的属性名（沙箱逃逸唯一通道）
    if isinstance(node, ast.Attribute):
        if node.attr.startswith("_"):
            raise SafeExprError(f"不允许的属性访问: {node.attr}")

    # 名称（变量/函数引用）不得以单/双下划线开头
    if isinstance(node, ast.Name):
        if node.id.startswith("_"):
            raise SafeExprError(f"不允许的名称: {node.id}")

    # 调用点：只允许白名单函数名，或“非下划线的属性方法”（s.upper()）
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            if func.id not in _ALLOWED_CALLABLES:
                raise SafeExprError(f"不允许的函数调用: {func.id}")
        elif isinstance(func, ast.Attribute):
            if func.attr.startswith("_"):
                raise SafeExprError(f"不允许的方法调用: {func.attr}")
        else:
            raise SafeExprError("不允许的调用形式")

    # 关键字参数名同样禁止下划线魔术名
    if isinstance(node, ast.keyword) and node.arg and node.arg.startswith("_"):
        raise SafeExprError(f"不允许的参数名: {node.arg}")

    for child in ast.iter_child_nodes(node):
        _check_node(child)


def _compile_checked(expression: str) -> Any:
    if not isinstance(expression, str):
        raise SafeExprError("表达式必须是字符串")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise SafeExprError("表达式过长")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise SafeExprError(f"表达式语法错误: {e}") from e
    _check_node(tree)
    return compile(tree, "<safe_expr>", "eval")


def is_safe_expression(expression: str) -> bool:
    """表达式是否通过安全策略（供测试/预检使用）。"""
    try:
        _compile_checked(expression)
        return True
    except SafeExprError:
        return False


def safe_eval(
    expression: str,
    variables: Optional[Mapping[str, Any]] = None,
    extra_callables: Optional[Mapping[str, Any]] = None,
) -> Any:
    """在受限沙箱中求值表达式。

    Args:
        expression: 表达式字符串。
        variables: 可引用的变量（对应原 eval 的 globals/local 映射）。
        extra_callables: 额外放行的调用（名称不得以 _ 开头）。

    Raises:
        SafeExprError: 表达式含不允许的语法/名称/调用。
    """
    code = _compile_checked(expression)

    scope: Dict[str, Any] = dict(_ALLOWED_CALLABLES)
    if extra_callables:
        for name, value in extra_callables.items():
            if name.startswith("_"):
                raise SafeExprError(f"不允许的名称: {name}")
            scope[name] = value
    if variables:
        for name, value in variables.items():
            if isinstance(name, str) and name.startswith("_"):
                raise SafeExprError(f"不允许的名称: {name}")
            scope[name] = value

    # __builtins__ 仍清空作为纵深防御（AST 已封死逃逸路径）
    return eval(code, {"__builtins__": {}}, scope)  # noqa: S307 - AST 白名单前置校验
