# -*- coding: utf-8 -*-
"""受保护子集里的**条件等待**不得以「零延迟让步次数」为界（PR #308 CI 红根修）。

## 根因（不是形状）

`tests/unit/tools/test_tool_cancellation.py` 的两条进程收尸判据此前这样等：

    for _ in range(200):
        if proc.poll() is not None:
            return True
        await asyncio.sleep(0)

以**让步次数**为界收口。空载机上 1~7 次让步即命中，看起来"必然够用"；而在 CI
上受保护子集与 4000+ 条用例**共享同一批 vCPU**，`sleep(0)` 只是把控制权交回
事件循环、**不保证内核完成一次调度**：实测同一份代码在 48 路自旋的超额订阅下，
200 次让步在 5ms 内走完，而子进程仍未被回收（`poll()` 仍为 `None`）⇒ 判据转红。

    构建 cnb-v4f-1k3jg3a81（PR #308）实测：
      FAILED tests/unit/tools/test_tool_cancellation.py
             ::TestCancelTokenProtocol::testCancelRunsRegisteredKillAction
      AssertionError: 令牌置位后进程仍然存活——回调没兑现

**这个红是假红**：回调已兑现（子进程确实被杀灭），只是等待窗口与机器负载捆绑
——正是 `AGENTS.md` 修复教义第 2 条点名的「判据与机器速度捆绑」形态，本仓此前
已有两次同源事故（`perf_gate.py` 微基准、`test_perf_gate_contract.py` 等待注入），
处置口径见 `test_ci_wallclock_assertion_ledger.py`。

## 与既有两个台账的分工（本守卫不重复它们）

- `test_ci_wallclock_assertion_ledger.py` 管「量耗时的**上界**」；
- `test_clock_caliber_ledger.py` 管「进程内计时的**口径**」；
- **本守卫管「等待本身以什么为界」**——靶心恰是那两处看不见的形态：让步计数为界
  的等待零时钟读数，故墙钟台账与计时口径台账对它都是空集。

## 判据

受保护子集里每一处「让步计数为界的等待」都必须在 `COUNT_BOUNDED_WAIT_LEDGER`
里逐条给结论；**空集是默认政策**——这类等待的正确形态是等**真事件**，本守卫的
反向控制逐个钉住三种合法写法：

- 等**外部事实**（OS 报出子进程退出、端口可连、文件出现）：带**具名超时常量**的
  真等待（`proc.wait(timeout=KILL_GRACE_S)`），超时值取自单源常量；
- 等**同一事件循环内的其它任务**推进：条件由本进程状态推进时，每轮让步都会推进
  该状态，与机器负载无关（不属本缺陷形态）；
- 等**真定时**：`asyncio.sleep(正数)` 是让出到点，不是自旋。

判据不得整体放行，也不得空转（反向控制三条在下方 `TestDetectorIsNotVacuous`）。
"""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan

PROTECTED = REPO_ROOT / "scripts" / "ci" / "protected_tests.txt"
GUARD_REL = "tests/unit/ci/test_count_bounded_wait_ledger.py"

#: 逐条结论台账：键 = "<受保护子集相对路径>::<函数名>"，值 = (命中数, 结论)。
#: **空集是默认政策**：让步计数为界的等待一旦出现即判红。
#: 确需留册者必须写明「它等的是什么、为什么与机器负载无关」，且同一契约的
#: 真事件面必须另有用例钉住——只留计数等于把判据交给机器负载。
COUNT_BOUNDED_WAIT_LEDGER: Dict[str, Tuple[int, str]] = {}


def protectedFiles() -> List[str]:
    """CI 实际跑的受保护子集（唯一事实源，不另建清单）。"""
    return [
        line.split("#", 1)[0].strip()
        for line in io.open(PROTECTED, encoding="utf-8").read().splitlines()
        if line.split("#", 1)[0].strip()
    ]


