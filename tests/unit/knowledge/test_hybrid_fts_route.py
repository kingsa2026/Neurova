"""大语料 hybrid 走 FTS5 倒排，失败/关闭时回退内存词法路。"""
import pytest

from neurova.knowledge import hybrid as hybrid_mod
from neurova.knowledge.repository import KnowledgeRepository

ALICE = {"user_id": "1", "role": "user"}


@pytest.fixture()
def repo(tmp_path):
    r = KnowledgeRepository(str(tmp_path / "kb"))
    for i in range(3):
        r.create_knowledge(
            "default", title="doc %d" % i, content="shared alpha %d" % i,
            visibility="public", owner_user_id="1",
        )
    return r


def test_large_corpus_uses_fts_and_skips_inmemory(repo, monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_AUX_SCAN_LIMIT", "1")
    monkeypatch.setenv("NEUROVA_KB_FTS_INDEX", "on")
    calls = []
    original = repo.ftsSearch

    def wrapped(*args, **kwargs):
        calls.append(1)
        return [dict(hit, score=1.0) for hit in original(*args, **kwargs)]

    monkeypatch.setattr(repo, "ftsSearch", wrapped)
    monkeypatch.setattr(
        hybrid_mod, "bm25_rank",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("in-memory bm25 should be skipped")),
    )
    monkeypatch.setattr(
        hybrid_mod, "full_text_search",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("in-memory fts should be skipped")),
    )

    hits = hybrid_mod.hybrid_search_knowledge(repo, ALICE, "shared alpha", limit=5)

    assert calls, "大语料没有调用 FTS5"
    assert hits
    fts_hit = next(hit for hit in hits if hit["title"] == "doc 0")
    assert fts_hit["confidence_breakdown"]["fts"] > 0
    assert fts_hit["confidence_breakdown"]["bm25"] == 0


def test_fts_off_uses_inmemory(repo, monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_AUX_SCAN_LIMIT", "1")
    monkeypatch.setenv("NEUROVA_KB_FTS_INDEX", "off")
    called = []
    monkeypatch.setattr(
        hybrid_mod, "bm25_rank",
        lambda *a, **k: called.append("bm25") or [("doc-0", 2.0)],
    )
    monkeypatch.setattr(
        hybrid_mod, "full_text_search",
        lambda *a, **k: called.append("fts") or [("doc-1", 3.0)],
    )

    hybrid_mod.hybrid_search_knowledge(repo, ALICE, "shared alpha", limit=5)

    assert called == ["bm25", "fts"]


def test_inmemory_routes_do_not_borrow_each_others_scores(repo, monkeypatch):
    ids = {item["title"]: item["knowledge_id"] for item in repo.visible_items(ALICE)}
    monkeypatch.setenv("NEUROVA_KB_AUX_SCAN_LIMIT", "1")
    monkeypatch.setenv("NEUROVA_KB_FTS_INDEX", "off")
    monkeypatch.setattr(
        hybrid_mod, "bm25_rank",
        lambda *a, **k: [(ids["doc 0"], 2.0)],
    )
    monkeypatch.setattr(
        hybrid_mod, "full_text_search",
        lambda *a, **k: [(ids["doc 1"], 3.0)],
    )

    hits = hybrid_mod.hybrid_search_knowledge(repo, ALICE, "shared alpha", limit=5)

    by_title = {hit["title"]: hit["confidence_breakdown"] for hit in hits}
    assert by_title["doc 0"]["bm25"] == 2.0
    assert by_title["doc 0"]["fts"] == 0.0
    assert by_title["doc 1"]["fts"] == 3.0
    assert by_title["doc 1"]["bm25"] == 0.0
