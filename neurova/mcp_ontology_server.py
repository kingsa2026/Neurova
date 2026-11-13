# -*- coding: utf-8 -*-
"""本体 MCP server（Ontology 接入 Agent 补全设计 M0/A1/A2，2026-11-10）。

把本体查询/断言校验/事实写入以 MCP tools 开放（拍板：MCP server 形态，双鉴权）：

- M0 基座：`build_ontology_mcp_asgi()` 返回带鉴权中间件的 ASGI app（挂主 app
  `/v1/mcp`）；鉴权双支持——X-Service-Token（服务身份）/X-API-Key（用户身份）/
  Bearer JWT，全不成立 fail-closed 401；身份经 ASGI scope state 传给 tool handler；
- A1 只读两件：ontology_query（术语/动作查询）、ontology_validate（断言 dry-run）；
- A2 写入一件：fact_submit（经 admission 唯一咽喉，默认直写拍板——逐字可核闸＋
  新谓词候选审批＋冲突三态票三层异步人审兜底，运维可经治理白名单收紧为同步审批）；
- A3/A4 工具（ontology_derive/动作清单）随 P2 批次在同文件追加。

**接线不是第二实现**（B3 门面先例）：handler 只转交既有处理函数
（OntologyTermRegistry/validateOntologyCandidates/productionAdmissionGate），
零业务逻辑复制；Agent 侧经 MCP client 链调用时（`mcp.` 前缀工具名）治理/审批/
审计/mcp_grants 全链复用（`tool_executor.py` is_mcp 分支）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mcp.server.mcpserver import Context, MCPServer
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_MCP_INSTRUCTIONS = (
    "Neurova 本体语义层：查询业务对象/关系/约束（ontology_query）、"
    "写入前自查断言合法性（ontology_validate）、提交业务断言入库（fact_submit，"
    "经逐字可核闸与候选/冲突异步人审兜底）。所有读写按调用凭据的租户隔离。"
)

_SERVER = MCPServer(name="neurova-ontology", instructions=_MCP_INSTRUCTIONS,
                    version="1.0.0")


# ── M0 鉴权（双支持拍板：服务令牌/API key/JWT；全不成立 fail-closed 401）──────

def _headersDict(scope: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in scope.get("headers") or []:
        out.setdefault(key.decode("latin-1").lower(), value.decode("latin-1"))
    return out


def _resolveIdentityFromHeaders(headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """与 REST 同族同规则的三段身份解析；返回 None = 401。

    不做静默降级（与 `get_current_user_or_api_key` 同一口径）：每段独立成立才用。
    """
    from neurova.api.api_key_manager import get_api_key_manager
    from neurova.api.auth import (
        _API_KEY_HEADER,
        _SERVICE_TOKEN_HEADER,
        service_token_matches,
    )

    if service_token_matches(headers.get(_SERVICE_TOKEN_HEADER.lower(), "")):
        return {
            "user_id": "system", "username": "service", "role": "admin",
            "neuser_id": "system", "tenant_id": "default",
            "auth_source": "service_token",
        }
    rawKey = (headers.get(_API_KEY_HEADER.lower()) or "").strip()
    if rawKey:
        apiKey = get_api_key_manager().validate_key(rawKey)
        if apiKey is not None:
            return {
                "user_id": apiKey.user_id, "username": f"apikey:{apiKey.name}",
                "role": "user", "neuser_id": apiKey.user_id,
                "agent_id": apiKey.agent_id, "key_id": apiKey.key_id,
                "tenant_id": "default", "auth_source": "api_key",
            }
    bearer = (headers.get("authorization") or "").strip()
    if bearer.lower().startswith("bearer "):
        return None  # JWT 走异步校验（见 asgi_entry），此处同步段不处理
    return None


def _identityFromJwt(token: str) -> Optional[Dict[str, Any]]:
    """JWT 段：复用 REST 的 `_identityFromCredentialsOr401`（同一校验实现，
    同步函数——唯一事实源不因 MCP 面改 async）。"""
    from fastapi.security.http import HTTPAuthorizationCredentials
    from neurova.api.auth import _identityFromCredentialsOr401

    try:
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        return _identityFromCredentialsOr401(creds)
    except Exception:  # noqa: BLE001 - JWT 无效即 401，不降级
        return None


async def _resolveIdentity(scope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    headers = _headersDict(scope)
    user = _resolveIdentityFromHeaders(headers)
    if user is not None:
        return user
    bearer = (headers.get("authorization") or "").strip()
    if bearer.lower().startswith("bearer "):
        return _identityFromJwt(bearer[7:].strip())
    return None


def _currentUserFromContext(ctx: Any) -> Dict[str, Any]:
    """从 MCP 请求上下文取中间件解析出的身份（缺省 service 视角，防御态）。"""
    try:
        request = getattr(getattr(ctx, "request_context", None), "request", None)
        user = getattr(getattr(request, "state", None), "neurova_user", None)
        if isinstance(user, dict):
            return user
    except Exception:  # noqa: BLE001 - 身份读取失败按无身份处理
        pass
    return {"user_id": "system", "username": "service", "role": "admin",
            "tenant_id": "default"}


def _tenantOf(user: Dict[str, Any]) -> str:
    return str((user or {}).get("tenant_id") or "default")


def _agentIdOf(user: Dict[str, Any], agentId: Optional[str]) -> str:
    return str(agentId or (user or {}).get("agent_id") or "default")


def _store():
    from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store

    return get_knowledge_fact_store()


# ── A1：ontology_query（只读）────────────────────────────────────────────────

@_SERVER.tool()
async def ontology_query(
    ctx: Context,
    query: str = "",
    kind: str = "",
    namespace: str = "",
    as_of: str = "",
    known_at: str = "",
) -> dict:
    """查询本体术语（只读）：按 term_id/label/别名模糊匹配。query 传关键词；
    kind 可选 concept/relation/property；namespace 可选过滤（so = 标准本体
    领域包；空 = 全部命名空间）。动作清单随 A4 批次扩展。
    W0-1：as_of/known_at 任一给出时切换为双时态时点事实查询（透传存储层
    factsBitemporal，CQ-10）；不可解析时间显式结构化拒绝，不静默忽略。"""
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    user = _currentUserFromContext(ctx)
    tenant = _tenantOf(user)
    needle = str(query or "").strip().lower()

    if as_of or known_at:
        # W0-1 双时态时点事实模式：与 REST /access/query 同一存储层查询、
        # 同一 parseBitemporalStamp 判据（不各写一份校验）。
        from neurova.knowledge.foundation.knowledge_facts import parseBitemporalStamp

        try:
            facts = _store().factsBitemporal(
                _agentIdOf(user, None), tenantId=tenant,
                asOf=parseBitemporalStamp(as_of, "as_of"),
                knownAt=parseBitemporalStamp(known_at, "known_at"))
        except ValueError as exc:
            return {"rejected": True, "detail": str(exc)}
        rows = []
        for fact in facts:
            haystack = " ".join([
                str(fact.get("content") or ""), str(fact.get("subject_key") or ""),
                str(fact.get("predicate_term_id") or ""),
                str(fact.get("object_term") or "")]).lower()
            if needle and needle not in haystack:
                continue
            rows.append({
                "fact_id": str(fact.get("fact_id") or ""),
                "subject_key": str(fact.get("subject_key") or ""),
                "predicate_term_id": str(fact.get("predicate_term_id") or ""),
                "object_term": str(fact.get("object_term") or ""),
                "content": str(fact.get("content") or ""),
                "confidence": fact.get("confidence"),
                "valid_from": fact.get("valid_from"),
                "valid_until": fact.get("valid_until"),
                "recorded_at": fact.get("recorded_at"),
                "retracted_at": fact.get("retracted_at"),
            })
        return {"tenant_id": tenant, "mode": "bitemporal", "facts": rows,
                "count": len(rows)}

    registry = OntologyTermRegistry(_store())

    if kind == "action":
        from neurova.knowledge.ontology.action_registry import getActionRegistry

        rows = getActionRegistry(_store()).list(tenantId=tenant)
        hits = [r for r in rows
                if not needle or needle in str(r["action_id"]).lower()
                or needle in str(r["label"]).lower()]
        return {"tenant_id": tenant, "matches": hits, "count": len(hits)}

    matches: List[Dict[str, Any]] = []
    for term in registry.terms(kind=kind or None, tenantId=tenant):
        if namespace and term.get("namespace") != namespace:
            continue
        termId = str(term.get("term_id") or "")
        haystack = " ".join([termId, str(term.get("label") or ""),
                             *(term.get("aliases") or [])]).lower()
        if needle and needle not in haystack:
            continue
        matches.append({k: term.get(k) for k in
                        ("term_id", "kind", "label", "definition", "datatype",
                         "namespace", "parent_term_id", "aliases")})
        if len(matches) >= 50:
            break
    return {"tenant_id": tenant, "matches": matches, "count": len(matches)}


# ── A1：ontology_validate（只读 dry-run）─────────────────────────────────────

@_SERVER.tool()
async def ontology_validate(
    ctx: Context,
    subject_label: str,
    predicate_term_id: str,
    object_term: str,
) -> dict:
    """写入前自查一条断言的合法性（只读 dry-run，不落库）：返回 findings 与
    verdict（pass/violation）。提交 fact_submit 前先调本工具可避免整批被拒。"""
    from neurova.knowledge.ontology.pipeline import dryRunFactCandidates
    from neurova.knowledge.ontology.shapes import ShapeRegistry
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
    from neurova.knowledge.ontology.validation import OntologyValidationReport

    user = _currentUserFromContext(ctx)
    agentId = _agentIdOf(user, None)
    tenant = _tenantOf(user)
    store = _store()
    rows = dryRunFactCandidates(
        store, agentId, tenant,
        [{"subjectLabel": subject_label, "predicateTermId": predicate_term_id,
          "objectTerm": object_term}],
        registry=OntologyTermRegistry(store),
        report=OntologyValidationReport(OntologyTermRegistry(store),
                                        shapes=ShapeRegistry(store)))
    row = rows[0] if rows else {}
    return {"verdict": row.get("verdict"), "findings": row.get("findings", [])}


# ── A2：fact_submit（写入，经 admission 唯一咽喉）────────────────────────────

@_SERVER.tool()
async def fact_submit(
    ctx: Context,
    subject_label: str,
    predicate_term_id: str,
    object_term: str,
    evidence_text: str = "",
    agent_id: str = "",
    simulation_id: str = "",
) -> dict:
    """提交一条业务断言入库（写入，默认直写）：经 admission 唯一咽喉逐字可核闸；
    未知谓词落候选审批面、冲突落三态票（三层异步人审兜底）。evidence_text 是
    可核证据原文——缺失会被逐字可核闸拒绝。返回 fact_id 供后续引用。"""
    from neurova.knowledge.foundation.admission import (
        AdmissionRequest,
        productionAdmissionGate,
    )

    user = _currentUserFromContext(ctx)
    agentId = _agentIdOf(user, agent_id)
    tenant = _tenantOf(user)
    content = f"{subject_label} {predicate_term_id} {object_term}".strip()
    qualifier = {"simulation_id": simulation_id} if simulation_id else {}
    from neurova.knowledge.foundation.admission import AdmissionError

    gate = productionAdmissionGate(_store())
    try:
        receipt = gate.admit(AdmissionRequest(
            agentId=agentId, tenantId=tenant,
            subjectLabel=str(subject_label or "").strip(),
            predicateTermId=str(predicate_term_id or "").strip(),
            objectTerm=str(object_term or "").strip(),
            content=content, evidenceText=str(evidence_text or ""),
            qualifier=qualifier,
            assertions=[{"actorType": "agent", "actorId": str(user.get("username") or ""),
                         "mediumRef": "mcp:ontology",
                         "statementText": content}]))
    except AdmissionError as exc:
        # 逐字可核闸/段缺失等契约拒绝：如实结构化回显（不降级成 MCP 工具错误）
        return {"rejected": True, "detail": str(exc)}
    factId = str(getattr(receipt, "factId", "") or "")
    dedup = getattr(receipt, "dedupedByContent", None)
    return {
        "fact_id": factId,
        "deduplicated": bool(dedup),
        # A5 采纳建议读数：采纳是 admin 治理动作（record_fact_adoption），
        # Agent 只获得表达通道——回执说明引用方式，不放宽权限。
        "adoption_hint": f"fact_id={factId} 可被管理员经 /access/use/{factId} 采纳" if factId else "",
    }


# ── A3：ontology_derive（推理查询）────────────────────────────────────────────

def _resolveAgentForActions(agentId: str) -> Optional[Dict[str, Any]]:
    """动作执行载体解析（W4，D5 门面转交）：agent 单源取法与治理端点同源
    （get_agent_instance），执行器 = ToolExecutor(agent)。None＝未就绪。"""
    from neurova.api.endpoints import get_agent_instance

    agent = get_agent_instance(agentId or "")
    if agent is None:
        return None
    from neurova.tool_executor import ToolExecutor

    return {"executor": ToolExecutor(agent), "agent": agent}


@_SERVER.tool()
async def ontology_sparql(
    ctx: Context,
    query: str,
) -> dict:
    """SPARQL 只读查询（W9，D8 已裁）：RDF 投影（turtle 单源）→rdflib SELECT/ASK。
    写形不支持；rdflib 未装显式 not_supported；行数上限/超时常量。"""
    from neurova.knowledge.ontology.sparql_query import (
        SparqlNotSupported,
        runSparqlQuery,
    )

    user = _currentUserFromContext(ctx)
    try:
        return runSparqlQuery(_store(), query, agentId=_agentIdOf(user, None),
                              tenantId=_tenantOf(user))
    except SparqlNotSupported as exc:
        return {"rejected": True, "not_supported": True, "detail": str(exc)}
    except ValueError as exc:
        return {"rejected": True, "detail": str(exc)}


@_SERVER.tool()
async def ontology_abduce(
    ctx: Context,
    subject_label: str,
    predicate: str,
    object_term: str,
    agent_id: str = "",
) -> dict:
    """溯因反向搜索（W9，只读）：目标三元组→解释树（规则/事实引用＋缺失前提
    清单）；深度/分支上限截断声明；解释是候选不是断言，零写。"""
    from neurova.knowledge.ontology.abduction import explainGoal

    user = _currentUserFromContext(ctx)
    return explainGoal(_store(), subjectLabel=subject_label, predicate=predicate,
                       objectTerm=object_term, agentId=_agentIdOf(user, agent_id),
                       tenantId=_tenantOf(user))


@_SERVER.tool()
async def ontology_community_search(
    ctx: Context,
    query: str,
    mode: str = "global",
    limit: int = 5,
) -> dict:
    """社区检索（W8）：mode=global（查询→社区摘要 map 命中）或 drift
    （实体邻域＋所属社区摘要）。既有四路 RRF 缺省行为逐字不变——两模式是
    独立只读检索面。"""
    from neurova.knowledge.community_graph import (
        communityDriftSearch,
        communityGlobalSearch,
    )

    user = _currentUserFromContext(ctx)
    agentId = _agentIdOf(user, None)
    tenant = _tenantOf(user)
    if mode == "global":
        hits = communityGlobalSearch(_store(), query, agentId=agentId,
                                     tenantId=tenant, limit=limit)
    elif mode == "drift":
        hits = communityDriftSearch(_store(), query, agentId=agentId,
                                    tenantId=tenant, limit=limit)
    else:
        return {"rejected": True, "detail": "mode %r 只支持 global|drift" % mode}
    return {"mode": mode, "hits": hits, "count": len(hits)}


@_SERVER.tool()
async def graph_search(
    ctx: Context,
    query: str,
    mode: str = "walk",
    max_hops: int = 2,
    limit: int = 8,
) -> dict:
    """知识图谱检索（graphiti 对照批 C4，只读）：mode=walk（从查询主体沿
    事实边多跳走查，答实体间关系链）、global（社区摘要匹配）、drift（实体
    邻域＋所属社区摘要）。与内置工具 graph_search 同语义、同租户/agent 域
    过滤；max_hops 钳位 2-4，limit 钳位 1-50。"""
    if mode not in ("walk", "global", "drift"):
        return {"rejected": True, "detail": "mode %r 只支持 walk|global|drift" % mode}
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 8
    try:
        maxHops = max(2, min(int(max_hops), 4))
    except (TypeError, ValueError):
        maxHops = 2
    user = _currentUserFromContext(ctx)
    agentId = _agentIdOf(user, None)
    tenant = _tenantOf(user)
    store = _store()
    if mode == "walk":
        from neurova.knowledge.foundation.graph_walk import (
            GraphFactWalker,
            GraphWalkConfig,
        )

        walker = GraphFactWalker(
            store, agentId=agentId,
            config=GraphWalkConfig(enabled=True, maxHops=maxHops, limit=limit),
        )
        results = walker.walkFromQuery(query, maxHops=maxHops, limit=limit,
                                       tenantId=tenant)
    elif mode == "global":
        from neurova.knowledge.community_graph import communityGlobalSearch

        results = communityGlobalSearch(store, query, agentId=agentId,
                                        tenantId=tenant, limit=limit)
    else:
        from neurova.knowledge.community_graph import communityDriftSearch

        results = communityDriftSearch(store, query, agentId=agentId,
                                       tenantId=tenant, limit=limit)
    return {"mode": mode, "results": results, "count": len(results)}


@_SERVER.tool()
async def ontology_decision_record(
    ctx: Context,
    category: str,
    scenario: str,
    reasoning: str,
    outcome: str,
    confidence: float,
    owner_id: str = "",
    simulation_id: str = "",
    action_id: str = "",
) -> dict:
    """决策登记（W7，D7 必选）：决策一等对象——decision_maker 取请求边界
    sender（不从 ContextVar 猜）；可选 simulationId/actionId 审计互链
    （metadata_json，D4 同款）。决策是问责台账，不经事实门。"""
    user = _currentUserFromContext(ctx)
    from neurova.knowledge.ontology.decision_ledger import DecisionLedger

    metadata: dict = {}
    if simulation_id:
        metadata["simulation_id"] = simulation_id
    if action_id:
        metadata["action_id"] = action_id
    try:
        row = DecisionLedger(_store()).recordDecision(
            tenantId=_tenantOf(user), category=category, scenario=scenario,
            reasoning=reasoning, outcome=outcome, confidence=confidence,
            decisionMaker=str(user.get("username") or ""),
            ownerId=str(owner_id or user.get("user_id") or ""),
            agentId=_agentIdOf(user, None), sessionId="",
            metadata=metadata)
    except ValueError as exc:
        return {"rejected": True, "detail": str(exc)}
    return row


@_SERVER.tool()
async def ontology_decision_link(
    ctx: Context,
    source_decision_id: str,
    target_decision_id: str,
    link_kind: str,
) -> dict:
    """决策链接（W7）：caused/precedent 无环硬校验、influenced 允许环；
    跨租户拒/自环拒；因果边不进推导账本（另一域）。"""
    user = _currentUserFromContext(ctx)
    from neurova.knowledge.ontology.decision_ledger import DecisionLedger

    try:
        return DecisionLedger(_store()).linkDecisions(
            source_decision_id, target_decision_id, link_kind,
            tenantId=_tenantOf(user),
            createdBy=str(user.get("username") or ""))
    except (ValueError, LookupError) as exc:
        return {"rejected": True, "detail": str(exc)}


@_SERVER.tool()
async def ontology_decision_trace(
    ctx: Context,
    decision_id: str,
    direction: str = "both",
) -> dict:
    """决策因果链（W7）：上溯/下探/双向，深度上限具名常量。影响图＝下游闭包读数。"""
    from neurova.knowledge.ontology.decision_ledger import DecisionLedger

    user = _currentUserFromContext(ctx)
    return {"decision_id": decision_id, "direction": direction,
            "chain": DecisionLedger(_store()).traceDecisionChain(
                decision_id, direction=direction, tenantId=_tenantOf(user))}


@_SERVER.tool()
async def ontology_decision_precedents(
    ctx: Context,
    query: str,
    limit: int = 5,
) -> dict:
    """判例检索（W7）：词法混合计分（嵌入接入前承载，偏差登记台账）；
    按租户过滤——跨租户零命中。"""
    from neurova.knowledge.ontology.decision_ledger import DecisionLedger

    user = _currentUserFromContext(ctx)
    hits = DecisionLedger(_store()).findPrecedents(
        query, limit=limit, tenantId=_tenantOf(user))
    return {"query": query, "hits": hits, "count": len(hits)}


@_SERVER.tool()
async def ontology_simulate(
    ctx: Context,
    scope_json: str = "{}",
    hypotheses_json: str = "[]",
) -> dict:
    """克隆世界推演（W5，只读生产）：生产库 backup 副本→假设经同一咽喉注入副本
    →规则/函数推演→diff 报告。生产唯一写＝台账追加一行（先演后决互链）。
    scope 超行上限显式拒（不静默截断）。"""
    import json as _json

    from neurova.knowledge.ontology.simulation import ScopeTooLargeError, runSimulation

    user = _currentUserFromContext(ctx)
    try:
        scope = _json.loads(scope_json or "{}")
        hypotheses = _json.loads(hypotheses_json or "[]")
        if not isinstance(scope, dict) or not isinstance(hypotheses, dict):
            raise ValueError("scope_json/hypotheses_json 须是 JSON 对象")
    except ValueError as exc:
        return {"rejected": True, "detail": str(exc)}
    scope.setdefault("agentId", _agentIdOf(user, None))
    scope.setdefault("tenantId", _tenantOf(user))
    try:
        return runSimulation(_store(), scope=scope, hypotheses=hypotheses)
    except ScopeTooLargeError as exc:
        return {"rejected": True, "detail": str(exc)}


@_SERVER.tool()
async def ontology_act(
    ctx: Context,
    action_id: str,
    params_json: str = "{}",
    agent_id: str = "",
    simulation_id: str = "",
) -> dict:
    """动作语义门面（W4，D5 已裁）：①precondition 求值（不满足显式拒，
    **不触工具**）→ ②ToolExecutor.execute 单管道（治理预检/审批/审计/mcp_grants
    全继承，本门面零复制判定）→ ③成功后 state_change 经 admission（W3 迁移约束
    自动继承）→ ④回执含 impact 声明＋状态读数＋fact_id/溯源。simulation_id 为
    先演后决互链（W5 落格后接台账，缺省 off）。"""
    import json as _json

    from neurova.knowledge.ontology.action_registry import ActionRegistry
    from neurova.knowledge.ontology.action_runtime import (
        ActionPreconditionError,
        executeAction,
    )

    user = _currentUserFromContext(ctx)
    tenant = _tenantOf(user)
    try:
        params = _json.loads(params_json or "{}")
        if not isinstance(params, dict):
            raise ValueError("params_json 须是 JSON 对象")
    except ValueError as exc:
        return {"rejected": True, "detail": "params_json 不可解析：%s" % exc}
    action = ActionRegistry(_store()).action(str(action_id or "").strip(),
                                             tenantId=tenant)
    if action is None:
        return {"rejected": True, "detail": "动作未登记: %s" % action_id}
    if not action.get("enabled"):
        return {"rejected": True, "detail": "动作已停用: %s" % action_id}
    resolved = _resolveAgentForActions(_agentIdOf(user, agent_id))
    if resolved is None:
        return {"rejected": True,
                "detail": "Agent 未就绪（动作执行载体不可用，稍后重试）"}
    try:
        receipt = await executeAction(
            action, params, resolved["executor"], _store(),
            agentId=_agentIdOf(user, agent_id), tenantId=tenant,
            machineRegistry=None)
        if simulation_id:
            receipt["simulation_id"] = simulation_id
        return receipt
    except ActionPreconditionError as exc:
        return {"rejected": True, "detail": str(exc),
                "action_id": action.get("action_id")}


@_SERVER.tool()
async def ontology_state(
    ctx: Context,
    subject_label: str,
    agent_id: str = "",
) -> dict:
    """主体状态读数（W3，只读）：当前状态＋状态机声明（states/transitions 闭集）
    ＋允许迁移列表。状态机未登记时如实回 has_machine=False。"""
    from neurova.knowledge.foundation.knowledge_facts import normalizeLabel
    from neurova.knowledge.ontology.state_machine_registry import StateMachineRegistry

    user = _currentUserFromContext(ctx)
    agentId = _agentIdOf(user, agent_id)
    tenant = _tenantOf(user)
    store = _store()
    normalized = normalizeLabel(subject_label)
    row = store._conn.execute(
        "SELECT subject_key, type_term_id FROM knowledge_subjects"
        " WHERE agent_id = ? AND tenant_id = ? AND normalized_label = ?"
        " AND status = 'active'",
        (agentId, tenant, normalized)).fetchone()
    if row is None:
        return {"rejected": True, "detail": "主体未登记: %s" % subject_label}
    subjectKey = str(row["subject_key"])
    typeTerm = str(row["type_term_id"] or "")
    machine = StateMachineRegistry(store).get(typeTerm, tenantId=tenant) if typeTerm else None
    registry = StateMachineRegistry(store)
    current = registry.currentState(agentId, subjectKey, tenantId=tenant)
    allowed: list = []
    if machine is not None and current:
        allowed = [t.get("to") for t in (machine.get("transitions") or [])
                   if str(t.get("from")) == current]
    return {
        "subject_label": subject_label,
        "subject_key": subjectKey,
        "type_term_id": typeTerm,
        "has_machine": machine is not None,
        "machine": {"states": (machine or {}).get("states"),
                    "transitions": (machine or {}).get("transitions"),
                    "initial_state": (machine or {}).get("initial_state")},
        "current_state": current,
        "allowed_transitions": allowed,
    }


@_SERVER.tool()
async def ontology_compute(
    ctx: Context,
    function_id: str,
    subject: str = "",
    agent_id: str = "",
) -> dict:
    """函数层只读 dry 求值（W2）：返回值＋输入快照＋表达式回显，**零落库**。
    真正落结论走 admission 写入口（dispatch 点燃）；本工具只回答"这个函数
    对这个主体现在算出多少"。selector 超行上限时结构化拒绝（D1 显式拒）。"""
    from neurova.knowledge.ontology.function_engine import FunctionEngine

    user = _currentUserFromContext(ctx)
    agentId = _agentIdOf(user, agent_id)
    tenant = _tenantOf(user)
    engine = FunctionEngine(_store())
    try:
        result = engine.dryEval(str(function_id or "").strip(),
                                subject=str(subject or ""), tenantId=tenant)
    except LookupError as exc:
        return {"rejected": True, "detail": str(exc)}
    if result.get("rejected"):
        return {"rejected": True, "detail": result.get("detail"),
                "expr_text": result.get("expr_text")}
    return result


