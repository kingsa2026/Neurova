"""
认知编排器测试
测试 CognitionOrchestrator 的各种功能，包括认知循环、注意力管理、记忆管理等。
"""

import pytest
import sys
import os
import time
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from neurova.core.cognition_orchestrator import (
    CognitionOrchestrator,
    CognitiveState,
    CognitiveCycleResult,
    AttentionLevel,
    MemoryType,
    AttentionManager,
    MemoryManager,
    MetacognitionMonitor
)


class TestAttentionLevel:
    """测试注意力级别枚举"""

    def test_attention_level_values(self):
        """测试注意力级别值"""
        assert AttentionLevel.CRITICAL.value == "critical"
        assert AttentionLevel.HIGH.value == "high"
        assert AttentionLevel.MEDIUM.value == "medium"
        assert AttentionLevel.LOW.value == "low"
        assert AttentionLevel.IDLE.value == "idle"


class TestMemoryType:
    """测试记忆类型枚举"""

    def test_memory_type_values(self):
        """测试记忆类型值"""
        assert MemoryType.SHORT_TERM.value == "short_term"
        assert MemoryType.WORKING.value == "working"
        assert MemoryType.LONG_TERM.value == "long_term"


class TestCognitiveState:
    """测试认知状态"""

    def test_create_cognitive_state(self):
        """测试创建认知状态"""
        state = CognitiveState(
            attention=AttentionLevel.HIGH,
            memory_load=0.7,
            learning_rate=0.8,
            context={"key": "value"},
            metadata={"meta": "data"}
        )
        assert state.attention == AttentionLevel.HIGH
        assert state.memory_load == 0.7
        assert state.learning_rate == 0.8
        assert state.context == {"key": "value"}
        assert state.metadata == {"meta": "data"}

    def test_cognitive_state_defaults(self):
        """测试认知状态默认值"""
        state = CognitiveState()
        assert state.attention == AttentionLevel.MEDIUM
        assert state.memory_load == 0.5
        assert state.learning_rate == 0.5
        assert state.context == {}
        assert state.metadata == {}

    def test_cognitive_state_to_dict(self):
        """测试认知状态转换为字典"""
        state = CognitiveState(
            attention=AttentionLevel.HIGH,
            memory_load=0.6
        )
        data = state.to_dict()
        assert data['attention'] == "high"
        assert data['memory_load'] == 0.6
        assert 'context' in data
        assert 'metadata' in data

    def test_cognitive_state_from_dict(self):
        """测试从字典创建认知状态"""
        data = {
            'attention': 'critical',
            'memory_load': 0.9,
            'learning_rate': 0.7,
            'context': {'test': 'value'},
            'metadata': {}
        }
        state = CognitiveState.from_dict(data)
        assert state.attention == AttentionLevel.CRITICAL
        assert state.memory_load == 0.9
        assert state.learning_rate == 0.7


class TestCognitiveCycleResult:
    """测试认知循环结果"""

    def test_create_cycle_result(self):
        """测试创建认知循环结果"""
        result = CognitiveCycleResult(
            success=True,
            observation={"query": "test"},
            execution_time=1.5
        )
        assert result.success is True
        assert result.observation == {"query": "test"}
        assert result.execution_time == 1.5

    def test_cycle_result_defaults(self):
        """测试认知循环结果默认值"""
        result = CognitiveCycleResult()
        assert result.success is False
        assert result.observation == {}
        assert result.recalled_memories == []
        assert result.decision == {}
        assert result.execution_result == {}
        assert result.reflection == {}
        assert result.consolidation_result == {}
        assert result.execution_time == 0.0


class TestAttentionManager:
    """测试注意力管理器"""

    @pytest.fixture
    def attention_manager(self):
        """创建注意力管理器实例"""
        return AttentionManager()

    def test_init(self, attention_manager):
        """测试初始化"""
        assert attention_manager is not None
        assert attention_manager.get_attention() == AttentionLevel.MEDIUM

    def test_get_attention(self, attention_manager):
        """测试获取注意力级别"""
        level = attention_manager.get_attention()
        assert level == AttentionLevel.MEDIUM

    def test_set_attention(self, attention_manager):
        """测试设置注意力级别"""
        attention_manager.set_attention(AttentionLevel.HIGH, "Test reason")
        assert attention_manager.get_attention() == AttentionLevel.HIGH

    def test_attention_switch_history(self, attention_manager):
        """测试注意力切换历史"""
        attention_manager.set_attention(AttentionLevel.HIGH, "First switch")
        attention_manager.set_attention(AttentionLevel.CRITICAL, "Second switch")
        
        history = attention_manager._switch_history
        assert len(history) == 2
        assert history[0]['to'] == "high"
        assert history[1]['to'] == "critical"

    def test_should_switch_attention(self, attention_manager):
        """测试判断是否需要切换注意力"""
        assert attention_manager.should_switch_attention(8) is True
        assert attention_manager.should_switch_attention(5) is False
        
        attention_manager.set_attention(AttentionLevel.HIGH)
        assert attention_manager.should_switch_attention(8) is False
        assert attention_manager.should_switch_attention(9) is True


