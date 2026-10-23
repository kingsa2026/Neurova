# -*- coding: utf-8 -*-
"""嵌套 pytest 的用例必须「父墙高于子墙」——否则一格超墙把整场跑测打死（§6-402 批 K 第二档）。

## 要防的那件事（同一机制，本批实测两次）

2026-10-22 夜 `pytest tests/unit` 在 **14%** 处消失、无汇总行、exit=1；2026-10-23 早同一命令
在 **44%** 处再次消失。两次凶手不同、机制同一条：`pyproject.toml` 只写了 `timeout = 30`，
**没有写 `timeout_method`**，而 pytest-timeout 在没有 `SIGALRM` 的平台上自动退回 **thread 法**；
thread 法打断不了正在执行的 Python 栈，它的处理是 dump 全部线程栈之后终止**整个进程**。
⇒ 在 Windows 开发机上，一格超时不是「这一格红」，是「整场连带打死」；Linux/CI 走 signal 法，
只红那一格、会话继续——这正是这道坎长期只在本地整批跑测时出现、而 CI 一直"看起来没事"的原因，
也是全仓预存红一直数不齐的根因之一。

第一处的根因是判据自己算得贵（幻影旋钮档，同批已修，见
`tests/unit/computer_use/test_computer_param_no_phantom_knobs.py` 的「成本形状」一节）。
第二处的根因是**预算的两层错配**：这些用例在子进程里再跑一遍 pytest，
`subprocess.run(..., timeout=T)` 给了子墙（实测 120–600s），却没给自己声明
`@pytest.mark.timeout(N)`，于是真正生效的上界是全局 30s——**子进程那条诚实的
`subprocess.TimeoutExpired` 红线永远轮不到说话**，报出来的却是"整场没了"。

## 不变量（判据只认代码形状，不认秒数也不认机器快慢）

一条被收集的用例，若其**同文件调用闭包**里有「用 subprocess 再跑一次 pytest」的落点：

1. 该落点必须有 `timeout=`（形参默认值那一形也算，如 `_runPytest(*args, timeout: int = 180)`）
   ——没有子墙的等待是无界的，父墙无从比较；
2. 用例必须带父墙：格上装饰器，或模块级 `pytestmark = pytest.mark.timeout(N)`；
3. **父墙 > 子墙**，相等也不行：两处同时到点就是掷骰子，输的一方是整场跑测。

存量已在本批归零 ⇒ 本闸自此零容忍：新增一条无预算（或预算错配）的嵌套 pytest 用例即红。

## 三条对照（本会话已在多处栽过"探测恒真/恒假"，判据自带对照是硬要求）

- **面自证**：本档必须报出「这次扫到几格真的在嵌套 pytest」，低于下限＝扫描根或收集口径写错，
  「零违规」与「没扫到」长得一模一样（同一形态见台账 §6-322 与形态 363）。
- **落点归账对照**：粗尺（不看调用图，只数函数体内的嵌套 subprocess-pytest 落点）读到的**落点
  集合**，必须与探测器归给用例的落点集合相等。落点被非用例函数独占、或 helper 挪出本文件时，
  粗尺会多于探测器——那正是本闸的失明面，当场点名，不静默放宽。
  （注意比的是**去重后的落点**，不是条数：一个 helper 服务 4 格用例是正常的，落点仍只有一处。）
- **合成样本对照**：四形违规（无父墙／父墙低于子墙／两墙相等／子进程无界）必须全被抓，
  合规样本与"跑 git 的 subprocess"必须不被抓。样本一律过 `ast.parse` 再喂探测器
  （形态 376：合成样本自己先要合法）。

判定只有 `_judgeTree` 一把尺：语料与合成样本走同一函数，避免"对照用的尺"与"判据用的尺"漂移。

## 边界（明写，不当已收口）

只认同文件闭包：`subprocess.run` 落在**别的模块**的 helper 里、由用例跨文件调用时，本闸认不到
——那需要跨模块调用图，代价与误判面都远大于收益。该缺口不是纸面上的：由上面那条落点归账对照
在**今天**读数相等来界定范围（现算：全部嵌套落点都在本文件内）。若将来出现跨文件 helper，
对照即红，届时按红的点名决定是补调用图还是把 helper 收回档内。
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tests import ast_scan

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_ROOT = REPO_ROOT / "tests"

#: 认「在子进程里跑 pytest」用的函数名（`subprocess.run/Popen/check_*`）。
_SPAWN_FUNCS = frozenset({"run", "Popen", "check_output", "check_call"})

#: 面自证下限：建档那轮现算 19 格嵌套 pytest 用例（其中 18 格违规、1 格合规），
#: 取一个「扫描根写窄就必然掉穿」的低线。
#: 不抄现值——只增不减的量写死就等于等着它讲假话。
_NESTING_FLOOR = 12

#: `tests/manual/` 不参与：该目录**不被收集**这件事由常驻判据
#: `tests/unit/test_manual_scripts_are_not_collectible.py` 钉着，本档不另立口径。
_NOT_COLLECTED_DIRS = ("manual",)


def _isCollectedTestName(name: str) -> bool:
    """与 `pyproject.toml` 的 `python_files=["test_*.py"]` ＋ `python_functions=["test_*","test[A-Z]*"]` 对齐。"""
    return name.startswith("test_") or (
        name.startswith("test") and len(name) > 4 and name[4].isupper())


def _secondsOf(node: ast.AST, table: Dict[str, ast.AST]) -> Optional[int]:
    """把 `120` / `NAME` / `NAME + 30` 这类常量表达式算成秒数；算不出给 None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name) and node.id in table:
        return _secondsOf(table[node.id], table)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        left = _secondsOf(node.left, table)
        right = _secondsOf(node.right, table)
        if left is None or right is None:
            return None
        return left + right if isinstance(node.op, ast.Add) else left - right
    return None


