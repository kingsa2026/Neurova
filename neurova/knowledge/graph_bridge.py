"""
知识条目 → 图谱自动抽取（批次 3 / RAG 演进 B2；Issue #72 收口落点）

抽取有**两个落点**，缺一不可：

1. **底座事实层（权威、被读的那张图）**：LLM 抽出的关系经唯一写咽喉
   `admit()` 落成 `record_kind='triple'` 的治理事实，实体类型落成 `is_a` 三元组。
   时效读面与多跳走查读的正是这张图；只写 JSON 属性图就等于"抽取产物永远
   进不了被检索的图"（审计 §5.3 / B-09）。
2. **JSON 属性图（派生投影、给可视化）**：`KnowledgeGraphManager` 的节点/边，
   节点 id 回写 `KnowledgeItem.graph_node_ids`。它是投影不是权威——投影层不持写权，
   也不该被当作读面。

设计要点：
- llm_call(prompt) -> str 可注入（测试零网络/零 LLM）；None 表示未配置，跳过
- 类型合法集合来自 `ontology_terms`（工单 020 的注册表），越界一律落 custom；
  加一种类型是往表里登记一行，不改本文件（工单 018 收编）
- 节点复用走 006 的身份消解段：同一实体不因类型词不同就开两个节点
- 任何异常不向上传播（导入链路的钩子调用，失败不阻断导入）
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_PROMPT_TEMPLATE = """从下面的知识条目中抽取实体与关系，输出严格的 JSON（不要解释）：
{{"entities": [{{"label": "...", "type": "concept|entity|event|memory|skill|tool|person|location|time|custom"}}], "relations": [{{"source": "实体标签", "target": "实体标签", "type": "is_a|has_a|part_of|related_to|causes|similar_to|opposite_of|temporal|spatial|causal|depends_on|used_by|contains|custom"}}]}}
约束：type 必须从给定枚举中选；实体 2-6 个；关系基于实体标签。

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


def registeredRelationTypes(registry: Any) -> List[str]:
    return registeredTypes(registry, "relation")


def registeredNodeTypes(registry: Any) -> List[str]:
    return registeredTypes(registry, "concept")


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


def _domainOf(item: Dict[str, Any], repo: Any) -> str:
    """这条条目属于哪个 agent 域：条目自带 > 反查仓库 > default。

    抽取钩子拿到的条目 dict 里没有 agent_id（仓库按 agent 分组存放），
    但没有它就落不了权威。反查是确定性的，不是猜——`find_item` 是仓库既有能力。
    """
    declared = str(item.get("agent_id", "") or "").strip()
    if declared:
        return declared
    if repo is not None:
        try:
            found = repo.find_item(str(item.get("knowledge_id", "") or ""))
        except Exception as exc:  # noqa: BLE001 - 反查失败不阻断抽取
            logger.debug("graph_bridge: agent 域反查失败: %s", exc)
            found = None
        if found:
            return str(found[0] or "default")
    return "default"


def _statementOf(source: str, relation: str, target: str) -> str:
    """三元组的说法文本 = 它自己的 SPO。

    不能三条共用条目正文：内容身份（004 口径）会把它们折成同一行，第二条根本不存在。
    也不自造自然语言模板——抽取产物本来就只有 SPO 这个形状，如实写它。
    """
    return "%s %s %s" % (source, relation, target)


def _assertionFor(item: Dict[str, Any], statement: str) -> Dict[str, Any]:
    """抽取断言的来路：管线抽的，依据就是这条条目（`medium_ref` 指名条目 id）。"""
    kid = str(item.get("knowledge_id", "") or "")
    return {
        "actorType": "pipeline",
        "actorId": "graph_bridge",
        "mediumRef": "entry:%s" % kid,
        "statementText": statement,
    }


