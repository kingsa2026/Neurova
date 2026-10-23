"""hybrid 元数据预筛：过滤必须发生在候选集构建时，而不是结果后筛。"""
import time

from neurova.knowledge import hybrid as hybrid_mod
from neurova.knowledge.repository import KnowledgeRepository


ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}


def _repo(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    repo.create_knowledge(
        "default", title="alpha", content="shared alpha body",
        category="cat-a", tags=["x"], source="manual",
        visibility="public", owner_user_id="1",
    )
    repo.create_knowledge(
        "default", title="beta", content="shared beta body",
        category="cat-b", tags=["y"], source="import",
        visibility="public", owner_user_id="1",
    )
    return repo


def test_hybrid_prefilters_corpus_before_bm25_and_fts(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    seen = []

    def fake_bm25(query, corpus, top_k=10):
        seen.append(("bm25", len(corpus)))
        return []

    def fake_fts(query, corpus, top_k=10):
        seen.append(("fts", len(corpus)))
        return []

    monkeypatch.setattr(hybrid_mod, "bm25_rank", fake_bm25)
    monkeypatch.setattr(hybrid_mod, "full_text_search", fake_fts)

    hits = hybrid_mod.hybrid_search_knowledge(
        repo, ALICE, "shared", limit=5, category="cat-a", tags=["x"],
        source="manual", updated_after=0, vector_index=None,
    )

    assert [h["title"] for h in hits] == ["alpha"]
    assert seen == [("bm25", 1), ("fts", 1)], "过滤后语料必须只剩 1 条，不能全库扫描"


def test_hybrid_updated_after_excludes_old_entries(tmp_path):
    repo = _repo(tmp_path)

    future = time.time() + 3600
    hits = hybrid_mod.hybrid_search_knowledge(
        repo, ALICE, "shared", limit=5, updated_after=future, vector_index=None
    )
    assert hits == []


def test_hybrid_source_filter(tmp_path):
    repo = _repo(tmp_path)

    hits = hybrid_mod.hybrid_search_knowledge(
        repo, ALICE, "shared", limit=5, source="import", vector_index=None
    )
    assert [h["title"] for h in hits] == ["beta"]


def test_aux_scan_limit_bounds_large_corpus(tmp_path, monkeypatch):
    """大语料时 BM25/FTS 只看主索引候选，不再全量 tokenize。"""
    repo = _repo(tmp_path)
    monkeypatch.setenv("NEUROVA_KB_AUX_SCAN_LIMIT", "1")
    monkeypatch.setenv("NEUROVA_KB_FTS_INDEX", "off")
    seen = []

    def fake_bm25(query, corpus, top_k=10):
        seen.append(len(corpus))
        return []

    def fake_fts(query, corpus, top_k=10):
        seen.append(len(corpus))
        return []

    monkeypatch.setattr(hybrid_mod, "bm25_rank", fake_bm25)
    monkeypatch.setattr(hybrid_mod, "full_text_search", fake_fts)

    hybrid_mod.hybrid_search_knowledge(
        repo, ALICE, "shared", limit=5, vector_index=None
    )

    assert seen == [1, 1], "大语料辅助路必须按 aux cap 取主索引候选"


def test_prefilter_scales_with_category_partition(tmp_path, monkeypatch):
    """候选集预筛按分区生效：60 条里只把 cat-a 的 30 条送进 BM25/FTS。"""
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    for i in range(60):
        repo.create_knowledge(
            "default", title="doc-%02d" % i, content="shared haystack %02d" % i,
            category="cat-a" if i % 2 == 0 else "cat-b",
            tags=["x"] if i % 2 == 0 else ["y"],
            visibility="public", owner_user_id="1",
        )
    seen = []

    def fake_bm25(query, corpus, top_k=10):
        seen.append(len(corpus))
        return []

    def fake_fts(query, corpus, top_k=10):
        seen.append(len(corpus))
        return []

    monkeypatch.setattr(hybrid_mod, "bm25_rank", fake_bm25)
    monkeypatch.setattr(hybrid_mod, "full_text_search", fake_fts)

    hybrid_mod.hybrid_search_knowledge(
        repo, ALICE, "shared", limit=5, category="cat-a", tags=["x"],
        vector_index=None,
    )

    assert seen == [30, 30], "预筛必须把 60 条语料缩到 30 条，而不是全量扫描"
