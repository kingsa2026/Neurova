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


async def _identityFromJwt(token: str) -> Optional[Dict[str, Any]]:
    """JWT 段：复用 REST 的 `_identityFromCredentialsOr401`（同一校验实现）。"""
    from fastapi.security.http import HTTPAuthorizationCredentials
    from neurova.api.auth import _identityFromCredentialsOr401

    try:
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        return await _identityFromCredentialsOr401(creds)
    except Exception:  # noqa: BLE001 - JWT 无效即 401，不降级
        return None


async def _resolveIdentity(scope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    headers = _headersDict(scope)
    user = _resolveIdentityFromHeaders(headers)
    if user is not None:
        return user
    bearer = (headers.get("authorization") or "").strip()
    if bearer.lower().startswith("bearer "):
        return await _identityFromJwt(bearer[7:].strip())
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
) -> dict:
    """查询本体术语（只读）：按 term_id/label/别名模糊匹配。query 传关键词；
    kind 可选 concept/relation/property；namespace 可选过滤（so = 标准本体
    领域包；空 = 全部命名空间）。动作清单随 A4 批次扩展。"""
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    user = _currentUserFromContext(ctx)
    tenant = _tenantOf(user)
    registry = OntologyTermRegistry(_store())
    needle = str(query or "").strip().lower()

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
    from neurova.knowledge.foundation.admission import AdmissionError

    gate = productionAdmissionGate(_store())
    try:
        receipt = gate.admit(AdmissionRequest(
            agentId=agentId, tenantId=tenant,
            subjectLabel=str(subject_label or "").strip(),
            predicateTermId=str(predicate_term_id or "").strip(),
            objectTerm=str(object_term or "").strip(),
            content=content, evidenceText=str(evidence_text or ""),
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
