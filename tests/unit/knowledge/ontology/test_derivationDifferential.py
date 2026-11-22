# -*- coding: utf-8 -*-
"""U14 真值维护差分测试：增量精确撤销 ≡ 全量重放重建。

被验证的不变量：对同一批「规则 × 原始事实」做任意合法的变更序列（断言、撤销前提、
取代、到期、登记规则、改版规则、删除规则）之后，被测系统（模型 A：真 store ＋ 真
productionAdmissionGate，增量维护）处于不动点时的已证结论集，必须与参考实现
（模型 B：每步之后用全新 store 从零重放现存规则与现存原始事实、fireAll 到不动点）
逐条一致。比较按 (tenant_id, agent_id, 主体规范名, 谓词, 客体) 五元组进行——
推导按租户与 agent 分区，跨维度的同名结论不许互相冒充。

除对拍外，另钉两条模型 A 的账本自洽判据：
1. 每条活动结论都有前提边，且至少一条边指向 active 前提、至少一条边来自现存规则——
   「拿着死前提或死规则对外检索」都是断链；
2. 物化档读侧排除与账本一致：`hiddenDerivedFactIds` 必须等于「任一推导边来自非
   enforce 档即隐藏」的独立口径（判据侧用自己的登记簿，不复读 ontology_rules），
   且 A/B 的读侧可见结论集相等。

随机化：`random.Random(seed)` 固定种子遍历（15 种子 × 每序列 45 操作），失败时打印
种子与完整操作序列便于复现。规模控制：单 store 事实行数 ≤ 55，全部用内存库。
"""

from __future__ import annotations

import json
import random

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE, OntologyTermRegistry

TENANT = "default"
AGENTS = ("default", "alpha")
SEEDS = tuple(range(1, 16))
OPS_PER_SEED = 45
MAX_FACT_ROWS = 55
MAX_ACTIVE_RULES = 7
MAX_ITERATIONS = 25
PAST_STAMP = "2000-01-01T00:00:00+00:00"

CONCEPTS = ("Order", "HighRisk")
# 基座谓词分两个池：BODY_BASES 可进规则正文（正原子）；NEG_TARGETS 只作否定原子、
# 永不进任何规则正文——引擎的层号算法会把「出现在任何正文里的谓词」算出层号 0，
# 与首层 head 同层即判「分层无解」；否定目标永不进正文就永不参与层号，分层必有解。
BODY_BASES = ("part_of", "located_in")
NEG_TARGETS = ("touches",)
BASE_PREDICATES = BODY_BASES + NEG_TARGETS
# head 谓词分两个池：NEG_HEADS 只作否定规则的 head、永不进任何正文——其 head
# 只正依赖基座谓词，分层必有解；PLAIN_HEADS 可进非否定规则的正文（正环靠不动点
# 收敛，引擎放行）。这样随机序列里「先登记成环规则、后登记否定规则」也不会撞上
# 「正环＋否定＝分层无解」的合法形状边界。
NEG_HEADS = ("reachable",)
PLAIN_HEADS = ("nearby", "linked")
RISK_LEVELS = ("High", "Low")
SUBJECTS = ("甲", "乙", "丙", "丁", "戊", "己")

VOCAB_TERMS = [
    {"termId": "Order", "kind": "concept", "label": "订单"},
    {"termId": "HighRisk", "kind": "concept", "label": "高风险"},
    {"termId": "part_of", "kind": "relation", "label": "属于"},
    {"termId": "located_in", "kind": "relation", "label": "位于"},
    {"termId": "touches", "kind": "relation", "label": "邻接"},
    {"termId": "hasRiskLevel", "kind": "relation", "label": "风险等级"},
    {"termId": "reachable", "kind": "relation", "label": "可达"},
    {"termId": "nearby", "kind": "relation", "label": "邻近"},
    {"termId": "linked", "kind": "relation", "label": "关联"},
]


def _admitTo(gate, agentId: str, subject: str, predicate: str, obj: str) -> str:
    """经真咽喉写入一条三元组；内容格式与推导侧同源，保证两模型内容键一致。"""
    content = "%s %s %s" % (subject, predicate, obj)
    return gate.admit(AdmissionRequest(
        agentId=agentId, tenantId=TENANT, subjectLabel=subject,
        predicateTermId=predicate, objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "u14",
                     "mediumRef": "u14:assert", "statementText": content}],
    )).factId


