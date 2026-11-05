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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service
from neurova.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


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
    return Response(content=text, media_type="text/turtle; charset=utf-8")


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
    version: Optional[str] = None
    basis: str = ""


class RuleWriteRequest(BaseModel):
    rule_id: str = ""
    head_predicate: str
    head_subject_var: Optional[str] = None
    # 条件类（升级计划 B1）：head 客体常量非空 ⇒ 形状是 conjunction（X is_a 该类）。
    # 留空 = 既有 relay 语义，存量调用方一位不改。
    head_object_const: Optional[str] = None
    body: Optional[List[Dict[str, Any]]] = None
    enabled: Optional[bool] = None
    version: Optional[str] = None
    basis: str = ""


def _requireAdmin(current_user: Dict[str, Any]) -> None:
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(
            status_code=403, detail="本体写面是治理动作，仅管理员可执行")


def _ontologyParts():
    """写面装配：与读面同款三件套，一次拿齐不留第二套装配点。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    store = get_knowledge_fact_store()
    return store, OntologyTermRegistry(store), ForwardChainingEngine(store)


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
        tenantId=tenantId)


def _updateTermPayload(registry: Any, termId: str,
                       body: TermWriteRequest, tenantId: str) -> Dict[str, Any]:
    """PUT 是部分更新：未提供的字段保留现值，只把显式声明交回注册表。
    全量替换会把只改一个 label 的请求顺手清掉父子/值域声明。"""
    existing = registry.term(termId, tenantId=tenantId) or {}
    return {
        "label": body.label or existing.get("label") or "",
        "parentTermId": (body.parent_term_id if body.parent_term_id is not None
                         else existing.get("parent_term_id")),
        "domain": body.domain if body.domain is not None else existing.get("domain_terms") or [],
        "rangeTerms": (body.range_terms if body.range_terms is not None
                       else existing.get("range_terms") or []),
        "rangeKinds": (body.range_kinds if body.range_kinds is not None
                       else existing.get("range_kinds") or []),
        "cardinality": (body.cardinality if body.cardinality is not None
                        else existing.get("cardinality")),
        "disjointWith": (body.disjoint_with if body.disjoint_with is not None
                         else existing.get("disjoint_with") or []),
        "requiredProps": (body.required_props if body.required_props is not None
                          else existing.get("required_props") or []),
        "version": body.version or existing.get("version") or "v1",
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
    store, registry, _engine = _ontologyParts()
    tenant = _tenantOf(current_user)
    termId = str(term_id or "").strip()
    if not registry.term(termId, tenantId=tenant):
        raise HTTPException(status_code=404, detail="术语未登记: %s" % termId)
    try:
        payload = _updateTermPayload(registry, termId, body, tenant)
        term = registry.register(termId, body.kind, tenantId=tenant, **payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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
    activityId = _landActivity(store, "ontology_term_write", current_user,
                               "delete", {"term_id": termId}, basis)
    return {"code": 0, "message": "success",
            "data": {"term_id": termId, "activity_id": activityId}}


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
    version: str = "v1"


class PipelineRuleRegistration(BaseModel):
    ruleId: str
    headPredicate: str
    body: List[Dict[str, Any]] = Field(default_factory=list)
    headSubjectVar: str = "X"
    # 条件类规则（B1）也要能进流水线——写面两条路径的形状参数不许只有一半
    headObjectConst: str = ""
    enabled: bool = True
    version: str = "v1"


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
