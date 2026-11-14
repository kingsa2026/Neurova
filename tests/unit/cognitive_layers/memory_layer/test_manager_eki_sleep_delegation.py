"""阶段2 RED: 验证 manager.py EKI stub 委托到真实模块

TDD 红灯阶段: 测试预期 EKI stub 方法委托到 modules/eki_module.py，
而非抛出 NotImplementedError。

当前 stub 抛出 NotImplementedError，本测试将失败（RED）。
GREEN 阶段将修改 manager.py 委托到真实模块。

覆盖:
  - EKI (10): eki_process_task, eki_recommend_reinforcement, eki_predict_decay,
              eki_get_memory_strength, eki_get_statistics, eki_batch_update,
              eki_update_memory_from_access, eki_set_enabled, eki_get_enabled, eki_configure
  （Sleep 四周期委托已随 SleepModule 退役删除，教义第 7 条，2026-11-14；
    睡眠整理唯一实现在是 sleep.py 的 SleepConsolidation）
"""
from __future__ import annotations

import os
import sys

import pytest

# 确保能导入 neurova
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")))

from neurova.cognitive_layers.memory_layer.manager import MemoryManager


@pytest.fixture
def manager(tmp_path):
    """提供独立的 MemoryManager 实例"""
    db_path = str(tmp_path / "test_delegation.db")
    return MemoryManager(db_path=db_path, agent_id="test", user_id="test")


# ────── EKI 委托测试 ──────


class TestEKIDelegation:
    """验证 EKI stub 委托到 EKIModule"""

    def test_eki_get_statistics_returns_module_stats(self, manager):
        """eki_get_statistics 应返回 EKIModule.get_stats() 的结果"""
        stats = manager.eki_get_statistics()
        # EKIModule.get_stats() 返回 total_memories, ensemble_size, inflation_factor
        assert "total_memories" in stats
        assert "ensemble_size" in stats
        assert "inflation_factor" in stats

    def test_eki_predict_decay_delegates(self, manager):
        """eki_predict_decay 应委托到 EKIModule.predict_decay"""
        # 先注册一个记忆到 EKI 模块
        manager.eki_update_memory_from_access(memory_id="mem_test", observation=0.8)
        result = manager.eki_predict_decay(memory_id="mem_test", hours_ahead=24.0)
        # predict_decay 返回 0.0-1.0 之间的保留率
        assert isinstance(result, (int, float))
        assert 0.0 <= result <= 1.0

    def test_eki_get_memory_strength_delegates(self, manager):
        """eki_get_memory_strength 应委托到 EKIModule.predict_importance"""
        manager.eki_update_memory_from_access(memory_id="mem_test", observation=0.9)
        strength = manager.eki_get_memory_strength(memory_id="mem_test")
        # predict_importance 返回 0.0-1.0 之间的重要性
        assert isinstance(strength, (int, float))
        assert 0.0 <= strength <= 1.0

    def test_eki_batch_update_delegates(self, manager):
        """eki_batch_update 应委托到 EKIModule.batch_update"""
        updates = [("mem_1", 0.8), ("mem_2", 0.6)]
        result = manager.eki_batch_update(updates=updates)
        # batch_update 返回 {memory_id: importance} 字典
        assert isinstance(result, dict)
        assert "mem_1" in result
        assert "mem_2" in result

    def test_eki_update_memory_from_access_delegates(self, manager):
        """eki_update_memory_from_access 应委托到 EKIModule.update_with_observation"""
        # 应返回 True 表示更新成功
        result = manager.eki_update_memory_from_access(memory_id="mem_test", observation=0.7)
        assert result is True

    def test_eki_process_task_returns_result(self, manager):
        """eki_process_task 应返回处理结果字典"""
        result = manager.eki_process_task(task_id="task_1", content="test content", observation=0.8)
        assert isinstance(result, dict)
        assert "task_id" in result or "memory_id" in result

    def test_eki_set_enabled_true_initializes_module(self, manager):
        """eki_set_enabled(True) 应初始化 EKI 模块"""
        manager.eki_set_enabled(True)
        assert manager.eki_get_enabled() is True

    def test_eki_set_enabled_false_shuts_down_module(self, manager):
        """eki_set_enabled(False) 应关闭 EKI 模块"""
        manager.eki_set_enabled(True)
        manager.eki_set_enabled(False)
        assert manager.eki_get_enabled() is False

    def test_eki_configure_updates_config(self, manager):
        """eki_configure 应更新模块配置"""
        manager.eki_configure(ensemble_size=20, inflation_factor=1.05)
        stats = manager.eki_get_statistics()
        assert stats["ensemble_size"] == 20
        assert stats["inflation_factor"] == 1.05

    def test_eki_recommend_reinforcement_returns_list(self, manager):
        """eki_recommend_reinforcement 应返回强化建议列表"""
        manager.eki_update_memory_from_access(memory_id="mem_test", observation=0.9)
        result = manager.eki_recommend_reinforcement(memory_ids=["mem_test"])
        assert isinstance(result, list)


# ────── Sleep 委托测试已删除：SleepModule 及 manager 四周期方法按教义第 7 条退役 ──────


# ────── EKI 不应抛出 NotImplementedError ──────


class TestEKINoLongerRaises:
    """验证 EKI 方法不再抛出 NotImplementedError（已委托到真实模块）"""

    def test_eki_process_task_no_longer_raises(self, manager):
        try:
            manager.eki_process_task(task_id="t1", content="test", observation=0.5)
        except NotImplementedError:
            pytest.fail("eki_process_task should delegate to EKIModule, not raise NotImplementedError")

    def test_eki_get_statistics_no_longer_raises(self, manager):
        try:
            manager.eki_get_statistics()
        except NotImplementedError:
            pytest.fail("eki_get_statistics should delegate to EKIModule, not raise NotImplementedError")

    def test_eki_predict_decay_no_longer_raises(self, manager):
        try:
            manager.eki_predict_decay(memory_id="mem_test", hours_ahead=24.0)
        except NotImplementedError:
            pytest.fail("eki_predict_decay should delegate to EKIModule, not raise NotImplementedError")