#: 「外部事实」探针：由 **OS / 内核**推进、事件循环**让出再多轮也推不动**的读数。
#: 靶心只认这些——循环内自己的状态（闭包计数器、事件对象、任务集合）由本进程
#: 的就绪队列推进，`sleep(0)` 交回控制权时必然跑完就绪回调，与机器负载无关，
#: 不是本判据的形态（假阳性会训练人忽略门禁，本仓已有明文纪律）。
#:
#: `poll` / `returncode` / `is_alive` 是子进程退出事实；`exists` / `is_file` 是
#: 外部进程可能产生的文件系统事实；`pgrep` / `tasklist` 是另行查表的外部事实。
EXTERNAL_FACT_PROBES = frozenset({
    "poll", "returncode", "is_alive", "waitpid", "pgrep", "tasklist",
    "exists", "is_file", "is_dir", "connect_ex",
})


def _readsExternalFact(loop: ast.AST) -> bool:
    """循环体/条件是否读到**外部事实**（见 `EXTERNAL_FACT_PROBES`）。"""
    for sub in ast.walk(loop):
        if isinstance(sub, ast.Attribute) and sub.attr in EXTERNAL_FACT_PROBES:
            return True
        if isinstance(sub, ast.Call):
            if _calleeName(sub) in EXTERNAL_FACT_PROBES:
                return True
    return False


def _parametersOf(fn: ast.AST) -> frozenset:
    """函数签名里绑定的形参名。"""
    arguments = getattr(fn, "args", None)
    if arguments is None:
        return frozenset()
    names = {
        arg.arg
        for arg in (
            list(arguments.posonlyargs) + list(arguments.args) + list(arguments.kwonlyargs)
        )
    }
    if arguments.vararg:
        names.add(arguments.vararg.arg)
    if arguments.kwarg:
        names.add(arguments.kwarg.arg)
    return frozenset(names)


def _callsParameter(loop: ast.AST, parameters: frozenset) -> bool:
    """循环里是否调用了**调用方传进来的**函数（谓词由调用方给）。

    这是本轮 CI 红的实际形态：`_pollUntilAsync(condition)` 自己不知道在等什么，
    条件与它要等的那个外部事实都由调用方（`lambda: proc.poll() is not None`）给出。
    对这样的循环，**循环体里推不动它等的条件**——它只有让步这一条路。故"等的是
    本循环推不动的条件"这一条根判据，在这一形态上的机器可见证据就是
    「谓词是形参」。只按外部事实名匹配会漏掉 helper 形态（本轮实测：漏），
    而 helper 形态恰恰是缺陷最容易被写成的样子。
    """
    for sub in ast.walk(loop):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id in parameters
        ):
            return True
    return False


def _calleeName(call: ast.Call) -> str:
    """调用的名字（`asyncio.sleep` → `sleep`；`sleep` → `sleep`）。"""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _isZeroDelayYield(node: ast.AST) -> bool:
    """节点是否是「零延迟让步」：`await <x>.sleep(0)`。

    必须是被 `await` 的那一个 —— 不 await 的 `asyncio.sleep(0)` 只是造了个
    协程对象就丢掉，既不等待也不让步，不属本判据的靶点。
    """
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Await):
            continue
        call = sub.value
        if not isinstance(call, ast.Call) or _calleeName(call) != "sleep":
            continue
        if not call.args:
            continue
        first = call.args[0]
        if isinstance(first, ast.Constant) and first.value == 0:
            return True
    return False


def _isCountBounded(loop: ast.AST) -> bool:
    """循环是否以**迭代次数**为界：`for _ in range(...)`。

    `while` 循环不属本形态 —— 它没有计数上界，不存在"数完就判红"的窗口
    （坏实现的形态是转不完，由 pytest-timeout 兜底，与本判据的靶心不同）。
    """
    if not isinstance(loop, ast.For):
        return False
    iterator = loop.iter
    return (
        isinstance(iterator, ast.Call)
        and isinstance(iterator.func, ast.Name)
        and iterator.func.id == "range"
    )


def _exitsOnCondition(loop: ast.AST) -> bool:
    """循环体是否**按条件提前退出**（`break` / `return`）。

    这是「等到了就停」的签名：没有提前退出的定次循环只是计量性地让出若干轮，
    不声称"等到了某件事"，不属本判据的靶点（假阳性会训练人忽略门禁）。
    """
    return any(
        isinstance(sub, (ast.Break, ast.Return)) for sub in ast.walk(loop)
    )


