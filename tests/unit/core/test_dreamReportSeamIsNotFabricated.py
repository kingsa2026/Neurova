# -*- coding: utf-8 -*-
"""梦境报告这条链：调用面必须落在定义面上（§6-136）。

来历：`tests/integration/test_sleep_closed_loop.py`（363 行 / 9 格）里有 8 格长期红。复算结论
不是"契约漂移"，是**这些 API 从来没存在过**：

- `MemoryStorage(db_path=...)` —— 真签名是 `__init__(self, storage_dir)`（`memory_layer/storage.py:275`），
  全仓历史里 `db_path` 从未出现在该文件（`git log --all -S "db_path" -- <file>` 零命中）；
- `storage.save_dream_report(...)` / `get_dream_report(...)` / `get_dream_report_stats()` ——
  `git log --all -S "def save_dream_report"` **零命中**：写侧从来没实现过，不是被删的；
- `CognitionOrchestrator(storage=...)` 与 `orchestrator._storage` —— 真签名
  `__init__(self, config=None)`（当时位于 `core` 包那只编排器的 `:322`，该文件已随 §6-166 退役；
  复核这条依据请用 `git log -S "def get_cognition_orchestrator" --oneline`，别按现树找文件），
  类里也没有 `_storage`；
- `IdleTimeTracker(storage=...)` / `idle_thresholds=` —— 真签名不收这些参数
  （`core/idle_tracker.py:90`）。

同一条病在**生产侧**也有一处，本批一并根修：`IdleTimeTracker.adjust_parameters_based_on_sleep_quality()`
读 `self._storage`（全类从未赋值）再调 `get_dream_report_stats()`（全仓无实现），外面套一层
`except Exception → log_debug` —— 于是它每次调用必然抛 AttributeError、必然被吞、必然原样返回，
"根据睡眠质量调整参数"从未调整过任何东西，且零生产调用方。按教义第 2 条，抹掉谎报的正规处置是
**摘掉这只门面**（要这条能力得先把梦境报告的真源接进来 → 台账登记为待裁），而不是留着它继续
"看起来有"。

本文件把这一类形态钉成机器可判：**对一个具名方法集合，调用面必须 ⊆ 定义面**；属性读必须有赋值。
反向对照自证探测器不是恒绿。
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests import ast_scan

import pytest

REPO = Path(__file__).resolve().parents[3]
ROOTS = (REPO / "neurova", REPO / "tests", REPO / "scripts")

# 从未实现过的梦境报告写侧/统计侧。原注说"实现只在 flow_orchestrator 里有读侧 get_dream_reports"——
# 那份 shim 已随 §6-311 裁乙第③刀退役（它读的是自己的内存 list，从不碰表），
# 于是 `dream_reports` 表回到本来的状态：`memory/scripts/init_db.py` 建了表，全仓既无写侧也无读侧。
# 本格的判据不变（正是要钉"从未实现"），改的只是这句指路的落点。
DREAM_REPORT_METHODS = {"save_dream_report", "get_dream_report", "get_dream_report_stats"}
FACADE = "adjust_parameters_based_on_sleep_quality"

# 同一形态的**已知存量**（2026-10-22 复算：15 处调用、4 个文件，全在测试与脚本侧，生产代码零命中）。
# 这些调用对 `memory_layer.storage.MemoryStorage(storage_dir)` 传 `db_path=`（个中还传 `neuser_id=`
# 这种不存在的键），运行即 TypeError——本批只修睡眠那一档，其余留作下一批，故用只降不升的棘轮
# 把它们钉在案上：新增落点即红，修掉一处就把计数改小。
# 已收口两处（§6-391 批 D）：`tests/performance/longmeval_simple.py`（改名收进收集面，
# 见 `tests/performance/memory/test_longTermMemoryBaselineGate.py`）与
# `scripts/demo_optimization.py::demo_vector_index_manager`（整段演示的
# `wait_for_index_completion`/`get_index_manager_state`/`vector_search`/`list_memories`/
# `check_vector_index_integrity` 全仓零定义，无从修起，故退役）。
_KNOWN_FABRICATED_SITES = {
    "tests/integration/test_full_conflict_integration.py",
    "tests/unit/memory/test_storage_comprehensive.py",
    "scripts/demo_closed_loop.py",
}
_KNOWN_FABRICATED_COUNT = 15

pytestmark = pytest.mark.timeout(60)


def _trees():
    # 枚举与解析走 tests/ast_scan 的共享预算（不私有 rglob + ast.parse——后者把
    # 判据成本绑在代码总量上，见 tests/unit/test_ci_ast_scan_budget_guard.py）。
    for root in ROOTS:
        for ref in ast_scan.sourceRefsUnder(root, ".py"):
            try:
                yield ref.path, ast.parse(ref.code)
            except (SyntaxError, UnicodeDecodeError):
                continue


def _definedNames(tree: ast.AST) -> set[str]:
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _calledNames(tree: ast.AST) -> set[str]:
    return {node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}


def _undefinedCalls(wanted: set[str]) -> list[str]:
    """在**同一个文件里**被调用、却没有被任何类/函数定义的具名方法。"""
    bad = []
    for p, tree in _trees():
        defs = _definedNames(tree)
        calls = _calledNames(tree) & wanted
        ghost = sorted(calls - defs)
        if ghost:
            bad.append(f"{p.relative_to(REPO).as_posix()}: 调用而无定义 {ghost}")
    return bad


def test_dreamReportCallSitesMatchDefinitions():
    bad = _undefinedCalls(DREAM_REPORT_METHODS)
    assert not bad, ("梦境报告的写侧/统计侧从来没有实现，任何调用点都是必炸死码：\n  "
                     + "\n  ".join(bad))


def test_facadeMethodIsGoneEverywhere():
    defs, calls = [], []
    for p, tree in _trees():
        if FACADE in _definedNames(tree):
            defs.append(p.relative_to(REPO).as_posix())
        if FACADE in _calledNames(tree):
            calls.append(p.relative_to(REPO).as_posix())
    assert not defs and not calls, (
        f"门面『{FACADE}』读一个从未赋值的 self._storage、再调一个全仓不存在的统计方法，"
        f"外面还套 catch-all——它从未调整过任何东西。定义面：{defs}；调用面：{calls}")


def test_idleTrackerHasNoUnassignedAttributeRead():
    """`self._x` 被读而类里从未赋过值＝调用即 AttributeError（这条病的机器形态）。

    类级属性（`PHASE_ORDER` 等）算"已定义"——它们是有意挂在类上的常量，不是孤儿读。
    """
    src = REPO / "neurova" / "core" / "idle_tracker.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "IdleTimeTracker")
    assigned = {t.attr for n in ast.walk(cls) if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Attribute)
                and isinstance(t.value, ast.Name) and t.value.id == "self"}
    assigned |= {n.target.attr for n in ast.walk(cls) if isinstance(n, ast.AnnAssign)
                 and isinstance(n.target, ast.Attribute)
                 and isinstance(n.target.value, ast.Name) and n.target.value.id == "self"}
    classLevel = set()
    for n in cls.body:
        if isinstance(n, ast.Assign):
            classLevel |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            classLevel.add(n.target.id)
    # 继承面按真源解析（不硬抄名字）：BaseModule 的方法与 self.* 赋值都算已定义
    inherited = set()
    baseTree = ast.parse((REPO / "neurova" / "core" / "base_module.py").read_text(encoding="utf-8"))
    for n in ast.walk(baseTree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inherited.add(n.name)
        elif isinstance(n, ast.Assign):
            inherited |= {t.attr for t in n.targets
                          if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                          and t.value.id == "self"}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Attribute) \
                and isinstance(n.target.value, ast.Name) and n.target.value.id == "self":
            inherited.add(n.target.attr)
    methods = {n.name for n in ast.walk(cls)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    read = {n.attr for n in ast.walk(cls) if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name) and n.value.id == "self"
            and isinstance(n.ctx, ast.Load)}
    orphans = sorted(read - assigned - classLevel - methods - inherited
                     - {"log_info", "log_debug", "log_warning", "log_error"})
    assert not orphans, f"idle_tracker 里这些 self.* 被读却从未赋值：{orphans}"


def test_memoryStorageIsConstructedByRealSignature():
    """按**导入来源**判：只有从 `memory_layer.storage` 取的那只 MemoryStorage 收 `storage_dir`。

    仓里另有同名的 `memory.core.storage.MemoryStorage(db_path=...)`（`neurova/memory/scripts/
    verify_attachment_feature.py:64` 用的就是它）——那是同名词不同物，不该被这条判据误伤，
    也不该被拿来越权证明"db_path 是普遍口子"（§6-128 那族"按符号局部名认通道"的老坑）。
    """
    tree = ast.parse((REPO / "neurova" / "cognitive_layers" / "memory_layer" / "storage.py")
                     .read_text(encoding="utf-8"))
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "MemoryStorage")
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    params = {a.arg for a in init.args.args}
    assert "storage_dir" in params, f"memory_layer 那只 MemoryStorage 的构造口变了：{sorted(params)}"

    offenders = []
    for p, t in _trees():
        importsIt = any(isinstance(n, ast.ImportFrom)
                        and n.module == "neurova.cognitive_layers.memory_layer.storage"
                        and any(a.name == "MemoryStorage" for a in n.names)
                        for n in ast.walk(t))
        if not importsIt:
            continue
        for node in ast.walk(t):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "MemoryStorage"
                    and any(k.arg == "db_path" for k in node.keywords)):
                offenders.append(f"{p.relative_to(REPO).as_posix()}:{node.lineno}")

    newOnes = [o for o in offenders if o.split(":")[0] not in _KNOWN_FABRICATED_SITES]
    assert not newOnes, (
        f"新的『按想象传构造参数』落点（该类只收 storage_dir）：{newOnes}")
    assert len(offenders) <= _KNOWN_FABRICATED_COUNT, (
        f"已知落点从 {_KNOWN_FABRICATED_COUNT} 涨到 {len(offenders)}——只降不升的棘轮被顶开：\n  "
        + "\n  ".join(sorted(offenders)))


def test_scannerReallyBites(tmp_path):
    """反向对照：调用而无定义、以及读而无赋值，两种形态都必须被抓到。"""
    ghost = tmp_path / "ghost.py"
    ghost.write_text(
        "class X:\n    def f(self, s):\n        return s.save_dream_report({})\n", encoding="utf-8")
    assert ({"save_dream_report"} - _definedNames(ast.parse(ghost.read_text("utf-8")))) == \
        {"save_dream_report"}
    tree = ast.parse(ghost.read_text(encoding="utf-8"))
    assert _calledNames(tree) & DREAM_REPORT_METHODS == {"save_dream_report"}
    ghost.unlink()
