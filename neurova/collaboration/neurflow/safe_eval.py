"""
安全条件表达式求值器 — 无 eval/exec 的受限 DSL 解析

为 neurflow 的 condition / loop break_condition 提供安全的表达式求值：
不支持任意 Python 代码，仅支持以下语法（白名单解析器实现）：

    表达式   := or_expr
    or_expr  := and_expr ("or" and_expr)*
    and_expr := not_expr ("and" not_expr)*
    not_expr := "not" not_expr | comparison
    比较式   := 操作数 ((== | != | >= | <= | > | < | in | not in) 操作数)?
    操作数   := 字面量 | $变量 | 标识符 | 函数(操作数) | ( 表达式 )
    函数     := len | str | int | float | bool   （白名单）

变量查找顺序：context 字典（含 $iteration/$current/$node/$var/$input 等注入值）。
任何解析/求值错误返回 False（与既有 exec_condition 的失败语义一致）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ── 词法 ─────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<var>\$[A-Za-z_]\w*)
      | (?P<number>\d+\.\d+|\d+)
      | (?P<op>==|!=|>=|<=|>|<)
      | (?P<paren>[()])
      | (?P<comma>,)
      | (?P<string>'[^']*'|"[^"]*")
      | (?P<word>[A-Za-z_]\w*)
    )""",
    re.VERBOSE,
)

_COMPARE_OPS = {"==", "!=", ">=", "<=", ">", "<"}
_FUNCS = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}
_CONSTANTS = {"True": True, "False": False, "None": None}


class _SafeEvalError(Exception):
    pass


def _tokenize(expr: str) -> List[str]:
    tokens: List[str] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if m is None:
            if expr[pos:].strip() == "":
                break
            raise _SafeEvalError(f"非法字符: {expr[pos:pos + 10]!r}")
        pos = m.end()
        tokens.append(m.lastgroup and m.group(m.lastgroup))
    return tokens


# ── 语法分析 + 求值（递归下降） ──────────────────────────────────


class _Parser:
    def __init__(self, tokens: List[str], context: Dict[str, Any]):
        self.tokens = tokens
        self.pos = 0
        self.context = context

    def peek(self) -> Optional[str]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> str:
        tok = self.peek()
        if tok is None:
            raise _SafeEvalError("表达式意外结束")
        self.pos += 1
        return tok

    def expect(self, tok: str) -> None:
        got = self.next()
        if got != tok:
            raise _SafeEvalError(f"期望 {tok!r}，实际 {got!r}")

    # 表达式入口
    def parse(self) -> Any:
        value = self.parse_or()
        if self.peek() is not None:
            raise _SafeEvalError(f"多余 token: {self.peek()!r}")
        return value

    def parse_or(self) -> Any:
        value = self.parse_and()
        while self.peek() == "or":
            self.next()
            rhs = self.parse_and()
            value = bool(value) or bool(rhs)
        return value

    def parse_and(self) -> Any:
        value = self.parse_not()
        while self.peek() == "and":
            self.next()
            rhs = self.parse_not()
            value = bool(value) and bool(rhs)
        return value

    def parse_not(self) -> Any:
        if self.peek() == "not":
            self.next()
            return not bool(self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self) -> Any:
        left = self.parse_operand()
        op = self.peek()
        if op in _COMPARE_OPS:
            self.next()
            right = self.parse_operand()
            return self._compare(op, left, right)
        if op == "in":
            self.next()
            return left in self.parse_operand()
        if op == "not" and self.tokens[self.pos + 1: self.pos + 2] == ["in"]:
            self.next()
            self.next()
            return left not in self.parse_operand()
        return left

    @staticmethod
    def _compare(op: str, left: Any, right: Any) -> Any:
        try:
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == ">=":
                return left >= right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            if op == "<":
                return left < right
        except TypeError:
            return False
        raise _SafeEvalError(f"未知比较符 {op}")

    def parse_operand(self) -> Any:
        tok = self.peek()
        if tok is None:
            raise _SafeEvalError("缺少操作数")
        if tok == "(":
            self.next()
            value = self.parse_or()
            self.expect(")")
            return value
        if tok == "-":
            self.next()
            return -self.parse_operand()
        return self.parse_primary()

    def parse_primary(self) -> Any:
        tok = self.next()
        if tok in _CONSTANTS:
            return _CONSTANTS[tok]
        if tok.startswith("$") or (tok.isidentifier() and tok not in ("and", "or", "not", "in")):
            # 函数调用（白名单）
            if self.peek() == "(" and tok in _FUNCS:
                self.next()
                args = [self.parse_or()]
                while self.peek() == ",":
                    self.next()
                    args.append(self.parse_or())
                self.expect(")")
                return _FUNCS[tok](*args)
            # 变量查找（$name 或裸标识符），未定义视为 None
            return self.context.get(tok)
        if tok.startswith(("'", '"')):
            return tok[1:-1]
        if tok[0].isdigit():
            return float(tok) if "." in tok else int(tok)
        raise _SafeEvalError(f"意外 token: {tok!r}")


def safe_eval_condition(expression: str, context: Dict[str, Any]) -> bool:
    """安全求值条件表达式（无 eval/exec），失败返回 False。

    Args:
        expression: 条件表达式，如 "$iteration >= 3 and $current != ''"
        context: 变量上下文，如 {"$iteration": 1, "$current": "...", "$node": {...}}

    Returns:
        布尔结果；解析/求值错误一律 False
    """
    if not expression or not str(expression).strip():
        return False
    try:
        tokens = _tokenize(str(expression))
        if not tokens:
            return False
        return bool(_Parser(tokens, context or {}).parse())
    except _SafeEvalError as e:
        import logging

        logging.getLogger(__name__).warning(
            "安全条件表达式求值失败: %r (%s)", expression, e
        )
        return False
    except Exception as e:  # noqa: BLE001 - 任何求值异常按 False 处理
        import logging

        logging.getLogger(__name__).warning(
            "安全条件表达式异常: %r (%s)", expression, e
        )
        return False


__all__ = ["safe_eval_condition"]
