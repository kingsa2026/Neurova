# -*- coding: utf-8 -*-
"""Turtle 全库导出 `serializeAll`（升级计划 B5，A4 标准栈互通面）。

判据（本文件只咬合导出面，不接线任何端点——路由由主会话统一挂）：
- 单个 Turtle 文档装下**本租户**全库：`@prefix kbg:` 头 + terms / rules / facts
  三段注释分段，谓词命名沿用 kbg: 前缀、形状与既有 `serialize` 一致；
- 逐字节确定性：同一库内容两次输出一致，且**插入顺序不漏进导出文本**
  （排序只来自固定 ORDER BY，不来自写入先后或时间戳）；
- 回读走 turtle.py 既有 `parseTurtle`：导出的文本能被自己的解析器读回，
  是这条链唯一的格式校验（turtle.py 模块纪律）；
- facts 段只收 `status='active' AND record_kind='triple'`：撤回态与叙述行不出现；
- 转义边界：引号/反斜杠/换行/制表经 `literal` 往返无损。
"""
from __future__ import annotations

import json

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.ontology.turtle import (
    NAMESPACE,
    iri,
    literal,
    parseTurtle,
    serializeAll,
    unescapeLiteral,
)


@pytest.fixture()
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "facts.db"))
    yield s
    s.close()


def _admit(store, subject, predicate, obj, tenantId="default", agentId="agent"):
    """经生产装配闸写入一条合法三元组（assertions 必带，走全五段）。"""
    content = "%s %s %s" % (subject, predicate, obj)
    return productionAdmissionGate(store, toolVersion="unit").admit(AdmissionRequest(
        agentId=agentId, tenantId=tenantId,
        subjectLabel=subject, predicateTermId=predicate, objectTerm=obj,
        content=content,
        assertions=[{"actorType": "user", "actorId": "u1", "statementText": content}],
    )).factId


def _subjectSet(text):
    return {s for s, _, _ in parseTurtle(text)}


class TestSingleDocumentShape:
    def test_prefixAndThreeSectionCommentsArePresent(self, store):
        OntologyTermRegistry(store).register("device", "concept", label="设备")
        ForwardChainingEngine(store).registerRule(
            "dev_rel", "mentions",
            [{"atom": "mentions", "subject": "X", "object": "Y"}])
        _admit(store, "路由器", "mentions", "端口")

        text = serializeAll(store)

        assert text.startswith("@prefix kbg: <%s> ." % NAMESPACE)
        for marker in ("# terms", "# rules", "# facts"):
            assert marker in text, "缺 %r 分段注释: %s" % (marker, text[:400])

    def test_termsRulesFactsAllLandInOneDocument(self, store):
        registry = OntologyTermRegistry(store)
        registry.register("device", "concept", label="设备")
        registry.register("router", "concept", label="路由器", parentTermId="device")
        ForwardChainingEngine(store).registerRule(
            "dev_rel", "mentions",
            [{"atom": "mentions", "subject": "X", "object": "Y"}])
        _admit(store, "路由器", "mentions", "端口")

        parsed = parseTurtle(serializeAll(store))

        # terms 段：kind/label 走字面量，parent 走 kbg: IRI
        assert (iri("device"), "kbg:kind", literal("concept")) in parsed
        assert (iri("device"), "kbg:label", literal("设备")) in parsed
        assert (iri("router"), "kbg:parentTermId", iri("device")) in parsed
        # rules 段：head/body 以 JSON 字符串字面量落地
        ruleRows = dict((p, o) for s, p, o in parsed if s == iri("dev_rel"))
        assert unescapeLiteral(ruleRows["kbg:headPredicate"])[0] == "mentions"
        body = json.loads(unescapeLiteral(ruleRows["kbg:body"])[0])
        assert body == [{"atom": "mentions", "subject": "X", "object": "Y"}]
        # facts 段：主体用 subject_key（canonical_label 经 iri() 收字形后 CJK 全塌成
        # 下划线，主体会互相吞并；subject_key 是 ASCII 唯一键），谓词用数据谓词
        key = store.resolveSubjectKey("agent", "路由器")
        assert (iri(key), "kbg:mentions", literal("端口")) in parsed


class TestDeterminism:
    def test_sameLibraryDumpsByteIdenticalTwice(self, store):
        OntologyTermRegistry(store).register("device", "concept", label="设备")
        ForwardChainingEngine(store).registerRule(
            "dev_rel", "mentions",
            [{"atom": "mentions", "subject": "X", "object": "Y"}])
        _admit(store, "路由器", "mentions", "端口")
        _admit(store, "交换机", "mentions", "网口")

        assert serializeAll(store) == serializeAll(store)

    def test_insertionOrderDoesNotLeakIntoTheDump(self, tmp_path):
        """同一逻辑内容、不同写入次序 ⇒ 导出逐字节一致（时间戳/写入序不进文本）。"""
        pairs = [("甲", "mentions", "乙"), ("乙", "mentions", "丙"),
                 ("丙", "mentions", "丁")]

        def build(reverse):
            s = KnowledgeFactStore(str(tmp_path / ("facts_%s.db" % reverse)))
            try:
                for subject, predicate, obj in (reversed(pairs) if reverse else pairs):
                    _admit(s, subject, predicate, obj)
                return serializeAll(s)
            finally:
                s.close()

        assert build(False) == build(True)

    def test_emptyTenantStillEmitsParseableDeterministicDocument(self, store):
        first = serializeAll(store)
        second = serializeAll(store)

        assert first == second
        assert parseTurtle(first) == []


