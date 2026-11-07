# -*- coding: utf-8 -*-
"""K-09 facts 侧源钟（台账 §6-570 三项设计决策，2026-11-07 点单落格）。

裁定三项：
- ① 源时间落在 facts 表两列（v36 迁移），不进 qualifier（qualifier 是冲突分组键）；
- ② 无源时间回退 recorded_at（COALESCE 语义，存量行为零漂移）；
- ③ most_recent 只认源钟，valid_from 职责不动（temporal 分类与窗口判定照旧）。

判据核心：回填一份「昨天修改的旧文档」，裁决赢家必须是它（源文档更新），
而不是今天入库的旧说法——入库钟不等于源钟。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    KnowledgeAdmissionGate,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.conflict_judge import KnowledgeConflictJudge
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore, _instant


def _iso(text: str) -> str:
    """存列口径：upsertFact 对源钟做 _instant 归一（与 valid_from 同款惯例）。"""
    return _instant(text)


def _member(factId: str, recordedAt: str, sourceModifiedAt: str = "",
            validFrom: str = "") -> dict:
    return {
        "fact_id": factId,
        "recorded_at": recordedAt,
        "source_modified_at": sourceModifiedAt or None,
        "valid_from": validFrom or None,
        "valid_until": None,
        "assertion_count": 1,
        "confidence": 0.6,
        "evidence_state": "evidenced",
    }


class TestMostRecentReadsSourceClock:
    """decide() 单元面：排序键＝COALESCE(source_modified_at, recorded_at)。"""

    def test_mostRecentPrefersNewerSourceClock(self):
        judge = KnowledgeConflictJudge(KnowledgeFactStore(":memory:"))
        olderIngest = _member("fact_a", "2026-11-06T10:00:00",
                              sourceModifiedAt="2026-01-01T00:00:00")
        newerSource = _member("fact_b", "2026-11-05T10:00:00",
                              sourceModifiedAt="2026-11-01T00:00:00")
        decision = judge.decide([olderIngest, newerSource])
        assert decision["policy"] == "most_recent"
        assert decision["winner"] == "fact_b", \
            "源文档更新的一方赢，尽管它入库更早（回填场景）"
        assert "source_modified_at" in decision["basis"], "依据写明读的是源钟"

    def test_fallsBackToRecordedAtWhenNoSourceTime(self):
        judge = KnowledgeConflictJudge(KnowledgeFactStore(":memory:"))
        older = _member("fact_a", "2026-11-01T00:00:00")
        newer = _member("fact_b", "2026-11-06T00:00:00")
        decision = judge.decide([older, newer])
        assert decision["winner"] == "fact_b", "无源钟回退 recorded_at，与存量行为一致"
        assert "recorded_at" in decision["basis"], "回退时依据写明用的是入库钟"

    def test_mixedClocksCompareOnBestAvailablePerRow(self):
        judge = KnowledgeConflictJudge(KnowledgeFactStore(":memory:"))
        withSource = _member("fact_a", "2026-11-06T00:00:00",
                             sourceModifiedAt="2026-01-01T00:00:00")
        withoutSource = _member("fact_b", "2026-11-06T12:00:00")
        decision = judge.decide([withSource, withoutSource])
        assert decision["winner"] == "fact_b", \
            "逐行取各自最好可用的钟：fact_b 的入库钟晚于 fact_a 的源钟"

    def test_validFromNeverEntersRecencyOrdering(self):
        judge = KnowledgeConflictJudge(KnowledgeFactStore(":memory:"))
        earlyWindow = _member("fact_a", "2026-11-01T00:00:00",
                              validFrom="2026-01-01T00:00:00")
        lateWindow = _member("fact_b", "2026-11-06T00:00:00",
                             validFrom="2026-12-01T00:00:00")
        decision = judge.decide([earlyWindow, lateWindow])
        assert decision["winner"] == "fact_b", \
            "valid_from 是业务生效窗不是文档钟，不参与「谁更新」的排序"


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def gate(store):
    return productionAdmissionGate(store)


def _admit(gate: KnowledgeAdmissionGate, subject: str, obj: str,
           sourceModifiedAt: str = "", sourceCreatedAt: str = ""):
    content = "%s purchased %s" % (subject, obj)
    return gate.admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId="purchased",
        objectTerm=obj, content=content,
        sourceCreatedAt=sourceCreatedAt or None,
        sourceModifiedAt=sourceModifiedAt or None,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))


class TestAdmissionPersistsSourceTimes:
    def test_admitPersistsSourceTimes(self, store, gate):
        receipt = _admit(gate, "客户X", "16寸金色",
                         sourceModifiedAt="2026-09-20T00:00:00",
                         sourceCreatedAt="2026-08-01T00:00:00")
        row = store.fact(receipt.factId)
        assert row["source_modified_at"] == _iso("2026-09-20T00:00:00")
        assert row["source_created_at"] == _iso("2026-08-01T00:00:00")

    def test_admitWithoutSourceTimesLeavesNull(self, store, gate):
        receipt = _admit(gate, "客户X", "16寸金色")
        row = store.fact(receipt.factId)
        assert row["source_modified_at"] is None
        assert row["source_created_at"] is None

    def test_dedupBackfillsSourceClock(self, store, gate):
        """同内容重放：无源钟的旧行被带源钟的新说法补齐（只补不回退）。"""
        first = _admit(gate, "客户X", "16寸金色")
        _admit(gate, "客户X", "16寸金色",
               sourceModifiedAt="2026-10-01T00:00:00")
        row = store.fact(first.factId)
        assert row["source_modified_at"] == _iso("2026-10-01T00:00:00"), \
            "重放带来源钟时回填旧行，否则同一事实永远停在无钟状态"


class TestConflictSupersedeFollowsSourceClock:
    def test_backfilledDocumentWinsSupersede(self, store, gate):
        """回填场景端到端：旧文档今天才入库，但源钟更新 ⇒ 它取代旧说法。"""
        olderDoc = _admit(gate, "客户X", "20寸红色",
                          sourceModifiedAt="2026-01-01T00:00:00")   # 旧源钟，先入库
        newerDoc = _admit(gate, "客户X", "16寸金色",
                          sourceModifiedAt="2026-11-01T00:00:00")   # 新源钟，后入库
        assert store.fact(newerDoc.factId)["status"] == "active"
        assert store.fact(olderDoc.factId)["status"] == "superseded", \
            "supersede 赢家按源钟选：源文档更新的一方活下来"


class TestProjectionCarriesSourceTimes:
    def test_entryLedgerProjectsSourceTimesIntoFacts(self, tmp_path, monkeypatch):
        from neurova.core.content_identity import normalized_key
        from neurova.knowledge.foundation.entry_ledger import EntryLedger
        from neurova.knowledge.foundation.narratives import FOUNDATION_DB_NAME
        from neurova.knowledge.repository import KnowledgeRepository

        monkeypatch.setenv("NEUROVA_KB_NARRATIVE_STORE", "on")
        body = "蜂群并发成本护栏要限流与记账两段机制。" * 4
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        item = repo.create_knowledge("default", "蜂群成本护栏", body)
        entries = [dict(entry) for entry in repo._items["default"]]
        for entry in entries:
            if entry.get("knowledge_id") == item["knowledge_id"]:
                entry["source_created_at"] = "2026-08-01T00:00:00"
                entry["source_modified_at"] = "2026-09-20T00:00:00"
        store = KnowledgeFactStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME))
        try:
            EntryLedger(store).syncFromEntries({"default": entries})
            fact = store.activeNarrativeFact("default", item["knowledge_id"],
                                             normalized_key(body))
            assert fact is not None
            row = store.fact(fact["fact_id"])
            assert row["source_modified_at"] == _iso("2026-09-20T00:00:00"), \
                "条目投影必须把源时间带进治理行"
            assert row["source_created_at"] == _iso("2026-08-01T00:00:00")
        finally:
            store.close()

    def test_reconcileRequestsCarrySourceTimes(self):
        from types import SimpleNamespace

        from neurova.knowledge.foundation.reconcile import _requestsFromRepository

        repo = SimpleNamespace(_items={"default": [{
            "knowledge_id": "k1", "title": "标题", "content": "正文",
            "source_created_at": "2026-08-01T00:00:00",
            "source_modified_at": "2026-09-20T00:00:00",
            "tenant_id": "default",
        }]})
        requests = _requestsFromRepository(repo, activityKind="import",
                                           activityBasis="test")
        assert requests[0].sourceModifiedAt == "2026-09-20T00:00:00"
        assert requests[0].sourceCreatedAt == "2026-08-01T00:00:00"


class TestEnterpriseSourceClock:
    def test_mappingDescriptorCarriesSourceTimeColumns(self, tmp_path):
        """B14 映射 DSL 补 sourceCreatedAt/sourceModifiedAt 两个键（同 validFrom 模式）。"""
        from neurova.knowledge.enterprise.registry import EnterpriseIngestor
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        store = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
        try:
            registry = OntologyTermRegistry(store)
            registry.registerMany([
                {"termId": "Order", "kind": "concept"},
                {"termId": "has_status", "kind": "relation"},
            ])
            ingestor = EnterpriseIngestor(store, registry=registry)
            descriptor = {
                "sourceId": "erp", "tenantId": "default", "sourceType": "sql",
                "columns": ["order_id", "status", "doc_modified"],
                "subject": {"template": "order:{order_id}"},
                "predicate": {"termId": "has_status"},
                "object": {"column": "status", "kind": "column"},
                "sourceModifiedAt": "doc_modified",
                "qualifiers": {}, "enabled": True, "agentId": "default",
            }
            ingestor.ingestBatch(descriptor,
                                 [{"order_id": "42", "status": "open",
                                   "doc_modified": "2026-10-01T00:00:00"}])
            facts = store.searchableFacts(agentId="default")
            hit = [f for f in facts if f.get("canonical_label") == "order:42"]
            assert hit, "事实已落库"
            row = store.fact(hit[0]["fact_id"])
            assert row["source_modified_at"] == _iso("2026-10-01T00:00:00"), \
                "企业源行的源时间按映射落库"
        finally:
            store.close()
