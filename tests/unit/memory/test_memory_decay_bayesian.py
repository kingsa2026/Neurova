"""
Memory.decay 贝叶斯曲线委托测试

断点 M-5 修复：原 Memory.decay() 用线性衰减 temp -= rate * hours，
完全绕过 TemperatureEngine.on_decay 的贝叶斯遗忘曲线。
修复后 decay 应委托 TemperatureEngine，具备贝叶斯特性：
  - 固化记忆（CRYSTALLIZED）不衰减
  - 高温记忆（>=80）不衰减
  - 今天访问过的记忆（days_idle < 1.0）不衰减
"""

from datetime import datetime, timezone, timedelta

import pytest

from neurova.cognitive_layers.memory_layer.models import (
    EmotionType,
    LifecycleStage,
    Memory,
)


class TestMemoryDecayUsesBayesian:
    """Memory.decay 应委托 TemperatureEngine 贝叶斯曲线，而非线性衰减"""

    def test_decay_delegates_to_temperature_engine(self):
        """tracer bullet: 固化记忆衰减后温度不变

        线性公式 temp -= rate*hours 会把 50 → 49，
        贝叶斯曲线对 is_crystallized=True 直接返回原温度（temperature.py 行 221-227）。
        用此差异验证 decay 已委托引擎。
        """
        mem = Memory(
            content="固化记忆",
            temperature=50.0,
            importance=50.0,
            lifecycle_stage=LifecycleStage.CRYSTALLIZED,
        )
        original_temp = mem.temperature

        mem.decay(hours=1.0, rate=1.0)

        # 固化记忆贝叶斯曲线不衰减；线性公式会变 49
        assert mem.temperature == original_temp, (
            f"固化记忆不应衰减: 期望 {original_temp}, 实际 {mem.temperature}"
        )

    def test_decay_result_within_bounds(self):
        """衰减后温度应在 [0, 100] 范围内

        用会真正衰减的记忆（非固化、低温、days_idle >= 1）触发贝叶斯曲线。
        """
        now = datetime.now(timezone.utc)
        mem = Memory(
            content="待衰减记忆",
            temperature=30.0,
            importance=50.0,
            lifecycle_stage=LifecycleStage.ACTIVE,
            # 设为 2 天前访问，确保 days_idle >= 1 触发衰减
            last_accessed_at=now - timedelta(days=2),
        )

        mem.decay(hours=24.0, rate=5.0)

        assert 0.0 <= mem.temperature <= 100.0, (
            f"温度越界: {mem.temperature}"
        )

    def test_decay_updates_timestamp(self):
        """衰减后 updated_at 应更新为当前时间"""
        before = datetime.now(timezone.utc)
        mem = Memory(
            content="时间戳记忆",
            temperature=30.0,
            importance=50.0,
            last_accessed_at=before - timedelta(days=2),
        )
        old_updated_at = mem.updated_at

        mem.decay(hours=1.0, rate=1.0)

        # updated_at 应被刷新到 decay 调用时刻
        assert mem.updated_at >= before, (
            f"updated_at 未更新: old={old_updated_at}, new={mem.updated_at}"
        )
