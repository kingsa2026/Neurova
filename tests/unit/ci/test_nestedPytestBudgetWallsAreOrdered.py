# -*- coding: utf-8 -*-
"""被收集用例的「父墙必须严格高于子墙」——一格超墙会把整场跑测打死。

## 要防的那件事（同一机制，实测五次）

2026-10-22 夜 `pytest tests/unit` 在 **14%** 处消失、无汇总行、exit=1；2026-10-23 早同一命令在
**44%** 处再次消失；同日又在 **33%**／**72%** 两处各消失一次（§6-408）。底层是同一条：
`pyproject.toml` 只声明 `timeout = 30`，**仓内没有 `timeout_method` 这个键**——pytest-timeout
在没有 `SIGALRM` 的平台上自动退回 **thread 法**，而 thread 法打断不了正在执行的 Python 栈，
其处理是 dump 全部线程栈之后终止**整个进程**。
⇒ 在 Windows 开发机上，一格超时不是「这一格红」，是「整场连带打死、报告一起丢」；
Linux/CI 走 signal 法只红那一格、会话继续——这正是这道坎长期只在本地整批跑测时出现、
而 CI 一直"看起来没事"的原因，也是全仓预存红一直数不齐的根因之一。

第一处的根因是判据自己算得贵（同批已修，见
`tests/unit/computer_use/test_computer_param_no_phantom_knobs.py` 的「成本形状」一节）。
其余几处的根因是**预算的两层错配**：用例在子进程里再跑一遍 pytest、或真起解释器、或跑一趟
git，`subprocess.run(..., timeout=T)` 给了子墙（实测 60–900s），却没给自己声明
`@pytest.mark.timeout(N)`，于是真正生效的上界是全局 30s——**子进程那条诚实的
`subprocess.TimeoutExpired` 红线永远轮不到说话**，报出来的却是"整场没了"。

## 不变量（批 P-1 扩面后的口径；判据只认代码形状，不认秒数也不认机器快慢）

一条被收集的用例，若其**同文件调用闭包**（含它按参数名消费的 `@pytest.fixture`）内有
**阻塞式子进程等待**落点：

1. 落点必须有可读的 `timeout=`——`subprocess.run/check_output/check_call` 就地等结果，
   `timeout=` 缺席即无界；`subprocess.Popen` 本身不阻塞，它配的那次收尸
   （`handle.wait()`／`communicate()`／`asyncio.to_thread(handle.wait, timeout=…)`）
   没带 `timeout=` 才算无界；
2. 用例的父墙＝格上装饰器，或模块级 `pytestmark = pytest.mark.timeout(N)`；
   **没声明不等于没有墙**，那堵墙就是 `pyproject.toml` 里那道全局值（本档从活配置现读，
   不抄字面量——抄了就成第二个事实源）；
3. **父墙 > 子墙**，相等也不行：两处同时到点就是掷骰子，输的一方是整场跑测。

⇒ 扩面前后差别在"谁进账"：原来只认作用域里出现字面量 `pytest` 的落点，现在
   `subprocess.<四函数>` 的落点**无论跑的是 pytest、解释器探针还是 git 都进账**，
   于是「跑 git 且 `timeout=5`」这种原先根本不进账的形状也进了账——它**合规**
   （5s < 全局 30s，子进程先超时、报的是诚实的 `TimeoutExpired`），
   而「跑 git 且 `timeout=45`」当场红（45s > 全局 30s ⇒ 先到点的是全局那道）。
   反向形状（无 `timeout=`）无论跑什么都算无界等待，一律点名。

同名假阳是扩面必须先关住的口子：`asyncio.run(...)`（现算 28 处）、`engine.run(...)`（8 处）
都顶着 `run` 这个名字，却与子进程无关。故落点要求接收者**确实是 `subprocess` 模块绑定**
（`import subprocess as sp` 也认；`import subprocess` 写在函数体里同样算——本仓有那种
局部 import 的既有形制），裸名进账的前提是本文件写过 `from subprocess import <四函数>`。

存量已在本批归零 ⇒ 本闸自此零容忍：新增一条无预算（或预算错配）的有界等待用例即红。

## 三条对照（本会话已在多处栽过"探测恒真/恒假"，判据自带对照是硬要求）

- **面自证**：本档必须报出「这次扫到几格真有子进程等待」，低于下限＝扫描根或收集口径写错，
  「零违规」与「没扫到」长得一模一样（同一形态见台账 §6-322 与形态 363）。
- **落点归账对照**：粗尺（不看调用图，只数本文件每个函数体内的落点）读到的**落点集合**，
  必须与探测器归给用例的落点集合相等。落点被既非用例也非 fixture 的函数独占时，粗尺会多于
  探测器——那正是本闸的失明面，当场点名，不静默放宽。
  （注意比的是**去重后的落点**，不是条数：一个 helper 服务 4 格用例是正常的，落点仍只有一处。）
- **合成样本对照**：违规各形（无父墙／父墙低于子墙／两墙相等／子进程无界／非 pytest 的子墙
  超全局／fixture 体无界／Popen 无界收尸）必须全被抓，合规样本（helper 派生父墙／短预算 git／
  Popen 配有界收尸／子墙取自外部常量但本格已声明父墙）必须不被抓。样本一律过 `ast.parse`
  再喂探测器（形态 376：合成样本自己先要合法）。

判定只有 `_judgeTree` 一把尺：语料与合成样本走同一函数，避免"对照用的尺"与"判据用的尺"漂移。

## 边界（明写，不当已收口）

- **只认同文件闭包**：`subprocess.run` 落在**别的模块**的 helper 里、由用例跨文件调用时，
  本闸认不到——那需要跨模块调用图，代价与误判面都远大于收益。该缺口不是纸面上的：由落点归账
  对照在**今天**读数相等来界定范围。若将来出现跨文件 helper，对照即红，届时按红的点名决定
  是补调用图还是把 helper 收回档内。
- **词汇只有 subprocess**：HTTP 轮询、`asyncio.Event.wait()`、`time.sleep()` 都不在本闸词汇内
  （§6-408 那处 72% 的 `asyncio` 空等就是这条边界的现形——它由
  `tests/unit/neurflow/test_approval_reply_mechanism.py` 的
  `TestApprovalWaitBudgetStaysUnderTheWall` 单独钉住，不是本闸的职责）。
  一个格子里既有 subprocess 又有 90s 轮询时，本闸只对它声明的子进程预算说话。
- **子墙写成外部导入常量时数值读不出**（如 `timeout=KILL_GRACE_S`，常量在生产侧）：
  本闸此时只要求该格**显式声明父墙**，不做数值比较。这是存在性检查，不是放行——
  没声明照样红；要它可比，得把那个常量搬进本档可解析的模块级赋值，而那是「新造第二份尺度」，
  不为此改生产侧单源。
"""

