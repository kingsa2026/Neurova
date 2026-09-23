# -*- coding: utf-8 -*-
"""T-01：工具/loop 域「死线」判据必须与台账同源、双向钉住（Issue #175）。

## 为什么这道守卫（根因，不是形状）

上下文域（B6-1）已趟通一条可机器验证的死线处置闭环，形态是**两轴分离**：
判据类由 `classify()` 机器算、台账照抄且不一致即报红。本片把它复用到工具/loop 域，
因为该域正是「定义了、导出了、生产零调用」的重灾面（`UnifiedToolRegistry` /
`ToolSchemaConverter` / `ToolCallParser` / `CostTrackingMixin` / `ToolExecutionPipeline` …），
而此前没有任何判据会发现它们——grep 名字数引用既会漏（同名第二份）也会误杀
（同名第二份的真实现）。

本守卫钉四条**机器可复算**的形态：

1. **判据类与实测一致**：台账那一列必须等于机器算的（人改台账去迎合 = 把判据
   降级成自述，故反过来查）。
2. **引用点数与实测一致**：本片显式要求「登记的引用点数与实测不符即报红」——
   处置进展与判据口径两件事都不许静默漂移。
3. **判据落到符号级，不是文件级**：`neurova/agent/tool_pipeline.py` 同一文件内
   `ToolExecutionPipeline`（:202）生产零调用，而 `notify_tool_result`（:460）与
   `get_pipeline_observers`（:443）是活的（被 `tool_executor.py` 与
   `security/tool_circuit_breaker.py` 消费）。按文件判「死」会连带砍断熔断器的
   观测接线——故这两条必须是反向控制：永远 `consumed` 且永远「待处置」。
4. **扫描限径**：`NeurUI/src-tauri/**/backend/neurova/` 下是整套字节偏移的运行时
   副本，不带生产根约束的扫描会把副本算成消费点。判据只认 `neurova/` 前缀
   （`tests/ast_scan.py` 的单源），故每个引用点都必须落在生产根内。

判据口径不在这里复制：一律取 `scripts/ci/tool_loop_deadline_ledger.py` 的
`facts()` / `readLedger()` / `classify()`（单一事实源）。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import tool_loop_deadline_ledger as ledger  # noqa: E402

PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
GUARD_REL = "tests/unit/tools/test_tool_loop_deadline_ledger.py"


def _facts() -> dict:
    return {str(row["symbol"]): row for row in ledger.facts()}


class TestJudgeIsMachineComputed:
    """判据类由机器算、台账照抄：两者不一致即判据口径漂移。"""

    def test_ledger_matches_computed_judge_classes(self):
        problems = ledger.reconcile()["judge_conflict"]
        assert not problems, (
            "台账的判据类与机器算出来的不一致——判据是从 AST 事实取的，台账必须照抄；"
            "改台账去迎合等于把判据降级成自述：\n  "
            + "\n  ".join(
                f"{p['symbol']}: 台账 {p['ledger']} / 实测 {p['computed']}"
                f"（{p['rule']}）" for p in problems)
        )

    def test_ledger_matches_measured_reference_counts(self):
        """本片显式要求：登记的引用点数与实测不一致即红。"""
        problems = ledger.reconcile()["count_conflict"]
        assert not problems, (
            "台账登记的引用点数与实测不符——处置进展与判据口径已经漂移：\n  "
            + "\n  ".join(
                f"{p['symbol']}: 台账 {p['ledger']} / 实测 {p['measured']}"
                for p in problems)
        )

    def test_ledger_matches_computed_threshold_axis(self):
        """第二判据轴同样由机器算：台账与实测不一致即红。

        这条由**变异实测**补上：初版守卫只断言了判据类与引用点数，把台账的
        `scaled_sparse` 手改成 `scaled_unreachable` 时 `reconcile()` 已报
        `threshold_conflict`，**守卫却全绿**——第二轴于是成了无人守的人填列
        （正是本片要避免的形态）。现补上该断言，变异即红。
        """
        problems = ledger.reconcile()["threshold_conflict"]
        assert not problems, (
            "台账的第二轴（阈值可达性）与机器算出来的不一致：\n  "
            + "\n  ".join(
                f"{p['symbol']}: 台账 {p['ledger']} / 实测 {p['computed']}（{p['reason']}）"
                for p in problems)
        )

    def test_ledger_kind_matches_measured_kind(self):
        """取数口径（种类）也是机器算的：台账写错种类会让判据按错口径取数。"""
        problems = ledger.reconcile()["kind_conflict"]
        assert not problems, (
            "台账的种类与实测不符（判据按错口径取数）：\n  "
            + "\n  ".join(
                f"{p['symbol']}: 台账 {p['ledger']} / 实测 {p['computed']}"
                for p in problems)
        )

    def test_every_registered_symbol_has_a_ledger_row(self):
        problems = ledger.reconcile()["not_registered"]
        assert not problems, (
            f"登记符号缺台账条目（论证缺位）：{[p['symbol'] for p in problems]}"
        )

    def test_ledger_has_no_row_without_registered_symbol(self):
        problems = ledger.reconcile()["missing"]
        assert not problems, (
            f"台账条目不在登记符号表里（僵尸行）：{[p['symbol'] for p in problems]}"
        )

    def test_every_row_states_a_basis(self):
        problems = ledger.reconcile()["empty_basis"]
        assert not problems, (
            "台账条目没有依据——「单独论证可达性」变成了空话："
            f"{[p['symbol'] for p in problems]}"
        )

    def test_disposals_are_from_the_finite_enum(self):
        problems = ledger.reconcile()["unknown_disposal"]
        assert not problems, f"处置不在有限枚举内（机器无法判定）：{problems}"


class TestJudgeIsSymbolScopedNotFileScoped:
    """前置警告 1：判据必须落到符号级。

    同一文件里既有死符号（`ToolExecutionPipeline`）也有活符号
    （`notify_tool_result` / `get_pipeline_observers`）。若判据按文件一刀切，
    砍掉「死文件」就会连带砍断熔断器的观测接线——故本组反向钉住两条活线。
    """

    DEAD_IN_FILE = "ToolExecutionPipeline"
    ALIVE_IN_FILE = ("notify_tool_result", "get_pipeline_observers")

    def test_dead_and_alive_symbols_share_a_file(self):
        facts = _facts()
        paths = {
            "dead": facts[self.DEAD_IN_FILE]["classify"]["def_files"],
            "alive": [
                path for symbol in self.ALIVE_IN_FILE
                for path in facts[symbol]["classify"]["def_files"]
            ],
        }
        assert set(paths["dead"]) == set(paths["alive"]), (
            "前置事实变了：本组要钉的正是「同一文件内既有死符号也有活符号」，"
            f"实测 dead={paths['dead']} alive={set(paths['alive'])}"
        )

    def test_dead_symbol_is_not_consumed(self):
        row = _facts()[self.DEAD_IN_FILE]
        assert row["judge"] == ledger.JUDGE_NO_CONSUMER, (
            f"{self.DEAD_IN_FILE} 的判据类变了（实测 {row['judge']}）："
            "本片只建判据不做处置，若它被判成 consumed 说明判据口径被放宽"
        )

    def test_alive_symbols_are_consumed(self):
        for symbol in self.ALIVE_IN_FILE:
            row = _facts()[symbol]
            assert row["judge"] == ledger.JUDGE_CONSUMED, (
                f"{symbol} 未被判为 {ledger.JUDGE_CONSUMED}，实为 {row['judge']}"
                f"（{row['classify']['rule']}）——它与死符号同处一个文件，"
                "按文件判「死」会连带砍断熔断器的观测接线"
            )


class TestScanIsScopedToProductionRoot:
    """前置警告 2：扫描必须限径，否则运行时副本会被算成消费点。"""

    def test_production_root_is_the_only_scan_root(self):
        assert ledger.SCAN_ROOTS == (ledger.PRODUCTION_ROOT,), (
            f"判据扫描根不止生产根：{ledger.SCAN_ROOTS}——"
            "运行时副本目录下的同名文件会被算成消费点"
        )

    def test_every_reference_site_is_inside_production_root(self):
        outside = [
            f"{symbol}: {site.path}:{site.line}"
            for row in ledger.facts()
            for symbol in (str(row["symbol"]),)
            for site in ledger.referenceSites(symbol)
            if not ledger.inProductionScope(site.path)
        ]
        assert not outside, (
            "引用点落在生产根之外（判据被扩到测试/文档/运行时副本）：\n  "
            + "\n  ".join(outside)
        )

    def test_scopePredicateRejectsSyntheticOutsidePaths(self):
        """反向控制：限径判据必须真的认得出生产根之外的路径（合成输入）。"""
        for rel in (
            "tests/unit/tools/test_tool_loop_deadline_ledger.py",
            "NeurUI/src-tauri/resources/backend/neurova/tool_executor.py",
            "scripts/ci/tool_loop_deadline_ledger.py",
            "docs/INDEX.md",
        ):
            assert not ledger.inProductionScope(rel), f"限径判据放行了生产根之外的路径：{rel}"
        assert ledger.inProductionScope("neurova/tool_executor.py")


class TestJudgeRulesAreDecidable:
    """判据规则本身可复算：同一份代码两次取数一致；四值的边界各自钉一条。"""

    def test_repeated_take_is_stable(self):
        first = {str(r["symbol"]): r["judge"] for r in ledger.facts()}
        second = {str(r["symbol"]): r["judge"] for r in ledger.facts()}
        assert first == second, "同一进程内两次取数结论不同——判据不确定"

    @staticmethod
    def _classifyWith(forms):
        """用合成的引用事实复算 `classify()`，不拿仓库现状当输入。

        每个元素是 `(形态, 文件名)`：三值组的 `def` 默认落在 `neurova/probe_home.py`，
        其余默认落在**同一文件**；需要「跨文件」时显式给第二个文件名。判据的骨就是
        「消费点是否落在定义文件之外」，故合成输入必须能把两种情形都造出来。
        """
        site = ledger.RefSite
        original = ledger.referenceSites
        home = "neurova/probe_home.py"

        def _sites():
            built = []
            for i, item in enumerate(forms):
                form, path = item[0], (item[1] if len(item) > 1 else home)
                built.append(site(path=path, line=i + 1, form=form))
            return tuple(built)

        try:
            ledger.referenceSites = lambda _symbol: _sites()
            return ledger.classify("probe")
        finally:
            ledger.referenceSites = original

    def test_absent_rule_does_not_require_zero_references(self):
        """`absent` 说的是「无定义、无赋值」，不是「零引用」。"""
        judge, detail = self._classifyWith([("call",), ("import",)])
        assert judge == ledger.JUDGE_ABSENT, (
            "有消费点但无定义必须判 absent；判成可达会让「有调用方、没有实现」"
            "这一类永久漏检"
        )
        assert detail["rule"] == "1 · 无定义、无赋值"

    def test_no_consumer_rule_separates_writes_from_reads(self):
        """只写不读必须与「跨文件可达」分开——否则本域最大的死线面会自称可达。"""
        judge, detail = self._classifyWith([("def",), ("write",), ("write",)])
        assert judge == ledger.JUDGE_NO_CONSUMER, (
            f"有定义、只有写入没有读取必须判 {ledger.JUDGE_NO_CONSUMER}，实测 {judge}"
        )
        assert detail["rule"] == "2 · 有定义/赋值，零消费点"

    def test_self_loop_rule_requires_same_file_consumption(self):
        judge, detail = self._classifyWith([("def",), ("read",)])
        assert judge == ledger.JUDGE_SELF_LOOP, f"消费点全在定义文件内应判 self_loop，实测 {judge}"
        assert detail["rule"] == "3 · 消费点全在自己定义文件内"

    def test_consumed_rule_requires_cross_file_consumption(self):
        judge, detail = self._classifyWith([("def",), ("read",), ("call", "neurova/probe_consumer.py")])
        assert judge == ledger.JUDGE_CONSUMED, f"跨文件消费应判 consumed，实测 {judge}"
        assert detail["rule"] == "4 · 存在跨文件消费点"

    def test_isolated_import_is_not_a_consumer(self):
        """孤立 `import` 只是再导出：同文件内没有别的引用时不算消费。"""
        judge, _ = self._classifyWith([("def",), ("import",), ("import", "neurova/probe_reexport.py")])
        assert judge == ledger.JUDGE_NO_CONSUMER, (
            "只有 import、没有调用/读取的符号被判成可消费——再导出会被算成使用"
        )
        judge, _ = self._classifyWith(
            [("def",), ("import", "neurova/probe_reexport.py"), ("read", "neurova/probe_reexport.py")]
        )
        assert judge == ledger.JUDGE_CONSUMED, (
            "同文件内除 import 外还有读取时，该 import 才算消费点"
        )


class TestReachableControlsAreNotVacuouslyGreen:
    """反向控制：已知可达的符号必须报 `consumed`，且不得被赋任何处置。"""

    def test_controls_are_consumed(self):
        facts = _facts()
        for symbol in ledger.REACHABLE_CONTROLS:
            assert facts[symbol]["judge"] == ledger.JUDGE_CONSUMED, (
                f"反向控制项 {symbol} 未被判为 {ledger.JUDGE_CONSUMED}，"
                f"实为 {facts[symbol]['judge']}（{facts[symbol]['classify']['rule']}）——"
                "判据整体失效（例如预筛丢掉全部文件）时正是这个形态，"
                "而单看「零消费」断言无法察觉。"
            )

    def test_controls_carry_no_disposal(self):
        problems = ledger.reconcile()["pending_controls"]
        assert not problems, (
            f"反向控制项被赋了处置 {problems}——它们本来就在生产链路上跑，"
            "任何处置动作都说明判据或台账被改坏了。"
        )

    def test_scope_is_not_vacuous(self):
        rows = ledger.facts()
        assert len(rows) >= 14, f"登记符号过少（判据空转）：{len(rows)}"
        assert len(ledger.readLedger()) == len(rows), (
            "台账条目数与登记符号数不等——双向钉住失去意义"
        )


class TestLedgerRegistrationIsDeferredToT10:
    """本片新测试不进受保护子集：登记动作统一由 T-10 收口（Issue #174 红线 2）。"""

    def test_guard_is_not_registered_in_this_wave(self):
        raw = io.open(PROTECTED, encoding="utf-8").read()
        listed = {
            line.split("#", 1)[0].strip()
            for line in raw.splitlines()
            if line.split("#", 1)[0].strip()
        }
        assert GUARD_REL not in listed, (
            f"{GUARD_REL} 被登记进受保护子集了——本片（T-01）只建判据，"
            "登记动作统一放 T-10；且 AGENTS.md 第 3 条要求红灯文件转绿前不得进清单。"
        )

    def test_guard_readings_are_falsifiable(self):
        """自证：本文件的断言真的能红（合成输入，不靠仓库现状）。"""
        with pytest.raises(AssertionError):
            assert ledger.JUDGE_NO_CONSUMER == ledger.JUDGE_CONSUMED
        assert ledger.inProductionScope("neurova/agent/gates.py") is True
