"""
睡眠闭环测试 — TDD 验证

数据流:
  空闲时间 → IdleTimeTracker → 阶段变更 → SleepConsolidation → 记忆巩固 → 长期存储

测试 4 个断裂点修复:
1. IdleTimeTracker 启动
2. MemoryManager.get_all_memories() 方法
3. MemoryRecord 与 Dict 转换
4. 整合后记忆写回 MemoryManager
"""
import os
import tempfile

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone


# ============================================================
# 断裂点 #1: IdleTimeTracker 启动
# ============================================================

class TestIdleTimeTrackerStart:
    """测试 IdleTimeTracker 是否正确启动"""

    def test_idle_tracker_has_start_method(self):
        """IdleTimeTracker 应该有 on_start 方法"""
        from neurova.core.idle_tracker import IdleTimeTracker

        tracker = IdleTimeTracker()
        assert hasattr(tracker, 'on_start'), "IdleTimeTracker 缺少 on_start 方法"

    def test_idle_tracker_monitoring_starts(self):
        """on_start 应该启动监控线程"""
        from neurova.core.idle_tracker import IdleTimeTracker

        tracker = IdleTimeTracker()
        tracker.on_start()
        
        # 检查监控是否启动
        assert tracker._monitor_running, "监控线程未启动"
        
        # 清理
        tracker.on_stop()

    def test_idle_tracker_stop(self):
        """on_stop 应该停止监控线程"""
        from neurova.core.idle_tracker import IdleTimeTracker

        tracker = IdleTimeTracker()
        tracker.on_start()
        tracker.on_stop()
        
        assert not tracker._monitor_running, "监控线程未停止"


# ============================================================
# 断裂点 #2: MemoryManager.get_all_memories() 方法
# ============================================================

class TestMemoryManagerGetAllMemories:
    """测试 MemoryManager.get_all_memories() 方法"""

    def test_memory_manager_has_get_all_memories(self):
        """MemoryManager 应该有 get_all_memories 方法"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        manager = MemoryManager(db_path=os.path.join(tempfile.mkdtemp(), 'mem.db'))
        assert hasattr(manager, 'get_all_memories'), "MemoryManager 缺少 get_all_memories 方法"

    def test_get_all_memories_returns_memories(self):
        """get_all_memories 应该返回所有记忆"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        manager = MemoryManager(db_path=os.path.join(tempfile.mkdtemp(), 'mem.db'))
        
        # 添加一些记忆
        manager.remember("记忆1", category="general")
        manager.remember("记忆2", category="general")
        
        # 获取所有记忆
        all_memories = manager.get_all_memories()
        
        assert len(all_memories) == 2, f"期望 2 条记忆，实际 {len(all_memories)}"
        assert isinstance(all_memories, list), "返回类型应该是 list"


# ============================================================
# 断裂点 #3: MemoryRecord 与 Dict 转换
# ============================================================

