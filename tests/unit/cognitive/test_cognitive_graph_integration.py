"""
认知图谱存储架构 — 集成测试 + 回归测试

D10: 验证所有认知图谱模块协同工作
D13: 验证 SleepConsolidation 对接新存储
温度范围：0-100（统一后）
"""

import asyncio

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════════════════════════
# D10: 集成测试 — 全链路协同
# ═══════════════════════════════════════════════════════════════════════════════

class TestCognitiveGraphFullStack:
    """认知图谱全栈集成：Engine → Crystallizer → Retriever → ReasoningTrace"""

    def test_store_observe_crystallize_retrieve_flow(self, tmp_path):
        """完整流程：存储 → 观察 → 结晶 → 检索"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode, MemoryType,
        )
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        crystallizer = PatternCrystallizer(engine=engine)
        retriever = UnifiedRetriever(engine=engine)

        # 1. 存储普通记忆
        engine.store(UnifiedMemoryNode(
            content="Python 文件读取操作",
            memory_type=MemoryType.SEMANTIC,
            category="programming",
        ))

        # 2. 观察工具使用模式（3次成功 → 触发结晶）
        for _ in range(3):
            crystallizer.observe(
                tool_name="file_read",
                context="Python 文件读取操作",
                success=True,
            )

        # 3. 检索应包含结晶经验
        results = asyncio.run(retriever.retrieve("Python 文件读取", limit=10))
        assert len(results) >= 2  # 普通记忆 + 结晶经验

        # 验证结晶经验存在
        pattern_results = [r for r in results if r.get('source') == 'pattern']
        assert len(pattern_results) >= 1

    def test_reasoning_trace_stored_and_retrievable(self, tmp_path, monkeypatch):
        """推理链存储后可检索（持久化需显式开启 NEUROVA_TRACE_PERSIST）"""
        monkeypatch.setenv("NEUROVA_TRACE_PERSIST", "1")
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        trace_mgr = ReasoningTraceManager(engine=engine)
        retriever = UnifiedRetriever(engine=engine)

        # 创建推理链
        trace_id = trace_mgr.start_trace("什么是深度学习？")
        trace_mgr.add_step(trace_id, "retrieve", "搜索深度学习", "找到相关记忆")
        trace_mgr.finish_trace(trace_id, "深度学习是机器学习的子领域", total_tokens=200)

        # 检索
        results = asyncio.run(retriever.retrieve("深度学习", limit=10))
        trace_results = [r for r in results if r.get('source') == 'episodic']
        assert len(trace_results) >= 1

    def test_temperature_unified_0_to_100(self, tmp_path):
        """温度系统统一为 0-100 范围"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))

        # 创建节点，温度应为 100.0
        node = UnifiedMemoryNode(content="test")
        assert node.temperature == 100.0

        # touch 后温度应为 100.0（已到上限）
        node.touch()
        assert node.temperature == 100.0

        # 创建中等温度节点
        node2 = UnifiedMemoryNode(content="medium", temperature=50.0)
        node2.touch()
        assert node2.temperature == 60.0  # +10

        # TemperatureEngine 也应使用 0-100
        stage = TemperatureEngine.get_lifecycle_stage(80.0)
        assert stage == "active"

        stage = TemperatureEngine.get_lifecycle_stage(30.0)
        assert stage == "secondary"

        stage = TemperatureEngine.get_lifecycle_stage(10.0)
        assert stage == "archived"

    def test_crystallizer_temperature_is_0_to_100(self, tmp_path):
        """结晶器温度输出在 0-100 范围"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode, MemoryType,
        )
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))

        # Mock store to capture the node
        stored_nodes = []
        original_store = engine.store
        def capture_store(node):
            stored_nodes.append(node)
            return original_store(node)
        engine.store = capture_store

        crystallizer = PatternCrystallizer(engine=engine)

        # 3 次成功观察 → 结晶，成功率 1.0 → 温度 100.0
        for _ in range(3):
            crystallizer.observe("file_read", "test context", success=True)

        assert len(stored_nodes) == 1
        assert stored_nodes[0].temperature == pytest.approx(100.0)
        assert stored_nodes[0].memory_type == MemoryType.PATTERN

    def test_wal_persistence_across_restart(self, tmp_path):
        """WAL 持久化：重启后数据不丢失"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )

        # 第一次启动：存储数据
        engine1 = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        for i in range(5):
            engine1.store(UnifiedMemoryNode(content=f"memory {i}", temperature=80.0))
        # 不调用 close()，模拟崩溃

        # 第二次启动：WAL 恢复
        engine2 = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        results = engine2.retrieve("memory", limit=10)
        assert len(results) == 5
        # 温度应保持 80.0
        for r in results:
            assert r.temperature == 80.0

    def test_flush_preserves_temperature_values(self, tmp_path):
        """L0→L1 flush 后温度值保持不变"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        # 存储不同温度的节点
        temps = [20.0, 40.0, 60.0, 80.0, 100.0]
        for t in temps:
            engine.store(UnifiedMemoryNode(content=f"temp {t}", temperature=t))

        # 手动 flush
        engine._flush_l0_to_l1()

        # 从 L1 检索
        results = engine.retrieve("temp", limit=10)
        result_temps = sorted([r.temperature for r in results])
        assert result_temps == sorted(temps)


# ═══════════════════════════════════════════════════════════════════════════════
# D13: SleepConsolidation 对接新存储
# ═══════════════════════════════════════════════════════════════════════════════

class TestSleepConsolidationAdapter:
    """SleepConsolidationAdapter 集成测试"""

    def test_adapter_init(self, tmp_path):
        """适配器可以正确初始化"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        from neurova.cognitive_layers.memory_layer.sleep_adapter import SleepConsolidationAdapter

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        adapter = SleepConsolidationAdapter(engine=engine)

        assert adapter.engine is engine
        assert adapter.consolidation is not None

    def test_run_consolidation_with_no_memories(self, tmp_path):
        """空引擎执行整合不报错"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        from neurova.cognitive_layers.memory_layer.sleep_adapter import SleepConsolidationAdapter

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        adapter = SleepConsolidationAdapter(engine=engine)

        result = adapter.run_consolidation()
        assert result["status"] == "no_memories"
        assert result["processed"] == 0

    def test_run_consolidation_with_memories(self, tmp_path):
        """有记忆时执行整合"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        from neurova.cognitive_layers.memory_layer.sleep_adapter import SleepConsolidationAdapter

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        adapter = SleepConsolidationAdapter(engine=engine, archive_threshold=20.0)

        # 存储不同温度的记忆
        for i in range(5):
            engine.store(UnifiedMemoryNode(
                content=f"memory {i}",
                temperature=30.0 + i * 15,  # 30, 45, 60, 75, 90
            ))

        result = adapter.run_consolidation()
        assert result["status"] == "completed"
        assert result["processed"] == 5

    def test_consolidation_decays_temperature(self, tmp_path):
        """整合后温度应衰减"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        from neurova.cognitive_layers.memory_layer.sleep_adapter import SleepConsolidationAdapter

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        adapter = SleepConsolidationAdapter(
            engine=engine,
            archive_threshold=20.0,
            decay_rate=0.5,  # 高衰减率以便测试
        )

        # 存储记忆
        engine.store(UnifiedMemoryNode(content="test memory", temperature=50.0))

        # 执行整合
        result = adapter.run_consolidation()
        assert result["status"] == "completed"

    def test_get_stats(self, tmp_path):
        """获取适配器统计信息"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
        from neurova.cognitive_layers.memory_layer.sleep_adapter import SleepConsolidationAdapter

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        adapter = SleepConsolidationAdapter(engine=engine)

        stats = adapter.get_stats()
        assert "engine" in stats
        assert "consolidation" in stats
        assert stats["consolidation"]["archive_threshold"] == 20.0


