"""决策台账（specs/2026-11-12 §8 W7，D7 必选）：决策一等对象＋因果链＋判例检索。

- 决策表是**问责台账**（agent_run_ledger 同族），不是知识事实——不经 admission
  事实门（通则 1 约束的是事实写入）；决策若产生知识事实，事实仍走 admission。
- 因果边**不进** knowledge_derivation_edges（该账本单源记事实推导溯源，
  决策链接是另一域，通则 6 不破）。
- 无环硬校验：caused/precedent 插入时查 target 上游闭包是否可达 source，
  成环显式拒；influenced 允许环（遍历深度受限）。
- 判例检索：词法混合计分（TFIDF 族）承载——嵌入路径接入前的偏差已登记台账
  （specs/2026-11-12 §8 原文"复用既有嵌入生成与混合检索管线"，现码索引侧无
  source_kind 概念、决策文本非知识条目；本实装按同族词法计分先行，嵌入接入
  后切管线，登记待追认）。
- 身份纪律（AGENTS.md §3）：decision_maker 取请求边界 sender（显式带入），
  owner_id 取 resolveSessionOwner 单点语义，agent/session 显式带——不从
  ContextVar 猜。
"""

from __future__ import annotations

import json
import math
import re
import uuid
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.core.time_utils import nowIso as _now

logger = get_logger(__name__)

#: 链接类型闭集（因果导致/影响/判例引用）
LINK_KINDS = ("caused", "influenced", "precedent")

#: trace 深度上限（单源具名常量，缺省 10）
MAX_DECISION_TRACE_DEPTH = 10

_SCHEMA_V47_DECISIONS = """
CREATE TABLE IF NOT EXISTS ontology_decisions (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    decision_id TEXT NOT NULL,
    owner_id TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    scenario TEXT NOT NULL DEFAULT '',
    reasoning TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    decision_maker TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    valid_from TEXT NOT NULL DEFAULT '',
    valid_until TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id, decision_id)
);
CREATE INDEX IF NOT EXISTS idx_decisions_tenant_cat
    ON ontology_decisions(tenant_id, category);

CREATE TABLE IF NOT EXISTS ontology_decision_links (
    link_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    source_decision_id TEXT NOT NULL,
    target_decision_id TEXT NOT NULL,
    link_kind TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, link_id),
    UNIQUE (tenant_id, source_decision_id, target_decision_id, link_kind)
);
CREATE INDEX IF NOT EXISTS idx_decision_links_src
    ON ontology_decision_links(tenant_id, source_decision_id, link_kind);
CREATE INDEX IF NOT EXISTS idx_decision_links_dst
    ON ontology_decision_links(tenant_id, target_decision_id, link_kind);
"""

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


