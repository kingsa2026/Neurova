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
        return original(*args, **kwargs)

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


def test_fts_off_uses_inmemory(repo, monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_AUX_SCAN_LIMIT", "1")
    monkeypatch.setenv("NEUROVA_KB_FTS_INDEX", "off")
    called = []
    monkeypatch.setattr(
        hybrid_mod, "bm25_rank",
        lambda *a, **k: called.append("bm25") or [],
    )
    monkeypatch.setattr(
        hybrid_mod, "full_text_search",
        lambda *a, **k: called.append("fts") or [],
    )

    hybrid_mod.hybrid_search_knowledge(repo, ALICE, "shared alpha", limit=5)

    assert called == ["bm25", "fts"]
