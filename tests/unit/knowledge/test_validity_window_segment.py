"""咽喉的时效窗口段：`AdmissionRequest.validFrom/validUntil` 必须真落库。

断点的形状：入参契约里有两个窗口字段（`admission.py:53-54`），且底座表上也有
`valid_from` / `valid_until` 两列（`knowledge_facts.py:75-76`）——**只有落库那一跳没有**：
`upsertFact` 不接这两个参数，`admit()` 也从不读它们。于是生产库里两列全 NULL
（2026-09-21 审计：`supersedes` / `valid_from` / `valid_until` 全 0 行），
`conflict_judge` 的 temporal 分类与 `expireDueFacts()` 双双失去输入，
"写出去没人读"，正是设计文档 §5 要灭的断点。

判据：声明过窗口的 admit，事实行上必须读得到同一个瞬时（归一为 UTC ISO）；
窗口不是"记账装饰"——到了 `validUntil` 之后，该事实必须退出检索候选。
"""

from __future__ import annotations

import datetime

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.temporal_facts import TemporalFactReader

_UTC = datetime.timezone.utc


def _presentUtc() -> datetime.datetime:
    """唯一取时口径：与写入端 `recorded_at` 同源（都取系统时钟）。

    用例自造一个写死的瞬时当"此刻"，就是给时间开了第二份事实源：写侧照真时钟落
    `recorded_at`，读侧却拿那个更早的瞬时当上界，过了那一刻本文件必红。上一版把
    `2026-09-21T12:00Z` 写死成"此刻"，实际绿灯窗口只有 45 分钟——CI 上跑的正是
    这个时间炸弹，不是被测行为坏了。窗口一律相对"此刻"声明，读侧 as-of 在断言处
    重新取时（必然不早于写入瞬时），用例从此与墙钟日期无关。
    """
    return datetime.datetime.now(_UTC)


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _admit(store, obj, *, validFrom=None, validUntil=None, content=None):
    gate = productionAdmissionGate(store, toolVersion="unit")
    text = content or ("成本护栏落在 %s" % obj)
    return gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="成本护栏", predicateTermId="governs",
        objectTerm=obj, content=text, validFrom=validFrom, validUntil=validUntil,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": text}],
    )).factId


class TestWindowIsPersisted:
    def test_declaredWindowLandsOnTheRow(self, store):
        until = _presentUtc() + datetime.timedelta(days=10)
        factId = _admit(store, "0.8", validUntil=until.isoformat())

        row = store.fact(factId)

        assert row["valid_until"] == until.isoformat(), (
            "调用方声明了 validUntil，事实行上却是 NULL——咽喉收了字段却没落库")

    def test_validFromIsPersistedAndNormalised(self, store):
        start = _presentUtc() - datetime.timedelta(days=1)
        factId = _admit(store, "0.9", validFrom=start.isoformat())

        assert store.fact(factId)["valid_from"] == start.isoformat()

    def test_nonUtcOffsetIsNormalisedToUtc(self, store):
        """时效比较的是瞬时：混着 +08:00 写进去，文本序会把"已到期"读成"未到期"。"""
        shifted = _presentUtc().astimezone(
            datetime.timezone(datetime.timedelta(hours=8)))
        factId = _admit(store, "0.7", validUntil=shifted.isoformat())

        assert store.fact(factId)["valid_until"] == shifted.astimezone(
            datetime.timezone.utc).isoformat()


class TestWindowActuallyGates:
    def test_closedWindowLeavesTheRetrievalSurface(self, store):
        """窗口不是记账装饰：过期后该事实必须退出候选，否则"窗口"仍是个没人读的字段。"""
        factId = _admit(store, "0.5",
                        validUntil=(_presentUtc() - datetime.timedelta(days=1)).isoformat())

        hits = TemporalFactReader(store, agentId="default").forQuery("成本护栏", now=_presentUtc())

        assert factId not in [h["id"] for h in hits]
        assert store.fact(factId)["status"] == "active", "读面过滤与生命周期状态各按自己口径判"

    def test_openWindowStaysVisible(self, store):
        factId = _admit(store, "0.6",
                        validUntil=(_presentUtc() + datetime.timedelta(days=30)).isoformat())

        assert factId in [h["id"] for h in TemporalFactReader(
            store, agentId="default").forQuery("成本护栏", now=_presentUtc())]

    def test_validFromInTheFutureIsNotYetEffective(self, store):
        factId = _admit(store, "0.9",
                        validFrom=(_presentUtc() + datetime.timedelta(days=5)).isoformat())

        assert factId not in [h["id"] for h in TemporalFactReader(
            store, agentId="default").forQuery("成本护栏", now=_presentUtc())]


class TestDedupeDoesNotDropTheWindow:
    def test_sameContentReplayBackfillsTheMissingWindow(self, store):
        """同内容重放折回旧行时，声明过窗口就要补上——否则同一句话第一次带窗口、
        第二次不带，行为随调用顺序漂移。"""
        until = (_presentUtc() + datetime.timedelta(days=3)).isoformat()
        first = _admit(store, "0.4", content="成本护栏取同一个取值")
        second = _admit(store, "0.4", content="成本护栏取同一个取值", validUntil=until)

        assert first == second, "同内容必须折回同一行（004 口径）"
        assert store.fact(first)["valid_until"] == until

    def test_replayBackfillNormalisesOffsetLikeTheFreshInsertPath(self, store):
        """折回补窗口与新建落窗口必须出自同一口径（都归一为 UTC 瞬时）。

        两条路径都在 `fillValidityWindow` 里写，但折回那条此前把调用方原样的字符串
        直接喂进去，绕过了新建路径用的归一函数。后果是同一句事实的 `valid_until`
        随"哪条路径先写"而变：+08:00 的 `20:00` 与 UTC 的 `12:00` 是同一瞬时，
        存成字面量之后，读面的文本序比较会把"已到期"读成"未到期"——时效窗口
        既非唯一瞬时，也就谈不上咬合。
        """
        shifted = datetime.datetime(2031, 6, 5, 20, 0, tzinfo=datetime.timezone(
            datetime.timedelta(hours=8)))
        text = "限额护栏取同一个取值"
        first = _admit(store, "0.2", content=text)
        second = _admit(store, "0.2", content=text, validUntil=shifted.isoformat())

        assert first == second
        assert store.fact(first)["valid_until"] == shifted.astimezone(
            datetime.timezone.utc).isoformat(), (
            "折回路径没走归一：同一瞬时被存成两种字面量，窗口读面按文本序判就会读错")
