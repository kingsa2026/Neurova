"""
模块有效性追踪器测试
测试 ModuleEffectivenessTracker 的各种功能，包括访问记录、闭环检查、效果报告等。
"""

import pytest
import sys
import os
import asyncio
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from neurova.core.module_tracker import (
    ModuleEffectivenessTracker,
    LoopStatus,
    EffectivenessLevel,
    ModuleAccessRecord,
    ModuleLoopChecklist,
    EffectivenessReport
)


class TestLoopStatus:
    """测试闭环状态枚举"""

    def test_loop_status_values(self):
        """测试闭环状态值"""
        assert LoopStatus.OPEN.value == "open"
        assert LoopStatus.PARTIAL.value == "partial"
        assert LoopStatus.CLOSED.value == "closed"
        assert LoopStatus.OVER_ENGINEERED.value == "over_engineered"


class TestEffectivenessLevel:
    """测试有效性等级枚举"""

    def test_effectiveness_level_values(self):
        """测试有效性等级值"""
        assert EffectivenessLevel.CRITICAL.value == "critical"
        assert EffectivenessLevel.LOW.value == "low"
        assert EffectivenessLevel.NORMAL.value == "normal"
        assert EffectivenessLevel.HIGH.value == "high"
        assert EffectivenessLevel.EXCELLENT.value == "excellent"


class TestModuleAccessRecord:
    """测试模块访问记录"""

    def test_create_access_record(self):
        """测试创建访问记录"""
        record = ModuleAccessRecord(
            timestamp=1234567890.0,
            access_type="read",
            caller="test_caller",
            details="test details"
        )
        assert record.timestamp == 1234567890.0
        assert record.access_type == "read"
        assert record.caller == "test_caller"
        assert record.details == "test details"


class TestModuleLoopChecklist:
    """测试模块闭环检查清单"""

    def test_create_loop_checklist(self):
        """测试创建闭环检查清单"""
        checklist = ModuleLoopChecklist(
            module_id="test_module",
            initialized=True,
            has_writes=True,
            has_reads=True,
            write_count=10,
            read_count=5
        )
        assert checklist.module_id == "test_module"
        assert checklist.initialized is True
        assert checklist.has_writes is True
        assert checklist.has_reads is True
        assert checklist.write_count == 10
        assert checklist.read_count == 5


class TestEffectivenessReport:
    """测试效果评估报告"""

    def test_create_effectiveness_report(self):
        """测试创建效果评估报告"""
        checklist = ModuleLoopChecklist(module_id="test_module")
        report = EffectivenessReport(
            module_id="test_module",
            loop_checklist=checklist,
            effectiveness_level=EffectivenessLevel.NORMAL,
            recommendations=["Keep up the good work"]
        )
        assert report.module_id == "test_module"
        assert report.loop_checklist == checklist
        assert report.effectiveness_level == EffectivenessLevel.NORMAL
        assert len(report.recommendations) == 1


