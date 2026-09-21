"""知识条目 → 图谱节点自动抽取（批次 3 / RAG 演进 B2）

打通 KnowledgeRepository → KnowledgeGraphManager 的写入链路：
LLM 从条目标题+正文抽取实体与关系，建立图谱节点/边，
并把节点 id 回写 KnowledgeItem.graph_node_ids。

同时把同一批实体与关系**经咽喉投进事实底座**（`knowledge_facts`）。这一步是 Issue #73
的根因位：此前抽取只落 JSON 属性图，而答题读的是底座事实表 ⇒ 抽出来的东西永远进不了
被读的那张图，priority 26/27 两条检索分支每轮恒定返回 0（审计 2026-09-21 §5.2 / B-09）。

设计要点：
- llm_call(prompt) -> str 可注入（测试零网络/零 LLM）；None 表示未配置，跳过
- 类型合法集合来自 `ontology_terms`（工单 020 的注册表），越界一律落 custom；
  加一种类型是往表里登记一行，不改本文件（工单 018 收编）
- **候选类型清单也从注册表取**：prompt 里那份枚举此前是硬编字符串，新登记的术语
  对抽取不可见（B-10）
- 实体类型同时落成 `is_a` 三元组并把 `type_term_id` 挂到主体上——本体人口的两半
- 节点复用走 006 的身份消解段：同一实体不因类型词不同就开两个节点
- 任何异常不向上传播（导入链路的钩子调用，失败不阻断导入）；但底座写入失败按
  ERROR 级点名原因暴露，不做静默降级
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_PROMPT_TEMPLATE = """从下面的知识条目中抽取实体与关系，输出严格的 JSON（不要解释）：
{{"entities": [{{"label": "...", "type": "{nodeTypes}"}}], "relations": [{{"source": "实体标签", "target": "实体标签", "type": "{relationTypes}"}}]}}
约束：type 必须从给定候选里选；实体 2-6 个；关系基于实体标签。