def _provenSets(store):
    """(已证结论集, 读侧可见结论集)——均按五元组，且只数带推导边的活动事实。"""
    ledger = store._derivationLedger
    derived = set(ledger.derivedFactIds())
    hidden = set(ledger.hiddenDerivedFactIds(TENANT))
    proven, visible = set(), set()
    for fact in store.searchableFacts(tenantId=TENANT):
        if fact["fact_id"] not in derived:
            continue
        key = (fact["tenant_id"], fact["agent_id"], fact["canonical_label"],
               fact["predicate_term_id"], fact["object_term"])
        proven.add(key)
        if fact["fact_id"] not in hidden:
            visible.add(key)
    return proven, visible


class _DifferentialRun:
    """一个种子的完整对拍：模型 A 增量推进，模型 B 每步全量重建。"""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.opsLog = []
        self.ruleOrder = []          # 我登记的规则 id，按创建序
        self.ruleBook = {}           # ruleId -> 当前登记规格（registerRule 的 kwargs）
        self.modeByRule = {}         # ruleId -> 物化档（判据侧独立登记簿）
        self.ruleCounter = 0
        self.storeA = KnowledgeFactStore(":memory:")
        registry = OntologyTermRegistry(self.storeA)
        registry.registerMany(VOCAB_TERMS)
        self.gateA = productionAdmissionGate(self.storeA)
        self.engineA = ForwardChainingEngine(
            self.storeA, gateFactory=lambda st: productionAdmissionGate(st))

    def close(self) -> None:
        self.storeA.close()

    # ── 模型 A 的操作算子 ────────────────────────────────────

    def _admitA(self, agentId: str, subject: str, predicate: str, obj: str) -> str:
        try:
            return _admitTo(self.gateA, agentId, subject, predicate, obj)
        except ValueError as exc:  # 咽喉拒绝：如实记账，两模型都不落这条
            self.opsLog.append({"op": "admitRejected", "agent": agentId,
                                "triple": [subject, predicate, obj],
                                "reason": str(exc)})
            return ""

    def _derivedIds(self) -> set:
        return set(self.storeA._derivationLedger.derivedFactIds())

    def _activeFacts(self) -> list:
        return self.storeA.searchableFacts(tenantId=TENANT)

    def _activeBaseFacts(self) -> list:
        derived = self._derivedIds()
        base = [f for f in self._activeFacts() if f["fact_id"] not in derived]
        base.sort(key=lambda f: (f["recorded_at"], f["fact_id"]))
        return base

    def _factRowCount(self) -> int:
        with self.storeA._lock:
            return int(self.storeA._conn.execute(
                "SELECT COUNT(*) AS n FROM knowledge_facts").fetchone()["n"])

    def op_assertFact(self) -> None:
        agent = self.rng.choice(AGENTS)
        subject = self.rng.choice(SUBJECTS)
        roll = self.rng.random()
        if roll < 0.25:
            predicate, obj = IS_A_PREDICATE, self.rng.choice(CONCEPTS)
        elif roll < 0.45:
            predicate, obj = "hasRiskLevel", self.rng.choice(RISK_LEVELS)
        else:
            predicate = self.rng.choice(BASE_PREDICATES)
            obj = self.rng.choice([s for s in SUBJECTS if s != subject])
        factId = self._admitA(agent, subject, predicate, obj)
        self.opsLog.append({"op": "assertFact", "agent": agent,
                            "triple": [subject, predicate, obj], "factId": factId})

    def op_retractFact(self) -> None:
        candidates = self._activeFacts()
        if not candidates:
            return
        victim = self.rng.choice(candidates)
        self.storeA.retract(victim["fact_id"], reason="u14 撤销前提")
        self.opsLog.append({"op": "retractFact", "factId": victim["fact_id"],
                            "triple": [victim["canonical_label"],
                                       victim["predicate_term_id"],
                                       victim["object_term"]]})

    def op_supersedeBase(self) -> None:
        base = self._activeBaseFacts()
        if not base:
            return
        old = self.rng.choice(base)
        subject, predicate, oldObj = (old["canonical_label"],
                                      old["predicate_term_id"], old["object_term"])
        if predicate == IS_A_PREDICATE:
            rivals = [c for c in CONCEPTS if c != oldObj]
        elif predicate == "hasRiskLevel":
            rivals = [r for r in RISK_LEVELS if r != oldObj]
        else:
            rivals = [s for s in SUBJECTS if s != oldObj]
        if not rivals:
            return
        rivalObj = self.rng.choice(rivals)
        rivalId = self._admitA(old["agent_id"], subject, predicate, rivalObj)
        # 取代只发生在双 active 上：新说法按内容键折回已退档行时不复活（咽喉语义），
        # 这种重复主张跳过即可——两模型的活性集都由 A 的现状决定，不受影响。
        if rivalId \
                and (self.storeA.fact(rivalId) or {}).get("status") == "active" \
                and (self.storeA.fact(old["fact_id"]) or {}).get("status") == "active":
            self.storeA.supersede(rivalId, old["fact_id"], reason="u14 取代旧说法")
        self.opsLog.append({"op": "supersedeBase", "agent": old["agent_id"],
                            "old": [subject, predicate, oldObj],
                            "new": [subject, predicate, rivalObj]})

    def op_expireBase(self) -> None:
        base = self._activeBaseFacts()
        if not base:
            return
        victim = self.rng.choice(base)
        self.storeA.setValidUntil(victim["fact_id"], PAST_STAMP)
        self.storeA.expireDueFacts(tenantId=TENANT)
        self.opsLog.append({"op": "expireBase", "factId": victim["fact_id"]})

    def op_assertNegationBlock(self) -> None:
        """对否定规则的已证结论补一条否定前提——把「结论先推、否定后到」的时序
        高频化。这是真值维护最关键也最难随机撞上的场景：否定前提晚于结论到达时，
        增量系统必须退掉被阻断的结论才与全量重放一致。"""
        derived = self._derivedIds()
        candidates = [f for f in self._activeFacts() if f["fact_id"] in derived]
        if not candidates:
            return
        victim = self.rng.choice(candidates)
        for edge in self.storeA._derivationLedger.premisesOf(victim["fact_id"]):
            rule = self.engineA.rule(edge["rule_id"], tenantId=TENANT) or {}
            if rule.get("shape") != "relay":
                continue
            negated = [a["predicate"] for a in rule.get("body") or []
                       if a.get("kind") == "not"]
            if not negated:
                continue
            predicate = self.rng.choice(negated)
            factId = self._admitA(victim["agent_id"], victim["canonical_label"],
                                  predicate, victim["object_term"])
            self.opsLog.append({"op": "assertNegationBlock", "agent": victim["agent_id"],
                                "triple": [victim["canonical_label"], predicate,
                                           victim["object_term"]],
                                "factId": factId})
            return
        self.opsLog.append({"op": "assertNegationBlock", "noop": True})

    # ── 规则算子（只生成合法形状） ───────────────────────────

    def _generateRuleSpec(self) -> dict:
        self.ruleCounter += 1
        ruleId = "u14_r%d" % self.ruleCounter
        mode = "enforce" if self.rng.random() < 0.3 else "observe"
        shape = self.rng.choices(
            ("relay", "relay_neg", "conjunction", "inverse", "inverse_neg"),
            weights=(38, 17, 20, 15, 10))[0]
        spec = {"ruleId": ruleId, "tenantId": TENANT, "version": "v1",
                "materialization": mode}
        if shape in ("conjunction",):
            spec.update({
                "headPredicate": IS_A_PREDICATE,
                "headObjectConst": self.rng.choice(CONCEPTS),
                "shape": "conjunction",
                "body": self._conjunctionBody(withNegation=False),
            })
        elif shape == "relay":
            spec.update({"headPredicate": self.rng.choice(PLAIN_HEADS),
                         "shape": "relay",
                         "body": self._relayBody(withNegation=False)})
        elif shape == "relay_neg":
            spec.update({"headPredicate": self.rng.choice(NEG_HEADS),
                         "shape": "relay",
                         "body": self._relayBody(withNegation=True)})
        elif shape == "inverse":
            spec.update({"headPredicate": self.rng.choice(PLAIN_HEADS),
                         "shape": "inverse", "headSubjectVar": "Y",
                         "body": [{"atom": self.rng.choice(BODY_BASES),
                                   "subject": "X", "object": "Y"}]})
        else:  # inverse_neg：否定原子按 _fireInverse 的口径钉在正文变元 (X, Y) 上
            spec.update({"headPredicate": self.rng.choice(NEG_HEADS),
                         "shape": "inverse", "headSubjectVar": "Y",
                         "body": [{"atom": self.rng.choice(BODY_BASES),
                                   "subject": "X", "object": "Y"},
                                  {"not": self.rng.choice(NEG_TARGETS),
                                   "subject": "X", "object": "Y"}]})
        return spec

    def _relayBody(self, withNegation: bool) -> list:
        # 带否定的规则正文正原子只用 BODY_BASES：head 不经正文正边自成环，分层必有解
        # （引擎拒「正环＋否定」的规则，随机生成器不得产出这种非法形状）。
        pool = list(BODY_BASES) if withNegation \
            else list(BODY_BASES) + list(PLAIN_HEADS)
        body = [{"atom": self.rng.choice(pool), "subject": "X", "object": "Y"}]
        if self.rng.random() < 0.6 or withNegation:
            body.append({"atom": self.rng.choice(pool), "subject": "Y", "object": "Z"})
        if withNegation and len(body) == 2:
            # 否定只指向 NEG_TARGETS（永不作 head、永不进其他正文）——分层必有解；
            # 变元按 _negatedHolds 的实际评估口径钉在 head 绑定 (X, Z) 上。
            body.append({"not": self.rng.choice(NEG_TARGETS),
                         "subject": "X", "object": "Z"})
        return body

    def _conjunctionBody(self, withNegation: bool) -> list:
        body = [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "Order"}]
        if self.rng.random() < 0.7:
            body.append({"atom": "hasRiskLevel", "subject": "X",
                         "objectConst": self.rng.choice(RISK_LEVELS)})
        if withNegation:
            body.append({"not": "hasRiskLevel", "subject": "X",
                         "objectConst": self.rng.choice(RISK_LEVELS)})
        return body

    def op_registerRule(self) -> None:
        if len(self.ruleOrder) >= MAX_ACTIVE_RULES:
            return self.op_reviseRule()
        spec = self._generateRuleSpec()
        self.engineA.registerRule(**spec)
        self.ruleBook[spec["ruleId"]] = spec
        self.ruleOrder.append(spec["ruleId"])
        self.modeByRule[spec["ruleId"]] = spec["materialization"]
        self.opsLog.append({"op": "registerRule", "spec": self._publicSpec(spec)})

    def _publicSpec(self, spec: dict) -> dict:
        return {k: v for k, v in spec.items() if k != "tenantId"}

    def _myRules(self) -> list:
        return [rid for rid in self.ruleOrder if rid in self.ruleBook]

    def op_reviseRule(self) -> None:
        if not self._myRules():
            return self.op_registerRule()
        ruleId = self.rng.choice(self._myRules())
        spec = dict(self.ruleBook[ruleId])
        version = int(str(spec.get("version", "v1")).lstrip("v") or 1)
        spec["version"] = "v%d" % (version + 1)
        if self.rng.random() < 0.3:
            spec["materialization"] = ("enforce" if spec["materialization"] == "observe"
                                       else "observe")
        if self.rng.random() < 0.6:
            spec["body"] = self._mutateBody(spec)
        self.engineA.registerRule(**spec)
        self.ruleBook[ruleId] = spec
        self.modeByRule[ruleId] = spec["materialization"]
        self.opsLog.append({"op": "reviseRule", "ruleId": ruleId,
                            "spec": self._publicSpec(spec)})

    def _mutateBody(self, spec: dict) -> list:
        body = [dict(atom) for atom in spec["body"]]
        # 与生成同一条纪律：带否定的规则，正原子变异不得引入 head 谓词，
        # 否定原子只能在 NEG_TARGETS 里换（进正文的谓词会被层号算法算出层号）。
        hasNegation = any("not" in atom for atom in body)
        pool = list(BODY_BASES) if hasNegation \
            else list(BODY_BASES) + list(PLAIN_HEADS)
        index = self.rng.randrange(len(body))
        atom = body[index]
        if "objectConst" in atom or atom.get("objectConst"):
            if atom.get("atom") == IS_A_PREDICATE or atom.get("not") == IS_A_PREDICATE:
                atom["objectConst"] = self.rng.choice(CONCEPTS)
            else:
                atom["objectConst"] = self.rng.choice(RISK_LEVELS)
        elif "not" in atom:
            atom["not"] = self.rng.choice(NEG_TARGETS)
        else:
            atom["atom"] = self.rng.choice(pool)
        return body

    def op_dropRule(self) -> None:
        if not self._myRules():
            return
        ruleId = self.rng.choice(self._myRules())
        self.engineA.dropRule(ruleId, reason="u14 删除规则", tenantId=TENANT)
        self.ruleBook.pop(ruleId, None)
        self.ruleOrder.remove(ruleId)
        self.modeByRule.pop(ruleId, None)
        self.opsLog.append({"op": "dropRule", "ruleId": ruleId})

    # ── 推进与对拍 ───────────────────────────────────────────

    def step(self, index: int) -> None:
        operators = (self.op_assertFact, self.op_assertFact, self.op_assertFact,
                     self.op_retractFact, self.op_retractFact,
                     self.op_supersedeBase, self.op_expireBase,
                     self.op_assertNegationBlock, self.op_assertNegationBlock,
                     self.op_registerRule, self.op_registerRule,
                     self.op_reviseRule, self.op_dropRule)
        before = self.opsLog
        operator = self.rng.choice(operators)
        if operator is self.op_assertFact and self._factRowCount() >= MAX_FACT_ROWS:
            operator = self.op_retractFact
        operator()
        if self.opsLog is before:  # 算子没记账（如空转）时补一条占位，保持序列可读
            self.opsLog.append({"op": operator.__name__, "noop": True})
        self.opsLog[-1]["step"] = index
        # 与 pipeline.py 的批处理契约一致：变更后对各 agent 推到不动点再对拍
        for agent in AGENTS:
            self.engineA.fireAll(agentId=agent, maxIterations=MAX_ITERATIONS)

    def _buildReference(self) -> KnowledgeFactStore:
        """模型 B：全新 store 重注册现存规则 → 重放现存原始事实 → fireAll 到不动点。"""
        store = KnowledgeFactStore(":memory:")
        registry = OntologyTermRegistry(store)
        registry.registerMany(VOCAB_TERMS)
        gate = productionAdmissionGate(store)
        engine = ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(st))
        for ruleId in self.ruleOrder:
            engine.registerRule(**self.ruleBook[ruleId])
        for fact in self._activeBaseFacts():
            _admitTo(gate, fact["agent_id"], fact["canonical_label"],
                     fact["predicate_term_id"], fact["object_term"])
        for agent in AGENTS:
            engine.fireAll(agentId=agent, maxIterations=MAX_ITERATIONS)
        return store

    def _expectedHidden(self) -> set:
        """独立口径：任一推导边来自非 enforce 档（含规则已删）即隐藏。"""
        hidden = set()
        with self.storeA._lock:
            rows = self.storeA._conn.execute(
                "SELECT DISTINCT derived_fact_id AS d, rule_id AS r"
                " FROM knowledge_derivation_edges").fetchall()
        for row in rows:
            if self.modeByRule.get(row["r"], "observe") != "enforce":
                hidden.add(row["d"])
        return hidden

    def _checkLedgerConsistency(self) -> str:
        ledger = self.storeA._derivationLedger
        surviving = {r["rule_id"] for r in
                     self.engineA.rules(includeDisabled=True, tenantId=TENANT)}
        active = {f["fact_id"] for f in self._activeFacts()}
        for factId in ledger.derivedFactIds():
            if factId not in active:
                continue
            premises = ledger.premisesOf(factId)
            if not premises:
                return "活动结论 %s 没有任何前提边" % factId
            if not any((self.storeA.fact(p["premise_fact_id"]) or {}).get("status") == "active"
                       for p in premises):
                return "活动结论 %s 的前提已全部离场（拿着死前提对外检索）" % factId
            if not any(p["rule_id"] in surviving for p in premises):
                return "活动结论 %s 只挂着已删除的规则（拿着死规则对外检索）" % factId
        return ""

    def compare(self) -> str:
        storeB = self._buildReference()
        try:
            provenA, visibleA = _provenSets(self.storeA)
            provenB, visibleB = _provenSets(storeB)
            if provenA != provenB:
                return ("已证结论集不一致\n  仅 A 有: %s\n  仅 B 有: %s"
                        % (sorted(provenA - provenB), sorted(provenB - provenA)))
            hiddenA = set(self.storeA._derivationLedger.hiddenDerivedFactIds(TENANT))
            expected = self._expectedHidden()
            if hiddenA != expected:
                return ("物化档隐藏集与独立口径不一致\n  账本隐藏: %s\n  独立口径: %s"
                        % (sorted(hiddenA), sorted(expected)))
            hiddenB = set(storeB._derivationLedger.hiddenDerivedFactIds(TENANT))
            if visibleA != visibleB:
                return ("读侧可见结论集不一致\n  仅 A 可见: %s\n  仅 B 可见: %s"
                        "\n  (隐藏集 A=%s B=%s)"
                        % (sorted(visibleA - visibleB), sorted(visibleB - visibleA),
                           sorted(hiddenA), sorted(hiddenB)))
            return self._checkLedgerConsistency()
        finally:
            storeB.close()

    def failureReport(self, reason: str) -> str:
        return ("[seed=%d] %s\n操作序列:\n%s"
                % (self.seed, reason,
                   json.dumps(self.opsLog, ensure_ascii=False, indent=1)))


