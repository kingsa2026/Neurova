"""墓碑收编进底座库（工单 019b-2c）。

墓碑不是"另一本账"：它记的是"这条知识被谁在什么时候收回了"，本来就是治理层的事。
留在 JSON 里的代价是——开闸之后条目权威在 SQLite、删除史在文件里，两边各自演化，
restore/list_deleted 读的那份就不再是写的那份。

形状纪律与 019a 一致：`self._tombstones` 的 dict 形状逐字段不变，12 个调用点一个字不改，
换的只有 `_load` / `_save_tombstones` 两个边界。
"""

from __future__ import annotations

import json

import pytest

from neurova.core.content_identity import normalized_key
from neurova.knowledge.foundation.entry_ledger import EntryLedger
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.narratives import FOUNDATION_DB_NAME, NarrativeStore
from neurova.knowledge.repository import KnowledgeRepository

ENV_FLAG = "NEUROVA_KB_NARRATIVE_STORE"
_BODY = "被删掉的条目正文要能整份回来，不能只剩一个壳。" * 5


@pytest.fixture
def gated(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "on")
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    yield repo, tmp_path


def _store(tmp_path) -> KnowledgeFactStore:
    return KnowledgeFactStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME))


def _seed(repo) -> str:
    return repo.create_knowledge("default", "会被收回的条目", _BODY, owner_user_id="u1")[
        "knowledge_id"]


class TestMigrationAndShape:
    def test_tombstoneTableLandsInMigrationChain(self, tmp_path):
        NarrativeStore(str(tmp_path / FOUNDATION_DB_NAME))
        probe = NarrativeStore(str(tmp_path / FOUNDATION_DB_NAME))
        with probe._conn() as conn:
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            assert "knowledge_tombstones" in names
            assert int(conn.execute("PRAGMA user_version").fetchone()[0]) >= 6

    def test_recShapeSurvivesRoundTrip(self, gated):
        repo, tmp_path = gated
        kid = _seed(repo)
        repo.delete_knowledge("default", kid, deleted_by="root")

        again = KnowledgeRepository(str(tmp_path / "kb"))
        recs = again.list_deleted()
        assert len(recs) == 1
        rec = recs[0]
        assert rec["knowledge_id"] == kid
        assert rec["agent_id"] == "default"
        assert rec["deleted_by"] == "root"
        assert rec["superseded_by"] is None
        assert rec["item"]["knowledge_id"] == kid
        assert rec["item"]["content"] == _BODY


class TestWritePath:
    def test_noJsonSidecarWhenGateOpen(self, gated, tmp_path):
        repo, tmp_path = gated
        kid = _seed(repo)
        repo.delete_knowledge("default", kid, deleted_by="root")
        assert not (tmp_path / "kb" / "knowledge_tombstones.json").exists()
        assert NarrativeStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME)).tombstoneCount() == 1

    def test_restoreRemovesTheRow(self, gated, tmp_path):
        repo, tmp_path = gated
        kid = _seed(repo)
        repo.delete_knowledge("default", kid, deleted_by="root")
        assert repo.restore_knowledge(kid)
        assert NarrativeStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME)).tombstoneCount() == 0

        again = KnowledgeRepository(str(tmp_path / "kb"))
        assert again.list_deleted() == []
        assert again.find_item(kid) is not None

    def test_purgeTombstoneAlsoRetractsGovernance(self, gated, tmp_path):
        """物理清除=条目与墓碑一起没了；治理行不能继续当"活着且没人认领"悬着。"""
        repo, tmp_path = gated
        kid = _seed(repo)
        repo.delete_knowledge("default", kid, deleted_by="root")
        assert repo.purge_knowledge("default", kid)

        facts = _store(tmp_path)
        try:
            assert EntryLedger(facts).verifyProjection(repo._items) == []
            assert facts.narrativeFactForEntry(kid) is None
        finally:
            facts.close()
        assert NarrativeStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME)).tombstoneCount() == 0

    def test_supersedeConflictWritesTombstoneRow(self, gated, tmp_path):
        repo, tmp_path = gated
        first = repo.create_knowledge("default", "同一条目", _BODY, owner_user_id="u1")
        repo.create_knowledge("default", "同一条目", _BODY, owner_user_id="u1")
        repo._items["default"] = [i for i in repo._items["default"]
                                  if i["knowledge_id"] != first["knowledge_id"]]
        repo._tombstones[first["knowledge_id"]] = {
            "item": first, "agent_id": "default", "deleted_at": 1.5,
            "deleted_by": "", "superseded_by": "other",
        }
        repo._save_tombstones()

        assert NarrativeStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME)).loadTombstones()[
            first["knowledge_id"]]["superseded_by"] == "other"


class TestCutoverAndRollback:
    def test_existingJsonTombstonesMoveOnce(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_FLAG, raising=False)
        seed = KnowledgeRepository(str(tmp_path / "kb"))
        kid = _seed(seed)
        seed.delete_knowledge("default", kid, deleted_by="root")
        assert (tmp_path / "kb" / "knowledge_tombstones.json").exists()

        monkeypatch.setenv(ENV_FLAG, "on")
        reopened = KnowledgeRepository(str(tmp_path / "kb"))
        assert [r["knowledge_id"] for r in reopened.list_deleted()] == [kid]
        assert not (tmp_path / "kb" / "knowledge_tombstones.json").exists()
        archived = " ".join(NarrativeStore.findArchivedJson(str(tmp_path / "kb")))
        # 三份旁账各自留名归档：共用前缀会让事后认不出哪份是哪份（实测撞过）
        for name in ("knowledge.json", "knowledge_tombstones.json", "knowledge_conflicts.json"):
            assert name + ".pre-narrative-store-" in archived, name

    def test_purgedTombstonesDoNotComeBack(self, tmp_path, monkeypatch):
        """墓碑清空后重启不能拿快照把删除史灌回来（与条目同一纪律）。"""
        monkeypatch.delenv(ENV_FLAG, raising=False)
        seed = KnowledgeRepository(str(tmp_path / "kb"))
        kid = _seed(seed)
        seed.delete_knowledge("default", kid, deleted_by="root")
        seed.purge_knowledge("default", kid)
        assert (tmp_path / "kb" / "knowledge_tombstones.json").exists()

        monkeypatch.setenv(ENV_FLAG, "on")
        reopened = KnowledgeRepository(str(tmp_path / "kb"))
        reopened._tombstones = {}
        reopened._save_tombstones()
        assert KnowledgeRepository(str(tmp_path / "kb")).list_deleted() == []

    def test_gateOffKeepsJsonBehaviour(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_FLAG, raising=False)
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        kid = _seed(repo)
        repo.delete_knowledge("default", kid, deleted_by="root")
        rec = json.loads((tmp_path / "kb" / "knowledge_tombstones.json").read_text(encoding="utf-8"))
        assert list(rec) == [kid] and rec[kid]["item"]["content"] == _BODY
        assert not (tmp_path / "kb" / FOUNDATION_DB_NAME).exists()
