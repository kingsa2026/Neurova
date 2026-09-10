"""M-18 回归测试：get_feedback 的 avg_temperature 分母口径。

根因：sleep.py get_feedback 用 `_consolidation_count`（整合轮数）做分母，
而分子 `_temperature_sum` 按记忆条数累加（consolidate 中 sum(m.temperature)），
轮数 != 条数时均值严重偏大。

修复后契约：分母与分子同口径 —— 累计参与求和的记忆条数；
无累计时保留原 50.0 兜底。
"""

import pytest

from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation


def _record(rid, content, temperature):
    return MemoryRecord(
        id=rid,
        content=content,
        temperature=temperature,
        importance=0.5,
    )


class TestM18AvgTemperatureDenominator:
    def test_avg_temperature_uses_memory_count_not_round_count(self):
        sc = SleepConsolidation(similarity_threshold=0.99, decay_rate=0.0)

        # 单轮 3 条互不相似的记忆：分子累加 3 条温度，分母必须是 3 而非 1 轮
        memories = [
            _record("a", "apple banana cherry", 60.0),
            _record("b", "dog elephant fox", 60.0),
            _record("c", "red green blue", 60.0),
        ]
        merged, merge_results = sc.consolidate(memories)
        assert len(merged) == 3, f"前置假设失败：不应发生合并 {len(merged)}"

        fb = sc.get_feedback()
        expected = sum(m.temperature for m in merged) / len(merged)
        assert fb["avg_temperature"] == pytest.approx(expected), (
            "avg_temperature 分母用了整合轮数而非记忆条数"
        )
        # 未发生衰减时均值应等于输入均值 60
        assert fb["avg_temperature"] == pytest.approx(60.0)

    def test_accumulates_across_rounds_with_same_denominator_semantics(self):
        sc = SleepConsolidation(similarity_threshold=0.99, decay_rate=0.0)
        sc.consolidate([_record("a1", "apple banana cherry", 50.0)])
        sc.consolidate(
            [
                _record("b1", "dog elephant fox", 70.0),
                _record("b2", "red green blue", 90.0),
            ]
        )
        fb = sc.get_feedback()
        # 两轮共 3 条：分子为 3 条温度之和，分母必须为 3（旧实现为轮数 2）
        assert fb["avg_temperature"] == pytest.approx((50.0 + 70.0 + 90.0) / 3.0)
        assert fb["consolidation_count"] == 2

    def test_no_data_keeps_default_fallback(self):
        sc = SleepConsolidation()
        fb = sc.get_feedback()
        assert fb["avg_temperature"] == 50.0
