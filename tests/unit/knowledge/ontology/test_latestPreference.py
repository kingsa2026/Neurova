# -*- coding: utf-8 -*-
"""B-4 最新偏好查询（升级计划 §3.2 L-B B-4）：按 subject+predicate 取最新。

两次购买只返回最新一条；不同主体的最新各自返回。
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
    yield s
    s.close()


class TestLatestPreference:
    def test_returnsOnlyLatestPerSubject(self, store):
        latest = store.latestFactsByPredicate(agentId="default",
                                              predicate="purchased")
        assert len(latest) == 2, "两个客户各取最新一条"
        bySubject = {f.get("canonical_label") or "": f["object_term"] for f in latest}
        assert bySubject.get("客户X") == "16寸金色", "客户X 取最新（金色）"
        assert bySubject.get("客户Y") == "18寸棕色"

    @pytest.mark.xfail(reason='retract 级联 retractAllDerivedFrom 后 MAX 子查询回退逻辑待验')
    def test_retractedExcluded(self, store):
        # 撤销客户X的最新购买 → 回退到前一条
        key = store.resolveSubjectKey("default", "客户X")
        rows = store._conn.execute(
            "SELECT fact_id FROM knowledge_facts"
            " WHERE subject_key = ? AND object_term = '16寸金色'",
            (key,)).fetchall()
        for r in rows:
            store.retract(r["fact_id"], reason="测试撤销")
        latest = store.latestFactsByPredicate(agentId="default",
                                              predicate="purchased")
        bySubject = {f.get("canonical_label") or "": f["object_term"] for f in latest}
        assert bySubject.get("客户X") == "20寸红色", "最新被撤后回退到次新"
