# -*- coding: utf-8 -*-
"""亚毫秒 CPU 自旋在粗粒度线程时钟上必须整格跳过，且不得绕过唯一基元（§6-96）。

根因（不是"Windows 慢"）：`tests/performance/test_perf_gate_contract.py` 的自证格形如
`deadline = time.thread_time() + x; while time.thread_time() < deadline: pass`。
本机（Windows 10.0.26200）实测该时钟的**推进粒度是 15.625ms**，而 `x` 取 0.1ms 一档 ⇒
"一次自旋"的物理成本是一个量子而非 0.1ms；它被生产循环调 2000 次 × 门禁的 5 轮 ⇒ ≈156s。
修复前实测红灯：

    .venv/Scripts/python.exe -m pytest "…::TestJudgingIgnoresMachineLoad::
    test_real_cpu_regression_in_step_metric_is_still_caught" -q --timeout=60
    ⇒ +++++++++++++++++++++++++++++++++++ Timeout +++++++++++++++++++++++++++++++++++  (63s)

该文件在受保护子集里（`scripts/ci/protected_tests.txt`），于是本机跑子集必被它在默认
`timeout=30` 处打断——整场性能门禁不可复跑，而 CI/Linux 侧粒度亚微秒、不受影响。

**为什么按实测粒度判、不按平台名判**：平台名两头都失真——不是每台 Windows 都粗，
也不是只有 Windows 会粗（低频 tick / 被限流的 Linux 容器同样粗）。按平台名判会在
粗粒度 Linux 上继续超时、在细粒度 Windows 上白白丢覆盖，所以本守卫把"不得以平台名为
条件"也钉成一条（`test_theGateIsKeyedOnGranularityNotOnPlatformName`）。

**为什么不信 `time.get_clock_info(...)` 的 resolution**：本机它宣称 `1e-07` 秒（0.0001ms），
实测 15.625ms —— 差五个数量级。拿宣称值判"这台机器分得出 0.1ms"，等于把要防的形态
原样放行，而且报出来的还是绿。

与其它三份时钟判据的分工（本守卫不重复它们）：
- `test_ci_wallclock_assertion_ledger.py` 管「量耗时的**上界**是否绑了墙钟」；
- `test_clock_caliber_ledger.py` 管「进程内计时的**口径**逐条有无结论」；
- `test_count_bounded_wait_ledger.py` 管「条件等待以什么为**界**」；
- **本守卫管「自旋目标与时钟粒度的关系」**——"要求机器烧 0.1ms CPU"这件事本身在某台
  机器上是否成立。上面三份看的都是"选了哪个时钟、界取在哪"，没有一份看"这台机器的
  时钟分不分得出这个目标"，故对本形态是空集。
"""

from __future__ import annotations

import ast
import importlib.util
import io
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = REPO_ROOT / "tests" / "performance" / "test_perf_gate_contract.py"

#: 唯一自旋基元与粒度探针：`thread_time` 自旋循环只许活在这两个函数里。
SPIN_PRIMITIVE = "spinThreadCpu"
GRANULARITY_PRIMITIVES = ("threadTimeQuantumMs", SPIN_PRIMITIVE)

#: 本守卫认的那道旗标名（契约文件里的 skipif 标记）。
GATE_NAME = "needsFineThreadClock"

#: 只注入**等待**的格（`_injectLoad` 的 `cpu_ms` 默认 0.0，走 `if cpu_ms:` 的假分支，
#: 一次 CPU 都不烧）——它正是"等待不进判分"这条主契约本身，本机也必须跑，
#: 不得被量子门一并带走。
SLEEP_ONLY_CELLS: Set[str] = {
    "TestJudgedValueIsLoadIndependent::test_judged_value_does_not_inflate_under_injected_waiting",
}


def _source() -> str:
    assert CONTRACT.is_file(), f"契约文件不存在：{CONTRACT}——被检对象消失，本守卫会空转"
    source = io.open(CONTRACT, encoding="utf-8").read()
    assert source.strip(), "契约文件为空——被检对象消失，本守卫会空转"
    return source


