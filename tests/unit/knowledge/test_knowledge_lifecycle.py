"""文档条目生命周期：可标记、可查询、检索可排除；不自动删除。"""
from neurova.knowledge.repository import KnowledgeRepository


ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}


def _create(repo, title="生命周期条目", content="lifecycle unique body"):
    return repo.create_knowledge(
        "default", title=title, content=content,
        visibility="public", owner_user_id="1",
    )


def test_archived_entry_is_excluded_from_search(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    item = _create(repo)

    assert repo.update_knowledge(
        "default", item["knowledge_id"], {"lifecycle_status": "archived"}
    ) is True

    assert repo.search_visible_items(ALICE, "lifecycle unique") == []
    # 仍可管理/恢复：详情不消失
    assert repo.get_item("default", item["knowledge_id"]) is not None


def test_expired_entry_is_excluded_from_search(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    item = _create(repo)

    assert repo.update_knowledge(
        "default", item["knowledge_id"],
        {"valid_until": "2000-01-01T00:00:00+00:00"},
    ) is True

    assert repo.search_visible_items(ALICE, "lifecycle unique") == []


def test_future_valid_until_stays_retrievable(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    item = _create(repo)

    assert repo.update_knowledge(
        "default", item["knowledge_id"],
        {"valid_until": "2999-01-01T00:00:00+00:00"},
    ) is True

    hits = repo.search_visible_items(ALICE, "lifecycle unique")
    assert [h["knowledge_id"] for h in hits] == [item["knowledge_id"]]


def test_lifecycle_report_counts_and_rows(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    active = _create(repo, "active", "active unique")
    archived = _create(repo, "archived", "archived unique")
    expired = _create(repo, "expired", "expired unique")
    repo.update_knowledge("default", archived["knowledge_id"], {"lifecycle_status": "archived"})
    repo.update_knowledge(
        "default", expired["knowledge_id"],
        {"valid_until": "2000-01-01T00:00:00+00:00"},
    )

    report = repo.lifecycleReport()

    assert report["total"] == 3
    assert report["counts"]["active"] == 1
    assert report["counts"]["archived"] == 1
    assert report["counts"]["expired"] == 1
    ids = {row["knowledge_id"] for row in report["non_retrievable"]}
    assert ids == {archived["knowledge_id"], expired["knowledge_id"]}
    assert active["knowledge_id"] not in ids


def test_expire_due_entries_dry_run_then_apply(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    due = _create(repo, "due", "due body")
    keep = _create(repo, "keep", "keep body")
    repo.update_knowledge(
        "default", due["knowledge_id"],
        {"valid_until": "2000-01-01T00:00:00+00:00"},
    )

    dry = repo.expireDueEntries(apply=False)
    assert dry["due"] == 1 and dry["archived"] == 0
    assert repo.get_item("default", due["knowledge_id"])["lifecycle_status"] == "active"

    applied = repo.expireDueEntries(apply=True)
    assert applied["due"] == 1 and applied["archived"] == 1
    archived = repo.get_item("default", due["knowledge_id"])
    assert archived["lifecycle_status"] == "archived"
    assert archived["lifecycle_reason"] == "expired"
    assert repo.get_item("default", keep["knowledge_id"])["lifecycle_status"] == "active"

    # 幂等：第二次没有可归档项
    assert repo.expireDueEntries(apply=True)["archived"] == 0


def test_archived_entry_projection_is_retracted(tmp_path):
    """归档要传到治理面：叙述事实不能被留在 active，否则图/时效路仍会读到。"""
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    repo = KnowledgeRepository(str(tmp_path / "kb"))
    item = _create(repo)
    repo.update_knowledge("default", item["knowledge_id"], {"lifecycle_status": "archived"})

    store = KnowledgeFactStore(repo._narrative_db_path)
    try:
        active_turns = {f.get("source_turn_id") for f in store.activeNarrativeFacts()}
    finally:
        store.close()

    assert "entry:%s" % item["knowledge_id"] not in active_turns