from __future__ import annotations

import ast
import functools
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tests import ast_scan

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_ROOT = REPO_ROOT / "tests"
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: 认「在子进程里跑东西」用的四个函数名（真落点还须以 subprocess 绑定为接收者）。
_SPAWN_FUNCS = frozenset({"run", "Popen", "check_output", "check_call"})
#: 自己就地等结果的三种。`Popen` 立刻返回，它的阻塞点在配对的那次收尸上。
_BLOCKING_SPAWN_FUNCS = frozenset({"run", "check_output", "check_call"})
#: 子进程句柄上真正会卡住的两个动作。
_REAP_FUNCS = frozenset({"wait", "communicate"})

#: 面自证下限。**扩面那轮（清存量前）现算：158 条违规／50 档／165 格真有子进程等待／
#: 95 个去重落点／候选 `test_` 档 113 个**。验尺锚点：同一棵树上 HEAD 版在册闸现读
#: **19 格嵌套 pytest／0 违规**（§6-402 的在册读数逐字复现）；本档把落点谓词收回
#: "作用域里出现字面量 pytest" 后读回 **21 格／0 违规**——多出的 2 格来自本档新增的
#: fixture 归账与类级父墙读取，不是语料漂移。测量尺与常驻尺同源才敢报数
#: （§6-408 批 P-1 票面的验尺步骤）。
#: 清完存量后格数不变（165），违规归零。下限取一条「扫描根写窄就必然掉穿」的低线，
#: 不抄现值：只增不减的量写死就等于等着它讲假话。
_WALL_FACE_FLOOR = 60

