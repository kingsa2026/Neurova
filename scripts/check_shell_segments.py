# -*- coding: utf-8 -*-
"""shell 分段治理静态扫描（U19 卡，alint 式试点）：拼接型 shell 命令必须可追溯。

背景：``neurova/security/command_segments.py`` 把 shell 命令按 &&/||/;/| 与
inline 子命令拆段，``neurova/security/governance.py`` 对**每一段**做白名单
裁决（任一段未命中即回落内容检测/审批）——"白名单命令 + 注入段"不能再搭便车。
执行咽喉在 ``neurova/tool_executor.py``。

口径（与出站扫描 ``check_outbound_fetch.py`` 同构，教义第 6 条·单一事实源）：
- 扫描 ``neurova/**/*.py`` 中"执行 shell 命令的调用点"：``subprocess.run/
  Popen/call/check_output(shell=True)``、``os.system``、paramiko
  ``exec_command``、``asyncio.create_subprocess_shell``；
- 且命令串在调用点含**拼接/格式化**（f-string、``+``、``.format``、``%``）
  ——这类点必须能追溯到分段治理：所在文件已在 ALLOW_REGISTRY 登记，或
  该文件 import 了 command_segments/governance 且在调用邻近（同一函数内）
  实际引用；否则记为违规；
- AST 判定（非正则）：注释、docstring、普通字符串字面量里的 ``os.system(``
  等字样一律不命中，先例扫描器的整行正则误报面在此收掉。

档位（拍板 D-T5：先 warning 跑误报率，误报清零后升 error 接 static-gate）：
- 默认 warning：列出违规点，**退出码恒 0**，不阻断；
- ``--strict``：违规退出 1——供误报清零后升档，本期不挂门禁。

扫描自身豁免：``tests/``、``scripts/``、ALLOW 登记文件。

已知盲区（记录在案，不算误报）：行级静态扫描看不到"跨函数先拼接再透传"
（如 ``tunnel/remote_deploy.py`` 的 ``writeText`` 先 f-string 拼好命令再经
``self.run`` 落到 ``exec_command``）——这类点由后续卡接过程间分析，或按
修复教义改成 argv 列表传递消掉拼接面。

用法：``python scripts/check_shell_segments.py [--strict]``。
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOT = REPO_ROOT / "neurova"

#: 分段治理事实源（命中点豁免须能追溯到这里）
GOVERNANCE_MODULE_PREFIXES = (
    "neurova.security.command_segments",
    "neurova.security.governance",
)

_SUBPROCESS_FUNCS = {"run", "Popen", "call", "check_output"}

# ══════════════════════════════════════════════════════════════
# 登记表（唯一豁免出处）：命中点经人工核实确已等效分段治理、或命令串
# 不受外部输入影响，才在此登记并逐条写明理由；目标 = 空表。
# 本期（2026-11-22）实跑 0 命中，暂无条目。
# ══════════════════════════════════════════════════════════════
ALLOW_REGISTRY: dict[str, str] = {}

# ══════════════════════════════════════════════════════════════
# 误报率（U19 试点口径，人工逐条核实后写入，每次实跑复核更新）：
#   误报率 = 人工核实为"非真风险"的命中点数 / 扫描命中点总数。
#   核实方法：逐条读调用点上下文——命令串的拼接段是否可能携带非受控
#   输入（用户/远端/工具参数），以及该点是否已有等效分段治理。
#   本期实跑命中 0 处：现有 shell 执行点（core/hooks_engine、
#   execution_engine/shell_sessions、api/endpoints/computer /shell、
#   computer_use/ssh_runner、tunnel/remote_deploy）的命令串在调用点
#   均为变量/属性透传，无拼接——无样可核，按 0.0 记。
# ══════════════════════════════════════════════════════════════
VERIFIED_FALSE_POSITIVE_RATE: float = 0.0


def findConcat(node: ast.AST) -> bool:
    """命令串表达式是否含拼接/格式化（f-string / ``+`` / ``%`` / ``.format``）。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.JoinedStr):
            return True
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, (ast.Add, ast.Mod)):
            return True
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "format"
        ):
            return True
    return False


