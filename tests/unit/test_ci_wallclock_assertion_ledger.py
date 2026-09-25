# -*- coding: utf-8 -*-
"""CI 受保护子集里的**墙钟上界断言**必须逐条登记结论。

根因（不是形状）：受保护子集在 CI 上按 171 个文件一次性跑，机器负载由整批
用例共享。而"响应路径/并发"这类**结构性契约**被几处用例编码成了**墙钟上界**
（`elapsed < 0.25`、`elapsed < 0.6`、`elapsed < 0.35`）：

- 契约本身与机器无关（"响应路径不付旁路代价"是步骤集合的事，不是秒数的事）；
- 判据却与机器强相关 ⇒ 同一份代码在 py3.11 绿、py3.12 红（实测 0.42625s vs
  阈值 0.25s），运维只能看到"偶发红"，看不到任何真实回归；
- 更坏的是它的**误判方向**：负载越高越红，于是"让 CI 变绿"的捷径就是放宽
  阈值——而那恰恰把真正的尾延迟回归也一并放行了。这正是教义第 2 条禁止的
  "降级断言换绿"。

本守卫不改判据的对错，只要求**逐条有结论**：受保护子集里每一个墙钟上界断言
都必须在 `WALLCLOCK_LEDGER` 里写明它测什么、为什么可以留墙钟（或已改为结构
不变量）。新增一处未登记的墙钟上界即判红——不许整体放行。

判据取自唯一事实源 `scripts/ci/protected_tests.txt`（CI 实际跑的清单），
不另建第二套文件清单。
"""

from __future__ import annotations

import ast
import io
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan
PROTECTED = REPO_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 取时钟的函数名（`time.perf_counter()` / `perf_counter()` / `time.time()` …）
CLOCK_FUNCS = frozenset({"perf_counter", "monotonic", "time", "time_ns", "process_time"})

#: 变量名里含这些词即视为"耗时量"（`elapsed` / `latency` / `duration_ms` …）
TIME_WORD = re.compile(r"(elapsed|latency|duration)", re.I)

#: 文本预筛关键词：整仓 1700 个测试文件里，含这些词的不到 200 个。
#: 无预筛时本守卫要 parse 全部文件（实测约 4s，CI 共享负载下会撞 pytest-timeout）——
#: 门禁自己都不稳，就会被人绕过。预筛只做"要不要 parse"的粗判，不漏判：
#: 候选词覆盖时钟函数名与耗时词，命中集合是 `wallclockBounds` 判据的超集。
PARSE_HINTS = ("perf_counter", "monotonic", "time.time", "time_ns", "process_time",
               "elapsed", "latency", "duration")


def _maybeContainsWallclock(text: str) -> bool:
    return any(hint in text for hint in PARSE_HINTS)


def protectedFiles() -> List[str]:
    """CI 实际跑的受保护子集（唯一事实源，不另建清单）。"""
    text = io.open(PROTECTED, encoding="utf-8").read()
    return [
        line.split("#", 1)[0].strip()
        for line in text.splitlines()
        if line.split("#", 1)[0].strip()
    ]


def _outsideSubsetRefs() -> List:
    """子集外的测试文件源码引用（**枚举与文本读取**收口到共享预算）。

    取数落在本仓唯一 AST 入口 `tests/ast_scan`：`sourceRefsUnder` 的 `hints`
    用的就是本模块自己的 `PARSE_HINTS`（`_maybeContainsWallclock` 的同一份词表，
    不抄第二份），故预筛口径与本地判定逐字一致；文本读取走 `_cachedCode`，
    与其余跨文件判据复用同一份缓存（Issue #148 / #197）。

    解析**不**并入共享缓存：实测 224 个候选文件私有 `ast.parse` 0.22s、
    走 `_cachedParse` 0.82s —— 共享缓存的 `maxsize=None` 会把语法树全部留下，
    gen2 GC 随即反复扫描这棵常驻图，成本反随命中面增长（见门禁台账里
    `test_pytest_collection_hygiene.py` 那条同因读数）。故本处保留私有解析，
    范围已由预筛限定在命中面之内。
    """
    return ast_scan.sourceRefsUnder(
        REPO_ROOT / "tests", ".py", hints=PARSE_HINTS)


def _derivesFromClock(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name) and func.id in CLOCK_FUNCS:
            return True
        if isinstance(func, ast.Attribute) and func.attr in CLOCK_FUNCS:
            return True
    return False


