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


class TestRetrieveTreatsInputAsSubstring:
    """L1 检索把用户输入当**子串**，不是 LIKE 通配模式（004 的同契约命中点）。

    根因：`retrieve` 的 LIKE 兜底各自拼 `f"%{query}%"`，而 `%` `_` 是 LIKE 元字符。
    实测（改前）：库内 2 行时查询 `%` 命中 **2 行**（真值 1 行——只有那一行真的含 `%`）。
    转义判据只此一份（`core.sql_like.likePattern`），不在这里另写一份。
    """

    def _engine(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine, UnifiedMemoryNode,
        )

        engine = CognitiveStorageEngine(agent_id="test", data_dir=str(tmp_path / "cse"))
        engine.store(UnifiedMemoryNode(content="含百分号 100% 的记录"))
        engine.store(UnifiedMemoryNode(content="带下划线 a_b 的记录"))
        engine.store(UnifiedMemoryNode(content="普通记录"))
        engine._flush_l0_to_l1()
        engine._l0_buffer.clear()  # 只走 L1（L0 走的是 Python 子串判定，不经 SQL）
        return engine

    def test_percentDoesNotActAsWildcard(self, tmp_path):
        """`%` 走 LIKE 兜底（FTS 对 `%` 直接语法报错），转义后只命中真含 `%` 的行。"""
        engine = self._engine(tmp_path)
        hits = [n.content for n in engine.retrieve("%", limit=10)]
        assert hits == ["含百分号 100% 的记录"], f"`%` 被当成通配模式：{hits}"

    def test_mixedMetacharQueryStaysSubstring(self, tmp_path):
        """`100%` 同样走兜底：只命中真含 `100%` 的行，不漏也不越权。"""
        engine = self._engine(tmp_path)
        hits = [n.content for n in engine.retrieve("100%", limit=10)]
        assert hits == ["含百分号 100% 的记录"], f"`100%` 子串语义失效：{hits}"
