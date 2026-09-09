"""
嵌入缓存（UnifiedVectorStore 落盘持久化）测试

背景（启动性能 2026-09-09）：init_moe_router 初始索引对 199 条记忆逐条
encode，实测 10.7s，且每次启动全量重算（嵌入结果不落盘）。根因修复：
UnifiedVectorStore 增加进程级内容寻址嵌入缓存——同文本同模型只编码一次，
落盘持久化，重启后直接命中。

缓存纪律：
- 仅真实模型后端（onnx/faiss/fastembed）且 encoder 已初始化时参与；
  tfidf 词汇表漂移、以及 onnx 未初始化时的 tfidf 降级路径一律不缓存
  （否则会把维度漂移的 tfidf 向量毒进缓存）。
- 模型指纹（backend:model_name）不匹配 → 整体失效重编。
"""
import base64
import json
from pathlib import Path

import pytest

from neurova.cognitive_layers.memory_layer import unified_vector_store as uvs
from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore


class FakeEncoder:
    """计数编码器：确定性向量 + 可切换指纹/初始化态"""

    def __init__(self, model_name: str = "test-model", dim: int = 8):
        self.model_name = model_name
        self.is_initialized = True
        self._dim = dim
        self.calls: list = []

    def encode(self, text: str):
        self.calls.append(text)
        # 确定性：按文本长度生成可辨识向量
        base = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8][: self._dim]
        return [base[i % self._dim] + len(text) * 0.01 * (i + 1) for i in range(self._dim)]

    async def initialize(self):
        """异步契约保持（引擎兼容旧调用方）"""
        return self.initialize_sync()

    def initialize_sync(self):
        """模拟初始化失败（不置 is_initialized）→ _encode_uncached 走 tfidf 降级"""
        return False


def _make_memories(n: int = 3):
    return [
        {"id": f"m{i}", "content": f"内容-{i}", "metadata": {"category": "knowledge"}}
        for i in range(n)
    ]


@pytest.fixture
def cache_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_EMBEDDING_CACHE", str(tmp_path / "embedding_cache.json"))
    uvs.reset_embedding_cache()
    yield tmp_path / "embedding_cache.json"
    uvs.reset_embedding_cache()


def _make_store(model_name: str = "test-model", dim: int = 8) -> UnifiedVectorStore:
    store = UnifiedVectorStore(backend="onnx")
    store._encoder = FakeEncoder(model_name=model_name, dim=dim)
    return store


class TestEmbeddingCache:
    def test_first_index_encodes_and_persists(self, cache_env):
        store = _make_store()
        store.index_memories(_make_memories(3))

        assert len(store._encoder.calls) == 3  # 首次全量编码
        assert cache_env.exists()
        data = json.loads(cache_env.read_text(encoding="utf-8"))
        assert data["fingerprint"].startswith("onnx:test-model")
        assert len(data["entries"]) == 3

    def test_second_start_hits_cache_zero_encode(self, cache_env):
        """重启后同文本同模型：0 次 encode，向量与首次一致（float32 精度内）"""
        store1 = _make_store()
        store1.index_memories(_make_memories(3))
        vectors_first = list(store1.memory_vectors)

        store2 = _make_store()  # 模拟重启后的新实例
        store2.index_memories(_make_memories(3))

        assert len(store2._encoder.calls) == 0  # 全部命中缓存
        for a, b in zip(vectors_first, store2.memory_vectors):
            assert a == pytest.approx(b, rel=1e-5)
        assert store2.memory_ids == ["m0", "m1", "m2"]

    def test_partial_new_memories_only_encode_missing(self, cache_env):
        store1 = _make_store()
        store1.index_memories(_make_memories(3))

        store2 = _make_store()
        mems = _make_memories(3) + [{"id": "m9", "content": "新内容", "metadata": {}}]
        store2.index_memories(mems)

        assert store2._encoder.calls == ["新内容"]
        assert store2.memory_ids == ["m0", "m1", "m2", "m9"]

    def test_fingerprint_mismatch_invalidates(self, cache_env):
        """换模型 → 缓存整体失效，重新编码"""
        store1 = _make_store(model_name="model-A")
        store1.index_memories(_make_memories(3))

        store2 = _make_store(model_name="model-B")
        store2.index_memories(_make_memories(3))
        assert len(store2._encoder.calls) == 3

    def test_tfidf_backend_never_caches(self, cache_env):
        """tfidf 词汇表漂移，向量不稳定，禁止入缓存"""
        store = UnifiedVectorStore(backend="tfidf")
        store.index_memories(_make_memories(3))
        assert not cache_env.exists()

    def test_uninitialized_encoder_not_cached(self, cache_env):
        """onnx 未初始化时 encode 走 tfidf 降级——该路径向量禁止入缓存"""
        store = _make_store()
        store._encoder.is_initialized = False
        store.index_memories(_make_memories(3))
        assert not cache_env.exists()

    def test_corrupted_cache_file_rebuilds(self, cache_env):
        cache_env.write_text("{broken json!!", encoding="utf-8")
        store = _make_store()
        store.index_memories(_make_memories(3))  # 不得抛异常，全量重编
        assert len(store._encoder.calls) == 3
        assert len(store.memory_ids) == 3

    def test_cache_size_capped(self, cache_env, monkeypatch):
        monkeypatch.setattr(uvs, "_EMBEDDING_CACHE_MAX_ENTRIES", 5)
        store = _make_store()
        store.index_memories(_make_memories(8))
        data = json.loads(cache_env.read_text(encoding="utf-8"))
        assert len(data["entries"]) <= 5

    def test_centroid_encoding_also_benefits(self, cache_env):
        """质心初始化同文本也走缓存（第二次启动 4 个质心 0 编码）"""
        experts = {"e1": {"category": "knowledge", "centroid_text": "事实知识"}}
        store1 = _make_store()
        store1.initialize_centroids(experts)
        assert len(store1._encoder.calls) == 1

        store2 = _make_store()
        store2.initialize_centroids(experts)
        assert len(store2._encoder.calls) == 0
