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

#: core schema 实体类型（T3 跨域碰撞归纳产物）
CORE_SCHEMA_ENTITY_TYPE = "core_schema"

#: 行为相似阈值（DCPM θ_beh=0.72）：行为描述嵌入余弦须超过
BEHAVIOR_COSINE_THRESHOLD = 0.72

#: 语义遥远阈值（DCPM θ_sem=0.40 的本仓标定值）：证据话题嵌入余弦须低于
#: （行为像、话题远）。0.65 经真嵌入（bge-small-zh-v1.5，512 维）实测标定：
#: 无关话题句对 ≈0.52，同话题句对 ≈0.84+——0.40 在该嵌入空间会把所有对
#: 都判成"话题不远"而恒空扫。
SEMANTIC_COSINE_THRESHOLD = 0.65

#: core 节点 evidence 并集上限（有界内嵌）
CORE_EVIDENCE_CAP = 50

#: T3 core 归纳提示词（成员规律 → 更高层通用模式）
CORE_INDUCTION_PROMPT = (
    "以下是几个不同生活域里的行为规律，它们在行为上同构（话题不同）。请归纳一个"
    "更高层的通用模式，输出严格 JSON（不要多余文字）：\n"
    '{"name": "<4-12 字的通用模式名>", "pattern": "<一句话通用规律>"}\n'
    "成员规律：\n"
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_TRUTHY = ("1", "true", "on", "yes")


def sleepInductionEnabled() -> bool:
    """门控读取（调用时解析，测试/运维可实时翻转）。"""
    import os

    return str(os.environ.get(INDUCTION_ENV, "")).strip().lower() in _TRUTHY


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


def clusterRecords(rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """贪心语义聚类：与簇代表余弦达阈值即入簇，否则自立新簇。"""
    clusters: List[List[Dict[str, Any]]] = []
    for row in rows:
        embedding = list(row.get("embedding") or [])
        best: Optional[List[Dict[str, Any]]] = None
        best_sim = 0.0
        for cluster in clusters:
            rep = list(cluster[0].get("embedding") or [])
            sim = _safeCosine(embedding, rep)
            if sim is None or sim < INDUCTION_COSINE_THRESHOLD:
                continue
            if sim > best_sim:
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


# ──────────────────────────────────────────────────────────────
# T3 跨域碰撞 sweeper——行为/语义双空间判据 → core schema 归纳
# ──────────────────────────────────────────────────────────────


def _norm(vec: Any) -> float:
    return float(sum(float(x) * float(x) for x in vec)) ** 0.5 if vec else 0.0


def _safeCosine(left: Any, right: Any) -> Optional[float]:
    """零向量安全余弦：任一侧零范数返回 None（不可判，不硬凑 0）。"""
    if not left or not right:
        return None
    na, nb = _norm(left), _norm(right)
    if na <= 0.0 or nb <= 0.0:
        return None
    try:
        return float(cosineSimilarity(list(left), list(right)))
    except Exception:  # noqa: BLE001 - 单对相似度失败按不可判处理
        return None


def _schemaEntitiesByScope(graph: Any) -> Dict[Optional[Tuple[str, str, str]], List[Any]]:
    """schema 节点按作用域分桶（无 scope 元数据的归 None 桶，不参与跨域扫描）。"""
    by_scope: Dict[Optional[Tuple[str, str, str]], List[Any]] = defaultdict(list)
    for entity in graph.entities.values():
        if getattr(entity, "entity_type", "") != SCHEMA_ENTITY_TYPE:
            continue
        scope = (getattr(entity, "metadata", None) or {}).get("scope")
        if isinstance(scope, (list, tuple)) and len(scope) == 3:
            by_scope[tuple(str(s) for s in scope)].append(entity)
    return by_scope


def _evidenceCentroid(manager: Any, evidence_ids: List[str]) -> Optional[List[float]]:
    """证据事实嵌入的质心（系统面逐条取；取不到的跳过；全缺返回 None）。"""
    if manager is None:
        return None
    centroid: Optional[List[float]] = None
    count = 0
    for eid in evidence_ids:
        try:
            row = manager.get_memory(str(eid), agent_wide=True)
        except Exception:  # noqa: BLE001 - 单条证据缺失不阻断
            row = None
        if not isinstance(row, dict):
            continue
        embedding = row.get("embedding") or []
        if not embedding:
            continue
        if centroid is None:
            centroid = [0.0] * len(embedding)
        if len(embedding) != len(centroid):
            continue  # 维度不齐的证据不进质心（换过嵌入引擎的旧向量）
        for i, x in enumerate(embedding):
            centroid[i] += float(x)
        count += 1
    if centroid is None or count == 0:
        return None
    return [x / count for x in centroid]


def _unionFind(pairs: List[Tuple[str, str]]) -> Dict[str, List[str]]:
    """经典并查集：把碰撞对聚成连通簇（DCPM Phase 3b 同构）。"""
    parent: Dict[str, str] = {}

    def _find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[rb] = ra
    clusters: Dict[str, List[str]] = defaultdict(list)
    for node in list(parent):
        clusters[_find(node)].append(node)
    return clusters


def _coreInductionPrompt(members: List[Any]) -> str:
    listing = "\n".join(
        f"- {getattr(m, 'name', '')}: {str((getattr(m, 'metadata', None) or {}).get('pattern') or '')}"
        for m in members
    )
    return CORE_INDUCTION_PROMPT + listing


def _hierarchicalType():
    """HIERARCHICAL 依赖类型（局部导入防环）。"""
    from neurova.cognitive_layers.memory_layer.dependency_graph import DependencyType

    return DependencyType.HIERARCHICAL


def runCrossDomainSweep(
    manager: Any,
    graph: Any = None,
    *,
    embed_fn: Optional[Callable[[str], List[float]]] = None,
    llm_fn: Optional[Callable[[str], str]] = None,
    behavior_threshold: float = BEHAVIOR_COSINE_THRESHOLD,
    semantic_threshold: float = SEMANTIC_COSINE_THRESHOLD,
    max_cores: int = INDUCTION_MAX_SCHEMAS_PER_CYCLE,
) -> Dict[str, Any]:
    """跨域碰撞扫描：行为像（cos>θ_beh）且话题远（cos<θ_sem）的 schema 对
    经 union-find 聚簇后，每簇一次 LLM 归纳出 core schema 节点。

    - 只在**同作用域**内扫（跨作用域永不碰撞——隔离纪律）；
    - 两个空间都高的是平凡冗余对，过滤掉（DCPM 同款）；
    - 行为嵌入 = schema pattern 的嵌入（T2 归纳提示词本就要求"行为规律"，
      它就是行为描述，不再多花一次 LLM）；话题嵌入 = 证据事实嵌入的质心；
    - fail-soft：LLM/图写失败只计数跳过，绝不抛出阻断睡眠链。
    """
    stats: Dict[str, Any] = {
        "enabled": sleepInductionEnabled(),
        "schemas_scanned": 0,
        "collisions": 0,
        "core_schemas": 0,
        "failed": 0,
        "max_cores": int(max_cores),
        "entities": [],
    }
    if not stats["enabled"] or graph is None or not callable(embed_fn):
        return stats

    by_scope = _schemaEntitiesByScope(graph)
    stats["schemas_scanned"] = sum(len(v) for v in by_scope.values())

    # 行为嵌入（每 schema 一次）
    behavior_emb: Dict[str, List[float]] = {}
    for scope, entities in by_scope.items():
        for entity in entities:
            pattern = str((getattr(entity, "metadata", None) or {}).get("pattern") or "")
            try:
                behavior_emb[entity.id] = list(embed_fn(pattern) or [])
            except Exception:  # noqa: BLE001 - 单点嵌入失败按零向量（不可判）处理
                behavior_emb[entity.id] = []

    collisions: List[Tuple[str, str]] = []
    for scope, entities in by_scope.items():
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                a, b = entities[i], entities[j]
                beh = _safeCosine(behavior_emb.get(a.id), behavior_emb.get(b.id))
                if beh is None or beh <= behavior_threshold:
                    continue  # 行为不像（或不可判）→ 不碰
                ca = _evidenceCentroid(manager, (a.metadata or {}).get("evidence") or [])
                cb = _evidenceCentroid(manager, (b.metadata or {}).get("evidence") or [])
                sem = _safeCosine(ca, cb)
                if sem is None or sem >= semantic_threshold:
                    continue  # 话题不远（或质心不可得）→ 不碰（含平凡冗余对）
                collisions.append((a.id, b.id))
    stats["collisions"] = len(collisions)
    if not collisions:
        return stats

    clusters = _unionFind(collisions)
    written = 0
    from neurova.cognitive_layers.memory_layer.dependency_graph import (
        DependencyEdge,
        EntityNode,
    )

    for _, member_ids in sorted(clusters.items()):
        if written >= max_cores:
            break
        members = [graph.get_entity(mid) for mid in member_ids]
        members = [m for m in members if m is not None]
        if len(members) < 2:
            continue
        parsed = None
        if llm_fn is not None:
            try:
                parsed = _parseSchemaResponse(llm_fn(_coreInductionPrompt(members)))
            except Exception as e:  # noqa: BLE001 - 单次归纳失败不阻断
                logger.warning("跨域归纳：core LLM 调用失败（跳过该簇）: %s", e)
        if parsed is None:
            stats["failed"] += 1
            continue
        scope = tuple(str(s) for s in (members[0].metadata or {}).get("scope") or [])
        evidence: List[str] = []
        for m in members:
            for eid in (m.metadata or {}).get("evidence") or []:
                eid = str(eid)
                if eid and eid not in evidence:
                    evidence.append(eid)
        core_id = (
            f"{CORE_SCHEMA_ENTITY_TYPE}:{scope[0] if scope else 'default'}:"
            f"{uuid.uuid4().hex[:12]}"
        )
        if not graph.add_entity(EntityNode(
            id=core_id,
            name=parsed["name"],
            entity_type=CORE_SCHEMA_ENTITY_TYPE,
            metadata={
                "pattern": parsed["pattern"],
                "evidence": evidence[:CORE_EVIDENCE_CAP],
                "member_schemas": [m.id for m in members],
                "scope": list(scope) if scope else [],
                "induced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "sleep_induction_cross_sweep",
            },
        )):
            stats["failed"] += 1
            continue
        core = graph.get_entity(core_id)
        if core is None:  # add_entity 报成功但取不到——按失败处理，不装作写入了
            stats["failed"] += 1
            continue
        for m in members:
            graph.add_dependency(DependencyEdge(
                id=f"edge:{uuid.uuid4().hex[:12]}",
                source_id=core.id,
                target_id=m.id,
                dep_type=_hierarchicalType(),
                metadata={"source": "sleep_induction_cross_sweep"},
            ))
        stats["entities"].append(core)
        written += 1
        stats["core_schemas"] = written

    logger.info(
        "跨域碰撞扫描完成: schema %s / 碰撞对 %s / 新 core %s（失败 %s）",
        stats["schemas_scanned"], stats["collisions"], stats["core_schemas"],
        stats["failed"],
    )
    return stats


def _managerEmbedFn(manager: Any) -> Optional[Callable[[str], List[float]]]:
    """从 MemoryManager 取行嵌入入口包装成 embed_fn（缺席返回 None）。"""
    fn = getattr(manager, "_embeddingForNewRow", None)
    if not callable(fn):
        return None

    def _embed(text: str) -> List[float]:
        vec = fn(str(text))
        return list(vec) if isinstance(vec, (list, tuple)) else []

    return _embed


def runInductionPhase(
    manager: Any,
    llm_fn: Optional[Callable[[str], str]],
    graph: Any = None,
    *,
    embed_fn: Optional[Callable[[str], List[float]]] = None,
) -> Dict[str, Any]:
    """T2+T3 的一次性入口（两条触发点共用）：先归纳 schema，再跨域扫碰撞。

    embed_fn 缺省从 manager 的行嵌入入口解析（真嵌入；解析不到则 T3
    如实跳过——不硬凑相似度）。
    """
    if graph is None:
        graph = get_dependency_graph_safe()
    induction = runSleepInduction(manager, llm_fn, graph=graph)
    if embed_fn is None:
        embed_fn = _managerEmbedFn(manager)
    sweep = runCrossDomainSweep(manager, graph=graph, embed_fn=embed_fn, llm_fn=llm_fn)
    return {"induction": induction, "sweep": sweep}
