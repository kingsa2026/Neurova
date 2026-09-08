"""
模块有效性追踪器测试（对齐 neurova/core/module_tracker.py 真实契约）
测试 ModuleEffectivenessTracker 的访问记录、闭环检查、效果报告、低效模块检测。
"""

import pytest
from neurova.core.module_tracker import (
    ModuleEffectivenessTracker,
    LoopStatus,
    EffectivenessLevel,
    ModuleAccessRecord,
    ModuleLoopChecklist,
    EffectivenessReport,
)


@pytest.fixture
def tracker():
    """创建追踪器实例（check_interval 拉大避免周期线程空转，收尾 shutdown）"""
    t = ModuleEffectivenessTracker(check_interval=3600, ineffective_threshold=0.1)
    yield t
    t.shutdown()


class TestLoopStatus:
    """测试闭环状态枚举"""

    def test_loop_status_values(self):
        """测试闭环状态值"""
        assert LoopStatus.NOT_STARTED.value == "not_started"
        assert LoopStatus.IN_PROGRESS.value == "in_progress"
        assert LoopStatus.COMPLETED.value == "completed"
        assert LoopStatus.FAILED.value == "failed"
        assert LoopStatus.INEFFECTIVE.value == "ineffective"


class TestEffectivenessLevel:
    """测试有效性等级枚举"""

    def test_effectiveness_level_values(self):
        """测试有效性等级值"""
        assert EffectivenessLevel.HIGH.value == "high"
        assert EffectivenessLevel.MEDIUM.value == "medium"
        assert EffectivenessLevel.LOW.value == "low"
        assert EffectivenessLevel.INEFFECTIVE.value == "ineffective"
        assert EffectivenessLevel.UNKNOWN.value == "unknown"


class TestModuleAccessRecord:
    """测试模块访问记录"""

    def test_create_access_record(self):
        """测试创建访问记录"""
        record = ModuleAccessRecord(
            module_id="test_module",
            access_type="read",
            details={"caller": "test_caller"},
        )
        assert record.module_id == "test_module"
        assert record.access_type == "read"
        assert record.details == {"caller": "test_caller"}

    def test_access_record_to_dict(self):
        """测试访问记录字典化"""
        record = ModuleAccessRecord(module_id="m1", access_type="write")
        data = record.to_dict()
        assert data["module_id"] == "m1"
        assert data["access_type"] == "write"
        assert "timestamp" in data


class TestModuleLoopChecklist:
    """测试模块闭环检查清单"""

    def test_create_loop_checklist(self):
        """测试创建闭环检查清单（字段面：initialized/started/used/effective/optimized）"""
        checklist = ModuleLoopChecklist(module_id="test_module", initialized=True)
        assert checklist.module_id == "test_module"
        assert checklist.initialized is True
        assert checklist.started is False
        assert checklist.used is False
        assert checklist.effective is False
        assert checklist.issues == []

    def test_checklist_to_dict(self):
        """测试检查清单字典化"""
        checklist = ModuleLoopChecklist(module_id="m1", initialized=True, started=True)
        data = checklist.to_dict()
        assert data["module_id"] == "m1"
        assert data["initialized"] is True
        assert data["started"] is True


class TestEffectivenessReport:
    """测试效果评估报告"""

    def test_create_effectiveness_report(self):
        """测试创建效果评估报告"""
        report = EffectivenessReport(
            module_id="test_module",
            effectiveness_level=EffectivenessLevel.HIGH,
            write_count=10,
            read_count=12,
            read_write_ratio=1.2,
            recommendations=["Keep up the good work"],
        )
        assert report.module_id == "test_module"
        assert report.effectiveness_level == EffectivenessLevel.HIGH
        assert report.read_write_ratio == 1.2
        assert len(report.recommendations) == 1

    def test_report_to_dict(self):
        """测试报告字典化"""
        report = EffectivenessReport(module_id="m1", effectiveness_level=EffectivenessLevel.UNKNOWN)
        data = report.to_dict()
        assert data["module_id"] == "m1"
        assert data["effectiveness_level"] == "unknown"
        assert data["last_activity"] is None


