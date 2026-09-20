"""推导账本与精确撤销（工单 022）：规则改了或前提撤了，只动该动的推导。

两本账：
- `knowledge_derivation_edges` —— 一条推导事实由哪条规则、从哪几条前提来。
  没有它，"撤销"就只有全清重算这一种做法，而那是拿别人的结论陪葬。
- `ontology_rule_fires` —— 每次求值点了哪些规则、产出哪些事实。审计要的是
  "这条结论是哪一版规则推出来的"，不是"当前规则长什么样"。

撤销只沿推导边往下走：**没有推导边的行是原始事实，任何撤销都不碰它**。
原始事实的退场由冲突裁决与条目生命周期负责（007/008），把两套混在一起就会出现
"改了个规则，把用户手写的事实删了"这种事故。

层号决定撤销顺序：先退深层再退浅层，否则深层结论的推导边还挂在一条
"已被撤销但当时还算数"的前提上，账本就自相矛盾了。
"""

from __future__ import annotations

import datetime
import json
import threading
import uuid
from typing import Any, Dict, List, Optional

_SCHEMA_V10 = """
CREATE TABLE IF NOT EXISTS knowledge_derivation_edges (
    derived_fact_id TEXT NOT NULL,
    premise_fact_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    rule_version TEXT NOT NULL DEFAULT 'v1',
    stratum INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (derived_fact_id, premise_fact_id, rule_id, rule_version)
);
CREATE INDEX IF NOT EXISTS idx_derivation_premise
    ON knowledge_derivation_edges(premise_fact_id);
CREATE INDEX IF NOT EXISTS idx_derivation_rule
    ON knowledge_derivation_edges(rule_id, rule_version);

CREATE TABLE IF NOT EXISTS ontology_rule_fires (
    fire_id TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL,
    rule_version TEXT NOT NULL DEFAULT 'v1',
    fired_at TEXT NOT NULL,
    head_predicate TEXT NOT NULL,
    derived_fact_ids_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_rule_fires_rule ON ontology_rule_fires(rule_id, fired_at);
"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class DerivationLedger:
    """推导来源的记录与撤销。SQL 都在同一座底座库里，不另建存储。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._cascade = threading.local()
        self._ensureTable()

    def _ensureTable(self) -> None:
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    # ── 记 ────────────────────────────────────────────────────

    def recordDerivation(self, derivedFactId: str, premiseFactIds: List[str],
                         rule: Dict[str, Any]) -> None:
        stamp = _now()
        with self._store._lock, self._store._conn:
            for premise in dict.fromkeys(premiseFactIds):     # 同一前提记一次
                self._store._conn.execute(
                    "INSERT OR IGNORE INTO knowledge_derivation_edges"
                    " (derived_fact_id, premise_fact_id, rule_id, rule_version, stratum,"
                    "  recorded_at) VALUES (?,?,?,?,?,?)",
                    (derivedFactId, premise, rule["rule_id"], rule.get("version", "v1"),
                     int(rule.get("stratification_level") or 0), stamp),
                )

    def recordFire(self, rule: Dict[str, Any], derivedFactIds: List[str]) -> str:
        fireId = "fire_%s" % uuid.uuid4().hex[:12]
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "INSERT INTO ontology_rule_fires (fire_id, rule_id, rule_version, fired_at,"
                " head_predicate, derived_fact_ids_json) VALUES (?,?,?,?,?,?)",
                (fireId, rule["rule_id"], rule.get("version", "v1"), _now(),
                 rule["head_predicate"], json.dumps(list(derivedFactIds), ensure_ascii=False)),
            )
        return fireId

    # ── 查 ────────────────────────────────────────────────────

    def derivationsOf(self, premiseFactId: str) -> List[Dict[str, Any]]:
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT derived_fact_id, rule_id, rule_version, stratum"
                " FROM knowledge_derivation_edges WHERE premise_fact_id = ?"
                " ORDER BY stratum DESC, derived_fact_id", (premiseFactId,)).fetchall()
        return [dict(r) for r in rows]

    def premisesOf(self, derivedFactId: str) -> List[Dict[str, Any]]:
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT premise_fact_id, rule_id, rule_version FROM knowledge_derivation_edges"
                " WHERE derived_fact_id = ? ORDER BY rule_id, premise_fact_id",
                (derivedFactId,)).fetchall()
        return [dict(r) for r in rows]

    def fires(self, ruleId: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM ontology_rule_fires"
        params: List[Any] = []
        if ruleId:
            sql += " WHERE rule_id = ?"
            params.append(ruleId)
        sql += " ORDER BY fired_at, fire_id"
        with self._store._lock:
            rows = self._store._conn.execute(sql, params).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            ids = json.loads(d.pop("derived_fact_ids_json") or "[]")
            d["derived_fact_ids"] = ids
            # 每次点燃现在还剩几条：审计问的是"这批结论还在不在"，
            # 而不是"退掉过几条"——后者写成一列就会和事实表各说各话。
            d["live_count"] = sum(
                1 for fid in ids
                if (self._store.fact(fid) or {}).get("status") == "active")
            out.append(d)
        return out

    # ── 撤销 ──────────────────────────────────────────────────

    def retractAllDerivedFrom(self, premiseFactId: str, reason: str = "") -> int:
        """前提退场 ⇒ 依赖它的一切推导逐层退场；原始事实一律不碰。

        边记到**前提**粒度，不记到证明粒度：一条结论有两条独立证明时，撤掉其中一条
        前提会连带退掉结论。这是保守侧——多退的在下一次求值里长回来；少退就是拿着
        一条已死的前提继续对外检索。
        """
        if getattr(self._cascade, "busy", False):
            return 0
        self._cascade.busy = True
        try:
            return sum(self._retractDerived(edge["derived_fact_id"], reason)
                       for edge in self.derivationsOf(premiseFactId))
        finally:
            self._cascade.busy = False

    def retractRuleVersion(self, ruleId: str, keepVersion: str) -> int:
        """规则改版：旧版本推出的结论全部撤回，新版本自己重推（不留"两版并存"）。"""
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT DISTINCT derived_fact_id FROM knowledge_derivation_edges"
                " WHERE rule_id = ? AND rule_version <> ? ORDER BY derived_fact_id",
                (ruleId, keepVersion)).fetchall()
        return sum(self._retractDerived(r["derived_fact_id"], "规则 %s 改版为 %s" % (ruleId, keepVersion))
                   for r in rows)

    def _retractDerived(self, factId: str, reason: str) -> int:
        """先退它自己的下游，再退它自己——深层先走，浅层才不会引用一条已经没了的前提。"""
        downstream = 0
        for edge in self.derivationsOf(factId):
            if edge["derived_fact_id"] == factId:
                continue
            downstream += self._retractDerived(edge["derived_fact_id"], reason or "前提已撤销")
        fact = self._store.fact(factId)
        if fact and fact.get("status") == "active" and self.premisesOf(factId):
            self._store.retract(factId, reason=reason or "推导前提已撤销")
            return 1 + downstream
        return downstream
