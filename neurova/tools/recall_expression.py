# -*- coding: utf-8 -*-
"""recall_query 的受限表达式解释器。

模型表达式只接收本会话召回条目的只读投影。解释器不调用 `eval`，也不暴露任意
Python 对象：名字、调用、属性、容器分配、迭代、整数与字符串都由同一组预算约束。
"""

from __future__ import annotations

import ast
import operator
import re
import time
from collections.abc import Sized
from typing import Any, Dict, List, Optional

from neurova.core.ast_scan import parseSource

monotonic = time.monotonic

ALLOWED_BUILTIN_NAMES = (
    "len", "sum", "min", "max", "sorted", "any", "all", "abs",
    "str", "int", "float", "bool", "list", "dict", "tuple", "set",
    "enumerate", "zip", "map", "filter", "reversed", "round",
)

FORBIDDEN_NAMES = frozenset({
    "import", "exec", "eval", "compile", "open", "getattr", "setattr",
    "delattr", "globals", "locals", "vars", "dir", "breakpoint",
    "__import__", "__builtins__",
})

MUTATING_METHODS = frozenset({
    "append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse",
    "update", "setdefault", "add", "discard", "difference_update",
    "intersection_update", "symmetric_difference_update",
})

MAX_RESULT_CHARS = 2000
MAX_EXPRESSION_CHARS = 8192
MAX_AST_NODES = 512
MAX_STEPS = 100000
MAX_ITERATIONS = 10000
MAX_CONTAINER_ITEMS = 20000
MAX_STRING_CHARS = 20000
MAX_TOTAL_CONTAINER_ITEMS = 100000
MAX_TOTAL_STRING_CHARS = 200000
MAX_STRUCTURAL_VISITS = 100000
MAX_INT_BITS = 65536
MAX_SECONDS = 1.0

_STRING_METHODS = frozenset({
    "capitalize", "casefold", "center", "count", "endswith", "expandtabs",
    "find", "index", "isalnum", "isalpha", "isascii", "isdecimal", "isdigit",
    "isidentifier", "islower", "isnumeric", "isprintable", "isspace", "istitle",
    "isupper", "join", "ljust", "lower", "lstrip", "partition", "removeprefix",
    "removesuffix", "replace", "rfind", "rindex", "rjust", "rpartition", "rsplit",
    "rstrip", "split", "splitlines", "startswith", "strip", "swapcase", "title",
    "upper", "zfill",
})
_DICT_METHODS = frozenset({"get", "keys", "values", "items", "copy"})
_LIST_METHODS = frozenset({"count", "index", "copy"})
_TUPLE_METHODS = frozenset({"count", "index"})
_SET_METHODS = frozenset({
    "copy", "difference", "intersection", "symmetric_difference", "union",
    "isdisjoint", "issubset", "issuperset",
})
_NUMBER_METHODS = frozenset({"bit_count", "bit_length", "is_integer", "as_integer_ratio"})

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.BitOr: operator.or_,
    ast.BitAnd: operator.and_,
    ast.BitXor: operator.xor,
}
_COMPARE_OPERATORS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
    ast.Invert: operator.invert,
}


class RecallExpressionError(ValueError):
    """表达式被白名单或资源预算拒绝。"""


class _Scope:
    def __init__(self, values: Optional[Dict[str, Any]] = None,
                 parent: Optional["_Scope"] = None, comprehension: bool = False) -> None:
        self.values = dict(values or {})
        self.parent = parent
        self.comprehension = comprehension

    def get(self, name: str) -> Any:
        if name in self.values:
            return self.values[name]
        if self.parent is not None:
            return self.parent.get(name)
        raise RecallExpressionError(f"未定义名字：{name}")

    def set(self, name: str, value: Any) -> None:
        self.values[name] = value

    def setNamed(self, name: str, value: Any) -> None:
        scope = self
        while scope.comprehension and scope.parent is not None:
            scope = scope.parent
        scope.values[name] = value


class _BuiltinCallable:
    def __init__(self, interpreter: "_Interpreter", name: str) -> None:
        self.interpreter = interpreter
        self.name = name


class _SafeMethod:
    def __init__(self, interpreter: "_Interpreter", receiver: Any, name: str) -> None:
        self.interpreter = interpreter
        self.receiver = receiver
        self.name = name


class _LambdaCallable:
    def __init__(self, interpreter: "_Interpreter", node: ast.Lambda,
                 closure: _Scope, defaults: Dict[str, Any], kwDefaults: Dict[str, Any]) -> None:
        self.interpreter = interpreter
        self.node = node
        self.closure = closure
        self.defaults = defaults
        self.kwDefaults = kwDefaults


class _SafeIterator:
    def __init__(self, interpreter: "_Interpreter", iterator: Any, name: str, cost: int = 1) -> None:
        self.interpreter = interpreter
        self.iterator = iterator
        self.name = name
        self.cost = cost

    def __iter__(self) -> "_SafeIterator":
        return self

    def __next__(self) -> Any:
        return self.interpreter.nextValue(self.iterator, self.cost)


def hasExactType(value: Any, candidates: tuple) -> bool:
    valueType = type(value)
    return any(valueType is candidate for candidate in candidates)


_SCALAR_TYPES = (str, bytes, int, float, bool, type(None))
_INTERNAL_VALUE_TYPES = (_BuiltinCallable, _SafeMethod, _LambdaCallable, _SafeIterator)
_VIEW_TYPES = (type({}.keys()), type({}.values()), type({}.items()))
_CONTAINER_TYPES = (list, tuple, set, frozenset, dict, *_VIEW_TYPES)
_SEQUENCE_TYPES = (str, bytes, list, tuple)


