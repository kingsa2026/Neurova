# -*- coding: utf-8 -*-
"""模块级重名定义＝被后一份静默遮蔽的死码（同功能双源的一种最隐蔽形态）。

来历：本仓在一次接缝重构里把 `isRealAgentTrajectoryExecutor` 写了两遍（旧那份读
`realAgentTrajectory` 旗标，新那份改结构推导）。**测试全绿**——因为后定义的覆盖了先定义的，
读到的行为恰好是想要的那个，而旧那份连同它的常量一起躺在文件里当"已经改过了"的证据。
同一次扫描还抓到 `llm/providers/multimodal_prober.py` 的 `_is_media_keyword_error`
（两版判定口径不同，先写的那版从不生效）。

判据一条：**同一模块内不得有两个同名顶层 def/class**。遮蔽只在"两份碰巧同义"时无害，
而没人知道它们是否同义——这正是双源该收口的理由（教义第 6/7 条）。
扫描面为空即红，防"路径写错→零文件→全绿"。
"""

import ast
import collections
import pathlib
import textwrap

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _shadowedDefinitions(root: pathlib.Path):
    """返回 [(文件, 名字, [行号...])]：模块体里出现两次以上的顶层 def/class。"""
    findings = []
    scanned = 0
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # 语法错误另有门禁，这里不重复报
            continue
        names = [node.name for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        counters = collections.Counter(names)
        for name, times in counters.items():
            if times > 1:
                lines = [node.lineno for node in tree.body
                         if getattr(node, "name", None) == name]
                findings.append((str(path.relative_to(root)), name, lines))
    return findings, scanned


def test_productionPackageHasNoShadowedTopLevelDefinitions():
    findings, scanned = _shadowedDefinitions(REPO_ROOT / "neurova")
    assert scanned > 500, f"扫描面异常收缩（只走了 {scanned} 个文件），这条判据现在不咬合"
    assert findings == [], f"模块级重名定义（先写的被后写的静默遮蔽）：{findings}"


def test_guardActuallyCatchesAShadowedDefinition(tmp_path):
    """反空转：造一个重名模块必须被抓到——扫描器坏掉时它会安静地什么都不报。"""
    (tmp_path / "dup.py").write_text(textwrap.dedent('''
        def helper(x):
            return x

        def helper(x):
            return x * 2
    '''), encoding="utf-8")

    findings, scanned = _shadowedDefinitions(tmp_path)
    assert scanned == 1
    assert findings and findings[0][0] == "dup.py" and findings[0][1] == "helper", findings


def test_classLevelMethodNamesAreNotFlagged(tmp_path):
    """不误伤：类内同名方法是正常形态，判据只管模块体。"""
    (tmp_path / "ok.py").write_text(textwrap.dedent('''
        class A:
            def run(self):
                return 1

        class B:
            def run(self):
                return 2

        def outer():
            def inner():
                return 3
            return inner()
    '''), encoding="utf-8")

    findings, scanned = _shadowedDefinitions(tmp_path)
    assert scanned == 1 and findings == [], findings
