# -*- coding: utf-8 -*-
r"""活体档的读数探针不许在 lambda 里引用 except 变量——那条 except 已经写过收尾动作了。

静态门实测（`python -m ruff check neurova tests`，F821）撞到的形状：

    try:
        LOCATOR = seed()
    except Exception as exc:                      # 这里已经写了 sys.exit(1) 收尾
        read("[0] 落根", lambda: (False, repr(exc)))
        sys.exit(1)

Python 3 在 `except` 块收尾时 `del exc`，所以那句 lambda **永远跑不到 exc**：真炸了就会变成
`NameError: name 'exc' is not defined` 盖住原始异常——报错说错了对象（形态集 243 同族）。
仓内既有写法是先把值绑定进普通变量再引用：`read(..., lambda exc=exc: ...)`。

同一片扫描面里还有另一种"打印半成品"的形态：`subprocess.run([sys.executable, "-c", PROBE, ...])`
引用了本模块从未绑定的 `PROBE`。判据同上——探针自己的名字得在本模块里绑得住。

覆盖边界：本判据按 AST 静态读，只看 `lambda` 参数之外的 `except … as <名>` 引用与模块级未绑定
名字（只覆盖探针常用的这两种）；跑起来才决定的错误路径仍要靠实跑证明，这里不冒充全量。
"""

from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

from tests import ast_scan

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MANUAL_DIR = REPO / "tests" / "manual"


def _lambdaEscapesHandler(tree: ast.AST) -> list:
    """`except … as 名` 块里的 lambda 引用了 名 却没用同名默认参数把它绑走。"""
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ExceptHandler) and node.name):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Lambda):
                continue
            defaults = {a.arg for a, d in zip(inner.args.args, inner.args.defaults)
                        if isinstance(d, ast.Name) and d.id == a.arg}
            used = {n.id for n in ast.walk(inner.body) if isinstance(n, ast.Name)
                    and isinstance(n.ctx, ast.Load)}
            if node.name in used and node.name not in defaults:
                hits.append(f"line {inner.lineno}: lambda 引用了 except 变量 {node.name}")
    return hits


def _moduleLevelBound(tree: ast.AST) -> set:
    """模块顶层绑定过的名字（含 import、赋值、函数/类定义、for、with、except as）。"""
    bound = set()

    def noteTargets(target):
        for n in ast.walk(target):
            if isinstance(n, ast.Name):
                bound.add(n.id)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                bound.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            if node.value is not None:
                for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                    noteTargets(t)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.With, ast.AsyncWith, ast.If,
                               ast.Try, ast.While)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    bound.add(sub.id)
                elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    bound.add(sub.name)
                elif isinstance(sub, ast.ExceptHandler) and sub.name:
                    bound.add(sub.name)
                elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for a in sub.names:
                        bound.add((a.asname or a.name).split(".")[0])
    return bound


def _liveScripts() -> list:
    refs = ast_scan.sourceRefsUnder(MANUAL_DIR, ".py")
    assert len(refs) > 100, (
        f"扫描面现读 {len(refs)} 个 .py（根＝tests/manual/）——根被改窄时「零命中」不代表干净")
    return [r for r in refs if not r.path.name.startswith("_")]


class TestProbesAreRunOnlyAfterTheyCanResolve:
    def testNoLambdaReachesIntoAFinishedExceptHandler(self):
        offenders = []
        for ref in _liveScripts():
            for hit in _lambdaEscapesHandler(ast.parse(ref.code)):
                offenders.append(f"{ref.path.name} {hit}")
        assert not offenders, (
            "读数 lambda 引用了 except 变量却没绑默认参数——真炸时 NameError 会盖住原始异常，"
            f"报错说错了对象：{offenders}")

    def testNoScriptRunsAProbeNameItNeverBinds(self):
        offenders = []
        for ref in _liveScripts():
            bound = _moduleLevelBound(ast.parse(ref.code)) | set(dir(builtins))
            # 函数内的局部绑定与参数也算"绑得住"：取全树 Store 名并集，只留真·从未出现过的名字
            everyName = {n.id for n in ast.walk(ast.parse(ref.code))
                         if isinstance(n, ast.Name)} | set(bound)
            used = {n.id for n in ast.walk(ast.parse(ref.code))
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
            for name in sorted(used - everyName):
                offenders.append(f"{ref.path.name}: {name}")
        assert not offenders, (
            f"脚本引用了自己从未绑定的名字（典型是把探针常量当成了已定义）：{offenders}")

    def testDetectorSeesBothShapes(self):
        """探测器自证（双向）：两种违规要认下来，既有合规写法不许被误报。"""
        broken = ("import sys\n"
                  "try:\n"
                  "    X = 1\n"
                  "except Exception as exc:\n"
                  "    read('x', lambda: (False, repr(exc)))\n"
                  "    sys.exit(1)\n")
        fixed = ("import sys\n"
                 "try:\n"
                 "    X = 1\n"
                 "except Exception as exc:\n"
                 "    read('x', lambda exc=exc: (False, repr(exc)))\n"
                 "    sys.exit(1)\n")
        assert _lambdaEscapesHandler(ast.parse(broken)), "违规写法没被咬到——那这格是橡皮章"
        assert not _lambdaEscapesHandler(ast.parse(fixed)), "合规写法被判成违规——零容忍格会误伤"
        probeMissing = "import subprocess, sys\nsubprocess.run([sys.executable, '-c', PROBE])\n"
        tree = ast.parse(probeMissing)
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "PROBE" in used and "PROBE" not in _moduleLevelBound(tree), (
            "未绑定名扫描没咬到 `-c PROBE` 这一形")