class TestTenantIsolation:
    def test_otherTenantRowsDoNotLeakIntoTheDump(self, store):
        registry = OntologyTermRegistry(store)
        registry.register("doc", "concept", label="默认租户文档", tenantId="default")
        registry.register("doc", "concept", label="二租户文档", tenantId="t2")
        _admit(store, "默认主体", "mentions", "默认客体", tenantId="default")
        _admit(store, "二租户主体", "mentions", "二租户客体", tenantId="t2")

        defaultDump = serializeAll(store)
        t2Dump = serializeAll(store, tenantId="t2")

        assert "默认客体" in defaultDump and "默认租户文档" in defaultDump
        assert "二租户客体" not in defaultDump and "二租户文档" not in defaultDump
        assert "二租户客体" in t2Dump and "二租户文档" in t2Dump
        assert "默认客体" not in t2Dump


class TestFactsSectionFilter:
    def test_retractedAndNarrativeFactsStayOut(self, store):
        factId = _admit(store, "活着", "mentions", "在库")
        store.retract(factId, reason="导出过滤判据")
        key = store.resolveSubjectKey("agent", "活着")
        store.upsertFact(agentId="agent", subjectKey=key, predicateTermId="documented_as",
                         objectTerm="entry:x", content="叙述行", recordKind="narrative")

        parsed = parseTurtle(serializeAll(store))

        subject = iri(key)
        exported = [o for s, p, o in parsed if s == subject]
        assert literal("在库") not in exported, "撤回态事实不得进 facts 段"
        assert literal("entry:x") not in exported, "叙述行不得进 facts 段"

    def test_agentIdNarrowsTheFactsSection(self, store):
        _admit(store, "A主体", "mentions", "甲", agentId="agentA")
        _admit(store, "B主体", "mentions", "乙", agentId="agentB")

        onlyA = serializeAll(store, agentId="agentA")

        subjects = _subjectSet(onlyA)
        assert iri(store.resolveSubjectKey("agentA", "A主体")) in subjects
        assert iri(store.resolveSubjectKey("agentB", "B主体")) not in subjects


class TestEscapeBoundaries:
    def test_quotesBackslashNewlineTabRoundTripLosslessly(self, store):
        tricky = '他说："A\\B"\n第二行\t制表'
        _admit(store, "边界主体", "mentions", tricky)

        parsed = parseTurtle(serializeAll(store))

        key = store.resolveSubjectKey("agent", "边界主体")
        objects = [unescapeLiteral(o)[0] for s, _, o in parsed if s == iri(key)]
        assert objects == [tricky], "转义往返必须无损: %r" % objects


class TestExportEndpoint:
    """B5 的**出口面**：`GET /v1/knowledge/ontology/export.ttl` 真把文档吐出去。

    模块会序列化不等于用户能导出——这一半此前登记为"路由由主会话统一挂"，
    本档把它咬合住：媒体类型、治理门（非管理员 403）、租户隔离、纯只读。
    导出文本仍用 turtle.py 自己的 `parseTurtle` 复核，不引第三方解析器
    （rdflib 对拍是可选测试，见 test_rdflibInterop.py）。
    """

    EXPORT_PATH = "/v1/knowledge/ontology/export.ttl"

    def _client(self, role: str = "admin"):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api import auth as knowledge_auth
        from neurova.api.endpoints import knowledge_ontology

        app = FastAPI()
        app.include_router(knowledge_ontology.router, prefix="/v1/knowledge")
        user = {"user_id": "9", "username": "u", "role": role, "tenant_id": "default"}
        app.dependency_overrides[knowledge_auth.get_current_user_or_service] = (
            lambda: dict(user))
        return TestClient(app)

    def _served(self, store, monkeypatch, role: str = "admin"):
        monkeypatch.setattr(
            "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store)
        return self._client(role).get(self.EXPORT_PATH)

    def test_servesParsableTurtleWithGovernanceGate(self, store, monkeypatch):
        OntologyTermRegistry(store).registerMany([{"termId": "person", "kind": "concept"}])
        _admit(store, "甲主体", "mentions", "乙")
        before = store.factCount()

        resp = self._served(store, monkeypatch)

        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/turtle"), resp.headers
        parsed = parseTurtle(resp.text)
        assert parsed, "导出的文档必须能被本仓解析器读回非空三元组"
        key = store.resolveSubjectKey("agent", "甲主体")
        assert iri(key) in {s for s, _, _ in parsed}
        # 纯只读：吐一遍全库不该动底座一根手指
        assert store.factCount() == before, "导出端点写了库——只读承诺破功"

    def test_nonAdminRefusedExplicitly(self, store, monkeypatch):
        _admit(store, "甲主体", "mentions", "乙")

        resp = self._served(store, monkeypatch, role="user")

        assert resp.status_code == 403, resp.text

    def test_otherTenantContentStaysOutOfDocument(self, store, monkeypatch):
        _admit(store, "本租户主体", "mentions", "丙", tenantId="default")
        _admit(store, "他租户主体", "mentions", "丁", tenantId="tenantB")

        resp = self._served(store, monkeypatch)

        text = resp.text
        assert iri(store.resolveSubjectKey("agent", "本租户主体")) in text
        assert iri(store.resolveSubjectKey("agent", "他租户主体")) not in text, \
            "导出把别的租户一起吐出去了——租户隔离破功"
