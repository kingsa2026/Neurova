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
                         rule: Dict[str, Any], sourceKind: str = "rule") -> None:
        """记一条推导边。`sourceKind`（W2，v43）：rule|function——函数结论与规则
        结论同一张账本，不建第二账本；物化档读数（_observeSideSubquery）按它分支。"""
        stamp = _now()
        with self._store._lock, self._store._conn:
            for premise in dict.fromkeys(premiseFactIds):     # 同一前提记一次
                self._store._conn.execute(
                    "INSERT OR IGNORE INTO knowledge_derivation_edges"
                    " (derived_fact_id, premise_fact_id, rule_id, rule_version, stratum,"
                    "  recorded_at, source_kind) VALUES (?,?,?,?,?,?,?)",
                    (derivedFactId, premise, rule["rule_id"], rule.get("version", "v1"),
                     int(rule.get("stratification_level") or 0), stamp, str(sourceKind)),
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

    def derivedFactIds(self) -> List[str]:
        """全库"被推导过"的事实 id，一条 DISTINCT 取完——读侧灰度的单点取数。

        含已退档结论的边（边记的是"曾经怎么来的"，不是"现在还算不算数"）：
        活动筛选由调用方那侧的 `status='active'` 负责，这里不替别人做决定。
        """
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT DISTINCT derived_fact_id FROM knowledge_derivation_edges"
                " ORDER BY derived_fact_id").fetchall()
        return [r["derived_fact_id"] for r in rows]

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

    def derivedExclusionClause(self, alias: str) -> str:
        """「排除该按观察态处理的推导行」的 SQL 片段——这张表只有账本知道怎么读。

        档位口径（v35，§12.6 设计 3）写在这**一处**：一条推导行只有在它的每一条
        推导边都来自 `materialization='enforce'` 的规则时才留在主路；有任何一条
        observe 边（或规则行已不在 enforce 名下）就按观察态排除——保守侧宁可少放
        一条，也不把没转正的推导混进检索。图谱走查把它接进递归 CTE 的 WHERE，
        检索读面经 `hiddenDerivedFactIds()` 取同一张片段的结果，两侧不各写一套判据。

        实测（2026-11-06 探针）：同一 statement 被两条规则各推一次会留下**两行**
        结论（推导写入的内容键带来源），所以"一行挂两种档位"今天不可达；片段仍按
        "全部边都 enforce 才放行"写——日后内容键若改并，这里不会静默变宽松。

        子查询用相关引用（`<alias>.tenant_id`）而不是占位符：接进 CTE 不会打乱
        外层 `?` 的次序。
        """
        return ("%s.fact_id NOT IN (%s)"
                % (alias, self._observeSideSubquery("%s.tenant_id" % alias)))

    @staticmethod
    def _observeSideSubquery(tenantRef: str) -> str:
        """「档位不足以进主路」的推导结论 id 子查询；`tenantRef` 是租户取值写法。

        W2：source_kind=function 的边查 ontology_functions 的物化档
        （substr 剥 "function:" 前缀），规则边照旧查 ontology_rules——
        两类结论同一判据形状（全部边 enforce 才放行），账本单源。"""
        return ("SELECT e.derived_fact_id FROM knowledge_derivation_edges e"
                " LEFT JOIN ontology_rules r"
                " ON r.rule_id = e.rule_id AND r.tenant_id = %s"
                " WHERE CASE WHEN COALESCE(e.source_kind, 'rule') = 'function'"
                " THEN COALESCE((SELECT f2.materialization FROM ontology_functions f2"
                "   WHERE f2.function_id = substr(e.rule_id, 10) AND f2.tenant_id = %s),"
                "  'observe')"
                " ELSE COALESCE(r.materialization, 'observe') END <> 'enforce'"
                % (tenantRef, tenantRef))

    def hiddenDerivedFactIds(self, tenantId: str = "default") -> List[str]:
        """读面要摘掉的推导行 id——与 `derivedExclusionClause` 同一段判据。

        比原来的「全部推导行」窄：enforce 档的结论不该被摘。原始事实没有推导边，
        天然不在这个集合里（子查询只从账本取数），不需要额外保护。
        """
        tenant = str(tenantId or "default")
        sql = ("SELECT f.fact_id FROM knowledge_facts f"
               " WHERE f.tenant_id = ? AND f.fact_id IN (%s)"
               % self._observeSideSubquery("?"))
        # W2：子查询从 1 个占位涨到 2 个（规则边 join ＋函数边 CASE）——参数序
        # 跟占位出现序走：外层 f.tenant_id → 子查询 r.tenant_id → 子查询 f2.tenant_id
        with self._store._lock:
            rows = self._store._conn.execute(sql, (tenant, tenant, tenant)).fetchall()
        return [str(row["fact_id"]) for row in rows]

    def hasEnforceRules(self, tenantId: str = "default") -> bool:
        """本租户有没有把任何规则转正——决定走查要不要去账本取溯源标注。

        灰度 off 且全表 observe 时推导行根本进不了 CTE，取标注就是白花一次 IO；
        一旦出现 enforce 档，标注就得照取，否则放进来的推导行没了 `via_derived`。
        """
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT 1 FROM ontology_rules WHERE tenant_id = ?"
                " AND materialization = 'enforce' LIMIT 1",
                (str(tenantId or "default"),)).fetchone()
        return row is not None

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

    def retractRuleVersion(self, ruleId: str, keepVersion: str,
                           tenantId: str = "default") -> int:
        """规则改版：旧版本推出的结论全部撤回，新版本自己重推（不留"两版并存"）。
        同 rule_id 跨租户（v25）互不波及。"""
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT DISTINCT e.derived_fact_id AS derived_fact_id"
                " FROM knowledge_derivation_edges e"
                " JOIN knowledge_facts f ON f.fact_id = e.derived_fact_id"
                " WHERE e.rule_id = ? AND e.rule_version <> ? AND f.tenant_id = ?"
                " ORDER BY e.derived_fact_id",
                (ruleId, keepVersion, str(tenantId or "default"))).fetchall()
        return sum(self._retractDerived(r["derived_fact_id"], "规则 %s 改版为 %s" % (ruleId, keepVersion))
                   for r in rows)

    def retractAllFromRule(self, ruleId: str, reason: str = "",
                           tenantId: str = "default") -> int:
        """规则退场：它推过的结论全撤，不分版本——删除比改版更彻底，
        保留任何一批"规则已不存在"的结论，都是拿着死规则对外检索。
        同 rule_id 跨租户（v25）互不波及：撤回只对本租户的派生事实。"""
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT DISTINCT e.derived_fact_id AS derived_fact_id"
                " FROM knowledge_derivation_edges e"
                " JOIN knowledge_facts f ON f.fact_id = e.derived_fact_id"
                " WHERE e.rule_id = ? AND f.tenant_id = ?"
                " ORDER BY e.derived_fact_id",
                (ruleId, str(tenantId or "default"))).fetchall()
        return sum(self._retractDerived(r["derived_fact_id"],
                                        reason or "规则 %s 已删除" % ruleId)
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
