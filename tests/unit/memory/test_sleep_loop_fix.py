"""
睡眠闭环修复测试

测试 IdleTimeTracker 可以触发 SleepConsolidation 当空闲阈值超过时。
使用 TDD 方法：先写失败的测试，然后实现修复。
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import time

class TestIdleTrackerTriggersSleepConsolidation:
    """测试 IdleTimeTracker 可以触发 SleepConsolidation"""

    def test_idle_tracker_has_set_sleep_consolidation_method(self):
        """IdleTimeTracker 应该有 set_sleep_consolidation 方法"""
        from neurova.core.idle_tracker import IdleTimeTracker
        
        tracker = IdleTimeTracker()
        assert hasattr(tracker, 'set_sleep_consolidation')
        assert callable(tracker.set_sleep_consolidation)

    def test_idle_tracker_has_set_memory_manager_method(self):
        """IdleTimeTracker 应该有 set_memory_manager 方法"""
        from neurova.core.idle_tracker import IdleTimeTracker
        
        tracker = IdleTimeTracker()
        assert hasattr(tracker, 'set_memory_manager')
        assert callable(tracker.set_memory_manager)

    def test_trigger_consolidation_calls_sleep_consolidation_run_sleep_cycle(self):
        """当触发巩固时，应该调用 SleepConsolidation.run_sleep_cycle()"""
        from neurova.core.idle_tracker import IdleTimeTracker
        
        # 创建 mock
        mock_consolidation = Mock()
        mock_memory_manager = Mock()
        
        # 创建 tracker 并注入 mock
        tracker = IdleTimeTracker()
        tracker.set_sleep_consolidation(mock_consolidation)
        tracker.set_memory_manager(mock_memory_manager)
        
        # 模拟记忆数据
        mock_memories = [Mock(), Mock()]
        mock_memory_manager.get_all_memories.return_value = mock_memories
        
        # 模拟 run_sleep_cycle 返回值
        mock_consolidation.run_sleep_cycle.return_value = {"phase": "sleep", "total_processed": 2}
        
        # 调用 _trigger_consolidation
        tracker._trigger_consolidation()
        
        # 验证 run_sleep_cycle() 被调用
        # 现实现会把 Dict 转换为 MemoryRecord 后再调用（字段来自 get_all_memories）
        assert mock_consolidation.run_sleep_cycle.called
        passed = mock_consolidation.run_sleep_cycle.call_args.args[0]
        assert len(passed) == len(mock_memories)

    def test_trigger_consolidation_handles_empty_memories(self):
        """当没有记忆时，不应该调用 consolidate"""
        from neurova.core.idle_tracker import IdleTimeTracker
        
        mock_consolidation = Mock()
        mock_memory_manager = Mock()
        
        tracker = IdleTimeTracker()
        tracker.set_sleep_consolidation(mock_consolidation)
        tracker.set_memory_manager(mock_memory_manager)
        
        # 返回空列表
        mock_memory_manager.get_all_memories.return_value = []
        
        tracker._trigger_consolidation()
        
        # 不应该调用 consolidate
        mock_consolidation.consolidate.assert_not_called()

    def test_trigger_consolidation_handles_missing_consolidation(self):
        """当没有设置 SleepConsolidation 时，应该优雅处理"""
        from neurova.core.idle_tracker import IdleTimeTracker
        
        mock_memory_manager = Mock()
        
        tracker = IdleTimeTracker()
        # 不设置 sleep_consolidation
        tracker.set_memory_manager(mock_memory_manager)
        
        # 应该不会抛出异常
        tracker._trigger_consolidation()

    def test_trigger_consolidation_handles_missing_memory_manager(self):
        """当没有设置 memory_manager 时，应该优雅处理"""
        from neurova.core.idle_tracker import IdleTimeTracker
        
        mock_consolidation = Mock()
        
        tracker = IdleTimeTracker()
        tracker.set_sleep_consolidation(mock_consolidation)
        # 不设置 memory_manager
        
        # 应该不会抛出异常
        tracker._trigger_consolidation()


class TestSleepConsolidationHasRunSleepCycle:
    """测试 SleepConsolidation 有 run_sleep_cycle 方法（向后兼容）"""

    def test_sleep_consolidation_has_run_sleep_cycle_method(self):
        """SleepConsolidation 应该有 run_sleep_cycle 方法"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        
        consolidation = SleepConsolidation()
        assert hasattr(consolidation, 'run_sleep_cycle')
        assert callable(consolidation.run_sleep_cycle)

    def test_run_sleep_cycle_calls_consolidate(self):
        """run_sleep_cycle 应该调用 consolidate 并返回结果"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        
        consolidation = SleepConsolidation()
        
        # 创建测试记忆
        from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord
        memories = [
            MemoryRecord(id="1", content="test1", embedding=[0.1, 0.2, 0.3]),
            MemoryRecord(id="2", content="test2", embedding=[0.1, 0.2, 0.3]),
        ]
        
        # 调用 run_sleep_cycle
        result = consolidation.run_sleep_cycle(memories)
        
        # 应该返回一个字典（向后兼容）
        assert isinstance(result, dict)
        assert "phase" in result
        assert "total_processed" in result
        assert "merged_count" in result
        assert "archived_count" in result


class TestSleepConsolidationConstructorAcceptsMemoryManager:
    """测试 SleepConsolidation 构造函数接受 memory_manager 参数"""

    def test_constructor_accepts_memory_manager_keyword(self):
        """构造函数应该接受 memory_manager 关键字参数"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        
        mock_memory_manager = Mock()
        
        # 这应该不会抛出 TypeError
        consolidation = SleepConsolidation(memory_manager=mock_memory_manager)
        assert consolidation.memory_manager is mock_memory_manager

    def test_constructor_accepts_storage_keyword(self):
        """构造函数应该接受 storage 关键字参数"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        
        mock_storage = Mock()
        
        # 这应该不会抛出 TypeError
        consolidation = SleepConsolidation(storage=mock_storage)
        assert consolidation.storage is mock_storage

    def test_constructor_accepts_all_parameters(self):
        """构造函数应该接受所有参数"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        
        mock_memory_manager = Mock()
        mock_storage = Mock()
        
        consolidation = SleepConsolidation(
            similarity_threshold=0.8,
            archive_threshold=25.0,
            decay_rate=0.05,
            memory_manager=mock_memory_manager,
            storage=mock_storage,
        )
        
        assert consolidation.similarity_threshold == 0.8
        assert consolidation.archive_threshold == 25.0
        assert consolidation.decay_rate == 0.05
        assert consolidation.memory_manager is mock_memory_manager
        assert consolidation.storage is mock_storage


class TestAgentCoreConnectsIdleTrackerAndSleepConsolidation:
    """测试 agent_core.py 正确连接 IdleTimeTracker 和 SleepConsolidation"""

    def test_agent_initializes_sleep_consolidation_without_error(self):
        """Agent 初始化 SleepConsolidation 时不应该抛出 TypeError"""
        # 这个测试会失败，因为当前代码传递了不接受的参数
        # 我们需要修复 agent_core.py 中的初始化代码
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        
        # 模拟 agent_core.py 中的调用
        mock_memory_manager = Mock()
        mock_storage = Mock()
        
        # 当前代码会抛出 TypeError，因为 SleepConsolidation 不接受这些参数
        # 修复后，这应该成功
        try:
            consolidation = SleepConsolidation(
                memory_manager=mock_memory_manager,
                storage=mock_storage,
            )
            # 如果成功，验证参数被保存
            assert consolidation.memory_manager is mock_memory_manager
            assert consolidation.storage is mock_storage
        except TypeError as e:
            pytest.fail(f"SleepConsolidation 构造函数不接受 memory_manager/storage 参数: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])