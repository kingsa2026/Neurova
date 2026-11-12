"""层级社区检测与 global/drift 检索（specs/2026-11-12 §9 W8）。

- 标签传播（stdlib 纯 Python，零依赖）在既有底座图（knowledge_subjects＋
  knowledge_facts 的 linked 边形状）上迭代至稳定；层级＝对社区代表点图再检测
  （粗化递归，层数上限具名常量）。
- 社区摘要经注入的摘要器生成（LLM 客户端惰性复用——缺省摘要空＝诚实形态，
  不造假文案）；v48 ontology_communities 表持久化。
- global 检索＝查询→社区摘要 map 命中（词法重叠计分）；drift＝实体邻域
  ＋所属社区摘要混合（邻域复用图走查既有形状）。
"""

from __future__ import annotations

import datetime
import json
import uuid
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 层级粗化层数上限
MAX_COMMUNITY_LEVELS = 3

_SCHEMA_V48_COMMUNITIES = """
CREATE TABLE IF NOT EXISTS ontology_chunk_strategies (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    strategy_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    params_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, strategy_id)
);
ALTER TABLE ontology_terms ADD COLUMN conflict_policy TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS ontology_communities (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    community_id TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 0,
    member_labels_json TEXT NOT NULL DEFAULT '[]',
    summary_text TEXT NOT NULL DEFAULT '',
    summary_digest TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, community_id)
);
"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _labelPropagation(nodes: List[str], edges: List[tuple]) -> List[List[str]]:
    """加权标签传播至稳定：邻居标签按边权（事实边数——簇内多证、簇间弱链）加权
    取众数（平票保己）。弱链不淹没强簇。"""
    weights: Dict[tuple, int] = {}
    for a, b in edges:
        if a == b:
            continue
        weights[(a, b)] = weights.get((a, b), 0) + 1
        weights[(b, a)] = weights.get((b, a), 0) + 1
    labels: Dict[str, str] = {n: n for n in nodes}
    for _round in range(len(nodes) + 1):
        changed = False
        for node in nodes:
            tally: Counter = Counter()
            for (a, b), w in weights.items():
                if a == node:
                    tally[labels[b]] += w
                # 无向边已双向记账（每条事实边 +1 两方向）——只取出向半边
                # 计票，入向半边是同一邻居的重复计票（会把弱链翻倍成平票）
            if not tally:
                continue
            majority = tally.most_common(1)[0][0]
            if labels[node] != majority:
                labels[node] = majority
                changed = True
        if not changed:
            break
    groups: Dict[str, List[str]] = {}
    for node in nodes:
        groups.setdefault(labels[node], []).append(node)
    return sorted([sorted(g) for g in groups.values()], key=lambda g: -len(g))


class CommunityGraphBuilder:
    """社区检测＋持久化（v48）。"""

    def __init__(self, store: Any, agentId: str = "default",
                 tenantId: str = "default") -> None:
        self._store = store
        self._agentId = agentId
        self._tenantId = tenantId
        self._ensureTable()

    def _ensureTable(self) -> None:
        from .foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    def _readGraph(self) -> tuple:
        with self._store._lock:
            nodeRows = self._store._conn.execute(
                "SELECT canonical_label FROM knowledge_subjects"
                " WHERE agent_id = ? AND tenant_id = ? AND status = 'active'"
                " ORDER BY canonical_label",
                (self._agentId, self._tenantId)).fetchall()
            edgeRows = self._store._conn.execute(
                "SELECT s.canonical_label AS src, f.object_term AS dst"
                " FROM knowledge_facts f JOIN knowledge_subjects s"
                " ON s.subject_key = f.subject_key"
                " WHERE f.agent_id = ? AND f.tenant_id = ? AND f.status = 'active'"
                " AND f.record_kind = 'triple' AND s.canonical_label = s.canonical_label"
                " ORDER BY s.canonical_label, f.object_term, f.fact_id",
                (self._agentId, self._tenantId)).fetchall()
        nodes = [str(r["canonical_label"]) for r in nodeRows]
        edges = [(str(r["src"]), str(r["dst"])) for r in edgeRows]
        return nodes, edges

    def detect(self, summarizer: Optional[Callable[[List[str]], str]] = None,
               level: int = 0) -> List[Dict[str, Any]]:
        """检测（标签传播）＋持久化＋可选摘要。返回社区行清单。"""
        nodes, edges = self._readGraph()
        groups = _labelPropagation(nodes, edges)
        out: List[Dict[str, Any]] = []
        for members in groups:
            summary = ""
            if summarizer is not None:
                summary = str(summarizer(members) or "")
            communityId = "com_%s" % uuid.uuid4().hex[:12]
            with self._store._lock, self._store._conn:
                self._store._conn.execute(
                    "INSERT OR REPLACE INTO ontology_communities"
                    " (tenant_id, community_id, level, member_labels_json,"
                    "  summary_text, summary_digest, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (self._tenantId, communityId, level,
                     json.dumps(members, ensure_ascii=False),
                     summary, _digest(summary), _now()))
            out.append({"community_id": communityId, "level": level,
                        "member_labels": members, "summary_text": summary})
        return out

    def loadCommunities(self, level: Optional[int] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM ontology_communities WHERE tenant_id = ?"
        params: List[Any] = [self._tenantId]
        if level is not None:
            sql += " AND level = ?"
            params.append(int(level))
        sql += " ORDER BY level, community_id"
        with self._store._lock:
            rows = self._store._conn.execute(sql, params).fetchall()
        return [{"community_id": str(r["community_id"]),
                 "level": int(r["level"]),
                 "member_labels": json.loads(r["member_labels_json"] or "[]"),
                 "summary_text": str(r["summary_text"] or "")} for r in rows]


def _digest(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def communityGlobalSearch(store: Any, query: str, agentId: str = "default",
                          tenantId: str = "default",
                          limit: int = 5) -> List[Dict[str, Any]]:
    """global 检索：查询→社区摘要 map 命中（词法重叠计分，零新依赖）。"""
    from .foundation.foundation_schema import applyTo

    with store._lock, store._conn:
        applyTo(store._conn)
    queryTokens = set(query.casefold())
    hits: List[Dict[str, Any]] = []
    with store._lock:
        rows = store._conn.execute(
            "SELECT community_id, member_labels_json, summary_text"
            " FROM ontology_communities WHERE tenant_id = ? ORDER BY level",
            (tenantId,)).fetchall()
    for row in rows:
        summary = str(row["summary_text"] or "")
        summaryTokens = set(summary.casefold())
        overlap = len(queryTokens & summaryTokens)
        if overlap:
            hits.append({"community_id": str(row["community_id"]),
                         "score": overlap,
                         "summary": summary,
                         "labels": json.loads(row["member_labels_json"] or "[]")})
    hits.sort(key=lambda h: -h["score"])
    return hits[:max(1, int(limit))]


def communityDriftSearch(store: Any, entityLabel: str, agentId: str = "default",
                         tenantId: str = "default",
                         limit: int = 5) -> List[Dict[str, Any]]:
    """drift 检索：实体邻域（knowledge_facts 既有客体接力一跳）＋所属社区摘要混合。"""
    from .foundation.foundation_schema import applyTo

    with store._lock, store._conn:
        applyTo(store._conn)
    neighbors: List[str] = []
    with store._lock:
        rows = store._conn.execute(
            "SELECT DISTINCT f.object_term FROM knowledge_facts f"
            " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
            " WHERE s.canonical_label = ? AND s.agent_id = ? AND s.tenant_id = ?"
            " AND f.status = 'active' AND f.record_kind = 'triple' LIMIT ?",
            (entityLabel, agentId, tenantId, int(limit))).fetchall()
    neighbors = [str(r["object_term"]) for r in rows]
    hits: List[Dict[str, Any]] = []
    with store._lock:
        rows = store._conn.execute(
            "SELECT community_id, member_labels_json, summary_text"
            " FROM ontology_communities WHERE tenant_id = ?", (tenantId,)).fetchall()
    for row in rows:
        labels = json.loads(row["member_labels_json"] or "[]")
        if entityLabel in labels or any(n in labels for n in neighbors):
            hits.append({"community_id": str(row["community_id"]),
                         "labels": labels,
                         "summary": str(row["summary_text"] or ""),
                         "matched_neighbor": entityLabel if entityLabel in labels
                         else next((n for n in neighbors if n in labels), "")})
    return hits[:max(1, int(limit))]
