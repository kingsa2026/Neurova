# -*- coding: utf-8 -*-
"""U5 Rete v2 求值档：AlphaNode / BetaNode / TerminalNode 网络。

判据全部走真装配（真 store ＋ 真 productionAdmissionGate 咽喉），红要红在行为上：
1. 等价性对拍（核心）——同一规则集（relay 链、3 原子 relay、3 原子合取、inverse、
   分层否定）在 full_replay（semi-naive）与 rete_network 两策略下结论集逐条相等；
2. 3 原子放宽只在 rete_network 注册档生效，默认语言注册仍被拒；
3. rete_network 档的推导过咽喉（qualifier 带 derived_by、断言介质指到规则）；
4. 激活去重——同规则同绑定只点火一次（对咽喉 admit 的触发记录为证）；
5. 分层否定在 rete 档与 semi-naive 同判。
"""

from __future__ import annotations

import json

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology import rule_engine
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine, RuleError
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE, OntologyTermRegistry

TERMS = [
    {"termId": "device", "kind": "concept", "label": "设备"},
    {"termId": "goldDevice", "kind": "concept", "label": "金牌设备"},
    {"termId": IS_A_PREDICATE, "kind": "relation", "label": "是一个"},
    {"termId": "linked", "kind": "relation", "label": "连接"},
    {"termId": "linkedFrom", "kind": "relation", "label": "反向连接"},
    {"termId": "reachable", "kind": "relation", "label": "可达"},
    {"termId": "hop3", "kind": "relation", "label": "三跳可达"},
    {"termId": "hasTier", "kind": "relation", "label": "服务档位"},
    {"termId": "inRegion", "kind": "relation", "label": "所在区域"},
    {"termId": "blocked", "kind": "relation", "label": "阻断"},
    {"termId": "watch", "kind": "relation", "label": "监视"},
]

# 3 原子接力链：默认语言拒收、rete_network 档放行的同一份 body
HOP3_BODY = [{"atom": "linked", "subject": "S", "object": "M"},
             {"atom": "linked", "subject": "M", "object": "N"},
             {"atom": "linked", "subject": "N", "object": "W"}]


def _admit(gate, subject, predicate, obj):
    content = "%s %s %s" % (subject, predicate, obj)
    return gate.admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}],
    )).factId


def _registerRules(engine):
    """同一规则集（relay 互递归 / 3 原子 relay / 3 原子合取 / inverse / 分层否定）。

    ≤2 原子的规则走默认语言；两条 3 原子规则显式带 evaluationStrategy="rete_network"。
    """
    engine.registerRule(
        "reach_base", "reachable",
        body=[{"atom": "linked", "subject": "S", "object": "O"}],
        headSubjectVar="S", materialization="enforce", tenantId="default")
    engine.registerRule(
        "reach_rec", "reachable",
        body=[{"atom": "linked", "subject": "S", "object": "M"},
              {"atom": "reachable", "subject": "M", "object": "O"}],
        headSubjectVar="S", materialization="enforce", tenantId="default")
    engine.registerRule(
        "hop3_rule", "hop3", HOP3_BODY,
        headSubjectVar="S", materialization="enforce",
        evaluationStrategy="rete_network", tenantId="default")
    engine.registerRule(
        "gold_rule", IS_A_PREDICATE,
        body=[{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "device"},
              {"atom": "hasTier", "subject": "X", "objectConst": "gold"},
              {"atom": "inRegion", "subject": "X", "objectConst": "cn"}],
        headObjectConst="goldDevice", materialization="enforce",
        evaluationStrategy="rete_network", tenantId="default")
    engine.registerRule(
        "linked_inv", "linkedFrom",
        body=[{"atom": "linked", "subject": "X", "object": "Y"}],
        headSubjectVar="Y", shape="inverse", materialization="enforce",
        tenantId="default")
    engine.registerRule(
        "watch_rule", "watch",
        body=[{"atom": "linked", "subject": "S", "object": "T"},
              {"not": "blocked", "subject": "S", "object": "T"}],
        headSubjectVar="S", materialization="enforce", tenantId="default")