def admitExtractedFacts(
    data: Dict[str, Any],
    item: Dict[str, Any],
    factStore: Any,
    termRegistry: Any = None,
) -> List[str]:
    """把抽取出的实体类型与关系经**唯一咽喉**落成底座三元组，返回落定的 fact_id。

    这是 B-09 的根修点：抽取的产物必须与被读的图是同一张图。谓词直接用抽取出的
    关系类型（越界已落 `custom`），实体类型落成 `is_a` 三元组——主体因此有类型，
    本体校验（020）才有东西可判，否则那条硬拒判据永远是全集免检。

    逐条独立 admit：一条不合法（本体硬拒/缺断言）不该让整条条目的抽取全灭，
    但**失败必须留名**——吞掉就又是"看着成功、其实没写"。
    """
    from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate

    gate = productionAdmissionGate(factStore, toolVersion="graph-bridge")
    agentId = str(item.get("agent_id", "") or "default")
    def _admitOne(subjectLabel: str, predicateTermId: str, objectTerm: str) -> Optional[str]:
        statement = _statementOf(subjectLabel, predicateTermId, objectTerm)
        try:
            receipt = gate.admit(AdmissionRequest(
                agentId=agentId,
                subjectLabel=subjectLabel,
                predicateTermId=predicateTermId,
                objectTerm=objectTerm,
                content=statement,
                relationKind="entity",
                assertions=[_assertionFor(item, statement)],
                sourceTurnId="entry:%s" % str(item.get("knowledge_id", "") or ""),
                activityKind="extract",
                activityBasis="graph_bridge.extract_knowledge_to_graph（LLM 抽取落底座）",
            ))
        except Exception as exc:  # noqa: BLE001 - 逐条隔离，坏条目不留名就不算失败
            logger.warning("graph_bridge: 抽取事实入底座被拒（%s %s %s）: %s",
                           subjectLabel, predicateTermId, objectTerm, exc)
            return None
        return receipt.factId

    factIds: List[str] = []
    for ent in data.get("entities") or []:
        if not isinstance(ent, dict):
            continue
        label = str(ent.get("label", "")).strip()
        nodeType = str(ent.get("type", "")).strip()
        if not label or not nodeType:
            continue
        decided = _typeFromRegistry(termRegistry, nodeType)
        factId = _admitOne(label, "is_a", decided)
        if factId:
            factIds.append(factId)
            # 主类型列在主体建出来之后才挂得上（此前主体还不存在）；
            # 挂着它又是定义域校验唯一读处，所以顺序不能反。
            _assignSubjectType(termRegistry, label, decided, agentId)

    for rel in data.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        source = str(rel.get("source", "")).strip()
        target = str(rel.get("target", "")).strip()
        if not source or not target or source == target:
            continue
        relation = _typeFromRegistry(termRegistry, rel.get("type"))
        factId = _admitOne(source, relation, target)
        if factId:
            factIds.append(factId)
    return factIds


def _assignSubjectType(termRegistry: Any, label: str, decided: str, agentId: str) -> None:
    """把实体类型挂到主体的**主类型列**上。

    两处落点各司其职，都是既有机制、不是新造的：

    - **主类型列** `knowledge_subjects.type_term_id`：设计 §4.2 定的身份层主类型，
      也是定义域校验（`validation.subjectType`）唯一的读处。只写 `is_a` 不写它，
      定义域那条硬拒就永远无依据可判（审计 §3：87 个主体的这一列全 NULL）。
    - **`is_a` 三元组**：`assertedTypesOf` 合并口径里"主体是什么"的落点，使类型
      在事实层可见（图走查/血缘都读得到）。

    `custom` 是兜底标记不是一种类型（术语表里没有它），所以只落 `is_a`、不占主类型列。
    """
    if termRegistry is None or not decided or decided == "custom":
        return
    try:
        subjectKey = termRegistry._store.resolveSubjectKey(agentId, label)
        if subjectKey:
            termRegistry.assignSubjectType(subjectKey, decided)
        else:
            logger.warning("graph_bridge: 主体 %r 未落库，类型 %s 挂不上去", label, decided)
    except Exception as exc:  # noqa: BLE001 - 挂类型失败不该让抽取整条死掉
        logger.warning("graph_bridge: 主体 %r 挂类型 %s 失败: %s", label, decided, exc)


def _typeFromRegistry(termRegistry: Any, value: Any) -> str:
    """注册表里登记过才算一种类型；越界落 custom，不猜。

    单一口径：本函数同时供底座落库与 JSON 投影使用——两处各判一次类型，
    就会出现"图上标 custom、库里标别的"这种同一实体两套类型。
    """
    text = str(value or "").strip()
    allowed = _registeredTypeIds(termRegistry)
    return text if text in allowed else "custom"


def _registeredTypeIds(termRegistry: Any) -> set:
    """合法类型集合的唯一口径：注册表是权威，缺席时退回枚举读兼容层。

    注册表**不缺席**时不再并上枚举——那等于给同一件事留第二份定义（018 收编后
    枚举值本来就是表里的行，并上去只会让"新登记的类型"与"旧枚举值"共用一条判据）。
    退回枚举只发生在"这一轮拿不到注册表"时，含义是"新登记的类型这一轮认不出来"。
    """
    if termRegistry is not None:
        return (set(registeredTypes(termRegistry, "concept"))
                | set(registeredTypes(termRegistry, "relation")))
    from neurova.cognitive_layers.knowledge_graph.manager import NodeType, RelationType

    return ({t.value for t in NodeType if t.value != "custom"}
            | {t.value for t in RelationType if t.value != "custom"})


