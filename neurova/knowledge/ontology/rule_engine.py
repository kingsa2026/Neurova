"""Datalog 形状的前向链（工单 021，G09）：规则是数据，推理可解释。

明确不做（写在这里，免得后来者以为是"还没做完"）：SPARQL 文本查询、OWL DL 完整语义、
外部推理服务、任意嵌套聚合。规则形状固定为一个 Datalog 片段：

    head(X, Z) :- body1(X, Y), body2(Y, Z)          # 二元接力
    head(X, Y) :- body(X, Y)                        # 直接搬移
    head(X, Z) :- body1(X, Y), body2(Y, Z), not body3(X, Z)   # 带否定的分层规则
    传递闭包 = 同一谓词自接力的特例，交给 SQLite 递归 CTE，不在 Python 里迭代到不动点

为什么是这个片段：底座的事实就是 (主体, 谓词, 客体) 三元组，任何"多跳结论"都能写成
三元组上的接力；超出这个形状的规则（聚合、算术、存在量化的新实体）需要的不是推理引擎
而是函数层，那是另一件事，不该偷偷塞进规则语言里。

分层与否定：**否定只能指向本层之前已经算完的谓词**。绕过层序就会推出
"A 且 非 A"这种双结论，而双结论在治理层是两条 active 事实互相矛盾——
比没有推导更糟。所以注册时算层、循环即报错并指出环在哪。
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Any, Dict, List, Optional, Tuple

_SCHEMA_V9 = """
CREATE TABLE IF NOT EXISTS ontology_rules (
    rule_id TEXT PRIMARY KEY,
    head_predicate TEXT NOT NULL,
    head_subject_var TEXT NOT NULL,
    body_json TEXT NOT NULL DEFAULT '[]',
    negated_predicates TEXT NOT NULL DEFAULT '[]',
    stratification_level INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    version TEXT NOT NULL DEFAULT 'v1',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_head ON ontology_rules(head_predicate, enabled);
"""

_VAR = re.compile(r"^[A-Z]$")
_TERM_KINDS_IN_BODY = ("atom", "not")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class RuleError(ValueError):
    pass


class ForwardChainingEngine:
    """规则的登记与求值。推导出的事实**经咽喉入库**，不直插 SQL。

    直插等于造出一批"没有主体消解、没有血缘、没有置信"的孤儿子——那正是 B03/G12
    要灭的病，只是换了个入口复活。
    """

    def __init__(self, store: Any, gateFactory: Any = None) -> None:
        self._store = store
        self._gateFactory = gateFactory
        self._ensureTable()

    def _ensureTable(self) -> None:
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    # ── 登记 ──────────────────────────────────────────────────

    def registerRule(self, ruleId: str, headPredicate: str, body: List[Dict[str, Any]], *,
                    headSubjectVar: str = "X", enabled: bool = True,
                    version: str = "v1") -> Dict[str, Any]:
        """登记一条规则。形状、变量、层序在这里一次判完——坏规则进不了表。

        body 元素：`{"atom": predicate, "subject": var, "object": var}` 或
        `{"not": predicate, "subject": var, "object": var}`。
        """
        ruleId = str(ruleId or "").strip()
        if not ruleId or not headPredicate:
            raise RuleError("rule_id 与 head 谓词都不能为空")
        atoms = self._parseBody(ruleId, body)
        headVars = {headSubjectVar}
        positive = [a for a in atoms if a["kind"] == "atom"]
        negated = [a for a in atoms if a["kind"] == "not"]
        if not positive:
            raise RuleError("规则 %s 没有任何肯定正文——没有依据的推导不叫推理" % ruleId)
        if len(positive) > 2:
            raise RuleError("规则 %s 正文超过 2 个原子；本引擎是三元组接力片段，"
                            "更长链条请写成多条规则逐层推" % ruleId)
        if len(positive) == 2 and positive[0]["object"] != positive[1]["subject"]:
            raise RuleError("规则 %s 的两个原子接不上（%s 与 %s 不是同一个变元）"
                            % (ruleId, positive[0]["object"], positive[1]["subject"]))
        if positive[-1]["object"] not in headVars | {a["object"] for a in positive}:
            raise RuleError("规则 %s 的 head 客体未在正文中出现" % ruleId)
        for atom in atoms:
            if not _VAR.match(atom["subject"]) or not _VAR.match(atom["object"]):
                raise RuleError("规则 %s 的变元必须是单个大写字母，收到 %s"
                                % (ruleId, (atom["subject"], atom["object"])))

        stratum, cycles = self._stratify(ruleId, headPredicate,
                                        [a["predicate"] for a in negated],
                                        [a["predicate"] for a in positive])
        stamp = _now()
        with self._store._lock, self._store._conn:
            existing = self._store._conn.execute(
                "SELECT created_at FROM ontology_rules WHERE rule_id = ?", (ruleId,)).fetchone()
            self._store._conn.execute(
                "INSERT OR REPLACE INTO ontology_rules (rule_id, head_predicate, head_subject_var,"
                " body_json, negated_predicates, stratification_level, enabled, version,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ruleId, headPredicate, headSubjectVar, json.dumps(body, ensure_ascii=False),
                 json.dumps(sorted({a["predicate"] for a in negated}), ensure_ascii=False),
                 stratum, 1 if enabled else 0, version,
                 existing["created_at"] if existing else stamp, stamp),
            )
            if cycles:
                self._dropRule(ruleId)
        if cycles:
            raise RuleError("规则 %s 经由否定形成循环，分层无解：%s" % (ruleId, " → ".join(cycles)))
        return self.rule(ruleId) or {}

    def _dropRule(self, ruleId: str) -> None:
        with self._store._lock, self._store._conn:
            self._store._conn.execute("DELETE FROM ontology_rules WHERE rule_id = ?", (ruleId,))

    @staticmethod
    def _parseBody(ruleId: str, body: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        atoms: List[Dict[str, str]] = []
        for item in body or []:
            keys = set(item) - {"subject", "object"}
            if keys != {"atom"} and keys != {"not"}:
                raise RuleError("规则 %s 的正文元素必须是 atom 或 not 之一，收到 %s"
                                % (ruleId, sorted(keys)))
            predicate = str(item.get("atom") or item.get("not") or "").strip()
            if not predicate:
                raise RuleError("规则 %s 有正文原子的谓词为空" % ruleId)
            atoms.append({"kind": "atom" if "atom" in item else "not",
                          "predicate": predicate,
                          "subject": str(item.get("subject", "")),
                          "object": str(item.get("object", ""))})
        return atoms

    def _stratify(self, ruleId: str, headPredicate: str, negated: List[str],
                  positive: List[str]) -> Tuple[int, List[str]]:
        """层号 = 依赖链上最长的正边；否定边要求被否定谓词在**更浅**的层。"""
        rules = self.rules(includeDisabled=False)
        producers: Dict[str, List[str]] = {}
        for rule in rules:
            producers.setdefault(rule["head_predicate"], []).append(rule["rule_id"])
        producers.setdefault(headPredicate, []).append(ruleId)

        levelOf = self._levels(producers)
        if headPredicate in levelOf and levelOf[headPredicate] < 0:
            return 0, [headPredicate, headPredicate]
        level = levelOf.get(headPredicate, 0)
        for target in negated:
            targetLevel = levelOf.get(target)
            if targetLevel is not None and targetLevel >= level:
                return level, [headPredicate, "not", target]
        return level, []

    def _levels(self, producers: Dict[str, List[str]]) -> Dict[str, int]:
        """谓词层号：正边取 max(依赖)+1；遇到回边返回 -1 标记成环。"""
        levels: Dict[str, int] = {}
        visiting: List[str] = []

        def resolve(predicate: str) -> int:
            if predicate in levels and levels[predicate] >= 0:
                return levels[predicate]
            if predicate in visiting:
                levels[predicate] = -1
                return -1
            visiting.append(predicate)
            best = 0
            for rule in self.rules(includeDisabled=False):
                if rule["head_predicate"] != predicate:
                    continue
                for dep in rule["depends_on"]:
                    value = resolve(dep)
                    if value < 0:
                        best = -1
                        break
                    best = max(best, value + 1)
                if best < 0:
                    break
            visiting.pop()
            levels[predicate] = best
            return best

        for predicate in list(producers):
            resolve(predicate)
        return levels

    def rule(self, ruleId: str) -> Optional[Dict[str, Any]]:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM ontology_rules WHERE rule_id = ?", (ruleId,)).fetchone()
        return self._hydrate(row) if row else None

    def rules(self, includeDisabled: bool = True) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM ontology_rules"
        if not includeDisabled:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY stratification_level, rule_id"
        with self._store._lock:
            rows = self._store._conn.execute(sql).fetchall()
        return [self._hydrate(r) for r in rows]

    @staticmethod
    def _hydrate(row) -> Dict[str, Any]:
        d = dict(row)
        raw = json.loads(d.pop("body_json") or "[]")
        # 存的是用户写的形状，读出来统一成判定用的形状（kind + predicate）——
        # 两处各认各的键，就会一个能注册、另一个永远匹配不上。
        d["body"] = [{"kind": "atom" if "atom" in a else "not",
                      "predicate": str(a.get("atom") or a.get("not") or ""),
                      "subject": str(a.get("subject", "")),
                      "object": str(a.get("object", ""))} for a in raw]
        d["negated_predicates"] = json.loads(d.get("negated_predicates") or "[]")
        d["depends_on"] = sorted({a["predicate"] for a in d["body"] if a["predicate"]})
        d["enabled"] = bool(d.get("enabled"))
        return d

    # ── 求值 ──────────────────────────────────────────────────

    def fireAll(self, agentId: Optional[str] = None, maxIterations: int = 10) -> Dict[str, Any]:
        """按层号升序反复求值到不动点。返回每轮新增，0 新增即停。"""
        rounds: List[int] = []
        derived: List[str] = []
        for _ in range(max(int(maxIterations), 1)):
            produced = self._oneRound(agentId)
            rounds.append(len(produced))
            if not produced:
                break
            derived.extend(produced)
        return {"derived": derived, "rounds": rounds,
                "iterations": len(rounds), "rules": [r["rule_id"] for r in self.rules()]}

    def fireFor(self, agentId: str, predicate: str) -> List[str]:
        """新事实落下后只点燃用得到它的规则——每写一条就全量重放到不动点，
        成本随事实数线性放大，那条路在对话链上不可接受。"""
        produced: List[str] = []
        for rule in sorted(self.rules(includeDisabled=False),
                           key=lambda r: (r["stratification_level"], r["rule_id"])):
            if predicate not in rule["depends_on"]:
                continue
            produced.extend(self._fireRule(rule, agentId))
        return produced

    def _oneRound(self, agentId: Optional[str]) -> List[str]:
        produced: List[str] = []
        for rule in sorted(self.rules(includeDisabled=False),
                           key=lambda r: (r["stratification_level"], r["rule_id"])):
            produced.extend(self._fireRule(rule, agentId))
        return produced

    def _fireRule(self, rule: Dict[str, Any], agentId: Optional[str]) -> List[str]:
        atoms = [a for a in rule["body"]]
        positive = [a for a in atoms if a["kind"] == "atom"]
        negated = [a for a in atoms if a["kind"] == "not"]
        params: List[Any] = []
        first, second = positive[0], (positive[1] if len(positive) > 1 else None)
        live = "status = 'active' AND record_kind = 'triple'"
        aLive, bLive = "a." + live.replace(" AND ", " AND a."), "b." + live.replace(" AND ", " AND b.")
        if second is None:
            scope = " AND agent_id = ?" if agentId else ""
            sql = ("SELECT subject_key, object_term FROM knowledge_facts"
                   " WHERE predicate_term_id = ? AND %s%s" % (live, scope))
            params = [first["predicate"]] + ([agentId] if agentId else [])
        else:
            # 中项靠"上一跳的客体 = 下一跳主体的规范标签"接上。没被登记成主体的客体接不上，
            # 那是消解段（006）的活，不在推理层偷偷做字符串相似。
            scope = " AND a.agent_id = ?" if agentId else ""
            sql = ("SELECT a.subject_key AS subject_key, b.object_term AS object_term"
                   " FROM knowledge_facts a"
                   " JOIN knowledge_subjects s2 ON s2.agent_id = a.agent_id"
                   "  AND s2.normalized_label = lower(trim(a.object_term)) AND s2.status = 'active'"
                   " JOIN knowledge_facts b ON b.subject_key = s2.subject_key"
                   "  AND b.agent_id = a.agent_id"
                   " WHERE a.predicate_term_id = ? AND b.predicate_term_id = ?"
                   "  AND %s AND %s%s" % (aLive, bLive, scope))
            params = [first["predicate"], second["predicate"]] + ([agentId] if agentId else [])
        sql = ("SELECT t.subject_key, t.object_term, MIN(s.canonical_label) AS label"
               " FROM (%s) t JOIN knowledge_subjects s ON s.subject_key = t.subject_key"
               " GROUP BY t.subject_key, t.object_term"
               " ORDER BY t.subject_key, t.object_term" % sql)
        with self._store._lock:
            rows = self._store._conn.execute(sql, params).fetchall()

        head = rule["head_predicate"]
        written: List[str] = []
        for row in rows:
            subjectKey, objectTerm, label = row["subject_key"], row["object_term"], row["label"]
            if self._negatedHolds(agentId, negated, subjectKey, objectTerm):
                continue
            factId = self._admitDerivedFact(rule, agentId, label, head, objectTerm, subjectKey)
            if factId:
                written.append(factId)
        return written

    def _negatedHolds(self, agentId: Optional[str], negated: List[Dict[str, str]],
                      subjectKey: str, objectTerm: str) -> bool:
        if not negated:
            return False
        for atom in negated:
            params: List[Any] = [agentId or "", subjectKey, atom["predicate"], objectTerm]
            with self._store._lock:
                row = self._store._conn.execute(
                    "SELECT 1 FROM knowledge_facts WHERE agent_id = ? AND subject_key = ?"
                    " AND predicate_term_id = ? AND object_term = ? AND status = 'active'",
                    params).fetchone()
            if row:
                return True
        return False

    def _admitDerivedFact(self, rule: Dict[str, Any], agentId: Optional[str], label: str,
                          predicate: str, objectTerm: str, subjectKey: str) -> Optional[str]:
        gate = self._gateFactory(self._store) if self._gateFactory else None
        if gate is None:
            raise RuleError("推理未接咽喉写入口——推导事实不许绕过 admit 直插 SQL")
        from ..foundation.admission import AdmissionRequest

        content = "%s %s %s（由规则 %s 推出）" % (label, predicate, objectTerm, rule["rule_id"])
        try:
            receipt = gate.admit(AdmissionRequest(
                agentId=agentId or "default", subjectLabel=label, predicateTermId=predicate,
                objectTerm=objectTerm, content=content,
                qualifier={"derived_by": rule["rule_id"],
                           "stratum": rule["stratification_level"]},
                assertions=[{"actorType": "pipeline", "actorId": "rule:%s" % rule["rule_id"],
                             "mediumRef": "rule:%s" % rule["rule_id"],
                             "statementText": content}],
            ), allowPendingSegments=True)
        except ValueError:
            return None            # 本体/基数拒绝推导结果：与原始写入同一口径，不开例外
        if receipt.dedupedByContent:
            # 折回已有行不算"新推导"——不动点判据靠这个终止，否则每轮都"产出"同一批事实
            return None
        return receipt.factId

    def transitiveClosure(self, agentId: str, predicate: str) -> List[Tuple[str, str]]:
        """传递闭包交给递归 CTE：一次查询算完，不在 Python 里迭代到不动点。

        链的接法与 `_fireRule` 一致——上一跳的客体按规范标签找到下一跳的主体；
        `UNION`（不是 UNION ALL）自带行去重，再加一条 path 判重防同一客体被反复绕。
        返回 (主体键, 可达客体) 对，不含自反。
        """
        sql = (
            "WITH RECURSIVE closure(agent_id, subject_key, object_term, path) AS ("
            "  SELECT agent_id, subject_key, object_term,"
            "         '|' || subject_key || '|' || object_term || '|'"
            "  FROM knowledge_facts"
            "  WHERE agent_id = ? AND predicate_term_id = ?"
            "    AND status = 'active' AND record_kind = 'triple'"
            "  UNION"
            "  SELECT c.agent_id, c.subject_key, f.object_term,"
            "         c.path || f.object_term || '|'"
            "  FROM closure c"
            "  JOIN knowledge_subjects s2 ON s2.agent_id = c.agent_id"
            "    AND s2.normalized_label = lower(trim(c.object_term)) AND s2.status = 'active'"
            "  JOIN knowledge_facts f ON f.subject_key = s2.subject_key"
            "    AND f.agent_id = c.agent_id AND f.predicate_term_id = ?"
            "    AND f.status = 'active' AND f.record_kind = 'triple'"
            "    AND instr(c.path, '|' || f.object_term || '|') = 0"
            ") SELECT c.subject_key, c.object_term FROM closure c"
            " LEFT JOIN knowledge_subjects s3 ON s3.agent_id = c.agent_id"
            "   AND s3.normalized_label = lower(trim(c.object_term)) AND s3.status = 'active'"
            # 自反的一对（A 可达 A）是环的副产物，不是结论；客体没登记成主体的照原样留着。
            " WHERE s3.subject_key IS NULL OR c.subject_key <> s3.subject_key"
            " ORDER BY c.subject_key, c.object_term"
        )
        with self._store._lock:
            rows = self._store._conn.execute(sql, (agentId, predicate, predicate)).fetchall()
        return [(r["subject_key"], r["object_term"]) for r in rows]
