"""睡眠归纳相位（T2）——深睡/休眠窗口内的 LLM schema 归纳。

DCPM（arXiv:2606.09483）System2 的启发：夜间引擎在"整理"之外还要做"归纳"——
从尚未被上层结构引用的事实里，按主题聚簇并归纳出行为规律（schema），供
后续检索浮出。本模块把这一相位装进本仓既有的睡眠窗口（IdleTimeTracker 的
deep_sleep/hibernate 触发点），不新增后台链路。

纪律（方案文档总原则）：
- **门控默认关**：``NEUROVA_SLEEP_INDUCTION`` 未开时本相位整体直通，
  行为与现状逐字节一致；
- **产物必带证据回指**：每个 schema 节点的 metadata.evidence 落源记忆 id；
- **按隔离三元组分桶**：聚类绝不跨 (agent, neuser, user) 作用域——
  alice 的事实归纳不出 bob 的 schema；
- **读路径零 LLM**：本模块只在睡眠窗口被调用，召回面不引入模型调用；
- **fail-soft**：LLM 单簇失败只跳过该簇并如实计数，绝不阻断整理主流程。

产物落点 = T4b 收口后的统一依赖图（``get_dependency_graph()``），实体类型
``schema``，检索面（/neuron API 与 T3 的行为匹配浮出）据此消费。
"""

from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.core.vector_math import cosineSimilarity

logger = get_logger(__name__)

#: 门控环境变量（默认 off；运维/测试经环境变量显式开启）
INDUCTION_ENV = "NEUROVA_SLEEP_INDUCTION"

#: 簇内最少事实数（低于此数不成簇——单条事实没有"规律"可归纳）
INDUCTION_MIN_CLUSTER = 2

#: 每周期 schema 产量上限（LLM 预算闸）
INDUCTION_MAX_SCHEMAS_PER_CYCLE = 8

#: 同簇相似度下限（语义近邻；区别于睡眠去重的"近等价" 0.98——归纳要的是
#: 同主题，不是同一条事实的重复记录。0.75 经真嵌入实测标定：同主题句对
#: ≈0.84-0.86，无关句对通常 <0.5）
INDUCTION_COSINE_THRESHOLD = 0.75

#: 单周期选材上限（超出按温度优先取舍，余量如实计入 deferred）
INDUCTION_MAX_CANDIDATES = 400

#: 归纳 LLM 调用提示词（要求严格 JSON，便于确定性解析）
INDUCTION_PROMPT = (
    "以下是从同一用户记忆中聚出的一组事实。请归纳它们共同体现的行为规律或"
    "稳定偏好，输出严格 JSON（不要多余文字）：\n"
    '{"name": "<4-12 字的模式名>", "pattern": "<一句话规律描述>"}\n'
    "事实清单：\n"
)

#: 依赖图上 schema 实体的类型标识
SCHEMA_ENTITY_TYPE = "schema"

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_TRUTHY = ("1", "true", "on", "yes")


def sleepInductionEnabled() -> bool:
    """门控读取（调用时解析，测试/运维可实时翻转）。"""
    import os

    return str(os.environ.get(INDUCTION_ENV, "")).strip().lower() in _TRUTHY


def _scopeKey(row: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(row.get("agent_id") or "default"),
        str(row.get("neuser_id") or "default"),
        str(row.get("user_id") or "default"),
    )


def _existingEvidenceIds(graph: Any) -> set:
    """既有 schema 节点已引用的事实 id 集合（这些事实不再重复参选）。"""
    covered: set = set()
    if graph is None:
        return covered
    try:
        for entity in graph.entities.values():
            if getattr(entity, "entity_type", "") != SCHEMA_ENTITY_TYPE:
                continue
            for eid in (getattr(entity, "metadata", None) or {}).get("evidence") or []:
                covered.add(str(eid))
    except Exception as e:  # noqa: BLE001 - 图读取失败按"无既有 schema"处理
        logger.debug("既有 schema 证据索引读取失败: %s", e)
    return covered