def _parentWall(node, table) -> Tuple[Optional[int], bool]:
    """用例（或模块）上声明的父墙，返回 (秒数或 None, 是否声明过)。

    声明过却读不出数值＝点名而不是放行：「写了装饰器但算不出数」正是需要人看一眼的形态，
    静默受理等于没闸。
    """
    if isinstance(node, ast.Module):
        for stmt in node.body:
            if not (isinstance(stmt, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets)):
                continue
            items = stmt.value.elts if isinstance(stmt.value, (ast.List, ast.Tuple)) else [stmt.value]
            for item in items:
                if (isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
                        and item.func.attr == "timeout" and item.args):
                    return _secondsOf(item.args[0], table), True
            return None, False
        return None, False
    for deco in node.decorator_list:
        if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute) and deco.func.attr == "timeout":
            if not deco.args:
                return None, True
            return _secondsOf(deco.args[0], table), True
    return None, False


def _defaultTimeout(fn, table) -> Optional[int]:
    """形参默认值里的 `timeout=`（helper 把子墙做成默认参的那一形）。"""
    a = fn.args
    positional = list(getattr(a, "posonlyargs", [])) + list(a.args)
    pairs = list(zip(reversed(positional), reversed(a.defaults or [])))
    pairs += list(zip(a.kwonlyargs, a.kw_defaults))
    for arg, default in pairs:
        if arg.arg == "timeout" and default is not None:
            return _secondsOf(default, table)
    return None


def _mentionsPytest(scope) -> bool:
    """作用域里出现字面量 `pytest`（可执行名或 `-m pytest` 的那一枚）。"""
    for node in ast.walk(scope):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.split("/")[-1] == "pytest":
                return True
    return False


def _spawnSites(fn, table) -> Set[Tuple[int, Optional[int]]]:
    """本函数体内的嵌套 subprocess-pytest 落点 {(行号, 子墙或 None)}。"""
    sites: Set[Tuple[int, Optional[int]]] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else "")
        if name not in _SPAWN_FUNCS:
            continue
        if not (_mentionsPytest(node) or _mentionsPytest(fn)):
            continue
        child = None
        for kw in node.keywords:
            if kw.arg == "timeout":
                child = _secondsOf(kw.value, table)
        if child is None:
            child = _defaultTimeout(fn, table)
        sites.add((node.lineno, child))
    return sites


def _calledNames(fn) -> Set[str]:
    out: Set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                out.add(func.id)
            elif isinstance(func, ast.Attribute):
                out.add(func.attr)
    return out


def _constants(tree) -> Dict[str, ast.AST]:
    table: Dict[str, ast.AST] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            table[stmt.targets[0].id] = stmt.value
    return table


