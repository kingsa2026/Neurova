"""同事务批量准入（升级计划 B7 立项后的交付判据）。

立项依据是实测：同事务摊薄 vs 逐条提交 = **+329%**（门槛 30%，
`tests/performance/knowledge/test_admissionThroughput.py`）。本档判的是**语义**，
不比速度：批量只许改变提交次数，不许改变任何一条 finding 的成色。

四条各管一件事，缺一条就是谎：
1. 全批落定后数据在盘上（提交真的发生了）；
2. 坏一条只退它自己——它已经写下的半条也不许留在库里（SAVEPOINT 契约；
   逐段提交的旧形态做不到这条，这正是"批量更原子"的实测证据）；
3. 拒因留名（finding 文本），不外抛、不静默；
4. 单条 `admit` 的默认态一位没动：调用即提交，别的连接立刻读得到。
"""

from __future__ import annotations

import sqlite3

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

AGENT = "batch"


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "admission_batch.db"))
    yield s
    s.close()


def _request(index: int, subject: str = "") -> AdmissionRequest:
    label = subject or f"批量主体{index:03d}"
    obj = f"客体{index:03d}"
    content = f"{label} mentions {obj}"
    return AdmissionRequest(
        agentId=AGENT, tenantId="default", subjectLabel=label,
        predicateTermId="mentions", objectTerm=obj, content=content,
        assertions=[{"actorType": "user", "actorId": "unit",
                     "statementText": content}],
    )


def _rowCount(store) -> int:
    return store._conn.execute(
        "SELECT COUNT(*) FROM knowledge_facts WHERE agent_id = ?", (AGENT,)
    ).fetchone()[0]


class TestAdmitBatchSemantics:
    def test_allValidRequestsLand(self, store):
        gate = productionAdmissionGate(store, toolVersion="unit-batch")
        findings = gate.admitBatch([_request(i) for i in range(3)])

        assert [f["ok"] for f in findings] == [True, True, True], findings
        assert [f["index"] for f in findings] == [0, 1, 2], "finding 必须对齐请求下标"
        assert len({f["fact_id"] for f in findings}) == 3
        assert _rowCount(store) == 3, "作用域出口没提交——批量变成了不落盘"

    def test_emptyBatchReturnsNoFindings(self, store):
        gate = productionAdmissionGate(store, toolVersion="unit-batch")
        assert gate.admitBatch([]) == []
        assert _rowCount(store) == 0

    def test_rejectedTripleIsNamedNotThrown(self, store):
        """谓词与客体都为空 ⇒ 咽喉必填校验拒；finding 留名，其余各条照落。"""
        gate = productionAdmissionGate(store, toolVersion="unit-batch")
        findings = gate.admitBatch([_request(0), AdmissionRequest(
            agentId=AGENT, tenantId="default", subjectLabel="批量主体空",
            predicateTermId="mentions", objectTerm="", content="",
            assertions=[{"actorType": "user", "actorId": "unit", "statementText": "x"}],
        ), _request(2)])

        assert [f["ok"] for f in findings] == [True, False, True], findings
        assert findings[1]["fact_id"] == ""
        assert findings[1]["finding"], "拒因必须留名——空 finding 就是静默失败"
        assert _rowCount(store) == 2

    def test_midWriteFailureRollsBackOnlyThatItem(self, store):
        """坏一条写下的半条也不许留库：血缘段在事实行落地之后炸。

        这条是批量与旧形态的分水岭——逐段提交时，事实行已经落盘，血缘炸了它还在；
        同事务 + 每条自己的 SAVEPOINT 才退得干净。
        """
        gate = productionAdmissionGate(store, toolVersion="unit-batch")
        realAttach = gate._attachLineage

        def boom(lineage, factId, request, deduped):
            if str(request.subjectLabel) == "批量主体001":
                raise RuntimeError("血缘段模拟炸（第二笔）")
            return realAttach(lineage, factId, request, deduped=deduped)

        gate._attachLineage = boom
        try:
            findings = gate.admitBatch([_request(0), _request(1), _request(2)])
        finally:
            gate._attachLineage = realAttach

        assert [f["ok"] for f in findings] == [True, False, True], findings
        assert "血缘段模拟炸" in findings[1]["finding"]
        assert _rowCount(store) == 2, "坏一条的半条没退干净——SAVEPOINT 契约破了"
        labels = {
            r[0] for r in store._conn.execute(
                "SELECT s.canonical_label FROM knowledge_facts f"
                " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
                " WHERE f.agent_id = ?", (AGENT,)).fetchall()
        }
        assert "批量主体001" not in labels, labels
        assert store._conn.in_transaction is False, \
            "批里有被拒条目后事务还开着——脏尾巴会被下一笔写一起提交"

    def test_scopeLeavesNoOpenTransactionBehind(self, store):
        """批后连接必须回到自动提交态：留着半个事务等于把脏尾巴交给下一笔写。"""
        gate = productionAdmissionGate(store, toolVersion="unit-batch")
        gate.admitBatch([_request(0)])
        assert store._conn.in_transaction is False
        assert store._conn.scopeDepth == 0


class TestSingleAdmitDurabilityUnchanged:
    """批量档不许改掉单条路径的落盘时机（这条改动最大的回归面在此）。"""

    def test_singleAdmitIsVisibleToAnotherConnection(self, tmp_path):
        path = str(tmp_path / "single_admit.db")
        store = KnowledgeFactStore(path)
        try:
            gate = productionAdmissionGate(store, toolVersion="unit-single")
            gate.admit(_request(0))
            side = sqlite3.connect(path)
            try:
                visible = side.execute(
                    "SELECT COUNT(*) FROM knowledge_facts WHERE agent_id = ?",
                    (AGENT,)).fetchone()[0]
            finally:
                side.close()
            assert visible == 1, "单条 admit 不再即时提交——默认态被批量档改掉了"
        finally:
            store.close()