def _runSeed(seed: int) -> None:
    run = _DifferentialRun(seed)
    try:
        for index in range(OPS_PER_SEED):
            run.step(index)
            reason = run.compare()
            if reason:
                pytest.fail(run.failureReport(reason))
        reason = run.compare()
        if reason:
            pytest.fail(run.failureReport(reason))
    finally:
        run.close()


@pytest.mark.parametrize("seed", SEEDS)
def test_incrementalRetractionMatchesFullReplay(seed):
    """随机操作序列差分对拍：增量精确撤销与全量重放重建逐条一致。"""
    _runSeed(seed)


def test_negationBlockThenRetractMatchesReplay():
    """确定性回归样例（U14 首跑在此暴露过不一致）：分层否定的真值维护。

    结论先推出 → 否定前提后到：被阻断的结论必须退场（全量重放推不出它）；
    否定前提再撤销：结论必须经重推长回来。两步都要与全新 store 的全量重放一致。
    """

    def scenario(store):
        registry = OntologyTermRegistry(store)
        registry.registerMany(VOCAB_TERMS)
        gate = productionAdmissionGate(store)
        engine = ForwardChainingEngine(
            store, gateFactory=lambda st: productionAdmissionGate(st))
        engine.registerRule("u14_neg_relay", "reachable", [
            {"atom": "part_of", "subject": "X", "object": "Y"},
            {"atom": "part_of", "subject": "Y", "object": "Z"},
            {"not": "touches", "subject": "X", "object": "Z"},
        ], materialization="enforce", tenantId=TENANT)
        _admitTo(gate, "default", "甲", "part_of", "乙")
        _admitTo(gate, "default", "乙", "part_of", "丙")
        for agent in AGENTS:
            engine.fireAll(agentId=agent, maxIterations=MAX_ITERATIONS)
        return gate, engine

    storeA = KnowledgeFactStore(":memory:")
    try:
        gateA, engineA = scenario(storeA)
        provenA, _ = _provenSets(storeA)
        assert ("default", "default", "甲", "reachable", "丙") in provenA, \
            "前提齐备且否定不成立时，结论该在已证集里"

        # 否定前提后到：结论必须退场
        _admitTo(gateA, "default", "甲", "touches", "丙")
        for agent in AGENTS:
            engineA.fireAll(agentId=agent, maxIterations=MAX_ITERATIONS)
        provenA, _ = _provenSets(storeA)
        assert ("default", "default", "甲", "reachable", "丙") not in provenA, \
            "否定前提成立后，被阻断的结论不许继续对外检索"

        # 对照：全新 store 全量重放，同样推不出这条
        storeB = KnowledgeFactStore(":memory:")
        try:
            scenario(storeB)
            _admitTo(productionAdmissionGate(storeB), "default", "甲", "touches", "丙")
            provenB, _ = _provenSets(storeB)
            assert ("default", "default", "甲", "reachable", "丙") not in provenB
        finally:
            storeB.close()

        # 否定前提撤销后：结论经重推长回来（撤销比故障更持久就是错的）
        with storeA._lock:
            row = storeA._conn.execute(
                "SELECT fact_id FROM knowledge_facts"
                " WHERE predicate_term_id = 'touches' AND object_term = '丙'").fetchone()
        storeA.retract(row["fact_id"], reason="撤销否定前提")
        for agent in AGENTS:
            engineA.fireAll(agentId=agent, maxIterations=MAX_ITERATIONS)
        provenA, _ = _provenSets(storeA)
        assert ("default", "default", "甲", "reachable", "丙") in provenA, \
            "否定前提离场后，结论必须经重推长回来"
    finally:
        storeA.close()
