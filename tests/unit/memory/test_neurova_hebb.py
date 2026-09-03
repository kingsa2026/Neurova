"""
NeuHebbMem 单元测试 — TDD 垂直切片 #1

测试 NeurovaHebb 数据模型和 NeuHebbMem 存储的公开行为。
使用临时目录，不污染真实数据。
"""

import json
import tempfile
import pytest
from pathlib import Path

from neurova.cognitive_layers.memory_layer.neurova_hebb import (
    NeurovaHebb,
    NeuHebbConfig,
    NeuHebbMem,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_config(tmp_path):
    """使用临时目录的配置。"""
    return NeuHebbConfig(
        persistence_path=str(tmp_path / "hebbs"),
        max_neurova_hebbs_per_document=5,
    )


@pytest.fixture
def mem(tmp_config):
    return NeuHebbMem(tmp_config)


def _make_hebb(**overrides) -> NeurovaHebb:
    """快速创建测试用 NeurovaHebb。"""
    defaults = dict(
        content="Python uses reference counting for garbage collection",
        question="How does Python manage memory?",
        answer="Reference counting plus cycle detection",
        source="pre_query",
        document_id="doc_001",
        verification_score=0.92,
    )
    defaults.update(overrides)
    return NeurovaHebb(**defaults)


# ── NeurovaHebb 数据模型 ──────────────────────────────────────────────────────

class TestNeurovaHebbModel:
    def test_default_id_generation(self):
        """每个 NeurovaHebb 自动获得唯一 ID。"""
        a = NeurovaHebb(content="x")
        b = NeurovaHebb(content="y")
        assert a.id != b.id
        assert a.id.startswith("hebb_")

    def test_touch_increments_usage(self):
        """touch() 递增 usage_count 并设置 last_used。"""
        h = _make_hebb()
        assert h.usage_count == 0
        assert h.last_used is None
        h.touch()
        assert h.usage_count == 1
        assert h.last_used is not None

    def test_roundtrip_dict(self):
        """to_dict → from_dict 保持数据一致。"""
        h = _make_hebb(metadata={"k": "v"})
        d = h.to_dict()
        h2 = NeurovaHebb.from_dict(d)
        assert h2.id == h.id
        assert h2.content == h.content
        assert h2.verification_score == h.verification_score
        assert h2.metadata == {"k": "v"}


# ── NeuHebbMem 存储 ──────────────────────────────────────────────────────────

class TestNeuHebbStore:
    """测试存储行为。"""

    def test_store_returns_count(self, mem):
        """store() 返回实际存储数量。"""
        hebbs = [_make_hebb(content=f"item {i}") for i in range(3)]
        stored = mem.store("doc_001", hebbs)
        assert stored == 3

    def test_store_truncates_at_limit(self, mem):
        """超过 per-document 限额时截断。"""
        # 限额是 5
        hebbs = [_make_hebb(content=f"item {i}") for i in range(8)]
        stored = mem.store("doc_001", hebbs)
        assert stored == 5
        assert mem.count("doc_001") == 5

    def test_store_persists_to_disk(self, tmp_config):
        """数据持久化到 JSON 文件，新实例可加载。"""
        mem1 = NeuHebbMem(tmp_config)
        mem1.store("doc_001", [_make_hebb(content="persisted")])

        # 新实例应能加载数据
        mem2 = NeuHebbMem(tmp_config)
        assert mem2.count("doc_001") == 1
        hebbs = mem2.retrieve("doc_001")
        assert hebbs[0].content == "persisted"

    def test_store_updates_metadata(self, mem):
        """存储后元数据中的 total_neurova_hebbs 正确更新。"""
        mem.store("doc_001", [_make_hebb(), _make_hebb()])
        meta = mem.get_metadata("doc_001")
        assert meta is not None
        assert meta["total_neurova_hebbs"] == 2
        assert "created_at" in meta
        assert "updated_at" in meta


class TestNeuHebbRetrieve:
    """测试检索行为。"""

    def test_retrieve_all(self, mem):
        """无 ID 参数时返回文档下所有条目。"""
        mem.store("doc_001", [_make_hebb(content="a"), _make_hebb(content="b")])
        result = mem.retrieve("doc_001")
        assert len(result) == 2
        assert all(isinstance(h, NeurovaHebb) for h in result)

    def test_retrieve_by_ids(self, mem):
        """指定 ID 列表时只返回匹配的条目。"""
        h1 = _make_hebb(content="target")
        h2 = _make_hebb(content="other")
        mem.store("doc_001", [h1, h2])
        result = mem.retrieve("doc_001", [h1.id])
        assert len(result) == 1
        assert result[0].content == "target"

    def test_retrieve_nonexistent_doc(self, mem):
        """检索不存在的文档返回空列表。"""
        assert mem.retrieve("nonexistent") == []

    def test_retrieve_preserves_fields(self, mem):
        """检索结果保留所有字段。"""
        h = _make_hebb(verification_score=0.88, metadata={"tag": "test"})
        mem.store("doc_001", [h])
        result = mem.retrieve("doc_001")
        assert result[0].verification_score == 0.88
        assert result[0].metadata == {"tag": "test"}


class TestNeuHebbDelete:
    """测试删除行为。"""

    def test_delete_specific_ids(self, mem):
        """删除指定 ID 的条目，返回删除数量。"""
        h1 = _make_hebb(content="keep")
        h2 = _make_hebb(content="remove")
        mem.store("doc_001", [h1, h2])
        deleted = mem.delete("doc_001", [h2.id])
        assert deleted == 1
        assert mem.count("doc_001") == 1
        remaining = mem.retrieve("doc_001")
        assert remaining[0].content == "keep"

    def test_delete_entire_document(self, mem):
        """无 ID 参数时删除整个文档。"""
        mem.store("doc_001", [_make_hebb(), _make_hebb()])
        deleted = mem.delete("doc_001")
        assert deleted == 2
        assert mem.count("doc_001") == 0
        assert mem.get_metadata("doc_001") is None

    def test_delete_nonexistent_doc(self, mem):
        """删除不存在的文档返回 0。"""
        assert mem.delete("nonexistent") == 0


class TestNeuHebbCount:
    """测试计数行为。"""

    def test_count_single_doc(self, mem):
        mem.store("doc_001", [_make_hebb(), _make_hebb()])
        assert mem.count("doc_001") == 2

    def test_count_all(self, mem):
        mem.store("doc_001", [_make_hebb()])
        mem.store("doc_002", [_make_hebb(), _make_hebb()])
        assert mem.count() == 3

    def test_count_empty(self, mem):
        assert mem.count() == 0


class TestNeuHebbGetAll:
    """测试 get_all 行为。"""

    def test_get_all_returns_dict(self, mem):
        mem.store("doc_001", [_make_hebb(content="a")])
        mem.store("doc_002", [_make_hebb(content="b")])
        all_hebbs = mem.get_all()
        assert set(all_hebbs.keys()) == {"doc_001", "doc_002"}
        assert len(all_hebbs["doc_001"]) == 1
        assert all_hebbs["doc_001"][0].content == "a"


class TestNeuHebbPersistence:
    """测试文件持久化边界情况。"""

    def test_corrupted_json_file(self, tmp_config):
        """JSON 文件损坏时优雅降级，不抛异常。"""
        storage_dir = Path(tmp_config.persistence_path)
        storage_dir.mkdir(parents=True, exist_ok=True)
        (storage_dir / "neurova_hebbs.json").write_text("NOT VALID JSON", encoding="utf-8")

        mem = NeuHebbMem(tmp_config)
        assert mem.count() == 0  # 应降级为空数据

    def test_empty_storage_directory(self, tmp_config):
        """空目录时初始化为空数据。"""
        mem = NeuHebbMem(tmp_config)
        assert mem.count() == 0
        assert mem.get_all() == {}
