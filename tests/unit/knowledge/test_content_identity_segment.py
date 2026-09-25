"""内容身份归一段（工单 004，设计文档 §5 段1、B03）。

口径是"抽取后内容"，不是原始字节/URL 串——同一份内容换格式、换入口、URL 带不同参数，
在底座侧都必须落回同一行。空内容例外：无身份即不参与去重（沿用 content_identity 的保守口径）。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, KnowledgeAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.redundancy import RedundancyAudit


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def gate(store):
    return KnowledgeAdmissionGate(store)


def _request(**overrides):
    payload = dict(
        agentId="bench",
        subjectLabel="神经瓦",
        predicateTermId="has_component",
        objectTerm="记忆层",
        content="神经瓦的记忆层含时序事实底座。",
    )
    payload.update(overrides)
    return AdmissionRequest(**payload)


class TestContentIdentitySegment:
    def test_contentKeyIsWrittenOnAdmit(self, gate, store):
        receipt = gate.admit(_request(), allowPendingSegments=True)

        assert store.fact(receipt.factId)["content_key"]

    def test_sameContentViaDifferentTripleIsNotDuplicated(self, gate, store):
        """不同三元组、同一内容：条目层曾各开一行（38 行纯冗余的成因），底座只留一行。"""
        first = gate.admit(_request(), allowPendingSegments=True)
        second = gate.admit(
            _request(subjectLabel="另一个名字", predicateTermId="mentions", objectTerm="别的客体"),
            allowPendingSegments=True,
        )

        assert second.factId == first.factId
        assert second.dedupedByContent == first.factId
        assert store.factCount() == 1

    def test_normalisationMakesWidthAndCaseIrrelevant(self, gate, store):
        gate.admit(_request(content="ＮＥＵＲＯＶＡ 记忆层"), allowPendingSegments=True)
        second = gate.admit(_request(content="neurova 记忆层"), allowPendingSegments=True)

        assert store.factCount() == 1
        assert second.dedupedByContent

    def test_differentContentOnSameTripleIsOneFactAndNotContentDedup(self, store):
        """同三元组、不同内容 = 同一断言的两种说法，底座只留一行，但不是"内容去重"命中的。

        两条说法谁作数属冲突账（工单 007）；本段只保证不再各开一行。
        """
        gate = KnowledgeAdmissionGate(store)
        gate.admit(_request(content="第一种说法原文"), allowPendingSegments=True)

        second = gate.admit(_request(content="第二种说法原文"), allowPendingSegments=True)

        assert store.factCount() == 1
        assert second.dedupedByContent is None, "去重原因不能张冠李戴：这里合的是三元组不是内容"

    def test_differentTripleAndDifferentContentCreateSeparateFacts(self, store):
        gate = KnowledgeAdmissionGate(store)
        gate.admit(_request(content="第一条独立内容"), allowPendingSegments=True)
        gate.admit(
            _request(content="第二条独立内容", subjectLabel="另一个主体", objectTerm="另一个客体"),
            allowPendingSegments=True,
        )

        assert store.factCount() == 2

    def test_emptyIdentityContentSkipsDeduplication(self, gate, store):
        """无内容身份（纯标点/空白）不得互相吞没——沿用 content_identity 的保守口径。"""
        gate.admit(_request(content="!!!", subjectLabel="甲", objectTerm="一"), allowPendingSegments=True)
        gate.admit(_request(content="???", subjectLabel="乙", objectTerm="二"), allowPendingSegments=True)

        facts = [store.factCount()]
        assert facts[0] == 2
        assert "content_identity" not in gate.pendingSegments()


class TestRedundancyAudit:
    def test_auditReportsDuplicateGroupsWithoutDeleting(self, tmp_path):
        from neurova.knowledge.repository import KnowledgeRepository

        repo = KnowledgeRepository(str(tmp_path / "kb"))
        for i in range(4):
            repo.create_knowledge("a", "同一篇笔记", "完全一样的正文内容", owner_user_id="u1")
        repo.create_knowledge("a", "另一篇", "别的正文", owner_user_id="u1")

        report = RedundancyAudit.auditRepository(repo)

        assert report["total_rows"] == 5
        assert report["distinct_content_keys"] == 2
        assert report["redundant_rows"] == 3, "同正文 4 行 ⇒ 多出的 3 行是纯冗余"
        assert report["groups"][0]["count"] == 4
        assert repo_visible_unchanged(repo)

    def test_auditCountsNoIdentityRowsSeparately(self, tmp_path):
        from neurova.knowledge.repository import KnowledgeRepository

        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo.create_knowledge("a", "空正文一", "", owner_user_id="u1")
        repo.create_knowledge("a", "空正文二", "   ", owner_user_id="u1")

        report = RedundancyAudit.auditRepository(repo)

        assert report["no_identity_rows"] == 2, "算不出身份的行不得进同一桶"
        assert report["redundant_rows"] == 0


def repo_visible_unchanged(repo) -> bool:
    """审计必须只读：条目数不因审计而变化。"""
    return sum(len(v) for v in repo._items.values()) == 5
