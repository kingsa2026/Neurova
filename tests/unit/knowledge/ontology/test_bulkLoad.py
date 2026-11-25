# -*- coding: utf-8 -*-
"""U3 批量装载契约：`ontology/bulk_load.bulkLoadFacts`。

判据全部走真装配（真 `KnowledgeFactStore` + `productionAdmissionGate` 真咽喉），
不打桩业务对象：
  * 逐行仍经唯一写咽喉 `admit` 落库，批量只是编排，不开第二条写路径；
  * 任一行违规 → 整批零落盘（对齐 pipeline dry-run 整批拒绝语义）；
  * dry-run 零写入并给逐行预检摘要；
  * 第二段出现异常行 → 立即停批，整批经 foundation 既有 batchScope（SAVEPOINT）
    事务回滚，最终回执仍判 failed，不留半截数据装成功。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.bulk_load import bulkLoadFacts
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def gate(store):
    return productionAdmissionGate(store, toolVersion="unit")


def _row(subject, predicate, obj, **kw):
    row = {"agentId": "default", "subjectLabel": subject,
           "predicateTermId": predicate, "objectTerm": obj,
           "content": "%s %s %s" % (subject, predicate, obj)}
    row.update(kw)
    return row


def _validRows(count):
    return [_row("人员-%02d" % index, "memberOf", "团队-%d" % (index % 3))
            for index in range(count)]


def _registerDomainTerms(store):
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "person", "kind": "concept"},
        {"termId": "city", "kind": "concept"},
        {"termId": "lives_in", "kind": "relation", "domain": ["person"],
         "rangeTerms": ["city"]},
        {"termId": "married_to", "kind": "relation", "domain": ["person"],
         "rangeTerms": ["person"], "cardinality": 1},
    ])
    return registry


def _typedSubject(store, registry, label, termId):
    key = store.upsertSubject("default", label)
    registry.assignSubjectType(key, termId)
    return key


def _tableCounts(store):
    return {table: store.queryReadOnly(
        "SELECT COUNT(*) AS n FROM %s" % table)[0]["n"]
        for table in ("knowledge_facts", "knowledge_subjects", "ontology_terms")}


def _activeFactCount(store):
    return store.queryReadOnly(
        "SELECT COUNT(*) AS n FROM knowledge_facts WHERE status = 'active'")[0]["n"]


class TestBulkLoadHappyPath:
    def test_fiftyValidRows_allAdmitted_withFiveBatchCallbacks(self, store, gate):
        calls = []

        receipt = bulkLoadFacts(store, _validRows(50), batchSize=10, dryRun=False,
                                onProgress=lambda done, total: calls.append((done, total)))

        assert receipt["total"] == 50
        assert receipt["admitted"] == 50
        assert receipt["failed"] == []
        assert receipt["dryRun"] is False
        assert calls == [(10, 50), (20, 50), (30, 50), (40, 50), (50, 50)], \
            "按批回调：批数 = ceil(50/10) = 5，done 为已处理行数"
        assert store.factCount() == 50, "50 行全部经咽喉落库"


class TestWholeBatchRejection:
    def test_violationAtRow45_zeroWrites_failedNamesIndexAndRule(self, store, gate):
        registry = _registerDomainTerms(store)
        _typedSubject(store, registry, "甲", "city")  # lives_in 定义域 person → 违规
        rows = _validRows(50)
        rows[45] = _row("甲", "lives_in", "某某市")
        before = _tableCounts(store)

        receipt = bulkLoadFacts(store, rows, batchSize=10, dryRun=False)

        assert receipt["admitted"] == 0, "任一行违规 → 整批零落盘，不许只回滚违规所在批"
        assert receipt["dryRun"] is False
        assert [f["index"] for f in receipt["failed"]] == [45]
        assert "本体校验未过" in receipt["failed"][0]["reason"]
        assert "domain" in receipt["failed"][0]["reason"]
        assert _tableCounts(store) == before, "facts/subjects/terms 相关表计数一概不变"


class TestDryRun:
    def test_dryRun_reportsPerRowPrecheck_andWritesNothing(self, store, gate):
        registry = _registerDomainTerms(store)
        _typedSubject(store, registry, "甲", "city")
        rows = _validRows(20)
        rows[7] = _row("甲", "lives_in", "某某市")
        before = _tableCounts(store)

        receipt = bulkLoadFacts(store, rows, batchSize=5, dryRun=True)

        assert _tableCounts(store) == before, "dry-run 只跑第一段，零写入"
        assert receipt["dryRun"] is True
        assert receipt["admitted"] == 0
        assert [f["index"] for f in receipt["failed"]] == [7]
        precheck = receipt["precheck"]
        assert len(precheck) == 20, "逐行预检摘要"
        assert all(entry["verdict"] == "pass"
                   for index, entry in enumerate(precheck) if index != 7)
        assert precheck[7]["verdict"] == "violation"
        assert any("domain" in message for message in precheck[7]["violations"])


class TestEmptyRows:
    def test_emptyRows_emptyReceipt_andNoCallbacks(self, store, gate):
        calls = []

        receipt = bulkLoadFacts(store, [], batchSize=10, dryRun=False,
                                onProgress=lambda done, total: calls.append((done, total)))

        assert receipt == {"total": 0, "admitted": 0, "failed": [], "dryRun": False}
        assert calls == [], "空 rows 直接返回空回执，不调回调"
        assert store.factCount() == 0

    def test_emptyRowsDryRun_emptyPrecheck(self, store, gate):
        receipt = bulkLoadFacts(store, [], dryRun=True)

        assert receipt["total"] == 0
        assert receipt["admitted"] == 0
        assert receipt["failed"] == []
        assert receipt["precheck"] == []


class TestMalformedRows:
    def test_missingField_unknownKey_nonDictRow_failExplicitly_notSilent(self, store, gate):
        rows = [_validRows(1)[0],
                {"agentId": "default", "subjectLabel": "乙"},
                dict(_row("丙", "memberOf", "团队"), mysteryField="x"),
                "不是 dict 的一行"]

        receipt = bulkLoadFacts(store, rows, batchSize=4, dryRun=False)

        assert receipt["total"] == 4
        assert receipt["admitted"] == 0, "任一行不合法 → 整批零落盘"
        assert {f["index"] for f in receipt["failed"]} == {1, 2, 3}
        reasons = {f["index"]: f["reason"] for f in receipt["failed"]}
        assert "缺必填字段" in reasons[1], "缺字段须显式点名，不静默吞"
        assert "mysteryField" in reasons[2], "未知字段须显式点名，不静默吞"
        assert "dict" in reasons[3], "非 dict 行须显式点名，不静默吞"
        assert store.factCount() == 0

    def test_batchSizeBelowOne_raises(self, store, gate):
        with pytest.raises(ValueError, match="batchSize"):
            bulkLoadFacts(store, _validRows(2), batchSize=0, dryRun=False)


class TestPhaseTwoAtomicRollback:
    def test_withinBatchCardinalityConflict_stopsAndRollsBackWholeBatch(self, store, gate):
        """干跑逐行只读、看不见批内先后依赖：第 0 行落库后，第 1 行才在咽喉
        校验段撞上 cardinality=1。此时必须立即停批，整批经 batchScope 事务
        回滚——回执仍判 failed，零落盘，不留半截事实/断言/推导装成功。"""
        registry = _registerDomainTerms(store)
        _typedSubject(store, registry, "甲", "person")
        rows = [_row("甲", "married_to", "乙", qualifier={"env": "x"}),
                _row("甲", "married_to", "丙", qualifier={"env": "x"})]
        before = store.factCount()

        receipt = bulkLoadFacts(store, rows, batchSize=2, dryRun=False)

        assert receipt["admitted"] == 0, "整批回滚后不留半截数据装成功"
        assert [f["index"] for f in receipt["failed"]] == [1]
        assert "cardinality" in receipt["failed"][0]["reason"]
        assert "回滚" in receipt["failed"][0]["reason"]
        assert _activeFactCount(store) == before, "active 事实零残留"
        assert store.factCount() == before, "整批事务回滚：账面行也零落盘"
