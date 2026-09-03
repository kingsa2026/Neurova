"""
UnifiedVectorStore 扩展测试 — TDD 垂直切片 #2

测试 add_neurova_hebb / search_neurova_hebbs 行为。
使用 "tfidf" 后端避免依赖 faiss/sentence-transformers。
"""

import pytest

from neurova.cognitive_layers.memory_layer.unified_vector_store import (
    UnifiedVectorStore,
    vector_normalize,
)


@pytest.fixture
def store():
    """使用 tfidf 后端的向量存储（零外部依赖）。"""
    return UnifiedVectorStore(backend="tfidf")


def _fake_vec(seed: int, dim: int = 100) -> list:
    """生成确定性伪随机向量用于测试。"""
    import random
    rng = random.Random(seed)
    vec = [rng.random() for _ in range(dim)]
    return vector_normalize(vec)


class TestAddNeurovaHebb:
    def test_add_single(self, store):
        """添加单个 Neurova Hebb 后可搜索到。"""
        vec = _fake_vec(42)
        store.add_neurova_hebb("hebb_001", vec, {"content": "test"})
        assert store.neurova_hebb_count() == 1

    def test_add_multiple(self, store):
        """添加多个 Neurova Hebb。"""
        for i in range(5):
            store.add_neurova_hebb(f"hebb_{i:03d}", _fake_vec(i), {"content": f"item {i}"})
        assert store.neurova_hebb_count() == 5


class TestSearchNeurovaHebbs:
    def test_search_returns_list(self, store):
        """search_neurova_hebbs 返回 (id, score) 元组列表。"""
        vec = _fake_vec(42)
        store.add_neurova_hebb("hebb_001", vec, {"content": "test"})
        results = store.search_neurova_hebbs(vec, top_k=5)
        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0][0] == "hebb_001"
        assert isinstance(results[0][1], float)

    def test_search_empty_index(self, store):
        """空索引时返回空列表。"""
        vec = _fake_vec(42)
        results = store.search_neurova_hebbs(vec, top_k=5)
        assert results == []

    def test_search_top_k_limit(self, store):
        """top_k 限制返回数量。"""
        for i in range(10):
            store.add_neurova_hebb(f"hebb_{i:03d}", _fake_vec(i), {})
        vec = _fake_vec(0)
        results = store.search_neurova_hebbs(vec, top_k=3)
        assert len(results) == 3

    def test_search_relevance_order(self, store):
        """结果按相似度降序排列。"""
        # 添加一个与查询非常相似的向量和一个不相似的
        query_vec = _fake_vec(42)
        similar_vec = _fake_vec(42)  # 同 seed → 同向量
        dissimilar_vec = _fake_vec(99)

        store.add_neurova_hebb("similar", similar_vec, {})
        store.add_neurova_hebb("dissimilar", dissimilar_vec, {})

        results = store.search_neurova_hebbs(query_vec, top_k=2)
        assert results[0][0] == "similar"
        assert results[0][1] > results[1][1]

    def test_search_with_metadata(self, store):
        """元数据正确存储在内部列表中。"""
        vec = _fake_vec(1)
        store.add_neurova_hebb("h1", vec, {"content": "hello", "score": 0.9})
        results = store.search_neurova_hebbs(vec, top_k=1)
        assert results[0][0] == "h1"


class TestRemoveNeurovaHebb:
    def test_remove_existing(self, store):
        """删除存在的条目返回 True。"""
        store.add_neurova_hebb("h1", _fake_vec(1), {})
        assert store.remove_neurova_hebb("h1") is True
        assert store.neurova_hebb_count() == 0

    def test_remove_nonexistent(self, store):
        """删除不存在的条目返回 False。"""
        assert store.remove_neurova_hebb("nonexistent") is False

    def test_remove_preserves_others(self, store):
        """删除一个不影响其他条目。"""
        store.add_neurova_hebb("h1", _fake_vec(1), {})
        store.add_neurova_hebb("h2", _fake_vec(2), {})
        store.remove_neurova_hebb("h1")
        assert store.neurova_hebb_count() == 1
        results = store.search_neurova_hebbs(_fake_vec(2), top_k=5)
        assert len(results) == 1
        assert results[0][0] == "h2"
