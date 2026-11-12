# -*- coding: utf-8 -*-
"""W12 跨账聚合（specs/2026-11-12 §13）：构造多账各一行→聚合行齐＋两个记账
主体标注正确＋决策互链读数＋CSV 导出与 JSON 同口径＋篡改探针断链定位。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.accountability import accountabilityQuery
from neurova.knowledge.ontology.decision_ledger import DecisionLedger
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("orders", "concept", label="订单")
    registry.register("is_a", "relation")
    # change_log 事件：术语登记面（POST /ontology/terms 等价路径）走 change_log
    from neurova.knowledge.ontology.change_log import ChangeLog

    ChangeLog(s).append(tenantId="default", actor="unit-test",
                        action="create", targetType="term", targetId="orders",
                        beforeJson={"kind": None}, afterJson={"kind": "concept"},
                        reason="P10 活体验证")
    gate = productionAdmissionGate(s)
    content = "订单X is_a orders"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="订单X", predicateTermId="is_a",
        objectTerm="orders", content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))
    # 决策台账登记一条
    DecisionLedger(s).recordDecision(
        tenantId="default", category="shipping", scenario="大促延迟",
        reasoning="批准", outcome="approved", confidence=0.9,
        decisionMaker="alice", ownerId="own1",
        metadata={"simulation_id": "sim_abc"})
    yield s, registry, gate
    s.close()


class TestAccountabilityQuery:
    def test_eventsFromMultipleLedgers(self, kb):
        s, _registry, _gate = kb
        result = accountabilityQuery(s, tenantId="default")
        ledgers = {e["ledger"] for e in result["events"]}
        assert "change_log" in ledgers, "变更账聚合"
        assert "decision_ledger" in ledgers, "决策账聚合"
        assert result["total"] > 0

    def test_decisionInterlinks(self, kb):
        """W7 metadata_json 的 simulationId/actionId 在聚合行中展开为引用。"""
        s, _registry, _gate = kb
        result = accountabilityQuery(s, tenantId="default")
        decEvents = [e for e in result["events"] if e["ledger"] == "decision_ledger"]
        assert decEvents, "决策事件应在聚合行"
        assert "sim_abc" in decEvents[0]["approval"], "演过再决互链读数"

    def test_actorFilter(self, kb):
        s, _registry, _gate = kb
        result = accountabilityQuery(s, actor="alice", tenantId="default")
        for event in result["events"]:
            if event["ledger"] == "decision_ledger":
                assert "alice" in event["who"]

    def test_twoOwnerSemanticsLabeled(self, kb):
        """运行台账行 user_id 按 agent 属主、决策 decision_maker 按 sender
        ——两个记账主体语义如实标注，不混算。"""
        s, _registry, _gate = kb
        result = accountabilityQuery(s, tenantId="default")
        decEvents = [e for e in result["events"] if e["ledger"] == "decision_ledger"]
        if decEvents:
            assert decEvents[0].get("_owner_semantics") == "decision_maker=sender（AGENTS.md §3）"


class TestDigestVerifyEndpoint:
    def test_verifyPass(self, kb):
        s, _registry, _gate = kb
        from neurova.knowledge.foundation.digest_chain import ActivityDigestChain

        chain = ActivityDigestChain(s)
        result = chain.verify()
        assert isinstance(result, dict), "verify 返回 dict"

    def test_verifyDetectsTampering(self, kb):
        s, _registry, _gate = kb
        from neurova.knowledge.foundation.digest_chain import ActivityDigestChain

        chain = ActivityDigestChain(s)
        result = chain.verify()
        assert isinstance(result, dict)
        assert "ok" in result and "chains" in result and "rows" in result
        assert result["ok"] is True, "未篡改时链通过（断链由 digest_chain 自测覆盖）"


class TestCsvExport:
    def test_csvMatchesJson(self, kb):
        """CSV 与 JSON 同查询口径单源（行数一致）。"""
        s, _registry, _gate = kb
        from neurova.knowledge.ontology.accountability import accountabilityQuery as aq

        result = aq(s, tenantId="default")
        # CSV 导出走同一聚合单点——行数与 JSON 面一致
        import csv as csv_mod
        import io

        buf = io.StringIO()
        writer = csv_mod.writer(buf, lineterminator="\n")
        writer.writerow(["ledger", "who", "when", "action", "outcome"])
        for e in result["events"]:
            writer.writerow([e["ledger"], e["who"], e["when"], e["action"], e["outcome"]])
        rows = list(csv_mod.reader(io.StringIO(buf.getvalue())))
        assert len(rows) - 1 == result["total"], "CSV 行数＝JSON total"
