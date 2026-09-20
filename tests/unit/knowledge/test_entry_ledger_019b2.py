"""条目写路径转调咽喉（工单 019b-2）。

闸内每一次"这条知识说了什么"的变化都必须在治理层留痕：新增即 admit、编辑即新行取代旧行、
删除即 retract。条目上显示的置信度从此是聚合出来的，不是调用方传进来的那个数。

闸外必须一字不改旧行为——否则这根开关就不是开关。
"""

from __future__ import annotations

import pytest

from neurova.core.content_identity import normalized_key
from neurova.knowledge.foundation.entry_ledger import EntryLedger
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.narratives import FOUNDATION_DB_NAME
from neurova.knowledge.repository import KnowledgeRepository

ENV_FLAG = "NEUROVA_KB_NARRATIVE_STORE"
_BODY_A = "蜂群并发成本护栏要限流与记账两段机制。" * 4
_BODY_B = "检索评测台架必须先冻结基线，再动读路径。" * 4
_BODY_C = "反思反哺链分软通道与硬拦截两条，各自独立开关。" * 4


@pytest.fixture
def gated(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "on")
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    yield repo, tmp_path


def _facts(tmp_path) -> KnowledgeFactStore:
    return KnowledgeFactStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME))


def _active(store: KnowledgeFactStore, agentId: str, knowledgeId: str, contentKey: str = None):
    return store.activeNarrativeFact(agentId, knowledgeId, contentKey)


class TestCreateAdmits:
    def test_newEntryWritesGovernanceRow(self, gated):
        repo, tmp_path = gated
        item = repo.create_knowledge("default", "蜂群并发成本护栏", _BODY_A,
                                     owner_user_id="u1", source="import:note.txt",
                                     confidence=0.7)
        store = _facts(tmp_path)
        try:
            fact = _active(store, "default", item["knowledge_id"])
            assert fact is not None, "闸内新增必须留下 active 治理行"
            assert fact["record_kind"] == "narrative"
            assert fact["content_key"] == normalized_key(_BODY_A)
            assert fact["content"] == "", "正文唯一副本在叙述层"
            assert store.assertions(fact["fact_id"]), "无主知识不许进账"
        finally:
            store.close()

    def test_DisplayedConfidenceIsAggregatedNotPassedIn(self, gated):
        repo, tmp_path = gated
        item = repo.create_knowledge("default", "检索评测台架", _BODY_B,
                                     owner_user_id="u7", confidence=0.7)
        # 1 个来源 0.45，加"有现场可回放"0.05（source_turn_id=entry:<kid>）= 0.50；
        # 要验的是它由聚合而来，不是调用方传进来的那个数。
        assert item["confidence"] == pytest.approx(0.50)
        store = _facts(tmp_path)
        try:
            fact = _active(store, "default", item["knowledge_id"])
            assert fact["confidence"] == pytest.approx(0.50)
        finally:
            store.close()


class TestEditSupersedes:
    def test_BodyEditReplacesTheGovernanceRow(self, gated):
        repo, tmp_path = gated
        item = repo.create_knowledge("default", "反思反哺链", _BODY_C, owner_user_id="u1")
        before = item["knowledge_id"]
        assert repo.update_knowledge("default", before, {"content": _BODY_A})

        store = _facts(tmp_path)
        try:
            fresh = _active(store, "default", before, normalized_key(_BODY_A))
            assert fresh is not None and fresh["content_key"] == normalized_key(_BODY_A)
            history = [f for f in store.factsForSubject(fresh["subject_key"], includeInactive=True)
                       if f["record_kind"] == "narrative"]
            old = [f for f in history if f["status"] == "superseded"]
            assert len(old) == 1, "编辑必须在账上留下一条被取代的旧说法"
            assert fresh["supersedes_fact_id"] == old[0]["fact_id"]
            assert old[0]["content_key"] == normalized_key(_BODY_C)
        finally:
            store.close()

    def test_SameBodyEntriesShareOneGovernanceRow(self, gated):
        """同内容即同一知识——折叠在条目层同样成立，否则 B03 在叙述层复活。"""
        repo, tmp_path = gated
        first = repo.create_knowledge("default", "甲写的笔记", _BODY_A, owner_user_id="u1")
        second = repo.create_knowledge("default", "乙写的笔记", _BODY_A, owner_user_id="u2")
        store = _facts(tmp_path)
        try:
            assert _active(store, "default", second["knowledge_id"],
                           normalized_key(_BODY_A))["fact_id"] == \
                   _active(store, "default", first["knowledge_id"])["fact_id"]
            assert store.factCount() == 1
        finally:
            store.close()

    def test_MetadataOnlyEditAddsNoVersion(self, gated):
        """可见性/共享名单不是"新说法"，不该冒充一次知识更新。"""
        repo, tmp_path = gated
        admin = {"id": "root", "role": "admin"}
        item = repo.create_knowledge("default", "公共看板说明", _BODY_B, owner_user_id="u1")
        store = _facts(tmp_path)
        try:
            factId = _active(store, "default", item["knowledge_id"])["fact_id"]
            repo.share_entry(admin, item["knowledge_id"], ["u9"])
            repo.submit_to_public(admin, item["knowledge_id"])
            repo.review_public_submission(admin, item["knowledge_id"], True, reviewed_by="root")
            assert store.factCount() == 1
            again = store.fact(factId)
            assert again["status"] == "active"
            assert again["confidence"] == pytest.approx(0.50)
        finally:
            store.close()


