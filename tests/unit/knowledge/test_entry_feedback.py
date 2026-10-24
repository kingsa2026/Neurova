"""文档条目（无 fact lineage）的采纳/注入账。"""
from neurova.knowledge.repository import KnowledgeRepository


def test_legacy_entry_without_id_gets_stable_migration_id():
    first = KnowledgeRepository._migrate_entry({
        "title": "legacy", "content": "body", "created_at": 1,
    })
    second = KnowledgeRepository._migrate_entry({
        "title": "legacy", "content": "body", "created_at": 1,
    })

    assert first["knowledge_id"].startswith("legacy-")
    assert first["knowledge_id"] == second["knowledge_id"], "同一条旧数据重启后必须仍是同一 id"


def test_entry_adoption_injection_and_metrics(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    item = repo.create_knowledge(
        "default", title="文档", content="正文", owner_user_id="1"
    )
    kid = item["knowledge_id"]

    assert repo.recordEntryAdoption("default", kid, "failure") is True
    feedback = repo.entryFeedbackMap([kid])
    assert feedback[kid]["adoption_outcome"] == "failure"

    assert repo.recordEntryInjections("default", [kid]) == 1
    feedback = repo.entryFeedbackMap([kid])
    assert feedback[kid]["injected_count"] == 1

    metrics = repo.entryFeedbackMetrics()
    assert metrics["total"] == 1
    assert metrics["outcomes"]["failure"] == 1
    assert metrics["injected_entries"] == 1
    assert metrics["injection_coverage"] == 1.0

    try:
        repo.recordEntryAdoption("default", kid, "not-a-state")
    except ValueError:
        pass
    else:
        raise AssertionError("未知三态必须拒绝")


def test_feedback_endpoint_writes_entry_adoption():
    from neurova.api.endpoints.console import _apply_feedback_to_entries

    class Repo:
        def __init__(self):
            self.written = []

        def recordEntryAdoption(self, agent_id, entry_id, outcome):
            self.written.append((agent_id, entry_id, outcome))
            return True

    repo = Repo()
    result = _apply_feedback_to_entries(
        repo, "a1", ["e1", "e2"], "dislike", None
    )

    assert result["recorded"] == 2
    assert repo.written == [("a1", "e1", "failure"), ("a1", "e2", "failure")]


def test_entry_feedback_persists_across_repo_restart(tmp_path):
    first = KnowledgeRepository(str(tmp_path / "kb"))
    item = first.create_knowledge(
        "default", title="文档", content="正文", owner_user_id="1"
    )
    kid = item["knowledge_id"]
    first.recordEntryAdoption("default", kid, "success")
    first.recordEntryInjections("default", [kid])

    second = KnowledgeRepository(str(tmp_path / "kb"))
    feedback = second.entryFeedbackMap([kid])

    assert feedback[kid]["adoption_outcome"] == "success"
    assert feedback[kid]["injected_count"] == 1
