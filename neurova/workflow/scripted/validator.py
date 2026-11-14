"""受限脚本静态校验（P3-14）。

模型写下的脚本在执行前必须过 AST 白名单：
- 禁 ``import`` / ``from ... import``（一切能力经宿主 ctx 提供）；
- 禁危险内建调用（eval/exec/compile/open/input/__import__/getattr/
  setattr/delattr/globals/locals/vars/dir/breakpoint/super/type 等）；
- 禁 dunder 属性访问（``__class__``/``__builtins__`` 逃逸面）；
- 必须定义 ``async def main(ctx)``（唯一入口，宿主只把 ctx 递给它）；
- 禁 ``global``/``nonlocal``（保持脚本是线性过程，journal 可确定性重放）。

解析走全仓唯一出口 ``tests.ast_scan.parseSource``（ratchet 钉住）。
"""

from __future__ import annotations

from typing import List

_BANNED_BUILTINS = {
    "eval", "exec", "compile", "open", "input", "__import__",
    "getattr", "setattr", "delattr", "globals", "locals", "vars", "dir",
    "breakpoint", "super", "type", "object", "memoryview", "bytearray",
    "classmethod", "staticmethod", "property", "help", "exit", "quit",
}


def validateScript(script: str) -> List[str]:
    """静态校验受限脚本；返回违规清单（空 = 通过）。"""
    violations: List[str] = []
    if not script or not script.strip():
        return ["脚本为空"]

    from tests.ast_scan import parseSource

    try:
        tree = parseSource(script, filename="<scripted-workflow>")
    except SyntaxError as e:
        return [f"脚本语法错误: {e}"]

    hasMain = False

    def _walk(node) -> None:
        nonlocal hasMain
        import ast

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            violations.append(f"禁止 import（行 {getattr(node, 'lineno', '?')}）——能力只经 ctx 提供")
            return
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            violations.append(f"禁止 global/nonlocal（行 {getattr(node, 'lineno', '?')}）——脚本须保持线性可重放")
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
            hasMain = True
            if not isinstance(node, ast.AsyncFunctionDef):
                violations.append(
                    f"main 必须定义为 async def main(ctx)（行 {getattr(node, 'lineno', '?')}）"
                    "——宿主 API 是异步的"
                )
            if not node.args.args:
                violations.append("main 必须接收 ctx 参数")
        if isinstance(node, ast.Attribute):
            attr = getattr(node, "attr", "")
            if attr.startswith("__"):
                violations.append(f"禁止 dunder 属性访问 .{attr}（行 {getattr(node, 'lineno', '?')}）")
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None)
            if name in _BANNED_BUILTINS:
                violations.append(f"禁止调用 {name}（行 {getattr(node, 'lineno', '?')}）")
        for child in ast.iter_child_nodes(node):
            _walk(child)

    _walk(tree)

    if not hasMain:
        violations.append("脚本必须定义 async def main(ctx) 作为入口")
    return violations