def countBoundedWaits(source) -> List[Tuple[int, str]]:
    """文件里「让步计数为界的等待」落点：`[(行号, 所属函数名)]`。

    判据 = **计数为界的循环** + **按条件提前退出** + **循环体里有零延迟让步**
    + **等的是外部事实**，四者同时成立才是靶点。任缺其一都不是本形态：

    - 缺「等的是本循环推不动的条件」一项的（等的是同一事件循环内的状态：
      闭包计数器、任务集合）由本进程就绪队列推进，`sleep(0)` 交回控制权时
      必然跑完就绪回调，**与机器负载无关**，不算缺陷——把这类误判成靶点
      会训练人忽略门禁。该项有两种机器可见形态：直接读外部事实，或谓词由
      调用方经形参传入（helper 形态，本轮 CI 红的实际写法）；
    - 缺「提前退出」的只是计量性让出，不声称"等到了"；
    - 缺「零延迟让步」的（真定时 `sleep(0.05)`）是让出到点，不是自旋。
    """
    tree = source if isinstance(source, ast.AST) else ast.parse(source)
    found: List[Tuple[int, str]] = []
    stack = [(tree.body, "<模块级>", frozenset())]
    visited: set = set()
    while stack:
        statements, owner, parameters = stack.pop()
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stack.append((statement.body, statement.name, _parametersOf(statement)))
                continue
            if isinstance(statement, ast.For) or isinstance(statement, ast.While):
                waitsUnreachable = _readsExternalFact(statement) or _callsParameter(
                    statement, parameters
                )
                if (
                    _isCountBounded(statement)
                    and _exitsOnCondition(statement)
                    and _isZeroDelayYield(statement)
                    and waitsUnreachable
                ):
                    key = (statement.lineno, owner)
                    if key not in visited:
                        visited.add(key)
                        found.append(key)
            stack.append((list(ast.iter_child_nodes(statement)), owner, parameters))
    return sorted(found)


def _scan() -> Dict[str, List[int]]:
    """受保护子集里的落点读数：`{"<相对路径>::<函数名>": [行号, ...]}`。"""
    hits: Dict[str, List[int]] = {}
    for rel in protectedFiles():
        path = REPO_ROOT / rel
        if not path.is_file() or not rel.endswith(".py"):
            continue
        try:
            tree = ast_scan._cachedParse(ast_scan._cacheKey(path), ast_scan.sourceCode(path))
        except (SyntaxError, OSError):
            continue
        for lineno, owner in countBoundedWaits(tree):
            hits.setdefault(f"{rel}::{owner}", []).append(lineno)
    return hits


class TestCountBoundedWaitsAreLedgered:
    """受保护子集里的让步计数等待逐条有结论（默认政策：一处都不许有）。"""

    def test_no_unledgered_count_bounded_wait(self):
        hits = _scan()
        unregistered = sorted(set(hits) - set(COUNT_BOUNDED_WAIT_LEDGER))
        assert unregistered == [], (
            "受保护子集里出现「让步计数为界的等待」（判据与机器负载捆绑，"
            "CI 共享 vCPU 时必偶发红）:\n  "
            + "\n  ".join(f"{key} → 行 {hits[key]}" for key in unregistered)
            + "\n修法：等**真事件**——等外部事实用带具名超时常量的真等待"
            "（`proc.wait(timeout=KILL_GRACE_S)`、`asyncio.wait_for(...)`），"
            "等同一事件循环内的状态推进用一次性让步；"
            "\n确需留册时登记进 COUNT_BOUNDED_WAIT_LEDGER 并写明为何与负载无关。"
        )

    def test_ledger_entries_match_live_hit_counts(self):
        """登记的命中数必须与实测一致——判据结构变了就得重新给结论。"""
        hits = _scan()
        drifted = []
        for key, (count, _reason) in COUNT_BOUNDED_WAIT_LEDGER.items():
            live = len(hits.get(key, []))
            if live != count:
                drifted.append(f"{key}: 登记 {count} 处，实测 {live} 处")
        assert drifted == [], "台账与实测命中数不一致（判据结构变了）:\n  " + "\n  ".join(drifted)

    def test_ledger_has_no_stale_entries(self):
        """台账里不得有已经不存在的落点（改了要同步销账）。"""
        hits = _scan()
        stale = [key for key in COUNT_BOUNDED_WAIT_LEDGER if key not in hits]
        assert stale == [], f"台账登记了已不存在的让步计数等待：{stale}"


