"""
VectorSearch（TF-IDF 关键词向量检索）单元测试 — 按当前真实 API 重写

真实 API:
- VectorSearch(index_path=None, config=None)
- add_text(text, metadata=None, doc_id=None) -> bool
- search(query, limit=10, threshold=0.0, metadata_filter=None) -> List[SearchResult(text, score, metadata, index)]
- update_document / remove_text / clear / size(property) / get_stats / get_documents
"""

import pytest

from neurova.cognitive_layers.memory_layer.vector_search import VectorSearch


@pytest.fixture
def vs():
    return VectorSearch()


class TestIndexing:
    def test_add_text_returns_true(self, vs):
        assert vs.add_text("你好世界", doc_id="d1") is True

    def test_size_tracks_documents(self, vs):
        vs.add_text("文档一", doc_id="d1")
        vs.add_text("文档二", doc_id="d2")
        assert vs.size == 2

    def test_duplicate_id_rejected_or_updated(self, vs):
        vs.add_text("第一版", doc_id="d1")
        # 重复 id：要么拒绝要么更新，不允许无限膨胀
        vs.add_text("第二版", doc_id="d1")
        assert vs.size == 1


class TestSearch:
    def test_search_finds_exact_token(self, vs):
        vs.add_text("你好世界", doc_id="d1")
        results = vs.search("你好", limit=5)
        texts = [r.text for r in results]
        assert "你好世界" in texts

    def test_search_no_match_below_threshold(self, vs):
        vs.add_text("完全无关的内容", doc_id="d1")
        results = vs.search("量子纠缠超导", limit=5, threshold=0.9)
        assert all(r.score < 0.9 for r in results)

    def test_search_limit(self, vs):
        for i in range(5):
            vs.add_text(f"共同词汇 文档{i}", doc_id=f"d{i}")
        results = vs.search("共同词汇", limit=3)
        assert len(results) <= 3

    def test_chinese_tokenization(self, vs):
        vs.add_text("机器学习改变世界", doc_id="ml")
        results = vs.search("机器学习", limit=3)
        assert any(r.text == "机器学习改变世界" for r in results)

    def test_metadata_filter(self, vs):
        vs.add_text("带标签的文档", doc_id="tagged", metadata={"kind": "note"})
        vs.add_text("另一份文档", doc_id="plain")
        results = vs.search("文档", limit=10, metadata_filter={"kind": "note"})
        assert all(r.metadata.get("kind") == "note" for r in results)
        assert any(r.text == "带标签的文档" for r in results)


class TestUpdateRemoveClear:
    def test_update_document(self, vs):
        vs.add_text("旧内容", doc_id="d1")
        updated = vs.update_document("d1", "新内容")
        if updated:
            assert any(r.text == "新内容" for r in vs.search("新内容", limit=5))

    def test_remove_text(self, vs):
        vs.add_text("要删除的", doc_id="d1")
        assert vs.remove_text("d1") is True
        assert vs.size == 0
        assert vs.get_document("d1") is None

    def test_clear(self, vs):
        vs.add_text("a", doc_id="a")
        vs.add_text("b", doc_id="b")
        vs.clear()
        assert vs.size == 0


class TestStats:
    def test_get_stats_dict(self, vs):
        vs.add_text("统计", doc_id="s1")
        stats = vs.get_stats()
        assert isinstance(stats, dict)
