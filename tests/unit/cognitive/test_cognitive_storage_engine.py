"""
认知图谱存储引擎 — TDD 测试

垂直切片：每个测试验证一个行为，逐步实现。
温度范围：0-100（统一后）。
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone


# ── Tracer Bullet 1: UnifiedMemoryNode 创建 ──────────────────────────────────

class TestUnifiedMemoryNodeCreation:
    """UnifiedMemoryNode 可以创建并有正确的默认值"""

    def test_create_with_defaults(self):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            UnifiedMemoryNode, MemoryType, StorageLayer,
        )
        node = UnifiedMemoryNode()
        assert node.id is not None and len(node.id) > 0
        assert node.content == ""
        assert node.memory_type == MemoryType.SEMANTIC
        assert node.category == "general"
        assert node.temperature == 100.0  # 统一 0-100
        assert node.layer == StorageLayer.L1_HOT
        assert node.metadata == {}
        assert node.embedding is None
        assert node.access_count == 0
        assert node.trace_id is None

    def test_create_with_values(self):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            UnifiedMemoryNode, MemoryType, StorageLayer,
        )
        node = UnifiedMemoryNode(
            content="test memory",
            memory_type=MemoryType.EPISODIC,
            category="conversation",
            temperature=50.0,
            metadata={"key": "value"},
        )
        assert node.content == "test memory"
        assert node.memory_type == MemoryType.EPISODIC
        assert node.category == "conversation"
        assert node.temperature == 50.0
        assert node.metadata == {"key": "value"}


# ── Tracer Bullet 2: touch() ─────────────────────────────────────────────────

class TestUnifiedMemoryNodeTouch:
    """touch() 增加访问计数和温度"""

    def test_touch_increases_access_count(self):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode
        node = UnifiedMemoryNode(temperature=50.0)
        node.touch()
        assert node.access_count == 1
        node.touch()
        assert node.access_count == 2

    def test_touch_increases_temperature(self):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode
        node = UnifiedMemoryNode(temperature=50.0)
        node.touch()
        assert node.temperature == pytest.approx(60.0)  # +10

    def test_touch_caps_temperature_at_100(self):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode
        node = UnifiedMemoryNode(temperature=95.0)
        node.touch()
        assert node.temperature == 100.0


# ── Tracer Bullet 3: decay() ─────────────────────────────────────────────────

class TestUnifiedMemoryNodeDecay:
    """decay() 降低温度"""

    def test_decay_reduces_temperature(self):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode
        node = UnifiedMemoryNode(temperature=50.0)
        node.decay(hours=1.0, rate=1.0)
        assert node.temperature == pytest.approx(49.0)

    def test_decay_floor_at_zero(self):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode
        node = UnifiedMemoryNode(temperature=1.0)
        node.decay(hours=10.0, rate=1.0)
        assert node.temperature == 0.0


# ── Tracer Bullet 4: CognitiveStorageEngine.store() ──────────────────────────

class TestCognitiveStorageEngineStore:
    """store() 写入 L0 缓冲区"""

    def test_store_returns_id(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        node = UnifiedMemoryNode(content="hello")
        result_id = engine.store(node)
        assert result_id == node.id

    def test_store_adds_to_l0_buffer(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        node = UnifiedMemoryNode(content="hello")
        engine.store(node)
        assert len(engine._l0_buffer) == 1
        assert engine._l0_buffer[0].content == "hello"


# ── Tracer Bullet 5: retrieve() from L0 ──────────────────────────────────────

class TestCognitiveStorageEngineRetrieveL0:
    """retrieve() 从 L0 缓冲区检索"""

    def test_retrieve_returns_stored_node(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        node = UnifiedMemoryNode(content="hello world")
        engine.store(node)
        results = engine.retrieve("hello", limit=10)
        assert len(results) == 1
        assert results[0].content == "hello world"

    def test_retrieve_returns_empty_for_no_match(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        node = UnifiedMemoryNode(content="hello world")
        engine.store(node)
        results = engine.retrieve("xyz", limit=10)
        assert len(results) == 0


# ── Tracer Bullet 6: L0 flush to L1 ──────────────────────────────────────────

class TestCognitiveStorageEngineFlush:
    """L0 满时自动 flush 到 L1 SQLite"""

    def test_flush_when_buffer_full(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        # Store 100 nodes to trigger flush
        for i in range(100):
            engine.store(UnifiedMemoryNode(content=f"node {i}"))
        # Buffer should be empty after flush
        assert len(engine._l0_buffer) == 0
        # L1 should have 100 records
        count = engine._db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        assert count == 100


# ── Tracer Bullet 7: retrieve() from L1 ──────────────────────────────────────

class TestCognitiveStorageEngineRetrieveL1:
    """retrieve() 从 L1 SQLite 检索"""

    def test_retrieve_from_l1_after_flush(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        # Store 100+ nodes to trigger flush
        for i in range(105):
            engine.store(UnifiedMemoryNode(content=f"node {i}"))
        # Should find results from L1
        results = engine.retrieve("node", limit=10)
        assert len(results) > 0


# ── Tracer Bullet 8: WAL crash recovery ───────────────────────────────────────

class TestCognitiveStorageEngineWAL:
    """WAL 崩溃恢复"""

    def test_wal_file_created_on_store(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        engine.store(UnifiedMemoryNode(content="hello"))
        wal_path = tmp_path / "wal.jsonl"
        assert wal_path.exists()

    def test_wal_recovery_on_restart(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )
        # First engine: store data
        engine1 = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        engine1.store(UnifiedMemoryNode(content="before crash"))
        # Simulate crash: don't flush, just create new engine
        engine2 = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path))
        # WAL recovery should restore the data
        results = engine2.retrieve("before crash", limit=10)
        assert len(results) == 1