def _collectAliases(tree: ast.Module) -> dict[str, str]:
    """localName → 全限定目标（模块或模块内符号），含函数内惰性 import。"""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    aliases[a.asname] = a.name
                else:
                    # import x.y.z 绑定顶名 x（按 x 解析属性链的接收者）
                    top = a.name.split(".")[0]
                    aliases.setdefault(top, top)
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                local = a.asname or a.name
                aliases[local] = f"{node.module}.{a.name}"
    return aliases


def _governanceSymbols(aliases: dict[str, str]) -> set[str]:
    """import 自 command_segments/governance 的本地绑定名。"""
    return {
        local
        for local, target in aliases.items()
        if target.startswith(GOVERNANCE_MODULE_PREFIXES)
    }


def _classifyCall(call: ast.Call, aliases: dict[str, str]) -> tuple[str | None, bool]:
    """识别 shell 执行调用点。返回 (kind, needsShellTrue)；kind=None 非执行点。"""
    func = call.func
    if isinstance(func, ast.Attribute):
        attr = func.attr
        if attr == "exec_command":
            return "paramiko.exec_command", False
        if attr == "create_subprocess_shell":
            return "asyncio.create_subprocess_shell", False
        if isinstance(func.value, ast.Name):
            mod = aliases.get(func.value.id, func.value.id)
            if mod == "subprocess" and attr in _SUBPROCESS_FUNCS:
                return f"subprocess.{attr}", True
            if mod == "os" and attr == "system":
                return "os.system", False
        return None, False
    if isinstance(func, ast.Name):
        target = aliases.get(func.id, "")
        if target == "os.system":
            return "os.system", False
        mod, _, name = target.rpartition(".")
        if mod == "subprocess" and name in _SUBPROCESS_FUNCS:
            return target, True
    return None, False


