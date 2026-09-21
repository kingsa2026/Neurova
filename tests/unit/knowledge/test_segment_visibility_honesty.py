"""段可见性必须分清「天生缺一格」与「这次装配漏了一段」。

病灶形状（2026-09-21 审计 §5.5）：`pendingSegments()` 里那句
`if "indexing" not in missing: missing.append("indexing")` 把「入索引段还没建」
硬编码成永远缺一段，于是**每个真实调用点都只能传 `allowPendingSegments=True`**
（`entry_ledger.py:62`、`backfill.py:41`、`reconcile.py:147`、`rule_engine.py:349`），
「缺段即拒」这条纪律在真实链路上等于不存在；回执里的 `pending_segments` 也再分不清
「设计上还没接」与「这次造门漏接」——两种截然不同的故障共用一个字段。

判据：装配齐全时 `pendingSegments()` 必须为空（纪律重新咬合），
未建的段另立名册如实报出；真实调用点不再需要逃生开关。
"""

from __future__ import annotations

import pathlib

import pytest

from neurova.knowledge.foundation.admission import (
    SEGMENT_STATUS,
    SEGMENTS,
    AdmissionRequest,
    KnowledgeAdmissionGate,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

_WIRED = ("identity_resolution", "ontology_adjudication", "conflict_judgement",
          "credibility_record", "lineage")


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _request():
    return AdmissionRequest(
        agentId="default", subjectLabel="甲", predicateTermId="uses", objectTerm="乙",
        content="甲使用乙", assertions=[{"actorType": "user", "actorId": "u1",
                                        "mediumRef": "unit", "statementText": "甲使用乙"}],
    )


class TestPlannedIsNotPending:
    def test_factoryReportsNoPendingSegment(self, store):
        gate = productionAdmissionGate(store, toolVersion="unit")

        assert gate.pendingSegments() == [], (
            "装配齐全的工厂不该再报缺段——报了就说明它报的是尚未建成的段，"
            "而那不是这次装配的缺口")
        assert gate.plannedSegments() == ["indexing"]

    def test_plannedSegmentIsNamedOnTheReceipt(self, store):
        receipt = productionAdmissionGate(store).admit(_request())

        assert receipt.plannedSegments == ["indexing"]
        assert receipt.pendingSegments == []

    def test_genuineGapIsStillNamedAndStillRefused(self, store):
        """漏接一段（不是没建的那段）必须照样拒——这才是「缺段即拒」的原意。"""
        gate = KnowledgeAdmissionGate(store)

        pending = gate.pendingSegments()

        assert set(pending) == set(_WIRED), "裸门漏的是已实现的那五段"
        assert "indexing" not in pending, "尚未建成的段不算这次装配的缺口"
        with pytest.raises(Exception) as excinfo:
            gate.admit(_request())
        assert "indexing" not in str(excinfo.value), (
            "拒绝理由里不该出现尚未建成的段——那会让人以为补上它就放行")

    def test_everySegmentHasADeclaredStatus(self):
        """段名册必须穷举 SEGMENTS：漏登记一段，它就会在两份读数里都消失。"""
        assert set(SEGMENT_STATUS) == set(SEGMENTS)
        assert set(SEGMENT_STATUS.values()) <= {"wired", "planned"}


class TestRealCallSitesNoLongerNeedTheEscapeHatch:
    """放大视角：四个真实调用点此前靠 `allowPendingSegments=True` 绕过纪律。"""

    def test_noneOfTheRealWritersPassesTheEscapeHatch(self):
        root = pathlib.Path(__file__).resolve().parents[3]
        hits = []
        for rel in ("neurova/knowledge/foundation/entry_ledger.py",
                    "neurova/knowledge/foundation/backfill.py",
                    "neurova/knowledge/foundation/reconcile.py",
                    "neurova/knowledge/ontology/rule_engine.py"):
            if "allowPendingSegments" in (root / rel).read_text(encoding="utf-8"):
                hits.append(rel)
        assert hits == [], "真实写入链上不许再出现逃生开关：%s" % hits
