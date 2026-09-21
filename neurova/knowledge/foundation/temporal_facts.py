"""时效事实读面（工单 012，灭 B01）：对话链那条分支改读底座库。

B01 的形状是"接了但不工作"：`chat_pipeline.py` 无参构造 `TemporalKnowledgeGraph()`，
其 `db_path` 默认 `":memory:"`，于是 priority 26 的检索器每轮扫自己那张空表——
成本恒定、收益恒零，而且每轮还可能重造实例。本模块不做兼容层，直接把这条分支的
数据源换成唯一权威：`knowledge_facts` 里"此刻仍然有效"的三元组。

三条口径写清楚，免得又长成第二套规则：

- **只供三元组**。条目正文（`record_kind='narrative'`）由 `KnowledgeRetriever` 那一路给；
  这里再放一份就是同一篇正文占两个槽。
- **"生效时间"取 `valid_from`，没声明就用 `recorded_at`**（**只限下界**）。缺列值不等于没有时间，
  但 `recorded_at` 是"我们何时得知"，不是"说法何时生效"——上界只认声明的 `valid_from`，
  否则参考时刻早于写入时刻的查询会把此刻仍有效的说法读没。
- **匹配规则是"主体名（或别名）出现在查询文本里"**，不做分词。旧的关键词切法用
  `[^\\w\\s]`，中文整句会切成一个 token，只有全句正好等于主体名才命中——那等于没有匹配。
  主体集合规模是"实体数"而不是"事实数"，一遍扫过即可，不为此引分词依赖。
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Optional

_UTC = datetime.timezone.utc
_MIN_LABEL_CHARS = 2


def subjectsMentionedIn(store: Any, query: str,
                        agentId: Optional[str] = None) -> List[str]:
    """"这条查询在问谁"的唯一判据：主体名或别名被查询文本包含。

    时效读面与多跳走查共用它——两条分支对"问的是谁"给出不同答案，
    就等于同一句话在一轮里被当成两件事。大小写不敏感；短于 2 字的标签不算
    （否则一个"的"字就能把整张图拽进上下文）。
    """
    haystack = (query or "").casefold()
    if not haystack:
        return []
    where = ["status = 'active'"]
    params: List[Any] = []
    if agentId:
        where.append("agent_id = ?")
        params.append(agentId)
    with store._lock:
        rows = store._conn.execute(
            "SELECT subject_key, canonical_label, aliases_json FROM knowledge_subjects"
            " WHERE %s" % " AND ".join(where), params).fetchall()
    keys: List[str] = []
    for row in rows:
        labels = [str(row["canonical_label"] or "")]
        try:
            labels += [str(a) for a in json.loads(row["aliases_json"] or "[]")]
        except (ValueError, TypeError):
            pass
        if any(len(label.strip()) >= _MIN_LABEL_CHARS and label.casefold() in haystack
               for label in labels):
            keys.append(row["subject_key"])
    return keys


class TemporalFactReader:
    """底座时效视图：`query_tkg_for_context` 的返回形状与旧桥逐字相同（检索链契约不破）。"""

    def __init__(self, store: Any, agentId: Optional[str] = None) -> None:
        if store is None:
            raise ValueError("TemporalFactReader 需要底座库句柄——不给权威就没得读")
        self._store = store
        self._agentId = agentId

    # ── 检索链契约 ────────────────────────────────────────────

    def query_tkg_for_context(self, query: str, max_facts: int = 10,
                              time_window_days: int = 30) -> List[Dict[str, Any]]:
        """`TKGRetrieverAdapter` 按这个名字与参数表调用，形状一字不改。"""
        return self.forQuery(query, maxFacts=max_facts, windowDays=time_window_days)

    def forQuery(self, query: str, maxFacts: int = 10, windowDays: int = 30,
                 now: Optional[datetime.datetime] = None) -> List[Dict[str, Any]]:
        text = (query or "").strip()
        if not text or maxFacts <= 0:
            return []
        moment = (now or datetime.datetime.now(_UTC)).astimezone(_UTC)
        windowStart = moment - datetime.timedelta(days=max(int(windowDays or 0), 0))
        keys = subjectsMentionedIn(self._store, text, self._agentId)
        if not keys:
            return []
        rows = self._effectiveFacts(keys, windowStart, moment, maxFacts)
        return [self._asFactDict(row) for row in rows]

    # ── 内部 ──────────────────────────────────────────────────

    def _effectiveFacts(self, keys: List[str], windowStart: datetime.datetime,
                        now: datetime.datetime, limit: int) -> List[Any]:
        placeholders = ",".join("?" * len(keys))
        # 生效时刻**下界**要有：只判上界的话，一条半年前的说法照样进此刻的上下文。
        # `valid_from` 没声明就退到 `recorded_at`——缺列值不等于没有时间。
        effective = "COALESCE(NULLIF(valid_from, ''), recorded_at)"
        clauses = [
            "subject_key IN (%s)" % placeholders,
            "status = 'active'",
            "record_kind = 'triple'",
            "%s >= ?" % effective,
            # 生效时刻**上界**只认调用方声明的 `valid_from`，不许拿 `recorded_at` 顶替：
            # 后者是"我们何时得知"，不是"说法何时生效"。混用会让参考时刻早于写入时刻的
            # 查询把**此刻仍然有效**的说法读没——同一份数据在 12:00Z 前后给出相反结论。
            "(valid_from IS NULL OR valid_from = '' OR valid_from <= ?)",
            "(valid_until IS NULL OR valid_until = '' OR valid_until > ?)",
        ]
        params: List[Any] = list(keys) + [windowStart.isoformat(), now.isoformat(),
                                          now.isoformat()]
        if self._agentId:
            clauses.insert(0, "agent_id = ?")
            params = [self._agentId] + params
        with self._store._lock:
            return self._store._conn.execute(
                "SELECT * FROM knowledge_facts WHERE %s"
                " ORDER BY (confidence IS NULL), confidence DESC,"
                " COALESCE(NULLIF(valid_from, ''), recorded_at) DESC, fact_id"
                " LIMIT ?" % " AND ".join(clauses),
                params + [limit]).fetchall()

    def _asFactDict(self, row: Any) -> Dict[str, Any]:
        fact = self._store._hydrate(row)
        subject = self._store.subjectFor(fact["subject_key"]) or {}
        return {
            "id": fact["fact_id"],
            "subject": str(subject.get("canonical_label", "") or ""),
            "predicate": fact["predicate_term_id"],
            "object": fact["object_term"],
            "confidence": fact["confidence"],
            "valid_from": str(fact.get("valid_from") or fact.get("recorded_at") or ""),
            "source": self._mediumOf(fact["fact_id"]),
        }

    def _mediumOf(self, factId: str) -> str:
        """来源取最近一条断言的 medium_ref——审计读得到的东西，不另编一个字段。"""
        rows = self._store.assertions(factId)
        return str(rows[-1].get("medium_ref", "") or "") if rows else ""
