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
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE

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
    """注册表缺席时，候选清单退回枚举读兼容层。

    它只兜底 prompt 候选文案，不是合法性判据——判据唯一在注册表（`_registeredTypeIds`）。
    """
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
                # 工单 001：抽取产物是模型输出，引用到的路径/版本号必须能在被抽取的
                # 条目原文里逐字找到。拒的是这条断言，不是整条条目的抽取——坏三元组
                # 入底座后会被当事实读，降权没有意义（底座没有"权重"）。
                evidenceText="%s\n%s" % (str(item.get("title", "") or ""),
                                         str(item.get("content", "") or "")),
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
        # 底座侧只收登记过的关系：`custom` 是兜底标记不是一种类型，拿它当谓词
        # 只会造出一批读不出来源的无义事实（实体类型那条 `is_a` 路由上面专管）。
        if relation == "custom":
            continue
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
        raw = llm_call(extractionPrompt(termRegistry, title=title, content=content))
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
        sourceLabel = str(rel.get("source", "")).strip()
        targetLabel = str(rel.get("target", "")).strip()
        source_id = label_to_id.get(sourceLabel)
        target_id = label_to_id.get(targetLabel)
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

def extractionPending(item: Dict[str, Any], store: Any, agentId: str) -> bool:
    """这条条目还欠一次抽取吗——判据问的是**权威**，不是投影。

    `/knowledge-graph/backfill` 此前按"`graph_node_ids` 为空"筛待办。但抽取收口
    **之前**抽过的条目两个字段都有值：旧实现只落 JSON 投影，也照样把节点 id 写回条目。
    于是最需要补抽的那批存量（投影有、权威无）恰好被待办判据全部跳过——端点报表写
     `entries=0`（"没有待补的"），实际是"待补的认不出来"（Issue #72 §5 登记的存量回填，
    它不是纯运维动作，上游有一处判据要先修）。

    判据落在权威：底座里这个域有指向本条目的抽取事实，才算抽过。投影是派生品，
    拿它当依据就是让派生品决定谁该被补——那正是两面分裂能活下来的原因。
    """
    return not _authorityFactsForEntry(store, agentId, str(item.get("knowledge_id", "") or ""))


def _authorityFactsForEntry(store: Any, agentId: str, knowledgeId: str) -> List[Any]:
    """本条条目在权威侧留下的抽取事实（按断言的 medium_ref 认，与协商口径同源）。

    条目 id 的落点有两处（`source_turn_id` 前缀与断言 `medium_ref`），两处任一命中都算：
    只认一处就会把另一条真实写入链的产物当成"没抽过"，补抽于是重复落一遍。
    """
    if not knowledgeId:
        return []
    wanted = {knowledgeId, "entry:%s" % knowledgeId, "legacy:%s" % knowledgeId}
    hits: List[Any] = []
    for fact in store.searchableFacts(agentId=agentId):
        if str(fact.get("source_turn_id") or "") in wanted:
            hits.append(fact)
            continue
        for assertion in store.assertions(fact["fact_id"]):
            if str(assertion.get("medium_ref") or "") in wanted:
                hits.append(fact)
                break
    return hits


# ── 投影一致性（Issue #72 未处置项：JSON 属性图是权威的派生投影）──────────
#
# 抽取那一刻两个落点同源，但权威侧此后还会变（存量补抽、冲突裁决取代、
# 推导结论落库、对账回放）。没有一条路径把投影拉回与权威一致，投影就成了
# 名下的第二份真相：可视化读它、检索读权威，两边各说各话且无人报出分叉。
# 下面三个函数把这件事收干净：分叉可读、可修、且只动本域。

def _relationTermIds(store: Any, termRegistry: Any) -> set:
    """谓词合法集：注册表是权威；注册表不可用时退回枚举读兼容层（与类型判据同口径）。"""
    if termRegistry is not None:
        return set(registeredRelationTypes(termRegistry))
    from neurova.cognitive_layers.knowledge_graph.manager import RelationType

    return {t.value for t in RelationType if t.value != "custom"}