class TestMemoryManager:
    """测试记忆管理器"""

    @pytest.fixture
    def memory_manager(self):
        """创建记忆管理器实例"""
        return MemoryManager(max_short_term=5, max_working=3)

    def test_init(self, memory_manager):
        """测试初始化"""
        assert memory_manager is not None
        assert memory_manager.max_short_term == 5
        assert memory_manager.max_working == 3

    def test_add_memory(self, memory_manager):
        """测试添加记忆"""
        memory_id = memory_manager.add_memory(
            content="Test memory",
            memory_type=MemoryType.SHORT_TERM
        )
        assert memory_id is not None
        assert memory_id.startswith("mem_")

    def test_add_memory_with_metadata(self, memory_manager):
        """测试添加带元数据的记忆"""
        memory_id = memory_manager.add_memory(
            content="Test memory",
            memory_type=MemoryType.WORKING,
            metadata={"key": "value"}
        )
        memory = memory_manager.retrieve_memory(memory_id)
        assert memory is not None
        assert memory['metadata'] == {"key": "value"}

    def test_retrieve_memory(self, memory_manager):
        """测试检索记忆"""
        memory_id = memory_manager.add_memory(
            content="Test memory",
            memory_type=MemoryType.SHORT_TERM
        )
        memory = memory_manager.retrieve_memory(memory_id)
        assert memory is not None
        assert memory['content'] == "Test memory"
        assert memory['access_count'] == 1

    def test_retrieve_nonexistent_memory(self, memory_manager):
        """测试检索不存在的记忆"""
        memory = memory_manager.retrieve_memory("nonexistent")
        assert memory is None

    def test_get_memories_by_type(self, memory_manager):
        """测试按类型获取记忆"""
        memory_manager.add_memory("Memory 1", MemoryType.SHORT_TERM)
        memory_manager.add_memory("Memory 2", MemoryType.SHORT_TERM)
        memory_manager.add_memory("Memory 3", MemoryType.WORKING)
        
        short_term = memory_manager.get_memories_by_type(MemoryType.SHORT_TERM)
        working = memory_manager.get_memories_by_type(MemoryType.WORKING)
        
        assert len(short_term) == 2
        assert len(working) == 1

    def test_clear_memories(self, memory_manager):
        """测试清空记忆"""
        memory_manager.add_memory("Memory 1", MemoryType.SHORT_TERM)
        memory_manager.add_memory("Memory 2", MemoryType.WORKING)
        
        count = memory_manager.clear_memories(MemoryType.SHORT_TERM)
        assert count == 1
        
        short_term = memory_manager.get_memories_by_type(MemoryType.SHORT_TERM)
        working = memory_manager.get_memories_by_type(MemoryType.WORKING)
        
        assert len(short_term) == 0
        assert len(working) == 1

    def test_clear_all_memories(self, memory_manager):
        """测试清空所有记忆"""
        memory_manager.add_memory("Memory 1", MemoryType.SHORT_TERM)
        memory_manager.add_memory("Memory 2", MemoryType.WORKING)
        memory_manager.add_memory("Memory 3", MemoryType.LONG_TERM)
        
        count = memory_manager.clear_memories()
        assert count == 3

    def test_memory_capacity_limit(self, memory_manager):
        """测试记忆容量限制"""
        for i in range(10):
            memory_manager.add_memory(f"Memory {i}", MemoryType.SHORT_TERM)
        
        short_term = memory_manager.get_memories_by_type(MemoryType.SHORT_TERM)
        assert len(short_term) == 5  # max_short_term=5


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
        """测试更新认知状态"""
        orchestrator.update_cognitive_state(
            attention=AttentionLevel.HIGH,
            memory_load=0.8,
            learning_rate=0.6
        )
        state = orchestrator.get_cognitive_state()
        assert state.attention == AttentionLevel.HIGH
        assert state.memory_load == 0.8
        assert state.learning_rate == 0.6

    def test_update_cognitive_state_with_context(self, orchestrator):
        """测试更新认知状态（带上下文）"""
        orchestrator.update_cognitive_state(
            context={"key1": "value1"},
            metadata={"meta1": "data1"}
        )
        orchestrator.update_cognitive_state(
            context={"key2": "value2"},
            metadata={"meta2": "data2"}
        )
        state = orchestrator.get_cognitive_state()
        assert state.context == {"key1": "value1", "key2": "value2"}
        assert state.metadata == {"meta1": "data1", "meta2": "data2"}

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

    def test_process_task(self, orchestrator):
        """测试处理任务"""
        result = orchestrator.process_task("Test task", priority=5)
        assert result is not None
        assert result['success'] is True
        assert 'selected_skills' in result
        assert 'cognitive_state' in result
        assert 'memory_id' in result

    def test_process_high_priority_task(self, orchestrator):
        """测试处理高优先级任务"""
        result = orchestrator.process_task("Critical task", priority=9)
        assert result['success'] is True
        state = orchestrator.get_cognitive_state()
        assert state.attention in [AttentionLevel.HIGH, AttentionLevel.CRITICAL]

    def test_process_thought_cycle(self, orchestrator):
        """测试处理认知循环"""
        input_context = {"query": "Test query"}
        result = orchestrator.process_thought_cycle(input_context)
        
        assert result is not None
        assert isinstance(result, CognitiveCycleResult)
        assert result.success is True
        assert result.observation is not None
        assert result.execution_time > 0

    def test_select_skill_for_task(self, orchestrator):
        """测试为任务选择技能"""
        skills = orchestrator.select_skill_for_task("Test task", top_k=3)
        assert skills is not None
        assert isinstance(skills, list)

    def test_enable_metacognition(self, orchestrator):
        """测试启用元认知监控"""
        orchestrator.enable_metacognition(True)
        assert orchestrator._metacognition_enabled is True
        
        orchestrator.enable_metacognition(False)
        assert orchestrator._metacognition_enabled is False

    def test_get_metacognition_report(self, orchestrator):
        """测试获取元认知报告"""
        report = orchestrator.get_metacognition_report()
        assert report is not None
        assert 'enabled' in report
        assert 'cycle_count' in report
        assert 'success_rate' in report
        assert 'cognitive_state' in report
        assert 'memory_stats' in report

    def test_set_registry(self, orchestrator):
        """测试设置技能注册表"""
        mock_registry = MagicMock()
        orchestrator.set_registry(mock_registry)
        assert orchestrator.get_registry() == mock_registry


