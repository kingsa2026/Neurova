"""M-08 回归测试：FaissBackend 嵌入模型加载失败时应降级到 TF-IDF，不抛 RuntimeError。

根因：FaissBackend._init_model 在 SentenceTransformer 运行时加载失败（库已装但模型
下载/OOM/路径失败）后仅 warning 并留 self._model=None，_get_embeddings 随即
raise RuntimeError，整个后端在每次 add_texts/search 崩溃，且无 TF-IDF 回落。

本测试在隔离环境内用 fake faiss + fake numpy + 强制 SentenceTransformer 抛错来
确定性复现"模型加载失败"路径，验证降级嵌入可用。

红绿验证：无修复时 _get_embeddings 直接 raise RuntimeError，本文件 3 个用例全红；
修复后（M-08 降级嵌入）全绿。
"""

import math

import pytest

import neurova.cognitive_layers.memory_layer.vector_search_advanced as vsa


class _FakeFaissIndex:
    def __init__(self, dim):
        self.dim = dim
        self._vecs = []

    def add(self, arr):
        # arr: list[list[float]]（fake numpy.array 原样返回）
        for v in arr:
            self._vecs.append(list(v))

    @property
    def ntotal(self):
        return len(self._vecs)

    def search(self, q, k):
        q = q if isinstance(q, list) else list(q)
        scores, indices = [], []
        for qv in q:
            sims = []
            for v in self._vecs:
                dot = sum(a * b for a, b in zip(qv, v))
                nq = math.sqrt(sum(a * a for a in qv)) or 1e-9
                nv = math.sqrt(sum(b * b for b in v)) or 1e-9
                sims.append(dot / (nq * nv))
            order = sorted(range(len(sims)), key=lambda i: -sims[i])[:k]
            scores.append([sims[i] for i in order])
            indices.append(order)
        return scores, indices


class _FakeFaiss:
    # 无 StandardGpuResources → _init_index 跳过 GPU 分支
    IndexFlatIP = staticmethod(lambda dim: _FakeFaissIndex(dim))


class _FakeNumpy:
    float32 = "float32"

    @staticmethod
    def array(data, dtype=None):
        return data


class _FailingSentenceTransformer:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("simulated model load failure")


@pytest.fixture
def patched_faiss(monkeypatch):
    # 进程内伪造 faiss/numpy，使 FaissBackend 可在无真实依赖环境构造并触发降级
    # raising=False：本环境 faiss/np/SentenceTransformer 因导入失败未绑定到模块
    monkeypatch.setattr(vsa, "faiss", _FakeFaiss(), raising=False)
    monkeypatch.setattr(vsa, "np", _FakeNumpy(), raising=False)
    monkeypatch.setattr(vsa, "HAS_FAISS", True)
    monkeypatch.setattr(vsa, "HAS_NUMPY", True)
    monkeypatch.setattr(vsa, "HAS_SENTENCE_TRANSFORMERS", True)
    monkeypatch.setattr(vsa, "SentenceTransformer", _FailingSentenceTransformer, raising=False)
    yield


def test_faiss_backend_degrades_when_model_load_fails(patched_faiss):
    """模型加载失败时 FaissBackend 仍能 add/search，不抛 RuntimeError。"""
    backend = vsa.FaissBackend(dimension=1024)
    # 模型加载失败 → _model 必须为 None（降级前提）
    assert backend._model is None

    n = backend.add_texts(["hello world memory", "foo bar baz"], ["a", "b"])
    assert n == 2

    results = backend.search("hello memory")
    assert results, "降级后 search 应返回结果而非 RuntimeError"
    ids = [r[0] for r in results]
    assert "a" in ids
    # 含 "hello" 的文档应排在含无关词的文档之前
    assert results[0][0] == "a"


def test_fallback_embedding_empty_text(patched_faiss):
    """空文本降级嵌入应为零向量（不抛错）。"""
    backend = vsa.FaissBackend(dimension=64)
    emb = backend._get_embeddings(["   "])
    assert emb == [[0.0] * 64]


def test_fallback_embedding_shape(patched_faiss):
    backend = vsa.FaissBackend(dimension=128)
    emb = backend._get_embeddings(["alpha beta", "gamma"])
    assert len(emb) == 2
    for row in emb:
        assert len(row) == 128
