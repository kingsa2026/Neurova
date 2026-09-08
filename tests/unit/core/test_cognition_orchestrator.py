"""
认知编排器测试（对齐 neurova/core/cognition_orchestrator.py 真实契约）
测试 CognitionOrchestrator 的认知循环、注意力管理、记忆管理、元认知监控。
"""

import pytest
from unittest.mock import MagicMock

from neurova.core.cognition_orchestrator import (
    CognitionOrchestrator,
    CognitiveState,
    CognitiveCycleResult,
    AttentionLevel,
    MemoryType,
    AttentionManager,
    MemoryManager,
    MetacognitionMonitor,
)


class TestAttentionLevel:
    """测试注意力级别枚举"""

    def test_attention_level_values(self):
        """测试注意力级别值"""
        assert AttentionLevel.LOW.value == "low"
        assert AttentionLevel.MEDIUM.value == "medium"
        assert AttentionLevel.HIGH.value == "high"
        assert AttentionLevel.CRITICAL.value == "critical"


class TestMemoryType:
    """测试记忆类型枚举"""

    def test_memory_type_values(self):
        """测试记忆类型值"""
        assert MemoryType.SHORT_TERM.value == "short_term"
        assert MemoryType.WORKING.value == "working"
        assert MemoryType.LONG_TERM.value == "long_term"
        assert MemoryType.EPISODIC.value == "episodic"
        assert MemoryType.SEMANTIC.value == "semantic"


class TestCognitiveState:
    """测试认知状态"""

    def test_create_cognitive_state(self):
        """测试创建认知状态"""
        state = CognitiveState(
            attention_level=AttentionLevel.HIGH,
            current_focus="test focus",
            cognitive_load=0.7,
            metadata={"meta": "data"},
        )
        assert state.attention_level == AttentionLevel.HIGH
        assert state.current_focus == "test focus"
        assert state.cognitive_load == 0.7
        assert state.metadata == {"meta": "data"}

    def test_cognitive_state_defaults(self):
        """测试认知状态默认值"""
        state = CognitiveState()
        assert state.attention_level == AttentionLevel.MEDIUM
        assert state.active_memories == []
        assert state.current_focus == ""
        assert state.emotional_state == "neutral"
        assert state.cognitive_load == 0.0
        assert state.metadata == {}

    def test_cognitive_state_to_dict(self):
        """测试认知状态转换为字典"""
        state = CognitiveState(attention_level=AttentionLevel.HIGH, cognitive_load=0.6)
        data = state.to_dict()
        assert data["attention_level"] == "high"
        assert data["cognitive_load"] == 0.6
        assert "active_memories" in data
        assert "emotional_state" in data
        assert "timestamp" in data


class TestCognitiveCycleResult:
    """测试认知循环结果"""

    def test_create_cycle_result(self):
        """测试创建认知循环结果"""
        result = CognitiveCycleResult(
            cycle_id="c1",
            success=True,
            observations=["obs1"],
            duration_ms=1.5,
        )
        assert result.success is True
        assert result.observations == ["obs1"]
        assert result.duration_ms == 1.5

    def test_cycle_result_defaults(self):
        """测试认知循环结果默认值"""
        result = CognitiveCycleResult()
        assert result.cycle_id == ""
        assert result.success is False
        assert result.observations == []
        assert result.recalled_memories == []
        assert result.reasoning_steps == []
        assert result.reflections == []
        assert result.consolidated_memories == []
        assert result.duration_ms == 0.0
        assert result.error is None

    def test_cycle_result_to_dict(self):
        """测试认知循环结果字典化"""
        result = CognitiveCycleResult(cycle_id="c1", success=True, error=None)
        data = result.to_dict()
        assert data["cycle_id"] == "c1"
        assert data["success"] is True
        assert "reasoning_steps" in data
        assert "timestamp" in data


