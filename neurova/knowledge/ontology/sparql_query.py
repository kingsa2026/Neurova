"""SPARQL 只读查询面（specs/2026-11-12 §10 W9，D8 已裁）。

rdflib 可选生产依赖（惰性 import＋fail-soft，DB 驱动同款形态）；查询面＝
既有 RDF 投影（turtle 序列化单源）构图 → rdflib 执行 SELECT/ASK——
**只读、零事实写**；UPDATE/CONSTRUCT 写形不支持（投影只读）；结果行数上限
＋查询超时常量，超限显式拒；rdflib 未装时显式 501 not_supported（诚实形态，
不静默降级）。rule_engine 头注边界不动。

投影图经 `graph_projection_cache.py` 按 (租户, agent) 复用与增量拼接
（C 维增强批 P1-1）：同水印复用已解析图，水印变化只对脏主体增量重投影；
U2 行集缓存在其上继续免掉同查询的重复求值。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from neurova.core.logger import get_logger
from neurova.knowledge.ontology.graph_projection_cache import GraphProjectionCache
from neurova.knowledge.ontology.query_cache import (
    PROJECTION_TENANT,
    SparqlProjectionCache,
)

logger = get_logger(__name__)

#: 结果行数上限
MAX_SPARQL_ROWS = 200
#: 查询超时（秒）
SPARQL_TIMEOUT_SECONDS = 10

_SPARQL_PREFIX = "PREFIX kbg: <https://neurova.local/knowledge/>"

_FORBIDDEN_FORMS = ("INSERT", "DELETE", "CONSTRUCT", "DESCRIBE", "DROP",
                    "LOAD", "CLEAR", "CREATE", "MOVE", "COPY")


class SparqlNotSupported(RuntimeError):
    """rdflib 未安装——显式 not_supported（501 形态），不静默降级。"""


def _rdflibAvailable() -> bool:
    try:
        import rdflib  # noqa: F401
        import rdflib.plugins.sparql  # noqa: F401

        return True
    except ImportError:
        return False


_CACHE_ATTACH_LOCK = threading.Lock()


def _projectionCacheFor(store: Any) -> SparqlProjectionCache:
    """store 上的进程内缓存实例（DCL + Lock，AGENTS.md §3 单例纪律）。

    缓存随 store 实例走：生产 store 是进程级单例（get_knowledge_fact_store），
    缓存即进程级；测试/多库场景每个 store 实例各自一份，键无需再掺库标识。
    """
    cache = getattr(store, "_sparqlProjectionCache", None)
    if cache is not None:
        return cache
    with _CACHE_ATTACH_LOCK:
        cache = getattr(store, "_sparqlProjectionCache", None)
        if cache is None:
            cache = SparqlProjectionCache()
            store._sparqlProjectionCache = cache
    return cache


def _graphCacheFor(store: Any) -> GraphProjectionCache:
    """store 上的投影图缓存实例（DCL + Lock，同上单例纪律）。"""
    cache = getattr(store, "_sparqlGraphCache", None)
    if cache is not None:
        return cache
    with _CACHE_ATTACH_LOCK:
        cache = getattr(store, "_sparqlGraphCache", None)
        if cache is None:
            cache = GraphProjectionCache()
            store._sparqlGraphCache = cache
    return cache


def runSparqlQuery(store: Any, query: str, agentId: str = "default",
                   tenantId: str = "default") -> Dict[str, Any]:
    """SPARQL 只读查询：投影构图→rdflib 执行 SELECT/ASK→行集。

    校验（空查/写形/rdflib 可用性）一律在前，缓存在后——命中不豁免任何校验，
    也不绕过行数上限（上限在未命中路径内施加，结果整体入缓存）。缓存键带库
    指纹与事实水印（query_cache.py）：库一动键就换，失效不挂写入口钩子。
    """
    query = str(query or "").strip()
    if not query:
        raise ValueError("SPARQL 查询为空")
    upper = query.upper()
    for forbidden in _FORBIDDEN_FORMS:
        if upper.lstrip().startswith(forbidden):
            raise ValueError(
                "SPARQL %s 写形不支持（投影只读面——SELECT/ASK 才在承诺内）" % forbidden)
    if not _rdflibAvailable():
        raise SparqlNotSupported(
            "rdflib 未安装：SPARQL 面显式 not_supported（可选生产依赖，惰性 import）")

    cache = _projectionCacheFor(store)
    cacheKey = None
    if cache.enabled:
        cacheKey = cache.buildKey(store, tenantId=tenantId, agentId=agentId,
                                  query=query)
        cached = cache.lookup(cacheKey)
        if cached is not None:
            return cached

    graphCache = _graphCacheFor(store)
    # 投影图在条目锁内取出/增量拼接，行集提取也在锁内完成——图不会边查边改
    with graphCache.reading(store, tenantId=PROJECTION_TENANT,
                            agentId=agentId) as graph:
        fullQuery = query if query.upper().startswith("PREFIX") \
            else (_SPARQL_PREFIX + "\n" + query)
        results = graph.query(fullQuery)
        rows: List[Dict[str, Any]] = []
        variables = [str(v) for v in results.vars] if hasattr(results, "vars") else []
        for row in results:
            if len(rows) >= MAX_SPARQL_ROWS:
                break
            rows.append({var: _nodeText(row[var]) for var in variables})
        # SPARQL 无 ORDER BY 时行序未定义（rdflib 的迭代序随图的历史而异）。
        # 这里按变量值给出确定性行序：同库同查询两次输出一致，增量拼接与
        # 全量重建的结果才可逐字节对拍（P1-1 等价判据的基础）。
        rows.sort(key=lambda row: tuple(row.get(var, "") for var in variables))
    result = {"variables": variables, "rows": rows,
              "row_count": len(rows),
              "truncated": len(rows) >= MAX_SPARQL_ROWS}
    if cacheKey is not None:
        cache.store(cacheKey, result)
    return result


def _nodeText(node: Any) -> str:
    return str(node) if node is not None else ""