标题：{title}
正文：{content}"""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def _parse_llm_json(text: str) -> Optional[Dict[str, Any]]:
    """解析 LLM 输出中的 JSON 对象（容忍 markdown 代码围栏）。"""
    if not text:
        return None
    match = _FENCE_RE.search(text)
    raw = match.group(1) if match else text
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except Exception:  # noqa: BLE001 - LLM 输出不可信
        return None
    return data if isinstance(data, dict) else None


def registeredTypes(registry: Any, kind: str) -> List[str]:
    """注册表里某一类（concept/relation）的合法术语 id。"""
    return [str(t.get("term_id", "")) for t in (registry.terms(kind) if registry else [])]


def _readCompatCandidates(kind: str) -> List[str]:
    """注册表缺席时，候选与合法集都退回枚举读兼容层（与 `_allowedTypes` 同一份来源）。"""
    from neurova.cognitive_layers.knowledge_graph.manager import NodeType, RelationType

    enum = NodeType if kind == "concept" else RelationType
    return [t.value for t in enum if t.value != "custom"]


def extractionPrompt(registry: Any, *, title: str, content: str) -> str:
    """抽取提示词：候选类型清单取自注册表，不再硬编。

    硬编的清单与注册表是两份类型事实源，新登记的术语抽不出来——"加类型不改 .py"
    于是只在校验侧成立。注册表不可用时退回枚举读兼容层的那批值，只影响 prompt 文案：
    合法性判定照样以注册表为准，越界一律落 `custom`。
    """
    nodeTypes = registeredNodeTypes(registry) if registry is not None else []
    relationTypes = registeredRelationTypes(registry) if registry is not None else []
    return _PROMPT_TEMPLATE.format(
        title=title, content=content[:4000],
        nodeTypes="|".join(nodeTypes) or "|".join(_readCompatCandidates("concept")),
        relationTypes="|".join(relationTypes) or "|".join(_readCompatCandidates("relation")),
    )


def registeredRelationTypes(registry: Any) -> List[str]:
    return registeredTypes(registry, "relation")


def registeredNodeTypes(registry: Any) -> List[str]:
    return registeredTypes(registry, "concept")


def _productionRegistry() -> Any:
    """生产底座的注册表；拿不到返回 None（由各消费点按自己的降级口径处理）。"""
    from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    try:
        return OntologyTermRegistry(get_knowledge_fact_store())
    except Exception as exc:  # noqa: BLE001 - 底座不可用不是抽取失败的理由
        logger.warning("graph_bridge: 本体注册表不可用（%s），本轮按无注册表处理", exc)
        return None


def _allowedTypes(termRegistry: Any, kind: str, legacyEnum: Any) -> set:
    """合法类型集合：注册表优先，拿不到时退回枚举读兼容层。

    这里是导入链路上的尽力而为钩子（异常不外抛、失败不阻断导入），所以底座不可用时
    必须还有一条能走的路，而不是让整个抽取静默死掉。退回枚举只意味着"新登记的类型
    这一轮认不出来"，落 custom 仍是有据可依的保守侧。
    """
    registry = termRegistry if termRegistry is not None else _productionRegistry()
    if registry is not None:
        return set(registeredTypes(registry, kind))
    logger.warning("graph_bridge: 本体注册表不可用，%s 合法集退回枚举读兼容层", kind)
    return {t.value for t in legacyEnum if t.value != "custom"}


def _resolveNodeId(graph: Any, label: str, resolver: Any) -> Optional[str]:
    """节点身份只由消解段决定。

    旧口径按 `(label, type)` 精确匹配，等于把类型当身份的一部分：同一个"青海湖"
    被叫成 concept 又被叫成 location 就开两个节点，图越写越碎。
    """
    try:
        candidates = [
            {"subject_key": node.node_id, "canonical_label": node.label,
             "aliases": list(node.aliases or [])}
            for node in graph.search_nodes(label, limit=50)
        ]
    except Exception:  # noqa: BLE001 - 图谱读面异常不当成身份判定
        return None
    if not candidates:
        return None
    resolution = resolver.resolve(label, candidates)
    if resolution.createdNew:
        if resolution.needsHumanReview and resolution.nearest:
            logger.info("graph_bridge: %r 与 %s 相似 %.2f，置信不足，另开节点待人工并",
                        label, resolution.nearest[0], resolution.nearest[1])
        return None
    return resolution.subjectKey


class _ExtractionSink:
    """抽取产物的底座落点：实体 → `is_a` 三元组 + 主体类型；关系 → 三元组。

    存在的理由（Issue #73）：抽取的产物此前只落 JSON 属性图，而答题读底座事实表，
    于是"抽出来的东西永远不被用"。这里让它经**唯一咽喉**进底座——不直插 SQL，
    否则就是 B03/G12 的那批孤儿子换个入口复活。

    单独抽出来是因为它要能离线构造（`factStore=None` = 这一环不接），
    且失败方向必须是**响亮**的：底座写不进去时点名事实与原因，不做静默降级。
    """

    def __init__(self, store: Any, agentId: str, *, registry: Any = None,
                 sourceId: str = "", title: str = "") -> None:
        self._store = store
        self._agentId = agentId
        self._registry = registry
        self._sourceId = sourceId
        self._title = title
        self._gateInstance: Any = None

    def _gate(self):
        """一条条目的全部实体/关系共用一个咽喉实例：造门是重活（登记种子规则 + 消解器），
        每条抽取都重造一次就是纯浪费。"""
        if self._gateInstance is None:
            from neurova.knowledge.foundation.admission import productionAdmissionGate

            self._gateInstance = productionAdmissionGate(self._store, toolVersion="graph-bridge")
        return self._gateInstance

    def _admit(self, subjectLabel: str, predicate: str, objectTerm: str, statement: str) -> None:
        from neurova.knowledge.foundation.admission import AdmissionRequest

        self._gate().admit(AdmissionRequest(
            agentId=self._agentId, subjectLabel=subjectLabel,
            predicateTermId=predicate, objectTerm=objectTerm, content=statement,
            activityKind="extract",
            activityBasis="graph_bridge.extract_knowledge_to_graph（条目抽取）",
            assertions=[{"actorType": "pipeline", "actorId": "graph_bridge",
                         "mediumRef": self._sourceId or "entry:%s" % self._title,
                         "statementText": statement}],
        ))

    def recordEntity(self, label: str, typeTermId: str) -> None:
        """实体类型落两处：`is_a` 三元组（可被多跳与推理读）与主体的 `type_term_id` 列。

        两处都要有：`assertedTypesOf` 读断言集判不相交，`subjectType` 读那一列判定义域。
        只写一处，本体硬拒就有一半判据恒免检（Issue #73 的 87 主体全 NULL）。
        """
        self._admit(label, "is_a", typeTermId, "%s is_a %s" % (label, typeTermId))
        if self._registry is None:
            return
        key = self._store.resolveSubjectKey(self._agentId, label)
        if key:
            self._registry.assignSubjectType(key, typeTermId)

    def recordRelation(self, sourceLabel: str, predicate: str, targetLabel: str) -> None:
        self._admit(sourceLabel, predicate, targetLabel,
                    "%s %s %s" % (sourceLabel, predicate, targetLabel))


def _sinkFor(factStore: Any, agentId: str, item: Dict[str, Any],
             registry: Any = None) -> Optional["_ExtractionSink"]:
    """底座落点：显式传入的 store 优先，否则按生产底座取；取不到就如实报出没落。

    不静默成功：底座缺席时抽取照旧写 JSON 图（那条路还在），但读数上必须看得见
    "这批抽取没有进事实底座"，否则用户以为图谱进检索了。
    """
    store = factStore
    if store is None:
        try:
            from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store

            store = get_knowledge_fact_store()
        except Exception as exc:  # noqa: BLE001 - 底座不可用不阻断导入
            logger.error("graph_bridge: 事实底座不可用（%s），本轮抽取不落底座——"
                         "priority 26/27 两条读面读不到它们", exc)
            return None
    return _ExtractionSink(store, agentId or "default", registry=registry,
                           sourceId=str(item.get("knowledge_id", "") or ""),
                           title=str(item.get("title", "") or ""))


def extract_knowledge_to_graph(
    item: Dict[str, Any],
    repo: Any = None,
    llm_call: Optional[Callable[[str], str]] = None,
    graph_manager: Any = None,
    termRegistry: Any = None,
    factStore: Any = None,
    agentId: str = "",
) -> List[str]:
    """抽取一条知识条目的实体/关系写入图谱与事实底座，返回回写后的 graph_node_ids。

    Args:
        item: 知识条目 dict（含 knowledge_id/title/content）
        repo: KnowledgeRepository（回写 graph_node_ids；None 则跳过回写）
        llm_call: prompt -> 文本 的调用器；None/异常/畸形输出 → 跳过（返回 []）
        graph_manager: KnowledgeGraphManager；None 时用全局单例
        termRegistry: OntologyTermRegistry；None 时接生产底座的注册表
        factStore: 事实底座；None 时按生产底座取（Issue #73：抽出的三元组要进被读的那张图）
        agentId: 事实归属的 agent 域；空串落 `default`

    Returns:
        条目关联的图谱节点 id 列表（失败为 []）
    """
    if llm_call is None:
        logger.info("graph_bridge: 未配置 LLM 调用器，跳过图谱抽取")
        return []

    title = str(item.get("title", ""))
    content = str(item.get("content", ""))
    if not (title or content):
        return []

    if termRegistry is None:
        termRegistry = _productionRegistry()

    try:
        raw = llm_call(extractionPrompt(termRegistry, title=title, content=content))
        data = _parse_llm_json(raw)
    except Exception as exc:  # noqa: BLE001 - LLM 不可用不阻断调用方
        logger.warning("graph_bridge: LLM 抽取失败: %s", exc)
        return []
    if not data:
        logger.warning("graph_bridge: LLM 输出无法解析为 JSON，跳过")
        return []

    sink = _sinkFor(factStore, agentId, item, termRegistry)

    if graph_manager is None:
        from neurova.cognitive_layers.knowledge_graph.manager import (
            get_knowledge_graph_manager,
        )

        graph_manager = get_knowledge_graph_manager()

    from neurova.cognitive_layers.knowledge_graph.manager import NodeType, RelationType
    from neurova.knowledge.identity.subject_resolver import SubjectResolver

    allowedNodeTypes = _allowedTypes(termRegistry, "concept", NodeType)
    allowedRelationTypes = _allowedTypes(termRegistry, "relation", RelationType)

    def _typeFromRegistry(value, allowed: set, default):
        """注册表里登记过才算一种类型；越界落 custom，不猜。"""
        text = str(value or "").strip()
        return text if text in allowed else default

    def _recordEntity(label: str, nodeType: str) -> None:
        if sink is None or nodeType == NodeType.CUSTOM.value:
            return
        sink.recordEntity(label, nodeType)

    resolver = SubjectResolver()

    # 建实体节点（身份由 006 消解段判，类型只是节点的属性）
    node_ids: List[str] = []
    label_to_id: Dict[str, str] = {}
    for ent in data.get("entities") or []:
        if not isinstance(ent, dict):
            continue
        label = str(ent.get("label", "")).strip()
        if not label:
            continue
        node_type = _typeFromRegistry(ent.get("type"), allowedNodeTypes, NodeType.CUSTOM.value)
        _recordEntity(label, node_type)
        existingId = _resolveNodeId(graph_manager, label, resolver)
        if existingId is not None:
            node_ids.append(existingId)
            label_to_id.setdefault(label, existingId)
            continue
        try:
            node = graph_manager.add_node(
                label=label,
                node_type=node_type,
                properties={"description": content[:200], "source_knowledge_id": str(item.get("knowledge_id", ""))},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("graph_bridge: 建节点失败 %s: %s", label, exc)
            continue
        node_ids.append(node.node_id)
        label_to_id[label] = node.node_id

    # 建关系边
    for rel in data.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        sourceLabel = str(rel.get("source", "")).strip()
        targetLabel = str(rel.get("target", "")).strip()
        source_id = label_to_id.get(sourceLabel)
        target_id = label_to_id.get(targetLabel)
        if not source_id or not target_id or source_id == target_id:
            continue
        relation = _typeFromRegistry(rel.get("type"), allowedRelationTypes,
                                     RelationType.CUSTOM.value)
        # 底座侧只收登记过的关系：`custom` 是兜底标记不是一种类型，拿它当谓词
        # 只会造出一批读不出来源的无义事实（`is_a` 那条路另有 recordEntity 专管）。
        if sink is not None and relation != RelationType.CUSTOM.value:
            try:
                sink.recordRelation(sourceLabel, relation, targetLabel)
            except ValueError as exc:
                logger.error("graph_bridge: 关系 %s %s %s 被本体拒绝（%s），未进事实底座",
                             sourceLabel, relation, targetLabel, exc)
        try:
            graph_manager.add_edge(
                source_id=source_id, target_id=target_id, relation_type=relation
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("graph_bridge: 建边失败 %s->%s: %s", source_id, target_id, exc)

    # 回写条目（经 find_item 跨组定位，不依赖 item dict 携带 agent_id）
    if node_ids and repo is not None:
        try:
            found = repo.find_item(str(item.get("knowledge_id", "")))
            if found is not None:
                agent_id, _current = found
                repo.update_knowledge(
                    agent_id,
                    str(item.get("knowledge_id", "")),
                    {"graph_node_ids": node_ids},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("graph_bridge: graph_node_ids 回写失败: %s", exc)

    return node_ids
