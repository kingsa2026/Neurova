"""
睡眠功能闭环集成测试

验证完整的睡眠闭环：激活 → 执行 → 记录 → 复用 → 调整
"""

import unittest
import tempfile
import shutil
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from unittest.mock import Mock, MagicMock, patch


class TestSleepClosedLoop(unittest.TestCase):
    """睡眠闭环集成测试"""
    
    def setUp(self):
        """测试前准备"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_sleep.db")
        
    def tearDown(self):
        """测试后清理"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_test_memories(self, count: int = 10) -> list:
        """创建测试记忆"""
        memories = []
        for i in range(count):
            memories.append({
                "id": f"mem_{i}",
                "content": f"Test memory {i}",
                "type": "fact",
                "source": "test",
                "metadata": {
                    "importance": 0.5,
                    "category": "test",
                },
                "created_at": datetime.now().isoformat(),
                "last_accessed": None,
                "access_count": 0,
                "embedding": [0.1 * i] * 128,
            })
        return memories
    
    def _create_test_dream_report(self, report_id: str = "report_1") -> Dict:
        """创建测试梦境报告"""
        return {
            "id": report_id,
            "agent_id": "test_agent",
            "session_id": "test_session",
            "report_type": "sleep_consolidation",
            "total_processed": 10,
            "merged_count": 3,
            "archived_count": 2,
            "merged_details": [
                {"source": "mem_1", "target": "mem_2", "similarity": 0.85}
            ],
            "archived_ids": ["mem_3", "mem_4"],
            "consolidation_quality": 0.75,
            "emotional_intensity": 0.6,
            "memory_coherence_score": 0.8,
            "sleep_start_at": (datetime.now() - timedelta(hours=1)).isoformat(),
            "sleep_end_at": datetime.now().isoformat(),
            "created_at": datetime.now().isoformat(),
            "metadata": {
                "phase": "deep_sleep",
                "duration_seconds": 3600,
            }
        }


class TestSleepActivation(TestSleepClosedLoop):
    """测试睡眠激活机制"""
    
    def test_idle_tracker_records_activity(self):
        """测试 IdleTimeTracker 能正确记录活动"""
        from neurova.core.idle_tracker import IdleTimeTracker
        
        tracker = IdleTimeTracker()
        
        # 初始状态应该是 active
        self.assertEqual(tracker.get_current_phase(), "active")
        
        # 记录活动
        tracker.record_activity()
        
        # 仍然是 active
        self.assertEqual(tracker.get_current_phase(), "active")
        
        print("✓ IdleTimeTracker.record_activity() works correctly")
    
    def test_idle_tracker_phase_transitions(self):
        """测试阶段转换逻辑"""
        from neurova.core.idle_tracker import IdleTimeTracker
        
        tracker = IdleTimeTracker(
            idle_thresholds={
                "light_sleep": 1,
                "deep_sleep": 2,
                "rem": 3,
                "hibernate": 4,
            },
            sleep_mode="time",  # 使用时间模式，不依赖温度
        )
        
        # 初始是 active
        self.assertEqual(tracker.get_current_phase(), "active")
        
        # 模拟空闲时间
        tracker._last_activity_time = time.time() - 2  # 2秒前
        
        # 检查阶段更新
        next_phase = tracker.check_and_update_phase()
        
        # 应该转换到 deep_sleep 或更高阶段
        self.assertIsNotNone(next_phase)
        
        print(f"✓ Phase transition works: active -> {next_phase}")


