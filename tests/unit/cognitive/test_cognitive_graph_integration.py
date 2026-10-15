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

from tests.cognitive_body_store import cognitiveEngine


# ═══════════════════════════════════════════════════════════════════════════════
# D10: 集成测试 — 全链路协同
# ═══════════════════════════════════════════════════════════════════════════════

class TestCognitiveGraphFullStack:
    """认知图谱全栈集成：Engine → Crystallizer → Retriever → ReasoningTrace"""

    def test_store_observe_crystallize_retrieve_flow(self, tmp_path):
        """完整流程：存储 → 观察 → 结晶 → 检索"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            UnifiedMemoryNode, MemoryType,
        )
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever

        engine = cognitiveEngine(tmp_path)
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

    def test_reasoning_trace_is_stored_but_never_enters_context(self, tmp_path, monkeypatch):
        """改判（§6-207，用户裁定乙前半）：原格名「存储后可检索」，后半句正是 2026-09-05
        回声污染的读侧成因——寒暄推理链被当相关记忆捞回上下文。现契约拆成两半各自钉：
        **存得下**（治理面开时正文库真有一行），**永不进上下文**（检索面取不到它）。
        """
        monkeypatch.setenv("NEUROVA_TRACE_PERSIST", "1")
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
        from tests.cognitive_body_store import bodyManager

        manager = bodyManager(tmp_path)
        engine = cognitiveEngine(tmp_path, manager=manager)
        trace_mgr = ReasoningTraceManager(engine=engine)
        retriever = UnifiedRetriever(engine=engine)

        # 创建推理链并 flush 进正文库
        trace_id = trace_mgr.start_trace("什么是深度学习？")
        trace_mgr.add_step(trace_id, "retrieve", "搜索深度学习", "找到相关记忆")
        trace_mgr.finish_trace(trace_id, "深度学习是机器学习的子领域", total_tokens=200)
        engine.close()

        echo = [m for m in manager.iterBodyMemories(limit=500)
                if (m.metadata or {}).get("cse_category") == "reasoning_trace"]
        assert len(echo) == 1, "门开着却没存下推理链——写侧契约也漂了"

        # 对照格：同一次查询里普通正文行照常返回，证"取不到"是过滤而非检索坏了
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode
        engine.store(UnifiedMemoryNode(content="深度学习属于机器学习的子领域"))
        engine.close()

        results = asyncio.run(retriever.retrieve("深度学习", limit=10))
        assert all(r.get("category") != "reasoning_trace" for r in results), (
            "推理链回声行又进上下文了（§6-207 的过滤器被绕过）")
        assert any("深度学习" in (r.get("content") or "") and r.get("category") != "reasoning_trace"
                   for r in results), "普通正文行也取不到了＝过滤器成了总闸或检索本身坏了"

    def test_temperature_unified_0_to_100(self, tmp_path):
        """温度系统统一为 0-100 范围"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            UnifiedMemoryNode,
        )
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine

        engine = cognitiveEngine(tmp_path)

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
            UnifiedMemoryNode, MemoryType,
        )
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

        engine = cognitiveEngine(tmp_path)

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
            UnifiedMemoryNode,
        )

        # 第一次启动：存储数据
        engine1 = cognitiveEngine(tmp_path)
        for i in range(5):
            engine1.store(UnifiedMemoryNode(content=f"memory {i}", temperature=80.0))
        # 不调用 close()，模拟崩溃

        # 第二次启动：崩溃恢复文件取回（另起一份正文库，模拟进程重启）
        engine2 = cognitiveEngine(tmp_path)
        results = engine2.retrieve("memory", limit=10)
        assert len(results) == 5
        # 温度应保持 80.0
        for r in results:
            assert r.temperature == 80.0

    def test_flush_preserves_temperature_values(self, tmp_path):
        """L0 并入正文库后温度值保持不变"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            UnifiedMemoryNode,
        )

        engine = cognitiveEngine(tmp_path)
        # 存储不同温度的节点
        temps = [20.0, 40.0, 60.0, 80.0, 100.0]
        for t in temps:
            engine.store(UnifiedMemoryNode(content=f"temp {t}", temperature=t))

        # 手动 flush
        engine._flushL0ToBody()

        # 从正文库检索
        results = engine.retrieve("temp", limit=10)
        result_temps = sorted([r.temperature for r in results])
        assert result_temps == sorted(temps)


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
            UnifiedMemoryNode, MemoryType,
        )

        engine = cognitiveEngine(tmp_path)
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
            UnifiedMemoryNode,
        )
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever

        engine = cognitiveEngine(tmp_path)
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
            UnifiedMemoryNode,
        )
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

        engine = cognitiveEngine(tmp_path)
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
