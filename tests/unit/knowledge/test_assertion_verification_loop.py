"""校验要闭环：断言写出去是 `unverified`，必须有人把它变成可读的结论。

病灶形状（2026-09-21 审计 §3、§5.5）：`knowledge_assertions.verification_state`
有列、有默认值、**没有任何写入者也没有任何校验者**，生产 92/92 条恒为 `unverified`；
`ActivityDigestChain.verify()` 早就会逐条重算摘要并定位篡改点，但它只报不改，
结论从不落回那一列——"记账齐全、校验从不闭环"。

闭环的形状（写入 → 校验 → 回写 → 再读出）：写断言时是 `unverified`；
校验器逐条给出裁决并**回写**该列；读面（血缘视图 / 巡检端点）能读出分布。
失败必须是 `failed` 而不是留在 `unverified`——"没验过"与"验过没过"是两件事。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.digest_chain import ActivityDigestChain
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage import KnowledgeLineageLedger

_STATES = ("unverified", "verified", "failed")


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def ledger(store):
    return KnowledgeLineageLedger(store, toolVersion="attest-test")


def _seed(store, ledger, texts=("第一条", "第二条")):
    key = store.upsertSubject("default", "被引用的事实")
    factId = store.upsertFact(agentId="default", subjectKey=key, predicateTermId="probe",
                              objectTerm="o", content="正文")
    activityId = ledger.openActivity("admit", basis="unit:attest")
    for i, text in enumerate(texts):
        ledger.attach(factId, [{"actorType": "user", "actorId": "u%d" % i,
                                "statementText": text, "mediumRef": "unit:test"}],
                      activityId=activityId)
    return activityId


def _states(store, activityId):
    with store._lock:
        return [r["verification_state"] for r in store._conn.execute(
            "SELECT verification_state FROM knowledge_assertions"
            " WHERE activity_id = ? ORDER BY seq", (activityId,)).fetchall()]


class TestStateIsWrittenAndReadable:
    def test_freshAssertionIsUnverified(self, store, ledger):
        activityId = _seed(store, ledger)

        assert _states(store, activityId) == ["unverified", "unverified"]
        assert set(_states(store, activityId)) <= set(_STATES)

    def test_attestWritesBackAVerdictForEveryRow(self, store, ledger):
        activityId = _seed(store, ledger)

        report = ActivityDigestChain(store).attest()

        assert _states(store, activityId) == ["verified", "verified"]
        assert report["verified"] == 2 and report["failed"] == 0

    def test_theVerdictIsReadableThroughTheLineageView(self, store, ledger):
        activityId = _seed(store, ledger)
        ActivityDigestChain(store).attest()
        factId = store._conn.execute(
            "SELECT fact_id FROM knowledge_assertions WHERE activity_id = ? LIMIT 1",
            (activityId,)).fetchone()["fact_id"]

        hops = ledger.traceLineage(factId)

        assert {h["verification_state"] for h in hops} == {"verified"}


class TestTamperingIsGradedNotJustReported:
    def test_editedRowIsGradedFailed(self, store, ledger):
        activityId = _seed(store, ledger)
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_assertions SET statement_text = ?"
                " WHERE activity_id = ? AND seq = 2", ("被改过的第二条", activityId))

        report = ActivityDigestChain(store).attest()

        assert _states(store, activityId) == ["verified", "failed"]
        assert report["failed"] == 1 and report["ok"] is False

    def test_repairedRowGetsRegradedOnTheNextRound(self, store, ledger):
        """再写入：修好之后重新校验要能回到 verified，否则这一列只降不升。"""
        activityId = _seed(store, ledger)
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_assertions SET statement_text = ?"
                " WHERE activity_id = ? AND seq = 2", ("被改过的第二条", activityId))
        chain = ActivityDigestChain(store)
        assert chain.attest()["failed"] == 1

        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_assertions SET statement_text = ?"
                " WHERE activity_id = ? AND seq = 2", ("第二条", activityId))
        report = chain.attest()

        assert _states(store, activityId) == ["verified", "verified"]
        assert report["ok"] is True

    def test_unknownStateIsRejectedAtTheStore(self, store, ledger):
        activityId = _seed(store, ledger)
        assertionId = store._conn.execute(
            "SELECT assertion_id FROM knowledge_assertions WHERE activity_id = ?",
            (activityId,)).fetchone()["assertion_id"]

        with pytest.raises(ValueError, match="verification_state"):
            store.setAssertionVerification(assertionId, "probably-fine")


class TestReadSideClosesTheLoop:
    def test_verifyReportCarriesTheDistribution(self, store, ledger):
        _seed(store, ledger)

        report = ActivityDigestChain(store).verify()

        assert report["verification"] == {"unverified": 2, "verified": 0, "failed": 0}

    def test_attestIsReachableFromTheGovernanceLoadPath(self, tmp_path, monkeypatch):
        """校验器必须有真实调用方，否则它自己就是下一个"从不闭环"。

        调用点选条目仓库的装载路径：装载即对齐治理层（`_syncEntryGovernance`），
        同一处把断言校验也跑掉，读数与数据同批刷新。
        """
        from neurova.knowledge.repository import KnowledgeRepository

        kb = KnowledgeRepository(str(tmp_path / "kb"))
        kb.create_knowledge("default", "甲", "内容甲", owner_user_id="u1",
                            detect_conflict=False)

        with kb._entryLedger() as ledger_:
            store = ledger_._store
            rows = store._conn.execute(
                "SELECT DISTINCT verification_state FROM knowledge_assertions").fetchall()
            states = {r["verification_state"] for r in rows}

        assert states == {"verified"}, (
            "装载路径必须把校验跑完并回写；恒为 unverified 就是从不闭环的原地复活")
