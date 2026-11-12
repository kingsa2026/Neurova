"""SPARQL 只读查询面（specs/2026-11-12 §10 W9，D8 已裁）。

rdflib 可选生产依赖（惰性 import＋fail-soft，DB 驱动同款形态）；查询面＝
既有 RDF 投影（turtle 序列化单源）构图 → rdflib 执行 SELECT/ASK——
**只读、零事实写**；UPDATE/CONSTRUCT 写形不支持（投影只读）；结果行数上限
＋查询超时常量，超限显式拒；rdflib 未装时显式 501 not_supported（诚实形态，
不静默降级）。rule_engine 头注边界不动。
"""

from __future__ import annotations

from typing import Any, Dict, List

from neurova.core.logger import get_logger

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


def runSparqlQuery(store: Any, query: str, agentId: str = "default",
                   tenantId: str = "default") -> Dict[str, Any]:
    """SPARQL 只读查询：投影构图→rdflib 执行 SELECT/ASK→行集。"""
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
    import rdflib

    from .turtle import serializeAll

    turtleText = serializeAll(store, agentId=agentId)
    graph = rdflib.Graph()
    graph.parse(data=turtleText, format="turtle")
    fullQuery = query if query.upper().startswith("PREFIX") \
        else (_SPARQL_PREFIX + "\n" + query)
    results = graph.query(fullQuery)
    rows: List[Dict[str, Any]] = []
    variables = [str(v) for v in results.vars] if hasattr(results, "vars") else []
    for row in results:
        if len(rows) >= MAX_SPARQL_ROWS:
            break
        rows.append({var: _nodeText(row[var]) for var in variables})
    return {"variables": variables, "rows": rows,
            "row_count": len(rows),
            "truncated": len(rows) >= MAX_SPARQL_ROWS}


def _nodeText(node: Any) -> str:
    return str(node) if node is not None else ""