class TestModuleEffectivenessTracker:
    """测试模块有效性追踪器"""

    @pytest.fixture
    def tracker(self, mock_event_bus, mock_logger):
        """创建追踪器实例"""
        return ModuleEffectivenessTracker(
            read_rate_threshold=0.5,
            warning_write_threshold=10,
            check_interval=300,
            event_bus=mock_event_bus,
            state_manager=MagicMock()
        )

    def test_init(self, tracker):
        """测试初始化"""
        assert tracker is not None
        assert tracker._read_rate_threshold == 0.5
        assert tracker._warning_write_threshold == 10
        assert tracker._check_interval == 300

    def test_initialize_all_modules(self, tracker):
        """测试初始化所有模块"""
        tracker._initialize_all_modules()

    def test_ensure_checklist(self, tracker):
        """测试确保检查清单存在"""
        checklist = tracker._ensure_checklist("test_module")
        assert checklist is not None
        assert checklist.module_id == "test_module"

    def test_record_access_write(self, tracker):
        """测试记录写入访问"""
        tracker.record_access(
            module_id="test_module",
            access_type="write",
            caller="test_caller",
            details="write operation"
        )
        
        checklist = tracker._loop_checklists.get("test_module")
        assert checklist is not None
        assert checklist.write_count == 1
        assert checklist.has_writes is True

    def test_record_access_read(self, tracker):
        """测试记录读取访问"""
        tracker.record_access(
            module_id="test_module",
            access_type="read",
            caller="test_caller",
            details="read operation"
        )
        
        checklist = tracker._loop_checklists.get("test_module")
        assert checklist is not None
        assert checklist.read_count == 1
        assert checklist.has_reads is True

    def test_update_loop_status_open(self, tracker):
        """测试更新闭环状态 - 开放"""
        checklist = ModuleLoopChecklist(module_id="test_module")
        tracker._update_loop_status(checklist)
        assert checklist.loop_status == LoopStatus.OPEN

    def test_update_loop_status_closed(self, tracker):
        """测试更新闭环状态 - 已闭环"""
        checklist = ModuleLoopChecklist(
            module_id="test_module",
            has_writes=True,
            has_reads=True,
            write_count=10,
            read_count=10
        )
        tracker._update_loop_status(checklist)
        assert checklist.loop_status == LoopStatus.CLOSED

    def test_update_loop_status_partial(self, tracker):
        """测试更新闭环状态 - 部分闭环"""
        checklist = ModuleLoopChecklist(
            module_id="test_module",
            has_writes=True,
            has_reads=True,
            write_count=10,
            read_count=3
        )
        tracker._update_loop_status(checklist)
        assert checklist.loop_status == LoopStatus.PARTIAL

    def test_update_loop_status_over_engineered(self, tracker):
        """测试更新闭环状态 - 过度设计"""
        checklist = ModuleLoopChecklist(
            module_id="test_module",
            has_writes=True,
            has_reads=False,
            write_count=15
        )
        tracker._update_loop_status(checklist)
        assert checklist.loop_status == LoopStatus.OVER_ENGINEERED

    def test_get_effectiveness_level_excellent(self, tracker):
        """测试获取有效性等级 - 优秀"""
        level = tracker.get_effectiveness_level(0.95)
        assert level == EffectivenessLevel.EXCELLENT

    def test_get_effectiveness_level_high(self, tracker):
        """测试获取有效性等级 - 高"""
        level = tracker.get_effectiveness_level(0.75)
        assert level == EffectivenessLevel.HIGH

    def test_get_effectiveness_level_normal(self, tracker):
        """测试获取有效性等级 - 正常"""
        level = tracker.get_effectiveness_level(0.55)
        assert level == EffectivenessLevel.NORMAL

    def test_get_effectiveness_level_low(self, tracker):
        """测试获取有效性等级 - 低"""
        level = tracker.get_effectiveness_level(0.30)
        assert level == EffectivenessLevel.LOW

    def test_get_effectiveness_level_critical(self, tracker):
        """测试获取有效性等级 - 严重不足"""
        level = tracker.get_effectiveness_level(0.10)
        assert level == EffectivenessLevel.CRITICAL

    def test_generate_report_specific_module(self, tracker):
        """测试生成特定模块的效果报告"""
        tracker.record_access("test_module", "write", "caller1")
        tracker.record_access("test_module", "read", "caller2")
        
        report = tracker.generate_report("test_module")
        assert report is not None
        assert report.module_id == "test_module"

    def test_generate_report_nonexistent_module(self, tracker):
        """测试生成不存在模块的报告"""
        report = tracker.generate_report("nonexistent")
        assert report is None

    def test_generate_recommendations_uninitialized(self, tracker):
        """测试生成未初始化模块的建议"""
        checklist = ModuleLoopChecklist(
            module_id="test_module",
            initialized=False
        )
        recommendations = tracker._generate_recommendations(checklist)
        assert any("未初始化" in r for r in recommendations)

    def test_generate_recommendations_no_reads(self, tracker):
        """测试生成无读取操作的建议"""
        checklist = ModuleLoopChecklist(
            module_id="test_module",
            initialized=True,
            has_writes=True,
            write_count=5,
            has_reads=False
        )
        recommendations = tracker._generate_recommendations(checklist)
        assert any("读取" in r for r in recommendations)

    def test_get_inefficient_modules(self, tracker):
        """测试获取低效模块列表"""
        tracker.record_access("module1", "write", "caller")
        tracker.record_access("module2", "write", "caller")
        tracker.record_access("module2", "read", "caller")
        
        inefficient = tracker.get_inefficient_modules()
        assert "module1" in inefficient

    def test_get_loop_status_summary(self, tracker):
        """测试获取闭环状态摘要"""
        tracker.record_access("module1", "write", "caller")
        tracker.record_access("module1", "read", "caller")
        tracker.record_access("module2", "write", "caller")
        
        summary = tracker.get_loop_status_summary()
        assert "total_modules" in summary
        assert "closed_loops" in summary
        assert "partial_loops" in summary
        assert "open_loops" in summary
        assert summary["total_modules"] >= 2

    def test_get_module_access_history(self, tracker):
        """测试获取模块访问历史"""
        tracker.record_access("test_module", "write", "caller1")
        tracker.record_access("test_module", "read", "caller2")
        
        history = tracker.get_module_access_history("test_module")
        assert len(history) == 2

    def test_get_module_access_history_with_limit(self, tracker):
        """测试获取模块访问历史（带限制）"""
        for i in range(10):
            tracker.record_access("test_module", "write", f"caller{i}")
        
        history = tracker.get_module_access_history("test_module", limit=5)
        assert len(history) == 5

    def test_register_module(self, tracker):
        """测试注册模块"""
        tracker.register_module("new_module")
        
        checklist = tracker._loop_checklists.get("new_module")
        assert checklist is not None
        assert checklist.module_id == "new_module"

    def test_unregister_module(self, tracker):
        """测试注销模块"""
        tracker.register_module("test_module")
        tracker.record_access("test_module", "write", "caller")
        
        tracker.unregister_module("test_module")
        
        checklist = tracker._loop_checklists.get("test_module")
        assert checklist is None
        
        records = tracker._access_records.get("test_module")
        assert records is None

    def test_reset_stats_specific_module(self, tracker):
        """测试重置特定模块的统计"""
        tracker.record_access("test_module", "write", "caller")
        tracker.record_access("test_module", "read", "caller")
        
        tracker.reset_stats("test_module")
        
        checklist = tracker._loop_checklists.get("test_module")
        assert checklist.write_count == 0
        assert checklist.read_count == 0

    def test_reset_stats_all_modules(self, tracker):
        """测试重置所有模块的统计"""
        tracker.record_access("module1", "write", "caller")
        tracker.record_access("module2", "write", "caller")
        
        tracker.reset_stats()
        
        checklist1 = tracker._loop_checklists.get("module1")
        checklist2 = tracker._loop_checklists.get("module2")
        assert checklist1.write_count == 0
        assert checklist2.write_count == 0