#: `tests/manual/` 不参与：该目录**不被收集**这件事由常驻判据
#: `tests/unit/test_manual_scripts_are_not_collectible.py` 钉着，本档不另立口径。
_NOT_COLLECTED_DIRS = ("manual",)

#: 落点条目 `(行号, 子墙秒数或 None, 是否"写了却读不出", 是否嵌套 pytest)`。
#: 三个状态分清楚才不谎报：没写 `timeout=`（无界）与写了但数值算不出来（不可读）
#: 是两件不同的事，处置也不同——后者只欠一次显式父墙声明。
Site = Tuple[int, Optional[int], bool, bool]


def _isCollectedTestName(name: str) -> bool:
    """与 `pyproject.toml` 的 `python_files=["test_*.py"]` ＋ `python_functions=["test_*","test[A-Z]*"]` 对齐。"""
    return name.startswith("test_") or (
        name.startswith("test") and len(name) > 4 and name[4].isupper())


@functools.lru_cache(maxsize=1)
def _globalWallSeconds() -> Optional[int]:
    """从 `pyproject.toml` 的活配置现读全局墙＝缺省父墙。

    抄一份字面量 `30` 进判据，就等于给同一件事第二份定义：那行配置改了而判据照旧，
    报出来的"合规"讲的是假话（教义第 6 条）。只认 `[tool.pytest.ini_options]` 段内的
    `timeout =`，切到下一个 `[表]` 为止——别处的同名词条不作数。
    """
    text = PYPROJECT.read_text(encoding="utf-8", errors="replace")
    marker = "[tool.pytest.ini_options]"
    _head, sep, tail = text.partition(marker)
    if not sep:
        return None
    lines: List[str] = []
    for line in tail.splitlines():
        if line.lstrip().startswith("["):
            break       # 下一个 [表] 为止：别处的同名词条不作数
        lines.append(line)
    match = re.search(r"^[ \t]*timeout[ \t]*=[ \t]*(\d+)", "\n".join(lines), re.M)
    return int(match.group(1)) if match else None


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
    """用例（或类／模块）上声明的父墙，返回 (秒数或 None, 是否声明过)。

    声明过却读不出数值＝点名而不是放行：「写了装饰器但算不出数」正是需要人看一眼的形态，
    静默受理等于没闸。
    """
    if isinstance(node, (ast.Module, ast.ClassDef)):
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


def _classWallChains(tree) -> Dict[str, List[ast.AST]]:
    """每个具名函数的外层作用域链（由内到外的类，末尾接模块）。

    类级 `pytestmark` 是真会生效的父墙（pytest 把它套到类内每一格），早先只认模块级与
    格上装饰器，于是 `TestNegativeControls` 那类"类上放宽"的形状被整类误判成无父墙——
    判据报错方向的错也是错。
    """
    chains: Dict[str, List[ast.AST]] = {}

    def visit(node, stack):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, [child] + stack)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chains.setdefault(child.name, list(stack) + [tree])
                visit(child, stack)
            else:
                visit(child, stack)

    visit(tree, [])
    return chains


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
    """作用域里出现字面量 `pytest`（可执行名或 `-m pytest` 的那一枚）——现在只供措辞分类。"""
    for node in ast.walk(scope):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.split("/")[-1] == "pytest":
                return True
    return False


