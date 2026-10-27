# -*- coding: utf-8 -*-
r"""常驻棘轮：禁 `cd <路径> && …` 这种靠 shell 改目录的子进程调用形状（§6-196 批 39）。

成因（本仓两次实测撞到的同一根）：Windows 的 `cmd` 里 `cd D:\x` **不改盘符**，缺 `/d` 就停在
调用方所在盘上。于是 `os.system(f"cd {tmp} && git init")` 里的 `{tmp}` 若在另一块盘
（本机 C 盘临时目录 / E 盘仓库），命令其实跑在 **pytest 的 CWD＝仓库根**上。实测 stdout：
`Reinitialized existing Git repository in E:/…/.git/`——一次单元跑测在开发者仓库里
`git init`，紧接着两行 `git config user.*` 把仓库身份改写。同一条形状还让那条用例本身
一红一绿：仓库根是 git 仓库时它"成功"，换台布局不同的机器就红。

修法方向选在**生产该非法状态的调用形状**上（教义第 1 条）：目录由 `cwd=` 参数交给
`subprocess`，不经过 shell，也就没有盘符问题；而不是给判据放行、或把测试改成"容忍在仓库根
init"。

判定按 **AST 形态 + 用途**取，不钉词（本文件自己的 docstring 就带着那句形状，按文本
grep 会当场把自己判红——同族先例见形态集第 118 条）：
- 认 `os.system(...)` / `os.popen(...)`，以及带 `shell=True` 的 `subprocess.*` 入口；
- 命令串的**字面量片段拼合**后匹配 `cd <某路径> &&` 即判（f-string 与拼接形的路径常在中间，
  只取首段会静默放过——`f"cd {p} && git init"` 的字面量只剩 `"cd " + " && git init"`）；
- 反向钉住三种不该判的形态：参数列表形式（无 shell）、`shell=True` 但不是 cd 形状、
  注释与 docstring 里的文字。

基线口径：**空表**（零容忍）——建档时全仓实测命中两处（`tests/unit/skills/test_github_push_skill.py`
三行、`examples/github_push_demo.py` 三行），本批同批改净，不留存量表；日后长出一处即红。
扫描面另有地板断言钉住四个根都真的覆盖到文件（根写错或漏一个，守卫会"扫了个空却报绿"）。
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.ast_scan import filesUnder, parseSource  # noqa: E402

#: 扫描根。刻意含 `examples/`：建档时的两处命中之一就是那份演示脚本，
#: 只扫 `neurova/tests/scripts` 会把它静默漏掉。
SCAN_ROOTS = ("neurova", "scripts", "tests", "examples")

#: 经 shell 解释器执行字符串命令的入口（os.system/os.popen 恒走 shell；
#: subprocess 系列只在带 shell=True 时才算）
SHELL_ALWAYS = {"system", "popen", "startfile"}
SHELL_ENTRY_FUNCS = {"run", "Popen", "call", "check_call", "check_output",
                     "getoutput", "getstatusoutput"}
SHELL_PREFIX = re.compile(r"^\s*cd\s+[^&]*&&", re.DOTALL)

#: 建档时全仓实测命中点，本轮已同批改净 ⇒ 基线为空。只准保持为空。
BASELINE: dict[str, int] = {}


def _literalText(node: ast.AST) -> str:
    """把一条命令串里的**字面量片段**拼起来（变量段留空）。

    f-string 与拼接形的路径部分常在中间（`f"cd {p} && git init"` 的字面量只剩
    `"cd "` + `" && git init"`），只取首段会把这两种形静默放过——所以按整串拼合再判。
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else ""
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literalText(node.left) + _literalText(node.right)
    return ""


def _calleeKey(node: ast.Call) -> tuple[str, str]:
    """返回 (所属模块尾段, 函数名)，只认 `os.x(...)` / `subprocess.x(...)` 这种属性调用。"""
    fn = node.func
    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
        return fn.value.id, fn.attr
    return "", getattr(fn, "id", "") if isinstance(fn, ast.Name) else ""


def _goesThroughShell(node: ast.Call, module: str, func: str) -> bool:
    if module == "os" and func in SHELL_ALWAYS:
        return True
    if module == "subprocess" and func in SHELL_ENTRY_FUNCS:
        return any(k.arg == "shell" and isinstance(k.value, ast.Constant)
                   and k.value.value is True for k in node.keywords)
    return False


