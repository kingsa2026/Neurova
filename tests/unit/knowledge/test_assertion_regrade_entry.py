"""存量断言归正入口：把"上链之前写下的行"补上链并落校验结论。

病灶（审计 2026-09-21 §3 / §6.6 / Issue #75）：`attest()` 已具备逐条裁决并回写
`verification_state` 的能力，但**存量行**没被处置——库里 92/92 恒 `unverified`，
其中大部分是上链机制（`_SCHEMA_V11`）之前写的（`digest` 为空）。上一批把这件
事登记为"运维动作，未执行"，于是读数上它们至今还是"没人验过"。

判据（动作必须真闭环，且不许把没依据的事报成验过）：

1. 存量行（`digest=''`）先补链位再裁决：`relinkUnlinked()` 清零该活动的链头后重排，
   结论必须是 `verified` 而不是留在 `unverified`。
2. **未上链且补不了的行**（没有活动的行）保持 `unverified`——那一维确实没依据，
   不许为了读数好看给个 `verified`。
3. 混合态活动（部分有摘要）不重排：说明链被削过，该由巡检报断裂。
4. 入口是幂等的：跑第二遍结论与第一遍逐条相同。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from neurova.knowledge.foundation.digest_chain import ActivityDigestChain
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage import KnowledgeLineageLedger


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _seedLegacyRows(store, ledger, activityId, count=3):
    """模拟"上链机制之前写下的行"：有活动、有正文、无链位、结论未定。"""
    key = store.upsertSubject("default", "存量主体")
    factId = store.upsertFact(agentId="default", subjectKey=key, predicateTermId="probe",
                              objectTerm="o", content="正文")
    ledger.attach(factId, [{"actorType": "user", "actorId": "u%d" % i,
                            "statementText": "第 %d 条说法" % i, "mediumRef": "legacy"}
                           for i in range(count)], activityId=activityId)
    with store._lock, store._conn:
        store._conn.execute(
            "UPDATE knowledge_assertions SET digest = '', seq = 0, prev_digest = ''"
            " WHERE activity_id = ?", (activityId,))
        store._conn.execute("DELETE FROM knowledge_lineage_heads WHERE activity_id = ?",
                            (activityId,))
    return factId


def _states(store, activityId=None):
    sql = ("SELECT verification_state FROM knowledge_assertions"
           + (" WHERE activity_id = ?" if activityId else "") + " ORDER BY asserted_at, assertion_id")
    params = (activityId,) if activityId else ()
    with store._lock:
        return [r["verification_state"] for r in store._conn.execute(sql, params).fetchall()]


class TestRegradeIsProvidedAsAnOpsEntry:
    def test_moduleExposesRegrade(self):
        from neurova.cognitive_layers.memory_layer import pollution_purge  # noqa: F401
        from neurova.knowledge.foundation import digest_chain

        assert hasattr(digest_chain.ActivityDigestChain, "relinkUnlinked")
        assert hasattr(digest_chain.ActivityDigestChain, "attest")


class TestLegacyRowsBecomeVerified:
    def test_relinkThenAttestTurnsLegacyRowsVerified(self, store):
        ledger = KnowledgeLineageLedger(store, toolVersion="regrade-test")
        activityId = ledger.openActivity("import", basis="legacy")
        _seedLegacyRows(store, ledger, activityId)
        chain = ActivityDigestChain(store)
        assert set(_states(store, activityId)) == {"unverified"}, "前提：先是不确定态"

        linked = chain.relinkUnlinked()
        report = chain.attest()

        assert linked == 3, "存量行必须被补上链（%d）" % linked
        assert _states(store, activityId) == ["verified"] * 3, (
            "补链后裁决仍停在 unverified：动作没闭环")
        assert report["unverified"] == 0 and report["verified"] == 3

    def test_rowsWithoutActivityStayUnverified(self, store):
        """没有活动的行没有链位依据，不许为了让读数好看给它一个 verified。"""
        key = store.upsertSubject("default", "无活动主体")
        factId = store.upsertFact(agentId="default", subjectKey=key, predicateTermId="probe",
                                  objectTerm="o", content="正文")
        # 上链之前的旧行可以没有活动（`activity_id` 为空）——那一维没依据，
        # 正是"不许为了让读数好看给它 verified"的反面样本。
        store.insertAssertion(factId, actorType="user", actorId="u", mediumRef="legacy",
                              statementText="无活动的说法", statementHash="0" * 16)
        chain = ActivityDigestChain(store)

        chain.relinkUnlinked()
        report = chain.attest()

        assert report["verified"] == 0 and report["unverified"] == 1, (
            "无活动行的结论必须是 unverified（无依据），不是 verified")

    def test_mixedStateActivityIsLeftToTheInspector(self, store):
        """混合态说明链被削过：不许用重排把它洗成一个新的自证。"""
        ledger = KnowledgeLineageLedger(store, toolVersion="regrade-test")
        activityId = ledger.openActivity("import", basis="legacy")
        factId = _seedLegacyRows(store, ledger, activityId, count=3)
        with store._lock, store._conn:
            first = store._conn.execute(
                "SELECT assertion_id FROM knowledge_assertions WHERE activity_id = ?"
                " ORDER BY asserted_at, assertion_id LIMIT 1", (activityId,)).fetchone()
            store._conn.execute(
                "UPDATE knowledge_assertions SET digest = 'deadbeef', seq = 1"
                " WHERE assertion_id = ?", (first["assertion_id"],))
        chain = ActivityDigestChain(store)

        linked = chain.relinkUnlinked()
        report = chain.verify(activityId)

        assert linked == 0, "混合态不许被重排——那会把削链洗成自证"
        assert report["ok"] is False, "削过的链必须由巡检报出来"


class TestRegradeIsIdempotent:
    def test_secondRunYieldsTheSameVerdicts(self, store):
        ledger = KnowledgeLineageLedger(store, toolVersion="regrade-test")
        activityId = ledger.openActivity("import", basis="legacy")
        _seedLegacyRows(store, ledger, activityId)
        chain = ActivityDigestChain(store)

        chain.relinkUnlinked()
        first = chain.attest()
        second = chain.attest(activityId)

        assert first["verification"] == second["verification"], "重跑结论漂移"
        assert _states(store, activityId) == ["verified"] * 3


class TestOpsEntryExists:
    def test_scriptIsPresentAndDryRunByDefault(self):
        import io

        script = (Path(__file__).resolve().parents[3] / "scripts"
                  / "knowledge_assertion_regrade.py")
        assert script.is_file(), "存量断言归正的运维入口不存在"
        text = io.open(script, encoding="utf-8").read()
        assert "--apply" in text, "落手必须显式开关"
        assert "dry" in text.lower(), "默认必须是预报"
