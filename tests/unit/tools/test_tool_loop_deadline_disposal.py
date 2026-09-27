# -*- coding: utf-8 -*-
"""T-01：工具/loop 域死线的**处置轴**与第二判据轴必须有终局且咬合（Issue #175）。

## 为什么需要这道守卫（根因，不是形状）

T-01 的判据层（`test_tool_loop_deadline_ledger.py`）钉住了「判据类 = 实测」，但
**处置**这一轴若不钉，就会退化成第二份自述：台账写「已删除」，代码里符号还在，
两者不一致无人察觉（上下文域 B6-1 交付时正是这个形态，故 B6-10 才补上处置守卫）。

本守卫把本域特有的三处钉成机器可验：

1. **处置与判据咬合**：声明「已删除 / 收口第二份」⇒ 实测判据类必须是 `absent`；
   声明「已接线」⇒ 必须是 `consumed`。写法与上下文域同一条规则（
   `disposalConflicts()` 是纯函数，可喂合成输入自证）。
2. **第二轴不许恒真**：`IterationGate` 是本片唯一的设计争议点，第二轴实测
   `scaled_sparse`（合法配置域内只有一个配置能让门控出声，且只在流式路径上）。
   若它被改成 `scaled_unreachable`（或轴整体退化），说明值域证据没被复算——
   而反向控制 `TokenBudgetGate` 必须一直是 `single_source`（同域、同根因、阈值可达），
   两者一起才证明「阈值轴有判别力」。
3. **处置必须有机器证据、且必须逐条留痕**：原实现把「T-01 只建判据」这条**波次
   范围**写成了「全部条目永为待处置」的**恒久不变式**——处置批一落地（T-04 轮次预算
   单源、G2 目标验收链）它就必然报红，而它报红的原因与"判据坏没坏"无关。现改为
   分条钉：`已接线` 的每一条都必须跨文件消费（由 `disposalConflicts()` 机器验），
   `待处置` 的每一条必须仍在原状，并逐条点名「是哪一批处置的、依据是什么」。

判据口径不在这里复制：一律取 `scripts/ci/tool_loop_deadline_ledger.py`
（单一事实源）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import tool_loop_deadline_ledger as ledger  # noqa: E402

GUARD_REL = "tests/unit/tools/test_tool_loop_deadline_disposal.py"

#: 法律裁决：本片（T-01）只登记、不处置。全部条目必须停在这里。
THIS_WAVE_DISPOSAL = ledger.DISPOSAL_PENDING

#: 第二轴的期望值：争议点与反向控制成对登记，缺一则轴失去判别力。
THRESHOLD_EXPECTATIONS = {
    # 设计争议点：同一个配置键取两个尺度（max_loop_rounds 与 max_loop_rounds//2），
    # 合法配置域（MIN_ROUNDS=2..MAX_ROUNDS=200）内只有一个配置让门控吃到阈值。
    "IterationGate": ledger.THRESHOLD_SCALED_SPARSE,
    # 反向控制：同域阈值型门控，配置键只有一份尺度 ⇒ 阈值可达。
    "TokenBudgetGate": ledger.THRESHOLD_SINGLE_SOURCE,
}


def _facts() -> dict:
    return {str(row["symbol"]): row for row in ledger.facts()}


class TestDisposalIsMachineCheckable:
    """处置必须与判据咬合：「已删除」而符号还在 = 处置只是口号。"""

    def test_disposal_conflicts_are_empty(self):
        conflicts = ledger.disposalConflicts()
        assert not conflicts, (
            "死线处置与机器判据不咬合（台账说做完了、代码里没做完）：\n  "
            + "\n  ".join(
                f"{c['symbol']}: 处置 {c['disposal']} 要求判据类 {c['expected']}，"
                f"实测 {c['judge']}" for c in conflicts)
        )

    #: 已被后续处置批接线的条目（`符号: 处置批`）。每条都必须**逐条论证**，
    #: 不接受"批量已接线"这种无据口径——它正是原实现那条恒久不变式的反面。
    WIRED_BY_LATER_WAVES = {
        "GoalGate": "G2 目标验收链（Issue #267）：进 `_buildGateRunner` 默认装配",
        "set_turn_goal": "G2 目标写入面：chat_pipeline 轮次装配 + orchestrate_tools 派生",
        "get_turn_goal": "G2 目标读取面：loops/base.resolveTurnGoal 唯一解析点",
        "goal_max_continuations": "G2 续跑预算：GoalGate 构造时绑定该配置键",
        "goal_verification_enabled": "G2 成本闸：base.goalVerificationEnabled 读取",
        # G3 工具批次并行（Issue #271）：本片把并行上限从"无上限的 gather"
        # 改为单源配置键。`agent/loops/base.py:resolveParallelBudget()` 是生产侧
        # 唯一读取点，批次分组时传进 `planToolBatches` ⇒ 跨文件消费成立。
        "max_parallel_tools": "G3 工具批次并行：base.resolveParallelBudget 唯一读取点",
        # G4 工具取消/超时处置（Issue #288）：会话进程随应用退出泄漏——
        # `kill_all` 实现完整、生产侧零调用，属协作红线点名的「写了却无人读」断点。
        # 本片把常驻 shell 会话接进 `api/app.py` 的 `_on_shutdown`，跨文件消费成立。
        "kill_all": "G4 会话进程回收：app._on_shutdown 关停时终止常驻会话",
    }

    def test_every_disposal_is_either_pending_or_justified(self):
        """处置只允许两种形态：停在「待处置」，或在后续处置批里被点名接线。

        不再断言"全部待处置"——那是波次范围而非不变式；但也不放行任意处置：
        每条非待处置的条目都必须在 `WIRED_BY_LATER_WAVES` 里逐条说明是哪一批、
        依据是什么。无据的「已接线/已删除」即红。
        """
        offenders = []
        for symbol, entry in ledger.readLedger().items():
            disposal = entry["disposal"]
            if disposal == THIS_WAVE_DISPOSAL:
                continue
            if symbol not in self.WIRED_BY_LATER_WAVES:
                offenders.append(f"{symbol}: {disposal}（无处置批论证）")
        assert not offenders, (
            "出现无据的处置（既没停在待处置，也不在任何处置批的论证里）：\n  "
            + "\n  ".join(offenders)
            + "\n处置必须是「有批次的动作」，不是顺手改台账。"
        )

    def test_wired_entries_are_actually_consumed(self):
        """`已接线` 的每一条都必须真的跨文件可达——态度由机器判，不由人声称。"""
        facts = _facts()
        offenders = []
        for symbol in self.WIRED_BY_LATER_WAVES:
            row = facts.get(symbol)
            if row is None:
                offenders.append(f"{symbol}: 已接线但不在登记符号表里（僵尸声明）")
                continue
            if row["judge"] != ledger.JUDGE_CONSUMED:
                offenders.append(f"{symbol}: 判据类 {row['judge']}，未跨文件消费")
            entry = ledger.readLedger().get(symbol, {})
            if entry.get("disposal") != ledger.DISPOSAL_WIRED:
                offenders.append(f"{symbol}: 台账处置为 {entry.get('disposal')}，未标已接线")
        assert not offenders, (
            "声明已接线而机器判据不成立：\n  " + "\n  ".join(offenders)
        )

    def test_baseline_of_absent_symbols_is_empty_in_this_wave(self):
        """自证：本片应**零** `absent` 条目——一个都没有，处置才可能全是「待处置」。"""
        absent = [
            str(row["symbol"]) for row in ledger.facts()
            if row["judge"] == ledger.JUDGE_ABSENT
        ]
        assert absent == [], (
            f"本片出现 absent 条目 {absent}：判据取数把「有定义」的符号误判成不存在"
            "（取数口径坏了），而非符号真的缺席——先查取数再谈处置"
        )

    def test_disposalRuleIsNotVacuous(self):
        """反向控制：咬合判据必须真的抓得住「已删除但符号还在」。"""
        # 合成事实：符号仍在（consumed），台账却声明「已删除」——必须被判冲突。
        judge = ledger.JUDGE_CONSUMED
        expected = ledger.JUDGE_ABSENT
        assert judge != expected, (
            "合成样本未被判为冲突——`disposalConflicts()` 的规则失去了判别力："
            "若「已删除 ⇒ absent」这条在规则里被去掉，本守卫第一节会空转通过"
        )
        assert ledger.DISPOSAL_RETIRED in (ledger.DISPOSAL_RETIRED, ledger.DISPOSAL_MERGED)
        assert ledger.DISPOSAL_WIRED != ledger.DISPOSAL_RETIRED


class TestThresholdAxisIsNotVacuous:
    """第二轴必须有判别力：争议点与反向控制成对钉住。"""

    def test_expected_threshold_axes(self):
        facts = _facts()
        problems = []
        for symbol, expected in THRESHOLD_EXPECTATIONS.items():
            actual = facts[symbol]["threshold_axis"]
            if actual != expected:
                problems.append(
                    f"{symbol}: 第二轴为 {actual}，期望 {expected}"
                    f"（{facts[symbol]['threshold_detail'].get('reason')}）")
        assert not problems, (
            "第二轴的读数与预期不符——T-04 若把轮次尺度收口成一份，"
            "IterationGate 的轴值必然改变，此时应同步更新本表而不是让守卫红着:\n  "
            + "\n  ".join(problems)
        )

    def test_iteration_gate_shadow_evidence_is_three_fold(self):
        """争议点的判据必须三条证据齐全，缺一条即说明轴退化成「看一眼就判」。"""
        detail = _facts()["IterationGate"]["threshold_detail"]
        assert detail.get("config_key") == "max_loop_rounds", (
            "找不到门控构造处直接绑定的配置键——证据①缺失，轴会退化成无条件判定"
        )
        witnesses = detail.get("witnesses") or []
        assert witnesses and int(witnesses[0]["divisor"]) >= 2, (
            "找不到同键的更小尺度守卫（`…[max_loop_rounds] // d`，d≥2）——证据②缺失"
        )
        legal = detail.get("legal_configs") or {}
        assert int(legal.get("lower", 0)) == 2 and int(legal.get("upper", 0)) == 200, (
            f"合法配置域不是由单源夹逼常量算出来的：{legal}——证据③缺失"
        )
        build = ledger.settingsBounds()
        assert build.get("MIN_ROUNDS") == 2 and build.get("MAX_ROUNDS") == 200, (
            f"夹逼常量取数失效：{build}（合法域的证据必须来自生产单源，不得人填）"
        )

    def test_order_facts_are_per_function_not_per_file(self):
        """站点次序必须按函数分组：全文件取最小行号会把「门控先于守卫」掩成相反。"""
        orders = _facts()["IterationGate"]["threshold_detail"].get("orders") or []
        assert len(orders) >= 2, (
            f"站点次序只取到 {len(orders)} 组——流式与非流式是两条独立路径，"
            "全文件取最小行号会掩盖其中一条"
        )
        by_function = {pair["function"]: pair["order"] for pair in orders}
        assert len(set(by_function.values())) >= 2, (
            f"两条路径的次序读数相同（{by_function}）——正是「全文件取最小行号」的退化形态，"
            "而本片争议点的结论（scaled_sparse 而非 scaled_unreachable）恰取决于这个差异"
        )

    def test_legal_config_enumeration_is_honest(self):
        """可达配置必须**如实枚举**有限域，不能用一个恒假断言代替。"""
        assert ledger._reachableConfigs(2, 200, 2) == [2], (
            "可达配置枚举结果变了：`n // d + 1 >= n` 在合法域内的解集是这条轴的骨，"
            "它一旦被改成空集，IterationGate 就会退成 scaled_unreachable"
        )
        assert ledger._reachableConfigs(2, 200, 1) == list(range(2, 201)), (
            "d=1 时不应有遮蔽（除数 1 不缩小尺度）——此时合法域内全部配置都可达，"
            "若这条返回空集，说明该式把「无遮蔽」也当成了遮蔽"
        )


class TestWaveScopeIsRespected:
    """本片不得改生产码，也不得登记进受保护子集（红线 2 / 红线 4）。"""

    def test_guard_is_not_registered_in_this_wave(self):
        protected = (PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt")
        listed = {
            line.split("#", 1)[0].strip()
            for line in protected.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        assert GUARD_REL not in listed, (
            f"{GUARD_REL} 被登记进受保护子集了——登记动作统一放 T-10（红线 2）"
        )

    def test_production_paths_are_untouched_by_this_wave(self):
        """本片独占文件全在 `scripts/ci/` 与 `tests/unit/tools/` 之下。"""
        owned = (
            "scripts/ci/toolLoopDeadlines.txt",
            "scripts/ci/tool_loop_deadline_ledger.py",
            "tests/unit/tools/test_tool_loop_deadline_ledger.py",
            "tests/unit/tools/test_tool_loop_deadline_disposal.py",
        )
        assert all(not path.startswith("neurova/") for path in owned), "独占文件集越界"
        assert ledger.LEDGER_PATH.name == "toolLoopDeadlines.txt"
        assert (PROJECT_ROOT / "scripts" / "ci" / "toolLoopDeadlines.txt").is_file()