class TestAttentionManager:
    """测试注意力管理器"""

    @pytest.fixture
    def attention_manager(self):
        """创建注意力管理器实例"""
        return AttentionManager()

    def test_init(self, attention_manager):
        """测试初始化"""
        assert attention_manager.get_attention() == AttentionLevel.MEDIUM

    def test_get_attention(self, attention_manager):
        """测试获取注意力级别"""
        assert attention_manager.get_attention() == AttentionLevel.MEDIUM

    def test_set_attention(self, attention_manager):
        """测试设置注意力级别（契约：单参 level）"""
        success = attention_manager.set_attention(AttentionLevel.HIGH)
        assert success is True
        assert attention_manager.get_attention() == AttentionLevel.HIGH

    def test_attention_switch_history(self, attention_manager):
        """测试注意力切换历史（(时间, 级别) 元组）"""
        attention_manager.set_attention(AttentionLevel.HIGH)
        attention_manager.set_attention(AttentionLevel.CRITICAL)

        history = attention_manager._attention_history
        assert len(history) == 2
        assert history[0][1] == AttentionLevel.HIGH
        assert history[1][1] == AttentionLevel.CRITICAL

    def test_should_switch_attention_empty_focus(self, attention_manager):
        """当前无焦点时直接切换"""
        assert attention_manager.should_switch_attention("new", "", 0.1) is True

    def test_should_switch_attention_importance(self, attention_manager):
        """重要性超阈值切换；高注意力下低重要性不切换"""
        assert attention_manager.should_switch_attention("new", "cur", 0.8) is True
        assert attention_manager.should_switch_attention("new", "cur", 0.3) is False

        attention_manager.set_attention(AttentionLevel.HIGH)
        assert attention_manager.should_switch_attention("new", "cur", 0.6) is False
        assert attention_manager.should_switch_attention("new", "cur", 0.9) is True


class TestMemoryManager:
    """测试记忆管理器"""

    @pytest.fixture
    def memory_manager(self):
        """创建记忆管理器实例（契约：无参构造）"""
        return MemoryManager()

    def test_init(self, memory_manager):
        """测试初始化"""
        assert memory_manager is not None
        for mt in MemoryType:
            assert memory_manager.get_memories_by_type(mt) == []

    def test_add_memory(self, memory_manager):
        """测试添加记忆"""
        memory_id = memory_manager.add_memory(
            memory_type=MemoryType.SHORT_TERM,
            content="Test memory",
        )
        assert memory_id is not None
        assert memory_id != ""

    def test_add_memory_with_metadata(self, memory_manager):
        """测试添加带元数据的记忆"""
        memory_id = memory_manager.add_memory(
            memory_type=MemoryType.WORKING,
            content="Test memory",
            metadata={"key": "value"},
        )
        results = memory_manager.retrieve_memory("Test memory", MemoryType.WORKING)
        assert len(results) == 1
        assert results[0]["metadata"] == {"key": "value"}

    def test_retrieve_memory(self, memory_manager):
        """测试检索记忆（契约：query 子串匹配，返回列表）"""
        memory_manager.add_memory(memory_type=MemoryType.SHORT_TERM, content="Test memory")

        results = memory_manager.retrieve_memory("Test")

        assert len(results) == 1
        assert results[0]["content"] == "Test memory"
        assert results[0]["access_count"] == 1

    def test_retrieve_nonexistent_memory(self, memory_manager):
        """测试检索不存在的记忆"""
        results = memory_manager.retrieve_memory("nonexistent")
        assert results == []

    def test_get_memories_by_type(self, memory_manager):
        """测试按类型获取记忆"""
        memory_manager.add_memory(MemoryType.SHORT_TERM, "Memory 1")
        memory_manager.add_memory(MemoryType.SHORT_TERM, "Memory 2")
        memory_manager.add_memory(MemoryType.WORKING, "Memory 3")

        short_term = memory_manager.get_memories_by_type(MemoryType.SHORT_TERM)
        working = memory_manager.get_memories_by_type(MemoryType.WORKING)

        assert len(short_term) == 2
        assert len(working) == 1

    def test_clear_memories(self, memory_manager):
        """测试清空指定类型记忆"""
        memory_manager.add_memory(MemoryType.SHORT_TERM, "Memory 1")
        memory_manager.add_memory(MemoryType.WORKING, "Memory 2")

        count = memory_manager.clear_memories(MemoryType.SHORT_TERM)
        assert count == 1

        assert memory_manager.get_memories_by_type(MemoryType.SHORT_TERM) == []
        assert len(memory_manager.get_memories_by_type(MemoryType.WORKING)) == 1

    def test_clear_all_memories(self, memory_manager):
        """测试清空所有记忆"""
        memory_manager.add_memory(MemoryType.SHORT_TERM, "Memory 1")
        memory_manager.add_memory(MemoryType.WORKING, "Memory 2")
        memory_manager.add_memory(MemoryType.LONG_TERM, "Memory 3")

        count = memory_manager.clear_memories()
        assert count == 3