class TestAsyncOperations:
    """测试异步操作"""

    @pytest.fixture
    def tracker(self, mock_event_bus, mock_logger):
        """创建追踪器实例"""
        return ModuleEffectivenessTracker(
            event_bus=mock_event_bus,
            state_manager=MagicMock()
        )

    @pytest.mark.asyncio
    async def test_periodic_check(self, tracker):
        """测试定期检查"""
        tracker._check_task = asyncio.create_task(tracker._periodic_check())
        await asyncio.sleep(0.1)
        tracker._check_task.cancel()
        try:
            await tracker._check_task
        except asyncio.CancelledError:
            pass


class TestEdgeCases:
    """测试边界情况"""

    def test_multiple_access_types(self, tracker):
        """测试多种访问类型"""
        tracker.record_access("test_module", "write", "caller1")
        tracker.record_access("test_module", "read", "caller2")
        tracker.record_access("test_module", "write", "caller3")
        
        checklist = tracker._loop_checklists["test_module"]
        assert checklist.write_count == 2
        assert checklist.read_count == 1

    def test_access_with_none_details(self, tracker):
        """测试带None详情的访问"""
        tracker.record_access("test_module", "write", "caller", None)
        
        history = tracker.get_module_access_history("test_module")
        assert len(history) == 1
        assert history[0]["details"] is None

    def test_threshold_boundary(self, tracker):
        """测试阈值边界"""
        tracker._warning_write_threshold = 10
        
        checklist = ModuleLoopChecklist(
            module_id="test_module",
            has_writes=True,
            write_count=10,
            has_reads=False
        )
        tracker._update_loop_status(checklist)
        assert checklist.loop_status != LoopStatus.OVER_ENGINEERED
        
        checklist.write_count = 11
        tracker._update_loop_status(checklist)
        assert checklist.loop_status == LoopStatus.OVER_ENGINEERED

    def test_read_rate_threshold(self, tracker):
        """测试读取率阈值"""
        tracker._read_rate_threshold = 0.5
        
        checklist = ModuleLoopChecklist(
            module_id="test_module",
            has_writes=True,
            has_reads=True,
            write_count=5,
            read_count=3
        )
        tracker._update_loop_status(checklist)
        assert checklist.loop_status == LoopStatus.PARTIAL
        
        checklist.read_count = 5
        tracker._update_loop_status(checklist)
        assert checklist.loop_status == LoopStatus.CLOSED

    def test_empty_recommendations(self, tracker):
        """测试空建议列表"""
        checklist = ModuleLoopChecklist(
            module_id="test_module",
            initialized=True,
            has_writes=True,
            has_reads=True,
            write_count=5,
            read_count=5,
            loop_status=LoopStatus.CLOSED,
            effectiveness_score=0.8
        )
        recommendations = tracker._generate_recommendations(checklist)
        assert len(recommendations) > 0
