"""
经验结晶器 — TDD 测试

垂直切片：每个测试验证一个行为，逐步实现。
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import List, Dict, Any
from datetime import datetime, timezone


# ── Tracer Bullet 1: PatternCrystallizer 初始化 ──────────────────────────────

class TestPatternCrystallizerInit:
    """PatternCrystallizer 可以正确初始化"""

    def test_init_with_engine_only(self):
        """只提供 CognitiveStorageEngine 时可以初始化"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        crystallizer = PatternCrystallizer(engine=engine)
        
        assert crystallizer.engine is engine
        assert crystallizer.evolution is None
        assert isinstance(crystallizer._buffer, dict)

    def test_init_with_evolution_orchestrator(self):
        """提供 EvolutionOrchestrator 时可以初始化"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        evolution = MagicMock()
        
        crystallizer = PatternCrystallizer(
            engine=engine,
            evolution_orchestrator=evolution,
        )
        
        assert crystallizer.engine is engine
        assert crystallizer.evolution is evolution


# ── Tracer Bullet 2: observe() 基本功能 ────────────────────────────────────────

class TestPatternCrystallizerObserve:
    """observe() 方法的基本功能"""

    def test_observe_adds_to_buffer(self):
        """observe() 将观察添加到缓冲区"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        crystallizer = PatternCrystallizer(engine=engine)
        
        crystallizer.observe(
            tool_name="file_read",
            context="读取配置文件",
            success=True,
            result="配置内容",
        )
        
        # 应该有一个缓冲区条目
        assert len(crystallizer._buffer) == 1
        # 缓冲区键应该是提取的模式键
        key = crystallizer._extract_pattern_key("读取配置文件")
        assert key in crystallizer._buffer
        assert len(crystallizer._buffer[key]) == 1
        assert crystallizer._buffer[key][0]['tool'] == "file_read"
        assert crystallizer._buffer[key][0]['success'] is True

    def test_observe_accumulates_multiple_entries(self):
        """observe() 累积多个条目（少于3次不触发结晶）"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        crystallizer = PatternCrystallizer(engine=engine)
        
        # 只观察2次相同模式（3次会触发结晶清空缓冲区）
        for i in range(2):
            crystallizer.observe(
                tool_name="file_read",
                context="读取配置文件",
                success=True,
            )
        
        key = crystallizer._extract_pattern_key("读取配置文件")
        assert len(crystallizer._buffer[key]) == 2


# ── Tracer Bullet 3: _extract_pattern_key() 提取模式键 ────────────────────────

class TestPatternCrystallizerExtractKey:
    """_extract_pattern_key() 正确提取模式键"""

    def test_extract_key_returns_string(self):
        """_extract_pattern_key() 返回字符串"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        crystallizer = PatternCrystallizer(engine=engine)
        
        key = crystallizer._extract_pattern_key("这是一个测试上下文")
        assert isinstance(key, str)
        assert len(key) > 0

    def test_extract_key_truncates_long_context(self):
        """_extract_pattern_key() 截断长上下文"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        crystallizer = PatternCrystallizer(engine=engine)
        
        long_context = ("alpha beta gamma delta epsilon zeta eta theta iota kappa "
                        "lambda mu nu xi omicron pi rho sigma tau upsilon phi chi") * 2
        key = crystallizer._extract_pattern_key(long_context)
        # 现行实现按关键词提取（| 分隔，前 8 个关键词），非位置截断——
        # 重复词去重后键长应远小于输入
        assert len(key) < len(long_context)

    def test_extract_key_strips_whitespace(self):
        """_extract_pattern_key() 去除空白"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        crystallizer = PatternCrystallizer(engine=engine)
        
        key = crystallizer._extract_pattern_key("  测试上下文  ")
        assert key == "测试上下文"


# ── Tracer Bullet 4: _try_crystallize() 结晶逻辑 ──────────────────────────────

