"""RetrievalMethod 四态枚举（TDD — Dify 对标 P0-3）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §2.6 / §4 P0-3）：
- 四态：SEMANTIC_SEARCH / FULL_TEXT_SEARCH / HYBRID_SEARCH / KEYWORD_SEARCH
- 能力助手：is_support_semantic_search / is_support_fulltext_search
  按后端类型决定支持集（与 Dify 的向量库类型能力位对齐）
- from_str 宽松解析（大小写不敏感、接受连字符/空格），非法值报 ValueError
"""

import pytest

from neurova.knowledge.search import RetrievalMethod


class TestRetrievalMethodEnum:
    def test_four_states_exist(self):
        assert RetrievalMethod.SEMANTIC_SEARCH.value == "semantic_search"
        assert RetrievalMethod.FULL_TEXT_SEARCH.value == "full_text_search"
        assert RetrievalMethod.HYBRID_SEARCH.value == "hybrid_search"
        assert RetrievalMethod.KEYWORD_SEARCH.value == "keyword_search"

    def test_from_str_loose_parsing(self):
        assert RetrievalMethod.from_str("semantic") is RetrievalMethod.SEMANTIC_SEARCH
        assert RetrievalMethod.from_str("HYBRID") is RetrievalMethod.HYBRID_SEARCH
        assert RetrievalMethod.from_str("full-text") is RetrievalMethod.FULL_TEXT_SEARCH
        assert RetrievalMethod.from_str("keyword_search") is RetrievalMethod.KEYWORD_SEARCH
        assert RetrievalMethod.from_str("hybrid_search") is RetrievalMethod.HYBRID_SEARCH

    def test_from_str_invalid_raises(self):
        with pytest.raises(ValueError):
            RetrievalMethod.from_str("no_such_method")

    def test_capability_helpers(self):
        # 语义路依赖向量后端：faiss/onnx/fastembed 支持，tfidf 不支持
        assert RetrievalMethod.SEMANTIC_SEARCH.is_support_semantic_search("faiss")
        assert not RetrievalMethod.SEMANTIC_SEARCH.is_support_semantic_search("tfidf")
        # 全文路：tfidf/bm25 类后端都支持
        assert RetrievalMethod.FULL_TEXT_SEARCH.is_support_fulltext_search("tfidf")
        assert RetrievalMethod.FULL_TEXT_SEARCH.is_support_fulltext_search("bm25")
        assert not RetrievalMethod.FULL_TEXT_SEARCH.is_support_fulltext_search("unknown_backend")
        # hybrid 语义+全文都要求
        assert RetrievalMethod.HYBRID_SEARCH.is_support_semantic_search("faiss")
        assert RetrievalMethod.HYBRID_SEARCH.is_support_fulltext_search("bm25")

    def test_backend_normalize(self):
        # 后端名带前缀/大小写差异时仍可判定
        assert RetrievalMethod.SEMANTIC_SEARCH.is_support_semantic_search("FAISS")
