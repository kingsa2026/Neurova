# -*- coding: utf-8 -*-
"""CQ 追溯矩阵的名册与探针（撤前端静态表，照 default-off 读数面先例）。

- 元数据（cqId/question/actor/priority/query/testId）照抄唯一事实源
  docs/specs/2026-11-05-ontology-cq.md 的追溯矩阵；对拍判据
  tests/unit/knowledge/ontology/test_cqMatrixReadout.py::test_registryMetadataMatchesSpecDocRowByRow
  钉"第二份抄本不许漂移"。query 列允许保留显示注解（比票面多的工程提示），
  testId 逐字（含 ::类名段）。
- status **不抄文档票面**：specs 的 status 列是计划态（人管），这里的 status 由
  探针查产品面符号给现值——端点处理函数、引擎方法、REST 参数签名是否在当前
  进程真实存在。接线/退役自动翻转，不靠人改表；CQ-10 是活证：asOf/knownAt
  接进 accessQuery 的 REST 签名那天，现值自动转 implemented。
- 探针全部惰性 import（不建对 api.endpoints 的模块级装配边）；探针异常不吞、
  不静默翻态——读数面让它原样抛，端点以显式失败呈现。

status 三态与 specs 票面闭集一致：探针判据全中 = implemented；全不中 = planned；
部分中 = partial（多符号合取的行才可能出现）。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Callable, Dict, List


# ---------------------------------------------------------------------------
# 探针（每条 CQ 一个；返回现值字符串，异常往外抛）
# ---------------------------------------------------------------------------

def _probeConditionClassDerivation() -> str:
    """CQ-01：条件类推导实例（HighRiskOrder 等）的产品面。"""
    from neurova.knowledge import derivation_citation

    probes = ("annotateDerivations", "filterConditionClassFacts")
    hits = sum(hasattr(derivation_citation, name) for name in probes)
    return "implemented" if hits == len(probes) else ("partial" if hits else "planned")


def _probeAccessQueryFacade() -> str:
    """CQ-02：四动词门面的 query 端点。"""
    from neurova.api.endpoints import knowledge_access_facade

    return "implemented" if hasattr(knowledge_access_facade, "accessQuery") else "planned"


def _probeTransitiveClosure() -> str:
    """CQ-03：传递闭包。"""
    from neurova.knowledge.ontology import rule_engine

    return "implemented" if hasattr(rule_engine.ForwardChainingEngine, "transitiveClosure") else "planned"


def _probeRelationCandidates() -> str:
    """CQ-04：关系候选（列表/批准/驳回三端点）。"""
    from neurova.api.endpoints import knowledge_ontology

    probes = ("list_relation_candidates", "approve_relation_candidate", "reject_relation_candidate")
    hits = sum(hasattr(knowledge_ontology, name) for name in probes)
    return "implemented" if hits == len(probes) else ("partial" if hits else "planned")


def _probeDerivationLedger() -> str:
    """CQ-05：推导前提追溯与规则撤销。"""
    from neurova.knowledge.ontology import derivation_ledger, rule_engine

    hits = (
        hasattr(derivation_ledger.DerivationLedger, "premisesOf")
        + hasattr(rule_engine.ForwardChainingEngine, "dropRule")
    )
    return "implemented" if hits == 2 else ("partial" if hits else "planned")


def _probeDerivationAnnotation() -> str:
    """CQ-06：检索命中的推导/观察标注。"""
    from neurova.knowledge import derivation_citation

    probes = ("annotateDerivations", "derivationSummary")
    hits = sum(hasattr(derivation_citation, name) for name in probes)
    return "implemented" if hits == len(probes) else ("partial" if hits else "planned")


def _probeTurtleExport() -> str:
    """CQ-07：确定性 Turtle 导出端点。"""
    from neurova.api.endpoints import knowledge_ontology

    return "implemented" if hasattr(knowledge_ontology, "export_ontology_turtle") else "planned"


def _probeLineageTables() -> str:
    """CQ-08：血缘两表（assertions/activities）在迁移注册表里有步骤。"""
    from neurova.knowledge.foundation import foundation_schema

    joined = "\n".join(sql for _ver, sql in getattr(foundation_schema, "_STEPS", []))
    ok = "knowledge_assertions" in joined and "knowledge_activities" in joined
    return "implemented" if ok else "planned"


def _probeUpperLiteSeeds() -> str:
    """CQ-09：upper-lite 种子。"""
    from neurova.knowledge.ontology import upper_lite

    return "implemented" if hasattr(upper_lite, "seedUpperLite") else "planned"


def _probeBitemporalRestParams() -> str:
    """CQ-10：asOf/knownAt 是否已接进 access/query 的 REST 签名（W0-1 已接线）。"""
    from neurova.api.endpoints import knowledge_access_facade

    params = inspect.signature(knowledge_access_facade.accessQuery).parameters
    hits = sum(1 for name in ("asOf", "knownAt") if name in params)
    return "implemented" if hits == 2 else ("partial" if hits else "planned")


def _probeShapeValidation() -> str:
    """CQ-11：写入前形状校验（端点＋评估器）。"""
    from neurova.api.endpoints import knowledge_access_facade
    from neurova.knowledge.ontology import shapes

    hits = (
        hasattr(knowledge_access_facade, "accessValidate")
        + hasattr(shapes.ShapeRegistry, "evaluateForRequest")
    )
    return "implemented" if hits == 2 else ("partial" if hits else "planned")


def _probeExportBreadth() -> str:
    """CQ-24：多格式导出（specs/2026-11-12 W11）——GraphML/GEXF/Cypher/CSV 端点。"""
    from neurova.knowledge.ontology.export import graph_exchange

    hits = (
        hasattr(graph_exchange, "exportGraphML")
        + hasattr(graph_exchange, "exportGexf")
        + hasattr(graph_exchange, "exportCypher")
        + hasattr(graph_exchange, "exportCsv")
    )
    return "implemented" if hits == 4 else ("partial" if hits else "planned")


def _probeIngestBreadth() -> str:
    """CQ-23：湖仓/推送摄取（specs/2026-11-12 W10）——三连接器/http_pull/webhook。"""
    from neurova.knowledge.enterprise import connectors_lakehouse, protocols, webhook_receiver
    from neurova.knowledge.enterprise.registry import buildAdapter

    hits = (
        hasattr(connectors_lakehouse.UnityCatalogAdapter, "fetchBatch")
        + hasattr(connectors_lakehouse.HttpPullAdapter, "fetchBatch")
        + ("unity_catalog" in protocols.SOURCE_TYPES)
        + (buildAdapter({"sourceType": "http_pull", "url": "https://x"},
                        "probe", "default") is not None)
        + hasattr(webhook_receiver.WebhookReceiver, "handle")
        + ("enterprise_webhook_dedup" in (webhook_receiver._SCHEMA_V49_WEBHOOK_DEDUP or ""))
    )
    return "implemented" if hits == 6 else ("partial" if hits else "planned")


def _probeInferenceBreadth() -> str:
    """CQ-21/22：推理广度（specs/2026-11-12 W9）——semi-naive/rete/SPARQL/溯因。"""
    from neurova.knowledge.ontology import abduction, rule_engine, sparql_query
    from neurova.mcp_ontology_server import ontology_abduce, ontology_sparql  # noqa: F401

    hits = (
        hasattr(rule_engine, "EVALUATION_STRATEGIES")
        + ("rete" in rule_engine.EVALUATION_STRATEGIES)
        + hasattr(sparql_query, "runSparqlQuery")
        + hasattr(abduction, "explainGoal")
        + (ontology_sparql is not None)
        + (ontology_abduce is not None)
    )
    return "implemented" if hits == 6 else ("partial" if hits else "planned")


def _probeGraphRag() -> str:
    """CQ-18/19/20：GraphRAG 工艺（specs/2026-11-12 W8）——策略注册/社区/消解。"""
    from neurova.knowledge import chunk_dispatch, community_graph, resolution
    from neurova.mcp_ontology_server import ontology_community_search  # noqa: F401

    hits = (
        (len(chunk_dispatch.CHUNK_KINDS) == 13)
        + hasattr(chunk_dispatch.ChunkStrategyRegistry, "register")
        + hasattr(community_graph.CommunityGraphBuilder, "detect")
        + (ontology_community_search is not None)
        + hasattr(resolution, "candidatePairsBlocking")
        + ("conflict_policy" in (community_graph._SCHEMA_V48_COMMUNITIES or ""))
    )
    return "implemented" if hits == 6 else ("partial" if hits else "planned")


def _probeDecisions() -> str:
    """CQ-16/17：决策因果与判例（specs/2026-11-12 W7）——台账/链接/trace/检索。"""
    from neurova.knowledge.ontology import decision_ledger
    from neurova.mcp_ontology_server import (ontology_decision_link,  # noqa: F401
                                             ontology_decision_precedents,
                                             ontology_decision_record,
                                             ontology_decision_trace)

    hits = (
        hasattr(decision_ledger.DecisionLedger, "recordDecision")
        + hasattr(decision_ledger.DecisionLedger, "linkDecisions")
        + hasattr(decision_ledger.DecisionLedger, "traceDecisionChain")
        + hasattr(decision_ledger.DecisionLedger, "findPrecedents")
        + (ontology_decision_record is not None)
        + (ontology_decision_trace is not None)
    )
    return "implemented" if hits == 6 else ("partial" if hits else "planned")


def _probeSimulation() -> str:
    """CQ-14：推演类（specs/2026-11-12 W5）——副本隔离/台账/工具。"""
    from neurova.knowledge.ontology import simulation
    from neurova.mcp_ontology_server import ontology_simulate  # noqa: F401

    hits = (
        hasattr(simulation, "runSimulation")
        + ("ontology_simulations" in (simulation._SCHEMA_V46_SIMULATIONS or ""))
        + (ontology_simulate is not None)
        + hasattr(simulation, "ScopeTooLargeError")
    )
    return "implemented" if hits == 4 else ("partial" if hits else "planned")


def _probeActionSemantics() -> str:
    """CQ-15：动作前置拒（specs/2026-11-12 W4）——语义三列/运行时/MCP 门面。"""
    from neurova.knowledge.ontology import action_registry, action_runtime
    from neurova.mcp_ontology_server import ontology_act  # noqa: F401

    hits = (
        ("precondition_json" in (action_registry._SCHEMA_V45_ACTION_SEMANTICS or ""))
        + hasattr(action_runtime, "executeAction")
        + (ontology_act is not None)
        + hasattr(action_registry.ActionRegistry, "upsert")
    )
    return "implemented" if hits == 4 else ("partial" if hits else "planned")


def _probeStateMachines() -> str:
    """CQ-13：状态类（specs/2026-11-12 W3）——登记面/迁移判/事件桥/读数工具。"""
    from neurova.api.endpoints import knowledge_ontology
    from neurova.knowledge import state_event_bridge
    from neurova.knowledge.ontology import state_machine_registry, validation

    hits = (
        hasattr(state_machine_registry.StateMachineRegistry, "register")
        + (1 if callable(getattr(validation.OntologyValidationReport,
                                 "_stateTransitionFindings", None)) else 0)
        + hasattr(state_event_bridge, "StateEventBridge")
        + hasattr(knowledge_ontology, "create_state_machine")
    )
    return "implemented" if hits == 4 else ("partial" if hits else "planned")


def _probeFunctionLayer() -> str:
    """CQ-12：数值计算层（specs/2026-11-12 W2）——登记面/引擎/MCP dry 工具。"""
    from neurova.api.endpoints import knowledge_ontology
    from neurova.knowledge.ontology import function_engine, function_registry
    from neurova.mcp_ontology_server import ontology_compute  # noqa: F401

    hits = (
        hasattr(function_registry.FunctionRegistry, "register")
        + hasattr(function_engine.FunctionEngine, "fireFor")
        + (ontology_compute is not None)
        + hasattr(knowledge_ontology, "create_ontology_function")
    )
    return "implemented" if hits == 4 else ("partial" if hits else "planned")


# ---------------------------------------------------------------------------
# 名册（元数据照抄 specs 票面；探针引用直挂本模块函数）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CqTraceRow:
    """一行＝一条能力问题的登记内容。"""

    cqId: str
    question: str
    actor: str
    priority: str
    #: 面向显示的转写：主干与 specs 票面对齐（判据钉前缀），可带显示注解。
    query: str
    #: 追溯键，逐字照抄 specs（含 ::类名段）。
    testId: str
    probe: Callable[[], str]


#: 顺序即面板顺序；元数据与 specs 追溯矩阵逐行对齐（对拍判据当场红）。
CQ_TRACE_ROWS: tuple = (
    CqTraceRow(
        cqId="CQ-01", question="哪些订单当前被归为高风险订单？", actor="知识使用者", priority="P1",
        query="GET /v1/knowledge-graph/{agent_id}/knowledge-graph（条件类推导实例 HighRiskOrder）",
        testId="tests/unit/knowledge/ontology/test_conditionClassDerivation.py::TestConditionClassDerivation",
        probe=_probeConditionClassDerivation),
    CqTraceRow(
        cqId="CQ-02", question="某主体与另一主体之间有哪些直接关系？", actor="知识使用者", priority="P1",
        query="POST /v1/knowledge/access/query（facts 检索，谓词过滤）",
        testId="tests/unit/knowledge/ontology/test_ontology_gate.py::TestFiveRules",
        probe=_probeAccessQueryFacade),
    CqTraceRow(
        cqId="CQ-03", question="从某实体出发沿传递关系能到哪些实体？", actor="知识使用者", priority="P1",
        query="ForwardChainingEngine.transitiveClosure(agentId, predicate)",
        testId="tests/unit/knowledge/ontology/test_forward_chaining.py::TestTransitiveClosure",
        probe=_probeTransitiveClosure),
    CqTraceRow(
        cqId="CQ-04", question="抽取出的未登记关系词形去了哪里、如何转正？", actor="本体管理员", priority="P1",
        query="GET/POST /v1/knowledge/ontology/relation-candidates*",
        testId="tests/unit/knowledge/ontology/test_relationMapping.py::TestUnknownRelationCandidate",
        probe=_probeRelationCandidates),
    CqTraceRow(
        cqId="CQ-05", question="一条推导结论由哪些规则与前提得出、如何精确撤销？", actor="本体管理员", priority="P1",
        query="DerivationLedger.premisesOf(factId) / dropRule",
        testId="tests/unit/knowledge/ontology/test_derivation_retract.py",
        probe=_probeDerivationLedger),
    CqTraceRow(
        cqId="CQ-06", question="检索命中里哪些是推导事实、哪些是观察事实？", actor="知识使用者", priority="P1",
        query="检索命中 derivation 标注（derivation_citation 单源）",
        testId="tests/unit/knowledge/test_derivationCitation.py",
        probe=_probeDerivationAnnotation),
    CqTraceRow(
        cqId="CQ-07", question="本体全库能否确定性交换导出、读回无损？", actor="集成方", priority="P1",
        query="GET /v1/knowledge/ontology/export.ttl",
        testId="tests/unit/knowledge/ontology/test_turtleExport.py",
        probe=_probeTurtleExport),
    CqTraceRow(
        cqId="CQ-08", question="一条事实的说法来源与证据链是什么？", actor="审计员", priority="P1",
        query="knowledge_assertions / knowledge_activities（血缘段）",
        testId="tests/unit/knowledge/test_digest_chain_integrity.py",
        probe=_probeLineageTables),
    CqTraceRow(
        cqId="CQ-09", question="上层本体（实体/事件/代理）如何约束类型层级？", actor="本体建模者", priority="P1",
        query="upper-lite 种子（seedUpperLite）＋父链查询",
        testId="tests/unit/knowledge/ontology/test_upperLite.py::TestUpperLiteSeeds",
        probe=_probeUpperLiteSeeds),
    CqTraceRow(
        cqId="CQ-10", question="某类事实在历史某时点是否成立（双时态）？", actor="审计员", priority="P2",
        query="asOf/knownAt 查询（B11 落地；W0-1 补 accessQuery 显式签名＋MCP 透传＋非法 4xx）",
        testId="tests/unit/knowledge/ontology/test_bitemporalQuery.py",
        probe=_probeBitemporalRestParams),
    CqTraceRow(
        cqId="CQ-11", question="写入前能否按自定义形状（SHACL 语义）做完整性校验？", actor="本体管理员", priority="P2",
        query="shapes 注册表＋dry-run（B10 落地，POST /ontology/validate）",
        testId="tests/unit/knowledge/ontology/test_ontologyShapes.py",
        probe=_probeShapeValidation),
    CqTraceRow(
        cqId="CQ-12", question="数值属性能否参与计算（聚合/比较出结论）？", actor="分析师", priority="P2",
        query="函数层（specs/2026-11-12 W2 落地：受限 AST＋selector 聚合＋咽喉入账）",
        testId="tests/unit/knowledge/ontology/test_functionDerivationGovernance.py",
        probe=_probeFunctionLayer),
    CqTraceRow(
        cqId="CQ-13", question="对象当前处于什么状态、允许哪些迁移？", actor="运维员", priority="P2",
        query="状态机（specs/2026-11-12 W3 落地：has_state＋迁移闭集＋事件桥）",
        testId="tests/unit/knowledge/ontology/test_stateMachineValidation.py",
        probe=_probeStateMachines),
    CqTraceRow(
        cqId="CQ-15", question="动作的前置条件不满足时是否拒绝执行？", actor="运维员", priority="P2",
        query="动作语义（specs/2026-11-12 W4 落地：precondition 不触工具＋单管道转交）",
        testId="tests/unit/knowledge/ontology/test_actionPrecondition.py",
        probe=_probeActionSemantics),
    CqTraceRow(
        cqId="CQ-14", question="假设某状态变化后下游会受什么影响？", actor="运维员", priority="P2",
        query="推演（specs/2026-11-12 W5 落地：副本隔离零生产写＋diff 报告）",
        testId="tests/unit/knowledge/ontology/test_simulationDiff.py",
        probe=_probeSimulation),
    CqTraceRow(
        cqId="CQ-16", question="这个决定依据什么、导致了什么下游后果？", actor="审计员", priority="P2",
        query="决策因果（specs/2026-11-12 W7 落地：决策台账＋caused 闭包 trace）",
        testId="tests/unit/knowledge/ontology/test_decisionCausalChain.py",
        probe=_probeDecisions),
    CqTraceRow(
        cqId="CQ-18", question="同一篇文档能否按声明的策略切块？", actor="知识管理员", priority="P2",
        query="切块策略（specs/2026-11-12 W8 落地：十三 kind 注册表＋单点分派）",
        testId="tests/unit/knowledge/test_chunkStrategyRegistry.py",
        probe=_probeGraphRag),
    CqTraceRow(
        cqId="CQ-19", question="整个语料库的社区结构与摘要能否检索？", actor="知识使用者", priority="P2",
        query="社区检索（specs/2026-11-12 W8 落地：标签传播＋global/drift）",
        testId="tests/unit/knowledge/test_communityGraphRAG.py",
        probe=_probeGraphRag),
    CqTraceRow(
        cqId="CQ-20", question="消解候选对是否被 blocking 收敛？", actor="知识管理员", priority="P2",
        query="消解补强（specs/2026-11-12 W8 落地：倒排桶 blocking＋近形守卫）",
        testId="tests/unit/knowledge/test_resolutionBlocking.py",
        probe=_probeGraphRag),
    CqTraceRow(
        cqId="CQ-21", question="递归推理在增量下结论还一致吗？", actor="知识管理员", priority="P2",
        query="推理广度（specs/2026-11-12 W9 落地：semi-naive 增量＋rete 策略槽）",
        testId="tests/unit/knowledge/ontology/test_semiNaiveEquivalence.py",
        probe=_probeInferenceBreadth),
    CqTraceRow(
        cqId="CQ-22", question="能否用 SPARQL 查询/溯因解释一条事实？", actor="集成方", priority="P2",
        query="SPARQL/溯因（specs/2026-11-12 W9 落地：投影只读＋解释树）",
        testId="tests/unit/knowledge/ontology/test_sparqlReadOnly.py",
        probe=_probeInferenceBreadth),
    CqTraceRow(
        cqId="CQ-23", question="湖仓/HTTP 推送源能否进同一摄取管道？", actor="集成方", priority="P2",
        query="摄取广度（specs/2026-11-12 W10 落地：三连接器＋http_pull 接线＋webhook 幂等）",
        testId="tests/unit/knowledge/enterprise/test_lakehouseConnectors.py",
        probe=_probeIngestBreadth),
    CqTraceRow(
        cqId="CQ-24", question="全库能否导出为外部图库可消化的格式？", actor="集成方", priority="P2",
        query="多格式导出（specs/2026-11-12 W11 落地：GraphML/GEXF/Cypher/CSV 确定性）",
        testId="tests/unit/knowledge/ontology/test_exportFormats.py",
        probe=_probeExportBreadth),
    CqTraceRow(
        cqId="CQ-17", question="过去有没有同类场景的判例？", actor="审计员", priority="P2",
        query="判例检索（specs/2026-11-12 W7 落地：词法混合计分，嵌入偏差登记）",
        testId="tests/unit/knowledge/ontology/test_decisionPrecedents.py",
        probe=_probeDecisions),
)


def cqTraceRows() -> List[Dict[str, str]]:
    """一次答完 11 条：元数据照 specs、status 为探针现值。

    不回探针名/归属模块等工程内部——页面是能力面板，不是工程面板。
    """
    rows: List[Dict[str, str]] = []
    for entry in CQ_TRACE_ROWS:
        rows.append({
            "cqId": entry.cqId,
            "question": entry.question,
            "actor": entry.actor,
            "priority": entry.priority,
            "query": entry.query,
            "testId": entry.testId,
            "status": entry.probe(),
        })
    return rows
