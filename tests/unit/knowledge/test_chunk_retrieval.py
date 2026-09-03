"""知识库块级检索溯源测试（P0-2 RAG 分块管线）。

契约：
- create_knowledge 新增 chunks 参数：[{content, index, char_start, char_end}]，
  入库到条目 chunks 字段（缺省 None=整篇模式，向后兼容）。
- search_visible_items 返回条目带 chunk_hits: [{chunk_index, content, score}]——
  命中的块与块级得分（索引路径按块级检索；substring 兜底按首块命中）。
"""

import pytest

from neurova.knowledge.repository import KnowledgeRepository


@pytest.fixture
def repo(tmp_path):
    return KnowledgeRepository(tmp_path)


def _doc_chunks():
    """三块长文：每块主题独立。"""
    return [
        {"content": "量子计算使用量子比特进行并行运算。", "index": 0, "char_start": 0, "char_end": 17},
        {"content": "经典密码学依赖大数分解难题。", "index": 1, "char_start": 18, "char_end": 31},
        {"content": "气候模型预测海洋温度上升趋势。", "index": 2, "char_start": 32, "char_end": 46},
    ]


class TestCreateWithChunks:
    def test_create_stores_chunks(self, repo):
        item = repo.create_knowledge(
            "default", title="综合文档", content="全文",
            chunks=_doc_chunks(),
        )
        stored = repo.get_item("default", item["knowledge_id"])
        assert stored["chunks"] == _doc_chunks()

    def test_create_without_chunks_backward_compatible(self, repo):
        item = repo.create_knowledge("default", title="旧式条目", content="整篇内容")
        stored = repo.get_item("default", item["knowledge_id"])
        assert stored["chunks"] is None


class TestChunkHits:
    def test_search_returns_chunk_hits(self, repo):
        item = repo.create_knowledge(
            "default", title="综合文档", content="量子计算。经典密码学。气候模型。",
            chunks=_doc_chunks(), owner_user_id="u1",
        )
        results = repo.search_visible_items({"user_id": "u1", "role": "admin"}, "量子比特")
        assert len(results) == 1
        hits = results[0].get("chunk_hits")
        assert hits, "应返回块级命中"
        assert hits[0]["chunk_index"] == 0
        assert "量子比特" in hits[0]["content"]
        assert hits[0]["score"] > 0

    def test_search_whole_doc_mode_no_chunk_hits(self, repo):
        # 未分块条目：chunk_hits 为空列表而非缺失（前端契约稳定）
        repo.create_knowledge("default", title="旧式条目", content="整篇内容")
        results = repo.search_visible_items({"user_id": "u1", "role": "admin"}, "整篇")
        assert results and results[0]["chunk_hits"] == []

    def test_substring_fallback_marks_first_hit_chunk(self, repo):
        item = repo.create_knowledge(
            "default", title="综合文档", content="量子计算。经典密码学。气候模型。",
            chunks=_doc_chunks(), owner_user_id="u1",
        )
        # 强制走 substring 兜底：索引置空不可用
        repo._indexes = {k: None for k in repo._indexes}
        results = repo.search_visible_items({"user_id": "u1", "role": "admin"}, "大数分解")
        assert len(results) == 1
        hits = results[0]["chunk_hits"]
        assert hits and hits[0]["chunk_index"] == 1

    def test_chunk_hits_empty_on_no_match(self, repo):
        repo.create_knowledge(
            "default", title="综合文档", content="量子计算。经典密码学。",
            chunks=_doc_chunks(), owner_user_id="u1",
        )
        results = repo.search_visible_items({"user_id": "u1", "role": "admin"}, "量子")
        for r in results:
            assert isinstance(r["chunk_hits"], list)