def shellCdHits(source: str, filename: str = "<str>") -> list[int]:
    """该份源码里 `cd <路径> &&` 形状的 shell 调用行号清单（口径唯一定义在此）。"""
    hits: list[int] = []
    try:
        tree = parseSource(source, filename=filename)
    except SyntaxError:
        return hits
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        module, func = _calleeKey(node)
        if not _goesThroughShell(node, module, func):
            continue
        first = node.args[0] if node.args else None
        if first is None:
            continue
        if SHELL_PREFIX.search(_literalText(first)):
            hits.append(node.lineno)
    return sorted(hits)


def _scanTree() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        for path in filesUnder(base):
            rel = path.relative_to(REPO_ROOT).as_posix()
            lines = shellCdHits(path.read_text(encoding="utf-8", errors="replace"), str(path))
            if lines:
                found[rel] = lines
    return found


def test_noCrossDriveShellCdShape():
    """零容忍：仓内不得再有靠 shell 改目录的调用形状。"""
    found = _scanTree()
    grown = {f: n for f, n in found.items() if n > BASELINE.get(f, 0)}
    vanished = {f: n for f, n in BASELINE.items() if f not in found or found[f] < n}
    assert not grown, (
        f"出现 `cd <路径> && …` 的 shell 调用形状 {grown}——Windows 跨盘符不改盘，"
        "命令实际跑在调用方 CWD 上（建档时实测就是在仓库根 git init + git config）。"
        "改法：把目录交给 subprocess 的 `cwd=` 参数，别经 shell。")
    assert not vanished, (
        f"基线站点被清零或减少 {vanished}——好事，但请同批把 BASELINE 收了，"
        "否则下一处冒出来会被旧基线吸收掉（只降不升要真降，得让降可见）。")


def test_scanRootsActuallyCoverTheTree():
    """地板：四个扫描根都必须真的各覆盖到源码文件。

    根写错一层（`parents[2]` 那类）时命中面会是空集，而空集对上空基线就是**假绿**。
    """
    counts = {r: len(filesUnder(REPO_ROOT / r)) for r in SCAN_ROOTS}
    assert all(n > 0 for n in counts.values()), f"扫描面缩水成 {counts}——守卫在判空气"
    assert counts["examples"] >= 1 and counts["tests"] > 500, f"扫描面异常 {counts}"
    demo = (REPO_ROOT / "examples" / "github_push_demo.py").as_posix().replace(
        f"{REPO_ROOT.as_posix()}/", "")
    assert demo in {p.relative_to(REPO_ROOT).as_posix()
                    for r in SCAN_ROOTS for p in filesUnder(REPO_ROOT / r)}, (
        f"{demo} 不在扫描面上——建档时的两处命中之一就是它，漏了这个根守卫对它失明")


@pytest.mark.parametrize("sample,expect", [
    pytest.param('import os\nos.system("cd some/dir && git init")\n', 1, id="os.system 常量形"),
    pytest.param('import os\np = 1\nos.system(f"cd {p} && git config user.name X")\n', 1,
                 id="f-string 首段形"),
    pytest.param('import subprocess\nsubprocess.run("cd d && ls", shell=True)\n', 1,
                 id="subprocess shell=True 形"),
    pytest.param('import subprocess\np = 1\nsubprocess.check_output("cd " + str(p) + " && ls",'
                 ' shell=True)\n', 1, id="字符串拼接最左形"),
    pytest.param('import subprocess\nsubprocess.run(["git", "init"], cwd="/tmp/x")\n', 0,
                 id="参数列表 + cwd= 不判"),
    pytest.param('import subprocess\nsubprocess.run("git status", shell=True)\n', 0,
                 id="shell=True 但非 cd 形状不判"),
    pytest.param('"""运行: cd Neurova && python -m x"""\n', 0, id="docstring 文字不判"),
    pytest.param('import os\nos.system("ls -la")\n', 0, id="无 cd 前缀不判"),
])
def test_detectorShapesAreTwoSided(sample: str, expect: int):
    """探测器必须两头都有牙：四种坏形都点名，四种好形都放行。

    反空转：只测放行侧的话，一个恒回空列表的实现也能全绿。
    """
    assert len(shellCdHits(sample)) == expect, shellCdHits(sample) or expect
