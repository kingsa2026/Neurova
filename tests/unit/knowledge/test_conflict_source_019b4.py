"""冲突旁账收编 + source 派生（工单 019b-4 第一、二件）。

冲突这一本先落到**条目级**新表，而不是塞进 007 的 `knowledge_conflicts`：
那张表的成员是事实行、必须带 `policy_basis` 与严重度，而条目级冲突现在记的是
"两个条目标题一致、内容相异"——硬塞要么丢相似度、要么靠 fact↔entry 来回翻译。
真正的合一在 017（等事实层成为条目唯一权威源之后），这片只把**存储**搬齐。
"""

from __future__ import annotations

import json

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.narratives import FOUNDATION_DB_NAME, NarrativeStore
from neurova.knowledge.repository import KnowledgeRepository

ENV_FLAG = "NEUROVA_KB_NARRATIVE_STORE"
_ADMIN = {"id": "root", "role": "admin"}
_BODY_A = "蜂群并发成本护栏要限流与记账两段。" * 4
_BODY_B = "蜂群并发成本护栏要限流与记账两段，另外补一段回滚口径。" * 4


@pytest.fixture
def gated(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "on")
    yield KnowledgeRepository(str(tmp_path / "kb")), tmp_path


def _conflictRepo(tmp_path) -> str:
    """造一条同标题、内容相异的冲突：第二次 create 会被记 pending。"""
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    repo.create_knowledge("default", "蜂群并发成本护栏", _BODY_A, owner_user_id="u1")
    repo.create_knowledge("default", "蜂群并发成本护栏", _BODY_B, owner_user_id="u1")
    return repo


def _sidecar(tmp_path):
    return tmp_path / "kb" / "knowledge_conflicts.json"


class TestConflictTable:
    def test_entry_conflicts_table_lands_at_version_seven(self, tmp_path):
        store = NarrativeStore(str(tmp_path / FOUNDATION_DB_NAME))
        with store._conn() as conn:
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            assert "knowledge_entry_conflicts" in names
            assert int(conn.execute("PRAGMA user_version").fetchone()[0]) >= 7

    def test_detection_writes_table_not_sidecar(self, gated):
        repo, tmp_path = gated
        assert len(repo.list_conflicts()) == 0
        _conflictRepo(tmp_path)
        reopened = KnowledgeRepository(str(tmp_path / "kb"))
        rows = reopened.list_conflicts()
        assert len(rows) == 1, "闸内检测到的冲突必须在重启后仍看得见"
        assert not _sidecar(tmp_path).exists()

    def test_record_shape_is_preserved_key_for_key(self, gated):
        repo, tmp_path = gated
        before = _conflictRepo(tmp_path).list_conflicts()[0]
        after = KnowledgeRepository(str(tmp_path / "kb")).list_conflicts()[0]

        assert set(after) == set(before)
        for key in ("conflict_id", "old_id", "new_id", "title", "similarity", "reason",
                    "status", "detected_at"):
            assert after[key] == before[key], key

    def test_resolution_persists(self, gated):
        repo, tmp_path = gated
        cid = repo.list_conflicts()[0]["conflict_id"] if repo.list_conflicts() else None
        assert cid is None  # 本 fixture 自己没造冲突，先确认起点
        seeded = _conflictRepo(tmp_path)
        cid = seeded.list_conflicts()[0]["conflict_id"]
        assert seeded.resolve_conflict(cid, "keep_both", "root")

        again = KnowledgeRepository(str(tmp_path / "kb"))
        rec = next(r for r in again.list_conflicts(status="resolved")
                   if r["conflict_id"] == cid)
        assert rec["resolved_by"] == "root" and rec["resolved_at"]
        assert rec["resolution"] == "keep_both"

    def test_gateOffKeepsSidecar(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "off")
        repo = _conflictRepo(tmp_path)
        assert len(repo.list_conflicts()) == 1
        assert _sidecar(tmp_path).exists()
        rec = json.loads(_sidecar(tmp_path).read_text(encoding="utf-8"))
        assert list(rec)[0] == repo.list_conflicts()[0]["conflict_id"]

    def test_existingSidecarMovesOnceAndIsArchived(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "off")
        cid = _conflictRepo(tmp_path).list_conflicts()[0]["conflict_id"]

        monkeypatch.setenv(ENV_FLAG, "on")
        reopened = _conflictRepo(tmp_path)
        ids = {r["conflict_id"] for r in reopened.list_conflicts()}
        assert cid in ids
        assert not _sidecar(tmp_path).exists()

        reopened.resolve_conflict(cid, "supersede_old", "root")
        again = KnowledgeRepository(str(tmp_path / "kb"))
        rec = next(r for r in again.list_conflicts(status="resolved")
                   if r["conflict_id"] == cid)
        assert rec["resolved_by"] == "root" and rec["resolution"] == "supersede_old"
        # 裁决连带把旧条目墓碑化：两条旁账必须同时看见这次裁决
        assert any(kid == rec["old_id"] for kid in [r["knowledge_id"] for r in again.list_deleted()])


class TestSourceComesFromAssertions:
    def test_declaredSourceRoundTripsThroughAssertion(self, gated):
        repo, tmp_path = gated
        item = repo.create_knowledge("default", "带来源的条目", _BODY_A, owner_user_id="u1",
                                     source="import:note.txt")
        reopened = KnowledgeRepository(str(tmp_path / "kb"))
        assert reopened.find_item(item["knowledge_id"])[1]["source"] == "import:note.txt"

    def test_sourcelessEntryGetsAnHonestPlaceholder(self, gated):
        """来源为空时不能再编一个 legacy 串：审计口径下"就是这个条目本身"才是真话。"""
        repo, tmp_path = gated
        item = repo.create_knowledge("default", "无来源条目", _BODY_B, owner_user_id="u1",
                                     source="")
        reopened = KnowledgeRepository(str(tmp_path / "kb"))
        got = reopened.find_item(item["knowledge_id"])[1]["source"]
        assert got == "entry:%s" % item["knowledge_id"]

        store = KnowledgeFactStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME))
        try:
            fact = store.narrativeFactForEntry(item["knowledge_id"])
            assert store.assertions(fact["fact_id"])[0]["medium_ref"] == got
        finally:
            store.close()

    def test_legacyFallbackStaysForBackfillRows(self, tmp_path, monkeypatch):
        """回填行的 medium 仍是 legacy:knowledge.json——搬家不是重写历史。"""
        monkeypatch.setenv(ENV_FLAG, "off")
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        item = repo.create_knowledge("default", "旧库条目", _BODY_A, owner_user_id="u1",
                                     source="")
        from neurova.knowledge.foundation.backfill import LegacyFactBackfill
        store = KnowledgeFactStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME))
        try:
            LegacyFactBackfill.run(repo, store)
            fact = store.narrativeFactForEntry(item["knowledge_id"])
            assert store.assertions(fact["fact_id"])[0]["medium_ref"] == "legacy:knowledge.json"
        finally:
            store.close()
