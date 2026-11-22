# -*- coding: utf-8 -*-
"""U11：neurova-ontology CLI 薄壳。

真临时数据根装配（tmp_path 真库 + 真生产咽喉写入），不打桩：四命令各自咬合
既有处理函数——terms 读面 / export 导出函数 / runSparqlQuery 只读查询 /
validateShapesRuntime dry-run。写形 SPARQL、未知格式、未登记术语一律显式报错
（诚实形态）；导出格式闭集以 export/ 实际函数为准。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology import cli
from neurova.knowledge.ontology.shapes import ShapeRegistry
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def kb(tmp_path):
    """真临时库 + 真生产咽喉：与 test_sparqlReadOnly / test_shaclRuntime 同款装配。"""
    db = str(tmp_path / "ontology_cli.db")
    store = KnowledgeFactStore(db)
    registry = OntologyTermRegistry(store)
    registry.register("device", "concept", label="设备")
    registry.register("linked", "relation", label="关联")
    registry.register("serial_code", "relation", label="序列号")

    def _admit(subject: str, predicate: str, obj: str) -> str:
        content = "%s %s %s" % (subject, predicate, obj)
        return productionAdmissionGate(store).admit(AdmissionRequest(
            agentId="default", subjectLabel=subject, predicateTermId=predicate,
            objectTerm=obj, content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}],
        )).factId

    _admit("设备A", "linked", "设备B")
    yield db, store, registry, _admit
    store.close()


# ── terms：转交 OntologyTermRegistry 读面 ──────────────────────────


class TestTermsCommand:
    def test_listShowsSeedAndRegisteredTerms(self, kb, capsys):
        db, *_ = kb
        rc = cli.main(["terms", "list", "--db", db])
        out = capsys.readouterr().out
        assert rc == 0
        assert "is_a" in out and "documented_as" in out, "种子术语必须在列"
        assert "device" in out and "linked" in out, "登记术语必须在列"

    def test_getShowsDeclaration(self, kb, capsys):
        db, *_ = kb
        rc = cli.main(["terms", "get", "is_a", "--db", db])
        out = capsys.readouterr().out
        assert rc == 0
        assert "relation" in out, "类别入表"
        assert "transitive" in out, "is_a 的传递性声明可见"

    def test_getUnknownTermFailsHonestly(self, kb, capsys):
        db, *_ = kb
        rc = cli.main(["terms", "get", "no_such_term", "--db", db])
        err = capsys.readouterr().err
        assert rc == 1
        assert "no_such_term" in err, "未登记术语点名报出，不静默"


# ── export：转交 export/ 既有函数，闭集以实际支持为准 ───────────────


class TestExportCommand:
    def test_turtleContainsPrefixes(self, kb, capsys):
        db, *_ = kb
        rc = cli.main(["export", "--format", "turtle", "--db", db])
        out = capsys.readouterr().out
        assert rc == 0
        assert "@prefix" in out, "Turtle 文档头带前缀声明"
        assert "kbg:" in out, "缺省命名空间前缀在文档中"

    def test_csvToFile(self, kb, tmp_path, capsys):
        db, *_ = kb
        outPath = tmp_path / "onto.csv"
        rc = cli.main(["export", "--format", "csv", "--out", str(outPath), "--db", db])
        assert rc == 0
        text = outPath.read_text(encoding="utf-8")
        assert "=== nodes ===" in text and "=== edges ===" in text, "CSV 双段结构完整"

    def test_unknownFormatRejectedByClosedSet(self, kb, capsys):
        db, *_ = kb
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["export", "--format", "n3", "--db", db])
        assert excinfo.value.code == 2, "argparse 闭集拒绝"
        assert "n3" in capsys.readouterr().err, "未知格式点名报出"


# ── sparql：转交 runSparqlQuery，只读面 ────────────────────────────


class TestSparqlCommand:
    def test_selectHitsProjectionRows(self, kb, capsys):
        db, *_ = kb
        rc = cli.main(["sparql", "SELECT ?s ?o WHERE { ?s kbg:linked ?o }", "--db", db])
        out = capsys.readouterr().out
        assert rc == 0
        assert "设备B" in out, "真 store 投影查出事实行"

    def test_writeFormRejectedHonestly(self, kb, capsys):
        db, *_ = kb
        rc = cli.main(["sparql", "INSERT DATA { <a> <b> <c> }", "--db", db])
        captured = capsys.readouterr()
        assert rc == 1
        assert "写形不支持" in captured.err, "runSparqlQuery 的拒写原因如实透出"


# ── validate：转交 validateShapesRuntime，显式 mode 不走环境档 ──────


class TestValidateCommand:
    def test_withoutShapesNotesHonestly(self, kb, capsys):
        db, *_ = kb
        rc = cli.main(["validate", "--db", db])
        out = capsys.readouterr().out
        assert rc == 0
        assert "无已注册用户形状" in out, "无形状时 note 如实呈现"

    def test_reportsViolationForSubject(self, kb, capsys):
        db, store, _registry, admit = kb
        admit("设备A", "serial_code", "bad-value")  # 无形状时先落一条违规事实
        ShapeRegistry(store).register(
            "default", "shape_serial_pattern", "relation", "pattern",
            {"pattern": r"^DEV-\d+$"}, targetTermId="serial_code",
            severity="violation", message="序列号须形如 DEV-数字")
        key = store.resolveSubjectKey("default", "设备A")
        rc = cli.main(["validate", "--subject", key, "--mode", "shadow", "--db", db])
        out = capsys.readouterr().out
        assert rc == 0
        assert "conforms=False" in out, "违规在报告中如实呈现"
        assert "序列号须形如" in out, "形状消息进入报告"


# ── 入口注册：pyproject [project.scripts] 单点 ─────────────────────


def test_entryPointRegisteredInPyproject():
    root = Path(__file__).resolve().parents[4]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'neurova-ontology = "neurova.knowledge.ontology.cli:main"' in text
