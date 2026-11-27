# -*- coding: utf-8 -*-
"""反向链证明器（本体域升级卡 U12）：从目标三元组反向搜索证明。

与前向链（`rule_engine`）严格分轨：前向链**写**（推导事实经咽喉落库），
本模块**只读**——不写任何表、不产生派生事实、不调 admit。

已证事实集的口径与检索主路一致，判据单源在推导账本
（`derivation_ledger.derivedExclusionClause`）：原始断言 + enforce 档派生算已证；
observe 档派生只留在解释链/审计里，不当作已证事实。因此一条前向链已物化的
observe 档结论，在这里仍会走规则展开重新给出证明树——这正是"定理证明"的用法。

规则读取复用 `ForwardChainingEngine._hydrate`（rule dict 的唯一解析出口，
不在这里抄第二份 body 形状），展开按登记的三种形状：
  relay        head(X,Z) :- b1(X,Y), b2(Y,Z)     head 客体取末原子客体变元
  conjunction  head(X,常量) :- b(X,常量), ...     同主体合取，head 客体是常量
  inverse      head(Y,X) :- b(X,Y)               head 主客对调

分层否定：`not p(X,Z)` 按「该目标在已证事实集中无证明」判定（与 rule_engine 的
分层语义一致——否定只指向更浅层已算完的谓词）。否定原子带未绑定变元、无法安全
判定时，该分支跳过并记 missing（reason=negation_unsupported），不猜。

环检测：目标三元组已在当前证明栈中 → 该分支剪枝（reason=cycle）。
深度上限：maxDepth 缺省取环境变量 NEUROVA_ONTOLOGY_PROVE_DEPTH（默认 16），
超限分支剪枝（reason=depth）。事实步不占深度，规则展开每层 +1。
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.tenant_scope import tenant_sql_where
from ..foundation.knowledge_facts import KnowledgeFactStore, normalizeLabel
from .rule_engine import ForwardChainingEngine

#: 与 rule_engine 同一口径：规则变元是单个大写字母。
_VAR = re.compile(r"^[A-Z]$")

#: 证明深度上限缺省值（规则展开层数）。
DEFAULT_PROVE_DEPTH = 16

#: 深度上限的环境变量名。
PROVE_DEPTH_ENV = "NEUROVA_ONTOLOGY_PROVE_DEPTH"


def _maxDepthFromEnv() -> int:
    """读环境变量里的深度上限；未设/非整数回落缺省值（与引擎策略槽同口径）。"""
    raw = str(os.environ.get(PROVE_DEPTH_ENV) or "").strip()
    if not raw:
        return DEFAULT_PROVE_DEPTH
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_PROVE_DEPTH


def proveGoal(store: Any, subjectTerm: str, predicateTerm: str, objectTerm: str, *,
              tenantId: str = "default", agentId: str = "default",
              maxDepth: Optional[int] = None) -> Dict[str, Any]:
    """从目标三元组 (subjectTerm, predicateTerm, objectTerm) 反向搜索证明。

    严格只读：不写任何表、不产生派生事实、不调 admit。
    谓词按 term_id 精确匹配（与前向链 join 同一口径）；主体词形经
    resolveSubjectKey 归一（大小写/别名不敏感、跟随合并）；客体词形
    精确相等或归一相等即命中。

    返回 {"proved": bool, "goal": {...}, "steps": [...], "missing": [...]}：
    - steps：证明树（根步 kind=rule|fact，ref=ruleId|factId，binding=变元绑定，
      sub=子证明）；proved=False 时为空列表；
    - missing：展开到深度上限仍缺的前提目标 [{goal, reason}]，reason 取
      unproven / cycle / depth / negation_blocked / negation_unsupported。
    """
    prover = _BackwardProver(store, tenantId=tenantId, agentId=agentId,
                             maxDepth=maxDepth)
    return prover.prove(str(subjectTerm or ""), str(predicateTerm or ""),
                        str(objectTerm or ""))


class _BackwardProver:
    """单次证明的上下文：规则表、已证事实集、深度上限。

    一次性装载数据、在内存里做合一与回溯；全部 SQL 都是 SELECT，
    且只经 `store._lock` 下的既有连接执行。
    """

    def __init__(self, store: Any, *, tenantId: str, agentId: str,
                 maxDepth: Optional[int]) -> None:
        self._store = store
        self._tenantId = str(tenantId or "default")
        self._agentId = str(agentId or "default")
        self._maxDepth = int(maxDepth) if maxDepth is not None else _maxDepthFromEnv()
        self._rules = self._loadRules()
        self._facts = self._loadProvenFacts()
        self._factsByPredicate: Dict[str, List[Dict[str, Any]]] = {}
        for fact in self._facts:
            self._factsByPredicate.setdefault(fact["predicate"], []).append(fact)

    # ── 数据装载（全部只读）─────────────────────────────────

    def _loadRules(self) -> List[Dict[str, Any]]:
        """读本租户启用规则；body 形状解析复用前向链的 _hydrate（单一事实源）。"""
        tenantClause, tenantParams = tenant_sql_where(self._tenantId)
        sql = "SELECT * FROM ontology_rules WHERE enabled = 1"
        params: List[Any] = []
        if tenantClause:
            sql += " AND " + tenantClause
            params.extend(tenantParams)
        sql += " ORDER BY stratification_level, rule_id"
        with self._store._lock:
            rows = self._store._conn.execute(sql, params).fetchall()
        return [ForwardChainingEngine._hydrate(row) for row in rows]

    def _loadProvenFacts(self) -> List[Dict[str, Any]]:
        """已证事实集：active 三元组 − observe 档派生（判据单源在账本）。

        与 searchableFacts 同口径：未过期、主体未并入他者；按 agent 收窄
        （推导事实的属主即 admit 的 agentId）。"""
        tenantClause, tenantParams = tenant_sql_where(self._tenantId, alias="f")
        currentClause, currentParams = KnowledgeFactStore.currentFactWhere("f")
        sql = ("SELECT f.fact_id, f.subject_key, f.predicate_term_id, f.object_term,"
               " s.canonical_label FROM knowledge_facts f"
               " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
               " AND s.agent_id = f.agent_id"
               " WHERE f.agent_id = ? AND " + currentClause +
               " AND f.record_kind = 'triple'"
               " AND s.status != 'merged'")
        params: List[Any] = [self._agentId, *currentParams]
        if tenantClause:
            sql += " AND " + tenantClause
            params.extend(tenantParams)
        # observe 档排除片段由账本单源提供（enforce 档派生照常算已证）。
        sql += " AND " + self._store._derivationLedger.derivedExclusionClause("f")
        sql += " ORDER BY f.fact_id"
        with self._store._lock:
            rows = self._store._conn.execute(sql, params).fetchall()
        return [{"factId": r["fact_id"], "subjectKey": r["subject_key"],
                 "predicate": r["predicate_term_id"], "object": r["object_term"],
                 "label": r["canonical_label"]} for r in rows]

    # ── 证明入口 ─────────────────────────────────────────────

    def prove(self, subjectTerm: str, predicateTerm: str,
              objectTerm: str) -> Dict[str, Any]:
        goal = {"subject": subjectTerm, "predicate": predicateTerm,
                "object": objectTerm}
        step, missing = self._proveGround(subjectTerm, predicateTerm, objectTerm,
                                          {}, 0, [])
        return {"proved": step is not None,
                "goal": goal,
                "steps": [step] if step is not None else [],
                "missing": self._dedupeMissing(missing)}

    def _proveGround(self, s: str, p: str, o: str, binding: Dict[str, str],
                     depth: int, stack: List[Tuple[str, str, str]]
                     ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """证明一个基例目标：先查已证事实，再枚举 head 可合一的规则。"""
        goalTriple = (s, p, o)
        if goalTriple in stack:
            # 环剪枝：这个目标正在当前证明路径上被证明，绕回去只会死循环。
            return None, [self._missingEntry(s, p, o, "cycle")]
        fact = self._matchFact(s, p, o)
        if fact is not None:
            return {"kind": "fact", "ref": fact["factId"],
                    "binding": dict(binding), "sub": []}, []
        missing: List[Dict[str, Any]] = []
        for rule in self._rules:
            if rule["head_predicate"] != p:
                continue
            headBinding: Dict[str, str] = {}
            headSubj, headObj = self._headTerms(rule)
            if not self._unify(headSubj, s, headBinding):
                continue
            if not self._unify(headObj, o, headBinding):
                continue
            if depth + 1 > self._maxDepth:
                missing.append(self._missingEntry(s, p, o, "depth"))
                continue
            subSteps, subMissing = self._proveSeq(
                rule["body"], 0, headBinding, depth + 1, stack + [goalTriple])
            if subSteps is not None:
                return {"kind": "rule", "ref": rule["rule_id"],
                        "binding": headBinding, "sub": subSteps}, []
            missing.extend(subMissing)
        # 目标本身没证出来——它就是一条仍缺的前提；reason 交给 missing 说明。
        missing.append(self._missingEntry(s, p, o, "unproven"))
        return None, missing

    def _proveSeq(self, atoms: List[Dict[str, Any]], idx: int,
                  binding: Dict[str, str], depth: int,
                  stack: List[Tuple[str, str, str]]
                  ) -> Tuple[Optional[List[Dict[str, Any]]], List[Dict[str, Any]]]:
        """顺序证明 atoms[idx:]，变元绑定沿路径传递；返回 (子证明|None, 缺口)。"""
        if idx >= len(atoms):
            return [], []
        atom = atoms[idx]
        if atom["kind"] == "not":
            return self._proveNegated(atoms, idx, binding, depth, stack)
        subject = self._substitute(atom["subject"], binding)
        predicate = atom["predicate"]
        objectTerm, objectIsConst = self._atomObject(atom)
        if objectIsConst:
            objectValue = objectTerm
        else:
            objectValue = self._substitute(objectTerm, binding)
        if not _VAR.match(subject) and (objectIsConst or not _VAR.match(objectValue)):
            step, missing = self._proveGround(subject, predicate, objectValue,
                                              binding, depth, stack)
            if step is None:
                return None, missing
            rest, restMissing = self._proveSeq(atoms, idx + 1, binding, depth, stack)
            if rest is None:
                return None, missing + restMissing
            return [step] + rest, []
        # 变元未绑定：从已证事实集枚举候选基例，逐个回溯（枚举域=事实词形）。
        missing = []
        for candBinding, candS, candO in self._patternCandidates(
                subject, predicate, objectValue, objectIsConst, binding):
            step, candMissing = self._proveGround(candS, predicate, candO,
                                                  candBinding, depth, stack)
            if step is None:
                missing.extend(candMissing)
                continue
            rest, restMissing = self._proveSeq(atoms, idx + 1, candBinding,
                                               depth, stack)
            if rest is not None:
                return [step] + rest, []
            missing.extend(restMissing)
        return None, missing

    def _proveNegated(self, atoms: List[Dict[str, Any]], idx: int,
                      binding: Dict[str, str], depth: int,
                      stack: List[Tuple[str, str, str]]
                      ) -> Tuple[Optional[List[Dict[str, Any]]], List[Dict[str, Any]]]:
        """分层否定：否定原子 = 该目标在已证事实集中无证明。

        带未绑定变元时无法安全判定 → 跳过该分支记 negation_unsupported，不猜。"""
        atom = atoms[idx]
        subject = self._substitute(atom["subject"], binding)
        objectTerm, objectIsConst = self._atomObject(atom)
        objectValue = objectTerm if objectIsConst else self._substitute(objectTerm, binding)
        if _VAR.match(subject) or (not objectIsConst and _VAR.match(objectValue)):
            return None, [self._missingEntry(subject, atom["predicate"], objectValue,
                                             "negation_unsupported")]
        if self._matchFact(subject, atom["predicate"], objectValue) is not None:
            return None, [self._missingEntry(subject, atom["predicate"], objectValue,
                                             "negation_blocked")]
        return self._proveSeq(atoms, idx + 1, binding, depth, stack)

    # ── 合一与候选枚举 ────────────────────────────────────────

    def _patternCandidates(self, subject: str, predicate: str, objectTerm: str,
                           objectIsConst: bool, binding: Dict[str, str]
                           ) -> List[Tuple[Dict[str, str], str, str]]:
        """为带未绑定变元的 body 原子枚举候选基例（枚举域=已证事实集词形）。

        主体变元绑到事实的规范标签、客体变元绑到 object_term——绑定值始终
        落在词形空间，与目标/规则头同一表示。"""
        facts = self._factsByPredicate.get(predicate, [])
        subjectKey = None
        if _VAR.match(subject):
            subjectIsVar = True
        else:
            subjectIsVar = False
            subjectKey = self._store.resolveSubjectKey(
                self._agentId, subject, tenantId=self._tenantId)
            if subjectKey is None:
                return []
        objectIsVar = not objectIsConst and _VAR.match(objectTerm)
        candidates: List[Tuple[Dict[str, str], str, str]] = []
        for fact in facts:
            if subjectKey is not None and fact["subjectKey"] != subjectKey:
                continue
            if not objectIsVar and not self._objectMatches(fact["object"], objectTerm):
                continue
            if subjectIsVar and objectIsVar and subject == objectTerm and \
                    normalizeLabel(fact["label"]) != normalizeLabel(fact["object"]):
                continue  # 同名变元 p(X,X)：事实两侧词形对不上即不合
            cand = dict(binding)
            candSubject = subject
            candObject = objectTerm
            if subjectIsVar:
                cand[subject] = fact["label"]
                candSubject = fact["label"]
            if objectIsVar:
                cand[objectTerm] = fact["object"]
                candObject = fact["object"]
            candidates.append((cand, candSubject, candObject))
        return candidates

    @staticmethod
    def _unify(term: str, value: str, binding: Dict[str, str]) -> bool:
        """规则头项与目标项合一：变元绑定到目标词形（重复绑定须一致），常量须相等。"""
        if _VAR.match(term):
            bound = binding.get(term)
            if bound is None:
                binding[term] = value
                return True
            return bound == value
        return term == value

    @staticmethod
    def _substitute(term: str, binding: Dict[str, str]) -> str:
        """变元按绑定替换成词形值；未绑定/常量原样返回。"""
        if _VAR.match(term) and term in binding:
            return binding[term]
        return term

    @staticmethod
    def _atomObject(atom: Dict[str, Any]) -> Tuple[str, bool]:
        """body 原子的客体项：relay/inverse 用变元 object，conjunction 用常量
        objectConst。返回 (项, 是否常量)。"""
        if atom["object"]:
            return atom["object"], False
        return atom["objectConst"], True

    @staticmethod
    def _headTerms(rule: Dict[str, Any]) -> Tuple[str, str]:
        """规则头的 (主语项, 客体项)：relay/inverse 客体是变元，conjunction 是常量。"""
        positive = [a for a in rule["body"] if a["kind"] == "atom"]
        shape = str(rule.get("shape") or "relay")
        if shape == "conjunction":
            return rule["head_subject_var"], str(rule.get("head_object_const") or "")
        if shape == "inverse":
            return rule["head_subject_var"], positive[0]["subject"]
        return rule["head_subject_var"], positive[-1]["object"]

    # ── 事实匹配与缺口记录 ────────────────────────────────────

    def _matchFact(self, s: str, p: str, o: str) -> Optional[Dict[str, Any]]:
        """已证事实集中找 (s,p,o)；主体经 resolveSubjectKey 归一（只读），
        客体精确或归一相等即命中。"""
        subjectKey = self._store.resolveSubjectKey(self._agentId, s,
                                                   tenantId=self._tenantId)
        if subjectKey is None:
            return None
        for fact in self._factsByPredicate.get(p, []):
            if fact["subjectKey"] != subjectKey:
                continue
            if self._objectMatches(fact["object"], o):
                return fact
        return None

    @staticmethod
    def _objectMatches(factObject: str, goalObject: str) -> bool:
        if factObject == goalObject:
            return True
        return normalizeLabel(factObject) == normalizeLabel(goalObject)

    @staticmethod
    def _missingEntry(subject: str, predicate: str, objectTerm: str,
                      reason: str) -> Dict[str, Any]:
        return {"goal": {"subject": subject, "predicate": predicate,
                         "object": objectTerm},
                "reason": reason}

    @staticmethod
    def _dedupeMissing(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        out: List[Dict[str, Any]] = []
        for entry in entries:
            key = (entry["goal"]["subject"], entry["goal"]["predicate"],
                   entry["goal"]["object"], entry["reason"])
            if key in seen:
                continue
            seen.add(key)
            out.append(entry)
        return out
