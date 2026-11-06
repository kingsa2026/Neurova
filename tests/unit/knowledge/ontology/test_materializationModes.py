# -*- coding: utf-8 -*-
"""按规则类的物化档位（升级计划 §12.6 设计 3 ＋验收门点名判据）。

票面：物化按规则类分 `observe`/`enforce`（复用 B1 灰度），**observe 不进主路、
enforce 进**。B1 当年只落了「一条全局 env 管所有推导」的形态——那是一刀切，
不是按规则类：想让某一条低风险规则先进主路，只能把全部推导一起放行。

判据钉四件事：
1. 缺省档位是 observe，存量规则读回来就是 observe（加列不改旧行为）；
2. 全局灰度 off 时，observe 规则的跳板仍进不了主路，enforce 规则的跳板进得来
   且带 `via_derived`（标注跟着档位走，不是只放数据不放出处）；
3. 档位**逐行独立**：同一 statement 被两条不同档位的规则各推一次时，账本里是两行
   结论（探针实测，内容键带来源），hide 集里只许有 observe 那一行；
4. 档位是声明字段：REST 登记/改版走「未提供即保留现值」，流水线 diff 看得见它，
   未知档位写入处拒（400 而非默默当 observe）。

红要红在行为上：本档不 import 待建模块，只用既有装配点（真咽喉＋真走查）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.graph_walk import GraphFactWalker
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE, OntologyTermRegistry

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
ENTRY_ID = "docMode1"
PREFIX = "/v1/knowledge"


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s)
    monkeypatch.delenv("NEUROVA_CONDITION_CLASSES_ROUTE", raising=False)
    yield s
    s.close()


@pytest.fixture
def client(store):
    from neurova.api.endpoints import knowledge_ontology

    app = FastAPI()
    app.include_router(knowledge_ontology.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(ADMIN)
    return TestClient(app)


def _admitRow(store, subject, predicate, obj, mediumRef="unit:test"):
    content = "%s %s %s" % (subject, predicate, obj)
    return productionAdmissionGate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": mediumRef, "statementText": content}],
    )).factId


def _seedModeVocabulary(store):
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "Order", "kind": "concept", "label": "订单"},
        {"termId": "HighRiskOrder", "kind": "concept", "label": "高风险订单"},
        {"termId": "hasRiskLevel", "kind": "relation", "label": "风险等级"},
        {"termId": "hasPriority", "kind": "relation", "label": "优先级"},
        {"termId": "requiresAction", "kind": "relation", "label": "需动作"},
    ])
    # 挂条目那一跳必须是显式事实：条目进排序只能走显式断言的介质
    _admitRow(store, "HighRiskOrder", "requiresAction", "复核",
              mediumRef="entry:%s" % ENTRY_ID)
    _admitRow(store, "订单M01", IS_A_PREDICATE, "Order")
    _admitRow(store, "订单M01", "hasRiskLevel", "High")
    _admitRow(store, "订单M01", "hasPriority", "Urgent")
    registry.assignSubjectType(
        store.resolveSubjectKey("default", "订单M01"), "Order")
    return registry


def _registerModeRule(store, ruleId, premisePredicate, premiseConst, *, mode=None):
    engine = ForwardChainingEngine(store,
                                   gateFactory=lambda st: productionAdmissionGate(st))
    kwargs = {} if mode is None else {"materialization": mode}
    return engine.registerRule(
        ruleId, IS_A_PREDICATE,
        [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "Order"},
         {"atom": premisePredicate, "subject": "X", "objectConst": premiseConst}],
        headObjectConst="HighRiskOrder", tenantId="default", **kwargs)


def _modeWalkEntries(store):
    hops = GraphFactWalker(store, agentId="default").walkFromQuery(
        "订单M01 风险", limit=10)
    return [h for h in hops if h.get("entry_id") == ENTRY_ID]


class TestModeDefaults:
    def testExistingRulesReadBackAsObserve(self, store):
        _seedModeVocabulary(store)
        rule = _registerModeRule(store, "rule_default", "hasRiskLevel", "High")
        assert rule["materialization"] == "observe", (
            "缺省档位不是 observe——加个列就把存量规则集体转正了")

    def testInvalidModeRejectedAtWrite(self, store):
        _seedModeVocabulary(store)
        with pytest.raises(ValueError):
            _registerModeRule(store, "rule_bad", "hasRiskLevel", "High",
                              mode="materialize_always")


class TestEnforceEntersMainPath:
    def testObserveBridgeStaysOutOfMainPathWhenGateOff(self, store):
        """对照格：全局灰度 off ＋ observe ⇒ 主路不进（B1 既有行为不许被档位改动带走）。"""
        _seedModeVocabulary(store)
        _registerModeRule(store, "rule_observe", "hasRiskLevel", "High",
                          mode="observe")
        assert _modeWalkEntries(store) == []

    def testEnforceBridgeEntersMainPathWithGateOff(self, store):
        _seedModeVocabulary(store)
        _registerModeRule(store, "rule_enforce", "hasRiskLevel", "High",
                          mode="enforce")
        entryHops = _modeWalkEntries(store)
        assert entryHops, (
            "enforce 档的推导跳板仍被排除——档位没接进走查的排除片段")
        assert entryHops[0]["via_derived"] is True, (
            "放行了数据却没放出处：档位进主路时必须仍标得出「这条是推出来的」")

    def testPerRuleRowsFollowTheirOwnMode(self, store):
        """档位逐行独立：同一 statement 被两条规则各推一次，账本里是**两行**结论。

        探针实测（2026-11-06）：条件类推导的内容键带着规则来源，第二条规则不会
        并进第一行 ⇒ 不存在"一行同时挂 observe 与 enforce 两种档位"的混合态。
        本格因此钉可达形态：hide 集里只许有 observe 档那一行，
        enforce 档那一行进主路（把条目顶上来）。
        """
        _seedModeVocabulary(store)
        _registerModeRule(store, "rule_enforce", "hasRiskLevel", "High",
                          mode="enforce")
        _registerModeRule(store, "rule_observe", "hasPriority", "Urgent",
                          mode="observe")

        ledger = store._derivationLedger
        derived = set(ledger.derivedFactIds())
        hidden = set(ledger.hiddenDerivedFactIds("default"))
        assert len(derived) == 2, (
            "两条规则没各推一行（实得 %d 行）——本格的机制前提变了，判据要跟着改" % len(derived))
        assert hidden and hidden < derived, "hide 集要么空要么全集——档位没在行间分开"
        assert all(_ruleModesOf(store, fid) == {"observe"} for fid in hidden), (
            "被摘的行里有 enforce 档——读面/走查摘错了对象")
        for fid in derived - hidden:
            assert "enforce" in _ruleModesOf(store, fid)
        assert _modeWalkEntries(store), "enforce 档那一行该把条目顶进主路"

    def testGlobalRouteFlagStillOverridesEveryMode(self, store, monkeypatch):
        _seedModeVocabulary(store)
        _registerModeRule(store, "rule_observe", "hasRiskLevel", "High",
                          mode="observe")
        monkeypatch.setenv("NEUROVA_CONDITION_CLASSES_ROUTE", "1")
        assert _modeWalkEntries(store), (
            "翻主路后 observe 也该进来——档位是灰度之下的细分，不是灰度之上的否决")


class TestReadSurfaceUsesTheSameModePredicate:
    def testFilterKeepsEnforceAndDropsObserve(self, store):
        from neurova.knowledge.derivation_citation import filterConditionClassFacts

        _seedModeVocabulary(store)
        _registerModeRule(store, "rule_enforce_rs", "hasRiskLevel", "High",
                          mode="enforce")
        _registerModeRule(store, "rule_observe_rs", "hasPriority", "Urgent",
                          mode="observe")
        derivedIds = set(store._derivationLedger.derivedFactIds())
        enforceRows = {fid for fid in derivedIds
                       if _ruleModesOf(store, fid) == {"enforce"}}
        observeRows = derivedIds - enforceRows
        assert enforceRows and observeRows, (
            "两条档位不同的规则没各自推出结论——本格什么都没判（判据空转）")

        pool = [{"lineage_id": fid, "text": "推导行"} for fid in sorted(derivedIds)]
        pool.append({"lineage_id": "fact_not_derived", "text": "显式行"})
        kept, dropped = filterConditionClassFacts(pool, store, tenantId="default")
        keptIds = {item["lineage_id"] for item in kept}

        assert "fact_not_derived" in keptIds, (
            "读面把显式事实也摘了——档位过滤不该碰原始行")
        assert enforceRows <= keptIds, (
            "enforce 档的推导行在读面仍被摘掉——读面与走查两套口径")
        assert not (observeRows & keptIds), "observe 档在读面漏放行"
        assert dropped == len(pool) - len(kept)


def _ruleModesOf(store, factId):
    """账本里这一行是由哪些档位的规则推出来的（判据侧的独立读法，不复用生产片段）。"""
    with store._lock:
        rows = store._conn.execute(
            "SELECT DISTINCT COALESCE(r.materialization, 'observe') AS mode"
            " FROM knowledge_derivation_edges e"
            " LEFT JOIN ontology_rules r"
            " ON r.rule_id = e.rule_id AND r.tenant_id = 'default'"
            " WHERE e.derived_fact_id = ?", (factId,)).fetchall()
    return {str(row["mode"]) for row in rows}


class TestModeIsADeclaredField:
    def testApiRegistersAndPutKeepsMode(self, client, store):
        _seedModeVocabulary(store)
        created = client.post(PREFIX + "/ontology/rules", json={
            "rule_id": "rule_api_enforce", "head_predicate": IS_A_PREDICATE,
            "head_object_const": "HighRiskOrder",
            "body": [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "Order"},
                     {"atom": "hasRiskLevel", "subject": "X", "objectConst": "High"}],
            "materialization": "enforce", "basis": "档位登记",
        })
        assert created.status_code == 200, created.text
        assert created.json()["data"]["rule"]["materialization"] == "enforce"

        kept = client.put(PREFIX + "/ontology/rules/rule_api_enforce", json={
            "head_predicate": IS_A_PREDICATE, "version": "1.1.0", "basis": "只改版",
        })
        assert kept.status_code == 200, kept.text
        assert kept.json()["data"]["rule"]["materialization"] == "enforce", (
            "PUT 省略档位把 enforce 擦回 observe——声明字段没走保留现值")

    def testApiRejectsUnknownModeWith400(self, client, store):
        _seedModeVocabulary(store)
        resp = client.post(PREFIX + "/ontology/rules", json={
            "rule_id": "rule_api_bad", "head_predicate": IS_A_PREDICATE,
            "head_object_const": "HighRiskOrder",
            "body": [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "Order"},
                     {"atom": "hasRiskLevel", "subject": "X", "objectConst": "High"}],
            "materialization": "yolo",
        })
        assert resp.status_code == 400

    def testPipelineDiffSeesModeChange(self, client, store):
        """发布面看得见档位：批次里改了 materialization，diff 不许当没发生。"""
        _seedModeVocabulary(store)
        run = client.post(PREFIX + "/ontology/pipeline/run", json={
            "agentId": "default", "ruleRegistrations": [{
                "ruleId": "rule_diff_observe", "headPredicate": IS_A_PREDICATE,
                "headObjectConst": "HighRiskOrder",
                "body": [{"atom": IS_A_PREDICATE, "subject": "X",
                          "objectConst": "Order"},
                         {"atom": "hasRiskLevel", "subject": "X",
                          "objectConst": "High"}],
                "materialization": "observe",
            }], "reason": "基线含档位"})
        assert run.status_code == 200, run.text
        baselineId = run.json()["data"]["baselineId"]

        ForwardChainingEngine(
            store, gateFactory=lambda st: productionAdmissionGate(st)).registerRule(
            "rule_diff_observe", IS_A_PREDICATE,
            [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "Order"},
             {"atom": "hasRiskLevel", "subject": "X", "objectConst": "High"}],
            headObjectConst="HighRiskOrder", materialization="enforce",
            tenantId="default")

        diff = client.get(PREFIX + "/ontology/pipeline/diff",
                          params={"fromBaseline": baselineId})
        assert diff.status_code == 200
        changed = diff.json()["data"]["rules"]["changed"]
        assert [c["id"] for c in changed] == ["rule_diff_observe"], changed
        assert changed[0]["from"]["materialization"] == "observe"
        assert changed[0]["to"]["materialization"] == "enforce"
