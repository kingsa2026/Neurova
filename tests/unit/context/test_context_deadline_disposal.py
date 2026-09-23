# -*- coding: utf-8 -*-
"""B6-10：死线处置必须有终局，且终局与机器判据咬合（Issue #90 审计 §5）。

## 为什么需要这道守卫

B6-1 立了「判据类（机器算）」与「处置（人填）」两条轴，`test_context_deadline_ledger.py`
钉住了第一轴（台账判据类必须等于实测）。但**处置这一轴当时没有任何守卫**：
台账里写「已删除」，代码里符号还在，两者不一致也无人察觉——"处置"于是退化成
第二份自述，正是 B6-1 拆轴时要避免的形态（修复教义第 2 条：不许把结论写成判据）。

本守卫把处置轴也钉成机器可验的三条：

1. **处置与判据咬合**：声明「已删除 / 收口第二份」的符号，其实测判据类必须为
   `absent`（生产侧无定义无赋值）；声明「已接线」的必须为 `consumed`。
   写「已删除」而判据仍是 `consumed`/`no_consumer` ⇒ 报红，说明处置只是口号。
2. **反向控制**：`disposeExpectations` 必须对**仍在仓**的符号报红——否则这条
   规则恒真（例如分类函数被改坏成永远返回 absent 时，第一节会空转通过）。
3. **文档悬空引用归零**：`EnhancedContextBuilder` 已从生产侧退场，架构文档里
   指向它的两处引用必须改指真面；引用扫描复用 `scripts/scan_docs_refs.py`
   的唯一判据，不另写一套解析。

判据口径不在这里复制：判据类取 `scripts/ci/context_deadline_ledger.py` 的
`facts()`，台账取同模块的 `readLedger()`（单一事实源）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import context_deadline_ledger as ledger  # noqa: E402

PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
GUARD_REL = "tests/unit/context/test_context_deadline_disposal.py"

#: 本批（B6-10 批次 A）给出终局的符号 → 期望（处置, 判据类）。
#: 期望值来自「处置完了之后生产侧应当长成什么样」，与台账逐条比对。
DISPOSED_EXPECTATIONS = {
    # 第二份实现收口：token 估算的唯一事实源是 context/token_estimator.py，
    # 池侧的再导出薄壳（连同它的三个 staticmethod）已删净。
    "ContextPoolUtils": ("收口第二份", ledger.JUDGE_ABSENT),
    # 第二份实现收口：`convert_context_for_model` 只是
    # `build_context_for_model` 的同实现别名（真实读路径是后者），别名已删净。
    "convert_context_for_model": ("收口第二份", ledger.JUDGE_ABSENT),
    # 零消费且语义与隔离契约冲突（跨身份合并池会打破 user/agent/session 隔离）。
    "merge_with": ("已删除", ledger.JUDGE_ABSENT),
    # 零消费：`vector_store` property 已覆盖按需创建，预加载入口是第二份路径。
    "preload_vector_store": ("已删除", ledger.JUDGE_ABSENT),
    # 零消费：窗口折叠的真面是 window_compactor，池上的"折叠候选"入口无人读。
    "select_fold_candidates": ("已删除", ledger.JUDGE_ABSENT),
    # 零消费：ack 的唯一通路是 `mark_hashes_seen`（orchestrator 调），
    # 按 turn 的旁路 ack 与它配套的 turn 索引一并删净。
    "mark_turn_seen": ("已删除", ledger.JUDGE_ABSENT),
    # 类已退场，遗留的是文档悬空引用 → 处置为「改文档指向真面」。
    "EnhancedContextBuilder": ("已删除", ledger.JUDGE_ABSENT),
    # 反向：B6-3 已把符号补齐并接线，处置必须与 consumed 咬合。
    "get_context_pool": ("已接线", ledger.JUDGE_CONSUMED),
    # B6-10 批次 B：审计点名的「唯一物证却无人校验」——判据的消费面落在
    # `neurova/context/fold_integrity.py`（折叠发生即对账），故有跨文件消费点。
    "_last_archived_window_hashes": ("已接线", ledger.JUDGE_CONSUMED),
}

#: 反向控制：这些符号仍在生产侧（判据非 absent），把它们标成「已删除」必须被抓到。
STILL_PRESENT_CONTROLS = ("draw", "archiveBatch", "ContextPoolRegistry")

#: 已退场类在架构文档里的悬空引用：文件 → 已删符号名。
RETIRED_DOC_REF_FILES = (
    "docs/01-architecture/COMPLETE_MODULES.md",
)
RETIRED_SYMBOL = "EnhancedContextBuilder"


def _facts() -> dict:
    return {str(row["symbol"]): row for row in ledger.facts()}


class TestDisposalIsMachineCheckable:
    """处置必须与判据咬合：「已删除」而符号还在 = 处置是口号。"""

    def test_disposed_symbols_match_declared_expectation(self):
        facts = _facts()
        problems = []
        for symbol, (disposal, expected_judge) in DISPOSED_EXPECTATIONS.items():
            entry = ledger.readLedger().get(symbol)
            if entry is None:
                problems.append(f"{symbol}: 台账缺该条（处置声明无处安放）")
                continue
            fact = facts.get(symbol)
            if fact is None:
                problems.append(f"{symbol}: 不在登记符号表里，判据取不到数")
                continue
            if entry["disposal"] != disposal:
                problems.append(
                    f"{symbol}: 台账处置为 {entry['disposal']}，期望 {disposal}")
            if fact["judge"] != expected_judge:
                problems.append(
                    f"{symbol}: 判据类为 {fact['judge']}（{fact['classify']['rule']}），"
                    f"期望 {expected_judge} —— 处置与生产侧实况不一致")
        assert not problems, (
            "死线处置与机器判据不咬合（台账说做完了、代码里没做完）：\n  "
            + "\n  ".join(problems)
        )

    def test_disposal_axis_is_not_vacuous(self):
        """反向控制：整条规则不得恒真——把仍在仓的符号标成「已删除」必须被抓到。"""
        facts = _facts()
        offenders = [
            symbol for symbol in STILL_PRESENT_CONTROLS
            if facts[symbol]["judge"] == ledger.JUDGE_ABSENT
        ]
        assert not offenders, (
            f"反向控制项 {offenders} 被判为 absent —— 判据整体失效，"
            "本守卫第一节会在空转中通过。"
        )
        # 规则本身的自证：仍在仓的符号不满足「已删除 ⇒ absent」的咬合判据。
        for symbol in STILL_PRESENT_CONTROLS:
            assert facts[symbol]["judge"] != ledger.JUDGE_ABSENT, (
                f"{symbol} 处置断言失去判别力"
            )


class TestRetiredSymbolLeavesNoDanglingDocRef:
    """已退场的类不得在活跃层文档里留下悬空引用（引用判据单源）。"""

    def test_architecture_doc_has_no_dangling_reference(self):
        scanner = pytest.importorskip("scripts.scan_docs_refs")
        by_basename = scanner.indexByBasename(scanner.trackedFiles())
        offenders = []
        for relative in RETIRED_DOC_REF_FILES:
            path = PROJECT_ROOT / relative
            assert path.is_file(), f"待检查文档不存在：{relative}"
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if RETIRED_SYMBOL not in line:
                    continue
                # 判据与活跃层扫描同源：能解析出目标文件才算引用，
                # 纯文字交代（点名已退役、不指向文件）不算悬空。
                for found in scanner.scanDocumentLinks(path, by_basename):
                    if found["line"] == lineno:
                        offenders.append(f"{relative}:{lineno} [{found['label']}]({found['ref']})")
        assert not offenders, (
            f"{RETIRED_SYMBOL} 已从生产侧退场，文档里仍有指向它的引用：\n  "
            + "\n  ".join(offenders)
            + "\n修法：改指真实可达的权威文档，或以显式文本交代去处。"
        )

    def test_retired_symbol_is_absent_in_production(self):
        assert _facts()[RETIRED_SYMBOL]["judge"] == ledger.JUDGE_ABSENT, (
            f"{RETIRED_SYMBOL} 又回到生产侧了 —— 本批按审计裁决退役它，"
            "不得被重新加回（否则文档那两处引用又变成活引用）。"
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        raw = PROTECTED.read_text(encoding="utf-8")
        listed = {
            line.split("#", 1)[0].strip()
            for line in raw.splitlines()
            if line.split("#", 1)[0].strip()
        }
        assert GUARD_REL in listed, (
            f"{GUARD_REL} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行"
            "（B5 收口时正是这个形态：文件在仓、单跑全绿、清单里没有）。"
        )