def _existingPatterns(graph: Any) -> Dict[Optional[Tuple[str, str, str]], set]:
    """既有 schema 的 pattern 归一集合，**按作用域分桶**（同 pattern 在不同
    作用域是两个合法 schema——去重只在本作用域内做）。无 scope 元数据的
    既有节点归入 None 桶，对任何作用域都保守拦截。"""
    patterns: Dict[Optional[Tuple[str, str, str]], set] = defaultdict(set)
    if graph is None:
        return patterns
    try:
        for entity in graph.entities.values():
            if getattr(entity, "entity_type", "") != SCHEMA_ENTITY_TYPE:
                continue
            pattern = str((getattr(entity, "metadata", None) or {}).get("pattern") or "")
            if not pattern.strip():
                continue
            scope = (getattr(entity, "metadata", None) or {}).get("scope")
            if isinstance(scope, (list, tuple)) and len(scope) == 3:
                key = tuple(str(s) for s in scope)
            else:
                key = None
            patterns[key].add("".join(pattern.split()).lower())
    except Exception as e:  # noqa: BLE001
        logger.debug("既有 pattern 索引读取失败: %s", e)
    return patterns


def selectInductionCandidates(
    manager: Any, graph: Any = None
) -> Dict[Tuple[str, str, str], List[Dict[str, Any]]]:
    """选材：活跃、有嵌入、未被既有 schema 证据引用的事实，按作用域分桶。

    使用系统面 ``get_all_memories()``（睡眠窗口本就是后台系统上下文），
    分桶保证归纳不跨作用域。``graph`` 缺省取模块单例。
    """
    if graph is None:
        graph = get_dependency_graph_safe()
    rows = manager.get_all_memories() or []
    covered = _existingEvidenceIds(graph)
    buckets: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("lifecycle_stage") or "active").lower() != "active":
            continue  # 退役行不参选（与睡眠整理的退役口径一致）
        embedding = row.get("embedding") or []
        if not isinstance(embedding, (list, tuple)) or len(embedding) == 0:
            continue  # 无嵌入无法聚类
        if str(row.get("id") or "") in covered:
            continue  # 已被既有 schema 引用
        buckets[_scopeKey(row)].append(row)
    # 温度优先取舍（与联想线索冷启动同一取舍观：先保最"热"的）
    for scope, bucket in buckets.items():
        bucket.sort(key=lambda r: float(r.get("temperature") or 0.0), reverse=True)
        if len(bucket) > INDUCTION_MAX_CANDIDATES:
            del bucket[INDUCTION_MAX_CANDIDATES:]
    return dict(buckets)


def get_dependency_graph_safe():
    """统一图的单例取法（失败返回 None，选材退化为"无既有 schema"）。"""
    try:
        from neurova.cognitive_layers.memory_layer.dependency_graph import (
            get_dependency_graph,
        )

        return get_dependency_graph()
    except Exception as e:  # noqa: BLE001
        logger.debug("依赖图单例不可用: %s", e)
        return None


