"""多跳图走查（工单 013，灭 B04）：属性图进对话链，读的是底座而不是 JSON 图。

B04 的形状是"图有 26% 覆盖率但答题时完全不被利用"。这里**不**把
`cognitive_layers/knowledge_graph/manager.py` 当读面：它把节点/边存成 JSON 文件、
遍历是 Python 侧 BFS 走内存 dict，与事实库是两套真相——从它读多跳，就会出现
"图上说一套、事实库里说一套"，正是这批改造要灭的病。

权威读面是 `knowledge_subjects` + `knowledge_facts` 上的递归 CTE，四条口径：

- **只走三元组**。叙述行的客体是内容键，当成边就会凭空造出一条没连过的链。
- **一跳不在此列**。一跳是时效读面（012）的活；两条分支都给就是同一说法占两个槽。
- **不跨 agent 域**。身份是 (agent, label) 维内唯一（`ux_subject_label`），
  跨域拼接等于把两个 agent 的说法连成一条链。
- **环靠"路径不重复经过同一主体"终止**，深度另有硬上限。SQLite 的递归 CTE 用
  `UNION ALL`，不去重——放任就是组合爆炸。

与 012 的另一处差别是刻意的：这里不按新近窗口筛（多跳问的是结构关系，不是"最近说过"），
但仍排除已失效说法。
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .temporal_facts import subjectsMentionedIn

GRAPH_RETRIEVER_ENV = "NEUROVA_KB_GRAPH_RETRIEVER"
_OFF_VALUES = ("0", "false", "off", "no")
_MAX_HOPS_CEILING = 4


@dataclass
class GraphWalkConfig:
    """多跳读面开关。默认开：B04 是断点不是新能力，关掉它等于把断点留在原地。"""

    enabled: bool = True
    maxHops: int = 2
    limit: int = 8

    @classmethod
    def fromEnv(cls) -> "GraphWalkConfig":
        raw = (os.environ.get(GRAPH_RETRIEVER_ENV) or "").strip().lower()
        return cls(enabled=raw not in _OFF_VALUES)


class GraphFactWalker:
    """从查询提到的主体出发，沿客体↔主体接力走若干跳。"""

    def __init__(self, store: Any, agentId: Optional[str] = None,
                 config: Optional[GraphWalkConfig] = None) -> None:
        if store is None:
            raise ValueError("GraphFactWalker 需要底座库句柄——不给权威就没得走")
        self._store = store
        self._agentId = agentId
        self._config = config or GraphWalkConfig.fromEnv()

    @property
    def factStore(self) -> Any:
        """检索器要拿它回写注入账（G07）；不暴露就别让旁路自己猜路径。"""
        return self._store

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def walkFromQuery(self, query: str, maxHops: Optional[int] = None,
                      limit: Optional[int] = None,
                      now: Optional[datetime.datetime] = None) -> List[Dict[str, Any]]:
        """返回 hop ≥ 2 的终点事实，按跳数由近及远、同跳内按置信与新近。"""
        hops = min(max(int(maxHops if maxHops is not None else self._config.maxHops), 2),
                   _MAX_HOPS_CEILING)
        cap = max(int(limit if limit is not None else self._config.limit), 1)
        anchors = subjectsMentionedIn(self._store, query or "", self._agentId)
        if not anchors:
            return []
        moment = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(
            datetime.timezone.utc)
        return [self._asHopDict(row) for row in self._walk(anchors, hops, cap, moment)]

    # ── 内部 ──────────────────────────────────────────────────

    def _walk(self, anchors: List[str], maxHops: int, limit: int,
              now: datetime.datetime) -> List[Any]:
        placeholders = ",".join("?" * len(anchors))
        stamp = now.isoformat()
        anchorClauses = ["f.status = 'active'", "f.record_kind = 'triple'",
                         "(f.valid_until IS NULL OR f.valid_until = ''"
                         " OR f.valid_until > ?)"]
        anchorValues: List[Any] = [stamp]
        if self._agentId:
            anchorClauses.append("f.agent_id = ?")
            anchorValues.append(self._agentId)
        # 递归段不再按 agent 过滤事实本身：域已经由 s2.agent_id = w.agent_id 与
        # f2.agent_id = s2.agent_id 两道锁住；多写一遍只会让"谁约束谁"看不清。
        headClause = ("f2.status = 'active' AND f2.record_kind = 'triple'"
                      " AND (f2.valid_until IS NULL OR f2.valid_until = ''"
                      " OR f2.valid_until > ?) AND f2.agent_id = s2.agent_id")
        #  visited 只记**经过的主体**（不含当前客体）：把客体也记进去，下一跳的起点
        #  永远被判成"重复经过"，整条链一步都走不动（本票第一版就是这么红的）。
        #  路径分隔符一律 ASCII：这条串会进日志与提示词，而 Windows 控制台默认码页
        #  不是 UTF-8，一个"⇒"就够把打印打成 UnicodeEncodeError。
        sql = (
            "WITH RECURSIVE walk(fact_id, agent_id, subject_key, predicate_term_id,"
            " object_term, confidence, recorded_at, hop, visited, path) AS ("
            "  SELECT f.fact_id, f.agent_id, f.subject_key, f.predicate_term_id,"
            "         f.object_term, f.confidence, f.recorded_at, 1,"
            "         '|' || lower(s0.canonical_label) || '|',"
            "         s0.canonical_label || ' -' || f.predicate_term_id || '-> '"
            "         || f.object_term"
            "  FROM knowledge_facts f"
            "  JOIN knowledge_subjects s0 ON s0.subject_key = f.subject_key"
            "  WHERE %s AND f.subject_key IN (%s)"
            "  UNION ALL"
            "  SELECT f2.fact_id, f2.agent_id, f2.subject_key, f2.predicate_term_id,"
            "         f2.object_term, f2.confidence, f2.recorded_at, w.hop + 1,"
            "         w.visited || lower(s2.canonical_label) || '|',"
            "         w.path || ' ; ' || s2.canonical_label || ' -' || f2.predicate_term_id"
            "         || '-> ' || f2.object_term"
            "  FROM walk w"
            "  JOIN knowledge_subjects s2 ON s2.agent_id = w.agent_id"
            "       AND s2.normalized_label = lower(trim(w.object_term))"
            "       AND s2.status = 'active'"
            "  JOIN knowledge_facts f2 ON f2.subject_key = s2.subject_key"
            "  WHERE w.hop < ? AND %s"
            "        AND instr(w.visited, '|' || lower(s2.canonical_label) || '|') = 0"
            ")"
            " SELECT * FROM walk WHERE hop >= 2"
            " ORDER BY hop, (confidence IS NULL), confidence DESC, recorded_at DESC, fact_id"
            " LIMIT ?"
        ) % (" AND ".join(anchorClauses), placeholders, headClause)
        params = anchorValues + anchors + [maxHops, stamp, limit]
        with self._store._lock:
            return self._store._conn.execute(sql, params).fetchall()

    def _asHopDict(self, row: Any) -> Dict[str, Any]:
        fact = dict(row)
        subject = self._store.subjectFor(fact["subject_key"]) or {}
        assertions = self._store.assertions(fact["fact_id"])
        return {
            "id": fact["fact_id"],
            "subject": str(subject.get("canonical_label", "") or ""),
            "predicate": fact["predicate_term_id"],
            "object": fact["object_term"],
            "confidence": fact["confidence"],
            "hop": fact["hop"],
            "path": fact["path"],
            "visited": fact["visited"],
            "source": str(assertions[-1].get("medium_ref", "") or "") if assertions else "",
        }
