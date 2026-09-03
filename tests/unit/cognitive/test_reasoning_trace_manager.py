"""
推理链管理器 — TDD 测试

垂直切片：每个测试验证一个行为，逐步实现。
"""

import pytest
from unittest.mock import MagicMock
from typing import List, Dict, Any


# ── Tracer Bullet 1: ReasoningTraceManager 初始化 ─────────────────────────────

class TestReasoningTraceManagerInit:
    """ReasoningTraceManager 可以正确初始化"""

    def test_init_with_engine(self):
        """提供 CognitiveStorageEngine 时可以初始化"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import (
            ReasoningTraceManager, ReasoningStep, ReasoningTrace,
        )
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        manager = ReasoningTraceManager(engine=engine)
        
        assert manager.engine is engine
        assert isinstance(manager._active_traces, dict)
        assert len(manager._active_traces) == 0


# ── Tracer Bullet 2: start_trace() 开始推理链 ────────────────────────────────

class TestReasoningTraceManagerStartTrace:
    """start_trace() 开始一条推理链"""

    def test_start_trace_returns_trace_id(self):
        """start_trace() 返回 trace_id"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        manager = ReasoningTraceManager(engine=engine)
        
        trace_id = manager.start_trace("什么是机器学习？")
        
        assert trace_id is not None
        assert len(trace_id) > 0

    def test_start_trace_creates_active_trace(self):
        """start_trace() 创建活跃推理链"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        manager = ReasoningTraceManager(engine=engine)
        
        trace_id = manager.start_trace("什么是机器学习？")
        
        assert trace_id in manager._active_traces
        trace = manager._active_traces[trace_id]
        assert trace.trace_id == trace_id
        assert trace.query == "什么是机器学习？"
        assert len(trace.steps) == 0
        assert trace.final_answer == ""


# ── Tracer Bullet 3: add_step() 添加推理步骤 ──────────────────────────────────

class TestReasoningTraceManagerAddStep:
    """add_step() 添加推理步骤"""

    def test_add_step_increases_steps(self):
        """add_step() 增加步骤数量"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        manager = ReasoningTraceManager(engine=engine)
        
        trace_id = manager.start_trace("测试查询")
        manager.add_step(
            trace_id=trace_id,
            action="retrieve",
            input_summary="搜索记忆",
            output_summary="找到3条记忆",
            memory_ids=["id1", "id2", "id3"],
        )
        
        trace = manager._active_traces[trace_id]
        assert len(trace.steps) == 1
        assert trace.steps[0].action == "retrieve"
        assert trace.steps[0].input_summary == "搜索记忆"
        assert trace.steps[0].output_summary == "找到3条记忆"
        assert trace.steps[0].memory_ids == ["id1", "id2", "id3"]

    def test_add_multiple_steps(self):
        """添加多个步骤"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        manager = ReasoningTraceManager(engine=engine)
        
        trace_id = manager.start_trace("测试查询")
        
        manager.add_step(trace_id, "retrieve", "搜索", "找到结果")
        manager.add_step(trace_id, "crystallize", "结晶", "创建模式")
        manager.add_step(trace_id, "llm_call", "调用LLM", "生成回复")
        
        trace = manager._active_traces[trace_id]
        assert len(trace.steps) == 3
        assert trace.steps[0].action == "retrieve"
        assert trace.steps[1].action == "crystallize"
        assert trace.steps[2].action == "llm_call"

    def test_add_step_ignores_invalid_trace_id(self):
        """无效 trace_id 时静默忽略"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        manager = ReasoningTraceManager(engine=engine)
        
        # 不应该抛出异常
        manager.add_step("invalid-id", "retrieve", "输入", "输出")
        assert len(manager._active_traces) == 0


# ── Tracer Bullet 4: finish_trace() 完成推理链 ────────────────────────────────

class TestReasoningTraceManagerFinishTrace:
    """finish_trace() 完成推理链并存储为记忆"""

    def test_finish_trace_stores_memory(self):
        """finish_trace() 将推理链存储为记忆"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode, MemoryType,
        )
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        manager = ReasoningTraceManager(engine=engine)
        
        trace_id = manager.start_trace("什么是机器学习？")
        manager.add_step(trace_id, "retrieve", "搜索", "找到结果")
        manager.finish_trace(trace_id, "机器学习是人工智能的分支", total_tokens=100)
        
        # 应该调用 engine.store()
        engine.store.assert_called_once()
        
        # 检查存储的节点
        stored_node = engine.store.call_args[0][0]
        assert isinstance(stored_node, UnifiedMemoryNode)
        assert stored_node.memory_type == MemoryType.EPISODIC
        assert stored_node.category == "reasoning_trace"
        assert stored_node.temperature == 100.0
        assert stored_node.trace_id == trace_id
        assert "推理链" in stored_node.content
        assert "机器学习" in stored_node.content

    def test_finish_trace_removes_from_active(self):
        """finish_trace() 从活跃推理链中移除"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        manager = ReasoningTraceManager(engine=engine)
        
        trace_id = manager.start_trace("测试查询")
        assert trace_id in manager._active_traces
        
        manager.finish_trace(trace_id, "回复", total_tokens=50)
        assert trace_id not in manager._active_traces

    def test_finish_trace_ignores_invalid_trace_id(self):
        """无效 trace_id 时静默忽略"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        manager = ReasoningTraceManager(engine=engine)
        
        # 不应该抛出异常
        manager.finish_trace("invalid-id", "回复", total_tokens=50)
        engine.store.assert_not_called()


# ── Tracer Bullet 5: finish_trace() 元数据 ─────────────────────────────────────

class TestReasoningTraceManagerMetadata:
    """finish_trace() 正确设置元数据"""

    def test_finish_trace_metadata(self):
        """finish_trace() 设置正确的元数据"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        manager = ReasoningTraceManager(engine=engine)
        
        trace_id = manager.start_trace("测试查询")
        manager.add_step(trace_id, "retrieve", "搜索", "找到结果", memory_ids=["m1", "m2"])
        manager.add_step(trace_id, "llm_call", "调用", "生成", memory_ids=["m3"])
        manager.finish_trace(trace_id, "最终回复", total_tokens=150)
        
        stored_node = engine.store.call_args[0][0]
        
        assert stored_node.metadata['steps_count'] == 2
        assert stored_node.metadata['actions'] == ["retrieve", "llm_call"]
        assert stored_node.metadata['memory_ids'] == ["m1", "m2", "m3"]
        assert stored_node.metadata['total_tokens'] == 150


