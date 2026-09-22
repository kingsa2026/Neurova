# -*- coding: utf-8 -*-
"""B6-6：向量层批量编码入口 + 稳定形态进内容寻址缓存（Issue #90 · B5 尾巴一）。

红灯依据（改前实测，Issue #90 台账 §15「仍未做」）：

- `UnifiedVectorStore` **没有** `encode_batch`：`semantic_drawer.ScoringContext.build`
  的 `hasattr(store, "encode_batch")` 分支恒假，"批量打分"在 store 这一层未接上；
- tfidf 形态一律不入内容寻址缓存：同一批文本跨轮重复真编码（实测 draw1/draw2 各 301 次）。

契约（修复后）：

1. `UnifiedVectorStore.encode_batch(texts)` 是**唯一**批量入口，返回与输入等长的向量列表；
2. 批量入口与 `encode` 共用同一份缓存与编码逻辑（`encode` 由批量入口派生，不是第二份实现）；
3. tfidf 的**稳定形态**（词表为空 → 定维哈希编码）参与缓存：同文本跨轮真编码次数降为 0；
4. 词表一旦被 IDF 填充，向量随语料漂移 → 指纹变化 → 旧缓存不得被当命中（不投毒）。
"""

from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer import unified_vector_store as uvs
from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.semantic_drawer import SemanticMatchDrawer


class BatchEncoder:
    """真契约替身：具备单条与批量两个入口，并分别计数（非 MagicMock）。"""

    def __init__(self, model_name: str = "batch-model", dim: int = 8):
        self.model_name = model_name
        self.is_initialized = True
        self._dim = dim
        self.single_calls: list = []
        self.batch_calls: list = []

    def _vector(self, text: str):
        return [float(len(text) % 7) + i * 0.01 for i in range(self._dim)]

    def encode(self, text: str):
        self.single_calls.append(text)
        return self._vector(text)

    def encode_batch(self, texts):
        self.batch_calls.append(list(texts))
        return [self._vector(t) for t in texts]


@pytest.fixture
def cache_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_EMBEDDING_CACHE", str(tmp_path / "embedding_cache.json"))
    uvs.reset_embedding_cache()
    yield tmp_path / "embedding_cache.json"
    uvs.reset_embedding_cache()


def _countingStore(backend: str = "tfidf"):
    """真 UnifiedVectorStore + **真编码**计数（缓存未命中才会走到这两条路径）。"""
    store = UnifiedVectorStore(backend=backend)
    counter = {"n": 0}

    for name in ("_encode_uncached", "_tfidf_encode"):
        original = getattr(store, name)

        def counting(text, _original=original):
            counter["n"] += 1
            return _original(text)

        setattr(store, name, counting)
    return store, counter


class TestBatchEntry:
    def test_batch_entry_returns_aligned_vectors(self, cache_env):
        """批量入口必须存在，且返回与输入等长的向量列表（顺序对齐）。"""
        store = UnifiedVectorStore(backend="onnx")
        store._encoder = BatchEncoder()

        vectors = store.encode_batch(["甲", "乙丙", "丁戊己"])

        assert len(vectors) == 3
        assert [len(v) for v in vectors] == [8, 8, 8]
        assert vectors[1] == store._encoder._vector("乙丙")

    def test_batch_entry_computes_in_one_encoder_call(self, cache_env):
        """批内文本走编码器的一次批量调用，不退化为逐条调用（这是本票的成本本体）。"""
        store = UnifiedVectorStore(backend="onnx")
        store._encoder = BatchEncoder()

        store.encode_batch(["甲", "乙", "丙"])

        assert len(store._encoder.batch_calls) == 1, "批量入口未走编码器的批量 API"
        assert store._encoder.single_calls == []

    def test_empty_input_returns_empty(self, cache_env):
        store = UnifiedVectorStore(backend="tfidf")
        assert store.encode_batch([]) == []

    def test_single_encode_derives_from_batch_entry(self, cache_env):
        """`encode` 不得是第二份实现：它必须经批量入口派生（同缓存、同编码口径）。"""
        store = UnifiedVectorStore(backend="onnx")
        store._encoder = BatchEncoder()

        single = store.encode("同一文本")
        batch = store.encode_batch(["同一文本"])[0]

        # 缓存按 base64(float32) 存（既定事实源），命中与首次计算在 float32 精度内一致
        assert single == pytest.approx(batch, rel=1e-6)


