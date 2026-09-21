"""007 残留 · 收紧裁定档位的**连带代价**必须写进票末（票面明令「必须写进」）。

票据 007 验收标准原文：「**必须写进票末的连带代价**：`tool_memory.muscle_memory_threshold`
是 ADR 0016 判死方向后 RSI 参数寻优臂**唯一还有真实梯度的旋钮**（起点 0.85 / 目标 0.8）。
本票收紧档位会让那条臂近乎空转，这是有意的临时状态，由 008 终态解；
不得为"让 RSI 有活干"而回退本票。」

前一轮在规格文档与索引里**零命中**（`RSI`/`空转`/`旋钮`），代价既没登记也没交给 008 的
重验去接——正是"有意为之的临时状态"最容易变成"无人知道的永久状态"的路径。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SPEC = REPO_ROOT / "docs" / "specs" / "2026-09-21-tool-experience-loop-repair.md"
INDEX = (REPO_ROOT / "docs" / "specs" / "2026-09-21-tool-experience-loop"
         / "tickets" / "000-索引.md")


class TestIdleCostIsRecorded:
    def test_spec_names_the_knob_and_the_idling(self):
        text = SPEC.read_text(encoding="utf-8")
        assert "muscle_memory_threshold" in text, "票末没有点名那颗旋钮"
        assert "空转" in text, "票末没有登记 RSI 寻优臂会近乎空转这一代价"
        assert "0.85" in text and "0.8" in text, "票末没有给出起点与目标两个值"

    def test_spec_states_it_is_intentional_and_released_by_008(self):
        text = SPEC.read_text(encoding="utf-8")
        assert "有意" in text and "008" in text, (
            "代价必须写明「有意为之的临时状态，由 008 终态解」，否则读成缺陷"
        )

    def test_index_carries_the_same_registration(self):
        text = INDEX.read_text(encoding="utf-8")
        assert "空转" in text and "muscle_memory_threshold" in text, (
            "索引（票集入口）没有同步这条代价登记"
        )

    def test_not_used_as_a_reason_to_revert_the_ticket(self):
        """反向锁：代价登记不得被读成"可以回退本票"。"""
        text = SPEC.read_text(encoding="utf-8")
        assert "不得" in text and "回退" in text, (
            "没有写明「不得为让 RSI 有活干而回退本票」，代价登记会被当成回退许可"
        )