class _Interpreter:
    def __init__(self, items: List[Dict[str, Any]]) -> None:
        self.items = items
        self.deadline = monotonic() + MAX_SECONDS
        self.steps = 0
        self.iterations = 0
        self.containerItems = 0
        self.stringChars = 0
        self.validatedContainers: Dict[int, Any] = {}
        self.validatingContainers = set()
        self.structuralWeights: Dict[int, tuple] = {}
        values: Dict[str, Any] = {"items": items}
        values.update({name: _BuiltinCallable(self, name) for name in ALLOWED_BUILTIN_NAMES})
        self.rootScope = _Scope(values)

    def run(self, tree: ast.Expression) -> Any:
        return self.evaluate(tree.body, self.rootScope)

    def tick(self) -> None:
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise RecallExpressionError(f"表达式步数超过预算 {MAX_STEPS}")
        if monotonic() >= self.deadline:
            raise RecallExpressionError(f"表达式执行时间超过预算 {MAX_SECONDS:.1f}s")

    def nextValue(self, iterator: Any, cost: int = 1) -> Any:
        if hasExactType(iterator, (_SafeIterator,)):
            return next(iterator)
        self.tick()
        try:
            value = next(iterator)
        except StopIteration:
            raise
        self.iterations += cost
        if self.iterations > MAX_ITERATIONS:
            raise RecallExpressionError(f"表达式迭代超过预算 {MAX_ITERATIONS}")
        return self.guard(value)

    def iterate(self, value: Any) -> Any:
        if hasExactType(value, (_SafeIterator,)):
            return value
        if not hasExactType(value, _CONTAINER_TYPES):
            raise RecallExpressionError("对象不可迭代")
        if len(value) > MAX_CONTAINER_ITEMS:
            raise RecallExpressionError(f"容器元素数超过预算 {MAX_CONTAINER_ITEMS}")
        return _SafeIterator(self, iter(value), "iterator")

    def materialize(self, value: Any) -> List[Any]:
        output: List[Any] = []
        for item in self.iterate(value):
            if len(output) >= MAX_CONTAINER_ITEMS:
                raise RecallExpressionError(f"容器元素数超过预算 {MAX_CONTAINER_ITEMS}")
            output.append(self.guard(item))
        self.checkContainerAllocation(len(output))
        return output

    def guard(self, value: Any) -> Any:
        self.validateValue(value)
        return value

    def validateValue(self, value: Any) -> None:
        if hasExactType(value, _SCALAR_TYPES):
            if hasExactType(value, (str, bytes)) and len(value) > MAX_STRING_CHARS:
                raise RecallExpressionError(f"字符串长度超过预算 {MAX_STRING_CHARS}")
            if hasExactType(value, (int,)) and value.bit_length() > MAX_INT_BITS:
                raise RecallExpressionError(f"整数位长超过预算 {MAX_INT_BITS}")
            return
        self.tick()
        if hasExactType(value, _INTERNAL_VALUE_TYPES):
            return
        if not hasExactType(value, _CONTAINER_TYPES):
            raise RecallExpressionError("不允许该类型参与表达式求值")
        if len(value) > MAX_CONTAINER_ITEMS:
            raise RecallExpressionError(f"容器元素数超过预算 {MAX_CONTAINER_ITEMS}")
        identity = id(value)
        if self.validatedContainers.get(identity) is value:
            return
        if identity in self.validatingContainers:
            raise RecallExpressionError("不允许循环容器参与表达式求值")
        self.validatingContainers.add(identity)
        try:
            if hasExactType(value, (dict,)):
                for key, item in value.items():
                    self.validateValue(key)
                    self.validateValue(item)
            else:
                for item in value:
                    self.validateValue(item)
        finally:
            self.validatingContainers.remove(identity)
        self.validatedContainers[identity] = value

    def structuralWeight(self, value: Any) -> int:
        memo: Dict[int, int] = {}

        def visit(current: Any) -> int:
            if hasExactType(current, (str, bytes)):
                return max(1, len(current))
            if hasExactType(current, (int,)):
                return max(1, current.bit_length())
            if hasExactType(current, _SCALAR_TYPES):
                return 1
            if hasExactType(current, _INTERNAL_VALUE_TYPES):
                return 1
            identity = id(current)
            if hasExactType(current, (tuple, frozenset)):
                cached = self.structuralWeights.get(identity)
                if cached is not None and cached[0] is current:
                    return cached[1]
            if identity in memo:
                return memo[identity]
            self.tick()
            if hasExactType(current, (dict,)):
                weight = 1 + sum(visit(key) + visit(item)
                                 for key, item in current.items())
            else:
                weight = 1 + sum(visit(item) for item in current)
            memo[identity] = weight
            if hasExactType(current, (tuple, frozenset)):
                self.structuralWeights[identity] = (current, weight)
            return weight

        return visit(value)

    def checkStructural(self, *values: Any) -> None:
        weight = sum(self.structuralWeight(value) for value in values)
        if weight > MAX_STRUCTURAL_VISITS:
            raise RecallExpressionError(f"结构展开超过预算 {MAX_STRUCTURAL_VISITS}")

    def checkStructuralItems(self, values: Any) -> None:
        self.checkStructural(*values)

    def evaluate(self, node: ast.AST, scope: _Scope) -> Any:
        self.tick()
        if isinstance(node, ast.Constant):
            return self.guard(node.value)
        if isinstance(node, ast.Name):
            return self.guard(scope.get(node.id))
        if isinstance(node, ast.List):
            return self.guard(self.evaluateElements(node.elts, scope, list))
        if isinstance(node, ast.Tuple):
            return self.guard(self.evaluateElements(node.elts, scope, tuple))
        if isinstance(node, ast.Set):
            return self.guard(self.evaluateElements(node.elts, scope, set))
        if isinstance(node, ast.Dict):
            return self.guard(self.evaluateDict(node, scope))
        if isinstance(node, ast.Subscript):
            receiver = self.evaluate(node.value, scope)
            key = self.evaluateSlice(node.slice, scope)
            if isinstance(key, slice) and hasExactType(receiver, _SEQUENCE_TYPES):
                start, stop, step = key.indices(len(receiver))
                size = len(range(start, stop, step))
                if hasExactType(receiver, (str, bytes)):
                    self.checkStringAllocation(size)
                else:
                    self.checkContainerAllocation(size)
            elif hasExactType(receiver, (dict,)):
                self.checkStructural(key, *receiver.keys())
            return self.guard(receiver[key])
        if isinstance(node, ast.Attribute):
            return self.safeMethod(self.evaluate(node.value, scope), node.attr)
        if isinstance(node, ast.Call):
            return self.evaluateCall(node, scope)
        if isinstance(node, ast.Lambda):
            return self.evaluateLambda(node, scope)
        if isinstance(node, ast.IfExp):
            branch = node.body if self.evaluate(node.test, scope) else node.orelse
            return self.evaluate(branch, scope)
        if isinstance(node, ast.BoolOp):
            value = self.evaluate(node.values[0], scope)
            for item in node.values[1:]:
                if isinstance(node.op, ast.And) and not value:
                    return value
                if isinstance(node.op, ast.Or) and value:
                    return value
                value = self.evaluate(item, scope)
            return value
        if isinstance(node, ast.UnaryOp):
            operation = _UNARY_OPERATORS.get(type(node.op))
            if operation is None:
                raise RecallExpressionError("不支持的一元运算")
            return self.guard(operation(self.evaluate(node.operand, scope)))
        if isinstance(node, ast.BinOp):
            return self.evaluateBinOp(node, scope)
        if isinstance(node, ast.Compare):
            left = self.evaluate(node.left, scope)
            for operationNode, comparator in zip(node.ops, node.comparators):
                right = self.evaluate(comparator, scope)
                operation = _COMPARE_OPERATORS.get(type(operationNode))
                if operation is None:
                    raise RecallExpressionError("不支持的比较运算")
                if not isinstance(operationNode, (ast.Is, ast.IsNot)):
                    self.checkStructural(left, right)
                if not operation(left, right):
                    return False
                left = right
            return True
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            return self.evaluateComprehension(node, scope)
        if isinstance(node, ast.NamedExpr):
            if not isinstance(node.target, ast.Name):
                raise RecallExpressionError("命名表达式只能赋值给名字")
            value = self.evaluate(node.value, scope)
            scope.setNamed(node.target.id, value)
            return value
        if isinstance(node, ast.JoinedStr):
            return self.guard(self.evaluateJoinedStr(node, scope))
        if isinstance(node, ast.FormattedValue):
            return self.evaluateFormattedValue(node, scope)
        if isinstance(node, ast.Slice):
            return slice(
                self.evaluate(node.lower, scope) if node.lower is not None else None,
                self.evaluate(node.upper, scope) if node.upper is not None else None,
                self.evaluate(node.step, scope) if node.step is not None else None,
            )
        raise RecallExpressionError(f"不支持的表达式节点：{type(node).__name__}")

    def evaluateElements(self, nodes: List[ast.AST], scope: _Scope, factory: Any) -> Any:
        values: List[Any] = []
        for node in nodes:
            if isinstance(node, ast.Starred):
                values.extend(self.materialize(self.evaluate(node.value, scope)))
            else:
                values.append(self.evaluate(node, scope))
            if len(values) > MAX_CONTAINER_ITEMS:
                raise RecallExpressionError(f"容器元素数超过预算 {MAX_CONTAINER_ITEMS}")
        self.checkContainerAllocation(len(values))
        if factory is set:
            self.checkStructuralItems(values)
        return factory(values)

    def evaluateDict(self, node: ast.Dict, scope: _Scope) -> Dict[Any, Any]:
        output: Dict[Any, Any] = {}
        keyWeight = 0
        for keyNode, valueNode in zip(node.keys, node.values):
            if keyNode is None:
                mapping = self.evaluate(valueNode, scope)
                if not isinstance(mapping, dict):
                    raise RecallExpressionError("字典展开只接受 dict")
                if len(output) + len(mapping) > MAX_CONTAINER_ITEMS:
                    raise RecallExpressionError(f"容器元素数超过预算 {MAX_CONTAINER_ITEMS}")
                keyWeight += sum(self.structuralWeight(key) for key in mapping.keys())
                if keyWeight > MAX_STRUCTURAL_VISITS:
                    raise RecallExpressionError(f"结构展开超过预算 {MAX_STRUCTURAL_VISITS}")
                output.update(mapping)
                continue
            key = self.evaluate(keyNode, scope)
            value = self.evaluate(valueNode, scope)
            keyWeight += self.structuralWeight(key)
            if keyWeight > MAX_STRUCTURAL_VISITS:
                raise RecallExpressionError(f"结构展开超过预算 {MAX_STRUCTURAL_VISITS}")
            if len(output) >= MAX_CONTAINER_ITEMS and key not in output:
                raise RecallExpressionError(f"容器元素数超过预算 {MAX_CONTAINER_ITEMS}")
            output[key] = value
        self.checkContainerAllocation(len(output))
        return output

    def evaluateSlice(self, node: ast.AST, scope: _Scope) -> Any:
        if isinstance(node, ast.Slice):
            return self.evaluate(node, scope)
        return self.evaluate(node, scope)

    def evaluateBinOp(self, node: ast.BinOp, scope: _Scope) -> Any:
        if isinstance(node.op, (ast.Pow, ast.LShift, ast.RShift)):
            raise RecallExpressionError("禁止幂、位移等无界整数运算")
        left = self.evaluate(node.left, scope)
        right = self.evaluate(node.right, scope)
        operation = _BINARY_OPERATORS.get(type(node.op))
        if operation is None:
            raise RecallExpressionError("不支持的二元运算")
        if isinstance(node.op, ast.Add):
            if isinstance(left, str) and isinstance(right, str):
                self.checkStringAllocation(len(left) + len(right))
            elif isinstance(left, (list, tuple)) and isinstance(right, type(left)):
                self.checkContainerAllocation(len(left) + len(right))
        if isinstance(node.op, ast.Mult):
            if isinstance(left, (str, bytes, list, tuple)) and isinstance(right, int):
                self.checkSequenceAllocation(left, right)
            elif isinstance(right, (str, bytes, list, tuple)) and isinstance(left, int):
                self.checkSequenceAllocation(right, left)
            elif isinstance(left, int) and isinstance(right, int):
                if left.bit_length() + right.bit_length() + 1 > MAX_INT_BITS:
                    raise RecallExpressionError(f"整数位长超过预算 {MAX_INT_BITS}")
        if isinstance(node.op, ast.Mod) and isinstance(left, (str, bytes)):
            raise RecallExpressionError("禁止字符串或 bytes % 格式化，避免无界宽度分配")
        if isinstance(node.op, (ast.BitOr, ast.BitAnd, ast.BitXor, ast.Sub)) and (
                hasExactType(left, (set, frozenset, dict))
                or hasExactType(right, (set, frozenset, dict))):
            self.checkStructural(left, right)
        return self.guard(operation(left, right))

    def checkStringAllocation(self, size: int) -> None:
        if size > MAX_STRING_CHARS:
            raise RecallExpressionError(f"字符串长度超过预算 {MAX_STRING_CHARS}")
        self.stringChars += size
        if self.stringChars > MAX_TOTAL_STRING_CHARS:
            raise RecallExpressionError(f"字符串累计分配超过预算 {MAX_TOTAL_STRING_CHARS}")

    def checkContainerAllocation(self, size: int) -> None:
        if size > MAX_CONTAINER_ITEMS:
            raise RecallExpressionError(f"容器元素数超过预算 {MAX_CONTAINER_ITEMS}")
        self.containerItems += size
        if self.containerItems > MAX_TOTAL_CONTAINER_ITEMS:
            raise RecallExpressionError(f"容器累计分配超过预算 {MAX_TOTAL_CONTAINER_ITEMS}")

    def checkSequenceAllocation(self, sequence: Any, count: int) -> None:
        size = max(0, len(sequence) * max(0, count))
        if isinstance(sequence, (str, bytes)):
            self.checkStringAllocation(size)
        else:
            self.checkContainerAllocation(size)

    def safeMethod(self, receiver: Any, name: str) -> _SafeMethod:
        allowed = False
        if isinstance(receiver, str):
            allowed = name in _STRING_METHODS
        elif isinstance(receiver, dict):
            allowed = name in _DICT_METHODS
        elif isinstance(receiver, list):
            allowed = name in _LIST_METHODS
        elif isinstance(receiver, tuple):
            allowed = name in _TUPLE_METHODS
        elif isinstance(receiver, (set, frozenset)):
            allowed = name in _SET_METHODS
        elif isinstance(receiver, (int, float)):
            allowed = name in _NUMBER_METHODS
        if not allowed:
            raise RecallExpressionError(f"禁止访问属性或方法：{name}")
        return _SafeMethod(self, receiver, name)

    def evaluateCall(self, node: ast.Call, scope: _Scope) -> Any:
        function = self.evaluate(node.func, scope)
        args: List[Any] = []
        for argument in node.args:
            if isinstance(argument, ast.Starred):
                args.extend(self.materialize(self.evaluate(argument.value, scope)))
            else:
                args.append(self.evaluate(argument, scope))
        kwargs: Dict[str, Any] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                raise RecallExpressionError("禁止 ** 关键字展开")
            kwargs[keyword.arg] = self.evaluate(keyword.value, scope)
        if hasExactType(function, (_BuiltinCallable,)):
            return self.callBuiltin(function.name, args, kwargs)
        if hasExactType(function, (_SafeMethod,)):
            return self.callMethod(function, args, kwargs)
        if hasExactType(function, (_LambdaCallable,)):
            return self.callLambda(function, args, kwargs)
        raise RecallExpressionError("表达式只能调用白名单内建函数、纯方法或 lambda")

    def evaluateLambda(self, node: ast.Lambda, scope: _Scope) -> _LambdaCallable:
        positional = list(node.args.posonlyargs) + list(node.args.args)
        defaults: Dict[str, Any] = {}
        for argument, default in zip(positional[-len(node.args.defaults):], node.args.defaults):
            defaults[argument.arg] = self.evaluate(default, scope)
        kwDefaults: Dict[str, Any] = {}
        for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if default is not None:
                kwDefaults[argument.arg] = self.evaluate(default, scope)
        return _LambdaCallable(self, node, scope, defaults, kwDefaults)

    def callLambda(self, function: _LambdaCallable, args: List[Any],
                   kwargs: Dict[str, Any]) -> Any:
        arguments = function.node.args
        positional = list(arguments.posonlyargs) + list(arguments.args)
        scope = _Scope(parent=function.closure)
        remaining = dict(kwargs)
        positionalOnly = {argument.arg for argument in arguments.posonlyargs}
        conflicting = sorted(positionalOnly.intersection(remaining))
        if conflicting:
            raise RecallExpressionError(
                f"lambda 位置专用参数不能按关键字传递：{', '.join(conflicting)}")
        for index, argument in enumerate(positional):
            if index < len(args):
                if argument.arg in remaining:
                    raise RecallExpressionError(f"lambda 参数重复：{argument.arg}")
                value = args[index]
            elif argument.arg in remaining:
                value = remaining.pop(argument.arg)
            elif argument.arg in function.defaults:
                value = function.defaults[argument.arg]
            else:
                raise RecallExpressionError(f"lambda 缺少参数：{argument.arg}")
            scope.set(argument.arg, self.guard(value))
        if len(args) > len(positional) and arguments.vararg is None:
            raise RecallExpressionError("lambda 位置参数过多")
        if arguments.vararg is not None:
            scope.set(arguments.vararg.arg, self.guard(tuple(args[len(positional):])))
        for argument in arguments.kwonlyargs:
            if argument.arg in remaining:
                value = remaining.pop(argument.arg)
            elif argument.arg in function.kwDefaults:
                value = function.kwDefaults[argument.arg]
            else:
                raise RecallExpressionError(f"lambda 缺少关键字参数：{argument.arg}")
            scope.set(argument.arg, self.guard(value))
        if arguments.kwarg is not None:
            scope.set(arguments.kwarg.arg, self.guard(remaining))
            remaining = {}
        if remaining:
            raise RecallExpressionError(f"lambda 收到未知关键字参数：{', '.join(sorted(remaining))}")
        return self.evaluate(function.node.body, scope)

    def callMethod(self, function: _SafeMethod, args: List[Any],
                   kwargs: Dict[str, Any]) -> Any:
        receiver = function.receiver
        name = function.name
        if kwargs and not isinstance(receiver, dict):
            allowedKeywords = {
                "split": {"sep", "maxsplit"},
                "rsplit": {"sep", "maxsplit"},
                "splitlines": {"keepends"},
            }
            if not isinstance(receiver, str) or name not in allowedKeywords \
                    or set(kwargs) - allowedKeywords[name]:
                raise RecallExpressionError(f"方法 {name} 不接受关键字参数")
        if isinstance(receiver, (set, frozenset)) and name in (
                "union", "difference", "intersection", "symmetric_difference",
                "isdisjoint", "issubset", "issuperset"):
            args = [self.materialize(value) for value in args]
            self.checkStructural(receiver, *args)
        if hasExactType(receiver, (list, tuple)) and name in ("count", "index") and args:
            self.checkStructural(receiver, args[0])
        if hasExactType(receiver, (dict,)) and name == "get" and args:
            self.checkStructural(args[0], *receiver.keys())
        if isinstance(receiver, str):
            precharged = False
            if name in ("startswith", "endswith"):
                self.checkStructural(*args)
            if name == "join":
                values = self.materialize(args[0])
                if any(not isinstance(value, str) for value in values):
                    raise RecallExpressionError("str.join 只能拼接字符串")
                self.checkStringAllocation(len(receiver) * max(0, len(values) - 1)
                                           + sum(len(value) for value in values))
                precharged = True
            elif name in ("center", "ljust", "rjust", "zfill") and args:
                self.checkStringAllocation(max(len(receiver), int(args[0])))
                precharged = True
            elif name == "expandtabs" and args:
                tabsize = int(args[0])
                self.checkStringAllocation(
                    len(receiver) + receiver.count("\t") * max(0, tabsize - 1))
                precharged = True
            elif name == "replace" and len(args) >= 2:
                old, replacement = args[0], args[1]
                occurrences = receiver.count(old) if old else len(receiver) + 1
                if len(args) >= 3 and int(args[2]) >= 0:
                    occurrences = min(occurrences, int(args[2]))
                self.checkStringAllocation(
                    len(receiver) + occurrences * (len(replacement) - len(old)))
                precharged = True
        else:
            precharged = False
        if isinstance(receiver, (set, frozenset)) and name in ("union", "symmetric_difference"):
            self.checkContainerAllocation(len(receiver) + sum(len(value) for value in args))
            precharged = True
        result = getattr(receiver, name)(*args, **kwargs)
        if not precharged:
            if isinstance(result, str):
                self.checkStringAllocation(len(result))
            elif hasExactType(result, (list, tuple, set, frozenset, dict)):
                self.checkContainerAllocation(len(result))
                if name in ("split", "rsplit", "splitlines", "partition", "rpartition"):
                    self.checkStringAllocation(sum(len(value) for value in result))
        return self.guard(result)

    def callBuiltin(self, name: str, args: List[Any], kwargs: Dict[str, Any]) -> Any:
        if name == "len":
            self.requireArity(name, args, 1, 1, kwargs)
            if not isinstance(args[0], Sized):
                raise RecallExpressionError("len 只接受有长度的对象")
            return len(args[0])
        if name in ("list", "tuple", "set"):
            self.requireArity(name, args, 0, 1, kwargs)
            values = self.materialize(args[0]) if args else []
            if name == "set":
                self.checkStructuralItems(values)
            output = {"list": list, "tuple": tuple, "set": set}[name](values)
            self.checkContainerAllocation(len(output))
            return self.guard(output)
        if name == "dict":
            return self.callDict(args, kwargs)
        if name in ("any", "all"):
            self.requireArity(name, args, 1, 1, kwargs)
            for value in self.iterate(args[0]):
                matched = bool(value)
                if name == "any" and matched:
                    return True
                if name == "all" and not matched:
                    return False
            return name == "all"
        if name == "sum":
            self.requireArity(name, args, 1, 2, kwargs)
            total = args[1] if len(args) == 2 else 0
            for value in self.iterate(args[0]):
                if isinstance(total, str) or isinstance(value, str):
                    raise RecallExpressionError("sum 不支持字符串累加")
                if hasExactType(total, (list, tuple)) and hasExactType(value, (list, tuple)):
                    self.checkContainerAllocation(len(total) + len(value))
                elif hasExactType(total, (bytes,)) and hasExactType(value, (bytes,)):
                    self.checkStringAllocation(len(total) + len(value))
                total = self.guard(total + value)
            return self.guard(total)
        if name in ("min", "max"):
            return self.callMinMax(name, args, kwargs)
        if name == "sorted":
            return self.callSorted(args, kwargs)
        if name == "abs":
            self.requireArity(name, args, 1, 1, kwargs)
            return self.guard(abs(args[0]))
        if name == "round":
            self.requireArity(name, args, 1, 2, kwargs)
            if len(args) == 2 and isinstance(args[1], int) and args[1] < -MAX_STRING_CHARS:
                raise RecallExpressionError(
                    f"round 负精度超过预算 {-MAX_STRING_CHARS}")
            return self.guard(round(*args))
        if name == "str":
            self.requireArity(name, args, 0, 3, kwargs)
            if not args:
                return ""
            if len(args) == 1:
                return self.stringify(args[0])
            if not isinstance(args[0], bytes) or not isinstance(args[1], str):
                raise RecallExpressionError("str 的多参数形式只接受 bytes、encoding、errors")
            if len(args) == 3 and not isinstance(args[2], str):
                raise RecallExpressionError("str 的 errors 必须是字符串")
            text = args[0].decode(*args[1:])
            self.checkStringAllocation(len(text))
            return self.guard(text)
        if name == "int":
            self.requireArity(name, args, 1, 2, kwargs)
            return self.guard(int(*args))
        if name == "float":
            self.requireArity(name, args, 1, 1, kwargs)
            return self.guard(float(*args))
        if name == "bool":
            self.requireArity(name, args, 0, 1, kwargs)
            return bool(args[0]) if args else False
        if name == "enumerate":
            self.requireArity(name, args, 1, 2, kwargs)
            start = args[1] if len(args) == 2 else 0
            return _SafeIterator(self, enumerate(self.iterate(args[0]), start), "enumerate", cost=0)
        if name == "zip":
            if kwargs:
                raise RecallExpressionError("zip 不接受关键字参数")
            iterators = [self.iterate(value) for value in args]
            return _SafeIterator(self, zip(*iterators), "zip", cost=0)
        if name == "reversed":
            self.requireArity(name, args, 1, 1, kwargs)
            try:
                iterator = reversed(args[0])
            except TypeError as exc:
                raise RecallExpressionError("reversed 只接受可反转序列") from exc
            return _SafeIterator(self, iterator, "reversed")
        if name == "map":
            if kwargs or len(args) < 2:
                raise RecallExpressionError("map 至少接受一个函数和一个迭代器")
            return _SafeIterator(self, self.mapValues(args[0], *args[1:]), "map", cost=0)
        if name == "filter":
            self.requireArity(name, args, 2, 2, kwargs)
            return _SafeIterator(self, self.filterValues(args[0], args[1]), "filter", cost=0)
        raise RecallExpressionError(f"未实现的内建函数：{name}")

    @staticmethod
    def requireArity(name: str, args: List[Any], minimum: int, maximum: int,
                     kwargs: Dict[str, Any]) -> None:
        if kwargs or not minimum <= len(args) <= maximum:
            raise RecallExpressionError(f"内建函数 {name} 参数数量不合法")

    def callDict(self, args: List[Any], kwargs: Dict[str, Any]) -> Dict[Any, Any]:
        if len(args) > 1:
            raise RecallExpressionError("dict 最多接受一个位置参数")
        output: Dict[Any, Any] = {}
        keyWeight = 0
        if args:
            source = args[0]
            if isinstance(source, dict):
                keyWeight = sum(self.structuralWeight(key) for key in source.keys())
                if keyWeight > MAX_STRUCTURAL_VISITS:
                    raise RecallExpressionError(f"结构展开超过预算 {MAX_STRUCTURAL_VISITS}")
                output.update(source)
            else:
                for pair in self.iterate(source):
                    values = self.materialize(pair)
                    if len(values) != 2:
                        raise RecallExpressionError("dict 的每个元素必须是长度 2 的键值对")
                    keyWeight += self.structuralWeight(values[0])
                    if keyWeight > MAX_STRUCTURAL_VISITS:
                        raise RecallExpressionError(f"结构展开超过预算 {MAX_STRUCTURAL_VISITS}")
                    if len(output) >= MAX_CONTAINER_ITEMS and values[0] not in output:
                        raise RecallExpressionError(f"容器元素数超过预算 {MAX_CONTAINER_ITEMS}")
                    output[values[0]] = values[1]
        if len(output) + len(kwargs) > MAX_CONTAINER_ITEMS:
            raise RecallExpressionError(f"容器元素数超过预算 {MAX_CONTAINER_ITEMS}")
        output.update(kwargs)
        self.checkContainerAllocation(len(output))
        return self.guard(output)

    def callMinMax(self, name: str, args: List[Any], kwargs: Dict[str, Any]) -> Any:
        key = kwargs.pop("key", None)
        defaultGiven = "default" in kwargs
        default = kwargs.pop("default", None)
        if kwargs or not args:
            raise RecallExpressionError(f"{name} 参数不合法")
        if key is not None and not self.isCallable(key):
            raise RecallExpressionError(f"{name} 的 key 必须是可调用对象")
        if len(args) == 1:
            iterator = self.iterate(args[0])
            try:
                best = self.nextValue(iterator)
            except StopIteration:
                if defaultGiven:
                    return default
                raise RecallExpressionError(f"{name}() 参数为空")
        else:
            if defaultGiven:
                raise RecallExpressionError(f"{name} 多参数形式不接受 default")
            best = self.guard(args[0])
            iterator = self.iterate(args[1:])
        bestKey = self.callValue(key, [best]) if key is not None else best
        for value in self.iterate(iterator):
            valueKey = self.callValue(key, [value]) if key is not None else value
            self.checkStructural(bestKey, valueKey)
            if (name == "min" and valueKey < bestKey) or (name == "max" and valueKey > bestKey):
                best, bestKey = value, valueKey
        return self.guard(best)

    def callSorted(self, args: List[Any], kwargs: Dict[str, Any]) -> List[Any]:
        self.requireArity("sorted", args, 1, 1, {})
        key = kwargs.pop("key", None)
        reverse = kwargs.pop("reverse", False)
        if kwargs:
            raise RecallExpressionError("sorted 收到未知关键字参数")
        if key is not None and not self.isCallable(key):
            raise RecallExpressionError("sorted 的 key 必须是可调用对象")
        values = self.materialize(args[0])
        if key is None:
            self.checkStructuralItems(values)
            values.sort(reverse=bool(reverse))
        else:
            decorated = [(self.callValue(key, [value]), value) for value in values]
            self.checkContainerAllocation(len(decorated))
            self.checkStructuralItems([pair[0] for pair in decorated])
            decorated.sort(key=lambda pair: pair[0], reverse=bool(reverse))
            values = [value for _, value in decorated]
            self.checkContainerAllocation(len(values))
        return self.guard(values)

    def mapValues(self, function: Any, *sources: Any) -> Any:
        if not self.isCallable(function):
            raise RecallExpressionError("map 的第一个参数必须是可调用对象")
        iterators = [self.iterate(source) for source in sources]
        while True:
            values: List[Any] = []
            try:
                for iterator in iterators:
                    values.append(self.nextValue(iterator))
            except StopIteration:
                return
            yield self.callValue(function, values)

    def filterValues(self, function: Any, source: Any) -> Any:
        if function is not None and not self.isCallable(function):
            raise RecallExpressionError("filter 的第一个参数必须是可调用对象或 None")
        iterator = self.iterate(source)
        while True:
            try:
                value = self.nextValue(iterator)
            except StopIteration:
                return
            if function is None or self.callValue(function, [value]):
                yield value

    @staticmethod
    def isCallable(value: Any) -> bool:
        return hasExactType(value, (_BuiltinCallable, _SafeMethod, _LambdaCallable))

    def callValue(self, function: Any, args: List[Any]) -> Any:
        if hasExactType(function, (_BuiltinCallable,)):
            return self.callBuiltin(function.name, args, {})
        if hasExactType(function, (_SafeMethod,)):
            return self.callMethod(function, args, {})
        if hasExactType(function, (_LambdaCallable,)):
            return self.callLambda(function, args, {})
        raise RecallExpressionError("尝试调用非白名单对象")

    def evaluateComprehension(self, node: Any, scope: _Scope) -> Any:
        def generate() -> Any:
            localScope = _Scope(parent=scope, comprehension=True)

            def walk(index: int) -> Any:
                if index == len(node.generators):
                    if isinstance(node, ast.DictComp):
                        yield self.evaluate(node.key, localScope), self.evaluate(node.value, localScope)
                    else:
                        yield self.evaluate(node.elt, localScope)
                    return
                generator = node.generators[index]
                if generator.is_async:
                    raise RecallExpressionError("不支持异步推导式")
                source = self.evaluate(generator.iter, localScope)
                for value in self.iterate(source):
                    self.assignTarget(generator.target, value, localScope)
                    if all(self.evaluate(condition, localScope) for condition in generator.ifs):
                        yield from walk(index + 1)

            yield from walk(0)

        iterator = _SafeIterator(self, generate(), "generator", cost=0)
        if isinstance(node, ast.GeneratorExp):
            return iterator
        if isinstance(node, ast.ListComp):
            return self.guard(self.materialize(iterator))
        if isinstance(node, ast.SetComp):
            output: set = set()
            structuralWeight = 0
            for value in iterator:
                structuralWeight += self.structuralWeight(value)
                if structuralWeight > MAX_STRUCTURAL_VISITS:
                    raise RecallExpressionError(f"结构展开超过预算 {MAX_STRUCTURAL_VISITS}")
                if len(output) >= MAX_CONTAINER_ITEMS and value not in output:
                    raise RecallExpressionError(f"容器元素数超过预算 {MAX_CONTAINER_ITEMS}")
                output.add(value)
            self.checkContainerAllocation(len(output))
            return self.guard(output)
        output: Dict[Any, Any] = {}
        keyWeight = 0
        for key, value in iterator:
            keyWeight += self.structuralWeight(key)
            if keyWeight > MAX_STRUCTURAL_VISITS:
                raise RecallExpressionError(f"结构展开超过预算 {MAX_STRUCTURAL_VISITS}")
            if len(output) >= MAX_CONTAINER_ITEMS and key not in output:
                raise RecallExpressionError(f"容器元素数超过预算 {MAX_CONTAINER_ITEMS}")
            output[key] = value
        self.checkContainerAllocation(len(output))
        return self.guard(output)

    def assignTarget(self, target: ast.AST, value: Any, scope: _Scope) -> None:
        if isinstance(target, ast.Name):
            scope.set(target.id, self.guard(value))
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            values = self.materialize(value)
            starredIndexes = [index for index, item in enumerate(target.elts)
                              if isinstance(item, ast.Starred)]
            if len(starredIndexes) > 1:
                raise RecallExpressionError("解包目标最多包含一个 *")
            if not starredIndexes:
                if len(values) != len(target.elts):
                    raise RecallExpressionError("解包数量不匹配")
                for itemTarget, itemValue in zip(target.elts, values):
                    self.assignTarget(itemTarget, itemValue, scope)
                return
            starIndex = starredIndexes[0]
            trailing = len(target.elts) - starIndex - 1
            if len(values) < len(target.elts) - 1:
                raise RecallExpressionError("解包数量不匹配")
            for index in range(starIndex):
                self.assignTarget(target.elts[index], values[index], scope)
            starTarget = target.elts[starIndex]
            if not isinstance(starTarget, ast.Starred):
                raise RecallExpressionError("无效的解包目标")
            starValues = values[starIndex:len(values) - trailing if trailing else len(values)]
            self.checkContainerAllocation(len(starValues))
            self.assignTarget(starTarget.value, starValues, scope)
            for offset in range(trailing):
                self.assignTarget(target.elts[starIndex + 1 + offset], values[-trailing + offset], scope)
            return
        raise RecallExpressionError("不支持的赋值目标")

    def evaluateJoinedStr(self, node: ast.JoinedStr, scope: _Scope) -> str:
        parts: List[str] = []
        for valueNode in node.values:
            if isinstance(valueNode, ast.Constant):
                parts.append(str(valueNode.value))
            else:
                parts.append(self.stringify(self.evaluate(valueNode, scope)))
        self.checkStringAllocation(sum(len(part) for part in parts))
        return "".join(parts)

    def evaluateFormattedValue(self, node: ast.FormattedValue, scope: _Scope) -> str:
        value = self.evaluate(node.value, scope)
        if node.conversion == 115:
            value = self.stringify(value)
        elif node.conversion in (114, 97):
            value = reprValue(value, MAX_STRING_CHARS + 1)
            if len(value) > MAX_STRING_CHARS:
                raise RecallExpressionError(f"字符串长度超过预算 {MAX_STRING_CHARS}")
        spec = ""
        if node.format_spec is not None:
            spec = self.stringify(self.evaluate(node.format_spec, scope))
            if len(spec) > 100:
                raise RecallExpressionError("格式化规格超过预算")
            for match in re.finditer(r"\d+", spec):
                if int(match.group()) > MAX_STRING_CHARS:
                    raise RecallExpressionError(f"字符串长度超过预算 {MAX_STRING_CHARS}")
        text = format(value, spec) if spec else self.stringify(value)
        self.checkStringAllocation(len(text))
        return self.guard(text)

    def stringify(self, value: Any) -> str:
        if hasExactType(value, (str,)):
            return self.guard(value)
        text = reprValue(value, MAX_STRING_CHARS + 1)
        if len(text) > MAX_STRING_CHARS:
            raise RecallExpressionError(f"字符串长度超过预算 {MAX_STRING_CHARS}")
        self.checkStringAllocation(len(text))
        return text

    def repr(self, value: Any, limit: int) -> tuple:
        prefix = reprValue(value, limit + 1)
        if len(prefix) <= limit:
            return prefix, len(prefix), True
        marker = f"…[截断，超过 {limit} 字符]"
        return prefix[:limit] + marker, limit + 1, False