@_SERVER.tool()
async def ontology_derive(
    ctx: Context,
    subject_label: str,
    agent_id: str = "",
) -> dict:
    """对本体的派生结论做一次求值查询：规则引擎求值到不动点（enforce 级规则
    结论经咽喉入库后直接可用；observe 态结论标注「观察态」防误导），返回该主体的
    活动事实与推导溯源（结论由哪条规则/哪些前提推出）。"""
    from neurova.knowledge.foundation.knowledge_facts import normalizeLabel
    from neurova.knowledge.foundation.admission import productionAdmissionGate
    from neurova.knowledge.ontology.derivation_ledger import DerivationLedger
    from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine

    user = _currentUserFromContext(ctx)
    agentId = _agentIdOf(user, agent_id)
    tenant = _tenantOf(user)
    store = _store()
    # 推理未接咽喉写入口是硬拒（RuleError）——与 REST 面同款装配
    engine = ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(st))
    fire = engine.fireAll(agentId=agentId, tenantId=tenant)

    # 主体定位：身份归一（大小写/空白不敏感）→ subject_key
    normalized = normalizeLabel(subject_label)
    subjectKey = ""
    row = store._conn.execute(
        "SELECT subject_key FROM knowledge_subjects"
        " WHERE agent_id = ? AND tenant_id = ? AND normalized_label = ?",
        (agentId, tenant, normalized)).fetchone()
    if row is not None:
        subjectKey = str(row["subject_key"])

    ledger = DerivationLedger(store)
    derivedIds = set(ledger.derivedFactIds())
    ruleById = {str(r["rule_id"]): r for r in engine.rules(tenantId=tenant)}

    conclusions: List[Dict[str, Any]] = []
    if subjectKey:
        factRows = store._conn.execute(
            "SELECT fact_id, subject_key, predicate_term_id, object_term"
            " FROM knowledge_facts WHERE tenant_id = ? AND agent_id = ?"
            " AND subject_key = ? AND status = 'active' AND record_kind = 'triple'"
            " ORDER BY predicate_term_id",
            (tenant, agentId, subjectKey)).fetchall()
        for factRow in factRows:
            factId = str(factRow["fact_id"])
            premises = ledger.premisesOf(factId)
            entry: Dict[str, Any] = {
                "fact_id": factId,
                "predicate": str(factRow["predicate_term_id"]),
                "object": str(factRow["object_term"]),
                "derived": factId in derivedIds,
                "premises": premises,
            }
            if premises:
                rule = ruleById.get(str(premises[0]["rule_id"]))
                entry["materialization"] = str((rule or {}).get("materialization") or "observe")
                entry["rule_id"] = str(premises[0]["rule_id"])
            conclusions.append(entry)

    return {
        "subject_label": subject_label,
        "subject_key": subjectKey,
        "fire_rounds": fire.get("rounds", []),
        "conclusions": conclusions,
        "count": len(conclusions),
    }


