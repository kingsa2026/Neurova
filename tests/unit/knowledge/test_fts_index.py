"""FTS5 持久倒排：检索、可见性、标签/分类、更新/删除/归档。"""
import pytest

from neurova.knowledge.repository import KnowledgeRepository

ALICE = {"user_id": "1", "role": "user"}
BOB = {"user_id": "2", "role": "user"}
ADMIN = {"user_id": "9", "role": "admin"}


@pytest.fixture()
def repo(tmp_path):
    r = KnowledgeRepository(str(tmp_path / "kb"))
    r.create_knowledge(
        "default", knowledge_id="k-public", title="Quantum Guide",
        content="quantum computing basics", category="tech", tags=["ai"],
        visibility="public", owner_user_id="1",
    )
    r.create_knowledge(
        "default", knowledge_id="k-private", title="Secret Recipe",
        content="grandma cookie recipe", category="life", tags=["food"],
        visibility="private", owner_user_id="1",
    )
    r.create_knowledge(
        "default", knowledge_id="k-other", title="Other Notes",
        content="unrelated text", category="misc", tags=["misc"],
        visibility="private", owner_user_id="2",
    )
    return r


def test_fts_search_respects_visibility(repo):
    assert [h["id"] for h in repo.ftsSearch("quantum", ALICE)] == ["k-public"]
    assert [h["id"] for h in repo.ftsSearch("cookie", ALICE)] == ["k-private"]
    assert repo.ftsSearch("cookie", BOB) == []
    assert [h["id"] for h in repo.ftsSearch("cookie", ADMIN)] == ["k-private"]


def test_fts_filters_tags_category_and_agent(repo):
    assert [h["id"] for h in repo.ftsSearch("quantum", ALICE, category="tech")] == ["k-public"]
    assert repo.ftsSearch("quantum", ALICE, category="life") == []
    assert [h["id"] for h in repo.ftsSearch("quantum", ALICE, tags=["ai"])] == ["k-public"]
    assert repo.ftsSearch("quantum", ALICE, tags=["food"]) == []
    assert [h["id"] for h in repo.ftsSearch("quantum", ALICE, agent_id="default")] == ["k-public"]


def test_fts_update_delete_archive_and_health(repo):
    assert repo.ftsSearch("quantum", ALICE)

    repo.update_knowledge(
        "default", "k-public",
        {"title": "Rust Guide", "content": "rust async runtime"},
    )
    assert repo.ftsSearch("quantum", ALICE) == []
    assert [h["id"] for h in repo.ftsSearch("rust", ALICE)] == ["k-public"]

    repo.delete_knowledge("default", "k-private")
    assert repo.ftsSearch("cookie", ALICE) == []

    repo.update_knowledge("default", "k-public", {"lifecycle_status": "archived"})
    assert repo.ftsSearch("rust", ALICE) == []

    health = repo.ftsHealth()
    assert health["docs"] >= 1
    assert health["active"] >= 0