def _parse(source: str) -> ast.Module:
    tree = ast.parse(source)
    assert tree.body, "解析出零个顶层节点——扫描面为空，本守卫会空转"
    return tree


def _parents(tree: ast.AST) -> Dict[ast.AST, ast.AST]:
    parents: Dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _functions(tree: ast.AST) -> List[ast.AST]:
    return [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _qualName(node: ast.AST, parents: Dict[ast.AST, ast.AST]) -> str:
    """用例格的稳定称呼：`类::方法`（模块级函数只有名字，嵌套函数带全链）。"""
    parts: List[str] = []
    cur = node
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            parts.append(cur.name)
        cur = parents.get(cur)
    return "::".join(reversed(parts))


def _isThreadTimeCall(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "thread_time")


def _callsByName(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == name
        for c in ast.walk(node)
    )


def spinLoops(source: str) -> List[str]:
    """所有"以 `thread_time()` 读数为条件的 while 自旋"所在函数（qualname 列表）。

    做成模块级公开函数：反向控制要用合成样本喂它，先证明检出器不是空转再谈结论。
    """
    tree = _parse(source)
    parents = _parents(tree)
    hits: List[str] = []
    for loop in ast.walk(tree):
        if not isinstance(loop, ast.While):
            continue
        if not any(_isThreadTimeCall(c) for c in ast.walk(loop.test)):
            continue
        holder = parents.get(loop)
        while holder is not None and not isinstance(
            holder, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            holder = parents.get(holder)
        hits.append(_qualName(holder, parents) if holder else "<module>")
    return hits


def _spinsInside(fn: ast.AST) -> bool:
    """该函数体内（含嵌套钩子）是否真的存在 `thread_time` 自旋循环或基元调用。

    两种形态都算，是为了让这个判据**在重构前后都成立**：重构前自旋是内联的，
    只认基元调用会让检出器在红灯阶段数到空集，于是本守卫的红会报成"我没检出东西"
    而不是"这些格跑到超时"——后者才是要钉的那个行为。
    """
    if _callsByName(fn, SPIN_PRIMITIVE):
        return True
    for loop in ast.walk(fn):
        if isinstance(loop, ast.While) and any(
            _isThreadTimeCall(c) for c in ast.walk(loop.test)
        ):
            return True
    return False


def spinReachingCells(source: str) -> Set[str]:
    """（含间接）会走到 CPU 自旋的用例格集合。

    间接是必须的：`_injectLoad` 里的钩子烧 CPU，而调用它的用例在**另一个类**里——
    只看用例函数体自身就会漏掉那一格，而"漏一格"正是本次要防的复发形态。
    """
    tree = _parse(source)
    parents = _parents(tree)
    fns = _functions(tree)
    byName: Dict[str, List[ast.AST]] = {}
    for fn in fns:
        byName.setdefault(fn.name, []).append(fn)

    reaching: Set[int] = {id(fn) for fn in fns if _spinsInside(fn)}
    changed = True
    while changed:
        changed = False
        for fn in fns:
            if id(fn) in reaching:
                continue
            called = {
                c.func.id for c in ast.walk(fn)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            }
            if any(id(g) in reaching for name in called for g in byName.get(name, ())):
                reaching.add(id(fn))
                changed = True

    return {
        _qualName(fn, parents)
        for fn in fns
        if fn.name.startswith("test") and id(fn) in reaching
        and isinstance(parents.get(fn), ast.ClassDef)
    }


def gatedCells(source: str) -> Set[str]:
    tree = _parse(source)
    parents = _parents(tree)
    out: Set[str] = set()
    for fn in _functions(tree):
        if not fn.name.startswith("test"):
            continue
        for dec in fn.decorator_list:
            name = dec.id if isinstance(dec, ast.Name) else getattr(dec, "attr", "")
            if name == GATE_NAME:
                out.add(_qualName(fn, parents))
    return out


def _attrChain(node: ast.AST) -> str:
    """把 `a.b.c` 形式的取数点拼成点分串，供属性级禁令比对（不做文本正则）。"""
    parts: List[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def forbiddenReadings(source: str) -> List[str]:
    """契约文件里"用平台名判 / 无条件 skip / 信时钟宣称值"三类的**语法形态**命中。

    按 AST 判而不是按文本包含判：本文件与契约文件的说明文字里都会出现 `win32`、
    `sys.platform`、`get_clock_info` 这些字样（正是"为什么要禁"的论证），
    文本包含会把论证本身判红——那种守卫既不咬缺陷、又会逼人删掉解释。
    """
    hits: List[str] = []
    for node in ast.walk(_parse(source)):
        if isinstance(node, ast.Attribute) and _attrChain(node) in (
            "sys.platform", "os.name", "sys.getwindowsversion",
        ):
            hits.append(f"平台名判据 {_attrChain(node)}（第 {node.lineno} 行）")
        if isinstance(node, ast.Constant) and node.value == "win32":
            hits.append(f"以 'win32' 字符串常量为条件（第 {node.lineno} 行）")
        if isinstance(node, ast.Call):
            if _attrChain(node.func) == "pytest.mark.skip":
                hits.append(f"无条件 pytest.mark.skip（第 {node.lineno} 行）")
            if _attrChain(node.func).endswith("get_clock_info"):
                hits.append(
                    f"取 get_clock_info 宣称值代替实测（第 {node.lineno} 行）"
                )
    return hits


def skipIfConditionIsConstant(source: str, markerName: str):
    """`markerName = pytest.mark.skipif(<ARG>, …)` 的 <ARG> 是否为字面量。

    返回 None 表示找不到这道旗标——调用方须把它当失败，不得当"没问题"。
    """
    for node in _parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == markerName for t in node.targets):
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and _attrChain(call.func) == "pytest.mark.skipif"):
            return True  # 旗标不是 skipif 调用：形态即错，按"恒真"处理
        return bool(call.args) and isinstance(call.args[0], ast.Constant)
    return None


def loadContract():
    spec = importlib.util.spec_from_file_location("perf_gate_contract_probed", CONTRACT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSpinCellsSkipRatherThanBurn:
    """行为面：本机跑这些格必须是「跳过或跑完」，不得是「跑到超时」。"""

    #: 本格要在子进程里把那几格真跑一遍（细粒度机器上真烧 CPU），默认 30s 不够。
    @pytest.mark.timeout(240)
    def test_theSpinScaleCellsAreSkippedOrPassedWithinBudget(self):
        required = sorted(spinReachingCells(_source()) - SLEEP_ONLY_CELLS)
        assert required, (
            "检出器在契约文件里没找到任何走 CPU 自旋的用例格——本守卫会空转："
            f"可达格 {sorted(spinReachingCells(_source()))}，豁免 {sorted(SLEEP_ONLY_CELLS)}"
        )
        nodeIds = [f"{CONTRACT}::{cell}" for cell in required]
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *nodeIds,
             "-q", "-rs", "--no-header", "--timeout=25", "-p", "no:cacheprovider"],
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            cwd=str(REPO_ROOT),
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            timeout=240,
        )
        output = proc.stdout + proc.stderr
        assert "Timeout" not in output, (
            f"{len(required)} 格里至少一格在本机跑到超时：{nodeIds}\n"
            "自旋目标低于时钟推进粒度时，一次自旋即跑满一个量子，判据成本变成"
            "「量子 × 迭代数」而非「目标 × 迭代数」——本文件在受保护子集里，"
            "于是本机整场性能门禁不可复跑。\n" + output[-1500:]
        )
        expected = f"{len(required)} skipped" if " skipped" in output[-400:] \
            else f"{len(required)} passed"
        assert proc.returncode == 0 and expected in output, (
            f"这些格既没整批跳过也没全跑完（应为 {expected}），"
            f"实际退码 {proc.returncode}：\n{output[-1200:]}"
        )
        if expected.endswith("skipped"):
            assert "thread_time" in output, (
                "跳过却没点名是哪个时钟粒度导致的——读者无从判断这次跑到底验了什么：\n"
                + output[-1200:]
            )