def _callName(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _subprocessBindings(tree) -> Tuple[Set[str], Set[str]]:
    """(本文件里 subprocess 的模块绑定名, `from subprocess import run` 这类裸名)。

    扩面的第一道精确化：`asyncio.run(...)`、`engine.run(...)` 都顶着 `run` 这个名字，
    却不是子进程等待。只认「接收者确实是 subprocess 绑定」的落点，裸名进账的前提是
    本文件真的写过 `from subprocess import <四函数>`。
    """
    modules: Set[str] = set()
    bare: Set[str] = set()
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.name == "subprocess":
                    modules.add(alias.asname or "subprocess")
        elif isinstance(stmt, ast.ImportFrom) and (stmt.module or "") == "subprocess":
            for alias in stmt.names:
                if alias.name in _SPAWN_FUNCS:
                    bare.add(alias.asname or alias.name)
    return modules, bare


def _handleNames(fn) -> Set[str]:
    """本函数里"看着就是 Popen 句柄"的名字：由 Popen 赋值得来，或形参标注 `subprocess.Popen`。"""
    names: Set[str] = set()
    a = fn.args
    for arg in list(getattr(a, "posonlyargs", [])) + list(a.args) + list(a.kwonlyargs):
        if arg.annotation is not None and "Popen" in ast.dump(arg.annotation):
            names.add(arg.arg)
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                and _callName(node.value) == "Popen":
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _timeoutArg(node: ast.Call, table) -> Tuple[Optional[int], bool]:
    """(该调用上 `timeout=` 算出的秒数, 是否写了 `timeout=`)。"""
    for kw in node.keywords:
        if kw.arg == "timeout":
            return _secondsOf(kw.value, table), True
    return None, False


def _receiverIsHandle(node: ast.Call, handles: Set[str], attrs: Set[str]) -> bool:
    func = node.func
    return (isinstance(func, ast.Attribute) and func.attr in attrs
            and isinstance(func.value, ast.Name) and func.value.id in handles)


def _spawnSites(fn, table, bindings) -> Set[Site]:
    """本函数体内的阻塞式子进程等待落点。"""
    modules, bare = bindings
    handles = _handleNames(fn)
    pytestKind = _mentionsPytest(fn)
    sites: Set[Site] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        name = _callName(node)
        func = node.func
        if name in _BLOCKING_SPAWN_FUNCS and (
                (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                 and func.value.id in modules)
                or (isinstance(func, ast.Name) and func.id in bare)):
            child, written = _timeoutArg(node, table)
            if child is None:
                #: `timeout=timeout` 那一形——helper 把子墙做成自己的形参默认值，
                #: 站点上写了 `timeout=` 却指向那个参数。数在默认值里，不是读不出。
                child = _defaultTimeout(fn, table)
            sites.add((node.lineno, child, written and child is None, pytestKind))
        elif name == "Popen":
            continue        # 起进程不阻塞；把账记在它配的那次收尸上
        elif name in _REAP_FUNCS and _receiverIsHandle(node, handles, _REAP_FUNCS):
            child, written = _timeoutArg(node, table)
            sites.add((node.lineno, child, written and child is None, pytestKind))
        elif name == "to_thread" and node.args and isinstance(node.args[0], ast.Attribute) \
                and node.args[0].attr in _REAP_FUNCS \
                and isinstance(node.args[0].value, ast.Name) \
                and node.args[0].value.id in handles:
            child, written = _timeoutArg(node, table)
            sites.add((node.lineno, child, written and child is None, pytestKind))
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


def _fixtureBodies(tree) -> Set[str]:
    """本文件里 `@pytest.fixture` 过的函数名——pytest 按**参数名**注入，调用图上没有这一跳。"""
    out: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            inner = deco.func if isinstance(deco, ast.Call) else deco
            if isinstance(inner, ast.Attribute) and inner.attr == "fixture":
                out.add(node.name)
            elif isinstance(inner, ast.Name) and inner.id == "fixture":
                out.add(node.name)
    return out


def _consumedFixtures(fn, fixtures: Set[str]) -> Set[str]:
    args = list(getattr(fn.args, "posonlyargs", [])) + list(fn.args.args) + list(fn.args.kwonlyargs)
    return {a.arg for a in args if a.arg in fixtures}


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


def _closureSites(fn, funcs, table, bindings, fixtures) -> Set[Site]:
    """同文件一跳以内的调用闭包里的落点并集（`self._helper()`／`_helper()`／fixture 参数名）。"""
    seen: Set[str] = {fn.name}
    queue: List[ast.AST] = [fn]
    sites: Set[Site] = set()
    while queue:
        current = queue.pop()
        sites |= _spawnSites(current, table, bindings)
        callees = _calledNames(current) | _consumedFixtures(current, fixtures)
        for callee in callees:
            node = funcs.get(callee)
            if node is not None and callee not in seen:
                seen.add(callee)
                queue.append(node)
    return sites


def _siteKindTag(pytestKind: bool) -> str:
    return "嵌套 pytest" if pytestKind else "子进程等待"


def _effectiveWall(fn, table, chains, moduleWall, moduleDeclared) -> Tuple[Optional[int], bool]:
    """格上装饰器 → 类级 `pytestmark` → 模块级 `pytestmark`，取第一处**声明过**的父墙。"""
    ownWall, ownDeclared = _parentWall(fn, table)
    if ownDeclared:
        return ownWall, True
    for scope in chains.get(fn.name, []):
        if isinstance(scope, ast.ClassDef):
            classWall, classDeclared = _parentWall(scope, table)
            if classDeclared:
                return classWall, True
    return moduleWall, moduleDeclared


def _judgeTree(tree: ast.AST, label: str):
    """一把尺跑到底：返回 (违规清单, 有界等待用例数, 粗尺落点集合, 归账落点集合)。"""
    table = _constants(tree)
    funcs = _functions(tree)
    bindings = _subprocessBindings(tree)
    fixtures = _fixtureBodies(tree)
    chains = _classWallChains(tree)
    globalWall = _globalWallSeconds()
    moduleWall, moduleDeclared = _parentWall(tree, table)

    findings: List[str] = []
    budgetTests = 0
    attributed: Set[Tuple[str, int]] = set()
    for name, fn in sorted(funcs.items()):
        if not _isCollectedTestName(name):
            continue
        sites = _closureSites(fn, funcs, table, bindings, fixtures)
        if not sites:
            continue
        budgetTests += 1
        wall, declared = _effectiveWall(fn, table, chains, moduleWall, moduleDeclared)
        for line, child, unreadable, pytestKind in sorted(sites, key=lambda s: (s[0], s[1] if s[1] is not None else -1)):
            attributed.add((label, line))
            kind = _siteKindTag(pytestKind)
            if unreadable:
                if not declared:
                    findings.append("%s:%d %s ⇒ %s的子墙写了却读不出数值（如外部导入常量），"
                                    "本格又无显式父墙——全局 %ss 先到＝整场打死"
                                    % (label, line, name, kind, globalWall))
            elif child is None:
                findings.append("%s:%d %s ⇒ %s无界等待（父墙=%s）"
                                % (label, line, name, kind, wall))
            elif not declared:
                if globalWall is None or globalWall <= child:
                    findings.append("%s:%d %s ⇒ 无父墙（%s子墙=%ds ≥ 全局 %ss，全局先到＝整场打死）"
                                    % (label, line, name, kind, child, globalWall))
            elif wall is None:
                findings.append("%s:%d %s ⇒ 父墙写了但读不出数值（%s子墙=%ds）"
                                % (label, line, name, kind, child))
            elif wall <= child:
                findings.append("%s:%d %s ⇒ 父墙 %ds ≤ %s子墙 %ds（到点竞速，输的是整场跑测）"
                                % (label, line, name, wall, kind, child))

    coarse: Set[Tuple[str, int]] = set()
    for fnName, fn in funcs.items():
        for site in _spawnSites(fn, table, bindings):
            coarse.add((label, site[0]))
    return findings, budgetTests, coarse, attributed


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
    文本预筛是充分条件：认的落点以 `subprocess` 绑定为接收者，这个词都没出现的
    文件不可能命中（`from subprocess import run` 同样带着 `subprocess` 这个词）。
    """
    findings: List[str] = []
    budgetTests = 0
    coarseAll: Set[Tuple[str, int]] = set()
    attributedAll: Set[Tuple[str, int]] = set()
    # 面自证落**枚举**那一趟，不落预筛结果：预筛命中的文件数随判据词表变，量不出"根被改窄"。
    # 根是 `TESTS_ROOT`（模块级常量），`filesUnder` 只枚举不解析，成本与文件数线性。
    enumerated = ast_scan.filesUnder(TESTS_ROOT, ".py")
    assert len(enumerated) > 50, (
        f"扫描面现读 {len(enumerated)} 个 .py（根＝{TESTS_ROOT}）——根被改窄或指错了，"
        "『没有嵌套用例漏给自己的预算』这句话不来自代码")
    for path in enumerated:
        if not path.name.startswith("test_"):
            continue
        if any(part in path.parts for part in _NOT_COLLECTED_DIRS):
            continue
        if not any(hint in ast_scan.sourceCode(path)
                   for hint in ("subprocess", "Popen", "check_output", "check_call")):
            continue
        label = _relPath(path)
        fileFindings, fileBudget, fileCoarse, fileAttributed = _judgeTree(
            ast_scan.transientTree(path), label)
        findings.extend(fileFindings)
        budgetTests += fileBudget
        coarseAll |= fileCoarse
        attributedAll |= fileAttributed
    return (tuple(findings), budgetTests, frozenset(coarseAll), frozenset(attributedAll))


class TestNestedPytestBudgetWalls:

    def test_noCollectedCaseOutlivesItsOwnWall(self):
        """父墙必须严格高于子墙；把全局墙当父墙的嵌套 pytest 用例一律点名。"""
        findings, budgetTests, _coarse, _attributed = _scanCorpus()
        assert not findings, (
            "这些用例在子进程里等一件事，自己的预算却没声明（或声明得比子进程还低）。"
            "Windows 侧 pytest-timeout 走 thread 法，超时即终止进程——一格超墙＝整场跑测没了：\n"
            + "\n".join(sorted(findings))
            + "\n（本轮扫到的有界等待用例：%d 格）" % budgetTests
        )

    def test_scanFaceAndSiteAttributionAreNotVacuous(self):
        """面自证＋落点归账：这次真扫到了带子进程等待的用例，且粗尺读到的每一处落点都被归过账。"""
        _findings, budgetTests, coarse, attributed = _scanCorpus()
        scannedFiles = len(ast_scan.sourceRefsUnder(TESTS_ROOT, ".py"))
        assert scannedFiles >= 1000, (
            "被收集测试语料现读 %d 个 .py——TESTS_ROOT 指错时零违规不作数" % scannedFiles)
        assert _globalWallSeconds() is not None, (
            "没能从 pyproject 读到全局墙——缺省父墙此刻无从判定，『合规』是假绿")
        assert budgetTests >= _WALL_FACE_FLOOR, (
            "只认到 %d 格有界等待用例（下限 %d）——要么 TESTS_ROOT 指错，要么收集口径写窄了；"
            "此时上一条的『零违规』是假绿" % (budgetTests, _WALL_FACE_FLOOR)
        )
        unattributed = sorted(coarse - attributed)
        assert not unattributed, (
            "粗尺读到、却没归给任何用例的子进程落点：%s ⇒ 本闸在此失明（落点被既非用例也非 "
            "fixture 的函数独占，或 helper 挪到了别的模块）。比的是去重后的落点，一个 helper "
            "服务几格用例不算多算" % (unattributed,)
        )

    def test_detectorBitesAllBudgetShapesAndSparesTheCompliantOnes(self):
        """合成样本正/负对照：违规各形全被抓，合规样本不被抓。

        样本里的秒数凡与全局墙有关者都从 `_globalWallSeconds()` 现算导出——写死
        「45 > 30」那种期望，等 pyproject 改了值就变成判据自己在说谎。
        """
        globalWall = _globalWallSeconds() or 30
        above = globalWall + 15
        below = max(1, globalWall - 25)
        cases = [
            ("import subprocess, sys\n"
             "def testNoMark():\n"
             "    subprocess.run([sys.executable, '-m', 'pytest', '-q'], timeout=120)\n",
             True, "无父墙（嵌套 pytest 子墙 120）"),
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
            ("import subprocess\n"
             "def testShortGit():\n"
             "    subprocess.run(['git', 'status'], timeout=%d)\n" % below,
             False, "合规（扩面新增）：跑 git 且子墙 %ds < 全局 %ds，子进程先超时＝诚实红线"
                    % (below, globalWall)),
            ("import subprocess\n"
             "def testLongGit():\n"
             "    subprocess.run(['git', 'status'], timeout=%d)\n" % above,
             True, "违规（扩面新增）：非 pytest 的子墙 %ds 超全局 %ds，扩面前这条根本不进账"
                   % (above, globalWall)),
            ("import subprocess, pytest\n"
             "@pytest.fixture\n"
             "def repo():\n"
             "    subprocess.run(['git', 'init'], timeout=120)\n"
             "def testUsesFixture(repo):\n"
             "    assert repo\n",
             True, "fixture 体的落点必须归账给消费它的用例（否则 120s 的等待挂在 30s 全局墙上）"),
            ("import subprocess\n"
             "def testDetachedSpawn():\n"
             "    proc = subprocess.Popen(['git', 'status'])\n"
             "    proc.wait()\n",
             True, "Popen 起进程不阻塞，但无 `timeout=` 的收尸是无限等待"),
            ("import subprocess, pytest\n"
             "def testReapedWithUnknownWall():\n"
             "    proc = subprocess.Popen(['git', 'status'])\n"
             "    proc.wait(timeout=KILL_GRACE_S)\n",
             True, "子墙取自外部常量且本格无显式父墙⇒ 照样点名（存在性检查，不是放行）"),
            ("import subprocess, pytest\n"
             "class TestGroup:\n"
             "    pytestmark = pytest.mark.timeout(120)\n"
             "    def testInClassWithClassMark(self):\n"
             "        subprocess.run(['git', 'status'], timeout=60)\n",
             False, "合规：类级 pytestmark 120 > 子墙 60（漏读类级墙会把整类误判成无父墙）"),
            ("import subprocess, pytest\n"
             "class TestGroup:\n"
             "    pytestmark = pytest.mark.timeout(60)\n"
             "    def testInClassWithThinMark(self):\n"
             "        subprocess.run(['git', 'status'], timeout=90)\n",
             True, "违规：类级 pytestmark 60 ≤ 子墙 90——类级墙同样要一比大小"),
            ("import subprocess, pytest\n"
             "@pytest.mark.timeout(90)\n"
             "def testReapedWithUnknownWallButOwnMark():\n"
             "    proc = subprocess.Popen(['git', 'status'])\n"
             "    proc.wait(timeout=KILL_GRACE_S)\n",
             False, "合规：子墙数值读不出，但该格显式声明了父墙，不再靠全局墙兜底"),
        ]
        for index, (source, expectFinding, why) in enumerate(cases):
            tree = ast.parse(source)        # 合成样本自己先要合法（形态 376）
            label = "sample%d" % index
            findings, _budget, coarse, attributed = _judgeTree(tree, label)
            assert (coarse - attributed) == set(), "样本 %s 落点未归账：%s" % (label, why)
            if expectFinding:
                assert findings, "探测器认不出「%s」这一形 ⇒ 主判据的绿是假的" % why
            else:
                assert not findings, "合规样本被判违规（%s）：%s" % (why, findings)

    def test_namesakeCallsOutsideSubprocessAreNotCounted(self):
        """反向控制：`asyncio.run`／`engine.run` 顶着同一个名字，却不是子进程等待。"""
        source = ("import asyncio\n"
                  "async def _coro():\n"
                  "    return 1\n"
                  "def testNamesakeRuns():\n"
                  "    asyncio.run(_coro())\n"
                  "    engine.run(timeout=900)\n")
        findings, budget, _coarse, _attributed = _judgeTree(ast.parse(source), "sampleNamesake")
        assert not findings and budget == 0, (
            "同名假阳进账了（现数 %d 格／%d 条）——扩面必须先关住这一口，"
            "否则全仓 28 处 asyncio.run 会把『违规』淹成噪声" % (budget, len(findings)))
