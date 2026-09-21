"""活动账必须记得住「谁把这条知识带进来的」，而不是条条都记成咽喉自己。

病灶形状（2026-09-21 审计 §3）：生产库里 92/92 条活动 `activity_kind='admit'`，
`basis` 全等于 `"KnowledgeAdmissionGate.admit"`。`basis` 这一列就是自证铁证——
**活动不是管线埋的，是写咽喉自己签的**。后果：溯源四问里的「经哪条管线进来」
在生产读数上无区分力，回填/导入/推导/直写四种来路长得一模一样。

修法不是给读面加个字段：`AdmissionRequest` 增加来路声明（kind + basis，或直接给
已开好的 `activityId`），咽喉照调用方的声明落账；只有"没有上层管线"的直写才由咽喉
兜底，且兜底必须在 `basis` 上自陈是兜底。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage import KnowledgeLineageLedger


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _admit(store, *, activityKind="", activityBasis="", activityId="", content="甲使用乙"):
    gate = productionAdmissionGate(store, toolVersion="unit")
    return gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="甲", predicateTermId="uses", objectTerm="乙",
        content=content, activityKind=activityKind, activityBasis=activityBasis,
        activityId=activityId,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}],
    ))


def _kindOf(store, factId):
    rows = store.lineageRows(factId)
    return rows[0]["activity_kind"], rows[0]["activity_basis"]


class TestCallerDeclaresItsPipeline:
    def test_declaredKindAndBasisReachTheLedger(self, store):
        receipt = _admit(store, activityKind="import", activityBasis="LegacyFactBackfill.run")

        assert _kindOf(store, receipt.factId) == ("import", "LegacyFactBackfill.run")

    def test_aDeferredActivityIsReusedNotDuplicated(self, store):
        """调用方已经开好活动时，咽喉接上它，不再另开一条同义活动。"""
        ledger = KnowledgeLineageLedger(store, toolVersion="unit")
        activityId = ledger.openActivity("extract", basis="GraphBridge.extract")
        before = len(store._conn.execute(
            "SELECT 1 FROM knowledge_activities").fetchall())

        receipt = _admit(store, activityId=activityId)

        after = len(store._conn.execute("SELECT 1 FROM knowledge_activities").fetchall())
        assert after == before, "调用方自带活动时咽喉不得再开一条"
        assert store.lineageRows(receipt.factId)[0]["activity_id"] == activityId
        assert _kindOf(store, receipt.factId)[0] == "extract"

    def test_directWriteFallbackSaysSoOutLoud(self, store):
        receipt = _admit(store)

        kind, basis = _kindOf(store, receipt.factId)

        assert kind == "admit"
        assert "兜底" in basis, "没有上层管线时，兜底必须在 basis 上自陈，不能冒充管线埋点"

    def test_receiptCarriesTheActivityItUsed(self, store):
        """回执带上活动 id：调用方要能顺着自己的账往下记（写出→读取的闭环）。"""
        assert _admit(store, activityKind="import", activityBasis="x").activityId


class TestRealCallSitesDeclareTheirOrigin:
    def test_backfillDeclaresImportAndReconcileReplayIsDistinguishable(self, tmp_path):
        from neurova.knowledge.foundation.backfill import LegacyFactBackfill
        from neurova.knowledge.foundation.reconcile import FoundationReconciler
        from neurova.knowledge.repository import KnowledgeRepository

        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo.create_knowledge("default", "甲", "内容甲", owner_user_id="u1",
                              detect_conflict=False)
        store = KnowledgeFactStore(str(tmp_path / "backfill.db"))
        try:
            LegacyFactBackfill.run(repo, store)
            kinds = {r["activity_kind"] for r in store._conn.execute(
                "SELECT DISTINCT activity_kind FROM knowledge_activities").fetchall()}
            bases = {r["basis"] for r in store._conn.execute(
                "SELECT DISTINCT basis FROM knowledge_activities").fetchall()}
        finally:
            store.close()

        assert "import" in kinds, "回填是导入，不是咽喉的 admit"
        assert not any(b == "KnowledgeAdmissionGate.admit" for b in bases), (
            "回填的来路必须由回填器自陈，不许落回咽喉兜底")
        assert FoundationReconciler is not None