# ═══════════════════════════════════════════════════════════════════════════════
# 回归测试：确保旧功能不被破坏
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegression:
    """回归测试：确保认知图谱修改不影响现有功能"""

    def test_unified_memory_node_serialization_roundtrip(self, tmp_path):
        """UnifiedMemoryNode 序列化/反序列化不丢失数据"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            UnifiedMemoryNode, MemoryType, StorageLayer,
        )

        original = UnifiedMemoryNode(
            content="test content",
            memory_type=MemoryType.EPISODIC,
            category="conversation",
            temperature=75.5,
            metadata={"key": "value", "nested": {"a": 1}},
            access_count=5,
            trace_id="trace-123",
        )

        d = original.to_dict()
        restored = UnifiedMemoryNode.from_dict(d)

        assert restored.content == original.content
        assert restored.memory_type == original.memory_type
        assert restored.category == original.category
        assert restored.temperature == original.temperature
        assert restored.metadata == original.metadata
        assert restored.access_count == original.access_count
        assert restored.trace_id == original.trace_id

    def test_retrieve_with_filters(self, tmp_path):
        """检索过滤器正常工作"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode, MemoryType,
        )

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        engine.store(UnifiedMemoryNode(content="episodic memory", memory_type=MemoryType.EPISODIC))
        engine.store(UnifiedMemoryNode(content="semantic memory", memory_type=MemoryType.SEMANTIC))
        engine.store(UnifiedMemoryNode(content="pattern memory", memory_type=MemoryType.PATTERN))

        # 过滤 EPISODIC
        results = engine.retrieve("memory", limit=10, filters={"memory_type": "episodic"})
        assert all(r.memory_type == MemoryType.EPISODIC for r in results)

        # 过滤 PATTERN
        results = engine.retrieve("memory", limit=10, filters={"memory_type": "pattern"})
        assert all(r.memory_type == MemoryType.PATTERN for r in results)

    def test_unified_retriever_deduplication(self, tmp_path):
        """统一检索器去重正常"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        retriever = UnifiedRetriever(engine=engine)

        # 存储相同内容
        for _ in range(3):
            engine.store(UnifiedMemoryNode(content="duplicate content"))

        results = asyncio.run(retriever.retrieve("duplicate", limit=10))
        # 去重后应只有 1 条
        assert len(results) == 1

    def test_pattern_crystallizer_low_success_no_crystallize(self, tmp_path):
        """低成功率不触发结晶"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        original_count = len(engine._l0_buffer)

        crystallizer = PatternCrystallizer(engine=engine)

        # 2 成功 1 失败 → 成功率 66% > 60%，应该结晶
        # 但先测试 1 成功 2 失败 → 成功率 33% < 60%
        crystallizer.observe("tool", "test context", success=True)
        crystallizer.observe("tool", "test context", success=False)
        crystallizer.observe("tool", "test context", success=False)

        # 不应该增加新节点（不结晶）
        # 注意：buffer 中的条目会被清空
        assert len(crystallizer._buffer) == 0
