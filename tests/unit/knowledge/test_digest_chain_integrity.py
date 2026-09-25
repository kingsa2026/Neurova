"""链式校验和（工单 023，G02）：改过任何一条断言，必须被发现并指到位置。

链的形状照设计文档 §3 G02 的修正：**每个活动一条链头，链头内逐断言递增**
`seq + digest`，链头另算滚动 `head_digest`。不是"逐事实一条链"——一条事实的多条
断言来自不同活动，把它们串成一条链等于让并发写入互相排队。

判据要说清的是"被发现"而不是"被挡住"：SQLite 里没有密钥，拿到写库权限的人
能重算整条链。本段保证的是**改写必留痕、留痕必指位**，巡检读数可信。
"""

from __future__ import annotations

import hashlib
import time

import pytest

from neurova.knowledge.foundation.digest_chain import ActivityDigestChain
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage import KnowledgeLineageLedger


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def ledger(store):
    return KnowledgeLineageLedger(store, toolVersion="digest-test")


def _assertion(text, actorId="u1"):
    return {"actorType": "user", "actorId": actorId, "statementText": text,
            "mediumRef": "unit:test"}


def _fact(store, factId="fact_a"):
    """断言必须挂在真实事实上（`insertAssertion` 要求主体存在），这里只立一行探针事实。"""
    with store._lock, store._conn:
        key = store.upsertSubject("default", factId)
        return store.upsertFact(agentId="default", subjectKey=key, predicateTermId="probe",
                                objectTerm=factId, content="探针 %s" % factId)


def _fill(store, ledger, factId="fact_a", texts=("第一条", "第二条", "第三条")):
    fid = _fact(store, factId)
    activityId = ledger.openActivity("admit", inputs={"probe": fid})
    for text in texts:
        ledger.attach(fid, [_assertion(text)], activityId=activityId)
    ledger.closeActivity(activityId)
    return activityId


class TestChainIsWrittenAtTheStore:
    def test_v11LandsWithHeadsAndChainColumns(self, store):
        names = {r[0] for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "knowledge_lineage_heads" in names
        cols = {r[1] for r in store._conn.execute(
            "PRAGMA table_info(knowledge_assertions)")}
        assert {"seq", "digest", "prev_digest"} <= cols
        assert int(store._conn.execute("PRAGMA user_version").fetchone()[0]) >= 11

    def test_assertionsChainInWriteOrder(self, store, ledger):
        activityId = _fill(store, ledger)

        with store._lock:
            got = store._conn.execute(
                "SELECT seq, digest, prev_digest FROM knowledge_assertions"
                " WHERE activity_id = ? ORDER BY seq", (activityId,)).fetchall()

        assert [r["seq"] for r in got] == [1, 2, 3], "seq 必须逐条递增且从 1 起"
        assert got[0]["prev_digest"] == "", "链首没有前驱"
        assert got[1]["prev_digest"] == got[0]["digest"], "第二条的前驱是第一条的摘要"
        assert len({r["digest"] for r in got}) == 3, "摘要不得重复"

    def test_eachActivityGetsItsOwnHead(self, store, ledger):
        first = _fill(store, ledger, factId="fact_a", texts=("甲",))
        second = _fill(store, ledger, factId="fact_b", texts=("乙", "丙"))
        chain = ActivityDigestChain(store)

        heads = {h["activity_id"]: h for h in chain.heads()}

        assert set(heads) >= {first, second}
        assert (heads[first]["last_seq"], heads[second]["last_seq"]) == (1, 2)

    def test_chainHeadIsRolledIntoADigest(self, store, ledger):
        activityId = _fill(store, ledger)
        chain = ActivityDigestChain(store)

        head = chain.head(activityId)

        assert head["head_digest"], "链头要自带滚动摘要，不能只记最后一跳"
        assert head["last_digest"] == chain.itemDigests(activityId)[-1]


class TestTamperingIsDetectedAndLocated:
    def test_editingStatementTextBreaksTheChainAtThatRow(self, store, ledger):
        activityId = _fill(store, ledger)

        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_assertions SET statement_text = ?"
                " WHERE activity_id = ? AND seq = 2", ("被改过的第二条", activityId))

        report = ActivityDigestChain(store).verify()

        assert report["ok"] is False
        assert report["break"]["seq"] == 2 and report["break"]["activity_id"] == activityId
        assert report["break"]["reason"] == "正文与哈希不符"

    def test_rewritingTextAndHashTogetherStillBreaks(self, store, ledger):
        """只补 statement_hash 是够的——摘要吃的是哈希，重算要连链一起重算。"""
        activityId = _fill(store, ledger)
        forged = "整条改掉"
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_assertions SET statement_text = ?, statement_hash = ?"
                " WHERE activity_id = ? AND seq = 2",
                (forged, hashlib.sha256(forged.encode("utf-8")).hexdigest()[:16], activityId))

        report = ActivityDigestChain(store).verify()

        assert report["ok"] is False
        assert report["break"]["seq"] == 2
        assert report["break"]["reason"] == "摘要与内容不符"

    def test_droppingAnItemBreaksSeqContinuity(self, store, ledger):
        activityId = _fill(store, ledger)

        with store._lock, store._conn:
            store._conn.execute(
                "DELETE FROM knowledge_assertions WHERE activity_id = ? AND seq = 2",
                (activityId,))

        report = ActivityDigestChain(store).verify()

        assert report["ok"] is False
        assert report["break"]["reason"] == "seq 不连续"

    def test_truncatingTheTailBreaksTheHeadDigest(self, store, ledger):
        activityId = _fill(store, ledger)

        with store._lock, store._conn:
            store._conn.execute(
                "DELETE FROM knowledge_assertions WHERE activity_id = ? AND seq = 3",
                (activityId,))

        report = ActivityDigestChain(store).verify()

        assert report["ok"] is False
        assert report["break"]["reason"] in ("链头序号与实况不符", "链头摘要与滚动结果不符")

    def test_untouchedStoreVerifiesClean(self, store, ledger):
        _fill(store, ledger)

        assert ActivityDigestChain(store).verify()["ok"] is True

    def test_preexistingRowsAreReportedAsUnlinkedNotBroken(self, store, ledger):
        """G02 之前的行：没摘要、没链头——如实报"没上链"，不报"被篡改"。"""
        _fill(store, ledger)
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_assertions SET digest = '', seq = 0, prev_digest = ''")
            store._conn.execute("DELETE FROM knowledge_lineage_heads")

        report = ActivityDigestChain(store).verify()

        assert report["ok"] is True and report["unlinked"] >= 1


