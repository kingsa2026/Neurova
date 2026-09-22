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