def _functions(tree) -> Dict[str, ast.AST]:
    """本文件里所有具名函数（模块级与类内方法，按简单名索引）。"""
    out: Dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name not in out:
            out[node.name] = node
    return out


def _closureSites(fn, funcs, table) -> Set[Tuple[int, Optional[int]]]:
    """同文件一跳以内的调用闭包里的落点并集（`self._helper()`／`_helper()` 按简单名解析）。"""
    seen: Set[str] = {fn.name}
    queue: List[ast.AST] = [fn]
    sites: Set[Tuple[int, Optional[int]]] = set()
    while queue:
        current = queue.pop()
        sites |= _spawnSites(current, table)
        for callee in _calledNames(current):
            node = funcs.get(callee)
            if node is not None and callee not in seen:
                seen.add(callee)
                queue.append(node)
    return sites


def _judgeTree(tree: ast.AST, label: str):
    """一把尺跑到底：返回 (违规清单, 嵌套用例数, 粗尺落点集合, 归账落点集合)。"""
    table = _constants(tree)
    funcs = _functions(tree)
    moduleWall, moduleDeclared = _parentWall(tree, table)

    findings: List[str] = []
    nestingTests = 0
    attributed: Set[Tuple[str, int]] = set()
    for name, fn in sorted(funcs.items()):
        if not _isCollectedTestName(name):
            continue
        sites = _closureSites(fn, funcs, table)
        if not sites:
            continue
        nestingTests += 1
        ownWall, ownDeclared = _parentWall(fn, table)
        wall = ownWall if ownDeclared else moduleWall
        declared = ownDeclared or moduleDeclared
        for line, child in sorted(sites):
            attributed.add((label, line))
            if child is None:
                findings.append("%s:%d %s ⇒ 子进程无界等待（父墙=%s）" % (label, line, name, wall))
            elif not declared:
                findings.append("%s:%d %s ⇒ 无父墙（子墙=%ds，全局 30s 先到＝整场打死）"
                                % (label, line, name, child))
            elif wall is None:
                findings.append("%s:%d %s ⇒ 父墙写了但读不出数值（子墙=%ds）" % (label, line, name, child))
            elif wall <= child:
                findings.append("%s:%d %s ⇒ 父墙 %ds ≤ 子墙 %ds（到点竞速，输的是整场跑测）"
                                % (label, line, name, wall, child))

    coarse: Set[Tuple[str, int]] = set()
    for fnName, fn in funcs.items():
        for line, _child in _spawnSites(fn, table):
            coarse.add((label, line))
    return findings, nestingTests, coarse, attributed


