# -*- coding: utf-8 -*-
"""SPARQL 投影图缓存（C 维增强批 P1-1）：投影图按 (租户, agent) 复用＋增量拼接。

U2 的行集缓存（query_cache.py）免掉了「同一查询重复求值」，但事实水印一变，
未命中路径仍要 `serializeAll` 全量重投影＋rdflib 全量重解析。本模块把**投影图
本身**缓存下来：

- 水印未变（逐主体内容指纹全等）→ 直接复用已解析的 rdflib 图，零投影零解析；
- 水印变了 → 按**主体粒度内容指纹**（逐行滚动哈希）对比出增/删/改的脏主体，
  只对脏主体 `serializeAll(subjectKeys=…)` 重投影，先从缓存图摘掉脏主体的
  旧三元组、再把子图并回去——**增量拼接**。

正确性锚点（为什么按主语摘除就是完整摘除）：

- facts 段的客体一律是字面量或术语 IRI（is_a 走 `rdf:type` 独立行），不存在
  「某主体的 IRI 出现在他人三元组宾语位」的交叉引用——摘主语即摘净该主体的
  全部投影痕迹；
- `serializeAll(subjectKeys=…)` 的子图永远带全量 terms/rules/standards 段，
  rdflib 图是集合语义（重复加无副作用）：主体块与术语块 IRI 撞名时，摘除波及
  的术语块会由子图原样补回，不丢行；
- 主体指纹的过滤条件与 `serializeAll` 的 facts 段同形（tenant_sql_where ＋
  active＋triple ＋ 真值 agentId 过滤），指纹看不到的行就是投影里没有的行。

术语/规则指纹变化（本体结构变更）→ 整图重建：terms/rules 段是全量导出，
增量拼不安全；结构行数小，全量重建成本可控。

容量：`NEUROVA_ONTOLOGY_GRAPH_CACHE`（缺省 4 个图；0=禁用，回退每次全量
重投影）。rdflib 由调用方（sparql_query）先行校验可用，本模块惰性 import。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Dict, Optional, Tuple

from neurova.core.cache import MemoryCache
from neurova.core.logger import get_logger
from neurova.core.tenant_scope import tenant_sql_where
from neurova.knowledge.ontology.query_cache import termsFingerprint

logger = get_logger(__name__)

#: 图缓存容量环境变量；0 = 禁用（查询一律全量重投影）
GRAPH_CACHE_CAPACITY_ENV = "NEUROVA_ONTOLOGY_GRAPH_CACHE"
#: 缺省容量：图对象比行集重得多，缺省只留个位数的 (租户, agent) 组合
DEFAULT_GRAPH_CACHE_CAPACITY = 4

_MISS = object()


def resolveGraphCacheCapacity(explicit: Optional[int] = None) -> int:
    """容量口径：显式入参优先，否则读环境变量；0=禁用，负数按 0（禁用）。

    环境变量非法（非整数）时告警并回退缺省——缓存配置错误不该把查询面打挂。
    """
    import os

    if explicit is not None:
        return max(0, int(explicit))
    raw = str(os.environ.get(GRAPH_CACHE_CAPACITY_ENV) or "").strip()
    if not raw:
        return DEFAULT_GRAPH_CACHE_CAPACITY
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("环境变量 %s=%r 不是整数，回退缺省容量 %d",
                       GRAPH_CACHE_CAPACITY_ENV, raw,
                       DEFAULT_GRAPH_CACHE_CAPACITY)
        return DEFAULT_GRAPH_CACHE_CAPACITY


def _subjectFingerprints(store: Any, tenantId: str,
                         agentId: Any) -> Dict[str, int]:
    """主体粒度内容指纹：投影可见行（与 serializeAll 的 facts 段同形过滤与排序）
    按 subject_key 做滚动哈希。

    必须是**内容**指纹而非长度/行号聚合：主体合并与版本回滚会就地改写
    object_term（等长改写连长度和都探不到），行号聚合也只探增删。这里逐行
    取 (predicate, object, fact_id) 滚动哈希——同一主体任一行内容变化，
    指纹必变；哈希只在进程内用于失效比对（缓存不跨进程存活），随机化无妨。
    """
    clause, clauseParams = tenant_sql_where(str(tenantId or "default"))
    sql = ("SELECT subject_key, predicate_term_id, object_term, fact_id"
           " FROM knowledge_facts WHERE %s AND status = 'active'"
           " AND record_kind = 'triple'" % clause)
    params: list = list(clauseParams)
    if agentId:
        sql += " AND agent_id = ?"
        params.append(str(agentId))
    sql += " ORDER BY subject_key, predicate_term_id, object_term, fact_id"
    with store._lock:
        rows = store._conn.execute(sql, params).fetchall()
    fps: Dict[str, int] = {}
    for row in rows:
        key = str(row["subject_key"])
        item = (str(row["predicate_term_id"]), str(row["object_term"]),
                str(row["fact_id"]))
        fps[key] = ((fps.get(key, 0) * 1000003) ^ hash(item)) & 0xFFFFFFFFFFFFFFFF
    return fps


class GraphProjectionCache:
    """投影图 LRU 缓存：键 = (tenantId, agentId)，值 = 已解析 rdflib 图＋指纹。

    `reading()` 是唯一消费口：返回图的同时持有该条目的写锁，调用方在
    with 块内完成 SPARQL 求值——增量拼接与并发求值互斥，图不会边查边改。
    """

    def __init__(self, capacity: Optional[int] = None) -> None:
        self._capacity = resolveGraphCacheCapacity(capacity)
        self._lock = threading.RLock()
        self._cache: Optional[MemoryCache] = (
            MemoryCache(capacity=self._capacity, cleanup_interval=0)
            if self._capacity > 0 else None)
        self._entryLocks: Dict[Tuple[str, str], threading.RLock] = {}
        # 观测计数（stats 读面与判据用）
        self._fullRebuilds = 0
        self._incrementalSplices = 0
        self._subjectsSpliced = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def enabled(self) -> bool:
        return self._cache is not None

    def _entryLock(self, key: Tuple[str, str]) -> threading.RLock:
        with self._lock:
            lock = self._entryLocks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._entryLocks[key] = lock
            return lock

    @contextmanager
    def reading(self, store: Any, *, tenantId: str, agentId: Any):
        """取出（或增量拼接出）当前投影图，并在条目锁内交给调用方求值。"""
        if self._cache is None:
            yield self._buildFull(store, tenantId, agentId)
            return
        key = (str(tenantId or "default"), str(agentId) if agentId else "")
        with self._entryLock(key):
            graph = self._resolve(store, tenantId, agentId, key)
            yield graph

    def _resolve(self, store: Any, tenantId: str, agentId: Any,
                 key: Tuple[str, str]):
        import rdflib

        termsFp = termsFingerprint(store, str(tenantId or "default"))
        subjectFps = _subjectFingerprints(store, tenantId, agentId)
        with self._lock:
            entry = self._cache.get(key, _MISS)
        if entry is not _MISS and entry["termsFp"] == termsFp:
            graph = entry["graph"]
            oldFps: Dict[str, int] = entry["subjectFps"]
            dirty = sorted(k for k, fp in subjectFps.items()
                           if oldFps.get(k) != fp)
            gone = sorted(k for k in oldFps if k not in subjectFps)
            if dirty or gone:
                self._splice(store, graph, tenantId, agentId, dirty, gone)
                self._incrementalSplices += 1
                self._subjectsSpliced += len(dirty) + len(gone)
            with self._lock:
                self._cache.set(key, {"graph": graph, "termsFp": termsFp,
                                      "subjectFps": subjectFps})
            return graph
        graph = self._buildFull(store, tenantId, agentId)
        with self._lock:
            self._cache.set(key, {"graph": graph, "termsFp": termsFp,
                                  "subjectFps": subjectFps})
        return graph

    def _buildFull(self, store: Any, tenantId: str, agentId: Any):
        """全量重建：serializeAll 全库 → rdflib 解析。"""
        import rdflib

        from neurova.knowledge.ontology.turtle import serializeAll

        turtleText = serializeAll(store, tenantId=str(tenantId or "default"),
                                  agentId=agentId)
        graph = rdflib.Graph()
        graph.parse(data=turtleText, format="turtle")
        self._fullRebuilds += 1
        return graph

    def _splice(self, store: Any, graph: Any, tenantId: str, agentId: Any,
                dirty: list, gone: list) -> None:
        """增量拼接：摘掉脏主体/消失主体的旧三元组，重投影脏主体并并回。"""
        import rdflib

        from neurova.knowledge.ontology.turtle import NAMESPACE, iriLocal, serializeAll

        for key in list(dirty) + list(gone):
            graph.remove((rdflib.URIRef(NAMESPACE + iriLocal(key)),
                          None, None))
        if dirty:
            subgraphText = serializeAll(store, tenantId=str(tenantId or "default"),
                                        agentId=agentId, subjectKeys=dirty)
            subgraph = rdflib.Graph()
            subgraph.parse(data=subgraphText, format="turtle")
            for triple in subgraph:
                graph.add(triple)

    def stats(self) -> Dict[str, Any]:
        """缓存观测快照（P2-5 读面消费；禁用时 enabled=False、计数保持）。"""
        if self._cache is None:
            return {"enabled": False, "capacity": self._capacity, "size": 0,
                    "full_rebuilds": self._fullRebuilds,
                    "incremental_splices": self._incrementalSplices,
                    "subjects_spliced": self._subjectsSpliced}
        with self._lock:
            stats = self._cache.get_stats()
        stats["enabled"] = True
        stats["full_rebuilds"] = self._fullRebuilds
        stats["incremental_splices"] = self._incrementalSplices
        stats["subjects_spliced"] = self._subjectsSpliced
        return stats
