# -*- coding: utf-8 -*-
"""P3-1a 审批决策绑定证据内容哈希（对照研究 reference_y 报告 §5 血缘差距一）红灯。

对方 StatementHash 语义的本仓落地：候选/建议生成时计算**证据内容哈希**
（sha256 截断），人工审批请求必须回带同一哈希——「批准时看的 ≠ 生效时用的」
在入口就被拒（409 语义），防证据漂移后被静默批准。

- 关系候选：evidence_hash = sha256(source_text)；批准/拒绝均校验；
- schema 术语建议：evidence_hash = sha256(payload_json)；decide 校验；
- 兼容纪律：迁移前生成的存量行 evidence_hash 为空串——审批不带哈希放行
  （不阻断存量治理流），带哈希则按不匹配拒。
"""

from __future__ import annotations

import hashlib

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.relation_candidates import RelationCandidateStore
from neurova.knowledge.ontology.schema_suggester import SchemaSuggester
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


def _hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


class TestRelationCandidateEvidenceHash:

    def test_recordComputesEvidenceHash(self, store):
        candidates = RelationCandidateStore(store)
        candidateId = candidates.record("default", "位于", sourceEntryId="e1",
                                        sourceText="甲 位于 上海")
        row = candidates.get(candidateId)
        assert row["evidence_hash"] == _hash("甲 位于 上海")

    def test_approveWithoutHashRejected(self, store):
        candidates = RelationCandidateStore(store)
        candidateId = candidates.record("default", "位于", sourceEntryId="e1",
                                        sourceText="甲 位于 上海")
        with pytest.raises(ValueError, match="evidence"):
            candidates.approve(candidateId, tenantId="default")

    def test_approveWithWrongHashRejected(self, store):
        candidates = RelationCandidateStore(store)
        candidateId = candidates.record("default", "位于", sourceEntryId="e1",
                                        sourceText="甲 位于 上海")
        with pytest.raises(ValueError, match="不匹配"):
            candidates.approve(candidateId, tenantId="default",
                               evidenceHash=_hash("别的文本"))

    def test_approveWithMatchingHashSucceeds(self, store):
        candidates = RelationCandidateStore(store)
        candidateId = candidates.record("default", "位于", sourceEntryId="e1",
                                        sourceText="甲 位于 上海")
        registry = OntologyTermRegistry(store)
        out = candidates.approve(candidateId, tenantId="default",
                                 evidenceHash=_hash("甲 位于 上海"),
                                 termRegistry=registry)
        assert out["status"] == "approved"
        assert out["promoted_term_id"] == "位于"

    def test_rejectAlsoBindsEvidence(self, store):
        candidates = RelationCandidateStore(store)
        candidateId = candidates.record("default", "位于", sourceEntryId="e1",
                                        sourceText="甲 位于 上海")
        with pytest.raises(ValueError, match="evidence"):
            candidates.reject(candidateId, tenantId="default")

    def test_legacyRowWithoutHashStillApprovable(self, store):
        # 存量行兼容：evidence_hash 空串（迁移前生成）不带哈希可批，带哈希按不匹配拒
        candidates = RelationCandidateStore(store)
        candidateId = candidates.record("default", "位于", sourceEntryId="e1",
                                        sourceText="甲 位于 上海")
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE ontology_relation_candidates SET evidence_hash = ''"
                " WHERE candidate_id = ?", (candidateId,))
        registry = OntologyTermRegistry(store)
        out = candidates.approve(candidateId, tenantId="default",
                                 termRegistry=registry)
        assert out["status"] == "approved"


class TestSuggestionEvidenceHash:

    def test_decideRequiresMatchingHash(self, store):
        suggester = SchemaSuggester(store)
        # 直接落一条建议（绕过 runForSource 的目录依赖）
        payload = {"name": "Customer", "description": "客户", "synonyms": [],
                   "columns": []}
        suggestionId = suggester._recordSuggestion(
            "default", "s1", "term", "term:s1:customers", payload,
            basis="rule", confidence=0.5)
        with pytest.raises(ValueError, match="evidence"):
            suggester.decideSuggestion("default", suggestionId, "approved")
        with pytest.raises(ValueError, match="不匹配"):
            suggester.decideSuggestion("default", suggestionId, "approved",
                                       evidenceHash=_hash("别的证据"))
        import json as _json

        evidenceHash = _hash(_json.dumps(payload, ensure_ascii=False,
                                         sort_keys=True))
        out = suggester.decideSuggestion("default", suggestionId, "approved",
                                         evidenceHash=evidenceHash)
        assert out["status"] == "approved"

    def test_decideWithCorrectHashApproves(self, store):
        suggester = SchemaSuggester(store)
        payload = {"name": "Customer", "description": "客户", "synonyms": [],
                   "columns": []}
        suggestionId = suggester._recordSuggestion(
            "default", "s1", "term", "term:s1:customers", payload,
            basis="rule", confidence=0.5)
        import json as _json

        evidenceHash = _hash(_json.dumps(payload, ensure_ascii=False,
                                         sort_keys=True))
        out = suggester.decideSuggestion("default", suggestionId, "approved",
                                         evidenceHash=evidenceHash)
        assert out["status"] == "approved"