def build_ontology_mcp_asgi():
    """构造本体 MCP 面（一次构建一对，transport 实例 run() 一次不可复用）。

    返回 `(asgi_entry, lifespan)`：asgi_entry 是带鉴权的裸 ASGI callable（挂主 app
    /v1/mcp）；lifespan 是子 Starlette 的 lifespan_context——FastAPI mount 不触发
    子 Starlette 的 lifespan（SDK 的 session_manager task group 在其中启动），
    主 app 的 startup/shutdown 钩子手动驱动它。
    """
    sub_app = _SERVER.streamable_http_app(streamable_http_path="/",
                                          json_response=True,
                                          stateless_http=True)
    lifespan_cm = sub_app.router.lifespan_context

    async def asgi_entry(scope, receive, send):
        if scope["type"] != "http":
            return await sub_app(scope, receive, send)
        user = await _resolveIdentity(scope)
        if user is None:
            resp = JSONResponse({"detail": "MCP 端点需要服务令牌、API key 或 JWT"},
                                status_code=401)
            await resp(scope, receive, send)
            return
        scope.setdefault("state", {})["neurova_user"] = user
        await sub_app(scope, receive, send)

    return asgi_entry, lifespan_cm


def create_ontology_mcp_server() -> MCPServer:
    """测试/工具面获取 server 实例（工具注册态同一份）。"""
    return _SERVER