class TestRelinkCoversExistingData:
    def test_relinkPutsLegacyRowsOnAChainAndThenDetectsEdits(self, store, ledger):
        activityId = _fill(store, ledger)
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_assertions SET digest = '', seq = 0, prev_digest = ''")

        linked = ActivityDigestChain(store).relinkUnlinked()
        chain = ActivityDigestChain(store)

        assert linked >= 3
        assert chain.verify()["ok"] is True
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_assertions SET statement_text = 'x'"
                " WHERE activity_id = ? AND seq = 1", (activityId,))
        assert chain.verify()["break"]["seq"] == 1

    def test_relinkIsIdempotent(self, store, ledger):
        _fill(store, ledger)
        chain = ActivityDigestChain(store)
        before = chain.verify()

        chain.relinkUnlinked()

        assert chain.verify() == before


class TestBatchPathIsNotSerialized:
    def test_chainingCostIsConstantPerRowNotPerChainLength(self, store, ledger):
        """每行只碰链头一次：链长 500 时追加不比链长 10 时贵一个量级。

        这条取代了"绝对耗时上界"——实测链本身几乎不花钱（500 条：上链 3.74s vs
        不上链 3.96s，同一台机器），大头是咽喉既有的"每断言一次提交"。所以真正
        要守住的是"链不做全链重扫"，而不是墙钟。
        """
        factId = _fact(store, "fact_bulk")

        def _append(times, tag):
            activityId = ledger.openActivity("import")
            started = time.perf_counter()
            for i in range(times):
                ledger.attach(factId, [_assertion("%s 第 %d 条陈述" % (tag, i),
                                                  actorId="u%d" % i)],
                              activityId=activityId)
            return time.perf_counter() - started, activityId

        _short, shortId = _append(10, "短")
        headOfShort = ActivityDigestChain(store).head(shortId)["last_seq"]
        _long, longId = _append(500, "长")
        chain = ActivityDigestChain(store)

        assert headOfShort == 10 and chain.head(longId)["last_seq"] == 500
        assert chain.verify()["ok"] is True
        # 每条的均摊成本不许随链长线性上涨（那才叫"被链串行化拖慢"）
        assert (_long / 500.0) <= (_short / 10.0) * 3.0 + 0.002