class TestDetectorIsNotVacuous:
    """反向控制：检出器要真的检出，且不得把合法等待当成靶点。"""

    #: 缺陷形态：计数为界 + 按条件提前退出 + 零延迟让步（本轮 CI 红的原文）。
    DEFECT = (
        "import asyncio\n"
        "async def _pollUntilAsync(condition, attempts=200):\n"
        "    for _ in range(attempts):\n"
        "        if condition():\n"
        "            return True\n"
        "        await asyncio.sleep(0)\n"
        "    return False\n"
    )

    #: 合法形态一：等外部事实，上界是具名常量（本轮修法）。
    REAL_EVENT_WAIT = (
        "import asyncio\n"
        "from neurova.sandbox.exec_sandbox import KILL_GRACE_S\n"
        "async def _awaitExit(proc):\n"
        "    try:\n"
        "        await asyncio.to_thread(proc.wait, timeout=KILL_GRACE_S)\n"
        "        return True\n"
        "    except Exception:\n"
        "        return False\n"
    )

    #: 合法形态二：真定时（让出到点），不是自旋。
    TIMED_WAIT = (
        "import asyncio\n"
        "async def _settle():\n"
        "    for _ in range(5):\n"
        "        if ready():\n"
        "            break\n"
        "        await asyncio.sleep(0.05)\n"
    )

    #: 合法形态三：等**同一事件循环内**的状态推进（闭包计数器），不是外部事实。
    #: 这正是 `tests/unit/agent/test_post_chat_p0_latency_observability.py` 里
    #: 「等并发步骤全部进门」的写法：任务由本进程 `create_task` 起，`sleep(0)`
    #: 交回控制权时它们必然被跑过一轮，与机器负载无关。
    SAME_LOOP_WAIT = (
        "import asyncio\n"
        "async def _run():\n"
        "    gauge = {'inflight': 0}\n"
        "    for _ in range(20):\n"
        "        if gauge['inflight'] == 5:\n"
        "            break\n"
        "        await asyncio.sleep(0)\n"
    )

    #: 合法形态四：定次让出、不声称「等到了」（无提前退出）。
    METERING = (
        "import asyncio\n"
        "async def _letTasksStart():\n"
        "    for _ in range(20):\n"
        "        await asyncio.sleep(0)\n"
    )

    def test_detector_reports_count_bounded_wait(self):
        hits = countBoundedWaits(self.DEFECT)
        assert hits == [(3, "_pollUntilAsync")], (
            f"检出器对本轮 CI 红的原文零命中（实测 {hits}）——本守卫会空转"
        )

    def test_detector_ignores_real_event_wait(self):
        assert countBoundedWaits(self.REAL_EVENT_WAIT) == [], (
            "等真事件（带具名超时常量）的写法被误判成让步计数等待——"
            "假阳性会把正确修法一起判红"
        )

    def test_detector_ignores_timed_wait(self):
        assert countBoundedWaits(self.TIMED_WAIT) == [], "真定时让出被误判成自旋"

    def test_detector_ignores_same_loop_wait(self):
        assert countBoundedWaits(self.SAME_LOOP_WAIT) == [], (
            "等同一事件循环内状态推进的写法被误判成靶点——它不是外部事实，"
            "让出若干轮必然推进，假阳性会训练人忽略门禁"
        )

    def test_detector_ignores_metering_loop(self):
        assert countBoundedWaits(self.METERING) == [], (
            "不声称「等到了」的定次让出被误判成等待——假阳性会训练人忽略门禁"
        )

    def test_detector_ignores_unawaited_sleep(self):
        """不 await 的 `asyncio.sleep(0)` 只是造了个协程就丢掉，不构成等待。"""
        source = (
            "def _noop():\n"
            "    for _ in range(5):\n"
            "        if ready():\n"
            "            return True\n"
            "        asyncio.sleep(0)\n"
        )
        assert countBoundedWaits(source) == []


class TestGuardIsRegistered:
    def test_guard_itself_is_registered(self):
        """守卫自己也得进清单，否则本文件的判据在 CI 上根本不执行。"""
        assert GUARD_REL in protectedFiles(), (
            f"{GUARD_REL} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )
