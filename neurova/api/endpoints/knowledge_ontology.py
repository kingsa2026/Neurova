"""本体类型系统读写面（S1 读 / S2 写）：图谱工作台调色板与编辑器的数据源。

这里不留第二份类型清单。术语的形状、父子、定义域/值域、基数、不相交与必填属性
全部由 `OntologyTermRegistry` 那一张表回答，规则由 `ForwardChainingEngine` 回答，
schema 版本由 `db_migration` 的版本域回答——前端拿到的是同一份事实源的一个视图。

值域有两种粒度并存：`range_terms` 逐个点名，`range_kinds` 按类别声明（`is_a` 就只说
"客体是 concept 这一类"）。读面把两者都如实带出，并额外给出**展开后**的
`range_terms_effective`——展开在读取时算，所以新登记一种概念不需要动 `is_a` 一行。

S2 开写面：术语/规则 CRUD、删除前影响面、变更留痕。判据全部在上游：
非法结构由注册表/规则引擎在写入处拒（端点只转 400），删除被引用术语在端点按
两处权威读数（registry.impactOf + engine.ruleReferences）裁 409，不许静默制造
悬空引用；每次写变更落 activity（操作人、动作、目标、依据），依据取调用方声明的
`basis`，不替调用方编一个。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, Path
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service
from neurova.api.deps import require_admin
from neurova.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()
from neurova.api.endpoints.knowledge_ontology_iri import router as _iriRouter
router.include_router(_iriRouter)


def _tenantOf(current_user: Dict[str, Any]) -> str:
    """操作者租户：本体读/写面的分区键（缺省 default）。"""
    return str(current_user.get("tenant_id") or "default")


def _schemaVersion() -> int:
    """schema 版本的唯一出处是版本域注册表，不在这里写死数字。"""
    from neurova.core.db_migration import latest_version
    from neurova.knowledge.foundation.narratives import NARRATIVE_DOMAIN

    return latest_version(NARRATIVE_DOMAIN)


def ontologySchemaData(tenantId: str = "default") -> Dict[str, Any]:
    """本体类型系统的读面数据（schema 端点与图谱 studio 共用的单一出处）。

    自 v25 起本体按租户分区：读面只报本租户的类型表；`tenant_scoped` 如实翻真。
    """
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    store = get_knowledge_fact_store()
    tenant = str(tenantId or "default")
    registry = OntologyTermRegistry(store)
    engine = ForwardChainingEngine(store)
    return {
        "terms": [
            {**t, "range_terms_effective": registry.rangeOf(t["term_id"], tenantId=tenant)}
            for t in registry.terms(tenantId=tenant)
        ],
        "rules": engine.rules(tenantId=tenant),
        "schema_version": _schemaVersion(),
        "tenant_scoped": True,
    }


def _termsView(registry: Any) -> List[Dict[str, Any]]:
    terms: List[Dict[str, Any]] = []
    for term in registry.terms():
        row = dict(term)
        # 声明形状留在 row 里不动；展开另起一个键，两者并存才说得清"值域从哪来"。
        row["range_terms_effective"] = registry.rangeOf(row["term_id"])
        terms.append(row)
    return terms


@router.get("/ontology/terms")
async def list_ontology_terms(
    limit: int = Query(100, ge=1, le=500),
    cursor: str = Query(""),
    fields: str = Query(""),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """术语列表（B12 L6）：cursor 键集分页 + fields 投影（缺省全字段兼容旧读数）。"""
    store, registry, _engine = _ontologyParts()
    tenant = _tenantOf(current_user)
    terms = sorted(registry.terms(tenantId=tenant), key=lambda t: t["term_id"])
    if cursor:
        terms = [t for t in terms if t["term_id"] > cursor]
    page = terms[:limit]
    nextCursor = page[-1]["term_id"] if len(terms) > limit else ""
    fieldsSet = {f.strip() for f in fields.split(",") if f.strip()} if fields else None
    if fieldsSet:
        page = [{k: v for k, v in t.items() if k in fieldsSet} for t in page]
    return {"code": 0, "message": "success",
            "data": {"items": page, "total": len(terms), "next_cursor": nextCursor}}


@router.get("/ontology/schema")
async def get_ontology_schema(
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """读取本体类型系统（术语 + 规则 + 版本）。只读；无写入口。"""

    # 与生产装配同款：类型判据的权威是注册表，拿不到就没有"这个类型合法吗"可答。
    return {
        "code": 0,
        "message": "success",
        "data": ontologySchemaData(_tenantOf(current_user)),
    }


@router.get("/ontology/quality")
async def getOntologyQualityReport(
    current_user: Dict = Depends(get_current_user_or_service),
):
    """本体质量报告（B13 L9，只读）：OOPS! 结构子集＋可计算指标。

    事实源是 `ontology/quality.py::ontologyQualityReport` 那一份计算，端点不自己
    数第二本账（教义第 6 条）。报告只覆盖**可计算**的形状缺陷（缺 label、孤儿类、
    逆关系单边、label 重复）；完整 OOPS!/OntoClean/OQuaRE 认证不在本仓承诺面
    （升级计划 §6 不纳入项），检索侧 NDCG/A-B 走 `/evaluation/*` 与 `/audit/*`。
    """
    from neurova.knowledge.ontology.quality import ontologyQualityReport

    store, _registry, _engine = _ontologyParts()
    return {"code": 0, "message": "success",
            "data": ontologyQualityReport(store, tenantId=_tenantOf(current_user))}


@router.get("/ontology/export.ttl")
async def export_ontology_turtle(
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    agent_id: Optional[str] = Query(
        default=None, description="只导该 agent 的事实段；缺省导本租户全部"),
):
    """全库 Turtle 导出（升级计划 B5，A4 标准栈互通面）：只读、按租户分区、治理面。

    导出的是 `ontology/turtle.py::serializeAll` 那一份文本，端点不自己拼第三份
    序列化（教义第 6 条）。**语法子集边界**（对外承诺面，与 docs/02-api 同条）：

    - 文档头固定 `@prefix kbg: <https://neurova.local/knowledge/>`；
    - 主语＝`kbg:<subject_key>`（IRI 安全的 ASCII 唯一键，不用中文标签，
      否则不同主体在 `iri()` 收字形时互相吞并）；
    - 谓词＝`kbg:<数据里的术语名>`，客体一律字符串字面量（**不出 IRI 客体、
      不出集合/匿名节点、不出 xsd 数据类型标记、不出 owl/rdf 模式词汇**）；
    - 事实段只收 `status='active' AND record_kind='triple'`：撤回态与叙述行不进导出；
    - 排序只来自固定 ORDER BY，时间戳与写入次序不进文本 ⇒ 同一库内容两次导出逐字节一致。

    互操作对拍（rdflib round-trip）是**可选测试**，产品侧零第三方依赖不变。
    """
    _requireAdmin(current_user)
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.turtle import serializeAll

    text = serializeAll(get_knowledge_fact_store(), tenantId=_tenantOf(current_user),
                        agentId=agent_id)
    # C1 字节级往返：响应头引用最近一次 RDF/XML 导入工件（单源＝ontology_artifacts，
    # 先按导出 agent 收窄，缺省回落本租户最近一次）
    from neurova.knowledge.foundation import get_knowledge_fact_store as _gkfs
    from neurova.knowledge.ontology.artifact_store import latestArtifact as _latestArtifact

    _store = _gkfs()
    _tenant = _tenantOf(current_user)
    latest = (_latestArtifact(_store, "rdf_import", tenantId=_tenant, agentId=agent_id or "")
              if agent_id else None) or _latestArtifact(_store, "rdf_import", tenantId=_tenant)
    headers = {}
    if latest is not None:
        headers["X-Original-Import-Sha256"] = latest["sha256"]
    return Response(content=text, media_type="text/turtle; charset=utf-8",
                    headers=headers)


@router.get("/ontology/export.jsonld")
async def export_ontology_jsonld(
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    agent_id: Optional[str] = Query(default=None),
):
    """JSON-LD 导出（B12 L7）：@context + @graph，逐字节确定。"""
    _requireAdmin(current_user)
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.export.jsonld import exportJsonLd

    text = exportJsonLd(get_knowledge_fact_store(), tenantId=_tenantOf(current_user),
                        agentId=agent_id or "")
    return Response(content=text, media_type="application/ld+json; charset=utf-8")


@router.get("/ontology/export.owl")
async def export_ontology_owl(
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    version: str = Query(default=""),
):
    """OWL 2 RL 可规则化公理导出（B12 L7）：互操作声明，不是运行时承诺。"""
    _requireAdmin(current_user)
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.export.owl import exportOwlAxioms

    text = exportOwlAxioms(get_knowledge_fact_store(), tenantId=_tenantOf(current_user),
                           version=version)
    return Response(content=text, media_type="text/turtle; charset=utf-8")


@router.get("/ontology/export.shacl")
async def export_ontology_shacl(
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """SHACL shapes 导出（B12 L7）：形状注册表镜像。"""
    _requireAdmin(current_user)
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.export.shacl import exportShaclShapes

    text = exportShaclShapes(get_knowledge_fact_store(), tenantId=_tenantOf(current_user))
    return Response(content=text, media_type="text/turtle; charset=utf-8")


@router.get("/ontology/export.prov")
async def export_ontology_prov(
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """PROV-O 导出（B12 L7）：assertions/activities/derivations。"""
    _requireAdmin(current_user)
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.export.prov import exportProv

    text = exportProv(get_knowledge_fact_store(), tenantId=_tenantOf(current_user))
    return Response(content=text, media_type="text/turtle; charset=utf-8")


# ── 形状注册表（B10 L4）──────────────────────────────────────

class ShapeWriteRequest(BaseModel):
    shape_id: str = ""
    target_kind: str
    target_term_id: str = ""
    path: Dict[str, Any] = Field(default_factory=dict)
    constraint_kind: str
    constraint: Dict[str, Any] = Field(default_factory=dict)
    severity: str = "violation"
    message: str = ""
    enabled: bool = True
    version: str = "v1"


def _shapeRegistry(store: Any):
    from neurova.knowledge.ontology.shapes import ShapeRegistry

    return ShapeRegistry(store)


@router.get("/ontology/domain-packs/{pack_id}/attribution")
async def get_domain_pack_attribution(
    pack_id: str = Path(...),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """C2：领域包归属卡（登录可读）——SHA-256/license/upstream/version/termCount。"""
    from neurova.knowledge.ontology.domain_pack import packAttribution

    try:
        card = packAttribution(pack_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"code": 0, "data": card, "request_id": ""}


@router.get("/ontology/domain-packs/{pack_id}/integrity")
async def verify_domain_pack_integrity(
    pack_id: str = Path(...),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """C2：领域包完整性校验（登录可读）——SHA-256 漂移显式报。"""
    from neurova.knowledge.ontology.domain_pack import verifyPackIntegrity

    try:
        result = verifyPackIntegrity(pack_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"code": 0, "data": result, "request_id": ""}


@router.get("/ontology/domain-packs")
async def list_domain_packs(
    current_user: Dict = Depends(get_current_user_or_service),
):
    """G5：可用领域包清单（概要）——前端概览卡片的选项源。"""
    from neurova.knowledge.ontology.domain_pack import availablePacks

    return {"code": 0, "data": availablePacks(), "request_id": ""}


@router.post("/ontology/domain-packs/{pack_id}/import")
async def import_domain_pack(
    request: Request,
    pack_id: str = Path(..., description="领域包标识"),
    current_user: Dict = Depends(require_admin()),
):
    """G5：导入领域包（仅管理员）——seedMissing 只补缺幂等；返回补上条数。"""
    from neurova.knowledge.ontology.domain_pack import importDomainPack

    store, registry, _engine = _ontologyParts()
    tenant = _tenantOf(current_user)
    try:
        added = importDomainPack(registry, pack_id, tenantId=tenant)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "未注册领域包" in str(exc) else 400,
                            detail=str(exc))
    # C2：领域包原始字节进不可变工件存储（content-addressed，漂移显式拒由
    # importDomainPack 的登记表把守，这里落的是工件层不可变版本）
    from neurova.knowledge.ontology.artifact_store import putArtifact
    from neurova.knowledge.ontology.domain_pack import packBytes

    artifact = putArtifact(store, "domain_pack", packBytes(pack_id),
                           sourceRef=pack_id, tenantId=tenant)
    _landActivity(store, "ontology_domain_pack_import", current_user, "import",
                  {"pack_id": pack_id, "added": added, "artifact_sha256": artifact["sha256"]}, "")
    return {"code": 0, "message": "success",
            "data": {"pack_id": pack_id, "added": added,
                     "artifact_sha256": artifact["sha256"],
                     "artifact_created": artifact["created"]},
            "request_id": getattr(request.state, "request_id", "")}


@router.get("/ontology/actions")
async def list_ontology_actions(
    risk_tier: Optional[str] = Query(default=None),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """A4：动作清单（登录可读）——Agent/前端查动作声明与风险档。"""
    from neurova.knowledge.ontology.action_registry import getActionRegistry

    store, _registry, _engine = _ontologyParts()
    tenant = _tenantOf(current_user)
    rows = getActionRegistry(store).list(tenantId=tenant, riskTier=risk_tier)
    return {"code": 0, "data": rows, "request_id": ""}


@router.post("/ontology/actions")
async def create_ontology_action(
    request: Request,
    body: Dict[str, Any],
    admin: Dict = Depends(require_admin()),
):
    """A4：登记动作（仅管理员）——bound_tool 悬空拒、risk_tier 闭集。"""
    from neurova.builtin_tools import get_registered_tool_names

    from neurova.knowledge.ontology.action_registry import getActionRegistry

    store, _registry, _engine = _ontologyParts()
    tenant = _tenantOf(admin)
    try:
        item = getActionRegistry(store).upsert(
            str(body.get("action_id") or ""), label=str(body.get("label") or ""),
            definition=str(body.get("definition") or ""),
            paramSchema=body.get("param_schema") or {},
            boundTool=str(body.get("bound_tool") or ""),
            riskTier=str(body.get("risk_tier") or "low"),
            enabled=bool(body.get("enabled", True)), tenantId=tenant,
            registeredTools=list(get_registered_tool_names()),
            # W4：动作语义三段（v45）——登记即校验（谓词在册/形状闭集）
            precondition=body.get("precondition") or {},
            impact=body.get("impact") or [],
            stateChange=body.get("state_change") or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "data": item, "request_id": ""}


@router.delete("/ontology/actions/{action_id}")
async def delete_ontology_action(
    action_id: str = Path(...),
    admin: Dict = Depends(require_admin()),
):
    """A4：删除动作（仅管理员）。"""
    from neurova.knowledge.ontology.action_registry import getActionRegistry

    store, _registry, _engine = _ontologyParts()
    tenant = _tenantOf(admin)
    if not getActionRegistry(store).drop(action_id, tenantId=tenant):
        raise HTTPException(status_code=404, detail=f"动作未登记: {action_id}")
    return {"code": 0, "data": {"action_id": action_id}, "request_id": ""}


@router.get("/ontology/functions")
async def list_ontology_functions(
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W2：函数清单（登录可读）——表达式/物化档/启用态读数。"""
    from neurova.knowledge.ontology.function_registry import FunctionRegistry

    store, _registry, _engine = _ontologyParts()
    tenant = _tenantOf(current_user)
    rows = FunctionRegistry(store).list(tenantId=tenant, includeDisabled=True)
    return {"code": 0, "data": rows, "request_id": ""}


@router.post("/ontology/functions")
async def create_ontology_function(
    body: Dict[str, Any],
    admin: Dict = Depends(require_admin()),
):
    """W2：登记函数（仅管理员）——登记即编译（白名单外节点/未知符号/越界谓词
    400 原样回显），output_predicate 须在注册表（B-10）。"""
    from neurova.knowledge.ontology.function_registry import FunctionRegistry

    store, _registry, _engine = _ontologyParts()
    tenant = _tenantOf(admin)
    try:
        item = FunctionRegistry(store).register(
            functionId=str(body.get("function_id") or ""), tenantId=tenant,
            exprText=str(body.get("expr_text") or ""),
            outputPredicate=str(body.get("output_predicate") or ""),
            inputBindings=body.get("input_bindings") or {},
            scope=body.get("scope") or {},
            materialization=str(body.get("materialization") or "observe"),
            label=str(body.get("label") or ""),
            definition=str(body.get("definition") or ""),
            enabled=bool(body.get("enabled", True)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "data": item, "request_id": ""}


@router.post("/ontology/functions/{function_id}/compute")
async def compute_ontology_function(
    function_id: str = Path(...),
    body: Dict[str, Any] = None,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W2：函数 dry 求值（登录可读，只读零落库）——与 MCP ontology_compute
    同一 FunctionEngine.dryEval 单源；selector 超行上限结构化拒绝（D1）。"""
    from neurova.knowledge.ontology.function_engine import FunctionEngine

    store, _registry, _engine = _ontologyParts()
    payload = body or {}
    try:
        result = FunctionEngine(store).dryEval(
            function_id, subject=str(payload.get("subject") or ""),
            tenantId=_tenantOf(current_user))
    except LookupError:
        raise HTTPException(status_code=404, detail=f"函数未登记: {function_id}")
    if result.get("rejected"):
        return {"code": 0, "data": result, "request_id": ""}
    return {"code": 0, "data": result, "request_id": ""}


@router.delete("/ontology/functions/{function_id}")
async def delete_ontology_function(
    function_id: str = Path(...),
    admin: Dict = Depends(require_admin()),
):
    """W2：删函数（仅管理员）——按源撤回其全部结论（derivation_ledger 单源）。"""
    from neurova.knowledge.ontology.function_registry import FunctionRegistry

    store, _registry, _engine = _ontologyParts()
    tenant = _tenantOf(admin)
    try:
        FunctionRegistry(store).delete(function_id, tenantId=tenant)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"函数未登记: {function_id}")
    return {"code": 0, "data": {"function_id": function_id}, "request_id": ""}


@router.get("/ontology/state-machines")
async def list_state_machines(
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W3：状态机清单（登录可读）——states/transitions/event_bindings 读数。"""
    from neurova.knowledge.ontology.state_machine_registry import StateMachineRegistry

    store, _registry, _engine = _ontologyParts()
    tenant = _tenantOf(current_user)
    rows = StateMachineRegistry(store).list(tenantId=tenant, includeDisabled=True)
    return {"code": 0, "data": rows, "request_id": ""}


@router.post("/ontology/state-machines")
async def create_state_machine(
    body: Dict[str, Any],
    admin: Dict = Depends(require_admin()),
):
    """W3：登记状态机（仅管理员）——闭集校验（states 外名字登记即拒）。"""
    from neurova.knowledge.ontology.state_machine_registry import StateMachineRegistry

    store, _registry, _engine = _ontologyParts()
    tenant = _tenantOf(admin)
    try:
        item = StateMachineRegistry(store).register(
            termId=str(body.get("term_id") or ""), tenantId=tenant,
            states=body.get("states") or [],
            transitions=body.get("transitions") or [],
            initialState=str(body.get("initial_state") or ""),
            eventBindings=body.get("event_bindings") or [],
            enabled=bool(body.get("enabled", True)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "data": item, "request_id": ""}


@router.get("/ontology/webhook/config")
async def get_webhook_config(
    current_user: Dict = Depends(get_current_user_or_service),
):
    """U5：webhook 接收面读数——enabled＋密钥指纹（SHA-256 前缀掩码，绝不回明文）。"""
    import hashlib
    import os

    from neurova.knowledge.enterprise.webhook_receiver import (
        WEBHOOK_ENV,
        WEBHOOK_SECRET_ENV,
        webhookEnabled,
    )

    secret = os.environ.get(WEBHOOK_SECRET_ENV, "")
    fingerprint = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12] if secret else ""
    return {"code": 0,
            "data": {"enabled": webhookEnabled(), "secret_env": WEBHOOK_SECRET_ENV,
                     "enabled_env": WEBHOOK_ENV, "secret_fingerprint": fingerprint},
            "request_id": ""}


@router.post("/ontology/webhook/rotate")
async def rotate_webhook_secret(
    admin: Dict = Depends(require_admin()),
):
    """U5：签名密钥轮换（admin）——进程内 env 指针写新随机值，回新指纹。

    部署面的持久化仍走环境变量指针（凭据不进库不进前端，AGENTS.md §3 同源）。
    """
    import hashlib
    import os
    import secrets

    from neurova.knowledge.enterprise.webhook_receiver import WEBHOOK_SECRET_ENV

    newSecret = secrets.token_hex(32)
    os.environ[WEBHOOK_SECRET_ENV] = newSecret
    fingerprint = hashlib.sha256(newSecret.encode("utf-8")).hexdigest()[:12]
    return {"code": 0, "data": {"secret_fingerprint": fingerprint}, "request_id": ""}


@router.post("/ontology/webhook/simulate")
async def simulate_webhook_push(
    body: Dict[str, Any],
    current_user: Dict = Depends(get_current_user_or_service),
):
    """U5：模拟推送三态——ok / duplicate（同幂等键二次推送零二次写）/
    bad_signature（坏签名拒收）。回执是接收器原话（含诚实拒绝），不加工。"""
    import json
    import os
    import time
    import uuid

    from neurova.knowledge.enterprise.webhook_receiver import (
        WEBHOOK_SECRET_ENV,
        WebhookReceiver,
        computeSignature,
    )
    from neurova.knowledge.foundation import get_knowledge_fact_store

    mode = str(body.get("mode") or "ok")
    if mode not in ("ok", "duplicate", "bad_signature"):
        raise HTTPException(status_code=400,
                            detail=f"mode 须为 ok/duplicate/bad_signature，得到 {mode!r}")
    secret = os.environ.get(WEBHOOK_SECRET_ENV, "")
    store = get_knowledge_fact_store()
    receiver = WebhookReceiver(store, secret=secret, sourceId="sim:webhook",
                               agentId="default", tenantId=_tenantOf(current_user))
    payload = json.dumps({
        "idempotency_key": "sim-" + uuid.uuid4().hex,
        "subject": "模拟主体", "predicate": "is_a", "object": "concept",
    }, ensure_ascii=False).encode("utf-8")
    ts = int(time.time())
    signature = computeSignature(payload, ts, secret)
    if mode == "bad_signature":
        signature = "0" * 64 if signature[0] != "0" else "1" * 64
    first = receiver.handle(payload, ts, signature)
    result: Dict[str, Any] = {"mode": mode, "first": first}
    if mode == "duplicate":
        # 同一幂等键立即重推：去重面应答"零二次写"
        result["second"] = receiver.handle(payload, ts, signature)
    return {"code": 0, "data": result, "request_id": ""}


@router.get("/ontology/webhook/dedup-stats")
async def get_webhook_dedup_stats(
    current_user: Dict = Depends(get_current_user_or_service),
):
    """U5：幂等去重台账读数（行数＋源数）——表随 v49 步就绪，未消费即 0。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.foundation.foundation_schema import applyTo

    store = get_knowledge_fact_store()
    with store._lock:
        applyTo(store._conn)
        row = store._conn.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT source_id) AS s"
            " FROM enterprise_webhook_dedup").fetchone()
    return {"code": 0, "data": {"rows": row["n"], "sources": row["s"]},
            "request_id": ""}


@router.get("/ontology/blocking-stats")
async def get_blocking_stats(
    agent_id: str = Query(default="default", description="图谱所属 agent"),
    node_limit: int = Query(default=500, ge=1, le=2000, alias="nodeLimit"),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """U3 消解队列 blocking 读数（登录可读）：候选对数/全对数对比。

    节点源与消解队列同源（KnowledgeGraphManager per-agent，教义第 6 条），
    不另造第二份节点读取。
    """
    from neurova.api.endpoints.knowledge_graph_api import _get_kg_manager
    from neurova.knowledge.resolution import candidatePairsBlocking, candidatePairsFullScan

    manager = _get_kg_manager(str(agent_id or "default"), _tenantOf(current_user))
    nodes = (list(manager._nodes.values())[:max(1, min(int(node_limit), 2000))]
             if manager is not None else [])
    full = candidatePairsFullScan(nodes)
    blocked = candidatePairsBlocking(nodes)
    return {"code": 0, "data": {"full_scan": len(full), "blocking": len(blocked),
                                "reduction_pct": round((1 - len(blocked) / max(len(full), 1)) * 100)},
            "request_id": ""}


@router.get("/ontology/conflict-policy/{term_id}")
async def get_conflict_policy(
    term_id: str = Path(...),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """U3 冲突队列 conflict_policy 声明读数（登录可读）。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    store = get_knowledge_fact_store()
    term = OntologyTermRegistry(store).term(term_id, tenantId=_tenantOf(current_user))
    if term is None:
        raise HTTPException(status_code=404, detail=f"术语未登记: {term_id}")
    return {"code": 0, "data": {"term_id": term_id,
                                "conflict_policy": term.get("conflict_policy") or "default"},
            "request_id": ""}


@router.get("/ontology/accountability")
async def query_ontology_accountability(
    subject: Optional[str] = Query(default=None),
    actor: Optional[str] = Query(default=None),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    current_user: Dict = Depends(require_admin()),
):
    """W12：跨五账聚合追责查询（仅管理员，只读）——两个记账主体如实标注。"""
    from neurova.knowledge.ontology.accountability import accountabilityQuery

    store, _registry, _engine = _ontologyParts()
    result = accountabilityQuery(store, subject=subject, actor=actor,
                                 timeWindowStart=start, timeWindowEnd=end,
                                 tenantId=_tenantOf(current_user))
    return {"code": 0, "data": result, "request_id": ""}


@router.post("/ontology/decisions")
async def create_ontology_decision(
    body: Dict[str, Any],
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W7：决策登记（登录可写，身份按请求边界 sender）。"""
    from neurova.knowledge.ontology.decision_ledger import DecisionLedger

    store, _registry, _engine = _ontologyParts()
    try:
        row = DecisionLedger(store).recordDecision(
            tenantId=_tenantOf(current_user),
            category=str(body.get("category") or ""),
            scenario=str(body.get("scenario") or ""),
            reasoning=str(body.get("reasoning") or ""),
            outcome=str(body.get("outcome") or ""),
            confidence=float(body.get("confidence", 0.5)),
            decisionMaker=str(current_user.get("username") or ""),
            ownerId=str(body.get("owner_id") or current_user.get("user_id") or ""),
            metadata=body.get("metadata") or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "data": row, "request_id": ""}


@router.get("/ontology/decisions")
async def list_ontology_decisions(
    limit: int = Query(default=50, le=200),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W7：决策清单（登录可读，租户隔离）。"""
    from neurova.knowledge.ontology.decision_ledger import DecisionLedger

    store, _registry, _engine = _ontologyParts()
    rows = DecisionLedger(store).list(tenantId=_tenantOf(current_user), limit=limit)
    return {"code": 0, "data": rows, "request_id": ""}


@router.post("/ontology/decisions/{decision_id}/links")
async def link_ontology_decisions(
    decision_id: str = Path(...),
    body: Dict[str, Any] = None,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W7：决策链接（caused/influenced/precedent 闭集；无环硬校验）。"""
    from neurova.knowledge.ontology.decision_ledger import DecisionLedger

    store, _registry, _engine = _ontologyParts()
    payload = body or {}
    try:
        row = DecisionLedger(store).linkDecisions(
            decision_id, str(payload.get("target_decision_id") or ""),
            str(payload.get("link_kind") or ""),
            tenantId=_tenantOf(current_user),
            createdBy=str(current_user.get("username") or ""))
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "data": row, "request_id": ""}


@router.get("/ontology/decisions/{decision_id}/trace")
async def trace_ontology_decision(
    decision_id: str = Path(...),
    direction: str = Query(default="both"),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W7：因果链读数（影响图＝下游闭包，不建独立引擎）。"""
    from neurova.knowledge.ontology.decision_ledger import DecisionLedger

    store, _registry, _engine = _ontologyParts()
    chain = DecisionLedger(store).traceDecisionChain(
        decision_id, direction=direction, tenantId=_tenantOf(current_user))
    return {"code": 0, "data": {"decision_id": decision_id,
                                "direction": direction, "chain": chain},
            "request_id": ""}


@router.get("/ontology/decisions/precedents")
async def search_decision_precedents(
    q: str = Query(default=""),
    limit: int = Query(default=5, le=50),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W7：判例检索（词法混合计分——嵌入接入前承载，偏差登记台账）。"""
    from neurova.knowledge.ontology.decision_ledger import DecisionLedger

    store, _registry, _engine = _ontologyParts()
    hits = DecisionLedger(store).findPrecedents(
        q, limit=limit, tenantId=_tenantOf(current_user))
    return {"code": 0, "data": hits, "request_id": ""}


@router.post("/ontology/simulations")
async def run_ontology_simulation(
    body: Dict[str, Any],
    admin: Dict = Depends(require_admin()),
):
    """W5：运行推演（仅管理员）——生产零写（台账追加除外），diff 报告回执。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.simulation import ScopeTooLargeError, runSimulation

    store = get_knowledge_fact_store()
    tenant = _tenantOf(admin)
    scope = dict(body.get("scope") or {})
    scope.setdefault("tenantId", tenant)
    scope.setdefault("agentId", str(body.get("agent_id") or "default"))
    try:
        report = runSimulation(store, scope=scope,
                               hypotheses=body.get("hypotheses") or {})
    except ScopeTooLargeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "data": report, "request_id": ""}


@router.get("/ontology/chunk-strategies")
async def list_chunk_strategies(
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W8：切块策略清单（登录可读，preview 选择器的服务端名册）。"""
    from neurova.knowledge.chunk_dispatch import ChunkStrategyRegistry

    store, _registry, _engine = _ontologyParts()
    rows = ChunkStrategyRegistry(store).list(tenantId=_tenantOf(current_user))
    return {"code": 0, "data": rows, "request_id": ""}


@router.post("/ontology/chunk-strategies")
async def create_chunk_strategy(
    body: Dict[str, Any],
    admin: Dict = Depends(require_admin()),
):
    """W8：登记切块策略（仅管理员，十三 kind 闭集；非法参数 400）。"""
    from neurova.knowledge.chunk_dispatch import ChunkStrategyRegistry

    store, _registry, _engine = _ontologyParts()
    try:
        row = ChunkStrategyRegistry(store).register(
            strategyId=str(body.get("strategy_id") or ""),
            tenantId=_tenantOf(admin), kind=str(body.get("kind") or ""),
            params=body.get("params") or {},
            enabled=bool(body.get("enabled", True)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "data": row, "request_id": ""}


@router.delete("/ontology/chunk-strategies/{strategy_id}")
async def delete_chunk_strategy(
    strategy_id: str = Path(...),
    admin: Dict = Depends(require_admin()),
):
    """W8：删切块策略（仅管理员）。"""
    from neurova.knowledge.chunk_dispatch import ChunkStrategyRegistry

    store, _registry, _engine = _ontologyParts()
    if not ChunkStrategyRegistry(store).delete(strategy_id, tenantId=_tenantOf(admin)):
        raise HTTPException(status_code=404, detail=f"策略未登记: {strategy_id}")
    return {"code": 0, "data": {"strategy_id": strategy_id}, "request_id": ""}


@router.get("/ontology/export.graphml")
async def export_ontology_graphml(
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    agent_id: Optional[str] = Query(default=None),
):
    """W11：GraphML 导出（管理员）——与既有五格式同族，确定性序列化。"""
    _requireAdmin(current_user)
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.export.graph_exchange import exportGraphML

    text = exportGraphML(get_knowledge_fact_store(),
                         tenantId=_tenantOf(current_user), agentId=agent_id)
    return Response(content=text, media_type="application/graphml+xml; charset=utf-8")


@router.get("/ontology/export.gexf")
async def export_ontology_gexf(
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    agent_id: Optional[str] = Query(default=None),
):
    """W11：GEXF 导出（管理员）。"""
    _requireAdmin(current_user)
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.export.graph_exchange import exportGexf

    text = exportGexf(get_knowledge_fact_store(),
                      tenantId=_tenantOf(current_user), agentId=agent_id)
    return Response(content=text, media_type="application/gexf+xml; charset=utf-8")


@router.get("/ontology/export.cypher")
async def export_ontology_cypher(
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    agent_id: Optional[str] = Query(default=None),
):
    """W11：Cypher dump 导出（管理员，外部图库自行导入）。"""
    _requireAdmin(current_user)
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.export.graph_exchange import exportCypher

    text = exportCypher(get_knowledge_fact_store(),
                        tenantId=_tenantOf(current_user), agentId=agent_id)
    return Response(content=text, media_type="text/plain; charset=utf-8")


@router.get("/ontology/export.csv")
async def export_ontology_csv(
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    agent_id: Optional[str] = Query(default=None),
):
    """W11：CSV 节点/边导出（管理员）。"""
    _requireAdmin(current_user)
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.export.graph_exchange import exportCsv

    text = exportCsv(get_knowledge_fact_store(),
                     tenantId=_tenantOf(current_user), agentId=agent_id)
    return Response(content=text, media_type="text/csv; charset=utf-8")


@router.post("/ontology/sparql")
async def run_ontology_sparql(
    body: Dict[str, Any],
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W9：SPARQL 只读查询（登录可读；rdflib 未装显式 501 not_supported）。"""
    from neurova.knowledge.ontology.sparql_query import (
        SparqlNotSupported,
        runSparqlQuery,
    )

    store, _registry, _engine = _ontologyParts()
    try:
        result = runSparqlQuery(store, str(body.get("query") or ""),
                                agentId=str(current_user.get("agent_id") or "default"),
                                tenantId=_tenantOf(current_user))
    except SparqlNotSupported as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "data": result, "request_id": ""}


@router.get("/ontology/artifacts")
async def list_ontology_artifacts(
    kind: Optional[str] = Query(default=None, description="工件种类闭集过滤"),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """C2：工件清单（元数据＋SHA-256 引用，不含字节）——按哈希引用的读数面。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.artifact_store import listArtifacts

    rows = listArtifacts(get_knowledge_fact_store(), kind=kind,
                         tenantId=_tenantOf(current_user), limit=limit)
    return {"code": 0, "data": rows, "request_id": ""}


@router.get("/ontology/artifacts/{sha256}/content")
async def get_ontology_artifact_content(
    sha256: str = Path(..., description="工件 SHA-256（内容地址）"),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """C1/C2：按哈希读工件原始字节（读时校验——损坏显式 500，不静默换字）。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.artifact_store import getArtifact

    content = getArtifact(get_knowledge_fact_store(), sha256)
    if content is None:
        raise HTTPException(status_code=404, detail=f"工件未登记: {sha256[:16]}")
    return Response(content=content, media_type="application/octet-stream",
                    headers={"X-Artifact-Sha256": sha256})


@router.get("/ontology/artifacts/{sha256}/verify")
async def verify_ontology_artifact(
    sha256: str = Path(...),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """C2：工件完整性核验（ok/drift/missing）——读数不是修复。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.artifact_store import verifyArtifact

    return {"code": 0, "data": verifyArtifact(get_knowledge_fact_store(), sha256),
            "request_id": ""}


@router.get("/ontology/import-artifact/latest")
async def get_latest_import_artifact(
    current_user: Dict = Depends(get_current_user_or_service),
    agent_id: Optional[str] = Query(default=None),
):
    """C1 字节级往返读数面：最近一次 RDF/XML 导入的原始字节（逐字节原样）。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.artifact_store import latestArtifact

    store = get_knowledge_fact_store()
    tenant = _tenantOf(current_user)
    latest = (latestArtifact(store, "rdf_import", tenantId=tenant, agentId=agent_id or "")
              if agent_id else None) or latestArtifact(store, "rdf_import", tenantId=tenant)
    if latest is None:
        raise HTTPException(status_code=404, detail="尚无 RDF/XML 导入工件")
    return Response(content=latest["content"], media_type="application/octet-stream",
                    headers={"X-Original-Import-Sha256": latest["sha256"]})


@router.post("/ontology/import-rdf")
async def import_ontology_rdf(
    request: Request,
    current_user: Dict = Depends(require_admin()),
):
    """C1：RDF/XML 导入（管理员，inert 姿态——不执行 SHACL/OWL；原始字节保留）。
    DOCTYPE/ENTITY 拒／资源上限超限拒／rdflib 未装 501。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.rdf_import import (
        RdfImportLimitError,
        RdfImportNotSupported,
        RdfImportSecurityError,
        importRdfXml,
    )

    body = await request.body()
    store = get_knowledge_fact_store()
    try:
        result = importRdfXml(body, agentId=str(current_user.get("agent_id") or "default"),
                              tenantId=_tenantOf(current_user))
    except RdfImportSecurityError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RdfImportLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RdfImportNotSupported as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # C1：原始字节进不可变工件存储（content-addressed，write-once）
    from neurova.knowledge.ontology.artifact_store import putArtifact

    artifact = putArtifact(store, "rdf_import", result.original_bytes,
                           sourceRef="import-rdf", tenantId=_tenantOf(current_user),
                           agentId=str(current_user.get("agent_id") or "default"))
    return {
        "code": 0,
        "data": {
            "triple_count": result.triple_count,
            "inert": result.inert,
            "unsupported_count": len(result.unsupported),
            "unsupported": result.unsupported[:20],
            "original_bytes": len(result.original_bytes),
            "sha256": result.sha256,
            "artifact_sha256": artifact["sha256"],
            "artifact_created": artifact["created"],
        },
        "request_id": "",
    }


@router.post("/ontology/abduce")
async def run_ontology_abduce(
    body: Dict[str, Any],
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W9：溯因反向搜索（登录可读，只读零写）。"""
    from neurova.knowledge.ontology.abduction import explainGoal

    store, _registry, _engine = _ontologyParts()
    result = explainGoal(store,
                         subjectLabel=str(body.get("subject_label") or ""),
                         predicate=str(body.get("predicate") or ""),
                         objectTerm=str(body.get("object_term") or ""),
                         agentId=str(current_user.get("agent_id") or "default"),
                         tenantId=_tenantOf(current_user))
    return {"code": 0, "data": result, "request_id": ""}


@router.post("/ontology/community-search")
async def search_ontology_community(
    body: Dict[str, Any],
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W8：社区检索（登录可读）——global/drift 两种模式。"""
    from neurova.knowledge.community_graph import (
        communityDriftSearch,
        communityGlobalSearch,
    )

    store, _registry, _engine = _ontologyParts()
    agentId = str(current_user.get("agent_id") or "default")
    tenant = _tenantOf(current_user)
    query = str(body.get("query") or "")
    mode = str(body.get("mode") or "global")
    limit = int(body.get("limit") or 5)
    if mode == "global":
        hits = communityGlobalSearch(store, query, agentId=agentId,
                                     tenantId=tenant, limit=limit)
    elif mode == "drift":
        hits = communityDriftSearch(store, query, agentId=agentId,
                                    tenantId=tenant, limit=limit)
    else:
        raise HTTPException(status_code=400, detail="mode 只支持 global|drift")
    return {"code": 0, "data": hits, "request_id": ""}


@router.post("/ontology/communities/detect")
async def detect_ontology_communities(
    current_user: Dict = Depends(require_admin()),
):
    """W8：社区检测手动触发（管理员）——标签传播＋持久化，返回社区行清单。

    检测缺省 off（读数面只出不进），本端点是唯一手动入口；摄取后增量另计。
    """
    from neurova.knowledge.community_graph import CommunityGraphBuilder

    store, _registry, _engine = _ontologyParts()
    rows = CommunityGraphBuilder(store, agentId=str(current_user.get("agent_id") or "default"),
                                 tenantId=_tenantOf(current_user)).detect()
    return {"code": 0, "data": rows, "request_id": ""}


@router.get("/ontology/communities")
async def list_ontology_communities(
    current_user: Dict = Depends(get_current_user_or_service),
):
    """W8：社区读数（登录可读；检测手动触发/摄取后增量，缺省 off）。"""
    from neurova.knowledge.community_graph import CommunityGraphBuilder

    store, _registry, _engine = _ontologyParts()
    rows = CommunityGraphBuilder(store, agentId=str(current_user.get("agent_id") or "default"),
                                 tenantId=_tenantOf(current_user)).loadCommunities()
    return {"code": 0, "data": rows, "request_id": ""}


@router.get("/ontology/simulations")
async def list_ontology_simulations(
    limit: int = Query(default=50, le=200),
    current_user: Dict = Depends(require_admin()),
):
    """W5：推演台账（仅管理员，只读）——scope/假设/diff 摘要读数。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store

    store = get_knowledge_fact_store()
    tenant = _tenantOf(current_user)
    with store._lock:
        rows = store._conn.execute(
            "SELECT simulation_id, agent_id, scope_json, hypothesis_json,"
            " diff_summary_json, created_at FROM ontology_simulations"
            " WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
            (tenant, int(limit))).fetchall()
    import json as _json

    items = []
    for row in rows:
        items.append({
            "simulation_id": str(row["simulation_id"]),
            "agent_id": str(row["agent_id"]),
            "scope": _json.loads(row["scope_json"] or "{}"),
            "hypotheses": _json.loads(row["hypothesis_json"] or "[]"),
            "diff_summary": _json.loads(row["diff_summary_json"] or "{}"),
            "created_at": str(row["created_at"]),
        })
    return {"code": 0, "data": items, "request_id": ""}


@router.delete("/ontology/state-machines/{term_id}")
async def delete_state_machine(
    term_id: str = Path(...),
    admin: Dict = Depends(require_admin()),
):
    """W3：删状态机（仅管理员）；存量 has_state 事实不动（迁移约束随机器退场）。"""
    from neurova.knowledge.ontology.state_machine_registry import StateMachineRegistry

    store, _registry, _engine = _ontologyParts()
    tenant = _tenantOf(admin)
    if not StateMachineRegistry(store).delete(term_id, tenantId=tenant):
        raise HTTPException(status_code=404, detail=f"状态机未登记: {term_id}")
    return {"code": 0, "data": {"term_id": term_id}, "request_id": ""}


@router.get("/ontology/namespaces")
async def list_ontology_namespaces(
    current_user: Dict = Depends(get_current_user_or_service),
):
    """G4：可用 IRI 命名空间注册表（前缀 → 基座）——术语表单下拉与领域包导入的
    选项源；空 namespace 语义（缺省 kbg:）由前端固定项表达，不进注册表。"""
    from neurova.knowledge.ontology.term_registry import NAMESPACE_REGISTRY

    return {"code": 0, "data": dict(NAMESPACE_REGISTRY), "request_id": ""}


@router.get("/ontology/shapes")
async def list_ontology_shapes(
    request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    enabled_only: bool = Query(default=False),
):
    """形状列表（B10 L4）：只读，按租户分区。"""
    store, _, _ = _ontologyParts()
    shapes = _shapeRegistry(store).list(
        tenantId=_tenantOf(current_user), enabledOnly=bool(enabled_only))
    return {"code": 0, "message": "success",
            "data": {"items": shapes, "total": len(shapes)}}


@router.post("/ontology/shapes")
async def create_ontology_shape(
    body: ShapeWriteRequest, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """登记形状（B10 L4）：与内置 6 项校验撞车即拒；写前/dry-run 同求值器。"""
    _requireAdmin(current_user)
    store, _, _ = _ontologyParts()
    shapeId = str(body.shape_id or "").strip()
    if not shapeId:
        raise HTTPException(status_code=400, detail="shape_id 不能为空")
    try:
        shape = _shapeRegistry(store).register(
            _tenantOf(current_user), shapeId, body.target_kind, body.constraint_kind,
            body.constraint, pathJson=body.path, targetTermId=body.target_term_id,
            severity=body.severity, message=body.message, enabled=body.enabled,
            version=body.version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    activityId = _landActivity(store, "ontology_shape_write", current_user, "create",
                               {"shape_id": shapeId}, body.message)
    return {"code": 0, "message": "success",
            "data": {"shape": shape, "activity_id": activityId}}


@router.put("/ontology/shapes/{shape_id}")
async def update_ontology_shape(
    shape_id: str, body: ShapeWriteRequest, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """更新形状（B10 L4）：不存在 404；不允许 PUT 静默新建。"""
    _requireAdmin(current_user)
    store, _, _ = _ontologyParts()
    tenant = _tenantOf(current_user)
    registry = _shapeRegistry(store)
    shapeId = str(shape_id or "").strip()
    if not registry.get(shapeId, tenantId=tenant):
        raise HTTPException(status_code=404, detail="形状不存在: %s" % shapeId)
    try:
        shape = registry.register(
            tenant, shapeId, body.target_kind, body.constraint_kind,
            body.constraint, pathJson=body.path, targetTermId=body.target_term_id,
            severity=body.severity, message=body.message, enabled=body.enabled,
            version=body.version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    activityId = _landActivity(store, "ontology_shape_write", current_user, "update",
                               {"shape_id": shapeId}, body.message)
    return {"code": 0, "message": "success",
            "data": {"shape": shape, "activity_id": activityId}}


@router.delete("/ontology/shapes/{shape_id}")
async def delete_ontology_shape(
    shape_id: str, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    basis: str = Query(default=""),
):
    """删除形状（B10 L4）：不存在 404。"""
    _requireAdmin(current_user)
    store, _, _ = _ontologyParts()
    registry = _shapeRegistry(store)
    shapeId = str(shape_id or "").strip()
    if not registry.get(shapeId, tenantId=_tenantOf(current_user)):
        raise HTTPException(status_code=404, detail="形状不存在: %s" % shapeId)
    registry.delete(shapeId, tenantId=_tenantOf(current_user))
    activityId = _landActivity(store, "ontology_shape_write", current_user, "delete",
                               {"shape_id": shapeId}, basis)
    return {"code": 0, "message": "success", "data": {"activity_id": activityId}}


# ── S2 写面 ──────────────────────────────────────────────────


class TermWriteRequest(BaseModel):
    term_id: str = ""
    kind: str
    label: str = ""
    parent_term_id: Optional[str] = None
    # 未提供（None）在 PUT 里意味着"保留现值"；显式空列表才是"清空声明"。
    domain: Optional[List[str]] = None
    range_terms: Optional[List[str]] = None
    range_kinds: Optional[List[str]] = None
    cardinality: Optional[int] = None
    disjoint_with: Optional[List[str]] = None
    required_props: Optional[List[str]] = None
    # B8 关系映射：关系特征/别名/外部 IRI/退役语义。None = PUT 保留现值。
    inverse_of: Optional[str] = None
    symmetric: Optional[bool] = None
    transitive: Optional[bool] = None
    aliases: Optional[List[str]] = None
    # G3 结构化列表：[{"kind": EXTERNAL_IRI_KINDS 闭集, "iri": IRI}]（校验在注册表）
    external_iris: Optional[List[Dict[str, str]]] = None
    # G1：定义描述项（表 1/表 2 第 4 项）；None = PUT 保留现值
    definition: Optional[str] = None
    # G2：数据属性基本类型（5.5 表 3 闭集，仅 property 可声明）；None = PUT 保留现值
    datatype: Optional[str] = None
    # G4：IRI 命名空间（NAMESPACE_REGISTRY 闭集；空 = 缺省 kbg:）；None = PUT 保留现值
    namespace: Optional[str] = None
    deprecated: Optional[bool] = None
    replaced_by: Optional[str] = None
    # B10 L2 / B11 L3：SKOS 多语言标签、模块归属、身份判据、限定关系 schema。
    # 与上面同一口径：None = PUT 保留现值，显式空容器才是清空声明。
    labels: Optional[Dict[str, str]] = None
    alt_labels: Optional[Dict[str, list]] = None
    module: Optional[str] = None
    identity_keys: Optional[List[str]] = None
    qualifier_schema: Optional[Dict[str, Any]] = None
    version: Optional[str] = None
    basis: str = ""


class RuleWriteRequest(BaseModel):
    rule_id: str = ""
    head_predicate: str
    head_subject_var: Optional[str] = None
    # 条件类（升级计划 B1）：head 客体常量非空 ⇒ 形状是 conjunction（X is_a 该类）。
    # 留空 = 既有 relay 语义，存量调用方一位不改。
    head_object_const: Optional[str] = None
    # B8：显式形状（relay/conjunction/inverse）；缺省按 head_object_const 推断。
    # inverse 要求 head 主语变元 = 正原子客体变元（X A Y ⇒ Y <head> X）。
    shape: Optional[str] = None
    body: Optional[List[Dict[str, Any]]] = None
    enabled: Optional[bool] = None
    version: Optional[str] = None
    # v35 物化档位：observe（缺省，不进主路）/ enforce（灰度 off 也进主路）
    materialization: Optional[str] = None
    basis: str = ""


def _requireAdmin(current_user: Dict[str, Any]) -> None:
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(
            status_code=403, detail="本体写面是治理动作，仅管理员可执行")


def _ontologyParts():
    """写面装配：与读面同款三件套，一次拿齐不留第二套装配点。

    引擎必须带**咽喉工厂**：条件类规则登记即求值，推导结论要落库只能走 admit——
    裸造引擎时这条路径当场 400（"推理未接咽喉写入口"），于是"REST 能登记条件类规则"
    只在库里没有匹配事实时成立，一旦有匹配就坏。与生产装配（`admission.py` 里
    种子规则那一处）同形态，不另造第二条推导写入口。
    """
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.foundation.admission import productionAdmissionGate
    from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    store = get_knowledge_fact_store()
    return (store, OntologyTermRegistry(store),
            ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(st)))


def _landActivity(store: Any, kind: str, actor: Dict[str, Any], action: str,
                  target: Dict[str, Any], basis: str) -> str:
    """变更留痕：操作人、动作、目标、依据（调用方没写就如实空着，不代编）。"""
    return store.insertActivity(
        kind,
        inputs={
            "actor": str(actor.get("user_id") or ""),
            "actor_name": str(actor.get("username") or ""),
            "action": action,
            **target,
        },
        basis=str(basis or ""),
        tenantId=str(actor.get("tenant_id") or "default"),
    )


def _registerTerm(registry: Any, termId: str, body: TermWriteRequest,
                  tenantId: str) -> Dict[str, Any]:
    return registry.register(
        termId, body.kind, label=body.label, parentTermId=body.parent_term_id,
        domain=body.domain, rangeTerms=body.range_terms, rangeKinds=body.range_kinds,
        cardinality=body.cardinality, disjointWith=body.disjoint_with,
        requiredProps=body.required_props, version=body.version or "v1",
        inverseOf=body.inverse_of, symmetric=bool(body.symmetric),
        transitive=bool(body.transitive), aliases=body.aliases,
        externalIris=body.external_iris, definition=body.definition or "",
        datatype=body.datatype or "", namespace=body.namespace or "",
        deprecated=bool(body.deprecated),
        replacedBy=body.replaced_by or "",
        labels=body.labels, altLabels=body.alt_labels,
        module=body.module or "", identityKeys=body.identity_keys,
        qualifierSchema=body.qualifier_schema,
        tenantId=tenantId)


def _putDeclaration(body: TermWriteRequest) -> Dict[str, Any]:
    """PUT 的请求体 → 注册表 `declarePartial` 的声明字典。

    这里**只投影不合并**：None 意为「这一栏没写」，补齐现值由 `declarePartial` 单点做
    （REST PUT 与流水线 termUpserts 共用同一份合并口径，端点不再抄第二份字段清单）。
    """
    return {
        "label": body.label, "parentTermId": body.parent_term_id,
        "domain": body.domain, "rangeTerms": body.range_terms,
        "rangeKinds": body.range_kinds, "cardinality": body.cardinality,
        "disjointWith": body.disjoint_with, "requiredProps": body.required_props,
        "inverseOf": body.inverse_of, "symmetric": body.symmetric,
        "transitive": body.transitive, "aliases": body.aliases,
        "externalIris": body.external_iris, "definition": body.definition,
        "datatype": body.datatype, "namespace": body.namespace,
        "deprecated": body.deprecated,
        "replacedBy": body.replaced_by, "identityKeys": body.identity_keys,
        "labels": body.labels, "altLabels": body.alt_labels,
        "module": body.module, "qualifierSchema": body.qualifier_schema,
        "version": body.version,
    }


def _fullImpact(registry: Any, engine: Any, termId: str,
                tenantId: str) -> Dict[str, Any]:
    impact = registry.impactOf(termId, tenantId=tenantId)
    impact["referencing_rules"] = engine.ruleReferences(termId, tenantId=tenantId)
    return impact


def _impactBlocksDelete(impact: Dict[str, Any]) -> bool:
    return bool(
        impact.get("fact_count") or impact.get("typed_subject_count")
        or impact.get("child_terms") or impact.get("referencing_rules"))


@router.post("/ontology/terms")
async def create_ontology_term(
    body: TermWriteRequest, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """登记术语（S2 写面）。已存在即 409——更新走 PUT，POST 不做静默改写。"""
    _requireAdmin(current_user)
    store, registry, engine = _ontologyParts()
    tenant = _tenantOf(current_user)
    termId = str(body.term_id or "").strip()
    if not termId:
        raise HTTPException(status_code=400, detail="term_id 不能为空")
    if registry.term(termId, tenantId=tenant):
        raise HTTPException(status_code=409, detail="术语已存在: %s（更新走 PUT）" % termId)
    try:
        term = _registerTerm(registry, termId, body, tenant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # B8：关系特征声明即推理——术语落定后把 auto_* 规则幂等对齐（含撤声明退场）。
    engine.ensureAutoRules(tenantId=tenant)
    activityId = _landActivity(store, "ontology_term_write", current_user,
                               "create", {"term_id": termId}, body.basis)
    return {"code": 0, "message": "success",
            "data": {"term": term, "activity_id": activityId}}


@router.put("/ontology/terms/{term_id}")
async def update_ontology_term(
    term_id: str, body: TermWriteRequest, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """更新术语（S2 写面）。不存在即 404——新建走 POST，PUT 不做静默新建。"""
    _requireAdmin(current_user)
    store, registry, engine = _ontologyParts()
    tenant = _tenantOf(current_user)
    termId = str(term_id or "").strip()
    if not registry.term(termId, tenantId=tenant):
        raise HTTPException(status_code=404, detail="术语未登记: %s" % term_id)
    try:
        term = registry.declarePartial(termId, body.kind, _putDeclaration(body), tenant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # B8：特征翻转/撤除在这里生效——auto 规则随之重建或退场（结论经账本精确撤销）。
    engine.ensureAutoRules(tenantId=tenant)
    activityId = _landActivity(store, "ontology_term_write", current_user,
                               "update", {"term_id": termId}, body.basis)
    return {"code": 0, "message": "success",
            "data": {"term": term, "activity_id": activityId}}


@router.delete("/ontology/terms/{term_id}")
async def delete_ontology_term(
    term_id: str, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    basis: str = Query(""),
):
    """删除术语（S2 写面）。被事实/主体类型/子术语/规则引用时返回 409 + 影响面，
    不提供强行删除——先清引用再删，悬空引用不可逆。"""
    _requireAdmin(current_user)
    store, registry, engine = _ontologyParts()
    tenant = _tenantOf(current_user)
    termId = str(term_id or "").strip()
    if not registry.term(termId, tenantId=tenant):
        raise HTTPException(status_code=404, detail="术语未登记: %s" % termId)
    impact = _fullImpact(registry, engine, termId, tenant)
    if _impactBlocksDelete(impact):
        raise HTTPException(
            status_code=409,
            detail={"message": "术语被引用，先清引用再删", "impact": impact})
    try:
        registry.dropTerm(termId, tenantId=tenant)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    # B8：术语删了，它的 auto_* 规则不能还在对外推理（结论经账本精确撤销）。
    engine.ensureAutoRules(tenantId=tenant)
    activityId = _landActivity(store, "ontology_term_write", current_user,
                               "delete", {"term_id": termId}, basis)
    return {"code": 0, "message": "success",
            "data": {"term_id": termId, "activity_id": activityId}}


# ── B8：未知关系候选审核面 ──────────────────────────────────────────

@router.get("/ontology/derivations/{fact_id}")
async def get_derivation_chain(
    fact_id: str,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """解释链（B11 L5 设计 4）：推导结论回溯到规则与前提，账本单源。

    derived=False 表示这是观察事实（无推导边）；不伪造解释。
    """
    store, _registry, _engine = _ontologyParts()
    fact = store.fact(str(fact_id or "").strip())
    if fact is None:
        raise HTTPException(status_code=404, detail="事实不存在: %s" % fact_id)
    ledger = getattr(store, "_derivationLedger", None)
    premises = ledger.premisesOf(str(fact_id or "").strip()) if ledger else []
    return {"code": 0, "message": "success",
            "data": {"fact_id": str(fact_id or "").strip(),
                     "derived": bool(premises),
                     "rule_id": premises[0]["rule_id"] if premises else "",
                     "rule_version": premises[0]["rule_version"] if premises else "",
                     "premise_count": len(premises),
                     "premises": premises,
                     "confidence": fact.get("confidence"),
                     "derivation_kind": (fact.get("qualifier") or {}).get("shape", "")}}


@router.get("/ontology/relation-candidates")
async def list_relation_candidates(
    status: str = Query("pending"),
    limit: int = Query(100, ge=1, le=500),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """候选列表（读面，登录即可见）：pending/approved/rejected 三态。"""
    store, _registry, _engine = _ontologyParts()
    from neurova.knowledge.ontology.relation_candidates import RelationCandidateStore

    try:
        items = RelationCandidateStore(store).list(
            tenantId=_tenantOf(current_user), status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "message": "success", "data": {"items": items}}


@router.post("/ontology/relation-candidates/{candidate_id}/approve")
async def approve_relation_candidate(
    candidate_id: str, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    basis: str = Query(""),
):
    """批准候选：登记术语并回填 promoted_term_id（审批流走注册表，不另造登记路径）。"""
    _requireAdmin(current_user)
    store, registry, engine = _ontologyParts()
    from neurova.knowledge.ontology.relation_candidates import RelationCandidateStore

    try:
        candidate = RelationCandidateStore(store).approve(
            str(candidate_id or "").strip(), tenantId=_tenantOf(current_user),
            reviewedBy=str(current_user.get("username") or current_user.get("user_id") or ""),
            termRegistry=registry)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    # 批准即登记术语：特征对齐一次（新术语此刻特征全关，登记面可再声明）。
    engine.ensureAutoRules(tenantId=_tenantOf(current_user))
    activityId = _landActivity(store, "ontology_candidate_review", current_user,
                               "approve", {"candidate_id": str(candidate_id).strip(),
                                           "promoted_term_id": candidate.get("promoted_term_id")},
                               basis)
    return {"code": 0, "message": "success",
            "data": {"candidate": candidate, "activity_id": activityId}}


@router.post("/ontology/relation-candidates/{candidate_id}/reject")
async def reject_relation_candidate(
    candidate_id: str, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    basis: str = Query(""),
):
    """拒绝候选：保留审计行不删除（拒绝过什么与批准过什么是同一本账的两面）。"""
    _requireAdmin(current_user)
    store, _registry, _engine = _ontologyParts()
    from neurova.knowledge.ontology.relation_candidates import RelationCandidateStore

    try:
        candidate = RelationCandidateStore(store).reject(
            str(candidate_id or "").strip(), tenantId=_tenantOf(current_user),
            reviewedBy=str(current_user.get("username") or current_user.get("user_id") or ""))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    activityId = _landActivity(store, "ontology_candidate_review", current_user,
                               "reject", {"candidate_id": str(candidate_id).strip()},
                               basis)
    return {"code": 0, "message": "success",
            "data": {"candidate": candidate, "activity_id": activityId}}


@router.post("/ontology/rules")
async def create_ontology_rule(
    body: RuleWriteRequest, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """登记规则（S2 写面）。形状/变元/分层由引擎在写入处判，坏规则进不了表。"""
    _requireAdmin(current_user)
    store, _registry, engine = _ontologyParts()
    tenant = _tenantOf(current_user)
    ruleId = str(body.rule_id or "").strip()
    if not ruleId:
        raise HTTPException(status_code=400, detail="rule_id 不能为空")
    if engine.rule(ruleId, tenantId=tenant):
        raise HTTPException(status_code=409, detail="规则已存在: %s（更新走 PUT）" % ruleId)
    try:
        rule = engine.registerRule(
            ruleId, body.head_predicate, body.body or [],
            headSubjectVar=body.head_subject_var or "X",
            headObjectConst=body.head_object_const or "",
            shape=body.shape or "",
            materialization=body.materialization or "observe",
            enabled=True if body.enabled is None else body.enabled,
            version=body.version or "v1", tenantId=tenant)
    except (ValueError,) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    activityId = _landActivity(store, "ontology_rule_write", current_user,
                               "create", {"rule_id": ruleId}, body.basis)
    return {"code": 0, "message": "success",
            "data": {"rule": rule, "activity_id": activityId}}


@router.put("/ontology/rules/{rule_id}")
async def update_ontology_rule(
    rule_id: str, body: RuleWriteRequest, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """更新规则（S2 写面）。改版即旧版结论由引擎自动撤回重推。"""
    _requireAdmin(current_user)
    store, _registry, engine = _ontologyParts()
    tenant = _tenantOf(current_user)
    if not engine.rule(str(rule_id or "").strip(), tenantId=tenant):
        raise HTTPException(status_code=404, detail="规则未登记: %s" % rule_id)
    existing = engine.rule(str(rule_id).strip(), tenantId=tenant) or {}
    try:
        rule = engine.registerRule(
            str(rule_id).strip(), body.head_predicate,
            # 未提供 body 时保留现值，但现值是读面形状，必须先换回写面形状——
            # 两套形状互咬报出来的 400 长得像"调用方传了坏 body"（见 toAuthoringBody）
            body.body if body.body is not None
            else engine.toAuthoringBody(existing.get("body") or []),
            headSubjectVar=(body.head_subject_var
                            or existing.get("head_subject_var") or "X"),
            headObjectConst=(body.head_object_const
                             if body.head_object_const is not None
                             else existing.get("head_object_const") or ""),
            shape=(body.shape if body.shape is not None
                   else existing.get("shape") or ""),
            materialization=(body.materialization if body.materialization is not None
                             else existing.get("materialization") or "observe"),
            enabled=(body.enabled if body.enabled is not None
                     else bool(existing.get("enabled", True))),
            version=body.version or existing.get("version") or "v1",
            tenantId=tenant)
    except (ValueError,) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    activityId = _landActivity(store, "ontology_rule_write", current_user,
                               "update", {"rule_id": str(rule_id).strip()}, body.basis)
    return {"code": 0, "message": "success",
            "data": {"rule": rule, "activity_id": activityId}}


@router.delete("/ontology/rules/{rule_id}")
async def delete_ontology_rule(
    rule_id: str, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
    basis: str = Query(""),
):
    """删除规则（S2 写面）。它推过的结论由派生账一并撤回，不留死规则的输出。"""
    _requireAdmin(current_user)
    store, _registry, engine = _ontologyParts()
    try:
        engine.dropRule(str(rule_id or "").strip(), basis,
                        tenantId=_tenantOf(current_user))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    activityId = _landActivity(store, "ontology_rule_write", current_user,
                               "delete", {"rule_id": str(rule_id).strip()}, basis)
    return {"code": 0, "message": "success",
            "data": {"rule_id": str(rule_id).strip(), "activity_id": activityId}}


@router.get("/ontology/impact")
async def get_ontology_impact(
    request: Request,
    term: str = Query(...),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """术语影响面（S2）：谓词事实、主体类型断言、子术语、引用规则四路读数。
    删除前决策依据；读面不改动任何数据。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    store = get_knowledge_fact_store()
    tenant = _tenantOf(current_user)
    registry = OntologyTermRegistry(store)
    termId = str(term or "").strip()
    if not registry.term(termId, tenantId=tenant):
        raise HTTPException(status_code=404, detail="术语未登记: %s" % termId)
    impact = _fullImpact(registry, ForwardChainingEngine(store), termId, tenant)
    return {"code": 0, "message": "success", "data": impact}


# ── B2 dry-run 只读出口 ──────────────────────────────────────


class OntologyValidateCandidate(BaseModel):
    subjectLabel: str
    subjectKey: str = ""
    predicateTermId: str
    objectTerm: str
    qualifier: Dict[str, Any] = Field(default_factory=dict)


class OntologyValidateRequest(BaseModel):
    tenantId: str = ""
    agentId: str = ""
    triples: List[OntologyValidateCandidate] = Field(default_factory=list)


@router.post("/ontology/validate")
async def validateOntologyCandidates(
    body: OntologyValidateRequest,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """候选三元组 dry-run（B2，纯只读）：入库前试算五条校验，不落任何库。

    逐条回 `{index, subjectKey, findings, violations, verdict}` ＋ summary。
    violation 不抛异常——dry-run 只报告，拒写是唯一写咽喉（admission）的职责；
    unregistered 沿用校验器的保守原则：判不了 ≠ 不合法。校验路径与 B6 流水线
    共用同一份（`ontology/pipeline.dryRunFactCandidates`），无第二实现。
    """
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.pipeline import dryRunFactCandidates

    for index, candidate in enumerate(body.triples):
        if not str(candidate.subjectLabel or "").strip():
            raise HTTPException(
                status_code=400, detail="triples[%d].subjectLabel 不能为空" % index)
        if not str(candidate.predicateTermId or "").strip():
            raise HTTPException(
                status_code=400, detail="triples[%d].predicateTermId 不能为空" % index)
    store = get_knowledge_fact_store()
    try:
        results = dryRunFactCandidates(
            store,
            agentId=str(body.agentId or ""),
            tenantId=str(body.tenantId or "").strip() or _tenantOf(current_user),
            factCandidates=[candidate.model_dump() for candidate in body.triples],
        )
    except Exception as exc:  # noqa: BLE001 — 校验器故障显式 5xx 带原因，不吞不降级
        raise HTTPException(status_code=500, detail="validate 校验器异常: %s" % exc)
    summary = {
        "total": len(results),
        "passed": sum(1 for row in results if row["verdict"] == "pass"),
        "violated": sum(1 for row in results if row["verdict"] == "violation"),
        "unregistered": sum(
            1 for row in results
            if any(f.get("kind") == "unregistered" for f in row["findings"])),
    }
    return {"code": 0, "message": "success",
            "data": {"results": results, "summary": summary}}


# ── B6 本体构建流水线 ────────────────────────────────────────


class PipelineTermUpsert(BaseModel):
    termId: str
    kind: str
    label: str = ""
    parentTermId: Optional[str] = None
    domain: Optional[List[str]] = None
    rangeTerms: Optional[List[str]] = None
    rangeKinds: Optional[List[str]] = None
    cardinality: Optional[int] = None
    disjointWith: Optional[List[str]] = None
    requiredProps: Optional[List[str]] = None
    # B8 关系特征：批次面与单条写面对称——这里写不出来的字段等于没有写面。
    inverseOf: Optional[str] = None
    symmetric: Optional[bool] = None
    transitive: Optional[bool] = None
    aliases: Optional[List[str]] = None
    externalIris: Optional[List[Dict[str, str]]] = None
    datatype: Optional[str] = None
    deprecated: Optional[bool] = None
    replacedBy: Optional[str] = None
    # B10 L2 / B11 L3 声明字段：批次里写不出来的字段等于没有写面——发布路径与单条写面对齐。
    labels: Optional[Dict[str, str]] = None
    altLabels: Optional[Dict[str, list]] = None
    module: Optional[str] = None
    identityKeys: Optional[List[str]] = None
    qualifierSchema: Optional[Dict[str, Any]] = None
    # None = 保留现值（版本推进是治理动作，不该由不带 version 的批次顺手重置）
    version: Optional[str] = None


class PipelineRuleRegistration(BaseModel):
    ruleId: str
    headPredicate: str
    body: List[Dict[str, Any]] = Field(default_factory=list)
    headSubjectVar: str = "X"
    # 条件类规则（B1）也要能进流水线——写面两条路径的形状参数不许只有一半
    headObjectConst: str = ""
    enabled: bool = True
    version: str = "v1"
    # 发布批次也要能声明档位：写面两条路径的形状参数不许只有一半
    materialization: str = "observe"


class PipelineFactCandidate(BaseModel):
    subjectLabel: str
    subjectKey: str = ""
    predicateTermId: str
    objectTerm: str
    qualifier: Dict[str, Any] = Field(default_factory=dict)


class PipelineRunRequest(BaseModel):
    agentId: str = ""
    tenantId: str = ""
    termUpserts: List[PipelineTermUpsert] = Field(default_factory=list)
    ruleRegistrations: List[PipelineRuleRegistration] = Field(default_factory=list)
    factCandidates: List[PipelineFactCandidate] = Field(default_factory=list)
    reason: str = ""


@router.post("/ontology/pipeline/run")
async def runOntologyPipeline(
    body: PipelineRunRequest, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """本体构建流水线（B6，管理员）：一批变更单事务式成版。

    ① 候选事实先全部 dry-run（复用 B2 校验路径），任一 violation 整批拒绝、
    零落盘（400 带 rejections）；② 依次应用术语 upsert 与规则登记（只登记不
    触发求值，应用中途失败整批回滚）；③ 写一行 `knowledge_baselines` 快照
    （scope=ontology_pipeline，复用既有表）作为发布点。返回
    `{baselineId, applied, summary}`。
    """
    _requireAdmin(current_user)
    from neurova.knowledge.ontology.pipeline import OntologyPipeline

    store, registry, engine = _ontologyParts()
    pipeline = OntologyPipeline(store, registry=registry, engine=engine)
    try:
        result = pipeline.run(
            agentId=str(body.agentId or "").strip(),
            tenantId=str(body.tenantId or "").strip() or _tenantOf(current_user),
            termUpserts=[spec.model_dump() for spec in body.termUpserts],
            ruleRegistrations=[spec.model_dump() for spec in body.ruleRegistrations],
            factCandidates=[spec.model_dump() for spec in body.factCandidates],
            createdBy=str(current_user.get("user_id") or ""),
            reason=str(body.reason or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not result.get("accepted"):
        raise HTTPException(
            status_code=400,
            detail={"message": str(result.get("summary") or "本体流水线整批拒绝"),
                    "rejections": result.get("rejections") or []})
    activityId = _landActivity(
        store, "ontology_pipeline_run", current_user, "run",
        {"baseline_id": result["baselineId"], **result["applied"]}, body.reason)
    return {"code": 0, "message": "success",
            "data": {**result, "activity_id": activityId}}


@router.get("/ontology/pipeline/diff")
async def getOntologyPipelineDiff(
    request: Request,
    fromBaseline: str = Query(..., description="起始基线 id（ontology_pipeline）"),
    toBaseline: str = Query("", description="目标基线 id；缺省对比当前实况"),
    current_user: Dict = Depends(get_current_user_or_service),
):
    """两基线（或基线↔当前实况）之间 terms/rules 差异（B6，只读）。"""
    from neurova.knowledge.ontology.pipeline import OntologyPipeline

    store, registry, engine = _ontologyParts()
    pipeline = OntologyPipeline(store, registry=registry, engine=engine)
    try:
        report = pipeline.diff(
            fromBaselineId=fromBaseline,
            toBaselineId=str(toBaseline or "").strip() or None)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "message": "success", "data": report}


class PipelineRollbackRequest(BaseModel):
    toBaselineId: str
    reason: str = ""


@router.post("/ontology/pipeline/rollback")
async def rollbackOntologyPipeline(
    body: PipelineRollbackRequest, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """回滚到基线（B12 L8，管理员）：terms/rules/shapes 逐字恢复＋审计＋推导撤销。"""
    _requireAdmin(current_user)
    from neurova.knowledge.ontology.pipeline import OntologyPipeline

    store, registry, engine = _ontologyParts()
    pipeline = OntologyPipeline(store, registry=registry, engine=engine)
    try:
        result = pipeline.rollback(
            toBaselineId=str(body.toBaselineId or "").strip(),
            tenantId=_tenantOf(current_user),
            actor=str(current_user.get("user_id") or ""))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    activityId = _landActivity(
        store, "ontology_pipeline_rollback", current_user, "rollback",
        {"baseline_id": body.toBaselineId, **result}, body.reason)
    return {"code": 0, "message": "success",
            "data": {**result, "activity_id": activityId}}


# ── S3 实例编辑写面 ──────────────────────────────────────────



class InstanceWriteRequest(BaseModel):
    agent_id: str
    subject_label: str
    predicate_term_id: str
    object_term: str
    content: str = ""
    entry_id: str = ""
    evidence_text: str = ""
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    # W1：工作台建边可带 qualifier（数值键经咽喉写入口归一成 canonical 量值）
    qualifier: Optional[Dict[str, Any]] = None
    basis: str = ""


@router.post("/graph/instances")
async def create_graph_instance(
    body: InstanceWriteRequest, request: Request,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """2D 新建实例关系（S3）：经唯一咽喉落底座事实，返回 fact_id/activity_id。

    工作台不自己写图、更不写 JSON 投影——投影由事实派生，直接改会被 rebuild
    静默覆盖。逐字可核闸照常生效：断言里的精确标识符必须在声明依据里逐字存在。
    """
    _requireAdmin(current_user)
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.foundation.admission import (
        AdmissionError,
        AdmissionRequest,
        productionAdmissionGate,
    )
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    agentId = str(body.agent_id or "").strip()
    subject = str(body.subject_label or "").strip()
    objTerm = str(body.object_term or "").strip()
    predicate = str(body.predicate_term_id or "").strip()
    if not agentId:
        raise HTTPException(status_code=400, detail="agent_id 不能为空")
    if not subject or not objTerm:
        raise HTTPException(status_code=400, detail="主体与客体都不能为空")
    # 底座对管线的未登记谓词"免检"（validation 的 unregistered 不是 violation），
    # 那是抽取宽容；人工治理面没有这个宽容——类型系统外的边进底座就是
    # 读不出来源的无义事实，先登记谓词再建边。
    store = get_knowledge_fact_store()
    instanceTenant = str(current_user.get("tenant_id") or "default")
    if not OntologyTermRegistry(store).term(predicate, tenantId=instanceTenant):
        raise HTTPException(
            status_code=400,
            detail="谓词未登记: %s（先在 /ontology/terms 登记关系类型再建边）" % predicate)
    statement = str(body.content or "").strip() or "%s %s %s" % (subject, predicate, objTerm)
    evidence = str(body.evidence_text or "").strip()
    # 咽喉的逐字核闸"没声明就不查"——那是给管线写入的宽容；2D 人工建边没有
    # 依据就是不可审计的边，写入口必须先拒，不能借咽喉的宽容溜进去。
    if not evidence:
        raise HTTPException(
            status_code=400,
            detail="工作台建边必须声明依据（evidence_text）：无依据的边不可审计")
    entryId = str(body.entry_id or "").strip()

    store = get_knowledge_fact_store()
    gate = productionAdmissionGate(store, toolVersion="ontology-studio")
    assertion = {
        "actorType": "user",
        "actorId": str(current_user.get("user_id") or ""),
        "mediumRef": "entry:%s" % entryId if entryId else "",
        "statementText": statement,
    }
    try:
        receipt = gate.admit(AdmissionRequest(
            agentId=agentId,
            tenantId=instanceTenant,
            subjectLabel=subject,
            predicateTermId=predicate,
            objectTerm=objTerm,
            content=statement,
            # W1：声明数值 schema 的谓词，qualifier 在咽喉写入口单点归一
            qualifier=dict(body.qualifier or {}),
            relationKind="entity",
            assertions=[assertion],
            sourceTurnId="entry:%s" % entryId if entryId else "",
            evidenceText=evidence,
            validFrom=body.valid_from,
            validUntil=body.valid_until,
            activityKind="admit",
            activityBasis=str(body.basis or "") or "2D 工作台实例编辑",
        ))
    except AdmissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # W3：is_a 建边后把主类型挂到主体列——与抽取路径（graph_bridge
    # _assignSubjectType）同一语义；状态机迁移约束按主体类型 term 查找，
    # 工作台建边不挂类型会让约束静默失明（就近裁定，待追认）。
    if predicate == "is_a":
        try:
            OntologyTermRegistry(store).assignSubjectType(
                receipt.subjectKey, objTerm, tenantId=instanceTenant)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    return {
        "code": 0,
        "message": "success",
        "data": {
            "fact_id": receipt.factId,
            "subject_key": receipt.subjectKey,
            "activity_id": receipt.activityId,
            "pending_segments": receipt.pendingSegments,
            "deduped_by_content": receipt.dedupedByContent,
        },
    }
