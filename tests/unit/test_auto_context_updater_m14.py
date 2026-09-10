"""回归测试：M-14 AutoContextUpdater 温度衰减真实生效（非空 stub）。

修复前 ``_update_temperature`` 是空实现（仅 logger.debug + return 0），
但 ``_perform_update`` 仍上报"更新完成"并递增 ``total_updates`` → 冷却维护
静默失效。本测试锁定真实衰减行为，防止回归为 no-op。
"""
import datetime

import pytest

from neurova.cognitive_layers.memory_layer.auto_context_updater import AutoContextUpdater


class _FakeMemoryManager:
    """内存版记忆管理器替身，只实现 AutoContextUpdater 依赖的两个方法。"""

    def __init__(self, memories):
        # memories: list of dicts (id, temperature, last_accessed_at?)
        self._memories = [dict(m) for m in memories]
        self.updates = []

    def get_all_memories(self):
        return [dict(m) for m in self._memories]

    def update_memory(self, memory_id, **kwargs):
        self.updates.append((memory_id, kwargs))
        for m in self._memories:
            if m["id"] == memory_id:
                m.update(kwargs)
                return True
        return False


def _iso_days_ago(days: float) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return dt.isoformat()


def test_temperature_decay_lowers_temperature():
    mm = _FakeMemoryManager([
        {"id": "m1", "temperature": 80.0, "last_accessed_at": _iso_days_ago(10)},
        {"id": "m2", "temperature": 50.0},  # 无访问时间 → 基础衰减 1.0
        {"id": "m3", "temperature": 0.0},    # 已在最低，不变
    ])
    updater = AutoContextUpdater(memory_manager=mm, temperature_decay_rate=1.0)
    n = updater._update_temperature()
    assert n == 2, f"应更新 2 条，实际 {n}"
    by_id = {m["id"]: m for m in mm._memories}
    # m1 空闲 10 天：decay = 1.0 * (1 + 10) = 11 → 80 - 11 = 69
    # m1 空闲 10 天：decay = 1.0 * (1 + 10) = 11 → 80 - 11 = 69（浮点近似）
    assert by_id["m1"]["temperature"] == pytest.approx(69.0)
    assert by_id["m2"]["temperature"] == 49.0
    assert by_id["m3"]["temperature"] == 0.0
    # 每下降温都应调用 update_memory 持久化
    assert all(kw.get("temperature") is not None for _, kw in mm.updates)


def test_no_manager_returns_zero():
    updater = AutoContextUpdater(memory_manager=None)
    assert updater._update_temperature() == 0


def test_perform_update_counts_decay():
    mm = _FakeMemoryManager([
        {"id": "x", "temperature": 70.0, "last_accessed_at": _iso_days_ago(5)},
    ])
    updater = AutoContextUpdater(memory_manager=mm, temperature_decay_rate=2.0)
    updater._perform_update()
    assert updater.get_stats()["temperature_updates"] >= 1
