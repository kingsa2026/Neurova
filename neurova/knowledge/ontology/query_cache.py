"""SPARQL 投影缓存（升级卡 U2）：进程内 LRU，失效靠"库指纹进键"。

`runSparqlQuery` 每次执行都全量重投影（`serializeAll` 读全库出 Turtle）＋重解析
（`rdflib.Graph.parse`）。而查询结果是库内容的纯函数：只随（租户、agent、查询
文本、本体侧术语/规则、事实集）变化。于是失效不挂在写入口（那得扫全仓每条写
路径，漏一处就是脏读），而是把库的指纹编进缓存键：**库一动，键就换**，旧键由
LRU 自然淘汰——失效与写入路径解耦，可靠性等价于"键判等"。

指纹口径（各一条轻量聚合 SQL，范围对齐投影的**实际读取范围**）：

- `termsFingerprint`：ontology_terms + ontology_rules 各取 COUNT＋MAX(updated_at)。
  规则行也进 Turtle 投影（ruleId/headPredicate/body 都是图里的三元组），规则变更
  必须同样击穿缓存，故与术语同段指纹。范围用请求租户——投影按请求租户读行，
  指纹必须盯住真正被读的那批行（KNOW-01）。
- `factsWatermark`：knowledge_facts 中 `status='active' AND record_kind='triple'`
  且本租户（真值 agentId 再按 agent 过滤，与 `serializeAll` 同形）的行，取
  COUNT＋**全量内容滚动哈希**（rowid 序）。count 探增删；内容哈希探一切改写
  ——长度和探不到等长就地改写（主体合并/回滚的同长形态），水印是失效的
  唯一判据，宁可多扫一遍不可放过脏读（P1-1 起强化）。

缓存值是**投影行集快照**（variables/rows/row_count/truncated 的深拷贝），不是
rdflib 图对象：命中原样返回快照拷贝，与未命中路径逐字节一致，且连 SPARQL 求值
也不再重跑。存储层复用 `core/cache.py` 的 MemoryCache（全仓唯一 LRU 实现，
§6/§7 不另造第二份），本类只负责键构造、容量口径与快照拷贝。
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, Optional, Tuple

from neurova.core.cache import MemoryCache
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 缓存容量环境变量；0 = 禁用缓存（查询一律直查）
SPARQL_CACHE_CAPACITY_ENV = "NEUROVA_ONTOLOGY_SPARQL_CACHE"
#: 缺省容量
DEFAULT_SPARQL_CACHE_CAPACITY = 128

# 哨兵：区分"键不存在"与"缓存了合法值"（复用 core.cache 的哨兵语义）
_MISS = object()


def resolveCacheCapacity(explicit: Optional[int] = None) -> int:
    """容量口径：显式入参优先，否则读环境变量；0=禁用，负数按 0（禁用）。

    环境变量非法（非整数）时告警并回退缺省——缓存配置错误不该把查询面打成 500。
    """
    if explicit is not None:
        return max(0, int(explicit))
    raw = str(os.environ.get(SPARQL_CACHE_CAPACITY_ENV) or "").strip()
    if not raw:
        return DEFAULT_SPARQL_CACHE_CAPACITY
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("环境变量 %s=%r 不是整数，回退缺省容量 %d",
                       SPARQL_CACHE_CAPACITY_ENV, raw,
                       DEFAULT_SPARQL_CACHE_CAPACITY)
        return DEFAULT_SPARQL_CACHE_CAPACITY


def termsFingerprint(store: Any, tenantId: str) -> str:
    """本体侧指纹：terms＋rules 各 COUNT＋MAX(updated_at)（投影导出的两段）。"""
    with store._lock:
        termRow = store._conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(MAX(updated_at), '') AS mx"
            " FROM ontology_terms WHERE tenant_id = ?", (tenantId,)).fetchone()
        ruleRow = store._conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(MAX(updated_at), '') AS mx"
            " FROM ontology_rules WHERE tenant_id = ?", (tenantId,)).fetchone()
    return "terms:%s:%s|rules:%s:%s" % (termRow["cnt"], termRow["mx"],
                                        ruleRow["cnt"], ruleRow["mx"])


def factsWatermark(store: Any, tenantId: str, agentId: Any) -> str:
    """事实集水印：投影可见行（active＋triple、本租户，真值 agentId 再过滤）
    的 COUNT＋**全量内容滚动哈希**（行序按 rowid）。

    长度和口径探不到等长就地改写（主体合并改 subject_key、版本回滚恢复字段
    的同长形态）——水印是缓存失效的唯一判据，宁可每次多扫一遍，不可放过
    一次脏读，故逐行内容进滚动哈希（rowid 一并入账，增删必变）。
    """
    sql = ("SELECT subject_key, predicate_term_id, object_term, fact_id, rowid"
           " FROM knowledge_facts"
           " WHERE tenant_id = ? AND status = 'active' AND record_kind = 'triple'")
    params: list = [tenantId]
    if agentId:  # 与 serializeAll 的投影过滤同形：真值才按 agent 过滤
        sql += " AND agent_id = ?"
        params.append(str(agentId))
    sql += " ORDER BY rowid"
    with store._lock:
        rows = store._conn.execute(sql, params).fetchall()
    rolling = 0
    for row in rows:
        item = (str(row["subject_key"]), str(row["predicate_term_id"]),
                str(row["object_term"]), str(row["fact_id"]),
                int(row["rowid"]))
        rolling = ((rolling * 1000003) ^ hash(item)) & 0xFFFFFFFFFFFFFFFF
    return "facts:%d:%s" % (len(rows), "%016x" % rolling)


def _copySnapshot(result: Dict[str, Any]) -> Dict[str, Any]:
    """行集快照深拷贝：入缓存存拷贝、命中返回拷贝——调用方改不到缓存里的对象。"""
    return {"variables": list(result.get("variables") or []),
            "rows": [dict(row) for row in result.get("rows") or []],
            "row_count": result.get("row_count", 0),
            "truncated": bool(result.get("truncated", False))}


class SparqlProjectionCache:
    """SPARQL 投影 LRU 缓存。

    键 = (tenantId, agentId, 规范化查询, termsFingerprint, factsWatermark)。
    查询规范化只做去首尾空白：SPARQL 字面量内的空白有语义，token 级折叠需要
    完整词法器——为命中率冒错配风险不值当，键保守一点只损失命中、不损失正确。
    """

    def __init__(self, capacity: Optional[int] = None) -> None:
        self._capacity = resolveCacheCapacity(capacity)
        self._lock = threading.RLock()
        # 0 容量＝禁用：连 MemoryCache 都不建（它内部 max(1, capacity)，
        # 装不下"禁用"语义）。cleanup_interval=0 不起清理线程（无 TTL，无需清理）。
        self._cache: Optional[MemoryCache] = (
            MemoryCache(capacity=self._capacity, cleanup_interval=0)
            if self._capacity > 0 else None)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def enabled(self) -> bool:
        return self._cache is not None

    def buildKey(self, store: Any, tenantId: str, agentId: Any,
                 query: str) -> Tuple[str, str, str, str, str]:
        """缓存键：调用方维度（tenant/agent/查询）＋库内容维度（指纹/水印）。

        指纹与水印盯住请求租户（KNOW-01）：投影按请求租户读行，失效判据
        必须对齐同一批行——跨租户指纹会让他租户写入击不穿本租户缓存。
        """
        tenant = str(tenantId or "default")
        return (tenant,
                str(agentId) if agentId else "",
                str(query or "").strip(),
                termsFingerprint(store, tenant),
                factsWatermark(store, tenant, agentId))

    def lookup(self, key: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
        """命中返回快照拷贝；未命中/禁用返回 None（结果恒为 dict，None 无歧义）。"""
        if self._cache is None:
            return None
        with self._lock:
            snapshot = self._cache.get(key, _MISS)
        if snapshot is _MISS:
            return None
        return _copySnapshot(snapshot)

    def store(self, key: Tuple[str, ...], result: Dict[str, Any]) -> None:
        """未命中回填（禁用时静默跳过）；存拷贝，与调用方对象脱钩。"""
        if self._cache is None:
            return
        with self._lock:
            self._cache.set(key, _copySnapshot(result))

    def clear(self) -> int:
        """清空（运维/测试用）；返回清掉的条数。"""
        if self._cache is None:
            return 0
        with self._lock:
            return self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        """命中率统计快照（禁用时 enabled=False、计数恒 0）。"""
        if self._cache is None:
            return {"enabled": False, "capacity": self._capacity, "size": 0,
                    "hits": 0, "misses": 0, "evictions": 0, "hit_rate": 0.0}
        with self._lock:
            stats = self._cache.get_stats()
        stats["enabled"] = True
        return stats