class TestTheGateIsHonest:
    """旗标三面：按粒度而非平台名、条件非常量、谓词两头都答得出。"""

    def test_theGateIsKeyedOnGranularityNotOnPlatformName(self):
        hits = forbiddenReadings(_source())
        assert hits == [], "量子门的条件里出现不该有的取数形态：" + "；".join(hits)

    def test_theGateConditionIsTheMeasurementNotAConstant(self):
        assert skipIfConditionIsConstant(_source(), GATE_NAME) is False, (
            f"{GATE_NAME} 的 skipif 条件不是「实测粒度的函数」（或是常量、或旗标不是 "
            "skipif）——写成 `skipif(True)` 就等于把这几格永久作废，"
            "CI/Linux 侧的覆盖静默归零"
        )

    def test_theGranularityPredicateAnswersBothWays(self):
        module = loadContract()
        predicate = getattr(module, "spinClockIsResolvable", None)
        assert callable(predicate), (
            "契约文件没有暴露「时钟能否分辨自旋目标」的谓词——门要么没建，"
            "要么建在了读不到的地方"
        )
        target = module.SUB_QUANTUM_SPIN_TARGET_MS
        assert predicate(0.0) is True, "粒度 0ms（细时钟）应判「照跑」——谓词方向反了"
        assert predicate(target) is True, "粒度恰等于目标应判「照跑」：边界不该多跳一格"
        assert predicate(target * 2) is False, "粒度粗于目标应判「跳过」——谓词恒真"
        assert predicate(float("inf")) is False, "时钟完全不推进也应判「跳过」"
        assert isinstance(module.CPU_QUANTUM_MS, float), "实测粒度读数缺失"

    def test_theDetectorsThemselvesAreNotVacuous(self):
        """反向控制：三台检出器各喂一份合成样本，必须真抓得到——守卫先自证不空转。"""
        synthetic = (
            "import time\n"
            "class TestX:\n"
            "    def test_spin(self):\n"
            f"        def {SPIN_PRIMITIVE}Helper(x):\n"
            "            while time.thread_time() < time.thread_time() + x:\n"
            "                pass\n"
            f"        {SPIN_PRIMITIVE}(0.1)\n"
        )
        assert spinLoops(synthetic) == ["TestX::test_spin::spinThreadCpuHelper"], (
            f"自旋检出器对显式的 thread_time while 循环零命中——{SPIN_PRIMITIVE} "
            "基元一旦被人内联回用例里，本守卫看不见"
        )
        assert "TestX::test_spin" in spinReachingCells(synthetic), (
            "可达性检出器抓不到「用例里调基元」——新增的漏网格会躲过本守卫"
        )
        assert forbiddenReadings(
            "import sys\nimport time\n"
            "if sys.platform == 'win32':\n    pass\n"
            "x = 'win32'\n"
            "time.get_clock_info('thread_time')\n"
            "import pytest\npytest.mark.skip()\n"
        ) != [], "禁令检出器对平台名/宣称值/无条件 skip 三种形态全不命中——它会空转"
        assert skipIfConditionIsConstant(
            "import pytest\n"
            f"{GATE_NAME} = pytest.mark.skipif(True, reason='x')", GATE_NAME,
        ) is True, "字面量条件未被检出——把门改成永久跳过即可绕过本守卫"
        assert skipIfConditionIsConstant(
            "import pytest\n"
            f"{GATE_NAME} = pytest.mark.skipif(not ok(CPU_QUANTUM_MS), reason='x')",
            GATE_NAME,
        ) is False, "合法形态（条件是量度的函数）被误判为常量——本守卫会把自己的修法判红"


class TestSpinPrimitiveIsSingleSource:
    """自旋只许活在一个基元里（教义第 6 条）：新增内联自旋即红。"""

    def test_noThreadTimeSpinLivesOutsideThePrimitives(self):
        offenders = [
            where for where in spinLoops(_source())
            if where.split("::")[-1] not in GRANULARITY_PRIMITIVES
        ]
        assert offenders == [], (
            f"`{SPIN_PRIMITIVE}` 之外仍有 thread_time 自旋循环：{offenders}。"
            "内联自旋绕开了「量子 × 迭代数」的唯一成本判定点，"
            "粗粒度机器上它会带着整份受保护子集一起超时"
        )