def _hasShellTrue(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _commandArg(call: ast.Call) -> ast.AST | None:
    """命令串实参：首个位置参数，或 args/cmd/command 关键字。"""
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg in ("args", "cmd", "command"):
            return kw.value
    return None


def _mapCallsToFunctions(tree: ast.Module) -> dict[int, ast.AST]:
    """每个 Call 节点 → 最内层所属函数（模块级调用不入表）。"""
    owners: dict[int, ast.AST] = {}
    stack: list[ast.AST] = []

    class Visitor(ast.NodeVisitor):
        def _enter(self, node: ast.AST) -> None:
            stack.append(node)
            self.generic_visit(node)
            stack.pop()

        visit_FunctionDef = _enter
        visit_AsyncFunctionDef = _enter
        visit_Lambda = _enter

        def visit_Call(self, node: ast.Call) -> None:
            if stack:
                owners[id(node)] = stack[-1]
            self.generic_visit(node)

    Visitor().visit(tree)
    return owners


def _governedNearCall(funcNode: ast.AST | None, govSymbols: set[str]) -> bool:
    """调用所在函数体内是否实际引用了分段治理符号（import 挂名不算）。"""
    if funcNode is None or not govSymbols:
        return False
    for sub in ast.walk(funcNode):
        if isinstance(sub, ast.Name) and sub.id in govSymbols:
            return True
    return False


def scanModule(path: Path, relKey: str) -> dict:
    """扫单文件：统计 shell 执行点/拼接点，返回未治理违规清单。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return {"file": relKey, "shellExecSites": 0, "concatSites": 0, "violations": []}
    lines = text.splitlines()
    aliases = _collectAliases(tree)
    govSymbols = _governanceSymbols(aliases)
    owners = _mapCallsToFunctions(tree)
    shellExecSites = 0
    concatSites = 0
    violations: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kind, needsShell = _classifyCall(node, aliases)
        if kind is None:
            continue
        if needsShell and not _hasShellTrue(node):
            continue
        shellExecSites += 1
        arg = _commandArg(node)
        if arg is None or not findConcat(arg):
            continue
        concatSites += 1
        if _governedNearCall(owners.get(id(node)), govSymbols):
            continue
        snippet = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
        violations.append({
            "file": relKey,
            "line": node.lineno,
            "snippet": snippet[:160],
            "kind": kind,
            "reason": "命令串含拼接/格式化，调用点未追溯到位分段治理"
                      "（文件未登记 ALLOW，调用邻近亦无 command_segments/governance 引用）",
        })
    return {
        "file": relKey,
        "shellExecSites": shellExecSites,
        "concatSites": concatSites,
        "violations": violations,
    }


def _iterTargets(root: Path, registry: dict[str, str]):
    """遍历待扫文件（豁免 __pycache__、tests/、scripts/、ALLOW 登记）。"""
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "__pycache__" in rel.split("/"):
            continue
        if rel.startswith("tests/") or rel.startswith("scripts/"):
            continue
        relKey = ("neurova/" + rel) if root.name == "neurova" else str(path)
        if relKey in registry:
            continue
        yield path, relKey


def collectReport(root: Path | None = None, registry: dict[str, str] | None = None) -> dict:
    """结构化扫描结果：计数 + 违规清单 + 误报率 + 档位。"""
    root = SCAN_ROOT if root is None else root
    registry = ALLOW_REGISTRY if registry is None else registry
    scannedFiles = 0
    shellExecSites = 0
    concatSites = 0
    violations: list[dict] = []
    for path, relKey in _iterTargets(root, registry):
        scannedFiles += 1
        result = scanModule(path, relKey)
        shellExecSites += result["shellExecSites"]
        concatSites += result["concatSites"]
        violations.extend(result["violations"])
    return {
        "scannedFiles": scannedFiles,
        "shellExecSites": shellExecSites,
        "concatSites": concatSites,
        "violations": violations,
        "falsePositiveRate": VERIFIED_FALSE_POSITIVE_RATE,
        "mode": "warning",
    }


def scanTree(root: Path, registry: dict[str, str] | None = None) -> list[dict]:
    """返回违规清单（collectReport 的违规面，供门禁/测试直接断言）。"""
    return collectReport(root, registry)["violations"]


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="shell 分段治理静态扫描（U19 试点）")
    parser.add_argument("--strict", action="store_true",
                        help="升档开关：存在违规退出 1（误报清零后接 static-gate 用）")
    args = parser.parse_args(argv)
    report = collectReport(root=root)
    report["mode"] = "strict" if args.strict else "warning"
    scope = root.name if root is not None else "neurova/"
    print(f"[check_shell_segments] 扫描 {scope}：{report['scannedFiles']} 个文件，"
          f"shell 执行点 {report['shellExecSites']} 处，"
          f"其中命令串含拼接/格式化 {report['concatSites']} 处。")
    violations = report["violations"]
    if violations:
        tail = "，不阻断" if not args.strict else ""
        print(f"[check_shell_segments] 未接分段治理的拼接型 shell 调用 "
              f"{len(violations)} 处（{report['mode']} 档{tail}）：")
        for v in violations:
            print(f"  ✗ {v['file']}:{v['line']} · {v['kind']} · {v['snippet']}")
    else:
        print("[check_shell_segments] 通过：拼接型 shell 调用均已接分段治理（或本期无拼接型调用点）。")
    hitCount = len(violations)
    fpCount = round(VERIFIED_FALSE_POSITIVE_RATE * hitCount)
    print(f"[check_shell_segments] 误报率统计：人工核实误报 {fpCount} / 命中 {hitCount} "
          f"= {VERIFIED_FALSE_POSITIVE_RATE:.0%}（逐条核实口径见脚本 VERIFIED_FALSE_POSITIVE_RATE 注释）。")
    if args.strict and violations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
