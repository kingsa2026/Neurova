"""P2-8 stall 探索指令 — 连续无接受时强制换变异轴的红灯测试。

与收敛降频互补：backoff 管频率（收敛后少跑），探索指令管方向（跑的
时候换打法）。墙标记（gate_wall）不计入窗口；无 stall 时 render 输出
与旧版逐字节一致。
"""

import pytest

from neurova.evolution.eval.history_ledger import exploration_directive


def _rec(hypothesis, accepted=False, reason="no_improvement"):
    return {"ts": "T", "hypothesis": hypothesis, "accepted": accepted,
            "reject_reason": reason if not accepted else ""}


class TestExplorationDirective:
    def test_stall_triggers_directive(self):
        records = [_rec(f"假设{i}") for i in range(5)]
        text = exploration_directive(records)
        assert text, "连续 5 轮无接受必须触发探索指令"
        assert "变异轴" in text
        assert "假设4" in text  # 点名历史假设

    def test_any_accepted_suppresses_directive(self):
        records = [_rec(f"假设{i}") for i in range(4)] + [_rec("有效改进", accepted=True)]
        assert exploration_directive(records) == ""

    def test_insufficient_window_no_directive(self):
        records = [_rec(f"假设{i}") for i in range(3)]
        assert exploration_directive(records) == ""

    def test_gate_wall_not_counted(self):
        """墙标记不是真实记录：不触发、不占窗口。"""
        records = [_rec(f"假设{i}") for i in range(4)] + [{"gate_wall": 7}]
        assert exploration_directive(records) == ""

    def test_custom_window(self):
        records = [_rec(f"假设{i}") for i in range(3)]
        assert exploration_directive(records, stall_window=3) != ""
        assert exploration_directive(records, stall_window=5) == ""

    def test_render_integrates_directive(self, tmp_path):
        """有 stall 时 render_for_prompt 输出含指令段。"""
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        ledger = EvolutionLedger(tmp_path)
        for i in range(5):
            ledger.append("s1", {"hypothesis": f"假设{i}", "accepted": False,
                                 "reject_reason": "no_improvement"})
        text = EvolutionLedger.render_for_prompt(ledger.recent("s1"))
        assert "已实测无效" in text
        assert "变异轴" in text

    def test_render_no_stall_byte_identical(self, tmp_path):
        """无 stall 时：含 accepted 记录的历史，渲染不出现探索指令段。"""
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        ledger = EvolutionLedger(tmp_path)
        for i in range(4):
            ledger.append("s1", {"hypothesis": f"假设{i}", "accepted": False,
                                 "reject_reason": "no_improvement"})
        ledger.append("s1", {"hypothesis": "有效改进", "accepted": True,
                             "reject_reason": ""})
        text = EvolutionLedger.render_for_prompt(ledger.recent("s1"))
        assert "变异轴" not in text
        # 与旧版（P1-4 契约）段结构一致：已有段不漂移
        assert "已实测无效" in text and "已生效" in text
