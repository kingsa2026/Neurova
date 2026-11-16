"""受限脚本静态校验与分析（P3-14；P3 蜂群对照 #7 扩展）。

模型写下的脚本在执行前必须过 AST 白名单：
- 禁 ``import`` / ``from ... import``（一切能力经宿主 ctx 提供）；
- 禁危险内建调用（eval/exec/compile/open/input/__import__/getattr/
  setattr/delattr/globals/locals/vars/dir/breakpoint/super/type 等）；
- 禁 dunder 属性访问（``__class__``/``__builtins`` 逃逸面）；
- 必须定义 ``async def main(ctx)``（唯一入口，宿主只把 ctx 递给它）；
- 禁 ``global``/``nonlocal``（保持脚本是线性过程，journal 可确定性重放）。

解析走全仓唯一出口 ``neurova.core.ast_scan.parseSource``（ratchet 钉住）。

P3（蜂群对照 #7）：``analyzeScript`` 在同一份 AST 走查上额外产出
**结构化诊断（诊断码 9001-9006）** 与 **四图**——调用点（site）、
因果（causality：哪个调用的结果流入哪个后续调用）、控制流（flow）、
交接（handoff：产出/消费链）。校验不过直接带码回诊断，脚本作者据码修脚本。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_BANNED_BUILTINS = {
    "eval", "exec", "compile", "open", "input", "__import__",
    "getattr", "setattr", "delattr", "globals", "locals", "vars", "dir",
    "breakpoint", "super", "type", "object", "memoryview", "bytearray",
    "classmethod", "staticmethod", "property", "help", "exit", "quit",
}

# 诊断码表（本仓自有语义，不引第三方码表）：
#   9001 脚本为空 / 语法错误
#   9002 禁止 import
#   9003 禁止 global/nonlocal
#   9004 main 入口缺失或签名不符
#   9005 禁止 dunder 属性访问
#   9006 禁止危险内建调用
_CODE_EMPTY = 9001
_CODE_SYNTAX = 9001
_CODE_IMPORT = 9002
_CODE_GLOBAL = 9003
_CODE_ENTRY = 9004
_CODE_DUNDER = 9005
_CODE_BANNED = 9006


def _walkScript(
    script: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """单一 AST 走查：结构化诊断 + 调用点记录 + 控制流计数。

    Returns:
        (diagnostics, rawSites, flow)
        diagnostics: [{"code", "message", "line"}]——message 与历史校验文案逐字一致；
        rawSites: [{"seq", "tool", "line", "produces", "_node"}]（_node 供因果分析，不外泄）；
        flow: {"loops", "branches", "tryBlocks", "awaits"}
    """
    diagnostics: List[Dict[str, Any]] = []
    rawSites: List[Dict[str, Any]] = []
    flow = {"loops": 0, "branches": 0, "tryBlocks": 0, "awaits": 0}

    if not script or not script.strip():
        diagnostics.append({"code": _CODE_EMPTY, "message": "脚本为空", "line": None})
        return diagnostics, rawSites, flow

    import ast

    from neurova.core.ast_scan import parseSource

    try:
        tree = parseSource(script, filename="<scripted-workflow>")
    except SyntaxError as e:
        diagnostics.append(
            {"code": _CODE_SYNTAX, "message": f"脚本语法错误: {e}", "line": getattr(e, "lineno", None)}
        )
        return diagnostics, rawSites, flow

    # 预扫：调用表达式 → 赋值目标变量（该调用"产出"什么）。
    # 注意 await ctx.callTool(...) 的 Assign.value 是 Await 节点——剥开再认 Call。
    produces: Dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = node.value
            if isinstance(value, ast.Await):
                value = value.value
            if isinstance(value, ast.Call):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if names:
                    produces[id(value)] = names[0]

    hasMain = False
    seq = 0

    def _walk(node) -> None:
        nonlocal hasMain, seq
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            diagnostics.append(
                {
                    "code": _CODE_IMPORT,
                    "message": f"禁止 import（行 {getattr(node, 'lineno', '?')}）——能力只经 ctx 提供",
                    "line": getattr(node, "lineno", None),
                }
            )
            return
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            diagnostics.append(
                {
                    "code": _CODE_GLOBAL,
                    "message": f"禁止 global/nonlocal（行 {getattr(node, 'lineno', '?')}）——脚本须保持线性可重放",
                    "line": getattr(node, "lineno", None),
                }
            )
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
            hasMain = True
            if not isinstance(node, ast.AsyncFunctionDef):
                diagnostics.append(
                    {
                        "code": _CODE_ENTRY,
                        "message": (
                            f"main 必须定义为 async def main(ctx)（行 {getattr(node, 'lineno', '?')}）"
                            "——宿主 API 是异步的"
                        ),
                        "line": getattr(node, "lineno", None),
                    }
                )
            if not node.args.args:
                diagnostics.append(
                    {"code": _CODE_ENTRY, "message": "main 必须接收 ctx 参数", "line": getattr(node, "lineno", None)}
                )
        if isinstance(node, ast.Attribute):
            attr = getattr(node, "attr", "")
            if attr.startswith("__"):
                diagnostics.append(
                    {
                        "code": _CODE_DUNDER,
                        "message": f"禁止 dunder 属性访问 .{attr}（行 {getattr(node, 'lineno', '?')}）",
                        "line": getattr(node, "lineno", None),
                    }
                )
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None)
            if name in _BANNED_BUILTINS:
                diagnostics.append(
                    {
                        "code": _CODE_BANNED,
                        "message": f"禁止调用 {name}（行 {getattr(node, 'lineno', '?')}）",
                        "line": getattr(node, "lineno", None),
                    }
                )
            # ctx.callTool("工具名", ...) 调用点（工具名须是字面量才可静态定名）
            if (
                isinstance(func, ast.Attribute)
                and getattr(func.value, "id", "") == "ctx"
                and func.attr == "callTool"
            ):
                seq += 1
                tool = ""
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    tool = node.args[0].value
                rawSites.append(
                    {
                        "seq": seq,
                        "tool": tool or "<运行期决定>",
                        "line": getattr(node, "lineno", None),
                        "produces": produces.get(id(node), ""),
                        "_node": node,
                    }
                )
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            flow["loops"] += 1
        if isinstance(node, ast.If):
            flow["branches"] += 1
        if isinstance(node, ast.Try):
            flow["tryBlocks"] += 1
        if isinstance(node, ast.Await):
            flow["awaits"] += 1
        for child in ast.iter_child_nodes(node):
            _walk(child)

    _walk(tree)

    if not hasMain:
        diagnostics.append(
            {
                "code": _CODE_ENTRY,
                "message": "脚本必须定义 async def main(ctx) 作为入口",
                "line": None,
            }
        )
    return diagnostics, rawSites, flow


def validateScript(script: str) -> List[str]:
    """静态校验受限脚本；返回违规清单（空 = 通过）。

    与 ``analyzeScript`` 同一次走查（单一事实源）：这里只投影出历史文案。
    """
    diagnostics, _sites, _flow = _walkScript(script)
    return [d["message"] for d in diagnostics]


def analyzeScript(script: str) -> Dict[str, Any]:
    """P3（蜂群对照 #7）：静态分析——诊断码 + 四图（site/causality/flow/handoff）。

    - sites：每个 ``ctx.callTool`` 调用点（序号/工具名/行号/产出变量）；
    - causality：前面某调用产出的变量被后面哪个调用消费（数据流边）；
    - flow：循环/分支/try/await 计数（控制流概要）；
    - handoff：按序交接链（每步消费哪些变量、产出哪个变量）。
    """
    diagnostics, rawSites, flow = _walkScript(script)

    sites: List[Dict[str, Any]] = []
    handoff: List[Dict[str, Any]] = []
    causality: List[Dict[str, Any]] = []
    producedAt: Dict[str, int] = {}

    import ast

    for entry in rawSites:
        node = entry["_node"]
        consumed = sorted(
            {
                n.id
                for n in ast.walk(node)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id != "ctx"
            }
        )
        sites.append(
            {"seq": entry["seq"], "tool": entry["tool"], "line": entry["line"], "produces": entry["produces"]}
        )
        handoff.append(
            {"seq": entry["seq"], "tool": entry["tool"], "consumes": consumed, "produces": entry["produces"]}
        )
        for var in consumed:
            src = producedAt.get(var)
            if src is not None and src < entry["seq"]:
                causality.append({"from_seq": src, "to_seq": entry["seq"], "via": var})
        if entry["produces"]:
            producedAt[entry["produces"]] = entry["seq"]

    return {
        "ok": not diagnostics,
        "diagnostics": diagnostics,
        "graphs": {
            "sites": sites,
            "causality": causality,
            "flow": flow,
            "handoff": handoff,
        },
    }