class DecisionLedger:
    """ontology_decisions / ontology_decision_links 的唯一读写面。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._ensureTable()

    def _ensureTable(self) -> None:
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    # ── 决策登记（唯一写点）───────────────────────────────────

    def recordDecision(self, tenantId: str, category: str, scenario: str,
                       reasoning: str, outcome: str, confidence: float,
                       decisionMaker: str, ownerId: str = "",
                       agentId: str = "", sessionId: str = "",
                       metadata: Optional[Dict[str, Any]] = None,
                       decisionId: str = "") -> Dict[str, Any]:  # noqa: C901
        """登记决策（唯一写点）。必填五项缺一即拒；confidence ∈ [0,1] 越界拒。"""
        for name, value in (("category", category), ("scenario", scenario),
                            ("reasoning", reasoning), ("outcome", outcome)):
            if not str(value or "").strip():
                raise ValueError("决策登记必填项缺失: %s" % name)
        confidence = float(confidence)
        if not (0.0 <= confidence <= 1.0):
            raise ValueError(
                "confidence %r 越界（须 ∈ [0,1]）" % confidence)
        decisionId = str(decisionId or "").strip() or "dec_%s" % uuid.uuid4().hex[:12]
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "INSERT OR REPLACE INTO ontology_decisions"
                " (tenant_id, decision_id, owner_id, category, scenario, reasoning,"
                "  outcome, confidence, decision_maker, agent_id, session_id,"
                "  metadata_json, created_at, valid_from, valid_until)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(tenantId or "default"), decisionId,
                 str(ownerId or ""), str(category or ""), str(scenario or ""),
                 str(reasoning or ""), str(outcome or ""), confidence,
                 str(decisionMaker or ""), str(agentId or ""),
                 str(sessionId or ""),
                 json.dumps(metadata or {}, ensure_ascii=False),
                 _now(), "", ""))
        return self.get(decisionId, tenantId=tenantId) or {}

    def get(self, decisionId: str, tenantId: str = "default") -> Optional[Dict[str, Any]]:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM ontology_decisions WHERE tenant_id = ? AND decision_id = ?",
                (str(tenantId or "default"), str(decisionId or "").strip())).fetchone()
        return self._hydrate(row) if row is not None else None

    def list(self, tenantId: str = "default", limit: int = 50) -> List[Dict[str, Any]]:
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT * FROM ontology_decisions WHERE tenant_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (str(tenantId or "default"), int(limit))).fetchall()
        return [self._hydrate(r) for r in rows]

    # ── 链接 ──────────────────────────────────────────────────

    def linkDecisions(self, sourceId: str, targetId: str, linkKind: str,
                      tenantId: str = "default", createdBy: str = "") -> Dict[str, Any]:
        """链接两决策：两端须存在且同租户（跨租户拒）、自环拒；
        caused/precedent 无环硬校验（插入时查 target 上游闭包是否可达 source）。"""
        sourceId = str(sourceId or "").strip()
        targetId = str(targetId or "").strip()
        linkKind = str(linkKind or "").strip()
        if linkKind not in LINK_KINDS:
            raise ValueError("link_kind %r 不在闭集 %s" % (linkKind, "/".join(LINK_KINDS)))
        if sourceId == targetId:
            raise ValueError("自环拒（source == target）")
        tenant = str(tenantId or "default")
        if self.get(sourceId, tenantId=tenant) is None \
                or self.get(targetId, tenantId=tenant) is None:
            raise LookupError("链接端点不存在或跨租户: %s → %s" % (sourceId, targetId))
        if linkKind in ("caused", "precedent"):
            downstream = self._downstreamClosure(targetId, tenant)
            if sourceId in downstream:
                raise ValueError(
                    "成环拒：source %s 已在 target %s 的 %s 下游闭包内"
                    % (sourceId, targetId, linkKind))
        linkId = "lnk_%s" % uuid.uuid4().hex[:12]
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "INSERT OR IGNORE INTO ontology_decision_links"
                " (link_id, tenant_id, source_decision_id, target_decision_id,"
                "  link_kind, created_by, created_at) VALUES (?,?,?,?,?,?,?)",
                (linkId, tenant, sourceId, targetId, linkKind,
                 str(createdBy or ""), _now()))
        return {"link_id": linkId, "source": sourceId, "target": targetId,
                "link_kind": linkKind}

    def _downstreamClosure(self, decisionId: str, tenant: str,
                           maxDepth: int = MAX_DECISION_TRACE_DEPTH) -> set:
        """target 的下游闭包（caused/precedent 边）——环检测读数：加 S→T 成环
        当且仅当 S 可从 T 下游到达。"""
        seen: set = set()
        frontier = [str(decisionId)]
        for _depth in range(maxDepth):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            with self._store._lock:
                rows = self._store._conn.execute(
                    "SELECT target_decision_id FROM ontology_decision_links"
                    " WHERE tenant_id = ? AND source_decision_id IN (%s)"
                    " AND link_kind IN ('caused','precedent')" % placeholders,
                    [tenant] + frontier).fetchall()
            frontier = []
            for row in rows:
                dst = str(row["target_decision_id"])
                if dst not in seen:
                    seen.add(dst)
                    frontier.append(dst)
        return seen

    # ── 因果链读数（递归 CTE 同族语义）────────────────────────

    def traceDecisionChain(self, decisionId: str, direction: str = "both",
                           tenantId: str = "default",
                           maxDepth: int = MAX_DECISION_TRACE_DEPTH) -> List[Dict[str, Any]]:
        """上溯（up）/下探（down）/双向（both），深度上限具名常量。"""
        decisionId = str(decisionId or "").strip()
        tenant = str(tenantId or "default")
        depth = max(1, min(int(maxDepth), MAX_DECISION_TRACE_DEPTH))
        results: List[Dict[str, Any]] = []
        seen = {decisionId}
        frontier = [decisionId]
        for _level in range(depth):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            rows: List[Any] = []
            with self._store._lock:
                if direction in ("up", "both"):
                    rows += self._store._conn.execute(
                        "SELECT source_decision_id AS node, link_kind,"
                        " 'up' AS side FROM ontology_decision_links"
                        " WHERE tenant_id = ? AND target_decision_id IN (%s)"
                        % placeholders, [tenant] + frontier).fetchall()
                if direction in ("down", "both"):
                    rows += self._store._conn.execute(
                        "SELECT target_decision_id AS node, link_kind,"
                        " 'down' AS side FROM ontology_decision_links"
                        " WHERE tenant_id = ? AND source_decision_id IN (%s)"
                        % placeholders, [tenant] + frontier).fetchall()
            nextFrontier: List[str] = []
            for row in rows:
                node = str(row["node"])
                if node in seen:
                    continue  # influenced 允许环：遍历不重复展开
                seen.add(node)
                nextFrontier.append(node)
                results.append({"decision_id": node,
                                "link_kind": str(row["link_kind"]),
                                "side": str(row["side"])})
            frontier = nextFrontier
        return results[:MAX_DECISION_TRACE_DEPTH]

    # ── 判例检索（词法混合计分——嵌入接入前承载，偏差已登记）────

    def findPrecedents(self, queryText: str, limit: int = 5,
                       tenantId: str = "default",
                       ownerId: Optional[str] = None) -> List[Dict[str, Any]]:
        """判例检索：scenario+reasoning 词法计分（TFIDF 族），按租户/属主过滤。"""
        query = str(queryText or "").strip()
        if not query:
            return []
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT decision_id, category, scenario, reasoning, outcome,"
                " confidence, decision_maker FROM ontology_decisions"
                " WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 500",
                (str(tenantId or "default"),)).fetchall()
        if ownerId is not None:
            tenant = str(tenantId or "default")
            rows = [r for r in rows if str(r["decision_maker"]) == str(ownerId)
                    or self._ownerMatches(str(r["decision_id"]), tenant, ownerId)]
        corpus = []
        for row in rows:
            text = "%s %s" % (row["scenario"], row["reasoning"])
            corpus.append((str(row["decision_id"]), text, dict(row)))
        queryTokens = _TOKEN_RE.findall(query.casefold())
        if not queryTokens:
            return []
        nDocs = max(len(corpus), 1)
        df: Dict[str, int] = {}
        docTokens: List[set] = []
        for _did, text, _row in corpus:
            tokens = set(_TOKEN_RE.findall(text.casefold()))
            docTokens.append(tokens)
            for token in tokens:
                df[token] = df.get(token, 0) + 1
        scored: List[Dict[str, Any]] = []
        for i, (did, _text, row) in enumerate(corpus):
            tokens = docTokens[i]
            score = 0.0
            for token in queryTokens:
                tf = 1.0 if token in tokens else 0.0
                if tf:
                    idf = math.log((nDocs + 1) / (df.get(token, 0) + 1)) + 1.0
                    score += tf * idf
            if score > 0:
                scored.append({"decision_id": did, "score": round(score, 4),
                               "scenario": str(row["scenario"]),
                               "reasoning": str(row["reasoning"]),
                               "outcome": str(row["outcome"]),
                               "confidence": float(row["confidence"]),
                               "decision_maker": str(row["decision_maker"])})
        scored.sort(key=lambda h: -h["score"])
        return scored[:max(1, int(limit))]

    def _ownerMatches(self, decisionId: str, tenant: str, ownerId: str) -> bool:
        row = None
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT owner_id FROM ontology_decisions"
                " WHERE tenant_id = ? AND decision_id = ?",
                (tenant, decisionId)).fetchone()
        return row is not None and str(row["owner_id"]) == str(ownerId)

    @staticmethod
    def _hydrate(row: Any) -> Dict[str, Any]:
        d = dict(row)
        d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
        return d