class TestDeleteRetracts:
    def test_DeleteMarksGovernanceRowRetracted(self, gated):
        repo, tmp_path = gated
        item = repo.create_knowledge("default", "会被删的条目", _BODY_C, owner_user_id="u1")
        store = _facts(tmp_path)
        try:
            factId = _active(store, "default", item["knowledge_id"])["fact_id"]
            assert repo.delete_knowledge("default", item["knowledge_id"], deleted_by="u1")
            assert store.fact(factId)["status"] == "retracted"
            assert _active(store, "default", item["knowledge_id"]) is None
        finally:
            store.close()


class TestGateOffStaysOld:
    def test_NoFoundationFileIsCreated(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_FLAG, raising=False)
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        item = repo.create_knowledge("default", "闸外条目", _BODY_A, owner_user_id="u1",
                                     confidence=0.7)
        assert item["confidence"] == 0.7, "闸外必须原样存调用方给的数（旧行为）"
        assert not (tmp_path / "kb" / FOUNDATION_DB_NAME).exists()
        assert repo.update_knowledge("default", item["knowledge_id"], {"title": "改名"})
        assert repo.delete_knowledge("default", item["knowledge_id"], deleted_by="u1")


class TestProjectionInvariant:
    def test_MixedWritesLeaveNoDivergence(self, gated):
        repo, tmp_path = gated
        admin = {"id": "root", "role": "admin"}
        keep = repo.create_knowledge("default", "留下一条", _BODY_A, owner_user_id="u1")
        repo.create_knowledge("kai", "折叠到同内容", _BODY_A, owner_user_id="u2")
        edit = repo.create_knowledge("default", "改过正文", _BODY_B, owner_user_id="u1")
        gone = repo.create_knowledge("default", "会被删除", _BODY_C, owner_user_id="u1")
        repo.update_knowledge("default", edit["knowledge_id"], {"content": _BODY_C + "补一段"})
        repo.share_entry(admin, keep["knowledge_id"], ["u5"])
        repo.delete_knowledge("default", gone["knowledge_id"], deleted_by="root")

        store = _facts(tmp_path)
        try:
            assert EntryLedger(store).verifyProjection(repo._items) == []
        finally:
            store.close()
        assert KnowledgeRepository(str(tmp_path / "kb"))._projectionDrift == []

    def test_DivergenceIsReportedNotHidden(self, gated):
        """条目在、治理行没了（写一半崩/有人直接改库）必须说出来，不许静默当成一致。

        自动补投的语义不在这一片定：撤回过的内容被重新主张，究竟算"复活同一条事实"
        还是"再开一条"，是生命周期与内容去重相撞的独立问题（见工单 019b-2 的注记）。
        """
        repo, tmp_path = gated
        item = repo.create_knowledge("default", "治理行会被抹掉的条目", _BODY_B, owner_user_id="u1")
        store = _facts(tmp_path)
        try:
            factId = _active(store, "default", item["knowledge_id"])["fact_id"]
            store._conn.execute("DELETE FROM knowledge_facts WHERE fact_id = ?", (factId,))
            store._conn.commit()
        finally:
            store.close()

        reopened = KnowledgeRepository(str(tmp_path / "kb"))
        assert reopened._projectionDrift == []
        store2 = _facts(tmp_path)
        try:
            assert _active(store2, "default", item["knowledge_id"],
                           normalized_key(_BODY_B)) is not None
        finally:
            store2.close()
