# -*- coding: utf-8 -*-
"""受保护子集里的跨文件 AST 判据必须走共享解析预算（Issue #148）。

根因（不是形状）：受保护子集里有若干个「单源 / 收口点」判据，判据内容是
「仓库里不得出现第二处实现」，实现方式却是**把全仓每个 `.py` 都 `ast.parse`
一遍、再 `ast.walk` 一遍**。实测解析成本 ≈ 1.4 ms/文件（本机 1000 文件 ≈ 1.4s、
2000 文件 ≈ 2.9s），词法遍历再叠 1.5 倍，于是**代码总量被编码成了时间上界**：

- 单跑这些用例本机 4–6s（`test_rsi_rollback_evidence` 4.4s、
  `test_write_boundary_closes_verification` 5.0s、`test_dead_cache_module_removed` 4.5s、
  `test_rsi_observation_surface` 5.4s、`test_capability_cache_single_source` 5.1s）；
- 与另外 170 个受保护文件共享机器、按 `-q` 一次性跑时，撞 `pytest-timeout`
  的默认 30s 墙钟——2026-09-22 构建 `cnb-2p6-1k347lfg1` 实测转红：
  `Failed: Timeout (>30.0s) from pytest-timeout`。

这不是「跑得慢」，是**判据与机器速度捆绑**（`AGENTS.md` 修复教义第 2 条点名的
「降级/绕开断言」的近亲）：判据本身与代码行数、与机器快慢都无关，墙钟上界
不会因为它变松而更成立，只会把真实的超时回归一起放行。

处置：解析单源到 `tests/ast_scan.py`（`AGENTS.md` 第 6 条：不新造平行体系）。
本守卫锁住**形态**而非具体秒数——判据不空转、不靠机器快慢：

1. **无预筛的全仓 `rglob + ast.parse` 归零**：受保护子集里出现新的一处即红；
2. **共享预算入口真实可用**：`callSites` / `importsOf` / `classDefsIn` 必须存在且
   能真报出命中（否则各守卫会退回各写一套，本门禁退化成空规则）；
3. **预筛不得漏报**：预筛是**充分条件**——谓词是 `X.<name>`，连 `<name>` 都没
   出现的文件不可能命中。故用「注入一个真实命中 + 一个不含关键词的文件」自证。
"""
from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests import ast_scan

PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 允许保留的「rglob + ast.parse」全仓扫描：**空集是默认政策**。
#: 确需保留者必须逐条写明理由，并说明为何不能走 `tests/ast_scan.py` 的预筛。
REPO_WIDE_SCAN_LEDGER: dict = {}  # type: ignore[type-arg]


def protectedFiles() -> list:
    """CI 实际跑的受保护子集（唯一事实源，不另建清单）。"""
    return [line.split("#", 1)[0].strip()
            for line in io.open(PROTECTED, encoding="utf-8").read().splitlines()
            if line.split("#", 1)[0].strip()]


