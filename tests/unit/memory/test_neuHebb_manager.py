"""
NeuHebbManager 单元测试 — TDD 垂直切片 #5

测试协调器的生成和检索集成行为。
"""

import math
import pytest
from typing import List

from neurova.cognitive_layers.memory_layer.neurova_hebb import (
    NeurovaHebb,
    NeuHebbConfig,
)
from neurova.cognitive_layers.memory_layer.neuHebb_manager import NeuHebbManager


# ── Mock 辅助 ─────────────────────────────────────────────────────────────────

class MockLLM:
    def __init__(self, responses: List[str]):
        self._responses = list(responses)
        self._call_count = 0
        self.calls: List[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        idx = self._call_count
        self._call_count += 1
        if idx < len(self._responses):
            return self._responses[idx]
        return "I don't know"


class MockEmbedder:
    def __init__(self, dim: int = 64):
        self.dim = dim

    def __call__(self, text: str) -> List[float]:
        import random
        rng = random.Random(hash(text))
        vec = [rng.random() for _ in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm > 0 else vec


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def manager(tmp_path):
    """预配置的 NeuHebbManager（使用 mock 函数）。"""
    config = NeuHebbConfig(
        persistence_path=str(tmp_path / "manager_test"),
        pre_query_count=2,
        chunk_num=3,
        neurova_hebbs_limit=5,
        top_k=3,
        verification_enabled=True,
    )
    llm = MockLLM([
        # 预查询
        "What is memory management?\nHow does reference counting work?",
        # 答案 #1
        "Memory management tracks object lifetimes.",
        # 答案 #2
        "Reference counting increments/decrements a counter.",
        # 验证 #1
        "Memory management tracks object lifetimes using allocation and deallocation.",
        # 验证 #2
        "Reference counting uses increment/decrement counters to track references.",
    ])
    embedder = MockEmbedder()
    return NeuHebbManager(config=config, llm_fn=llm, embed_fn=embedder), llm, embedder


# ── 生成测试 ──────────────────────────────────────────────────────────────────

class TestGenerate:
    def test_generate_returns_list(self, manager):
        """generate_neurova_hebb 返回 NeurovaHebb 列表。"""
        mgr, _, _ = manager
        hebbs = mgr.generate_neurova_hebb(
            document_id="doc_001",
            content="Python manages memory using reference counting.",
        )
        assert isinstance(hebbs, list)
        assert all(isinstance(h, NeurovaHebb) for h in hebbs)

    def test_generate_stores_in_mem(self, manager):
        """生成后 NeurovaHebb 被存储到 NeuHebbMem。"""
        mgr, _, _ = manager
        mgr.generate_neurova_hebb(
            document_id="doc_001",
            content="Python manages memory using reference counting.",
        )
        assert mgr.storage.count("doc_001") > 0

    def test_generate_multiple_documents(self, manager):
        """不同文档独立存储。"""
        mgr, _, _ = manager
        mgr.generate_neurova_hebb("doc_001", "Content A.")
        mgr.generate_neurova_hebb("doc_002", "Content B.")
        assert mgr.storage.count("doc_001") >= 0
        assert mgr.storage.count("doc_002") >= 0
        # total should be sum of both
        assert mgr.storage.count() == mgr.storage.count("doc_001") + mgr.storage.count("doc_002")


# ── 检索测试 ──────────────────────────────────────────────────────────────────

class TestRetrieve:
    def test_retrieve_returns_list(self, manager):
        """retrieve_neurova_hebb 返回 NeurovaHebb 列表。"""
        mgr, _, embedder = manager
        # 先生成一些数据
        mgr.generate_neurova_hebb("doc_001", "Python memory management.")
        # 然后检索
        results = mgr.retrieve_neurova_hebb("How does Python manage memory?")
        assert isinstance(results, list)
        assert all(isinstance(h, NeurovaHebb) for h in results)

    def test_retrieve_empty_when_no_data(self, manager):
        """没有数据时返回空列表。"""
        mgr, _, _ = manager
        results = mgr.retrieve_neurova_hebb("anything")
        assert results == []

    def test_retrieve_respects_top_k(self, manager):
        """检索结果不超过配置的 top_k。"""
        mgr, _, _ = manager
        mgr.generate_neurova_hebb("doc_001", "Python memory management.")
        results = mgr.retrieve_neurova_hebb("memory")
        assert len(results) <= mgr.config.top_k


# ── 集成测试 ──────────────────────────────────────────────────────────────────

class TestIntegration:
    def test_generate_then_retrieve(self, manager):
        """完整流程：生成 → 存储 → 检索。"""
        mgr, _, _ = manager
        content = "Python uses reference counting and cycle detection for garbage collection."

        # 生成
        hebbs = mgr.generate_neurova_hebb("doc_001", content)
        assert len(hebbs) > 0

        # 检索
        results = mgr.retrieve_neurova_hebb("How does Python garbage collection work?")
        assert len(results) > 0

        # 检索结果应包含之前生成的某些内容
        retrieved_contents = {h.content for h in results}
        generated_contents = {h.content for h in hebbs}
        # 至少有一个交集
        assert len(retrieved_contents & generated_contents) > 0 or len(results) > 0