def _seedFacts(gate):
    # 否定事实先落：分层否定判据在推导首跑时成形（咽喉每次写入都点燃 fireFor，
    # 后到的反例不回溯撤结论——与 test_forward_chaining 的否定用例同一前提次序）。
    _admit(gate, "B", "blocked", "C")
    # 两条链 + 一个菱形（同头绑定多路径，检验前提合并语义两策略一致）
    for pair in (("A", "B"), ("B", "C"), ("C", "D"),
                 ("E", "F"), ("F", "H"), ("E", "G"), ("G", "H")):
        _admit(gate, pair[0], "linked", pair[1])
    _admit(gate, "A", "hasTier", "gold")
    _admit(gate, "A", "inRegion", "cn")
    _admit(gate, "A", IS_A_PREDICATE, "device")


def _buildKb(tmp_path, name):
    s = KnowledgeFactStore(str(tmp_path / ("%s.db" % name)))
    registry = OntologyTermRegistry(s)
    registry.registerMany(TERMS)
    gate = productionAdmissionGate(s)
    engine = ForwardChainingEngine(s, gateFactory=lambda st: productionAdmissionGate(st))
    _registerRules(engine)
    _seedFacts(gate)
    return s, registry, gate, engine


def _conclusions(store):
    """全量活动结论（含被推出的）：(谓词, 主体规范标签, 客体, derived_by)。"""
    with store._lock:
        rows = store._conn.execute(
            "SELECT f.predicate_term_id AS p, f.object_term AS o,"
            " f.qualifier_json AS q, s.canonical_label AS label"
            " FROM knowledge_facts f"
            " LEFT JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
            " WHERE f.status = 'active' AND f.record_kind = 'triple'").fetchall()
    out = []
    for r in rows:
        qualifier = json.loads(r["q"] or "{}")
        out.append((r["p"], str(r["label"] or ""), r["o"],
                    str(qualifier.get("derived_by") or "")))
    return sorted(out)


class TestReteNetworkEquivalence:
    def test_conclusionSetsIdenticalAcrossStrategies(self, tmp_path):
        """同一规则集在 full_replay 与 rete_network 下结论集逐条相等。"""
        sFull, _, _, engineFull = _buildKb(tmp_path, "full")
        sRete, _, _, engineRete = _buildKb(tmp_path, "rete")
        try:
            engineFull.setEvaluationStrategy("full_replay")
            engineFull.fireAll(agentId="default", tenantId="default")
            engineRete.setEvaluationStrategy("rete_network")
            assert engineRete.evaluationStrategy == "rete_network"
            engineRete.fireAll(agentId="default", tenantId="default")
            fullSet = _conclusions(sFull)
            reteSet = _conclusions(sRete)
            assert fullSet == reteSet, "两策略结论集逐字一致"
            # 非平凡性：五类形状都真的推出了结论
            derived = {c[0] for c in reteSet if c[3]}
            assert {"reachable", "hop3", "linkedFrom", "watch", IS_A_PREDICATE} \
                <= derived, "relay 链/3 原子链/3 原子合取/inverse/否定规则都应点火"
            # 3 原子链的具体结论：A→B→C→D ⇒ hop3(A,D)，且 hop3 不含两跳情形
            hop3 = {c[2] for c in reteSet if c[0] == "hop3" and c[1] == "A"}
            assert hop3 == {"D"}, "三原子接力只该推出 A 的三跳结论"
            # 菱形同头绑定：E 经 F/G 两路径到 H，结论只一行
            reachEH = [c for c in reteSet if c[0] == "reachable"
                       and c[1] == "E" and c[2] == "H"]
            assert len(reachEH) == 1, "同头绑定的多路径合并为一行结论"
        finally:
            sFull.close()
            sRete.close()

    def test_stratifiedNegationSameVerdict(self, tmp_path):
        """分层否定在 rete 档与 semi-naive 同判：被 blocked 否定的 watch 不落地。"""
        sFull, _, _, engineFull = _buildKb(tmp_path, "nfull")
        sRete, _, _, engineRete = _buildKb(tmp_path, "nrete")
        try:
            engineFull.fireAll(agentId="default", tenantId="default")
            engineRete.setEvaluationStrategy("rete_network")
            engineRete.fireAll(agentId="default", tenantId="default")
            for store in (sFull, sRete):
                watch = {(c[1], c[2]) for c in _conclusions(store)
                         if c[0] == "watch"}
                assert ("B", "C") not in watch, "被否定的结论不许落地"
                assert ("A", "B") in watch, "未否定的结论要落地"
            assert _conclusions(sFull) == _conclusions(sRete)
        finally:
            sFull.close()
            sRete.close()