def _relPath(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


@functools.lru_cache(maxsize=None)
def _scanCorpus():
    """一次性全扫（枚举走共享文本预算，解析走一次性入口，同会话两条判据共用一份读数）。

    入口选择照 `tests/unit/test_ci_ast_scan_budget_guard.py` 的规矩：本档只扫一次，
    故用 `sourceRefsUnder(hints=...)` ＋ `transientTree`，不用会把整片节点元组留在
    会话里的 `walkedModules`／`nodeScan`（保留的收益只在重复扫描时成立）。
    文本预筛是充分条件：认的落点是 `subprocess.run/Popen/check_*`，这些词一个都没
    出现的文件不可能命中。
    """
    findings: List[str] = []
    nestingTests = 0
    coarseAll: Set[Tuple[str, int]] = set()
    attributedAll: Set[Tuple[str, int]] = set()
    for ref in ast_scan.sourceRefsUnder(
            TESTS_ROOT, ".py",
            hints=("subprocess", "Popen", "check_output", "check_call")):
        path = ref.path
        if not path.name.startswith("test_"):
            continue
        if any(part in path.parts for part in _NOT_COLLECTED_DIRS):
            continue
        label = _relPath(path)
        fileFindings, fileNesting, fileCoarse, fileAttributed = _judgeTree(
            ast_scan.transientTree(path), label)
        findings.extend(fileFindings)
        nestingTests += fileNesting
        coarseAll |= fileCoarse
        attributedAll |= fileAttributed
    return (tuple(findings), nestingTests, frozenset(coarseAll), frozenset(attributedAll))


class TestNestedPytestBudgetWalls:

    def test_noCollectedNestingTestIsLeftToTheGlobalWall(self):
        """父墙必须严格高于子墙；无父墙的嵌套 pytest 用例一律点名。"""
        findings, nestingTests, _coarse, _attributed = _scanCorpus()
        assert not findings, (
            "这些用例在子进程里再跑一遍 pytest，自己的预算却没声明（或声明得比子进程还低）。"
            "Windows 侧 pytest-timeout 走 thread 法，超时即终止进程——一格超墙＝整场跑测没了：\n"
            + "\n".join(sorted(findings))
            + "\n（本轮扫到的嵌套 pytest 用例：%d 格）" % nestingTests
        )

    def test_scanFaceAndSiteAttributionAreNotVacuous(self):
        """面自证＋落点归账：这次真扫到了嵌套用例，且粗尺读到的每一处落点都被归过账。"""
        _findings, nestingTests, coarse, attributed = _scanCorpus()
        scannedFiles = len(ast_scan.sourceRefsUnder(TESTS_ROOT, ".py"))
        assert scannedFiles >= 1000, (
            "被收集测试语料现读 %d 个 .py——TESTS_ROOT 指错时零违规不作数" % scannedFiles)
        assert nestingTests >= _NESTING_FLOOR, (
            "只认到 %d 格嵌套 pytest 用例（下限 %d）——要么 TESTS_ROOT 指错，要么收集口径写窄了；"
            "此时上一条的『零违规』是假绿" % (nestingTests, _NESTING_FLOOR)
        )
        unattributed = sorted(coarse - attributed)
        assert not unattributed, (
            "粗尺读到、却没归给任何用例的嵌套落点：%s ⇒ 本闸在此失明（落点被非用例函数独占，"
            "或 helper 挪到了别的模块）。比的是去重后的落点，一个 helper 服务几格用例不算多算"
            % (unattributed,)
        )

    def test_detectorBitesAllFourBudgetShapesAndSparesTheCompliantOne(self):
        """合成样本正/负对照：违规四形全被抓，合规样本不被抓。"""
        cases = [
            ("import subprocess, sys\n"
             "def testNoMark():\n"
             "    subprocess.run([sys.executable, '-m', 'pytest', '-q'], timeout=120)\n",
             True, "无父墙"),
            ("import subprocess, sys, pytest\n"
             "@pytest.mark.timeout(60)\n"
             "def testLowParent():\n"
             "    subprocess.run([sys.executable, '-m', 'pytest', '-q'], timeout=120)\n",
             True, "父墙低于子墙"),
            ("import subprocess, sys, pytest\n"
             "@pytest.mark.timeout(120)\n"
             "def testEqualWalls():\n"
             "    subprocess.run([sys.executable, '-m', 'pytest', '-q'], timeout=120)\n",
             True, "两墙相等"),
            ("import subprocess, sys, pytest\n"
             "@pytest.mark.timeout(180)\n"
             "def testNoChildWall():\n"
             "    subprocess.run([sys.executable, '-m', 'pytest', '-q'])\n",
             True, "子进程无界等待"),
            ("import subprocess, sys, pytest\n"
             "def _helper():\n"
             "    subprocess.run([sys.executable, '-m', 'pytest', '-q'], timeout=120)\n"
             "@pytest.mark.timeout(180)\n"
             "def testViaHelper():\n"
             "    _helper()\n",
             False, "合规：父墙 180 > 子墙 120，且落点在 helper 里也认得到"),
        ]
        for index, (source, expectFinding, why) in enumerate(cases):
            tree = ast.parse(source)        # 合成样本自己先要合法（形态 376）
            label = "sample%d" % index
            findings, _nesting, coarse, attributed = _judgeTree(tree, label)
            assert (coarse - attributed) == set(), "样本 %s 落点未归账：%s" % (label, why)
            if expectFinding:
                assert findings, "探测器认不出「%s」这一形 ⇒ 主判据的绿是假的" % why
            else:
                assert not findings, "合规样本被判违规（%s）：%s" % (why, findings)

    def test_detectorDoesNotFlagNonPytestSubprocess(self):
        """负对照：跑 `git` 的 subprocess 不是嵌套 pytest，不该进账。"""
        source = ("import subprocess, pytest\n"
                  "def testShallNotBeFlagged():\n"
                  "    subprocess.run(['git', 'status'], timeout=5)\n")
        findings, nesting, _coarse, _attributed = _judgeTree(ast.parse(source), "sampleGit")
        assert not findings and nesting == 0
