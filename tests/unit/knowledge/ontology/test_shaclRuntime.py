"""SHACL 运行时校验（升级卡 U1）：形状单源、三档开关、fail-soft。

判据都走真写入口（真 store + 真生产咽喉）。注意：段3 前半的既有 DSL 形状
求值（shapes.evaluateForRequest）会先于本卡的 SHACL 段拦截违规候选——
两道闸同向，谁先命中都算拒写；本卡的独有价值在「标准 SHACL 语义 +
全子图视角」（DSL 只看候选行，SHACL 看主体邻域内全部已落库事实），由
test_shaclCatchesLegacyFactsTheDslMisses 专门钉住。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology import shacl_runtime
from neurova.knowledge.ontology.export.shacl import exportShaclShapes
from neurova.knowledge.ontology.shapes import ShapeRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _gate(store):
    return productionAdmissionGate(store, toolVersion="unit")


def _admit(store, subject, predicate, obj):
    content = "%s %s %s" % (subject, predicate, obj)
    return _gate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate, objectTerm=obj,
        content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit", "mediumRef": "unit:test",
                     "statementText": content}],
    ), allowPendingSegments=True).factId


def _registerPatternShape(store, shapeId="shape_serial_pattern", severity="violation",
                          pattern=r"^DEV-\d+$", target="serial_code"):
    return ShapeRegistry(store).register(
        "default", shapeId, "relation", "pattern", {"pattern": pattern},
        targetTermId=target, severity=severity, message="序列号须形如 DEV-数字")


class TestShapesSingleSource:
    def test_shapesTtlIsParseableRdf(self, store):
        """导出面与运行时共用的形状文档必须是可解析 Turtle（缺 rdf 前缀即红）。"""
        import rdflib

        _registerPatternShape(store)
        ttl = exportShaclShapes(store, "default")
        graph = rdflib.Graph().parse(data=ttl, format="turtle")
        shapes = list(graph.subjects(
            rdflib.RDF.type, rdflib.URIRef("http://www.w3.org/ns/shacl#NodeShape")))
        assert len(shapes) == 1, "注册了一个形状，解析后应恰好一个 sh:NodeShape"

    def test_runtimeUsesTheSameShapesDocument(self, store):
        _registerPatternShape(store)
        ttl = exportShaclShapes(store, "default")
        report = shacl_runtime.validateShapesRuntime(
            store, "default", mode="enforce",
            dataGraphTtl=ttl)  # 形状文档自身当数据图：无目标事实即 conform
        assert report["supported"] is True
        assert report["conforms"] is True


class TestThreeModes:
    def test_offIsTheDefaultAndSkipsEverything(self, store, monkeypatch):
        monkeypatch.delenv("NEUROVA_ONTOLOGY_SHACL_RUNTIME", raising=False)
        # 无形状时违规数据照常入库（此时 DSL 也不拦），随后注册形状验证 off 档跳过
        factId = _admit(store, "设备A", "serial_code", "bad-value")
        assert factId
        _registerPatternShape(store)
        report = shacl_runtime.validateShapesRuntime(store, "default")
        assert report["mode"] == "off" and report.get("skipped") is True

    def test_enforceRejectsViolationAtTheGate(self, store, monkeypatch):
        monkeypatch.setenv("NEUROVA_ONTOLOGY_SHACL_RUNTIME", "enforce")
        _registerPatternShape(store)
        # 段3 前半的 DSL 形状求值与后半的 SHACL 闸同向，谁先命中都算拒写
        with pytest.raises(ValueError, match="SHACL|本体校验未过"):
            _admit(store, "设备A", "serial_code", "bad-value")
        # 合规数据照常入库
        assert _admit(store, "设备B", "serial_code", "DEV-123")

    def test_shaclCatchesLegacyFactsTheDslMisses(self, store, monkeypatch):
        """SHACL 的独有价值：主体邻域全图视角。先落一条违规事实（当时无形状），
        形状补注册后，同主体的**合规**新写入被 SHACL 闸拦下——DSL 只看候选行
        看不见旧账，SHACL 子图看得见。"""
        monkeypatch.setenv("NEUROVA_ONTOLOGY_SHACL_RUNTIME", "enforce")
        legacy = _admit(store, "设备A", "serial_code", "bad-value")
        assert legacy
        _registerPatternShape(store)
        with pytest.raises(ValueError, match="SHACL"):
            _admit(store, "设备A", "serial_code", "DEV-456")

    def test_shadowWarnsButDoesNotBlock(self, store, monkeypatch):
        monkeypatch.setenv("NEUROVA_ONTOLOGY_SHACL_RUNTIME", "shadow")
        factId = _admit(store, "设备A", "serial_code", "bad-value")  # 无形状时先落库
        assert factId
        _registerPatternShape(store)
        # shadow 档下 SHACL 闸永不拒写（返回空）； DSL 闸不在本卡开关范围内
        assert shacl_runtime.admissionShaclCheck(store, None, None) == []
        report = shacl_runtime.validateShapesRuntime(
            store, "default", mode="shadow",
            subjectKeys=[store.resolveSubjectKey("default", "设备A")])
        assert report["conforms"] is False and report["violations"]

    def test_invalidModeFallsBackToOffWithWarning(self, store, monkeypatch):
        monkeypatch.setenv("NEUROVA_ONTOLOGY_SHACL_RUNTIME", "yolo")
        assert shacl_runtime.shaclMode() == "off"
        assert shacl_runtime.admissionShaclCheck(store, None, None) == []


class TestEnforceSemantics:
    def test_firstEverFactOfASubjectIsChecked(self, store, monkeypatch):
        """候选三元组必须进数据图：主体首条违规事实也要被拦（否则校验空转）。"""
        monkeypatch.setenv("NEUROVA_ONTOLOGY_SHACL_RUNTIME", "enforce")
        _registerPatternShape(store)
        with pytest.raises(ValueError, match="SHACL|本体校验未过"):
            _admit(store, "全新设备", "serial_code", "bad-value")

    def test_warningSeverityDoesNotBlock(self, store, monkeypatch):
        monkeypatch.setenv("NEUROVA_ONTOLOGY_SHACL_RUNTIME", "enforce")
        _registerPatternShape(store, shapeId="shape_serial_warn", severity="warning")
        factId = _admit(store, "设备A", "serial_code", "bad-value")
        assert factId, "warning 级形状违规记录但不拒写"

    def test_missingPyshaclIsHonestFailSoft(self, store, monkeypatch):
        monkeypatch.setenv("NEUROVA_ONTOLOGY_SHACL_RUNTIME", "enforce")
        _registerPatternShape(store)

        def _boom():
            raise ImportError("No module named 'pyshacl'")

        monkeypatch.setattr(shacl_runtime, "_importPyshacl", _boom)
        report = shacl_runtime.validateShapesRuntime(store, "default")
        assert report["supported"] is False and "pyshacl" in report["reason"]
        assert shacl_runtime.admissionShaclCheck(store, None, None) == [], \
            "依赖缺位不拦截写入（首启链负责补齐），但必须显式降级而非静默假装校验过"

    def test_subjectScopingKeepsOtherSubjectsOutOfTheGraph(self, store, monkeypatch):
        monkeypatch.setenv("NEUROVA_ONTOLOGY_SHACL_RUNTIME", "enforce")
        _admit(store, "设备甲", "serial_code", "bad-value")  # 无形状时先落库
        _admit(store, "设备乙", "serial_code", "DEV-777")    # 乙全合规（主体须有事实才可解析）
        _registerPatternShape(store)
        keyYi = store.resolveSubjectKey("default", "设备乙")
        report = shacl_runtime.validateShapesRuntime(
            store, "default", subjectKeys=[keyYi])
        assert report["conforms"] is True, "乙的子图不应被甲的违规连坐"
        reportJia = shacl_runtime.validateShapesRuntime(
            store, "default", subjectKeys=[store.resolveSubjectKey("default", "设备甲")])
        assert reportJia["conforms"] is False

    def test_noRegisteredShapesIsAnHonestNoop(self, store, monkeypatch):
        monkeypatch.setenv("NEUROVA_ONTOLOGY_SHACL_RUNTIME", "enforce")
        report = shacl_runtime.validateShapesRuntime(
            store, "default", subjectKeys=["whatever"])
        assert report["conforms"] is True and report.get("note") == "无已注册用户形状"