class TestCognitionOrchestrator:
    """测试认知编排器"""

    @pytest.fixture
    def orchestrator(self):
        """创建认知编排器实例"""
        return CognitionOrchestrator()

    def test_init(self, orchestrator):
        """测试初始化"""
        assert orchestrator is not None
        assert orchestrator._attention_manager is not None
        assert orchestrator._memory_manager is not None
        assert orchestrator._cognitive_state is not None

    def test_get_cognitive_state(self, orchestrator):
        """测试获取认知状态"""
        state = orchestrator.get_cognitive_state()
        assert state is not None
        assert isinstance(state, CognitiveState)

    def test_update_cognitive_state(self, orchestrator):
        """测试更新认知状态（契约：收 CognitiveState 对象）"""
        orchestrator.update_cognitive_state(
            CognitiveState(attention_level=AttentionLevel.HIGH, cognitive_load=0.8)
        )
        state = orchestrator.get_cognitive_state()
        assert state.attention_level == AttentionLevel.HIGH
        assert state.cognitive_load == 0.8

    def test_update_cognitive_state_isolated_copy(self, orchestrator):
        """get_cognitive_state 返回深拷贝，外部修改不污染内部状态"""
        state = CognitiveState(current_focus="focus1")
        orchestrator.update_cognitive_state(state)

        retrieved = orchestrator.get_cognitive_state()
        retrieved.current_focus = "mutated"

        assert orchestrator.get_cognitive_state().current_focus == "focus1"

    def test_get_attention_manager(self, orchestrator):
        """测试获取注意力管理器"""
        manager = orchestrator.get_attention_manager()
        assert manager is not None
        assert isinstance(manager, AttentionManager)

    def test_get_memory_manager(self, orchestrator):
        """测试获取记忆管理器"""
        manager = orchestrator.get_memory_manager()
        assert manager is not None
        assert isinstance(manager, MemoryManager)

    @pytest.mark.asyncio
    async def test_process_task(self, orchestrator):
        """测试处理任务（契约：async process_task(task)）"""
        result = await orchestrator.process_task("Test task")
        assert result is not None
        assert result["success"] is True
        assert "cycle_result" in result
        assert "selected_skill" in result
        assert "duration_ms" in result

    @pytest.mark.asyncio
    async def test_process_thought_cycle(self, orchestrator):
        """测试处理认知循环"""
        result = await orchestrator.process_thought_cycle("Test query")

        assert result is not None
        assert isinstance(result, CognitiveCycleResult)
        assert result.success is True
        assert result.duration_ms >= 0
        assert result.cycle_id != ""

    @pytest.mark.asyncio
    async def test_process_thought_cycle_empty_input(self, orchestrator):
        """测试空输入的认知循环不崩"""
        result = await orchestrator.process_thought_cycle("")
        assert result is not None
        assert result.success is True

    @pytest.mark.asyncio
    async def test_multiple_cycles_count(self, orchestrator):
        """测试多次认知循环累计周期计数"""
        for i in range(3):
            result = await orchestrator.process_thought_cycle(f"Query {i}")
            assert result.success is True

        assert orchestrator._cycle_count == 3

    def test_select_skill_for_task(self, orchestrator):
        """测试为任务选择技能（契约：无 registry 时返回 None）"""
        assert orchestrator.select_skill_for_task("Test task") is None

    def test_select_skill_for_task_with_registry(self, orchestrator):
        """注册 registry 后按 keywords 匹配最高分技能"""
        skill = MagicMock()
        skill.keywords = ["deploy"]
        registry = MagicMock()
        registry.list_skills.return_value = [skill]

        orchestrator.set_registry(registry)

        assert orchestrator.select_skill_for_task("please deploy app") is skill

    def test_enable_metacognition(self, orchestrator):
        """测试启用元认知监控"""
        orchestrator.enable_metacognition(True)
        assert orchestrator._metacognition_enabled is True
        assert orchestrator._metacognition_monitor is not None

        orchestrator.enable_metacognition(False)
        assert orchestrator._metacognition_enabled is False

    def test_get_metacognition_report_disabled(self, orchestrator):
        """未启用元认知时报告为 None"""
        assert orchestrator.get_metacognition_report() is None

    @pytest.mark.asyncio
    async def test_get_metacognition_report(self, orchestrator):
        """启用后报告键面对齐实现"""
        orchestrator.enable_metacognition(True)
        await orchestrator.process_thought_cycle("Test query")

        report = orchestrator.get_metacognition_report()
        assert report is not None
        assert report["monitoring"] is True
        assert report["total_cycles"] == 1
        assert report["successful_cycles"] == 1
        assert "success_rate" in report
        assert "average_duration_ms" in report

    def test_set_registry(self, orchestrator):
        """测试设置技能注册表"""
        mock_registry = MagicMock()
        orchestrator.set_registry(mock_registry)
        assert orchestrator.get_registry() is mock_registry


