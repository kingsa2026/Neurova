"""可选 ANN 向量后端：启用、回退与能力读数。"""
from __future__ import annotations

import pytest

from neurova.core import vector_math
from neurova.knowledge.repository import KnowledgeRepository
from neurova.knowledge.vector_ann import (
    DEFAULT_ANN_MIN_RECORDS,
    annMinRecords,
    prepareVectors,
    resolveAnnBackend,
)
from neurova.knowledge.vector_index import KnowledgeVectorIndex

ALICE = {"user_id": "1", "username": "a", "role": "user", "neuser_id": "1"}


class StubEngine:
    VOCAB = ["quantum", "rust", "async", "cookie", "recipe", "travel", "sales", "plan"]

    def encode(self, text):
        lowered = (text or "").lower()
        return [1.0 if word in lowered else 0.0 for word in self.VOCAB]

    def encode_batch(self, texts):
        return [self.encode(text) for text in texts]


class FakeAnnBackend:
    name = "fake-ann"

    def __init__(self):
        self.builds = 0
        self.searches = 0
        self.failBuild = False
        self.failSearch = False

    def build(self, vectors):
        self.builds += 1
        if self.failBuild:
            raise RuntimeError("build boom")
        return {"vectors": vectors}

    def search(self, handle, query, top_k):
        self.searches += 1
        if self.failSearch:
            raise RuntimeError("search boom")
        scored = [
            (kid, vector_math.cosineSimilarity(query, vec))
            for kid, vec in handle["vectors"].items()
        ]
        scored = [pair for pair in scored if pair[1] > 0.0]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]


@pytest.fixture()
def repo(tmp_path):
    knowledge = KnowledgeRepository(str(tmp_path / "kb"))
    knowledge.create_knowledge(
        "a", title="Quantum Guide", content="quantum computing",
        visibility="public", owner_user_id="1",
    )
    knowledge.create_knowledge(
        "a", title="Secret Recipe", content="grandma cookie recipe",
        owner_user_id="1",
    )
    return knowledge


def _index(tmp_path, backend, min_records=0):
    return KnowledgeVectorIndex(
        str(tmp_path / "vec"),
        engine=StubEngine(),
        annBackend=backend,
        annMinRecordCount=min_records,
    )


def test_ann_fast_path_returns_same_ranking(repo, tmp_path):
    backend = FakeAnnBackend()
    index = _index(tmp_path, backend)
    index.ensure_indexed(repo, ALICE)

    hits = index.search("quantum computing basics", ALICE, top_k=3)

    assert backend.searches == 1
    assert hits and hits[0]["title"] == "Quantum Guide"


def test_build_failure_falls_back_and_does_not_retry_same_records(repo, tmp_path):
    backend = FakeAnnBackend()
    backend.failBuild = True
    index = _index(tmp_path, backend)
    index.ensure_indexed(repo, ALICE)

    first = index.search("quantum", ALICE, top_k=3)
    second = index.search("quantum", ALICE, top_k=3)

    assert first and second, "ANN 构建失败必须回退全量余弦，而不是返回空"
    assert backend.builds == 1, "同一份记录不重复重建坏索引"
    assert index.health()["ann"]["failed_users"] == 1


def test_query_failure_falls_back(repo, tmp_path):
    backend = FakeAnnBackend()
    backend.failSearch = True
    index = _index(tmp_path, backend)
    index.ensure_indexed(repo, ALICE)

    hits = index.search("quantum", ALICE, top_k=3)

    assert hits and hits[0]["title"] == "Quantum Guide"
    assert index.health()["ann"]["failed_users"] == 1


def test_records_change_rebuilds_ann(repo, tmp_path):
    backend = FakeAnnBackend()
    index = _index(tmp_path, backend)
    index.ensure_indexed(repo, ALICE)
    index.search("quantum", ALICE, top_k=3)

    repo.create_knowledge(
        "a", title="Rust Async", content="rust async runtime",
        visibility="public", owner_user_id="1",
    )
    index.ensure_indexed(repo, ALICE)
    hits = index.search("rust async", ALICE, top_k=3)

    assert backend.builds == 2, "记录版本变化后必须重建，不能拿旧 ANN 索引回答"
    assert hits and hits[0]["title"] == "Rust Async"


def test_min_records_skips_ann_for_small_corpus(repo, tmp_path):
    backend = FakeAnnBackend()
    index = _index(tmp_path, backend, min_records=100)
    index.ensure_indexed(repo, ALICE)

    hits = index.search("quantum", ALICE, top_k=3)

    assert hits and backend.builds == 0, "低于阈值不建 ANN，走全量余弦"


def test_health_reports_disabled_and_injected_backends(repo, tmp_path):
    disabled = KnowledgeVectorIndex(
        str(tmp_path / "off"), engine=StubEngine(), annBackend=None
    )
    assert disabled.health()["ann"]["enabled"] is False
    assert disabled.health()["ann"]["reason"] == "disabled"

    injected = _index(tmp_path, FakeAnnBackend())
    health = injected.health()["ann"]
    assert health["enabled"] is True
    assert health["backend"] == "fake-ann"


def test_real_hnsw_backend_auto_integration(repo, tmp_path):
    """装了 hnswlib 的环境：哨兵自动探测 → 真索引参与检索，健康读数点名后端。"""
    pytest.importorskip("hnswlib")
    index = KnowledgeVectorIndex(
        str(tmp_path / "vec-real"),
        engine=StubEngine(),
        annMinRecordCount=1,
    )
    index.ensure_indexed(repo, ALICE)

    hits = index.search("quantum computing basics", ALICE, top_k=3)
    health = index.health()["ann"]

    assert hits and hits[0]["title"] == "Quantum Guide"
    assert health["enabled"] is True
    assert health["backend"] == "hnswlib"
    assert health["indexed_users"] == 1


def test_resolver_honours_off_unknown_and_env(monkeypatch):
    backend, reason = resolveAnnBackend("off")
    assert backend is None and reason == "disabled_by_config"

    backend, reason = resolveAnnBackend("no-such-backend")
    assert backend is None and reason == "unknown_backend:no-such-backend"

    monkeypatch.setenv("NEUROVA_KB_ANN_MIN_RECORDS", "123")
    assert annMinRecords() == 123
    monkeypatch.delenv("NEUROVA_KB_ANN_MIN_RECORDS")
    assert annMinRecords() == DEFAULT_ANN_MIN_RECORDS


def test_prepare_vectors_rejects_dimension_mismatch_and_zero_only():
    assert prepareVectors({"a": {"vector": [1.0, 0.0]}, "b": {"vector": [1.0]}}) is None
    assert prepareVectors({"a": {"vector": [0.0, 0.0]}}) is None
    assert prepareVectors({"a": {"vector": [1.0, 0.0]}}) == {"a": [1.0, 0.0]}