def clusterRecords(rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """贪心语义聚类：与簇代表余弦达阈值即入簇，否则自立新簇。"""
    clusters: List[List[Dict[str, Any]]] = []
    for row in rows:
        embedding = list(row.get("embedding") or [])
        best: Optional[List[Dict[str, Any]]] = None
        best_sim = 0.0
        for cluster in clusters:
            rep = list(cluster[0].get("embedding") or [])
            try:
                sim = float(cosineSimilarity(embedding, rep))
            except Exception:  # noqa: BLE001 - 单对相似度失败按不相似处理
                continue
            if sim >= INDUCTION_COSINE_THRESHOLD and sim > best_sim:
                best_sim = sim
                best = cluster
        if best is not None:
            best.append(row)
        else:
            clusters.append([row])
    return clusters


def _parseSchemaResponse(text: str) -> Optional[Dict[str, str]]:
    """从模型回复里取严格 JSON 的 name/pattern（容忍前后杂质）。"""
    if not text:
        return None
    match = _JSON_RE.search(str(text))
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    name = str(data.get("name") or "").strip()
    pattern = str(data.get("pattern") or "").strip()
    if not name or not pattern:
        return None
    return {"name": name, "pattern": pattern}


def induceSchemaForCluster(
    cluster: List[Dict[str, Any]], llm_fn: Callable[[str], str]
) -> Optional[Dict[str, str]]:
    """对一簇事实做一次 LLM 归纳；任何失败返回 None（调用方跳过该簇）。"""
    if llm_fn is None:
        return None
    listing = "\n".join(
        f"- {row.get('id')}: {str(row.get('content') or '')[:200]}"
        for row in cluster
    )
    try:
        response = llm_fn(INDUCTION_PROMPT + listing)
        return _parseSchemaResponse(response)
    except Exception as e:  # noqa: BLE001 - 单簇归纳失败不阻断睡眠链
        logger.warning("睡眠归纳：单簇 LLM 调用失败（跳过该簇）: %s", e)
        return None


def runSleepInduction(
    manager: Any,
    llm_fn: Optional[Callable[[str], str]],
    graph: Any = None,
    *,
    max_schemas: int = INDUCTION_MAX_SCHEMAS_PER_CYCLE,
) -> Dict[str, Any]:
    """执行一次睡眠归纳相位（深睡/休眠触发点调用；门控关闭时直通）。

    Returns:
        如实计数：enabled/candidates/clusters/schemas/deferred/dedup_skipped/
        failed/max_schemas；entities 为本轮新写的图节点（测试与日志用）。
    """
    stats: Dict[str, Any] = {
        "enabled": sleepInductionEnabled(),
        "candidates": 0,
        "clusters": 0,
        "schemas": 0,
        "deferred": 0,
        "dedup_skipped": 0,
        "failed": 0,
        "max_schemas": int(max_schemas),
        "entities": [],
    }
    if not stats["enabled"] or manager is None:
        return stats
    if graph is None:
        graph = get_dependency_graph_safe()
    if graph is None:
        logger.warning("睡眠归纳：依赖图不可用，本周期跳过")
        return stats

    buckets = selectInductionCandidates(manager, graph)
    existing_patterns = _existingPatterns(graph)
    written = 0

    for scope, rows in sorted(buckets.items()):
        clusters = [
            c for c in clusterRecords(rows) if len(c) >= INDUCTION_MIN_CLUSTER
        ]
        stats["clusters"] += len(clusters)
        for cluster in clusters:
            if written >= max_schemas:
                stats["deferred"] += 1
                continue
            parsed = induceSchemaForCluster(cluster, llm_fn)
            if parsed is None:
                stats["failed"] += 1
                continue
            normalized = "".join(parsed["pattern"].split()).lower()
            if normalized in existing_patterns.get(scope, set()) or normalized in existing_patterns.get(None, set()):
                stats["dedup_skipped"] += 1
                continue
            agent_id, neuser_id, user_id = scope
            entity_id = f"schema:{agent_id}:{uuid.uuid4().hex[:12]}"
            if not graph.add_entity(
                _makeSchemaEntity(entity_id, parsed, cluster, scope)
            ):
                stats["failed"] += 1
                continue
            stored = graph.get_entity(entity_id)
            if stored is None:  # add_entity 报成功但取不到——按失败处理，不装作写入了
                stats["failed"] += 1
                continue
            existing_patterns.setdefault(scope, set()).add(normalized)
            stats["entities"].append(stored)
            written += 1
            stats["schemas"] = written

    stats["candidates"] = sum(len(rows) for rows in buckets.values())
    logger.info(
        "睡眠归纳完成: 候选 %s / 簇 %s / 新 schema %s（上限 %s，顺延 %s，"
        "去重跳过 %s，失败 %s）",
        stats["candidates"], stats["clusters"], stats["schemas"],
        stats["max_schemas"], stats["deferred"], stats["dedup_skipped"],
        stats["failed"],
    )
    return stats


def buildSyncLlmFn(client: Any) -> Optional[Callable[[str], str]]:
    """把异步 LLM 客户端桥接成睡眠线程可用的同步 ``llm_fn(prompt) -> str``。

    睡眠整理跑在空闲监控线程（无事件循环），客户端 ``generate`` 是协程——
    经 ``run_async_safely``（mem_core 的唯一桥）换新 loop 执行。客户端缺席
    或无 generate 返回 None（调用方跳过归纳，如实降级）。
    """
    if client is None or not hasattr(client, "generate"):
        return None

    def _sync(prompt: str) -> str:
        from neurova.mem_core import run_async_safely

        return run_async_safely(client.generate(prompt))

    return _sync


def _makeSchemaEntity(entity_id, parsed, cluster, scope):
    """构造 schema 实体（证据回指 + 作用域 + 归纳元信息）。"""
    from neurova.cognitive_layers.memory_layer.dependency_graph import EntityNode

    agent_id, neuser_id, user_id = scope
    return EntityNode(
        id=entity_id,
        name=parsed["name"],
        entity_type=SCHEMA_ENTITY_TYPE,
        metadata={
            "pattern": parsed["pattern"],
            "evidence": [str(row.get("id") or "") for row in cluster],
            "scope": [agent_id, neuser_id, user_id],
            "induced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "sleep_induction",
            "cluster_size": len(cluster),
        },
    )