class TestMetacognitionMonitor:
    """测试元认知监控器"""

    @pytest.fixture
    def monitor(self):
        """创建元认知监控器实例（契约：构造需 orchestrator）"""
        return MetacognitionMonitor(CognitionOrchestrator())

    def test_init(self, monitor):
        """测试初始化"""
        assert monitor is not None
        assert monitor._monitoring is False

    def test_start_stop_monitoring(self, monitor):
        """测试启动和停止监控"""
        monitor.start_monitoring()
        assert monitor._monitoring is True

        monitor.stop_monitoring()
        assert monitor._monitoring is False

    def test_record_cycle_requires_monitoring(self, monitor):
        """未开启监控时 record_cycle 不记录"""
        result = CognitiveCycleResult(cycle_id="c1", success=True, duration_ms=1.0)
        monitor.record_cycle(result)

        report = monitor.get_report()
        assert report["total_cycles"] == 0

    def test_record_cycle(self, monitor):
        """测试记录认知循环"""
        monitor.start_monitoring()

        result = CognitiveCycleResult(cycle_id="c1", success=True, duration_ms=1.5)
        monitor.record_cycle(result)

        report = monitor.get_report()
        assert report["total_cycles"] == 1
        assert report["successful_cycles"] == 1

    def test_record_failed_cycle(self, monitor):
        """测试记录失败的认知循环（产生 cycle_failed 警报）"""
        monitor.start_monitoring()

        result = CognitiveCycleResult(cycle_id="c1", success=False, error="boom", duration_ms=2.0)
        monitor.record_cycle(result)

        report = monitor.get_report()
        assert report["total_cycles"] == 1
        assert report["successful_cycles"] == 0
        assert any(a["type"] == "cycle_failed" for a in report["alerts"])

    def test_get_report(self, monitor):
        """测试获取监控报告键面"""
        report = monitor.get_report()
        assert report is not None
        assert "monitoring" in report
        assert "total_cycles" in report
        assert "success_rate" in report
        assert "average_duration_ms" in report
        assert "alerts" in report

    def test_execution_time_anomaly(self, monitor):
        """测试执行时间异常检测（>10s 触发 slow_cycle）"""
        monitor.start_monitoring()

        result = CognitiveCycleResult(cycle_id="c1", success=True, duration_ms=15000.0)
        monitor.record_cycle(result)

        report = monitor.get_report()
        assert any(a["type"] == "slow_cycle" for a in report["alerts"])


class TestEdgeCases:
    """测试边界情况"""

    def test_empty_query(self):
        """测试空查询"""
        orchestrator = CognitionOrchestrator()
        state = orchestrator.get_cognitive_state()
        assert state is not None

    def test_memory_type_isolation(self):
        """不同记忆类型互不串扰"""
        manager = MemoryManager()
        manager.add_memory(MemoryType.EPISODIC, "episodic content")
        manager.add_memory(MemoryType.SEMANTIC, "semantic content")

        episodic = manager.retrieve_memory("content", MemoryType.EPISODIC)
        semantic = manager.retrieve_memory("content", MemoryType.SEMANTIC)

        assert len(episodic) == 1
        assert len(semantic) == 1
        assert episodic[0]["content"] != semantic[0]["content"]