class TestPatternCrystallizerCrystallize:
    """_try_crystallize() 结晶逻辑"""

    def test_crystallize_when_success_rate_high(self):
        """成功率高时结晶"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine, UnifiedMemoryNode
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        crystallizer = PatternCrystallizer(engine=engine)
        
        # 添加3个成功观察
        key = "test_pattern"
        crystallizer._buffer[key] = [
            {'tool': 'file_read', 'success': True, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
            {'tool': 'file_read', 'success': True, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
            {'tool': 'file_read', 'success': True, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
        ]
        
        crystallizer._try_crystallize(key)
        
        # 应该调用 engine.store()
        engine.store.assert_called_once()
        # 缓冲区应该被清空
        assert key not in crystallizer._buffer

    def test_crystallize_when_success_rate_low(self):
        """成功率低时不结晶"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        crystallizer = PatternCrystallizer(engine=engine)
        
        # 添加3个失败观察
        key = "test_pattern"
        crystallizer._buffer[key] = [
            {'tool': 'file_read', 'success': False, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
            {'tool': 'file_read', 'success': False, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
            {'tool': 'file_read', 'success': False, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
        ]
        
        crystallizer._try_crystallize(key)
        
        # 不应该调用 engine.store()
        engine.store.assert_not_called()
        # 缓冲区应该被清空（无论是否结晶）
        assert key not in crystallizer._buffer

    def test_crystallize_creates_pattern_node(self):
        """结晶创建 PATTERN 类型的记忆节点"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode, MemoryType,
        )
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        crystallizer = PatternCrystallizer(engine=engine)
        
        # 添加3个成功观察
        key = "test_pattern"
        crystallizer._buffer[key] = [
            {'tool': 'file_read', 'success': True, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
            {'tool': 'file_read', 'success': True, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
            {'tool': 'file_read', 'success': True, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
        ]
        
        crystallizer._try_crystallize(key)
        
        # 获取存储的节点
        stored_node = engine.store.call_args[0][0]
        assert isinstance(stored_node, UnifiedMemoryNode)
        assert stored_node.memory_type == MemoryType.PATTERN
        assert stored_node.category == "crystallized"
        assert "模式" in stored_node.content
        assert "file_read" in stored_node.content


# ── Tracer Bullet 5: observe() 触发结晶 ────────────────────────────────────────

class TestPatternCrystallizerObserveTriggers:
    """observe() 在足够观察后触发结晶"""

    def test_observe_triggers_crystallize_after_three(self):
        """3次观察后触发结晶"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        crystallizer = PatternCrystallizer(engine=engine)
        
        # 观察3次
        for i in range(3):
            crystallizer.observe(
                tool_name="file_read",
                context="读取配置文件",
                success=True,
            )
        
        # 应该触发结晶
        engine.store.assert_called_once()
        # 缓冲区应该被清空
        assert len(crystallizer._buffer) == 0

    def test_observe_does_not_trigger_before_three(self):
        """少于3次观察不触发结晶"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        crystallizer = PatternCrystallizer(engine=engine)
        
        # 只观察2次
        for i in range(2):
            crystallizer.observe(
                tool_name="file_read",
                context="读取配置文件",
                success=True,
            )
        
        # 不应该触发结晶
        engine.store.assert_not_called()
        # 缓冲区应该有条目
        assert len(crystallizer._buffer) > 0


# ── Tracer Bullet 6: retrieve() 检索结晶经验 ──────────────────────────────────

class TestPatternCrystallizerRetrieve:
    """retrieve() 检索结晶经验"""

    def test_retrieve_returns_list(self):
        """retrieve() 返回列表"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        engine.retrieve.return_value = []
        
        crystallizer = PatternCrystallizer(engine=engine)
        result = crystallizer.retrieve("test query")
        
        assert isinstance(result, list)

    def test_retrieve_calls_engine_with_pattern_filter(self):
        """retrieve() 调用引擎并过滤 PATTERN 类型"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode, MemoryType,
        )
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        mock_node = MagicMock()
        mock_node.id = "pattern-id"
        mock_node.content = "模式: test_pattern 类任务用 file_read 成功率 100%"
        mock_node.metadata = {
            'primary_tool': 'file_read',
            'success_rate': 1.0,
        }
        mock_node.temperature = 1.0
        engine.retrieve.return_value = [mock_node]
        
        crystallizer = PatternCrystallizer(engine=engine)
        result = crystallizer.retrieve("test query", limit=5)
        
        engine.retrieve.assert_called_once_with(
            "test query",
            limit=5,
            filters={'memory_type': 'pattern'},
        )
        
        assert len(result) == 1
        assert result[0]['id'] == "pattern-id"
        assert result[0]['method'] == "file_read"
        assert result[0]['confidence'] == 1.0
        assert result[0]['source'] == "crystallized"


# ── Tracer Bullet 7: EvolutionOrchestrator 集成 ────────────────────────────────

class TestPatternCrystallizerEvolution:
    """PatternCrystallizer 与 EvolutionOrchestrator 集成"""

    @patch("neurova.evolution.evolution_facade.EvolutionFacade")
    def test_crystallize_calls_evolution(self, MockEvolutionFacade):
        """结晶时调用 EvolutionOrchestrator"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        evolution = MagicMock()
        
        crystallizer = PatternCrystallizer(
            engine=engine,
            evolution_orchestrator=evolution,
        )
        
        # 添加3个成功观察
        key = "test_pattern"
        crystallizer._buffer[key] = [
            {'tool': 'file_read', 'success': True, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
            {'tool': 'file_read', 'success': True, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
            {'tool': 'file_read', 'success': True, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
        ]
        
        crystallizer._try_crystallize(key)
        
        # 生产代码通过 EvolutionFacade.record_experience() 调用
        MockEvolutionFacade.assert_called_once_with(evolution)
        facade_instance = MockEvolutionFacade.return_value
        facade_instance.record_experience.assert_called_once()
        call_args = facade_instance.record_experience.call_args[0]
        assert "模式" in call_args[0]  # content
        assert call_args[1] == key  # pattern_key
        assert call_args[2] == ["file_read"]  # tools
        assert call_args[3] is True  # success

    def test_crystallize_does_not_call_evolution_when_none(self):
        """EvolutionOrchestrator 为 None 时不调用"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        
        engine = MagicMock(spec=CognitiveStorageEngine)
        
        crystallizer = PatternCrystallizer(engine=engine, evolution_orchestrator=None)
        
        # 添加3个成功观察
        key = "test_pattern"
        crystallizer._buffer[key] = [
            {'tool': 'file_read', 'success': True, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
            {'tool': 'file_read', 'success': True, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
            {'tool': 'file_read', 'success': True, 'context': 'test', 'timestamp': datetime.now(timezone.utc).isoformat()},
        ]
        
        # 应该不抛出异常
        crystallizer._try_crystallize(key)
        engine.store.assert_called_once()


# ── Tracer Bullet 8: 完整流程 ─────────────────────────────────────────────────

class TestPatternCrystallizerFullFlow:
    """PatternCrystallizer 完整流程测试"""

    def test_full_observe_crystallize_retrieve_flow(self):
        """完整的观察-结晶-检索流程"""
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
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
            if filters and filters.get('memory_type') == 'pattern':
                return stored_nodes[:limit]
            return []
        
        engine.retrieve.side_effect = mock_retrieve
        
        crystallizer = PatternCrystallizer(engine=engine)
        
        # 步骤1: 观察3次成功使用
        for i in range(3):
            crystallizer.observe(
                tool_name="file_read",
                context="读取配置文件",
                success=True,
            )
        
        # 步骤2: 验证结晶发生
        assert len(stored_nodes) == 1
        assert stored_nodes[0].memory_type == MemoryType.PATTERN
        
        # 步骤3: 检索结晶经验
        results = crystallizer.retrieve("配置文件", limit=5)
        
        assert len(results) == 1
        assert results[0]['method'] == "file_read"
        assert results[0]['confidence'] == 1.0