def validateRecallExpression(expression: str) -> ast.Expression:
    """解析并校验表达式；不合法抛 `RecallExpressionError`。"""
    if not expression or not expression.strip():
        raise RecallExpressionError("表达式为空")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise RecallExpressionError(f"表达式长度超过预算 {MAX_EXPRESSION_CHARS}")
    try:
        tree = parseSource(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise RecallExpressionError(f"表达式语法错误：{exc}") from exc

    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise RecallExpressionError(f"表达式节点数超过预算 {MAX_AST_NODES}")
    for node in nodes:
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
            if node.attr in MUTATING_METHODS:
                raise RecallExpressionError(f"禁止调用可变方法 {node.attr}")
        if isinstance(node, ast.Call) and any(keyword.arg is None for keyword in node.keywords):
            raise RecallExpressionError("禁止 ** 关键字展开")
    return tree


def runRecallExpression(expression: str, items: List[Dict[str, Any]]) -> str:
    """在白名单解释器里对 `items` 求值表达式，返回截断后的字符串结果。"""
    tree = validateRecallExpression(expression)
    try:
        interpreter = _Interpreter(items)
        result = interpreter.run(tree)
        if isinstance(result, str):
            text = result
            if len(text) > MAX_RESULT_CHARS:
                text = text[:MAX_RESULT_CHARS] + f"…[截断，共 {len(text)} 字符]"
            return text
        text, _length, _exact = interpreter.repr(result, MAX_RESULT_CHARS)
        return text
    except RecallExpressionError:
        raise
    except Exception as exc:
        raise RecallExpressionError(f"表达式求值失败：{exc}") from exc


def reprValue(value: Any, limit: int) -> str:
    parts: List[str] = []
    remaining = max(0, limit)

    def appendText(text: str) -> None:
        nonlocal remaining
        if remaining <= 0:
            return
        chunk = text[:remaining]
        parts.append(chunk)
        remaining -= len(chunk)

    def appendValue(current: Any, seen: set, depth: int) -> None:
        if remaining <= 0:
            return
        if depth > 20:
            appendText("...")
            return
        if hasExactType(current, (_SafeIterator,)):
            appendText(f"<{current.name} object>")
            return
        if hasExactType(current, (str, bytes)):
            appendText(repr(current[:remaining]))
            return
        if hasExactType(current, (int,)):
            if current.bit_length() > remaining * 4:
                appendText("<large int>")
                return
            appendText(repr(current))
            return
        if hasExactType(current, (float, bool, type(None))):
            appendText(repr(current))
            return
        identity = id(current)
        if identity in seen:
            appendText("...")
            return
        if hasExactType(current, (dict,)):
            if not current:
                appendText("{}")
                return
            seen.add(identity)
            appendText("{")
            for index, (key, item) in enumerate(current.items()):
                if index:
                    appendText(", ")
                appendValue(key, seen, depth + 1)
                appendText(": ")
                appendValue(item, seen, depth + 1)
                if remaining <= 0:
                    break
            appendText("}")
            seen.remove(identity)
            return
        if hasExactType(current, (list, tuple, set, frozenset)):
            if not current:
                appendText("set()" if hasExactType(current, (set,)) else
                           ("frozenset()" if hasExactType(current, (frozenset,)) else
                            ("()" if hasExactType(current, (tuple,)) else "[]")))
                return
            seen.add(identity)
            if hasExactType(current, (set,)):
                appendText("{")
            elif hasExactType(current, (frozenset,)):
                appendText("frozenset({")
            else:
                appendText("(" if hasExactType(current, (tuple,)) else "[")
            for index, item in enumerate(current):
                if index:
                    appendText(", ")
                appendValue(item, seen, depth + 1)
                if remaining <= 0:
                    break
            appendText("})" if hasExactType(current, (frozenset,)) else
                       (")" if hasExactType(current, (tuple,)) else
                        ("}" if hasExactType(current, (set,)) else "]")))
            if hasExactType(current, (tuple,)) and len(current) == 1:
                appendText(",")
            seen.remove(identity)
            return
        appendText("<unsupported>")

    appendValue(value, set(), 0)
    return "".join(parts)
