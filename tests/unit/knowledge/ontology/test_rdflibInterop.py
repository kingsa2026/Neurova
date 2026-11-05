# -*- coding: utf-8 -*-
"""Turtle 全库导出的 rdflib 互操作对拍（升级计划 B5，可选测试）。

产品零依赖不变（specs/2026-09-20 六项决策）：rdflib 未安装时本文件整文件 skip，
不装依赖、不进产品 import 面。装了的时候它回答的问题是——我们那个"Turtle 子集"
导出的文本，标准 RDF 解析器认不认：三方库数出来的三元组必须与自家 `parseTurtle`
读回的集合一致（自家解析器收 every 行，rdflib 的 Graph 按集合去重，故比集合）。
"""
from __future__ import annotations

import pytest

rdflib = pytest.importorskip("rdflib", reason="可选对拍：rdflib 未安装则 skip，不装依赖")

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.ontology.turtle import NAMESPACE, parseTurtle, serializeAll


@pytest.fixture()
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "facts.db"))
    yield s
    s.close()


def test_rdflibParsesTheExportAndAgreesWithOwnParser(store):
    OntologyTermRegistry(store).register("device", "concept", label="设备")
    productionAdmissionGate(store, toolVersion="interop").admit(AdmissionRequest(
        agentId="agent", tenantId="default",
        subjectLabel="路由器", predicateTermId="mentions", objectTerm="端口",
        content="路由器 mentions 端口",
        assertions=[{"actorType": "user", "actorId": "u1",
                     "statementText": "路由器 mentions 端口"}],
    ))

    text = serializeAll(store)

    graph = rdflib.Graph().parse(data=text, format="turtle")
    own = set(parseTurtle(text))

    assert len(graph) == len(own), (
        "rdflib 数出 %d 条、自家解析器数出 %d 条（去重后）——两套解析器对同一份文本看法不一"
        % (len(graph), len(own))
    )
    mentions = rdflib.URIRef(NAMESPACE + "mentions")
    hits = [str(o) for s, p, o in graph if p == mentions]
    assert hits == ["端口"], "facts 段的客体经标准解析器读回应为原文: %r" % hits