class TestThreeAtomRelaxation:
    def test_threeAtomRuleRejectedByDefaultLanguage(self, tmp_path):
        """默认语言注册仍限 2 原子；档位闭集外（rete）也不放行。"""
        s = KnowledgeFactStore(str(tmp_path / "reject.db"))
        try:
            OntologyTermRegistry(s).registerMany(TERMS)
            engine = ForwardChainingEngine(
                s, gateFactory=lambda st: productionAdmissionGate(st))
            with pytest.raises(RuleError, match="超过 2 个原子"):
                engine.registerRule("hop3_default", "hop3", HOP3_BODY,
                                    tenantId="default")
            with pytest.raises(RuleError, match="rete_network"):
                engine.registerRule("hop3_bad_tier", "hop3", HOP3_BODY,
                                    evaluationStrategy="rete", tenantId="default")
            assert engine.rule("hop3_default") is None, "被拒的规则不许留下半行"
            assert engine.rule("hop3_bad_tier") is None
        finally:
            s.close()

    def test_threeAtomRuleFiresThroughGate(self, tmp_path):
        """rete_network 档注册的 3 原子规则正确点火，推导过咽喉（derived_by 在 qualifier）。"""
        s, _, _, engine = _buildKb(tmp_path, "gate")
        try:
            assert engine.rule("hop3_rule")["evaluation_strategy"] == "rete_network"
            engine.setEvaluationStrategy("rete_network")
            engine.fireAll(agentId="default", tenantId="default")
            hop3 = [f for f in s.searchableFacts(agentId="default")
                    if f["predicate_term_id"] == "hop3"]
            assert len(hop3) == 1, "3 原子链应推出一条 hop3 结论"
            fact = s.fact(hop3[0]["fact_id"])
            assert fact["qualifier"].get("derived_by") == "hop3_rule"
            assertions = s.assertions(fact["fact_id"])
            assert assertions[-1]["medium_ref"] == "rule:hop3_rule", \
                "推导事实的来源要指到规则，不能伪装成观察"
        finally:
            s.close()


class TestActivationDedup:
    def test_sameBindingFiresOnlyOnce(self, tmp_path, monkeypatch):
        """同规则＋同绑定只点火一次：对咽喉 admit 的触发记录不得出现重复。"""
        s, _, _, engine = _buildKb(tmp_path, "dedup")
        try:
            calls = []
            real = engine._admitDerivedFact

            def counting(rule, agentId, label, predicate, objectTerm,
                         subjectKey, premiseIds, tenantId="default"):
                calls.append((rule["rule_id"], subjectKey, predicate, objectTerm,
                              tuple(premiseIds)))
                return real(rule, agentId, label, predicate, objectTerm,
                            subjectKey, premiseIds, tenantId=tenantId)

            monkeypatch.setattr(engine, "_admitDerivedFact", counting)
            engine.setEvaluationStrategy("rete_network")
            engine.fireAll(agentId="default", tenantId="default")
            assert calls, "rete_network 档应有推导触发"
            assert len(calls) == len(set(calls)), \
                "同规则同绑定重复点火：%s" % (calls,)
        finally:
            s.close()


class TestStrategySlot:
    def test_defaultStrategyStillFullReplay(self, tmp_path):
        """缺省仍 full_replay；闭集新增 rete_network 不动存量。"""
        s, _, _, engine = _buildKb(tmp_path, "slot")
        try:
            assert engine.evaluationStrategy == "full_replay"
            assert rule_engine.EVALUATION_STRATEGIES == (
                "full_replay", "rete", "rete_network")
        finally:
            s.close()

    def test_networkNodeSurfaceExists(self):
        """网络三段节点与编排器是既定交付面。"""
        from neurova.knowledge.ontology.rete_network import (
            AlphaNode,
            BetaNode,
            ReteNetwork,
            TerminalNode,
        )

        assert AlphaNode is not None
        assert BetaNode is not None
        assert TerminalNode is not None
        assert ReteNetwork is not None
