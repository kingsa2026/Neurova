"""`neurova/benchmark` 的门面实装退役判据（票④第一包，用户裁定取甲＝退役）。

**为什么值得单独一档**：这个包 575 行里有 468 行是实现，全仓对它门面名字的取用只剩一处
——我自己上一批写的落点判据（`test_HomeFamilyLandingsFollowDataRoot.py` 构造 `BenchmarkFramework()`
钉 `_storage_dir` 落点）。生产面对 `BenchmarkFramework`/`get_benchmark_framework` 的取数是 **0**，
而 `neurova/api/endpoints/benchmark.py:106` 自己的注释就写着"真实评测执行器（neurova/benchmark 框架
+ LLM 答题打分）**未接线**，本端点不投机实现"。也就是说这份实装是**从未接通的框架**，
不是被谁摘了消费者。

**先比后合的比**（教义第 7 条要求先摆证据，别不比较就删弱者）：
- 现役评测那条活路是 `rag_eval.py`（数据集落盘、`evaluate_dataset` 打分）＋ `rag_dataset_gen.py`，
  由端点 9 处**子模块直取**消费，与本文件无 import 关系（实测：包内子模块无人回头取 `__init__` 的名字）；
- 门面侧独有的是 `_DEFAULT_SUITES` 那套硬编码题面（三段论之类）与一份 SQLite 运行历史持久面。
  题面是**玩具数据**、现役数据集走 `save_dataset` 由用户提供 ⇒ 并进来等于往活路里塞占位数据，
  故不并；运行历史那一面现役端点用进程内 `_RUNS_STORE`（重启即失），要真做持久评测台账
  是**新能力工作**（`core/agent_run_ledger` 已有台账先例可循），不在退役批里顺手造。
- ⇒ 判定＝退役；删掉的不是"能力"，是**一条从未接通、且其唯一数据是玩具题面的平行实现**。

判据形状（三格，两轨）：主格钉"实现不在门面里了，且全仓无人提名"；两枚交付锁钉"退役别把活路
一起删没"——RAG 那条子模块路必须仍可解析、真装配点里 benchmark 路由必须照常在册。
交付锁的失效方向由**删过头**提供：把 `rag_eval.py` 删了或把 router 摘了，它们就红。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

#: 本档在 `tests/unit/benchmark/` 下 ⇒ 仓根是 parents[3]（写成一层的 [2] 会得到 `tests/neurova/…`，
#: 三格全撞 FileNotFoundError——那是装配噪声，不是一条红判据）。
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
BENCH_INIT = REPO_ROOT / "neurova" / "benchmark" / "__init__.py"

#: 门面实装曾有的顶层名字（退役后**一个都不许再被代码引用**）。必须是 frozenset：
#: 上一版写成 tuple 却在判据里用 `&`，那一格其实一直停在 TypeError 上，什么都没判。
RETIRED_NAMES = frozenset({
    "BenchmarkFramework",
    "get_benchmark_framework",
    "reset_benchmark_framework",
    "BenchmarkStatus",
    "BenchmarkCategory",
    "BenchmarkSuite",
    "BenchmarkResult",
})


def _trackedFiles(suffix: str) -> list:
    import subprocess

    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p.endswith(suffix)]


def test_benchmarkFacadeHoldsNoImplementation():
    """主红①：`benchmark/__init__.py` 只剩包说明，不许还留着 class/def 实现。

    取 AST 而不是数关键词：docstring 与注释里出现 "BenchmarkFramework" 不算实现存在，
    按词判会把自己家的说明文档判红（本仓这一形跑过两遭）。
    """
    tree = ast.parse(BENCH_INIT.read_text(encoding="utf-8", errors="replace"))
    impl = [n.name for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))]
    assigned = [t.id for n in tree.body if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)]
    assert not impl, f"门面里还留着实现（{len(impl)} 个顶层定义）：{impl[:8]}"
    assert not assigned, f"门面里还留着模块级状态：{assigned[:8]}"


def _codeReferences(text: str) -> set:
    """一个文件里**以代码身份**出现的目标名字（不是注释、不是 docstring）。

    为什么必须按 AST 判而不是 `if name in text`：退役哨兵档自己就得写着那些退役名字，
    被退役的门面也要留一份"这里曾经是什么"的说明——按词判会把这两处自己判红。
    本仓同族的教训跑过两遭（按词判的守卫被自家文档撞红）。
    """
    found = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
                found.add(alias.name)
                if alias.asname:
                    found.add(alias.asname)
    return found


def test_noOneAnyMoreNamesTheRetiredSurface():
    """主红②：退役名字在全仓（生产＋测试）都不许再被**代码引用**——留一处就是留一条指向空气的引用。

    扫描面用 `git ls-files` 而不是 `rglob`：只认跟踪件，工作树里别人的在途新档不该由我判红。
    两处**必须**排除且理由不同：本哨兵档（它按定义就得写出那些名字）、
    被退役的门面 `__init__.py`（它留的是"这里曾经是什么"的分子说明，属文档不是引用）。
    """
    selfPath = pathlib.Path(__file__).resolve()
    offenders = []
    for rel in _trackedFiles(".py"):
        path = (REPO_ROOT / rel).resolve()
        if path == BENCH_INIT or path == selfPath or not path.exists():
            continue
        hit = RETIRED_NAMES & _codeReferences(path.read_text(encoding="utf-8", errors="replace"))
        if hit:
            offenders.append((rel, sorted(hit)))
    assert not offenders, (
        "这些文件还在**代码里**引用已退役的门面名字（改判或删除引用，别留着当指路牌）：%s" % offenders
    )


def test_liveRagEvalPathStillResolvesThroughSubmodules():
    """交付锁①：现役评测那条活路是子模块直取，退役门面不许把它一起带走。

    取的是**生产真正走的 import 形态**（端点里 9 处 `from neurova.benchmark.rag_eval import …`），
    名字按端点实际取用列，不在测试里自推一套。
    """
    from neurova.benchmark.rag_eval import evaluate_dataset, load_datasets, save_dataset
    from neurova.benchmark.rag_dataset_gen import generate_items

    assert callable(load_datasets) and callable(save_dataset)
    assert callable(evaluate_dataset) and callable(generate_items)


def test_benchmarkRoutesStillRegisteredInRealAssembly():
    """交付锁②：真装配点 `create_app()` 里 benchmark 路由照常在册。

    "在册"的取数面必须是 `app.openapi()["paths"]`——该 app 把 API 挂成一个 Mount，
    `app.routes` 顶层只给挂载点，按它数会得到 0 条并把探针骗成 FAIL。
    """
    from neurova.api.app import create_app

    app = create_app()
    paths = sorted(p for p in app.openapi()["paths"] if "/benchmark" in p)
    assert len(paths) >= 12, f"benchmark 路由现读 {len(paths)} 条（退役前应 ≥12）：{paths[:5]}"


def test_landingJudgmentNoLongerPinsTheRetiredLanding():
    """交付锁③：上一批那张落点判据不许留一枚指向已退役落点的悬空 pin。

    那张档当初为钉 `benchmark` 的 `_storage_dir` 裸相对落点而**构造** `BenchmarkFramework()`；
    实现退役后那个字段不存在了，判据若不同批改判就会退化成"永远测不到的形状检查"。
    这一格把"改判是否真做了"钉成会红的判据，而不是靠提交说明里的一句承诺。
    """
    landing = REPO_ROOT / "tests" / "unit" / "core" / "test_HomeFamilyLandingsFollowDataRoot.py"
    text = landing.read_text(encoding="utf-8", errors="replace")
    assert "BenchmarkFramework" not in text, (
        "落点判据还在提名已退役的 `BenchmarkFramework` ⇒ 那一格已经悬空，须同批改判"
    )