def _authorityRelations(store: Any, agentId: str, termRegistry: Any) -> List[Dict[str, str]]:
    """权威侧的关系清单：底座三元组里"两端都有主体"的那些。

    `is_a` 不在此列：它是实体类型落到事实层的形状，投影里对应的是**节点类型**
    而不是一条边（两边都算就会把同一个类型事实算成一条多余/缺失的边）。
    客体不是主体的说法同样不算边（字面量客体，比如 `版本 = 2.0`）。
    """
    declared = _relationTermIds(store, termRegistry)
    declared.discard(IS_A_PREDICATE)

    byLabel = {s["canonical_label"] for s in store.listSubjects(agentId)}
    out: List[Dict[str, str]] = []
    for fact in store.searchableFacts(agentId=agentId):
        predicate = str(fact.get("predicate_term_id") or "")
        if predicate == IS_A_PREDICATE or predicate not in declared:
            continue
        source = str(fact.get("canonical_label") or "")
        target = str(fact.get("object_term") or "")
        if not source or target not in byLabel:
            continue
        out.append({"source": source, "relation": predicate, "target": target})
    return out


def _projectionRelations(graph: Any) -> List[Dict[str, str]]:
    """投影侧的关系清单（同一形状：两端都是节点，`is_a` 不在这）。"""
    labels = {n.node_id: n.label for n in graph._nodes.values()}
    out: List[Dict[str, str]] = []
    for edge in graph._edges.values():
        source = labels.get(edge.source_id)
        target = labels.get(edge.target_id)
        relation = edge.relationTypeValue
        if not source or not target or relation == IS_A_PREDICATE:
            continue
        out.append({"source": source, "relation": relation, "target": target})
    return out


def projectionDrift(agentId: str, graph: Any, store: Any,
                    termRegistry: Any = None) -> Dict[str, Any]:
    """权威与投影的关系差集：缺的（权威有投影无）与孤儿（投影有权威无）。

    只报不计分、不自动修：分叉是**运维读数**，修由 `rebuildProjectionFromAuthority`
    显式做——顺手修掉就等于把报出与处置混成一件事，读的人再也看不到曾经分叉过。
    """
    authority = _authorityRelations(store, agentId, termRegistry)
    projection = _projectionRelations(graph)

    def _key(rel: Dict[str, str]) -> str:
        return "\x1f".join((rel["source"], rel["relation"], rel["target"]))

    held = {_key(r) for r in projection}
    known = {_key(r) for r in authority}
    return {
        "agent_id": agentId,
        "authority_relations": len(authority),
        "projection_relations": len(projection),
        "missing_relations": [r for r in authority if _key(r) not in held],
        "orphan_relations": [r for r in projection if _key(r) not in known],
    }


def rebuildProjectionFromAuthority(agentId: str, graph: Any, store: Any,
                                   termRegistry: Any = None) -> Dict[str, Any]:
    """按权威重建本域的投影：节点取自主体（类型取自主类型列），边取自三元组。

    重建是**幂等**的：先摘掉本域旧的边与孤立节点，再按权威铺一遍，跑几次结论一样。
    节点身份仍由消解段定（006 口径），不按 label 精确匹配——否则同一实体换个
    类型词就开两个节点，图越写越碎；也因此"本域旧节点"只能按参与本域关系的标签认。
    """
    from neurova.cognitive_layers.knowledge_graph.manager import NodeType as _NodeType
    from neurova.knowledge.identity.subject_resolver import SubjectResolver

    authority = _authorityRelations(store, agentId, termRegistry)
    wanted = {r["source"] for r in authority} | {r["target"] for r in authority}

    labels = {n.node_id: n.label for n in graph._nodes.values()}
    for edge_id, edge in list(graph._edges.items()):
        if labels.get(edge.source_id) in wanted or labels.get(edge.target_id) in wanted:
            graph.delete_edge(edge_id)
    for node in list(graph._nodes.values()):
        if node.label in wanted and not graph.get_neighbors(node.node_id):
            graph.delete_node(node.node_id)

    types = {s["canonical_label"]: (s.get("type_term_id") or _NodeType.CONCEPT.value)
             for s in store.listSubjects(agentId)}
    resolver = SubjectResolver()
    nodeIds: Dict[str, str] = {}
    for label in sorted(wanted):
        nodeType = types.get(label) or _NodeType.CONCEPT.value
        if nodeType == "custom":
            nodeType = _NodeType.CONCEPT.value
        existing = _resolveNodeId(graph, label, resolver)
        if existing is not None:
            nodeIds[label] = existing
            continue
        nodeIds[label] = graph.add_node(label=label, node_type=nodeType).node_id

    edges = 0
    for rel in authority:
        sourceId = nodeIds.get(rel["source"])
        targetId = nodeIds.get(rel["target"])
        if not sourceId or not targetId or sourceId == targetId:
            continue
        if graph.add_edge(source_id=sourceId, target_id=targetId,
                          relation_type=rel["relation"]) is not None:
            edges += 1
    return {"agent_id": agentId, "nodes": len(nodeIds), "edges": edges,
            "drift": projectionDrift(agentId, graph, store, termRegistry)}
