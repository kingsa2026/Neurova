"""
NeuHebbForge 单元测试 — TDD 垂直切片 #3

测试预查询生成、文档分块、Neurova Hebb 生成管道的行为。
通过依赖注入 mock LLM 和 embedding 函数，不调用真实模型。
"""

import math
import pytest
from typing import List

from neurova.cognitive_layers.memory_layer.neurova_hebb import (
    NeurovaHebb,
    NeuHebbConfig,
)
from neurova.cognitive_layers.memory_layer.neuHebb_forge import NeuHebbForge


# ── Mock 辅助 ─────────────────────────────────────────────────────────────────

class MockLLM:
    """可控的 LLM mock，按调用顺序返回预设响应。"""

    def __init__(self, responses: List[str]):
        self._responses = list(responses)
        self._call_count = 0
        self.calls: List[str] = []  # 记录收到的 prompt

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        idx = self._call_count
        self._call_count += 1
        if idx < len(self._responses):
            return self._responses[idx]
        return "I don't know"


class MockEmbedder:
    """可控的 embedding mock，返回基于 hash 的确定性向量。"""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def __call__(self, text: str) -> List[float]:
        # 简单 hash → 确定性向量
        import random
        rng = random.Random(hash(text))
        vec = [rng.random() for _ in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm > 0 else vec


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def config():
    return NeuHebbConfig(
        chunk_num=3,
        pre_query_count=2,
        verification_enabled=True,
        neurova_hebbs_limit=5,
        diversity_threshold=0.85,
    )


@pytest.fixture
def forge(config):
    """使用 mock 的 NeuHebbForge。"""
    # LLM 响应序列：
    # 1. pre_query generation (返回多个问题)
    # 2-3. answer generation (每个预查询一个答案)
    # 4-5. verification/summary (每个预查询一个验证)
    # 6-7. verification/summary (第二次验证)
    llm = MockLLM([
        # 预查询生成
        "What is Python memory management?\nHow does garbage collection work?\nWhy use reference counting?",
        # 答案生成 #1
        "Python uses reference counting as its primary memory management strategy.",
        # 答案生成 #2
        "Garbage collection uses cycle detection to free circular references.",
        # 答案生成 #3
        "Reference counting provides deterministic destruction.",
        # 验证 #1
        "Python uses reference counting plus cycle detection for memory management.",
        # 验证 #2
        "Garbage collection detects and frees circular reference cycles.",
        # 验证 #3
        "Reference counting gives deterministic object destruction.",
    ])
    embedder = MockEmbedder(dim=64)
    return NeuHebbForge(config=config, llm_fn=llm, embed_fn=embedder), llm, embedder


# ── 预查询生成 ────────────────────────────────────────────────────────────────

class TestPreQueryGeneration:
    def test_generates_queries(self, forge):
        """generate_pre_queries 返回非空查询列表。"""
        forge_obj, llm, _ = forge
        queries = forge_obj.generate_pre_queries(
            "Python uses reference counting for memory management."
        )
        assert isinstance(queries, list)
        assert len(queries) > 0
        assert all(isinstance(q, str) for q in queries)

    def test_queries_count_respects_config(self, forge):
        """生成的查询数量不超过配置上限。"""
        forge_obj, _, _ = forge
        queries = forge_obj.generate_pre_queries("Some content here.")
        assert len(queries) <= forge_obj.config.pre_query_count

    def test_llm_called_with_content(self, forge):
        """LLM 被调用时包含文档内容。"""
        forge_obj, llm, _ = forge
        content = "Neural networks use backpropagation."
        forge_obj.generate_pre_queries(content)
        assert len(llm.calls) >= 1
        assert "backpropagation" in llm.calls[0] or content[:50] in llm.calls[0]


# ── 文档分块 ──────────────────────────────────────────────────────────────────

class TestContentSplitting:
    def test_split_returns_list(self, forge):
        """split_content 返回字符串列表。"""
        forge_obj, _, _ = forge
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = forge_obj.split_content(text)
        assert isinstance(chunks, list)
        assert all(isinstance(c, str) for c in chunks)

    def test_split_preserves_content(self, forge):
        """分块后所有内容都在某个 chunk 中。"""
        forge_obj, _, _ = forge
        text = "Alpha. Beta. Gamma."
        chunks = forge_obj.split_content(text)
        combined = " ".join(chunks)
        assert "Alpha" in combined
        assert "Beta" in combined


# ── Neurova Hebb 生成 ────────────────────────────────────────────────────────

class TestNeurovaHebbGeneration:
    def test_generate_returns_list(self, forge):
        """generate_neurova_hebb 返回 NeurovaHebb 列表。"""
        forge_obj, _, _ = forge
        hebbs = forge_obj.generate_neurova_hebb(
            document_id="doc_001",
            content="Python memory management uses reference counting.",
        )
        assert isinstance(hebbs, list)
        assert all(isinstance(h, NeurovaHebb) for h in hebbs)

    def test_generated_hebbs_have_content(self, forge):
        """生成的 NeurovaHebb 有非空 content。"""
        forge_obj, _, _ = forge
        hebbs = forge_obj.generate_neurova_hebb(
            document_id="doc_001",
            content="Python memory management uses reference counting.",
        )
        for h in hebbs:
            assert h.content  # 非空
            assert h.question  # 有原始问题
            assert h.answer  # 有原始答案

    def test_generated_hebbs_have_document_id(self, forge):
        """生成的 NeurovaHebb 关联正确的 document_id。"""
        forge_obj, _, _ = forge
        hebbs = forge_obj.generate_neurova_hebb(
            document_id="my_doc",
            content="Some content.",
        )
        for h in hebbs:
            assert h.document_id == "my_doc"

    def test_generated_hebbs_have_embeddings(self, forge):
        """生成的 NeurovaHebb 有嵌入向量。"""
        forge_obj, _, _ = forge
        hebbs = forge_obj.generate_neurova_hebb(
            document_id="doc_001",
            content="Some content.",
        )
        for h in hebbs:
            assert h.embedding is not None
            assert len(h.embedding) > 0

    def test_hebbs_count_within_limit(self, forge):
        """生成的 NeurovaHebb 数量不超过 neurova_hebbs_limit。"""
        forge_obj, _, _ = forge
        hebbs = forge_obj.generate_neurova_hebb(
            document_id="doc_001",
            content="Some content.",
        )
        assert len(hebbs) <= forge_obj.config.neurova_hebbs_limit

    def test_source_is_pre_query(self, forge):
        """默认来源标记为 pre_query。"""
        forge_obj, _, _ = forge
        hebbs = forge_obj.generate_neurova_hebb(
            document_id="doc_001",
            content="Some content.",
        )
        for h in hebbs:
            assert h.source == "pre_query"


# ── 无效答案过滤 ──────────────────────────────────────────────────────────────

class TestInvalidAnswerFiltering:
    def test_idk_answers_skipped(self):
        """LLM 回答 "I don't know" 时跳过该 NeurovaHebb。"""
        llm = MockLLM([
            # 预查询
            "What is X?",
            # 答案 → 无效
            "I don't know the answer.",
        ])
        embedder = MockEmbedder()
        config = NeuHebbConfig(
            pre_query_count=1,
            verification_enabled=True,
            neurova_hebbs_limit=5,
        )
        forge = NeuHebbForge(config=config, llm_fn=llm, embed_fn=embedder)
        hebbs = forge.generate_neurova_hebb("doc_001", "Some content.")
        # 无效答案应被过滤
        assert len(hebbs) == 0

    def test_valid_answers_kept(self):
        """有效答案通过验证。"""
        llm = MockLLM([
            "What is X?",
            "X is a valid answer.",       # 有效答案
            "X is a verified answer.",     # 验证通过
        ])
        embedder = MockEmbedder()
        config = NeuHebbConfig(
            pre_query_count=1,
            verification_enabled=True,
            neurova_hebbs_limit=5,
        )
        forge = NeuHebbForge(config=config, llm_fn=llm, embed_fn=embedder)
        hebbs = forge.generate_neurova_hebb("doc_001", "Some content.")
        assert len(hebbs) >= 1
