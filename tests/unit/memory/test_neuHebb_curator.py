"""
NeuHebbCurator 单元测试 — TDD 垂直切片 #4

测试 Neurova Hebb 检索和多样性过滤行为。
"""

import math
import pytest
from typing import List

from neurova.cognitive_layers.memory_layer.neurova_hebb import (
    NeurovaHebb,
    NeuHebbConfig,
    NeuHebbMem,
)
from neurova.cognitive_layers.memory_layer.neuHebb_curator import NeuHebbCurator


# ── 辅助 ──────────────────────────────────────────────────────────────────────

class MockEmbedder:
    def __init__(self, dim: int = 64):
        self.dim = dim

    def __call__(self, text: str) -> List[float]:
        import random
        rng = random.Random(hash(text))
        vec = [rng.random() for _ in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm > 0 else vec


def _make_hebb(content: str, **overrides) -> NeurovaHebb:
    defaults = dict(content=content, document_id="doc_001")
    defaults.update(overrides)
    return NeurovaHebb(**defaults)


@pytest.fixture
def config():
    return NeuHebbConfig(
        top_k=3,
        diversity_threshold=0.85,
        max_neurova_hebbs_per_query=5,
        persistence_path=":memory:",  # 内存模式
    )


@pytest.fixture
def curator(config, tmp_path):
    """使用 mock embedding 的 curator。"""
    config.persistence_path = str(tmp_path / "curator_test")
    embedder = MockEmbedder()
    return NeuHebbCurator(config=config, embed_fn=embedder), embedder


@pytest.fixture
def curator_with_data(config, tmp_path):
    """预装数据的 curator。"""
    config.persistence_path = str(tmp_path / "curator_data")
    embedder = MockEmbedder()
    mem = NeuHebbMem(config)
    c = NeuHebbCurator(config=config, embed_fn=embedder, storage=mem)

    # 存入几条 NeurovaHebb
    hebbs = [
        _make_hebb("Python uses reference counting"),
        _make_hebb("Garbage collection detects cycles"),
        _make_hebb("Memory pools reduce allocation overhead"),
    ]
    for h in hebbs:
        h.embedding = embedder(h.content)
    mem.store("doc_001", hebbs)
    return c, embedder, mem


# ── 查询嵌入 ──────────────────────────────────────────────────────────────────

class TestQueryEmbedding:
    def test_returns_vector(self, curator):
        """get_query_embedding 返回向量。"""
        c, _ = curator
        vec = c.get_query_embedding("How does Python manage memory?")
        assert isinstance(vec, list)
        assert len(vec) > 0
        assert all(isinstance(x, float) for x in vec)


# ── 检索 ──────────────────────────────────────────────────────────────────────

class TestRetrieve:
    def test_retrieve_returns_list(self, curator_with_data):
        """retrieve 返回 NeurovaHebb 列表。"""
        c, embedder, _ = curator_with_data
        query_vec = embedder("How does Python manage memory?")
        results = c.retrieve(query_vec, top_k=3)
        assert isinstance(results, list)
        assert all(isinstance(h, NeurovaHebb) for h in results)

    def test_retrieve_respects_top_k(self, curator_with_data):
        """返回数量不超过 top_k。"""
        c, embedder, _ = curator_with_data
        query_vec = embedder("memory management")
        results = c.retrieve(query_vec, top_k=2)
        assert len(results) <= 2

    def test_retrieve_empty_storage(self, curator):
        """空存储时返回空列表。"""
        c, embedder = curator
        query_vec = embedder("anything")
        results = c.retrieve(query_vec, top_k=5)
        assert results == []


# ── 多样性过滤 ────────────────────────────────────────────────────────────────

class TestDiversityFilter:
    def test_filter_returns_list(self, curator):
        """diversity_filter 返回 NeurovaHebb 列表。"""
        c, embedder = curator
        hebbs = [
            _make_hebb("item A"),
            _make_hebb("item B"),
        ]
        for h in hebbs:
            h.embedding = embedder(h.content)
        filtered = c.diversity_filter(hebbs)
        assert isinstance(filtered, list)
        assert len(filtered) <= len(hebbs)

    def test_filter_preserves_unique(self, curator):
        """完全不同的内容全部保留。"""
        c, embedder = curator
        hebbs = [
            _make_hebb("quantum physics basics"),
            _make_hebb("neural network training"),
            _make_hebb("classical music composition"),
        ]
        for h in hebbs:
            h.embedding = embedder(h.content)
        filtered = c.diversity_filter(hebbs)
        assert len(filtered) == 3

    def test_filter_deduplicates_similar(self):
        """高度相似的内容被过滤。"""
        config = NeuHebbConfig(diversity_threshold=0.5, top_k=5)

        # 两个完全相同内容的 embedding
        same_vec = [1.0] + [0.0] * 63

        def mock_embed(text: str) -> List[float]:
            return same_vec  # 所有文本返回相同向量

        c = NeuHebbCurator(config=config, embed_fn=mock_embed)
        hebbs = [
            _make_hebb("same content A"),
            _make_hebb("same content B"),
        ]
        for h in hebbs:
            h.embedding = mock_embed(h.content)

        filtered = c.diversity_filter(hebbs)
        # 第二个因太相似应被过滤
        assert len(filtered) == 1

    def test_filter_empty_list(self, curator):
        """空列表返回空列表。"""
        c, _ = curator
        assert c.diversity_filter([]) == []
