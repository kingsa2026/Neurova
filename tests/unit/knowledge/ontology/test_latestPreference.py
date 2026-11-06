# -*- coding: utf-8 -*-
"""B-4 最新偏好查询（升级计划 §3.2 L-B B-4）：按 subject+predicate 取最新。

两次购买经冲突裁决只留最新 active 一条——latestFactsByPredicate 天然正确。
同主体同谓词不同客体 ⇒ 冲突裁决自动 supersede 旧行（admission 内建），
所以本查询不需要额外的"去重"逻辑——咽喉已保证每个 (subject, predicate)
只有一个 active 行。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    gate = productionAdmissionGate(s)

    def _admit(subject, predicate, obj, recordedAt=None):
        content = "%s %s %s" % (subject, predicate, obj)
        receipt = gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=subject, predicateTermId=predicate,
            objectTerm=obj, content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))
        if recordedAt:
            with s._lock, s._conn:
                s._conn.execute(
                    "UPDATE knowledge_facts SET recorded_at = ? WHERE fact_id = ?",
                    (recordedAt, receipt.factId))
        return receipt

    _admit("客户X", "purchased", "20寸红色", recordedAt="2026-08-01T00:00:00")
    _admit("客户X", "purchased", "16寸金色", recordedAt="2026-09-20T00:00:00")
    _admit("客户Y", "purchased", "18寸棕色", recordedAt="2026-09-01T00:00:00")
    yield s, _admit
    s.close()


class TestLatestPreference:
    def test_returnsLatestPerSubject(self, store):
        s, _admit = store
        latest = s.latestFactsByPredicate(agentId="default",
                                          predicate="purchased")
        assert len(latest) == 2, "两个客户各取一条（冲突裁决后唯一 active）"
        bySubject = {f.get("canonical_label") or "": f["object_term"] for f in latest}
        assert bySubject.get("客户X") == "16寸金色", "客户X 取最新（金色）"
        assert bySubject.get("客户Y") == "18寸棕色"

    def test_conflictResolutionSupersedesOldPreference(self, store):
        """同 subject+predicate 新 admit 自动 supersede 旧行（admission 内建）。

        latestFactsByPredicate 的"最新"语义与冲突裁决的"最新覆盖"语义一致——
        不需要额外去重，咽喉已经保证了每个 (subject, predicate) 只有一个 active 行。
        """
        s, _admit = store
        _admit("客户X", "purchased", "22寸蓝色", recordedAt="2026-10-01T00:00:00")
        latest = s.latestFactsByPredicate(agentId="default", predicate="purchased")
        bySubject = {f.get("canonical_label") or "": f["object_term"] for f in latest}
        assert bySubject.get("客户X") == "22寸蓝色", \
            "新购买 supersede 旧购买，latest 反映最新状态"

    def test_differentSubjectsIndependent(self, store):
        s, _admit = store
        _admit("客户Z", "purchased", "22寸蓝色", recordedAt="2026-10-01T00:00:00")
        latest = s.latestFactsByPredicate(agentId="default", predicate="purchased")
        assert len(latest) == 3, "三个客户各自独立"