def extract_knowledge_to_graph(
    item: Dict[str, Any],
    repo: Any = None,
    llm_call: Optional[Callable[[str], str]] = None,
    graph_manager: Any = None,
    termRegistry: Any = None,
    factStore: Any = None,
    agentId: str = "",
) -> List[str]:
    """抽取一条知识条目的实体/关系：落底座三元组 + 投影 JSON 属性图，回写节点 id。

    Args:
        item: 知识条目 dict（含 knowledge_id/title/content）
        repo: KnowledgeRepository（回写 graph_node_ids；None 则跳过回写）
        llm_call: prompt -> 文本 的调用器；None/异常/畸形输出 → 跳过（返回 []）
        graph_manager: KnowledgeGraphManager；None 时用全局单例
        termRegistry: OntologyTermRegistry；None 时接生产底座的注册表
        factStore: KnowledgeFactStore；None 时用生产底座单例。**它是权威落点**，
            给了它抽取产物才进得了被检索的那张图
        agentId: 事实域。条目 dict 里没有这一栏（仓库按 agent 分组存放），
            缺省时经 `repo.find_item` 反查，再缺才落 default——不靠"猜不到的域不写"
            把权威落点静默跳过

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

    try:
        raw = llm_call(_PROMPT_TEMPLATE.format(title=title, content=content[:4000]))
        data = _parse_llm_json(raw)
    except Exception as exc:  # noqa: BLE001 - LLM 不可用不阻断调用方
        logger.warning("graph_bridge: LLM 抽取失败: %s", exc)
        return []
    if not data:
        logger.warning("graph_bridge: LLM 输出无法解析为 JSON，跳过")
        return []

    if graph_manager is None:
        from neurova.cognitive_layers.knowledge_graph.manager import (
            get_knowledge_graph_manager,
        )

        graph_manager = get_knowledge_graph_manager()

    # ── 落点一：底座事实层（被读的那张图）────────────────────────
    # 顺序刻意如此：抽出来的说法先入权威，JSON 属性图只是它的投影。
    # 反过来（先投影、再尽力入底座）会让"投影有、权威没有"成为常态，
    # 而那正是 B-09 的病态。
    authority = factStore
    if authority is None:
        from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store

        # 不 try：拿不到权威就不该假装抽成功。测试会话里这会被 storage_fence 当场
        # 拦下（正是"忘了注入隔离库"该有的响亮形态），生产里由调用点逐条隔离。
        authority = get_knowledge_fact_store()
    domain = agentId or _domainOf(item, repo)
    if termRegistry is None:
        # 类型判据的唯一权威是本体注册表。拿不到它就没有"这个类型合法吗"，
        # 落库那条路会退成整片 custom——退成默认值等于把判据换成猜测，所以这里
        # 顺手建一份（生产装配同款）；注册表本身不可用才是硬故障，如实上抛。
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        termRegistry = OntologyTermRegistry(authority)
    admitted = admitExtractedFacts(
        data, {**item, "agent_id": domain}, authority, termRegistry)

    from neurova.knowledge.identity.subject_resolver import SubjectResolver

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
        node_type = _typeFromRegistry(termRegistry, ent.get("type"))
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
        source_id = label_to_id.get(str(rel.get("source", "")).strip())
        target_id = label_to_id.get(str(rel.get("target", "")).strip())
        if not source_id or not target_id or source_id == target_id:
            continue
        relation = _typeFromRegistry(termRegistry, rel.get("type"))
        try:
            graph_manager.add_edge(
                source_id=source_id, target_id=target_id, relation_type=relation
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("graph_bridge: 建边失败 %s->%s: %s", source_id, target_id, exc)

    if admitted:
        logger.info("graph_bridge: 抽取入底座 %s 条三元组（条目 %s / 域 %s）",
                    len(admitted), str(item.get("knowledge_id", "")), domain)
    else:
        # 抽取出的关系一条都没进权威 = 这条条目在答题面上不存在。响亮报出，
        # 不静默返回一个"看着成功"的节点 id 列表。
        logger.warning("graph_bridge: 抽取未产生任何底座三元组（条目 %s / 域 %s）——"
                       "这批实体边只存在于 JSON 投影里，检索链读不到",
                       str(item.get("knowledge_id", "")), domain)

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
