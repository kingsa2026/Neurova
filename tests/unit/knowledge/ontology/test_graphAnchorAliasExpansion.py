# -*- coding: utf-8 -*-
"""W0-2 query_expander 先比后合退役（specs/2026-11-12 §2 W0-2；D6 已裁）。

对比结论（先比后合，教义第 7 条）：四级扩展中「别名」已被两处既有面覆盖——
subjectsMentionedIn 别名子串锚点（temporal_facts.py，时效读面与走查共用）与
检索侧查询别名归一（query_normalization.py，2026-10-30 准确性档）；「term_id/
别名→扩展词」对图走查锚点无增益。不可替代部分＝子类实例＋关系邻域，并入
graph_walk 锚点解析单点（本档红→绿钉住）；随后 query_expander.py 及其专属
测试退役，全仓零 import（教义第 7 条：该功能在仓内只剩一处实现被消费）。

走查语义：锚点自身事实是跳板，返回 hop≥2 叶子——夹具造
订单D0x -assigned_to-> 张三/李四 -works_on-> 项目 的两跳链作读数。
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.graph_walk import GraphFactWalker
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


def _admit(store, subject, predicate, obj):
    content = "%s %s %s" % (subject, predicate, obj)
    productionAdmissionGate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))


@pytest.fixture
def kb(tmp_path, monkeypatch):
    # 种子兜底闸关死：红必须落在"本体扩展缺席"上，不许 BM25 兜底掩盖
    monkeypatch.setenv("NEUROVA_KB_FACT_SURFACE", "0")
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    registry = OntologyTermRegistry(s)
    registry.registerMany([
        {"termId": "Order", "kind": "concept", "label": "订单", "aliases": ["order"]},
        {"termId": "HighRiskOrder", "kind": "concept", "parentTermId": "Order",
         "label": "高风险订单"},
        {"termId": "has_status", "kind": "relation", "aliases": ["状态"]},
    ])
    gate = productionAdmissionGate(s)
    for subject in ("订单D01", "订单D02"):
        _admit(s, subject, "is_a", "Order")
        registry.assignSubjectType(s.resolveSubjectKey("default", subject), "Order")
        _admit(s, subject, "has_status", "正常" if subject.endswith("01") else "异常")
        _admit(s, subject, "assigned_to", "张三")
    _admit(s, "订单D03", "is_a", "HighRiskOrder")
    registry.assignSubjectType(s.resolveSubjectKey("default", "订单D03"), "HighRiskOrder")
    _admit(s, "订单D03", "assigned_to", "李四")
    _admit(s, "张三", "works_on", "项目P")
    _admit(s, "李四", "works_on", "项目Q")
    # 项目实体自身的事实：锚点链 D0x→张三→项目P 的 hop2 才有叶子可回
    _admit(s, "项目P", "has_status", "执行中")
    _admit(s, "项目Q", "has_status", "已交付")
    yield s, registry
    s.close()


class TestConceptSubclassAnchor:
    def test_conceptQueryAnchorsOnTypedInstances(self, kb):
        """查询命中概念 → 该类型实例成锚点，两跳叶子可达（现零锚点空走即红）。"""
        s, _registry = kb
        rows = GraphFactWalker(s, agentId="default").walkFromQuery("Order")
        subjects = {r["subject"] for r in rows}
        assert "张三" in subjects, "Order 的实例（订单D01/02）应成为锚点接出张三"

    def test_aliasOfConceptAnchorsToo(self, kb):
        """概念别名词形（order）同样触发实例锚点。"""
        s, _registry = kb
        rows = GraphFactWalker(s, agentId="default").walkFromQuery("order 状态如何")
        subjects = {r["subject"] for r in rows}
        assert "张三" in subjects

    def test_subclassTermScopesToItsOwnInstances(self, kb):
        """查询命中子类 HighRiskOrder → 只锚子类实例，不扩散到父类全量（D01/02 不入）。"""
        s, _registry = kb
        rows = GraphFactWalker(s, agentId="default").walkFromQuery("HighRiskOrder")
        subjects = {r["subject"] for r in rows}
        assert "李四" in subjects, "HighRiskOrder 实例（订单D03）应锚出李四"
        assert "张三" not in subjects, "父类实例不得被子类查询扩散锚入"

    def test_relationAliasAnchorsOnPredicateSubjects(self, kb):
        """查询命中关系（状态=has_status 别名）→ 断言该谓词的主体成锚点。"""
        s, _registry = kb
        rows = GraphFactWalker(s, agentId="default").walkFromQuery("状态")
        subjects = {r["subject"] for r in rows}
        assert "张三" in subjects, "断言 has_status 的主体（订单D01/02）应成为锚点"


class TestStrongCriterionPriority:
    def test_subjectSubstringAnchorsStillFirst(self, kb):
        """强判据（主体名/别名词形命中）不被扩展排挤：直接点名的主体照常锚入。"""
        s, _registry = kb
        rows = GraphFactWalker(s, agentId="default").walkFromQuery("张三 手头有什么")
        subjects = {r["subject"] for r in rows}
        assert "项目P" in subjects, "张三 的两跳叶子（项目P 的状态事实）应可达"

    def test_unmatchedQueryZeroAnchors(self, kb):
        """未命中任何术语词形 → 零扩展（不猜不造，种子闸关死时零走查）。"""
        s, _registry = kb
        rows = GraphFactWalker(s, agentId="default").walkFromQuery("totally_unrelated_xyz")
        assert rows == []


class TestQueryExpanderRetired:
    def test_moduleDeleted(self):
        path = Path(__file__).resolve().parents[4] / "neurova" / "knowledge" / \
            "ontology" / "query_expander.py"
        assert not path.exists(), "query_expander.py 应已按 D6 退役删除（%s）" % path

    def test_noImportsAnywhere(self):
        repo_root = Path(__file__).resolve().parents[4]
        hits = []
        for base in (repo_root / "neurova", repo_root / "tests"):
            for py in base.rglob("*.py"):
                if py.name == Path(__file__).name or py.name == "__pycache__":
                    continue
                for line in py.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if "query_expander" in line and re.search(
                            r"(import|from)\s|import_module", line):
                        hits.append("%s: %s" % (py, line.strip()))
        assert hits == [], "全仓零 query_expander import（退役守卫）：%r" % hits
