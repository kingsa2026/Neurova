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


def _ledgerSource() -> str:
    return io.open(
        PROJECT_ROOT / "scripts" / "ci" / "tool_loop_deadline_ledger.py",
        encoding="utf-8",
    ).read()


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

    `agent/tool_pipeline.py` 里曾同时有死符号与活符号。**T-09 死码处置批已把死符号
    真删**，于是本组的前置事实从「同一文件里一死一活」变成「同一个退役动作之后，
    活符号原样活着」——这正是前置警告 1 要守的东西，只是形态从**空间**（同文件）
    移到了**时间**（同批退役）：判据若按文件一刀切，那次退役就会连带砍断熔断器的
    观测接线。故本组保留两条活线的反向钉住，并把「死符号已真删」也钉住。

    `DEAD_IN_FILE` 的判据类**必然**从 `no_consumer` 变成 `absent`——那不是口径放宽，
    是按纪律做了退役（`tests/unit/tools/test_t09_pipeline_face_ruling.py` 另有
    拥有者级判据与逐条论证）。故本组不再断言它停在 `no_consumer`。
    """

    DEAD_IN_FILE = "ToolExecutionPipeline"
    ALIVE_IN_FILE = ("notify_tool_result", "get_pipeline_observers")

    def test_alive_symbols_share_the_file_with_the_retired_one(self):
        """活符号仍在（与被退役符号**曾**同处的）那个文件里定义。

        这是前置警告 1 的时效形态：退役之后，那个文件必须还在、活符号必须还在
        ——若退役是按文件做的，这条会直接失败。
        """
        facts = _facts()
        fileOfRetired = "neurova/agent/tool_pipeline.py"
        assert facts[self.DEAD_IN_FILE]["origin"].startswith("agent/tool_pipeline.py"), (
            f"{self.DEAD_IN_FILE} 的登记出处变了（实测 {facts[self.DEAD_IN_FILE]['origin']}）"
        )
        for symbol in self.ALIVE_IN_FILE:
            paths = facts[symbol]["classify"]["def_files"]
            assert fileOfRetired in paths, (
                f"{symbol} 不再定义在 {fileOfRetired}——退役把活符号一起带走了"
                f"（实测定义文件 {paths}）"
            )

    def test_dead_symbol_is_retired_not_tolerated(self):
        """被点名的那条死符号必须**已从生产侧消失**，而不是停在原状。

        与 `test_dead_symbol_was_not_consumed_by_relaxed_judgement` 成对：
        这一条钉「它真的走了」，下一条钉「它不是靠放宽判据糊过去的」。
        """
        row = _facts()[self.DEAD_IN_FILE]
        assert row["judge"] == ledger.JUDGE_ABSENT, (
            f"{self.DEAD_IN_FILE} 判据类实测 {row['judge']}，未随 T-09 退场"
        )

    def test_dead_symbol_was_not_consumed_by_relaxed_judgement(self):
        """它**不得**被判成 `consumed`——那才是判据口径被放宽的形态。

        T-01 建判据时这一条断言的期望值是 `no_consumer`；T-09 退役后合法终局是
        `absent`。两种都是「口径没被放宽」的诚实读数，`consumed` 不是——所以断言
        从「必须等于 no_consumer」收窄为「必须属于 {no_consumer, absent}」，
        把原来的判别力（拒收 consumed）完整保留下来。
        """
        row = _facts()[self.DEAD_IN_FILE]
        assert row["judge"] in (ledger.JUDGE_NO_CONSUMER, ledger.JUDGE_ABSENT), (
            f"{self.DEAD_IN_FILE} 被判成 {row['judge']}：它不是「有定义零消费」，"
            "也没有被真删——而是被判据算成了可达，说明口径被放宽"
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
    """反向控制：已知**在生产侧存活**的符号，且不得被赋任何处置。"""

    #: 判据类的**存活**取值域：反向控制各自落在其中之一。
    #:
    #: 为什么不统一要求 `consumed`（Issue #310 收口）：`ctx_snapshot` 是**局部量**，
    #: 它的消费点天然落在自己函数内，判据类必然是 `self_loop` —— 要求它 `consumed`
    #: 等于要求把一个活在自己函数里的局部量接出函数外，那才是把它改坏。
    #: 本断言的原意是「判据不能空转」（预筛丢掉全部文件时会退化成 `absent`/`no_consumer`），
    #: 而「不是 `absent` 也不是 `no_consumer`」恰好就是那个原意的**机器可验形态**，
    #: 且对两类控制都成立——收窄成 `consumed` 是过严，不是更严。
    LIVE_JUDGES = (ledger.JUDGE_CONSUMED, ledger.JUDGE_SELF_LOOP)

    def test_controls_are_alive(self):
        facts = _facts()
        for symbol in ledger.REACHABLE_CONTROLS:
            assert facts[symbol]["judge"] in self.LIVE_JUDGES, (
                f"反向控制项 {symbol} 未被判为存活（{self.LIVE_JUDGES}），"
                f"实为 {facts[symbol]['judge']}（{facts[symbol]['classify']['rule']}）——"
                "判据整体失效（例如预筛丢掉全部文件）时正是这个形态，"
                "而单看「零消费」断言无法察觉。"
            )

    def test_liveJudgesAreNotVacuous(self):
        """`LIVE_JUDGES` 必须真的在判别：喂两个「死」判据类进来必须被拒。

        这条是本类上一条断言的反向控制——否则把 `LIVE_JUDGES` 改成「四个判据类全收」
        也能通过，该断言就退化成恒真。
        """
        assert ledger.JUDGE_ABSENT not in self.LIVE_JUDGES
        assert ledger.JUDGE_NO_CONSUMER not in self.LIVE_JUDGES

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


class TestSingleSourceScanIsLinearAndCached:
    """`_singleSourceDerivations` 的取数成本必须有界（本判据根因 = CI 单红超时）。

    根因：该函数对**每个文件**先 `ast.walk(tree)` 找函数节点，再对**每个函数**
    重新 `ast.walk(node)` 扫子树——内层遍历把外层已走过的节点又走一遍，
    嵌套函数被反复重访（实测 1.59M 节点里有 1.46M 是重复访问，≈92% 白干）。
    再叠加 `facts()` → `thresholdAxis()` → `_ctorBindings()` 每个登记符号各调一次
    （28 次全程重扫 1032 个生产文件），总节点访问量冲到 9.5M。

    单独跑（无覆盖率）约 9s，尚在 30s 全局阈值内；但 `--cov` 对每次 AST 遍历
    都挂行跟踪，同一路径实测 24.8s，CI 的 2 核 runner 上即翻过 30s 被判超时。
    故本判据钉的不是"耗时多少秒"（那随机器漂移），而是**根因形态**。

    **第二轮**（2026-10-03 构建 `cnb-7l9-1k3vmrra7` 实测）：「单趟 + 缓存」两条
    都已满足，CI 仍超时——因为真正的量纲不是"几趟"，而是**扫了多大面**。旧实现把
    全生产树（1030 文件 / 1.58M 节点）走完，为**每个**含下标的函数建条目（1540 条），
    而消费方 `_derivationCallKey()` 只认 `resolve` 前缀名——消费面只有 14 条，
    其余 1526 条**一生无人读**。故本片补第三条判据：扫描面必须收窄到消费面。
    """

    def test_subtreeIsNotRewalked(self, monkeypatch):
        """取数只允许单趟遍历：函数节点不得触发第二次子树 walk。"""
        import ast as ast_module

        walksPerNode = []
        realWalk = ast_module.walk

        def countingWalk(node):
            walksPerNode.append(1)
            return realWalk(node)

        # 只观察本功能的取数：清缓存后单跑一次，统计 walk 调用次数。
        monkeypatch.setattr(ledger.ast if hasattr(ledger, "ast") else ast_module,
                            "walk", countingWalk, raising=False)
        ledger._singleSourceDerivations.cache_clear() if hasattr(
            ledger._singleSourceDerivations, "cache_clear"
        ) else None

        files = [
            path for path in ledger.PRODUCTION_ROOT.rglob("*.py")
            if "__pycache__" not in path.parts
        ]
        try:
            ledger._singleSourceDerivations()
        finally:
            monkeypatch.undo()

        # 允许每个文件一趟树的 walk；重复子树遍历会让次数显著越过文件数。
        # 取 1.5 倍作余量（实现若略改结构也不至于误杀），但落在"每函数再走一遍"
        # 的形态上必然爆掉——那正是根因。
        assert len(walksPerNode) <= len(files) * 1.5, (
            f"`_singleSourceDerivations` 对 {len(files)} 个文件发起了 "
            f"{len(walksPerNode)} 次 ast.walk——内层按函数重走子树，"
            "单趟遍历的线性口径已被打破（CI 超时的根因）"
        )

    def test_repeatedTakeIsCached(self):
        """同一进程内重复取数必须命中缓存（`facts()` 每个符号各调一次）。"""
        assert hasattr(ledger._singleSourceDerivations, "cache_clear"), (
            "`_singleSourceDerivations` 未挂缓存——`facts()` 会为每个登记符号"
            "重扫全部生产文件，取数成本随符号数线性叠加"
        )
        ledger._singleSourceDerivations.cache_clear()
        first = ledger._singleSourceDerivations()
        second = ledger._singleSourceDerivations()
        assert first is second, "重复取数未命中缓存：每次都重新全仓扫描"

    def test_readingsSurviveTheRewrite(self):
        """根修不得改变取数结果：判据口径是单一事实源，只许更快。"""
        ledger._singleSourceDerivations.cache_clear()
        derivations = ledger._singleSourceDerivations()
        assert derivations.get("resolveToolRoundBudget") == "max_loop_rounds", (
            "单源派生点读数在优化后丢失——那是判据口径漂移，不是提速：\n  "
            + repr({k: v for k, v in derivations.items() if "Round" in k})
        )

    def test_scanSurfaceIsNarrowedToTheConsumptionSurface(self):
        """扫描面必须收窄到消费面：条目名一律落在 `_DERIVATION_PREFIXES` 上。

        根因（`cnb-7l9-1k3vmrra7`）：旧实现为**全仓每个含下标的函数**建条目
        （实测 1540 条），消费方只认 `resolve` 前缀——1526 条无人读的映射，
        代价却是整棵生产树（1.58M 节点）走一遍。CI 上带 `--cov` 即越过 30s。

        判据钉的是**每条映射都必须可能被消费**：名字不以消费前缀起头的条目，
        在 `_derivationCallKey()` 里首行就被 `startswith` 挡掉——它不可能是读数，
        只能是与代码总量成正比的空转。这条同时把"预筛是否真的生效"钉住：
        预筛若失效，全仓非 `resolve` 文件会被重新纳入，条目数立刻爆回去。
        """
        ledger._singleSourceDerivations.cache_clear()
        derivations = ledger._singleSourceDerivations()
        unconsumable = sorted(
            name for name in derivations
            if not name.startswith(ledger._DERIVATION_PREFIXES)
        )
        assert not unconsumable, (
            f"取数里混进了 {len(unconsumable)} 条**消费方永不可能读到**的映射"
            f"（消费前缀 {ledger._DERIVATION_PREFIXES}）：{unconsumable[:10]}\n"
            "——扫描面未收窄到消费面，取数成本重新与代码总量挂钩（CI 超时根因）"
        )

    def test_prefilterActuallyShrinksTheParseSurface(self):
        """文本预筛必须真的少解析文件：否则条目数会随代码总量线性涨回去。"""
        from tests import ast_scan

        total = len(ast_scan.sourceRefsUnder(
            ledger.PRODUCTION_ROOT, suffix=".py"))
        scanned = len(ast_scan.sourceRefsUnder(
            ledger.PRODUCTION_ROOT, suffix=".py",
            hints=ledger._DERIVATION_PREFIXES))
        assert scanned < total, (
            f"预筛未生效：生产根 {total} 个文件全被纳入解析面。"
            "函数名以消费前缀起头 ⇒ 文本必含它，不含它的文件不可能有派生点。"
        )
        assert scanned * 2 <= total, (
            f"预筛面 {scanned}/{total} 过宽——预期不超过半数。"
            "预筛失效时取数成本重新随代码总量增长（CI 超时根因）"
        )


class TestLedgerHasNoShadowedDefinitions:
    """台账脚本不得有同名定义互相遮蔽（修复教义第 6 条）。

    根因：本文件曾并存两份 `_singleSourceDerivations` / `_DERIVATION_PREFIXES` /
    `_derivationCallKey` / `_ctorBindings`——后一份静默遮蔽前一份，于是"改了一处、
    生效的是另一处"。这类第二份定义不会报错，只会让根修落在死码上，故必须机器钉住。
    """

    def test_noDuplicateTopLevelDefinitions(self):
        import ast as ast_module
        import collections

        src = _ledgerSource()
        tree = ast_module.parse(src)
        names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast_module.FunctionDef, ast_module.AsyncFunctionDef, ast_module.ClassDef))
        ]
        duplicates = {name: count for name, count in collections.Counter(names).items() if count > 1}
        assert not duplicates, (
            f"台账脚本存在同名顶层定义（后者静默遮蔽前者，根修会落在死码上）：{duplicates}"
        )

    def test_noDuplicateModuleLevelConstants(self):
        import ast as ast_module
        import collections

        src = _ledgerSource()
        tree = ast_module.parse(src)
        names: list = []
        for node in tree.body:
            if isinstance(node, ast_module.Assign):
                for target in node.targets:
                    if isinstance(target, ast_module.Name):
                        names.append(target.id)
        duplicates = {name: count for name, count in collections.Counter(names).items() if count > 1}
        assert not duplicates, f"台账脚本存在同名模块级常量定义：{duplicates}"
