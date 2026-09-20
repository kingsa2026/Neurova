"""读面合一（工单 019b-3）：接入治理层的方式是**富化**，不是再开一个池子。

011 已经用真数据否证过"两池按秩交织"：同一份内容在两个池子里各算一票，
弱事实凭 BM25 短文本优势挤掉强叙述命中。所以这一片不换尺子、不动排序——
底座只把治理字段挂到已经排好序的命中上，并留下注入回流的内键。

顺带了结 A→B→A：内容唯一索引从"每 agent 每内容一行"改成"每 agent 每内容一行**活着的**"，
改回原样才算新的一次主张；被取代的旧行留档。
"""

from __future__ import annotations

import pytest

from neurova.core.content_identity import normalized_key
from neurova.knowledge.foundation.backfill import LegacyFactBackfill
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.entry_ledger import EntryLedger
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.read_surface import attachGovernance, recordHitsAsInjection
from neurova.knowledge.foundation.reconcile import FoundationReconciler
from neurova.knowledge.repository import KnowledgeRepository

ENV_FLAG = "NEUROVA_KB_NARRATIVE_STORE"
_BODY_A = "蜂群并发成本护栏要限流与记账两段。" * 5
_BODY_B = "检索评测台架必须先冻结基线再动读路径。" * 5
_BODY_C = "反思反哺链分软通道与硬拦截两条。" * 5


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "facts.db"))
    yield s
    s.close()


def _request(content, **over):
    payload = dict(agentId="default", subjectLabel="某条目", recordKind="narrative",
                   objectTerm="k-x", content=content,
                   assertions=[{"actorType": "user", "actorId": "u1",
                                "mediumRef": "import:note.txt", "statementText": "某条目"}])
    payload.update(over)
    return AdmissionRequest(**payload)


class TestContentDedupeIsNotAnOrderFunction:
    """内容去重必须与裁决顺序无关——这条守的是刚试过又撤回去的那一步。

    试过把 (agent, content_key) 唯一索引改成"只管 active 行"，让 A→B→A 算新一代主张。
    实测代价：回放里某行被自动取代之后，同内容不再折叠而是另开一行，
    静态预测与实跑当场分叉（130 行：预测 92、实跑 102），也就是把去重做成了裁决顺序的函数。
    代际语义要立，得先让预测侧看得懂它，或者让"哪条生效"离开唯一索引。已登记为开洞。

    同一个洞在条目面的另一张嘴（019b-4b 记下）：两条正文相同的条目共享一行，
    其中一条改了正文就会把那条共享行判成 superseded，另一条因此查不到 active 行、
    投影报分叉且不收敛（`_load` 的 ERROR 会点名它）。修法不在这里补一次取代，
    也不是让空出来的行被别条认领——那要等代际语义与预测侧一起立起来。
    """

    def test_supersededRowStillAbsorbsIdenticalContent(self, store):
        gate = productionAdmissionGate(store, toolVersion="unit")
        first = gate.admit(_request(_BODY_A), allowPendingSegments=True)
        gate.admit(_request(_BODY_B), allowPendingSegments=True)
        back = gate.admit(_request(_BODY_A), allowPendingSegments=True)

        assert back.factId == first.factId, "同内容只能有一条行，否则去重随裁决漂移"
        assert store.factCount() == 2

    def test_entryIdSurvivesTheContentKeyRewrite(self, store):
        """客体换成内容键之后，"这是哪条条目"只剩 source_turn_id 一个落点，咽喉必须兜住。"""
        gate = productionAdmissionGate(store, toolVersion="unit")
        receipt = gate.admit(_request(_BODY_A, objectTerm="entry-42"),
                             allowPendingSegments=True)

        assert store.fact(receipt.factId)["source_turn_id"] == "entry:entry-42"
        assert store.narrativeFactForEntry("entry-42")["fact_id"] == receipt.factId

class TestEnrichmentNotInterleaving:
    def test_GovernanceRidesOntoExistingOrder(self, store):
        gate = productionAdmissionGate(store, toolVersion="unit")
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="蜂群并发成本护栏", recordKind="narrative",
            objectTerm="entry-1", content=_BODY_A,
            assertions=[{"actorType": "user", "actorId": "u1", "mediumRef": "import:note.txt",
                         "statementText": "蜂群并发成本护栏"}]), allowPendingSegments=True)
        legacy = [{"knowledge_id": "entry-1", "title": "蜂群", "content": _BODY_A},
                  {"knowledge_id": "ghost", "title": "无治理行", "content": "别的正文"}]

        hits, lineage = attachGovernance(store, legacy)

        assert [h["knowledge_id"] for h in hits] == ["entry-1", "ghost"], "合一不得改命中顺序"
        assert hits[0]["lineage_id"] and hits[0]["evidence_state"] == "evidenced"
        assert hits[0]["confidence"] == pytest.approx(0.50)
        assert hits[1].get("lineage_id") is None, "查不到治理行就原样放行，不编造"
        assert lineage == [hits[0]["lineage_id"]]

    def test_InjectionCountsLandOnTheFacts(self, store):
        gate = productionAdmissionGate(store, toolVersion="unit")
        receipt = gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="检索台架", recordKind="narrative",
            objectTerm="entry-2", content=_BODY_B,
            assertions=[{"actorType": "user", "actorId": "u1", "mediumRef": "m",
                         "statementText": "检索台架"}]), allowPendingSegments=True)
        hits, _ = attachGovernance(store, [{"knowledge_id": "entry-2", "content": _BODY_B}])

        assert recordHitsAsInjection(store, hits) == 1
        assert store.fact(receipt.factId)["injected_count"] == 1

    def test_OffGateLegacyPathUnchanged(self, tmp_path, monkeypatch):
        """关闸时读面根本不被调用——旧行为不是"尽量不变"，是根本没走到新代码。"""
        monkeypatch.delenv("NEUROVA_KB_FACT_SURFACE", raising=False)
        monkeypatch.delenv(ENV_FLAG, raising=False)
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo.create_knowledge("default", "闸外条目", _BODY_C, owner_user_id="u1")
        from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter

        retriever = KnowledgeRetrieverAdapter(repo)
        assert retriever._surface() is None


class TestReconcileStillAgrees:
    def test_BackfillAndReconcileStillMatch(self, store, tmp_path):
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo.create_knowledge("default", "甲", _BODY_A, owner_user_id="u1")
        repo.create_knowledge("default", "乙", _BODY_B, owner_user_id="u2")
        report = FoundationReconciler.reconcile(repo, str(tmp_path / "replay.db"))

        LegacyFactBackfill.run(repo, store)
        assert store.factCount() == report["actual"]["facts"]
        assert store.subjectCount() == report["actual"]["subjects"]
        assert EntryLedger(store).verifyProjection(repo._items) == []

