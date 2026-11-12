# -*- coding: utf-8 -*-
"""W1 量值唯一解析/归一/比较实装（specs/2026-11-12 §3）。

quantity.py 是数值 qualifier 的唯一判据源：解析（K/M/G/T 后缀＋中文万/亿＋常见
物理单位）、同维归一到基准单位、量值比较；解析失败返回 None（诚实，不猜）。
四组判据：解析/归一/比较/失败形态。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.quantity import (
    compareQuantity,
    normalizeTo,
    numericQualifierKeys,
    parseQuantity,
)


class TestParseQuantity:
    def test_dataSuffix(self):
        q = parseQuantity("200MB")
        assert q is not None and q["dimension"] == "data"
        assert normalizeTo(q["value"], q["unit"], "B") == pytest.approx(2e8)
        q2 = parseQuantity("2.5GB")
        assert q2 is not None
        assert normalizeTo(q2["value"], q2["unit"], "B") == pytest.approx(2.5e9)

    def test_bareCountSuffix(self):
        """裸 K/M/G/T 按计数倍率读（数据量必须带 B——歧义消解口径）。"""
        q = parseQuantity("200M")
        assert q is not None and q["dimension"] == "count"
        assert normalizeTo(q["value"], q["unit"], "count") == pytest.approx(2e8)

    def test_chineseCounting(self):
        q = parseQuantity("3亿")
        assert q is not None and q["dimension"] == "count"
        assert q["value"] * _multiplier(q) == pytest.approx(3e8)
        q2 = parseQuantity("100万")
        assert q2 is not None and q2["dimension"] == "count"

    def test_physicalUnits(self):
        assert parseQuantity("12kg")["dimension"] == "mass"
        assert parseQuantity("5km")["dimension"] == "length"
        assert parseQuantity("30min")["dimension"] == "time"
        assert parseQuantity("45%")["dimension"] == "ratio"

    def test_pureNumber(self):
        q = parseQuantity("42")
        assert q is not None and q["value"] == pytest.approx(42.0)

    def test_failuresReturnNone(self):
        assert parseQuantity("两百M") is None          # 中文数字不猜
        assert parseQuantity("") is None
        assert parseQuantity("M") is None              # 无数值
        assert parseQuantity("abc") is None


def _multiplier(q):
    return {"M": 1e6, "G": 1e9, "K": 1e3, "T": 1e12,
            "万": 1e4, "亿": 1e8}.get(q["unit"], 1.0)


class TestNormalizeTo:
    def test_sameDimension(self):
        assert normalizeTo(2, "GB", "B") == pytest.approx(2e9)
        assert normalizeTo(3, "亿", "count") == pytest.approx(3e8)
        assert normalizeTo(12, "kg", "g") == pytest.approx(12000.0)
        assert normalizeTo(30, "min", "s") == pytest.approx(1800.0)

    def test_crossDimensionRejected(self):
        assert normalizeTo(1, "kg", "m") is None
        assert normalizeTo(1, "GB", "万") is None

    def test_unknownUnitRejected(self):
        assert normalizeTo(1, "xyzunit", "m") is None


class TestCompareQuantity:
    def test_sameDimensionComparable(self):
        a = parseQuantity("200MB")
        b = parseQuantity("0.3GB")
        assert compareQuantity(a, b) == -1
        assert compareQuantity(a, a) == 0
        assert compareQuantity(b, a) == 1

    def test_crossDimensionIncomparable(self):
        assert compareQuantity(parseQuantity("200MB"), parseQuantity("12kg")) is None
        assert compareQuantity(parseQuantity("200M"), parseQuantity("0.3GB")) is None
        assert compareQuantity(parseQuantity("3亿"), None) is None


class TestNumericQualifierKeys:
    def test_declaredNumberKeys(self):
        term = {"qualifier_schema": {"allowed": {
            "capacity": {"type": "number"}, "note": {"type": "text"}}},
            "required": []}
        assert numericQualifierKeys(term) == ["capacity"]

    def test_stringFormAlsoAccepted(self):
        term = {"qualifier_schema": {"allowed": {"coverage": "number"}}}
        assert numericQualifierKeys(term) == ["coverage"]

    def test_undeclaredZeroDrift(self):
        assert numericQualifierKeys(None) == []
        assert numericQualifierKeys({"qualifier_schema": {}}) == []


class TestAdmissionNormalization:
    """声明 number 的键：字符串值在写入口单点归一成 canonical dict（读面不重复归一）。"""

    def test_stringValueCanonicalizedAtAdmission(self, tmp_path):
        s = KnowledgeFactStore(str(tmp_path / "kb.db"))
        registry = _registryWithNumericSchema(s)
        gate = productionAdmissionGate(s)
        receipt = gate.admit(AdmissionRequest(
            agentId="default", tenantId="default", subjectLabel="仓库W1",
            predicateTermId="stores", objectTerm="货物X",
            content="仓库W1 stores 货物X",
            qualifier={"capacity": "200MB"},
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": "仓库W1 stores 货物X"}]))
        fact = s.fact(receipt.factId)
        stored = fact["qualifier"]["capacity"]
        assert isinstance(stored, dict), "写入口应归一成 canonical 量值"
        assert stored["dimension"] == "data"
        assert stored["value"] == pytest.approx(2e8)
        assert stored["unit"] == "B"
        # 归一只走写入口一次：读面拿到的就是 canonical 形
        assert numericQualifierKeys(registry.term("stores")) == ["capacity"]
        s.close()

    def test_unparseableStillRejectedByValidation(self, tmp_path):
        s = KnowledgeFactStore(str(tmp_path / "kb.db"))
        _registryWithNumericSchema(s)
        gate = productionAdmissionGate(s)
        with pytest.raises(ValueError, match="本体校验"):
            gate.admit(AdmissionRequest(
                agentId="default", tenantId="default", subjectLabel="仓库W1",
                predicateTermId="stores", objectTerm="货物X",
                content="仓库W1 stores 货物X",
                qualifier={"capacity": "两百M"},
                assertions=[{"actorType": "pipeline", "actorId": "unit",
                             "mediumRef": "unit:test",
                             "statementText": "仓库W1 stores 货物X"}]))
        s.close()

    def test_undeclaredPredicateFreeJsonZeroDrift(self, tmp_path):
        """未声明数值 schema 的谓词 qualifier 仍自由 JSON（存量零漂移）。"""
        s = KnowledgeFactStore(str(tmp_path / "kb.db"))
        registry = _registryWithNumericSchema(s)
        registry.register("mentions", "relation")
        gate = productionAdmissionGate(s)
        receipt = gate.admit(AdmissionRequest(
            agentId="default", tenantId="default", subjectLabel="仓库W1",
            predicateTermId="mentions", objectTerm="货物X",
            content="仓库W1 mentions 货物X",
            qualifier={"capacity": "200M"},
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test",
                         "statementText": "仓库W1 mentions 货物X"}]))
        stored = s.fact(receipt.factId)["qualifier"]["capacity"]
        assert stored == "200M", "未声明谓词不归一（存量零漂移）"
        s.close()


def _registryWithNumericSchema(s):
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    registry = OntologyTermRegistry(s)
    registry.register("warehouses", "concept", label="仓库")
    registry.register("stores", "relation", domain=["warehouses"],
                      qualifierSchema={"allowed": {"capacity": {"type": "number"}},
                                       "required": []})
    return registry
