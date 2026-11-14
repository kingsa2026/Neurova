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

import json
import uuid
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.core.time_utils import nowIso as _now

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
    # 边端点可能没有主体行（客体词不建 subject）——必须入册，否则
    # tally[labels[b]] 直接 KeyError（实测：A1→B1 弱边即触发）
    for a, b in weights:
        for end in (a, b):
            if end not in labels:
                labels[end] = end
    for _round in range(len(labels) + 1):
        changed = False
        for node in labels:
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
    for node in labels:
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
        # P3-6：图读数走 store 只读公开口，不再直摸 `_lock`/`_conn`。
        nodeRows = self._store.queryReadOnly(
            "SELECT canonical_label FROM knowledge_subjects"
            " WHERE agent_id = ? AND tenant_id = ? AND status = 'active'"
            " ORDER BY canonical_label",
            (self._agentId, self._tenantId))
        edgeRows = self._store.queryReadOnly(
            "SELECT s.canonical_label AS src, f.object_term AS dst"
            " FROM knowledge_facts f JOIN knowledge_subjects s"
            " ON s.subject_key = f.subject_key"
            " WHERE f.agent_id = ? AND f.tenant_id = ? AND f.status = 'active'"
            " AND f.record_kind = 'triple' AND s.canonical_label = s.canonical_label"
            " ORDER BY s.canonical_label, f.object_term, f.fact_id",
            (self._agentId, self._tenantId))
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

    def rebuildIfDrifted(self, summarizer: Optional[Callable[[List[str]], str]] = None,
                         level: int = 0,
                         driftThreshold: float = 0.3) -> Dict[str, Any]:
        """增量维护入口（C5，graphiti 对照批）：漂移超阈值才全量替换。

        与 detect 的差别：detect 每次全新 community_id 落行、旧行不清
        （重复调用累积重复社区）；本方法把「新检测结果 vs 既有行」的成员
        集合 Jaccard 漂移量算出来，未超阈值直接返回现况（community_id
        保持不变），超阈值才在**同一事务**里先删该 (tenant, level) 旧行
        再插新行——替换可审计、不累积。首建（无既有行）视漂移为 1.0。
        返回 `{"refreshed", "drift", "communities"}` 读数。
        """
        nodes, edges = self._readGraph()
        groups = _labelPropagation(nodes, edges)
        existing = self.loadCommunities(level=level)
        drift = _communityDrift(existing, groups)
        if existing and drift < driftThreshold:
            return {"refreshed": False, "drift": drift,
                    "communities": len(existing)}
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "DELETE FROM ontology_communities WHERE tenant_id = ? AND level = ?",
                (self._tenantId, int(level)))
            for members in groups:
                summary = ""
                if summarizer is not None:
                    summary = str(summarizer(members) or "")
                communityId = "com_%s" % uuid.uuid4().hex[:12]
                self._store._conn.execute(
                    "INSERT OR REPLACE INTO ontology_communities"
                    " (tenant_id, community_id, level, member_labels_json,"
                    "  summary_text, summary_digest, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (self._tenantId, communityId, int(level),
                     json.dumps(members, ensure_ascii=False),
                     summary, _digest(summary), _now()))
        return {"refreshed": True, "drift": drift, "communities": len(groups)}


def _communityDrift(existing: List[Dict[str, Any]],
                    newGroups: List[List[str]]) -> float:
    """漂移量 = max(成员对称差比例, 结构重排距离)；无既有行 = 1.0（首建）。

    两个信号各管一种变化、取 max 防稀释：
    - 成员级对称差——图里新增/移除主体直接可见（双向平均 Jaccard 会把
      「凭空长出一半社区」稀释到 0.25，漏过 0.3 阈值，实测踩过）；
    - 双向平均最佳 Jaccard——成员不变但分组重排（拆簇/并簇）时成员级
      口径恒 0，只有它看得见。"""
    if not existing:
        return 1.0
    newSets = [set(g) for g in newGroups]
    if not newSets:
        return 1.0
    oldSets = [set(row["member_labels"]) for row in existing]

    oldAll = set()
    for s in oldSets:
        oldAll |= s
    newAll = set()
    for s in newSets:
        newAll |= s
    union = oldAll | newAll
    memberDrift = (len(oldAll ^ newAll) / len(union)) if union else 0.0

    def _avgBest(src: List[set], dst: List[set]) -> float:
        sims = []
        for s in src:
            best = 0.0
            for d in dst:
                union2 = s | d
                if union2:
                    best = max(best, len(s & d) / len(union2))
            sims.append(best)
        return sum(sims) / len(sims) if sims else 1.0

    structureDrift = 1.0 - (_avgBest(oldSets, newSets)
                            + _avgBest(newSets, oldSets)) / 2.0
    return round(max(memberDrift, structureDrift), 6)


def _digest(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def communityGlobalSearch(store: Any, query: str, agentId: str = "default",
                          tenantId: str = "default",
                          limit: int = 5) -> List[Dict[str, Any]]:
    """global 检索：查询→社区摘要 map 命中（词法重叠计分，零新依赖）。"""
    queryTokens = set(query.casefold())
    hits: List[Dict[str, Any]] = []
    # P3-6：读数走 store 只读公开口（表随 store 建库时就绪，无需此地再保一次 schema）。
    rows = store.queryReadOnly(
        "SELECT community_id, member_labels_json, summary_text"
        " FROM ontology_communities WHERE tenant_id = ? ORDER BY level",
        (tenantId,))
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
    # P3-6：读数走 store 只读公开口（同 communityGlobalSearch）。
    rows = store.queryReadOnly(
        "SELECT DISTINCT f.object_term FROM knowledge_facts f"
        " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
        " WHERE s.canonical_label = ? AND s.agent_id = ? AND s.tenant_id = ?"
        " AND f.status = 'active' AND f.record_kind = 'triple' LIMIT ?",
        (entityLabel, agentId, tenantId, int(limit)))
    neighbors = [str(r["object_term"]) for r in rows]
    hits: List[Dict[str, Any]] = []
    rows = store.queryReadOnly(
        "SELECT community_id, member_labels_json, summary_text"
        " FROM ontology_communities WHERE tenant_id = ?", (tenantId,))
    for row in rows:
        labels = json.loads(row["member_labels_json"] or "[]")
        if entityLabel in labels or any(n in labels for n in neighbors):
            hits.append({"community_id": str(row["community_id"]),
                         "labels": labels,
                         "summary": str(row["summary_text"] or ""),
                         "matched_neighbor": entityLabel if entityLabel in labels
                         else next((n for n in neighbors if n in labels), "")})
    return hits[:max(1, int(limit))]