class TestModuleEffectivenessTracker:
    """测试模块有效性追踪器"""

    def test_init(self, tracker):
        """测试初始化（契约：check_interval/ineffective_threshold）"""
        assert tracker is not None
        assert tracker._check_interval == 3600
        assert tracker._ineffective_threshold == 0.1

    def test_ensure_checklist(self, tracker):
        """测试确保检查清单存在（幂等）"""
        checklist = tracker._ensure_checklist("test_module")
        assert checklist is not None
        assert checklist.module_id == "test_module"
        assert tracker._ensure_checklist("test_module") is checklist

    def test_record_access_write(self, tracker):
        """测试记录写入访问（计数进 _write_counts）"""
        tracker.register_module("test_module")
        tracker.record_access(module_id="test_module", access_type="write", details={"op": "save"})

        assert tracker._write_counts["test_module"] == 1
        checklist = tracker._checklists["test_module"]
        assert checklist.used is True

    def test_record_access_read(self, tracker):
        """测试记录读取访问"""
        tracker.register_module("test_module")
        tracker.record_access(module_id="test_module", access_type="read")

        assert tracker._read_counts["test_module"] == 1
        assert tracker._checklists["test_module"].used is True

    def test_record_access_updates_effective(self, tracker):
        """有写且有足量读 → checklist.effective 置 True"""
        tracker.register_module("test_module")
        tracker.record_access("test_module", "write")
        for _ in range(3):
            tracker.record_access("test_module", "read")

        checklist = tracker._checklists["test_module"]
        assert checklist.effective is True  # ratio=3 > 0.1

    def test_on_lifecycle_callbacks(self, tracker):
        """生命周期回调推进 checklist 标志（on_stop 将 started 复位）"""
        tracker.on_initialize("m1")
        tracker.on_start("m1")

        checklist = tracker._checklists["m1"]
        assert checklist.initialized is True
        assert checklist.started is True

        tracker.on_stop("m1")
        assert tracker._checklists["m1"].started is False

    def test_get_effectiveness_level_unknown(self, tracker):
        """无任何访问 → UNKNOWN"""
        assert tracker.get_effectiveness_level("ghost") == EffectivenessLevel.UNKNOWN

    def test_get_effectiveness_level_high(self, tracker):
        """不写只读（write_count=0）或读写比 ≥1 → HIGH"""
        tracker.register_module("r_only")
        tracker.record_access("r_only", "read")
        assert tracker.get_effectiveness_level("r_only") == EffectivenessLevel.HIGH

        tracker.register_module("balanced")
        tracker.record_access("balanced", "write")
        tracker.record_access("balanced", "read")
        tracker.record_access("balanced", "read")
        assert tracker.get_effectiveness_level("balanced") == EffectivenessLevel.HIGH

    def test_write_without_reads_is_ineffective(self, tracker):
        """只写不读（产出无人消费）按读写比 0 判 INEFFECTIVE"""
        tracker.register_module("w_only")
        tracker.record_access("w_only", "write")
        assert tracker.get_effectiveness_level("w_only") == EffectivenessLevel.INEFFECTIVE

    def test_get_effectiveness_level_medium(self, tracker):
        """读写比 0.5~1 → MEDIUM"""
        tracker.register_module("m1")
        tracker.record_access("m1", "write")
        tracker.record_access("m1", "write")
        tracker.record_access("m1", "read")
        assert tracker.get_effectiveness_level("m1") == EffectivenessLevel.MEDIUM

    def test_get_effectiveness_level_ineffective(self, tracker):
        """读写比低于阈值 → INEFFECTIVE"""
        tracker.register_module("m1")
        for _ in range(20):
            tracker.record_access("m1", "write")
        tracker.record_access("m1", "read")  # ratio=0.05 < 0.1
        assert tracker.get_effectiveness_level("m1") == EffectivenessLevel.INEFFECTIVE

    def test_generate_report(self, tracker):
        """测试生成模块效果报告"""
        tracker.register_module("test_module")
        tracker.record_access("test_module", "write", {"caller": "c1"})
        tracker.record_access("test_module", "read", {"caller": "c2"})

        report = tracker.generate_report("test_module")
        assert report is not None
        assert report.module_id == "test_module"
        assert report.write_count == 1
        assert report.read_count == 1
        assert report.last_activity is not None

    def test_generate_report_unregistered_module(self, tracker):
        """未注册模块的报告为 UNKNOWN 级别（不抛错）"""
        report = tracker.generate_report("nonexistent")
        assert report is not None
        assert report.module_id == "nonexistent"
        assert report.effectiveness_level == EffectivenessLevel.UNKNOWN

    def test_generate_recommendations_ineffective(self, tracker):
        """低效级别给出整改建议"""
        recs = tracker._generate_recommendations("m1", EffectivenessLevel.INEFFECTIVE, 0.05)
        assert len(recs) >= 2
        assert any("m1" in r for r in recs)

    def test_generate_recommendations_unknown(self, tracker):
        """未使用模块给出检查建议"""
        recs = tracker._generate_recommendations("m1", EffectivenessLevel.UNKNOWN, 0.0)
        assert len(recs) >= 1

    def test_generate_recommendations_high(self, tracker):
        """高效级别无建议"""
        recs = tracker._generate_recommendations("m1", EffectivenessLevel.HIGH, 1.5)
        assert recs == []

    def test_get_inefficient_modules(self, tracker):
        """测试获取低效模块列表（只含注册过的低效模块）"""
        tracker.register_module("module1")
        tracker.register_module("module2")
        tracker.record_access("module1", "write")
        for _ in range(5):
            tracker.record_access("module2", "write")
            tracker.record_access("module2", "read")

        inefficient = tracker.get_inefficient_modules()
        assert len(inefficient) == 1
        assert inefficient[0]["module_id"] == "module1"

    def test_get_loop_status_summary(self, tracker):
        """测试获取闭环状态摘要（键面：total_modules/initialized/started/used/effective/checklists）"""
        tracker.register_module("module1")
        tracker.register_module("module2")
        tracker.record_access("module1", "write")

        summary = tracker.get_loop_status_summary()
        assert "total_modules" in summary
        assert "initialized" in summary
        assert "used" in summary
        assert "effective" in summary
        assert "checklists" in summary
        assert summary["total_modules"] == 2
        assert summary["used"] == 1

    def test_get_module_access_history(self, tracker):
        """测试获取模块访问历史"""
        tracker.record_access("test_module", "write")
        tracker.record_access("test_module", "read")

        history = tracker.get_module_access_history("test_module")
        assert len(history) == 2
        assert history[0]["access_type"] == "write"

    def test_get_module_access_history_with_limit(self, tracker):
        """测试获取模块访问历史（带限制）"""
        for i in range(10):
            tracker.record_access("test_module", "write")

        history = tracker.get_module_access_history("test_module", limit=5)
        assert len(history) == 5

    def test_register_unregister_module(self, tracker):
        """测试注册/注销模块（注销清理全部痕迹）"""
        tracker.register_module("new_module")
        assert "new_module" in tracker._modules
        assert "new_module" in tracker._checklists

        tracker.record_access("new_module", "write")
        tracker.unregister_module("new_module")

        assert "new_module" not in tracker._modules
        assert "new_module" not in tracker._checklists
        assert "new_module" not in tracker._access_records
        assert "new_module" not in tracker._write_counts

    def test_reset_stats_specific_module(self, tracker):
        """测试重置特定模块的统计"""
        tracker.register_module("test_module")
        tracker.record_access("test_module", "write")
        tracker.record_access("test_module", "read")

        tracker.reset_stats("test_module")

        assert tracker._write_counts["test_module"] == 0
        assert tracker._read_counts["test_module"] == 0
        assert tracker._checklists["test_module"].used is False

    def test_reset_stats_all_modules(self, tracker):
        """测试重置所有模块的统计"""
        tracker.register_module("module1")
        tracker.register_module("module2")
        tracker.record_access("module1", "write")
        tracker.record_access("module2", "write")

        tracker.reset_stats()

        assert tracker._write_counts == {}
        assert tracker._access_records == {}

    def test_access_details_defaults_to_dict(self, tracker):
        """details 缺省为空 dict"""
        tracker.record_access("test_module", "write")
        history = tracker.get_module_access_history("test_module")
        assert history[0]["details"] == {}


class TestPeriodicCheck:
    """测试定期检查"""

    def test_periodic_check_runs(self, tracker):
        """_periodic_check 同步触发全模块检查"""
        tracker.register_module("m1")
        tracker._periodic_check()  # 不抛错即通过

    def test_shutdown_stops_thread(self):
        """shutdown 后周期线程退出"""
        t = ModuleEffectivenessTracker(check_interval=3600)
        thread = t._check_thread
        assert thread is not None and thread.is_alive()

        t.shutdown()
        assert not thread.is_alive()


class TestGlobalFunctions:
    """测试单例管理"""

    def test_get_module_effectiveness_tracker(self):
        """单例两次获取同实例"""
        from neurova.core.module_tracker import get_module_effectiveness_tracker, reset_module_effectiveness_tracker

        reset_module_effectiveness_tracker()
        t1 = get_module_effectiveness_tracker(check_interval=3600)
        t2 = get_module_effectiveness_tracker()
        assert t1 is t2
        reset_module_effectiveness_tracker()
