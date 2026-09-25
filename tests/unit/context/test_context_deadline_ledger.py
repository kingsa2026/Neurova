# -*- coding: utf-8 -*-
"""B6-1：上下文域死线三态台账必须与判据同源、双向钉住。

## 为什么需要这道守卫

审计 §10 对 B6 的要求是「每个孤儿需**单独论证可达性**」。这条要求有两种都会
静默失效的退化形态，本守卫各钉一条：

1. **判据退化成人填的自述** —— 台账里那一列"三态"若由人手写，那它就不是判据，
   而是结论。故本批把轴拆开：判据类由 `scripts/ci/context_deadline_ledger.py`
   的 `classify()` 机器算，台账照抄；**不一致即报红**（人改台账去迎合就把
   判据降级成了自述，所以反过来查）。
2. **反向控制项被改坏** —— `draw` / `archiveBatch` 是已知生产可达的符号。
   若判据整体失效（例如预筛把所有文件都丢掉），它们会被误报成"零消费"，
   而单看"零消费"断言无法察觉。故反向控制项必须是 `consumed` 形态、
   且台账处置必须一直是「待处置」——被标成「已接线/已删除」即说明判据或
   台账被改坏（它们本来就在跑，不该有任何处置）。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import context_deadline_ledger as ledger  # noqa: E402

PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
GUARD_REL = "tests/unit/context/test_context_deadline_ledger.py"


def _listed() -> set:
    raw = io.open(PROTECTED, encoding="utf-8").read()
    return {
        line.split("#", 1)[0].strip()
        for line in raw.splitlines()
        if line.split("#", 1)[0].strip()
    }


class TestJudgeIsMachineComputed:
    """判据类由机器算、台账照抄：两者不一致即判据口径漂移。"""

    def test_ledger_matches_computed_judge_classes(self):
        """台账的判据类必须等于机器算出的判据类（双向钉住）。

        取数走 `computeJudgeClasses()`（判据类单源 `classify()` 的轻取数面），
        不再整份跑 `reconcile()` 的引用点核对 —— 后者对**只比判据类**的用例是
        重复取数，且实测把本用例推到 2.64s，与其余 170 个受保护文件共享机器时
        撞 pytest-timeout 的 30s 墙钟（构建 `cnb-ddh-1k3bgqn80` 的 py3.12 腿
        即因此判红：`Failed: Timeout (>30.0s)`，同一提交 py3.11 全绿）。

        判据强度未降：不一致照样报红，报错文案也是逐条列出的同一份文案。
        """
        computed = ledger.computeJudgeClasses()
        entries = ledger.readLedger()
        problems = [
            {
                "symbol": symbol,
                "ledger": entries[symbol]["judge"],
                "computed": judge,
                "rule": ledger.classify(symbol)[1]["rule"],
            }
            for symbol, judge in computed.items()
            if entries[symbol]["judge"] != judge
        ]
        assert not problems, (
            "台账的判据类与机器算出来的不一致——判据是从事实取的，"
            "台账必须照抄；改台账去迎合等于把判据降级成自述：\n  "
            + "\n  ".join(f"{p['symbol']}: 台账 {p['ledger']} / 实测 {p['computed']}"
                          f"（{p['rule']}）" for p in problems)
        )
        # 同源自证：轻取数面与完整对账面**同一判据**（同源 `classify()`），
        # 但只比一次取数 —— 再跑一遍 `reconcile()` 就是把 2.6s 的重复取数请回来。
        assert ledger.computedJudge("dedup") == computed["dedup"], (
            "单符号取数与批量取数不一致 —— 取数收口被改坏"
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
            f"台账条目没有依据——「单独论证可达性」变成了空话：{[p['symbol'] for p in problems]}"
        )

    def test_disposals_are_from_the_finite_enum(self):
        problems = ledger.reconcile()["unknown_disposal"]
        assert not problems, (
            f"处置不在有限枚举内（机器无法判定）：{problems}"
        )


class TestReachableControlsAreNotVacuouslyGreen:
    """反向控制：已知可达的符号必须报 `consumed`，且不得被赋任何处置。"""

    def test_controls_are_consumed(self):
        rows = {str(row["symbol"]): row for row in ledger.facts()}
        for symbol in ledger.REACHABLE_CONTROLS:
            assert rows[symbol]["judge"] == ledger.JUDGE_CONSUMED, (
                f"反向控制项 {symbol} 未被判为 {ledger.JUDGE_CONSUMED}，"
                f"实为 {rows[symbol]['judge']}（{rows[symbol]['classify']['rule']}）——"
                "判据整体失效（例如预筛丢掉了全部文件）时正是这个形态，"
                "而单看「零消费」断言无法察觉。"
            )

    def test_controls_carry_no_disposal(self):
        problems = ledger.reconcile()["pending_controls"]
        assert not problems, (
            f"反向控制项被赋了处置 {problems}——它们本来就在生产链路上跑，"
            "任何处置动作都说明判据或台账被改坏了。"
        )

    def test_scope_is_not_vacuous(self):
        """范围不得缩成空集：登记符号与台账条目都要有实际规模。"""
        rows = ledger.facts()
        assert len(rows) >= 15, f"登记符号过少（判据空转）：{len(rows)}"
        assert len(ledger.readLedger()) == len(rows), (
            "台账条目数与登记符号数不等——双向钉住失去意义"
        )


class TestJudgeRulesAreDecidable:
    """判据规则本身必须可复算：同一份代码两次取数结果一致。"""

    def test_repeated_take_is_stable(self):
        first = {str(r["symbol"]): r["judge"] for r in ledger.facts()}
        second = {str(r["symbol"]): r["judge"] for r in ledger.facts()}
        assert first == second, "同一进程内两次取数结论不同——判据不确定"

    def test_absent_rule_does_not_require_zero_references(self):
        """`absent` 说的是「无定义」，不是「零引用」。

        这条区分是判据的骨：若把「有引用」当成「符号存在」，那么"有调用方、
        没有实现"这一类（P2-1）会永远被判成可达。B6-3 补上 `get_context_pool`
        真面之前，它就是这个形态的**活标本**；现在该符号已存在（判据随之转为
        `consumed`），故本用例改为直接对 `classify()` 喂"有消费点、无定义"的
        事实，把规则本身钉住——**规则不因标本被修好而失去守卫**。
        """
        from scripts.ci import context_deadline_ledger as mod

        site = mod.RefSite

        original = mod.referenceSites

        def _sites(forms):
            return tuple(
                site(path=f"neurova/{i}.py", line=i + 1, form=form)
                for i, form in enumerate(forms)
            )

        def _run(forms):
            try:
                mod.referenceSites = lambda _symbol: _sites(forms)
                return mod.classify("get_context_pool")
            finally:
                mod.referenceSites = original

        judge, _ = _run(["def", "call"])
        assert judge == mod.JUDGE_CONSUMED, "自证前置：有定义 + 跨文件消费点应为 consumed"
        judge, detail = _run(["call"])
        assert judge == mod.JUDGE_ABSENT, (
            "有消费点但无定义必须判 absent；判成可达会让「有调用方、没有实现」"
            "这一类永久漏检"
        )
        assert detail["rule"] == "1 · 无定义、无赋值"

    def test_p2_1_symbol_now_consumed(self):
        """B6-3 交付后的新事实：符号已补齐，判据由 absent 转 consumed。"""
        rows = {str(r["symbol"]): r for r in ledger.facts()}
        assert rows["get_context_pool"]["judge"] == ledger.JUDGE_CONSUMED, (
            "get_context_pool 已补真面并有跨文件消费点；若退回 absent，说明符号"
            "又被删掉了（P2-1 复发）"
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        assert GUARD_REL in _listed(), (
            f"{GUARD_REL} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行"
            "（B5 收口时正是这个形态：文件在仓、单跑全绿、清单里没有）。"
        )
