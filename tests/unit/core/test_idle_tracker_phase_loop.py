"""空闲睡眠触发链路测试（P2）

覆盖空闲触发链的四处断点:
- P2-5: get_next_phase/should_enter_phase/_calculate_time_until_next 用 f"to_{phase}"
  读阈值，而 SleepPhaseThresholds 字段是 idle_* → getattr 默认 0 → 阶段迁移错乱。
- P2-6: check_and_update_phase 硬编码温度 25.0，从不读真实记忆温度。
- 断点: _on_phase_changed 从未注册为回调 → 阶段迁移永远不触发记忆巩固。
- 断点: record_activity 在 active 阶段不重置空闲计时 → 空闲时长虚增。
- 断点: 空闲路径 _write_back_consolidated_memories 从不删除被合并的源记忆 → 记忆翻倍。
"""

import time
import unittest

from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
from neurova.core.idle_tracker import IdleTimeTracker, SleepPhaseThresholds


class FakeMemoryManager:
    """最小记忆管理器桩：记录 remember/forget/update 调用"""

    def __init__(self, memories):
        self._mems = {m["id"]: dict(m) for m in memories}
        self.added = []
        self.forgotten = []
        self.updated = []

    def get_all_memories(self):
        return [dict(v) for v in self._mems.values()]

    def remember(self, content, **kwargs):
        mid = f"new_{len(self.added)}"
        self.added.append({"id": mid, "content": content, **kwargs})
        self._mems[mid] = {"id": mid, "content": content, **kwargs}
        return mid

    def forget(self, memory_id, soft=True):
        self.forgotten.append(memory_id)
        self._mems.pop(memory_id, None)
        return True

    def update_memory(self, memory_id=None, **kwargs):
        self.updated.append(("update_memory", memory_id, kwargs))
        return True

    def update_memory_temperature(self, memory_id=None, interaction_type="recall"):
        self.updated.append(("temperature", memory_id, interaction_type))
        return True


def _sample_memories():
    """m1/m2 语义相似（同嵌入）应被合并；m3 是孤立单例必须保留"""
    return [
        {
            "id": "m1",
            "content": "用户喜欢咖啡",
            "embedding": [1.0, 0.0],
            "temperature": 60.0,
            "importance": 0.5,
            "categories": ["preference"],
        },
        {
            "id": "m2",
            "content": "用户喜欢喝咖啡",
            "embedding": [1.0, 0.0],
            "temperature": 60.0,
            "importance": 0.5,
            "categories": ["preference"],
        },
        {
            "id": "m3",
            "content": "明天下雨",
            "embedding": [0.0, 1.0],
            "temperature": 60.0,
            "importance": 0.5,
            "categories": ["general"],
        },
    ]


class IdleTrackerPhaseLoopTest(unittest.TestCase):
    def test_time_mode_threshold_keys_map_to_real_fields(self):
        tracker = IdleTimeTracker()
        tracker.update_config(sleep_mode="time")

        self.assertIsNone(tracker.get_next_phase(100.0), "空闲 0 秒不应进入任何睡眠阶段")
        tracker._last_activity_time = time.time() - 2000
        self.assertEqual(tracker.get_next_phase(100.0), "light_sleep")

    def test_temperature_mode_uses_real_memory_temperature(self):
        tracker = IdleTimeTracker()
        tracker.set_temperature_provider(lambda: 10.0)
        self.assertEqual(tracker.check_and_update_phase(), "light_sleep")
        self.assertEqual(tracker.get_current_phase(), "light_sleep")

        hot = IdleTimeTracker()
        hot.set_temperature_provider(lambda: 100.0)
        self.assertIsNone(hot.check_and_update_phase())
        self.assertEqual(hot.get_current_phase(), "active")

    def test_phase_transition_triggers_consolidation_and_write_back(self):
        tracker = IdleTimeTracker()
        tracker.set_temperature_provider(lambda: 100.0)  # 保持 active，避免监控线程干扰
        fake_mm = FakeMemoryManager(_sample_memories())
        consolidation = SleepConsolidation(memory_manager=fake_mm)
        tracker.set_sleep_consolidation(consolidation)
        tracker.set_memory_manager(fake_mm)

        tracker.on_start()
        try:
            registered = tracker._callbacks.get("phase_changed", [])
            self.assertIn(
                tracker._on_phase_changed,
                registered,
                "阶段迁移回调必须在启动时注册，否则巩固永不触发",
            )
            self.assertTrue(tracker.enter_manual_phase("light_sleep"))
        finally:
            tracker.on_stop()

        self.assertGreaterEqual(consolidation.get_feedback()["consolidation_count"], 1)
        self.assertEqual(
            set(fake_mm.forgotten),
            {"m1", "m2"},
            "被合并的源记忆应删除，单例记忆 m3 必须保留",
        )
        self.assertTrue(fake_mm.added, "合并后的新记忆应写回")

    def test_record_activity_resets_idle_while_active(self):
        tracker = IdleTimeTracker()
        tracker._last_activity_time = time.time() - 100
        tracker.record_activity()
        self.assertLess(tracker.get_current_idle_time(), 5)

    def test_phase_thresholds_cover_all_sleep_phases(self):
        thresholds = SleepPhaseThresholds()
        mapping = IdleTimeTracker._PHASE_THRESHOLD_KEYS
        for phase in ("light_sleep", "deep_sleep", "rem", "hibernate"):
            self.assertTrue(hasattr(thresholds, mapping[phase]), f"阶段 {phase} 缺少阈值字段 {mapping[phase]}")
            self.assertGreater(getattr(thresholds, mapping[phase]), 0)


if __name__ == "__main__":
    unittest.main()
