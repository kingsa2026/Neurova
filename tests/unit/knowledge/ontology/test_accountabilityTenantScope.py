# -*- coding: utf-8 -*-
"""KNOW-06：追责账本跨账聚合按租户过滤。

审计定位（全仓逐文件审计报告 2026-11-25 §6 KNOW-06）：推导账本全局读取、
agent_runs 直接取全库最近 200 条、哈希链全局校验——返回他租户用户、会话、
运行状态和推导主体。判据：聚合面只返回请求租户的账目（真实账本、真实运行
台账、真实推导链）。
"""

from __future__ import annotations

import pytest

from neurova.core.agent_run_store import AgentRunStore
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.accountability import accountabilityQuery
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("orders", "concept", label="订单")
    registry.register("is_a", "relation")
    gate = productionAdmissionGate(s)
    content = "订单X is_a orders"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="订单X", predicateTermId="is_a",
        objectTerm="orders", content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))
    yield s, registry, gate
    s.close()


def _assertion(text: str) -> list:
    return [{"actorType": "pipeline", "actorId": "unit",
             "mediumRef": "unit:test", "statementText": text}]


class TestAccountabilityTenantScope:
    def test_agentRunLedgerScopedToTenant(self, kb, monkeypatch, tmp_path):
        """他租户的运行行不得出现在本租户追责面（agent_runs 不取全库）。"""
        s, _registry, _gate = kb
        runs = AgentRunStore(tmp_path / "runs.db")
        monkeypatch.setattr("neurova.core.agent_run_store.get_agent_run_store",
                            lambda: runs)
        runs.intake("sess-acme", "user-acme", "agent-a", "task", tenant_id="acme")
        runs.intake("sess-default", "user-default", "agent-b", "task",
                    tenant_id="default")

        result = accountabilityQuery(s, tenantId="default")

        runEvents = [e for e in result["events"] if e["ledger"] == "agent_run_ledger"]
        whos = {e["who"] for e in runEvents}
        assert "user-acme" not in whos, "他租户运行状态不得进入 default 追责面"
        assert "user-default" in whos, "本租户运行行照常聚合"

    def test_derivationLedgerScopedToTenant(self, kb):
        """他租户的推导（规则/结论主体）不得出现在本租户追责面。"""
        s, registry, _gate = kb
        registry.register("linked", "relation", tenantId="acme")
        registry.register("reachable", "relation", tenantId="acme")
        engine = ForwardChainingEngine(
            s, gateFactory=lambda st: productionAdmissionGate(st))
        engine.registerRule(
            "reach_acme", "reachable",
            [{"atom": "linked", "subject": "S", "object": "O"}],
            headSubjectVar="S", materialization="enforce", tenantId="acme")
        gate = productionAdmissionGate(s)
        content = "机甲A linked 机甲B"
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="机甲A", predicateTermId="linked",
            objectTerm="机甲B", content=content, tenantId="acme",
            assertions=_assertion(content)))

        defaultResult = accountabilityQuery(s, tenantId="default")
        assert not [e for e in defaultResult["events"]
                    if e["ledger"] == "derivation_ledger"], \
            "default 追责面不得出现 acme 的推导事件"

        acmeResult = accountabilityQuery(s, tenantId="acme")
        assert [e for e in acmeResult["events"]
                if e["ledger"] == "derivation_ledger"], "acme 自己的推导照常聚合"

    def test_digestChainVerifyScopedToTenant(self, kb):
        """哈希链完整性校验按租户圈域：chains 计数只数本租户活动链。"""
        s, registry, _gate = kb
        registry.register("linked", "relation", tenantId="acme")
        gate = productionAdmissionGate(s)
        content = "机甲A linked 机甲B"
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="机甲A", predicateTermId="linked",
            objectTerm="机甲B", content=content, tenantId="acme",
            assertions=_assertion(content)))

        result = accountabilityQuery(s, tenantId="default")
        digest = [e for e in result["events"] if e["ledger"] == "digest_chain"]
        assert digest, "摘要链事件照常聚合"
        assert "chains=1" in digest[0]["basis"], \
            "chains 计数只含本租户活动链（acme 的链不计入）"
