"""推导事实的读侧治理单源（升级计划 B1 拍板项 2 ＋ B4 溯源契约）。

一句话：**"这条结论是推出来的"这件事，只在这里判一次**。
判定依据是推导账本的边（`knowledge_derivation_edges`），不是事实行里那个
`qualifier.derived_by` 抄送字段——账本同时是撤销与血缘视图的依据，读侧另拿
一份字符串当判据就是第二个事实源，两边哪天分叉，撤销和过滤会各说各话。

两件事分开，互不耦合：
- `filterConditionClassFacts` —— 观察态灰度（默认）：推导事实不作为检索条目出去，
  账本、血缘视图与本体 API 照常可查；`NEUROVA_CONDITION_CLASSES_ROUTE=1` 翻主路，双向可回滚。
- `annotateDerivations` —— 溯源标注：显式给每条命中盖 `derivation`，让调用方分得清
  观察事实与推导事实；显式事实是 `{"derived": False}`，**读账失败时整键不挂**
  （没有标注＝没溯过源，不等于"溯过、不是推导"）。

现役落点：`read_surface.FactSurface.search`（全仓唯一"事实→检索条目形状"的出口，
其种子锚点又被图谱路由吃掉 ⇒ 这是推导进对话的唯一活路，别在下游补判空）。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

#: 灰度开关：默认观察态（推导记账但不进检索池）
CONDITION_CLASS_ROUTE_ENV = "NEUROVA_CONDITION_CLASSES_ROUTE"
_ROUTE_ON = ("1", "true", "on", "yes")

#: 显式事实的标注形态——单点定义，消费方按这个形状读
NOT_DERIVED: Dict[str, Any] = {"derived": False}


def conditionClassRouteOn() -> bool:
    """这一轮推导事实进不进检索池——每次现读环境变量，不做进程级缓存。

    缓存它就等于给灰度加第二层默认值：翻开关要重启，回滚不再是双向的。
    """
    return str(os.environ.get(CONDITION_CLASS_ROUTE_ENV) or "").strip().lower() in _ROUTE_ON


def _derivedFactIds(store: Any) -> set:
    """全库"被推导过"的事实 id，一条 DISTINCT 取完。

    刻意不按命中集拼 `IN (…)`：读面的候选池可达全库活动事实，参数个数能顶穿
    SQLite 的变量上限，而这条表只有推导事实，本来比候选池小得多。
    """
    return set(store._derivationLedger.derivedFactIds())


def filterConditionClassFacts(items: List[Dict[str, Any]],
                              store: Any) -> Tuple[List[Dict[str, Any]], int]:
    """观察态下把推导事实从检索池里摘掉，返回 `(留下的条目, 摘掉条数)`。

    翻主路时无条件放行；读账失败时**放行**并记 0 摘除——读侧治理故障不该让
    检索主路陪葬，宁可多放一条推导，也不静默少放一片显式事实。
    """
    if conditionClassRouteOn() or not items:
        return items, 0
    if not any(item.get("lineage_id") for item in items):
        return items, 0
    try:
        derived = _derivedFactIds(store)
    except Exception:  # noqa: BLE001 - 读账失败让路，检索主路不陪葬
        return items, 0
    if not derived:
        return items, 0
    kept = [
        item for item in items
        if str(item.get("lineage_id") or "") not in derived
    ]
    return kept, len(items) - len(kept)


def derivationInfo(edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    """由推导边生成标注形状（规则号＋前提数）——这个形状只在这里定义一次。

    读面条目与图谱走查的跳都吃它：两处各拼一份 `{ruleId, premiseCount}` 就是
    第二个事实源，哪天一边改字段名，对话里的溯源会静默变成读不出来源的空壳。
    """
    if not edges:
        return dict(NOT_DERIVED)
    ruleIds = sorted({str(e["rule_id"]) for e in edges})
    return {
        "derived": True,
        "ruleId": ruleIds[0] if ruleIds else "",
        "premiseCount": len({str(e["premise_fact_id"]) for e in edges}),
    }


def annotateDerivations(items: List[Dict[str, Any]],
                        store: Any) -> List[Dict[str, Any]]:
    """给每条命中挂 `derivation`：推导的带规则号与前提数，显式的带 `{"derived": False}`。

    就地写键后原序返回（调用方拿到的是同一批条目，秩一个字不改）。逐条取边只对
    真推导的那几条发生（top-k 里通常为零）；读账失败时整键不挂：缺席是"没查过"的
    诚实形态，写 `{"derived": False}` 就是替账本作伪证。
    """
    if not items:
        return items
    lineageIds = [
        str(item["lineage_id"]) for item in items if item.get("lineage_id")
    ]
    try:
        derived = _derivedFactIds(store)
        edgesById = {
            factId: store._derivationLedger.premisesOf(factId) for factId in derived
            if factId in set(lineageIds)
        }
    except Exception:  # noqa: BLE001 - 标注失败只丢标注，不丢命中
        return items
    for item in items:
        edges = edgesById.get(str(item.get("lineage_id") or ""))
        item["derivation"] = derivationInfo(edges or [])
    return items


def derivationSummary(annotated: List[Dict[str, Any]]) -> Dict[str, Any]:
    """这一批命中的推导占比读数——没有它，"灰度效果"只能靠猜。"""
    return {
        "hits": len(annotated),
        "derived_hits": sum(
            1 for item in annotated
            if (item.get("derivation") or {}).get("derived") is True
        ),
    }