def _readsElapsed(node: ast.AST, elapsedNames: frozenset) -> bool:
    """表达式是否读到已认定的耗时量（派生：`budget = elapsed * 3`）。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in elapsedNames:
            return True
    return False


def _isClockReading(node: ast.AST, instantNames: frozenset) -> bool:
    """表达式是否给出一个**时刻**：裸时钟调用，或读到已认定的时刻量。"""
    if _derivesFromClock(node):
        return True
    return isinstance(node, ast.Name) and node.id in instantNames


def _isClockDifference(node: ast.AST, instantNames: frozenset) -> bool:
    """表达式是否是「时钟差」——算一段用时，而不是把一个时刻做平移。

    - `perf_counter() - t0`（减掉一个已记下的时刻）**是**用时；
    - `time.time() - 31 * 86400`（减一个常量）**不是**用时，是"31 天前那个时刻"；
    - `time.time() + 3600` 同理是过期时间戳。

    三者都是"含时钟调用的运算"，只看有没有时钟调用会把后两者算成耗时——
    假阳性会训练人忽略门禁（本仓早已写明这条理由）。
    """
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Sub):
        return False
    left, right = node.left, node.right
    if not _derivesFromClock(left):
        left, right = right, left
    if not _derivesFromClock(left) or isinstance(right, ast.Constant):
        return False
    return _isClockReading(right, instantNames)


def _clockNames(tree: ast.AST) -> frozenset:
    """模块里"一份用时"的局部变量名（`elapsed = t1 - t0` 这类）。

    传染式求不动点，覆盖三种**绕一手**的写法——判据还是同一条契约，只是多转了一手，
    漏掉它们等于"改一处写法就能从门禁下溜过"：

    - 差值：`elapsed = perf_counter() - t0`；
    - 派生：`avg_time = elapsed / 5`（用时的变换仍是用时）；
    - 收集：`samples.append(perf_counter() - t0)` 后 `median(samples) < 0.2`
      （样本先入容器再取中位，"各 N 轮取中位"这类读数正是这么写的）。

    报错面：**时刻**不是用时——`before = time.time()` / `expires_at = time.time() + 3600`
    既不算用时，也不向下游传染（否则 `assert before <= s._last_activity <= after`
    这类时刻区间断言会被误判成墙钟上界）。
    """
    instants: set = set()
    elapsed: set = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            targets: List[ast.Name] = []
            if isinstance(node, ast.Assign) and node.value is not None:
                value = node.value
                if _isClockDifference(value, frozenset(instants)) or _readsElapsed(
                    value, frozenset(elapsed)
                ):
                    bucket = elapsed
                elif _derivesFromClock(value):
                    bucket = instants
                else:
                    continue
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
            ):
                # 用时样本入容器：容器名同样算用时（`median(samples)` 量的是用时）
                if not any(
                    _isClockDifference(arg, frozenset(instants))
                    or _readsElapsed(arg, frozenset(elapsed))
                    for arg in node.args
                ):
                    continue
                bucket = elapsed
                targets = [node.func.value]
            else:
                continue
            for target in targets:
                if target.id not in bucket:
                    bucket.add(target.id)
                    changed = True
    return frozenset(elapsed)


def _measureName(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        index = node.slice
        if isinstance(index, ast.Constant) and isinstance(index.value, str):
            return index.value
    return ""


def _isWallclockMeasure(node: ast.AST, clockNames: frozenset) -> bool:
    """判据是否在量"耗时"：由时钟算出、名字含耗时词、或**就地**含时钟调用。

    第三类是必须的：`assert time.perf_counter() - t0 < 0.5` 这类把时钟算在
    断言里的写法，没有任何"耗时变量名"可抓——漏了它，改一处写法就能从门禁
    下溜过去（门槛空过等于没有门槛）。
    """
    if _readsElapsed(node, clockNames):
        return True
    # 就地写时钟：`assert perf_counter() - t0 < 0.5`（减常量才是时刻平移，不算耗时）
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
        for side in (node.left, node.right):
            if _derivesFromClock(side) and not isinstance(
                node.right if side is node.left else node.left, ast.Constant
            ):
                return True
    name = _measureName(node)
    if not name:
        return False
    return name in clockNames or bool(TIME_WORD.search(name))


def wallclockBounds(source: str) -> List[Tuple[int, str, str]]:
    """文件里所有"耗时量 < 常量"断言：[(行号, 所属用例名, 表达式)]。

    只收**上界**（`<` / `<=`）：下界断言（`elapsed >= 11 * delay`）在负载下只会
    更成立，不会把 CI 判红，不属于本守卫的靶点。
    """
    tree = ast.parse(source)
    clock = _clockNames(tree)
    found: List[Tuple[int, str, str]] = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not func.name.startswith("test"):
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.Assert):
                continue
            for sub in ast.walk(node.test):
                if not isinstance(sub, ast.Compare):
                    continue
                if not any(isinstance(op, (ast.Lt, ast.LtE)) for op in sub.ops):
                    continue
                left = sub.left
                # `abs(get_turn_tool_elapsed() - 1.0) < 1e-9` 是数值精度断言，不是墙钟
                if isinstance(left, ast.Call) and isinstance(left.func, ast.Name):
                    if left.func.id == "abs":
                        continue
                if _isWallclockMeasure(left, clock):
                    found.append((node.lineno, func.name, ast.unparse(left)))
    return found


#: 逐条结论台账：**保留**墙钟上界的命中点。键 = "<受保护子集相对路径>::<用例名>"，
#: 值 = (命中数, 结论)。命中数变了说明该用例的判据结构变了，必须重新逐条给结论
#: ——不许靠"文件在集合里"整体放行（那等于其余命中点不写理由）。
#:
#: 台账为空是默认政策（此处不允许留墙钟）；确需留墙钟的命中点必须逐条写明理由，
#: 且**同一契约的结构面必须另有用例钉住**——只留比值等于把契约交给机器速度。
WALLCLOCK_LEDGER: Dict[str, Tuple[int, str]] = {
    "tests/unit/context/test_ledger_write_batching.py"
    "::test_batch_round_is_far_below_per_row_shape": (
        1,
        "A2 的倍数本身是机时契约（同机同存量 A/B 比值），墙钟不可替代；"
        "其结构面另由 test_round_uses_one_connection_and_one_transaction 钉住"
        "（一轮 0 次新建连接 + 1 次 BEGIN + 1 次 COMMIT）。"
        "原写法把「首次 token 估算器的冷加载」算进分子（实测 ~250ms），"
        "分子恒为现状形状的 1.2 倍 ⇒ 在 CI 上必然判红，与本条契约无关；"
        "已改为两侧预热后取 3 轮中位，实测 135–427×，对阈值 3× 有 45× 以上裕量",
    ),
}


#: 已从"墙钟上界"改为"结构不变量"的命中点：键 = "<相对路径>::<用例名>"，值 = 理由。
#: 它们必须**一直**不含墙钟上界——改回墙钟即判红（那是本批 CI 偶发红的根因）。
CONVERTED_TO_INVARIANT: Dict[str, str] = {
    "tests/unit/agent/test_post_chat_p0_latency_observability.py"
    "::test_background_response_path_does_not_scale_with_bypass_steps":
        "响应路径不等旁路步骤 ⇒ 闸住旁路步骤，process() 必须仍能返回（结构，非秒数）",
    "tests/unit/agent/test_post_chat_p0_latency_observability.py"
    "::test_concurrent_background_actually_parallel":
        "旁路步骤并发 ⇒ 同轮在飞高水位 = 并发步数（串行时恒为 1）",
    "tests/unit/core/test_index_observability_p0_3.py"
    "::test_snapshot_cost_does_not_scale_with_row_count":
        "快照成本只随 schema 走 ⇒ 行数放大后语句序列逐条相同",
    "tests/unit/evolution/test_rsi_result_summary_wiring.py"
    "::test_summary_never_awaits_rsi_on_response_path":
        "RSI 不在响应路径 ⇒ 闸住 RSI 步骤，process() 必须仍能返回",
}


def _scan() -> Dict[str, List[Tuple[int, str]]]:
    hits: Dict[str, List[Tuple[int, str]]] = {}
    for rel in protectedFiles():
        path = REPO_ROOT / rel
        if not path.is_file() or not rel.endswith(".py"):
            continue
        try:
            source = io.open(path, encoding="utf-8", errors="ignore").read()
            bounds = wallclockBounds(source)
        except SyntaxError:
            continue
        for lineno, test_name, expr in bounds:
            hits.setdefault(f"{rel}::{test_name}", []).append((lineno, expr))
    return hits


class TestWallclockBoundsAreLedgered:
    """受保护子集里的墙钟上界断言逐条有结论。"""

    def test_no_unledgered_wallclock_upper_bound(self):
        hits = _scan()
        unregistered = sorted(set(hits) - set(WALLCLOCK_LEDGER))
        detail = {k: hits[k] for k in unregistered}
        assert unregistered == [], (
            "受保护子集里出现未登记的墙钟上界断言（必须逐条给结论："
            "改为结构不变量，或写明为何墙钟不可替代）:\n  "
            + "\n  ".join(f"{k} → {detail[k]}" for k in unregistered)
        )

    def test_ledger_entries_match_live_hit_counts(self):
        """登记的行数必须与实测一致——判据变了就得重新给结论。"""
        hits = _scan()
        drifted = []
        for key, (count, _reason) in WALLCLOCK_LEDGER.items():
            live = len(hits.get(key, []))
            if live != count:
                drifted.append(f"{key}: 登记 {count} 处，实测 {live} 处")
        assert drifted == [], "墙钟台账与实测命中数不一致（判据结构变了）:\n  " + "\n  ".join(drifted)

    def test_ledger_has_no_stale_entries(self):
        """台账里不得有已经不存在的命中点（删了判据要同步销账）。"""
        hits = _scan()
        stale = [k for k in WALLCLOCK_LEDGER if k not in hits]
        assert stale == [], f"台账登记了已不存在的墙钟断言：{stale}"


class TestConvertedSitesStayStructural:
    """已改为结构不变量的 4 处不得改回墙钟（那正是本批 CI 偶发红的根因）。"""

    def test_converted_sites_have_no_wallclock_bound(self):
        hits = _scan()
        regressed = {k: hits[k] for k in CONVERTED_TO_INVARIANT if k in hits}
        assert regressed == {}, (
            "下列用例又出现了墙钟上界断言（本批已把它们改为结构不变量，"
            "改回去会让 CI 在共享机负载下偶发红）:\n  "
            + "\n  ".join(f"{k} → {regressed[k]}" for k in sorted(regressed))
        )

    def test_converted_sites_still_exist(self):
        """登记为"已改结构不变量"的用例必须真实存在，否则台账在给不存在的靶点作保。"""
        missing = []
        for key in CONVERTED_TO_INVARIANT:
            rel, _, test_name = key.partition("::")
            path = REPO_ROOT / rel
            if not path.is_file() or f"def {test_name}(" not in path.read_text(
                encoding="utf-8", errors="ignore"
            ):
                missing.append(key)
        assert missing == [], f"台账登记了已不存在的用例：{missing}"

    def test_converted_sites_are_in_protected_subset(self):
        files = set(protectedFiles())
        absent = [k.split("::")[0] for k in CONVERTED_TO_INVARIANT if k.split("::")[0] not in files]
        assert absent == [], f"登记文件不在受保护子集，CI 不跑：{absent}"


#: 受保护子集**之外**的墙钟上界：CI 不跑它们，故不阻塞本批；但按教义第 5 条
#: （放大视角）不得静默遗留——逐条登记，写明为何本轮不动。
#:
#: 本批只修"会让 CI 偶发红"的那批（受保护子集内已改结构不变量的 4 处 + 逐条登记的 1 处）。
#: 子集外这些要么本意就是量真实机时（性能/超时类基准），要么被测对象是墙上时钟本身，
#: 改动它们属于另一票的范围；此处登记以免"没人知道还有多少处"。
OUTSIDE_SUBSET_LEDGER: Dict[str, int] = {
    "tests/api/test_channel_config_blocking_regression.py": 2,
    "tests/auth/test_security_integration.py": 3,
    "tests/e2e/test_phase4_integration.py": 2,
    "tests/integration/test_multi_agent_coordination.py": 1,
    "tests/performance/test_context_pool_load.py": 1,
    "tests/unit/agent/test_b7_worker_occupancy.py": 2,
    "tests/unit/agent/test_handle_tool_calls_parallel.py": 1,
    "tests/unit/agent/test_post_chat_pipeline_tdd.py": 1,
    "tests/unit/api/test_security_p0_audit_fixes.py": 1,
    "tests/unit/channels/test_wechat_ilink_qrcode.py": 1,
    "tests/unit/context/test_context_pool_agent_core_integration.py": 1,
    "tests/unit/memory/test_moe_routing.py": 2,
    "tests/unit/neurflow/test_parallel_execution.py": 1,
    "tests/unit/skills/test_skill_import_architecture.py": 1,
    "tests/unit/sync/test_slow_consumer_seq_policy.py": 1,
    "tests/unit/tools/test_tool_orchestrator.py": 2,
}


class TestOutsideSubsetHitsAreCounted:
    """子集外的墙钟上界不许"消失在视野里"：数量必须与实测一致。"""

    def test_outside_subset_counts_match(self):
        live: Dict[str, int] = {}
        subset = set(protectedFiles())
        for ref in _outsideSubsetRefs():
            if not ref.path.match("test_*.py"):
                continue
            rel = ast_scan.relativeToRepo(ref.path)
            if rel in subset or not _maybeContainsWallclock(ref.code):
                continue
            try:
                count = len(wallclockBounds(ref.code))
            except SyntaxError:
                continue
            if count:
                live[rel] = count
        assert live == OUTSIDE_SUBSET_LEDGER, (
            "子集外墙钟上界的分布变了（新增/清理都要同步登记，不许静默遗留）:\n"
            f"  新增或变化: "
            f"{ {k: v for k, v in live.items() if OUTSIDE_SUBSET_LEDGER.get(k) != v} }\n"
            f"  台账里已不存在: "
            f"{sorted(set(OUTSIDE_SUBSET_LEDGER) - set(live))}"
        )


class TestDetectorIsNotVacuous:
    """反向控制：检出器要真的检出，且不得把数值精度断言当墙钟。"""

    def test_detector_finds_clock_upper_bound(self):
        sample = (
            "import time\n"
            "def test_x():\n"
            "    t0 = time.perf_counter()\n"
            "    elapsed = time.perf_counter() - t0\n"
            "    assert elapsed < 0.25\n"
        )
        assert wallclockBounds(sample), "检出器对教科书形态的墙钟上界零命中——本守卫会空转"

    def test_detector_finds_inline_clock_expression(self):
        """就地写时钟的形态必须同样命中（换一处写法不得从门禁下溜过）。"""
        sample = (
            "import time\n"
            "def test_x():\n"
            "    t0 = time.perf_counter()\n"
            "    assert time.perf_counter() - t0 < 0.5\n"
        )
        assert wallclockBounds(sample), (
            "断言里就地算时钟的墙钟上界漏检——改一处写法即可绕过本门禁"
        )

    def test_detector_ignores_numeric_precision(self):
        sample = (
            "def test_x(obj):\n"
            "    assert abs(obj.get_turn_tool_elapsed() - 1.0) < 1e-9\n"
        )
        assert wallclockBounds(sample) == [], "数值精度断言被误判成墙钟（假阳性会训练人忽略门禁）"

    def test_prefilter_never_drops_a_real_hit(self):
        """预筛必须不漏判：受保护子集里每个真命中都要能过预筛。

        （预筛只是"要不要 parse"的粗判；若它把真命中滤掉，本守卫会静默空转。）
        """
        for rel in protectedFiles():
            path = REPO_ROOT / rel
            if not path.is_file() or not rel.endswith(".py"):
                continue
            text = io.open(path, encoding="utf-8", errors="ignore").read()
            try:
                hits = wallclockBounds(text)
            except SyntaxError:
                continue
            if hits:
                assert _maybeContainsWallclock(text), (
                    f"{rel} 含真命中却被预筛滤掉——本守卫会对它空转"
                )

    def test_detector_follows_clock_through_collected_samples(self):
        """时钟样本先收进列表、再取中位：量的是墙钟，不得漏检。

        `samples.append(perf_counter() - t0)` 之后 `median(samples) < 0.2` 与
        教科书形态是同一个契约，只是多绕了一手；漏检等于"改一处写法即可绕过门禁"。
        """
        sample = (
            "import time, statistics\n"
            "def test_x():\n"
            "    samples = []\n"
            "    for _ in range(3):\n"
            "        t0 = time.perf_counter()\n"
            "        samples.append(time.perf_counter() - t0)\n"
            "    assert statistics.median(samples) < 0.2\n"
        )
        assert wallclockBounds(sample), "时钟样本经列表收集后取中位的墙钟上界漏检"

    def test_detector_follows_clock_through_derived_variable(self):
        """时钟先落到一个变量，再由它派生第二个变量：派生量同样是耗时量。"""
        sample = (
            "import time\n"
            "def test_x():\n"
            "    t0 = time.perf_counter()\n"
            "    elapsed = time.perf_counter() - t0\n"
            "    budget = elapsed * 3\n"
            "    assert budget < 0.5\n"
        )
        assert wallclockBounds(sample), "由耗时量派生的变量的上界断言漏检"

    def test_detector_ignores_lower_bound(self):
        sample = (
            "import time\n"
            "def test_x():\n"
            "    t0 = time.perf_counter()\n"
            "    elapsed = time.perf_counter() - t0\n"
            "    assert elapsed >= 1.65\n"
        )
        assert wallclockBounds(sample) == [], "下界断言在负载下只会更成立，不该进本台账"

    def test_self_is_in_protected_subset(self):
        rel = "tests/unit/test_ci_wallclock_assertion_ledger.py"
        assert rel in protectedFiles(), (
            f"{rel} 不在受保护子集——CI 根本不跑它，本守卫退化成空壳"
        )