def _repoWideAstScans(source: str) -> list:
    """文件里「`rglob(...)` + `ast.parse(...)` 同处一个用例」的用例名。"""
    hits = []
    for func in ast.walk(ast.parse(source)):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not func.name.startswith("test"):
            continue
        calls = {node.func.attr for node in ast.walk(func)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        if "rglob" in calls and "parse" in calls:
            hits.append(func.name)
    return sorted(hits)


class TestNoUnprefilteredRepoWideScan:
    """受保护子集里的全仓 AST 扫描归零：判据不得与代码总量捆绑。"""

    def test_no_unledgered_repo_wide_ast_scan(self):
        live = {}
        for rel in protectedFiles():
            path = PROJECT_ROOT / rel
            if not path.is_file() or not rel.endswith(".py"):
                continue
            try:
                source = io.open(path, encoding="utf-8", errors="ignore").read()
                hits = _repoWideAstScans(source)
            except SyntaxError:
                continue
            if hits:
                live[rel] = hits
        unledgered = {rel: hits for rel, hits in live.items() if rel not in REPO_WIDE_SCAN_LEDGER}
        assert not unledgered, (
            "受保护子集里出现「rglob + ast.parse」全仓扫描（判据与代码总量、"
            "与机器速度捆绑，30s 默认墙钟下必偶发红）:\n  "
            + "\n  ".join(f"{rel} → {hits}" for rel, hits in sorted(unledgered.items()))
            + "\n修法：走 tests/ast_scan.py（callSites / importsOf / classDefsIn / nodeScan(hints=...)）;"
            "\n确需保留时登记进 REPO_WIDE_SCAN_LEDGER 并写明为何预筛不适用。"
        )

    def test_ledger_has_no_stale_entries(self):
        """台账里不得有已经不存在命中点的条目（清了扫描要同步销账）。"""
        live = {}
        for rel in protectedFiles():
            path = PROJECT_ROOT / rel
            if not path.is_file() or not rel.endswith(".py"):
                continue
            try:
                source = io.open(path, encoding="utf-8", errors="ignore").read()
                hits = _repoWideAstScans(source)
            except SyntaxError:
                continue
            if hits:
                live[rel] = hits
        stale = sorted(set(REPO_WIDE_SCAN_LEDGER) - set(live))
        assert not stale, f"台账登记了已不存在的全仓扫描：{stale}"


class TestTextCacheIsOnTheHotPath:
    """跨判据复用的文本缓存必须真被热路径读到（写了不读 = 断点）。

    根因（同根新命中点）：`sourceRefsUnder` 一度**绕开**本模块自己的
    `_cachedCode`，逐次 `path.read_text()`。于是「同进程里 N 个跨文件判据
    只读盘一次」是纸面承诺 —— 实测 20 个登记符号读盘 **20140 次**
    （生产树里只有 1007 个文件）。读写同源一处定义，却只有写侧（缓存）
    没有读侧（消费），正是协作红线点名的断点。
    """

    def test_sourceRefsUnder_reuses_the_text_cache(self, tmp_path):
        for i in range(3):
            (tmp_path / f"m{i}.py").write_text(f"V{i} = {i}\n", encoding="utf-8")
        ast_scan._cachedCode.cache_clear()
        ast_scan.sourceRefsUnder(tmp_path, hints=("V0",))
        info = ast_scan._cachedCode.cache_info()
        assert info.misses == 3, (
            "`sourceRefsUnder` 没走 `_cachedCode`：它把每份源码都重新读盘一次，"
            f"文本缓存形同不存在（实测 misses={info.misses}，应为文件数 3）。\n"
            "修法：`sourceRefsUnder` 用 `_cachedCode(_cacheKey(path))` 取文本，"
            "与 `sourceCode` 同源。"
        )

    def test_repeated_hint_scans_read_each_file_once(self, tmp_path):
        for i in range(4):
            (tmp_path / f"m{i}.py").write_text(f"TARGET_{i} = {i}\n", encoding="utf-8")
        ast_scan._cachedCode.cache_clear()
        for hint in ("TARGET_0", "TARGET_1", "TARGET_2", "TARGET_3"):
            ast_scan.sourceRefsUnder(tmp_path, hints=(hint,))
        info = ast_scan._cachedCode.cache_info()
        assert info.misses == 4, (
            "同一棵树被 4 个判据各读一遍：读盘次数随**判据数**增长而不是随"
            f"**文件数**收敛（实测 misses={info.misses}，应为 4）。"
        )


class TestRelativeToRepoIsMemoized:
    """`relativeToRepo` 必须按路径记忆化：调用次数不得与**节点数**挂钩。

    根因：调用方（如 `context_deadline_ledger._rawNodes`）在**逐节点**的循环里
    调它，`Path.relative_to` 每次都要重新解析路径（实测 249547 次调用 ≈ 2.2s，
    占该取数整体耗时的一半）。

    收口点必须在**共享源**：若只在某个消费方加一层镜像缓存，别的消费方
    （`tests/unit/llm/test_capability_cache_single_source.py` 等也逐节点取它）
    照样按节点付账 —— 那是 consumer-only guard 的形态。
    """

    def test_same_path_is_computed_once(self):
        target = ast_scan.REPO_ROOT / "tests" / "ast_scan.py"
        ast_scan.relativeToRepo.cache_clear()
        calls = {"n": 0}
        real = Path.relative_to

        def counting(self, *args, **kwargs):
            calls["n"] += 1
            return real(self, *args, **kwargs)

        Path.relative_to = counting
        try:
            for _ in range(50):
                ast_scan.relativeToRepo(target)
        finally:
            Path.relative_to = real
        assert calls["n"] == 1, (
            f"同一路径调 50 次却算了 {calls['n']} 次相对路径——未记忆化，"
            "调用方一旦在逐节点循环里用它，耗时即与节点数成正比。"
        )

    def test_call_count_does_not_track_node_count(self):
        """反向控制：**节点数**涨时，`relativeToRepo` 调用次数不得涨。"""
        path = ast_scan.REPO_ROOT / "neurova" / "context" / "orchestrator.py"
        nodes = list(ast_scan._cachedNodes(ast_scan.SourceRef(
            path, ast_scan._cacheKey(path), ast_scan.sourceCode(path))))
        assert len(nodes) > 1000, f"夹具节点数太少（{len(nodes)}），判不出随节点增长"

        ast_scan.relativeToRepo.cache_clear()
        seen = []
        real = Path.relative_to

        def counting(self, *args, **kwargs):
            seen.append(self)
            return real(self, *args, **kwargs)

        Path.relative_to = counting
        try:
            for _ in nodes:
                ast_scan.relativeToRepo(path)
        finally:
            Path.relative_to = real
        assert len(seen) == 1, (
            f"{len(nodes)} 个节点调了 {len(seen)} 次相对路径——调用次数随节点数增长，"
            "正是墙钟超时的来源（缓存清空后，同一路径只该真实计算一次）。"
        )


class TestSharedParseBudgetIsReal:
    """共享预算入口必须真能用，否则各守卫会退回各写一套（门禁空转）。"""

    def test_helper_surface_exists(self):
        for name in ("callSites", "importsOf", "classDefsIn", "nodeScan",
                     "sourceRefsUnder", "relativeToRepo", "filesUnder"):
            assert hasattr(ast_scan, name), (
                f"tests/ast_scan.py 未提供 {name}：跨文件判据没有共享入口，"
                "本门禁会退化成一条空规则。"
            )

    def test_prefilter_is_sufficient_not_a_loophole(self, tmp_path):
        """预筛是**充分条件**：命中必定在，未命中的文件确实不含关键词。

        反向控制：注入一个真实命中（含关键词）必须被报出；同时确认
        `sourceRefsUnder` 的预筛**只**按关键词缩面，不是把所有文件都丢掉。
        """
        (tmp_path / "hit.py").write_text(
            "def f(x):\n    return x.attest()\n", encoding="utf-8")
        (tmp_path / "miss.py").write_text(
            "def g(x):\n    return x.other()\n", encoding="utf-8")

        hits = ast_scan.callSites(tmp_path, "attest")
        assert [path.name for path, _line in hits] == ["hit.py"], (
            f"预筛漏掉了真实命中或放行了未命中文件：{hits}"
        )
        assert {ref.path.name for ref in ast_scan.sourceRefsUnder(tmp_path, hints=("attest",))} \
            == {"hit.py"}, "文本预筛口径失效（应只留下一处含关键词的文件）"

    def test_class_defs_helper_finds_top_level_only(self, tmp_path):
        """`classDefsIn` 只认顶层类定义：嵌套同名类不算「另一份实现」。"""
        (tmp_path / "mod.py").write_text(
            "class Probe:\n    pass\n\n\ndef f():\n    class Probe:\n        pass\n",
            encoding="utf-8")
        hits = ast_scan.classDefsIn(tmp_path, "Probe")
        assert [line for _path, line in hits] == [1], (
            f"`classDefsIn` 应只认顶层定义，实际：{hits}"
        )

    def test_imports_helper_ignores_mentions_in_strings_and_comments(self, tmp_path):
        """判据是 `import` 语句：字符串/注释里提一句不算引用。"""
        (tmp_path / "mention.py").write_text(
            '# import neurova.performance\n'
            'NOTE = "neurova.performance"\n',
            encoding="utf-8")
        (tmp_path / "real.py").write_text(
            "import neurova.performance\n", encoding="utf-8")
        hits = ast_scan.importsOf(
            ast_scan.nodeScan(tmp_path, hints=("neurova.performance",)),
            "neurova.performance")
        assert [path.name for path, _line in hits] == ["real.py"], (
            f"`importsOf` 把文本提及当成了引用（假阳性）或漏了真实 import：{hits}"
        )


class TestSharedBudgetIsReusedWithinOneProcess:
    """同进程内 N 个判据扫同一棵子树，解析只付一次（这正是「预算」的含义）。"""

    def test_repeated_scan_hits_the_cache(self, tmp_path):
        (tmp_path / "a.py").write_text("def f(x):\n    return x.attest()\n", encoding="utf-8")
        ast_scan.callSites(tmp_path, "attest")
        before = ast_scan._cachedNodes.cache_info()
        ast_scan.callSites(tmp_path, "attest")
        after = ast_scan._cachedNodes.cache_info()
        assert after.hits > before.hits, (
            "第二次扫描没有命中节点缓存——「跨用例复用一次解析」不成立，"
            "本预算就成了纸面承诺。"
        )


@pytest.mark.parametrize("rel", [
    "tests/unit/knowledge/test_write_boundary_closes_verification.py",
    "tests/unit/core/test_dead_cache_module_removed.py",
    "tests/unit/evolution/rsi/test_rsi_observation_surface.py",
    "tests/unit/evolution/rsi/test_rsi_rollback_evidence.py",
    "tests/unit/llm/test_capability_cache_single_source.py",
    "tests/unit/test_ci_thin_env_guards.py",
    "tests/unit/test_dev_path_and_runtime_dep_guards.py",
])
def test_known_hit_points_use_the_shared_budget(rel):
    """本次收口的命中点必须一直用共享预算（改回全仓 rglob+parse 即红）。"""
    source = io.open(PROJECT_ROOT / rel, encoding="utf-8").read()
    assert "ast_scan" in source, (
        f"{rel} 不再使用 tests/ast_scan.py 的共享解析预算——"
        "跨文件 AST 判据又各写一套，Issue #148 的根因会回来。"
    )
    assert not _repoWideAstScans(source), (
        f"{rel} 又出现了 rglob + ast.parse 的同用例组合：{_repoWideAstScans(source)}"
    )