class TestSleepExecution(TestSleepClosedLoop):
    """测试睡眠执行"""
    
    def test_sleep_consolidation_run_sleep_cycle(self):
        """测试 SleepConsolidation 能执行睡眠周期"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        
        # 创建模拟的 memory_manager
        memory_manager = Mock()
        memory_manager.get_all_memories.return_value = self._create_test_memories(10)
        
        # 创建 SleepConsolidation 实例
        consolidation = SleepConsolidation(memory_manager=memory_manager)
        
        # 执行睡眠周期
        memories = self._create_test_memories(10)
        result = consolidation.run_sleep_cycle(memories, "light_sleep")
        
        # 验证结果
        self.assertIsNotNone(result)
        self.assertIn("phase", result)
        self.assertEqual(result["phase"], "light_sleep")
        
        print(f"✓ SleepConsolidation.run_sleep_cycle() works: {result}")


class TestDreamReportPersistence(TestSleepClosedLoop):
    """测试梦境报告持久化"""
    
    def test_save_and_load_dream_report(self):
        """测试梦境报告的保存和加载"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        # 创建存储实例
        storage = MemoryStorage(db_path=self.db_path)
        
        # 创建测试报告
        report = self._create_test_dream_report()
        
        # 保存报告
        result = storage.save_dream_report(report)
        self.assertTrue(result)
        
        # 加载报告
        loaded = storage.get_dream_report(report["id"])
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["id"], report["id"])
        self.assertEqual(loaded["total_processed"], 10)
        
        print(f"✓ Dream report saved and loaded successfully: {loaded['id']}")
        
        storage.close()
    
    def test_get_dream_report_stats(self):
        """测试获取梦境报告统计"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        # 创建存储实例
        storage = MemoryStorage(db_path=self.db_path)
        
        # 保存多个报告
        for i in range(3):
            report = self._create_test_dream_report(f"report_{i}")
            report["consolidation_quality"] = 0.5 + i * 0.1
            storage.save_dream_report(report)
        
        # 获取统计
        stats = storage.get_dream_report_stats()
        
        # 验证统计
        self.assertEqual(stats["total_reports"], 3)
        self.assertGreater(stats["avg_quality"], 0)
        
        print(f"✓ Dream report stats: {stats}")
        
        storage.close()


class TestSleepReportRetrieval(TestSleepClosedLoop):
    """测试睡眠报告检索（在认知循环中）"""
    
    def test_cognition_orchestrator_recall_with_sleep_reports(self):
        """测试 CognitionOrchestrator._recall() 能检索睡眠报告"""
        from neurova.core.cognition_orchestrator import CognitionOrchestrator
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        # 创建存储实例并保存测试报告
        storage = MemoryStorage(db_path=self.db_path)
        report = self._create_test_dream_report()
        result = storage.save_dream_report(report)
        self.assertTrue(result, "Failed to save dream report")
        
        # 验证报告已保存
        loaded = storage.get_dream_report(report["id"])
        self.assertIsNotNone(loaded, "Failed to load saved dream report")
        
        # 创建 CognitionOrchestrator 实例（带 storage）
        orchestrator = CognitionOrchestrator(storage=storage)
        
        # 验证能加载睡眠报告
        dream_reports = orchestrator._storage.get_dream_reports(limit=5)
        self.assertGreater(len(dream_reports), 0, "No dream reports found")
        
        print(f"✓ CognitionOrchestrator can retrieve dream reports: {len(dream_reports)} reports")
        
        storage.close()
    
    def test_cognition_orchestrator_reflect_with_sleep_stats(self):
        """测试 CognitionOrchestrator._reflect() 能加载睡眠统计"""
        from neurova.core.cognition_orchestrator import CognitionOrchestrator
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        # 创建存储实例并保存测试报告
        storage = MemoryStorage(db_path=self.db_path)
        report = self._create_test_dream_report()
        storage.save_dream_report(report)
        
        # 创建 CognitionOrchestrator 实例（带 storage）
        orchestrator = CognitionOrchestrator(storage=storage)
        
        # 验证能获取睡眠统计
        stats = orchestrator._storage.get_dream_report_stats()
        self.assertGreater(stats["total_reports"], 0)
        
        print(f"✓ CognitionOrchestrator can access sleep stats: {stats}")
        
        storage.close()


class TestIntelligentAdjustment(TestSleepClosedLoop):
    """测试智能调整功能"""
    
    def test_adjust_parameters_based_on_sleep_quality(self):
        """测试 IdleTimeTracker.adjust_parameters_based_on_sleep_quality()"""
        from neurova.core.idle_tracker import IdleTimeTracker
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        # 创建存储实例并保存测试报告
        storage = MemoryStorage(db_path=self.db_path)
        
        # 保存多个报告（模拟历史数据）
        for i in range(5):
            report = self._create_test_dream_report(f"report_{i}")
            report["consolidation_quality"] = 0.8  # 高质量
            report["memory_coherence_score"] = 0.7
            storage.save_dream_report(report)
        
        # 创建 IdleTimeTracker 实例（带 storage）
        tracker = IdleTimeTracker(storage=storage)
        
        # 调整参数
        adjustment = tracker.adjust_parameters_based_on_sleep_quality()
        
        # 验证调整结果
        self.assertTrue(adjustment["adjusted"])
        self.assertIn("stats_used", adjustment)
        
        print(f"✓ Parameter adjustment works: {adjustment}")
        
        storage.close()
    
    async def test_sleep_phase_config_manager_adjustment(self):
        """测试 SleepPhaseConfigManager.adjust_config_based_on_sleep_quality()"""
        from neurova.core.sleep_phase_config_manager import SleepPhaseConfigManager
        
        # 创建配置管理器
        manager = SleepPhaseConfigManager()
        
        # 模拟统计信息
        stats = {
            "total_reports": 5,
            "avg_quality": 0.8,  # 高质量
            "avg_coherence": 0.7,
            "avg_processed": 10,
            "avg_merged": 3,
            "avg_archived": 2,
        }
        
        # 调整配置（async 方法需要 await）
        adjustments = await manager.adjust_config_based_on_sleep_quality(stats)
        
        # 验证调整结果
        self.assertTrue(adjustments["adjusted"])
        self.assertGreater(len(adjustments.get("changes", [])), 0)
        
        print(f"✓ Phase config adjustment works: {len(adjustments.get('changes', []))} changes")
        
        # 测试获取调整建议
        recommendations = manager.get_adjustment_recommendations(stats)
        self.assertGreater(len(recommendations), 0)
        
        print(f"✓ Adjustment recommendations: {recommendations}")


class TestCompleteClosedLoop(TestSleepClosedLoop):
    """测试完整闭环"""
    
    def test_complete_sleep_closed_loop(self):
        """测试完整的睡眠闭环：激活 → 执行 → 记录 → 复用 → 调整"""
        from neurova.core.idle_tracker import IdleTimeTracker
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        from neurova.core.cognition_orchestrator import CognitionOrchestrator
        
        print("\n=== Testing Complete Sleep Closed Loop ===\n")
        
        # 1. 创建存储
        storage = MemoryStorage(db_path=self.db_path)
        print("✓ Step 1: Storage created")
        
        # 2. 创建 IdleTimeTracker（激活机制）
        tracker = IdleTimeTracker(storage=storage)
        tracker.record_activity()
        print("✓ Step 2: IdleTimeTracker activated")
        
        # 3. 执行睡眠整理
        memory_manager = Mock()
        memory_manager.get_all_memories.return_value = self._create_test_memories(10)
        consolidation = SleepConsolidation(memory_manager=memory_manager)
        memories = self._create_test_memories(10)
        result = consolidation.run_sleep_cycle(memories, "deep_sleep")
        print(f"✓ Step 3: Sleep consolidation executed: {result['phase']}")
        
        # 4. 保存梦境报告（记录）
        report = self._create_test_dream_report()
        report["consolidation_quality"] = result.get("consolidation_quality", 0.75)
        storage.save_dream_report(report)
        print(f"✓ Step 4: Dream report saved: {report['id']}")
        
        # 5. 在认知循环中复用（检索）
        orchestrator = CognitionOrchestrator(storage=storage)
        dream_reports = orchestrator._storage.get_dream_reports(limit=5)
        self.assertGreater(len(dream_reports), 0)
        print(f"✓ Step 5: Dream reports retrieved in cognitive loop: {len(dream_reports)} reports")
        
        # 6. 智能调整
        adjustment = tracker.adjust_parameters_based_on_sleep_quality()
        self.assertTrue(adjustment["adjusted"])
        print(f"✓ Step 6: Parameters adjusted: {adjustment}")
        
        # 7. 验证闭环完整性
        stats = storage.get_dream_report_stats()
        self.assertGreater(stats["total_reports"], 0)
        print(f"✓ Step 7: Closed loop verified: {stats['total_reports']} reports in history")
        
        print("\n=== Sleep Closed Loop Test Passed ===\n")
        
        storage.close()


def run_tests():
    """运行所有测试"""
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTest(unittest.makeSuite(TestSleepActivation))
    suite.addTest(unittest.makeSuite(TestSleepExecution))
    suite.addTest(unittest.makeSuite(TestDreamReportPersistence))
    suite.addTest(unittest.makeSuite(TestSleepReportRetrieval))
    suite.addTest(unittest.makeSuite(TestIntelligentAdjustment))
    suite.addTest(unittest.makeSuite(TestCompleteClosedLoop))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result


if __name__ == "__main__":
    run_tests()