class TestTfidfStableShapeCaching:
    def test_same_text_across_rounds_encodes_once(self, cache_env):
        """tfidf 稳定形态（词表为空）跨轮真编码次数为 0（改前两轮各 100 次）。"""
        store, counter = _countingStore()
        texts = [f"归档条目 {i}：固件升级失败回滚" for i in range(50)]

        counter["n"] = 0
        first = store.encode_batch(texts)
        first_calls = counter["n"]

        counter["n"] = 0
        second = store.encode_batch(texts)
        second_calls = counter["n"]

        assert first_calls == 50, f"首轮真编码 {first_calls} 次（应为逐条 50 次）"
        assert second_calls == 0, f"第二轮真编码 {second_calls} 次（稳定形态应全部命中缓存）"
        assert [v for vec in first for v in vec] == pytest.approx(
            [v for vec in second for v in vec], rel=1e-6
        )

    def test_vocabulary_drift_invalidates_cached_vectors(self, cache_env):
        """词表被 IDF 填充后向量随语料漂移：旧缓存不得被当命中（防投毒）。"""
        store, counter = _countingStore()
        text = "固件升级失败回滚"

        counter["n"] = 0
        hashShape = store.encode(text)
        assert counter["n"] == 1

        # 语料进入：词表/IDF 变化 → 编码形态从"定维哈希"变为"IDF 加权"
        store._update_idf(["固件升级失败回滚", "另一条完全不同的语料文本"])
        counter["n"] = 0
        afterDrift = store.encode(text)

        assert counter["n"] == 1, "词表漂移后仍命中旧缓存 → 维度/权重不一致的向量被复用"
        assert len(afterDrift) != len(hashShape) or afterDrift != hashShape


class TestDrawerUsesBatchEntry:
    def test_drawer_batches_candidate_encoding(self, cache_env):
        """抽屉批量打分必须走 store 的批量入口（改前 hasattr 恒假 → 逐条 encode）。"""

        class BatchStore:
            def __init__(self):
                self.batch_calls = 0
                self.single_calls = 0

            def encode(self, text):
                self.single_calls += 1
                return [float(len(text)), 1.0]

            def encode_batch(self, texts):
                self.batch_calls += 1
                return [[float(len(t)), 1.0] for t in texts]

        drops = [
            ContextInput(source=ContextSource.MEMORY, content=f"条目 {i}", priority=60, tokens=5)
            for i in range(20)
        ]
        drawer = SemanticMatchDrawer(max_tokens=100000)
        store = BatchStore()
        drawer._vector_store = store

        drawer.draw(drops, need="条目 3")

        assert store.batch_calls == 1, "候选未走批量入口"
        assert store.single_calls == 1, "need 应只编码一次（且经单条入口）"


class TestCacheNamespaces:
    """同一进程可能同时存在 tfidf（知识库分片）与真模型后端（记忆/上下文）。

    两类向量的指纹不同：共用一个"指纹不匹配即整体失效"的文件会让两边互相
    清空（每轮都重算）。缓存文件必须按指纹**分命名空间**共存，且旧格式
    （顶层 `fingerprint`/`entries`）仍能读出——不静默丢弃既有缓存。
    """

    def test_two_fingerprints_coexist_in_one_file(self, cache_env):
        modelStore = UnifiedVectorStore(backend="onnx")
        modelStore._encoder = BatchEncoder(model_name="m-a")
        modelStore.encode_batch(["模型侧文本"])

        tfidfStore = UnifiedVectorStore(backend="tfidf")
        tfidfStore.encode_batch(["tfidf 侧文本"])

        uvs.flush_embedding_cache()
        import json

        raw = json.loads(cache_env.read_text(encoding="utf-8"))
        namespaces = raw.get("namespaces") or {}
        modelKeys = [k for k in namespaces if k.startswith("onnx:m-a")]
        tfidfKeys = [k for k in namespaces if k.startswith("tfidf")]
        assert modelKeys and tfidfKeys, f"两个指纹未共存，实际命名空间：{sorted(namespaces)}"
        assert len(namespaces[modelKeys[0]]) == 1
        assert len(namespaces[tfidfKeys[0]]) == 1

    def test_legacy_single_fingerprint_file_still_readable(self, cache_env):
        """旧格式（顶层 fingerprint/entries）必须能读回，不因升级整体丢弃。"""
        import base64
        import json
        from array import array

        legacyVec = [1.0, 2.0, 3.0]
        encoded = base64.b64encode(array("f", legacyVec).tobytes()).decode("ascii")
        import hashlib

        key = hashlib.sha256("旧文本".encode("utf-8")).hexdigest()
        cache_env.write_text(
            json.dumps({"fingerprint": "onnx:m-a", "entries": {key: encoded}}),
            encoding="utf-8",
        )
        uvs.reset_embedding_cache()

        store = UnifiedVectorStore(backend="onnx")
        store._encoder = BatchEncoder(model_name="m-a")
        vector = store.encode_batch(["旧文本"])[0]

        assert not store._encoder.batch_calls, "旧格式缓存未被读回（文本被重新编码）"
        assert vector == pytest.approx(legacyVec, rel=1e-5)