# ── Tracer Bullet 6: get_recent_traces() 获取最近推理链 ────────────────────────

class TestReasoningTraceManagerGetRecent:
    """get_recent_traces() 获取最近的推理链"""

    def test_get_recent_traces_returns_list(self):
        """get_recent_traces() 返回列表"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        engine.retrieve.return_value = []
        
        manager = ReasoningTraceManager(engine=engine)
        result = manager.get_recent_traces()
        
        assert isinstance(result, list)

    def test_get_recent_traces_calls_engine(self):
        """get_recent_traces() 调用引擎检索"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode, MemoryType,
        )
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        mock_node = MagicMock()
        mock_node.trace_id = "trace-1"
        mock_node.content = "推理链: 查询 → 回复"
        mock_node.metadata = {'steps_count': 2}
        mock_node.created_at.isoformat.return_value = "2026-06-04T12:00:00"
        engine.retrieve.return_value = [mock_node]
        
        manager = ReasoningTraceManager(engine=engine)
        result = manager.get_recent_traces(limit=5)
        
        engine.retrieve.assert_called_once_with(
            "",
            limit=5,
            filters={'category': 'reasoning_trace'},
        )
        
        assert len(result) == 1
        assert result[0]['trace_id'] == "trace-1"
        assert result[0]['steps_count'] == 2


# ── Tracer Bullet 7: ReasoningStep 数据类 ─────────────────────────────────────

class TestReasoningStepDataclass:
    """ReasoningStep 数据类正确创建"""

    def test_create_reasoning_step(self):
        """ReasoningStep 可以正确创建"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningStep
        
        step = ReasoningStep(
            step_id="step-1",
            action="retrieve",
            input_summary="搜索记忆",
            output_summary="找到3条",
            memory_ids=["m1", "m2"],
        )
        
        assert step.step_id == "step-1"
        assert step.action == "retrieve"
        assert step.input_summary == "搜索记忆"
        assert step.output_summary == "找到3条"
        assert step.memory_ids == ["m1", "m2"]

    def test_reasoning_step_has_timestamp(self):
        """ReasoningStep 有默认时间戳"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningStep
        from datetime import datetime, timezone
        
        step = ReasoningStep(
            step_id="step-1",
            action="retrieve",
            input_summary="输入",
            output_summary="输出",
        )
        
        assert step.timestamp is not None
        assert isinstance(step.timestamp, datetime)


# ── Tracer Bullet 8: 完整流程 ─────────────────────────────────────────────────

class TestReasoningTraceManagerFullFlow:
    """ReasoningTraceManager 完整流程测试"""

    def test_full_trace_flow(self):
        """完整的推理链流程：开始 → 添加步骤 → 完成 → 检索"""
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode, MemoryType,
        )
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        
        # 模拟存储和检索
        stored_nodes = []
        def mock_store(node):
            stored_nodes.append(node)
            return node.id
        
        engine.store.side_effect = mock_store
        
        def mock_retrieve(query, limit=10, filters=None):
            if filters and filters.get('category') == 'reasoning_trace':
                return stored_nodes[:limit]
            return []
        
        engine.retrieve.side_effect = mock_retrieve
        
        manager = ReasoningTraceManager(engine=engine)
        
        # 步骤1: 开始推理链
        trace_id = manager.start_trace("如何优化数据库查询？")
        
        # 步骤2: 添加多个步骤
        manager.add_step(
            trace_id, "retrieve",
            "搜索优化经验", "找到5条相关记忆",
            memory_ids=["m1", "m2", "m3"],
        )
        manager.add_step(
            trace_id, "crystallize",
            "结晶模式", "发现索引优化模式",
            memory_ids=["m4"],
        )
        manager.add_step(
            trace_id, "llm_call",
            "生成优化建议", "建议添加索引",
            memory_ids=[],
        )
        
        # 步骤3: 完成推理链
        manager.finish_trace(
            trace_id,
            "建议为查询字段添加索引以优化性能",
            total_tokens=250,
        )
        
        # 步骤4: 验证存储
        assert len(stored_nodes) == 1
        node = stored_nodes[0]
        assert node.memory_type == MemoryType.EPISODIC
        assert node.category == "reasoning_trace"
        assert node.metadata['steps_count'] == 3
        assert node.metadata['total_tokens'] == 250
        assert len(node.metadata['memory_ids']) == 4
        
        # 步骤5: 检索最近推理链
        results = manager.get_recent_traces(limit=10)
        assert len(results) == 1
        assert results[0]['trace_id'] == trace_id