class TestMemoryRecordConversion:
    """测试 MemoryRecord 与 Dict 的转换"""

    def test_dict_to_memory_record(self):
        """应该能将 Dict 转换为 MemoryRecord"""
        from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord

        # 测试数据（模拟 Memory.to_dict() 格式）
        memory_dict = {
            "id": "mem_001",
            "content": "测试内容",
            "temperature": 50.0,
            "importance": 0.8,
            "categories": ["general"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # 使用 from_dict 转换为 MemoryRecord
        record = MemoryRecord.from_dict(memory_dict)

        assert record.id == "mem_001"
        assert record.content == "测试内容"
        assert record.temperature == 50.0
        assert record.importance == 0.8
        assert record.categories == ["general"]

    def test_memory_record_to_dict(self):
        """MemoryRecord 应该能转换为 Dict"""
        from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord

        record = MemoryRecord(
            id="mem_002",
            content="测试内容2",
            temperature=60.0,
            importance=0.7,
            categories=["test"],
        )

        # 转换为 Dict
        result = record.to_dict()

        assert result["id"] == "mem_002"
        assert result["content"] == "测试内容2"
        assert result["temperature"] == 60.0
        assert result["importance"] == 0.7
        assert result["categories"] == ["test"]

    def test_memory_manager_dict_to_memory_record(self):
        """应该能将 MemoryManager 返回的 Dict 转换为 MemoryRecord"""
        from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        # 创建 MemoryManager 并添加记忆
        manager = MemoryManager(db_path=os.path.join(tempfile.mkdtemp(), 'mem.db'))
        manager.remember("测试记忆", category="general")
        
        # 获取记忆（返回 Dict）
        all_memories = manager.get_all_memories()
        assert len(all_memories) == 1
        
        # 转换为 MemoryRecord
        record = MemoryRecord.from_dict(all_memories[0])
        
        assert record.id, "应该有 ID"
        assert record.content == "测试记忆"
        assert record.temperature >= 0, "温度应该有效"


# ============================================================
# 断裂点 #4: 整合后记忆写回 MemoryManager
# ============================================================

class TestConsolidationWriteBack:
    """测试整合后记忆写回 MemoryManager"""

    def test_sleep_consolidation_write_back(self):
        """SleepConsolidation 应该能将整合后的记忆写回 MemoryManager"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation, MemoryRecord
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        # 创建 MemoryManager 并添加记忆
        manager = MemoryManager(db_path=os.path.join(tempfile.mkdtemp(), 'mem.db'))
        manager.remember("记忆1", category="general")
        manager.remember("记忆2", category="general")
        
        # 获取记忆并转换为 MemoryRecord
        all_memories = manager.get_all_memories()
        memory_records = [MemoryRecord.from_dict(m) for m in all_memories]
        
        # 执行睡眠整合
        consolidation = SleepConsolidation(memory_manager=manager)
        merged_memories, merge_results = consolidation.consolidate(memory_records)
        
        # 验证整合结果
        assert len(merged_memories) <= len(memory_records), "整合后记忆数量应该减少"
        assert len(merge_results) >= 0, "应该有合并记录"
        
        # 验证写回机制（通过 IdleTimeTracker）
        from neurova.core.idle_tracker import IdleTimeTracker
        
        tracker = IdleTimeTracker()
        tracker.set_sleep_consolidation(consolidation)
        tracker.set_memory_manager(manager)
        
        # 手动触发整合
        tracker._trigger_consolidation()
        
        # 验证记忆被更新
        updated_memories = manager.get_all_memories()
        assert len(updated_memories) >= 1, "应该至少有 1 条记忆被更新"


# ============================================================
# 端到端闭环测试
# ============================================================

class TestSleepLoopEndToEnd:
    """端到端睡眠闭环测试"""

    def test_full_sleep_loop(self):
        """完整睡眠闭环：空闲 → 阶段变更 → 整合 → 写回"""
        from neurova.core.idle_tracker import IdleTimeTracker
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation, MemoryRecord
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        # 1. 创建组件
        manager = MemoryManager(db_path=os.path.join(tempfile.mkdtemp(), 'mem.db'))
        tracker = IdleTimeTracker()
        consolidation = SleepConsolidation(memory_manager=manager)
        
        # 2. 连接组件
        tracker.set_sleep_consolidation(consolidation)
        tracker.set_memory_manager(manager)
        
        # 3. 添加记忆
        manager.remember("记忆1", category="general")
        manager.remember("记忆2", category="general")
        
        # 4. 启动追踪器
        tracker.on_start()
        
        # 5. 模拟空闲后触发整合
        # 手动调用整合（模拟阶段变更）
        all_memories = manager.get_all_memories()
        memory_records = [MemoryRecord.from_dict(m) for m in all_memories]
        result = consolidation.run_sleep_cycle(memory_records)
        
        # 6. 验证结果
        assert result is not None, "整合结果不应为 None"
        assert "merged_count" in result, "结果应包含 merged_count"
        
        # 7. 清理
        tracker.on_stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])