class TestMetacognitionMonitor:
    """测试元认知监控器"""

    @pytest.fixture
    def monitor(self):
        """创建元认知监控器实例"""
        return MetacognitionMonitor()

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

    def test_record_cycle(self, monitor):
        """测试记录认知循环"""
        monitor.start_monitoring()
        
        result = CognitiveCycleResult(success=True, execution_time=1.5)
        monitor.record_cycle(result)
        
        report = monitor.get_report()
        assert report['metrics']['total_cycles'] == 1
        assert report['metrics']['successful_cycles'] == 1

    def test_record_failed_cycle(self, monitor):
        """测试记录失败的认知循环"""
        monitor.start_monitoring()
        
        result = CognitiveCycleResult(success=False, execution_time=2.0)
        monitor.record_cycle(result)
        
        report = monitor.get_report()
        assert report['metrics']['total_cycles'] == 1
        assert report['metrics']['failed_cycles'] == 1

    def test_get_report(self, monitor):
        """测试获取监控报告"""
        report = monitor.get_report()
        assert report is not None
        assert 'monitoring' in report
        assert 'metrics' in report
        assert 'alerts_count' in report

    def test_execution_time_anomaly(self, monitor):
        """测试执行时间异常检测"""
        monitor.start_monitoring()
        
        result = CognitiveCycleResult(success=True, execution_time=15.0)
        monitor.record_cycle(result)
        
        report = monitor.get_report()
        assert report['alerts_count'] > 0


class TestEdgeCases:
    """测试边界情况"""

    def test_memory_load_bounds(self):
        """测试记忆负载边界"""
        orchestrator = CognitionOrchestrator()
        
        orchestrator.update_cognitive_state(memory_load=1.5)
        state = orchestrator.get_cognitive_state()
        assert state.memory_load == 1.0
        
        orchestrator.update_cognitive_state(memory_load=-0.5)
        state = orchestrator.get_cognitive_state()
        assert state.memory_load == 0.0

    def test_learning_rate_bounds(self):
        """测试学习率边界"""
        orchestrator = CognitionOrchestrator()
        
        orchestrator.update_cognitive_state(learning_rate=2.0)
        state = orchestrator.get_cognitive_state()
        assert state.learning_rate == 1.0
        
        orchestrator.update_cognitive_state(learning_rate=-1.0)
        state = orchestrator.get_cognitive_state()
        assert state.learning_rate == 0.0

    def test_empty_query(self):
        """测试空查询"""
        orchestrator = CognitionOrchestrator()
        result = orchestrator.process_thought_cycle({"query": ""})
        assert result is not None

    def test_multiple_cycles(self):
        """测试多次认知循环"""
        orchestrator = CognitionOrchestrator()
        
        for i in range(5):
            result = orchestrator.process_thought_cycle({"query": f"Query {i}"})
            assert result.success is True
        
        report = orchestrator.get_metacognition_report()
        assert report['cycle_count'] == 5
