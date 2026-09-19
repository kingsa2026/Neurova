"""消解段接写咽喉（工单 006）：算法不接进 admit() 就是断点。"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, KnowledgeAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.identity.subject_resolver import SubjectResolver


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _request(**overrides):
    payload = dict(
        agentId="bench", subjectLabel="神经瓦记忆层", predicateTermId="describes",
        objectTerm="v1", content="第一段内容，讲记忆层。",
    )
    payload.update(overrides)
    return AdmissionRequest(**payload)


class TestAdmissionUsesDeterministicResolver:
    def test_withoutResolver_reportsSegmentPending(self, store):
        gate = KnowledgeAdmissionGate(store)

        receipt = gate.admit(_request(), allowPendingSegments=True)

        assert "identity_resolution" in receipt.pendingSegments
        assert "identity_resolution" not in receipt.segmentsApplied

    def test_withResolver_similarityMergeReusesSubject(self, store):
        """近义标签在 auto 阈值上并入既有主体，不再另开一个身份。"""
        gate = KnowledgeAdmissionGate(
            store, resolver=SubjectResolver(autoThreshold=0.6, reviewThreshold=0.4),
        )
        first = gate.admit(_request(), allowPendingSegments=True)

        second = gate.admit(
            _request(subjectLabel="神经瓦记忆层备份", content="第二段内容，与第一段不同。"),
            allowPendingSegments=True,
        )

        assert second.subjectKey == first.subjectKey
        assert store.subjectCount() == 1
        assert "identity_resolution" not in second.pendingSegments

    def test_withResolver_lowConfidenceCreatesSubjectAndFlagsReview(self, store):
        """置信不足：另开身份 + 标待审，等人工队列接（007 同一套人工通路）。"""
        gate = KnowledgeAdmissionGate(
            store, resolver=SubjectResolver(autoThreshold=0.99, reviewThreshold=0.2),
        )
        gate.admit(_request(), allowPendingSegments=True)

        second = gate.admit(
            _request(subjectLabel="记忆层", objectTerm="v2", content="另一段内容。"),
            allowPendingSegments=True,
        )

        assert second.needsHumanReview is True, "置信不足必须留下待审标记，不得静默合并"
        assert store.subjectCount() == 2

    def test_sameOrderReplayIsIdentical(self, tmp_path):
        """判据本意：同一输入重放两次结果一致——不是"任意到达顺序都收敛"。"""
        labels = ["神经瓦记忆层", "神经瓦记忆层备份", "别的主题域", "记忆层 神经瓦"]

        def replay(tag):
            scratch = KnowledgeFactStore(str(tmp_path / (tag + ".db")))
            gate = KnowledgeAdmissionGate(
                scratch, resolver=SubjectResolver(autoThreshold=0.8, reviewThreshold=0.5),
            )
            for index, label in enumerate(labels):
                gate.admit(
                    _request(subjectLabel=label, objectTerm="obj%d" % index,
                             content="独立正文 %s %d" % (label, index)),
                    allowPendingSegments=True,
                )
            out = sorted(scratch.listSubjects("bench"), key=lambda r: r["subject_key"])
            scratch.close()
            return [(r["canonical_label"], r["status"]) for r in out]

        assert replay("a") == replay("b")

    def test_batchClusteringIgnoresInputOrder(self, tmp_path):
        """批处理口径与顺序无关；增量写入则先到者作代表——两种口径不能混为一谈。"""
        subjects = [
            {"subject_key": "s%d" % i, "canonical_label": "神经瓦记忆层" if i % 2 else "神经瓦记忆层备份",
             "type_term_id": "concept", "aliases": []}
            for i in range(6)
        ]
        resolver = SubjectResolver(autoThreshold=0.8, reviewThreshold=0.5)

        forward = resolver.auditCollisions(subjects)
        backward = resolver.auditCollisions(list(reversed(subjects)))

        assert [c["members"] for c in forward] == [c["members"] for c in backward]

    def test_incrementalAdmitIsOrderSensitive_pinnedAsKnownLimitation(self, tmp_path):
        """已知限制（不遮蔽）：增量消解的代表元依赖到达顺序。

        要顺序无关只能在写入后跑批归并（auditCollisions + mergeSubjects），
        那属于 019 的迁移口径，本票不假装它不存在。
        """
        labels = ["神经瓦记忆层", "神经瓦记忆层备份"]

        def run(order):
            scratch = KnowledgeFactStore(str(tmp_path / ("ord%d.db" % len(order[0]))))
            gate = KnowledgeAdmissionGate(
                scratch, resolver=SubjectResolver(autoThreshold=0.8, reviewThreshold=0.5),
            )
            for index, label in enumerate(order):
                gate.admit(
                    _request(subjectLabel=label, objectTerm="o%d" % index,
                             content="正文 %s %d" % (label, index)),
                    allowPendingSegments=True,
                )
            rows = scratch.listSubjects("bench")
            first = rows[0]["canonical_label"] if len(rows) == 1 else "|".join(sorted(r["canonical_label"] for r in rows))
            scratch.close()
            return first

        assert run(labels) != run(list(reversed(labels))), \
            "两条标签会合并，代表元应是先到者——顺序不同则代表元不同"
