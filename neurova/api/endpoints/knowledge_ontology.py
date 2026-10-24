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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service
from neurova.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _schemaVersion() -> int:
    """schema 版本的唯一出处是版本域注册表，不在这里写死数字。"""
    from neurova.core.db_migration import latest_version
    from neurova.knowledge.foundation.narratives import NARRATIVE_DOMAIN

    return latest_version(NARRATIVE_DOMAIN)


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
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    store = get_knowledge_fact_store()
    registry = OntologyTermRegistry(store)
    engine = ForwardChainingEngine(store)

    return {
        "code": 0,
        "message": "success",
        "data": {
            "terms": _termsView(registry),
            "rules": engine.rules(),
            "schema_version": _schemaVersion(),
            # 租户级本体是已拍板、尚未落地的迁移（term_id 目前全表唯一，加一列
            # tenant 并不能让两个租户各用同一个 id）。如实报出，不由前端过滤冒充隔离。
            "tenant_scoped": False,
        },
    }


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


def _registerTerm(registry: Any, termId: str, body: TermWriteRequest) -> Dict[str, Any]:
    return registry.register(
        termId, body.kind, label=body.label, parentTermId=body.parent_term_id,
        domain=body.domain, rangeTerms=body.range_terms, rangeKinds=body.range_kinds,
        cardinality=body.cardinality, disjointWith=body.disjoint_with,
        requiredProps=body.required_props, version=body.version or "v1")


def _updateTermPayload(registry: Any, termId: str,
                       body: TermWriteRequest) -> Dict[str, Any]:
    """PUT 是部分更新：未提供的字段保留现值，只把显式声明交回注册表。
    全量替换会把只改一个 label 的请求顺手清掉父子/值域声明。"""
    existing = registry.term(termId) or {}
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


def _fullImpact(registry: Any, engine: Any, termId: str) -> Dict[str, Any]:
    impact = registry.impactOf(termId)
    impact["referencing_rules"] = engine.ruleReferences(termId)
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
    termId = str(body.term_id or "").strip()
    if not termId:
        raise HTTPException(status_code=400, detail="term_id 不能为空")
    if registry.term(termId):
        raise HTTPException(status_code=409, detail="术语已存在: %s（更新走 PUT）" % termId)
    try:
        term = _registerTerm(registry, termId, body)
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
    termId = str(term_id or "").strip()
    if not registry.term(termId):
        raise HTTPException(status_code=404, detail="术语未登记: %s" % termId)
    try:
        payload = _updateTermPayload(registry, termId, body)
        term = registry.register(termId, body.kind, **payload)
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
    termId = str(term_id or "").strip()
    if not registry.term(termId):
        raise HTTPException(status_code=404, detail="术语未登记: %s" % termId)
    impact = _fullImpact(registry, engine, termId)
    if _impactBlocksDelete(impact):
        raise HTTPException(
            status_code=409,
            detail={"message": "术语被引用，先清引用再删", "impact": impact})
    try:
        registry.dropTerm(termId)
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
    ruleId = str(body.rule_id or "").strip()
    if not ruleId:
        raise HTTPException(status_code=400, detail="rule_id 不能为空")
    if engine.rule(ruleId):
        raise HTTPException(status_code=409, detail="规则已存在: %s（更新走 PUT）" % ruleId)
    try:
        rule = engine.registerRule(
            ruleId, body.head_predicate, body.body or [],
            headSubjectVar=body.head_subject_var or "X",
            enabled=True if body.enabled is None else body.enabled,
            version=body.version or "v1")
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
    if not engine.rule(str(rule_id or "").strip()):
        raise HTTPException(status_code=404, detail="规则未登记: %s" % rule_id)
    existing = engine.rule(str(rule_id).strip()) or {}
    try:
        rule = engine.registerRule(
            str(rule_id).strip(), body.head_predicate,
            body.body if body.body is not None else existing.get("body") or [],
            headSubjectVar=(body.head_subject_var
                            or existing.get("head_subject_var") or "X"),
            enabled=(body.enabled if body.enabled is not None
                     else bool(existing.get("enabled", True))),
            version=body.version or existing.get("version") or "v1")
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
        engine.dropRule(str(rule_id or "").strip(), basis)
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
    registry = OntologyTermRegistry(store)
    termId = str(term or "").strip()
    if not registry.term(termId):
        raise HTTPException(status_code=404, detail="术语未登记: %s" % termId)
    impact = _fullImpact(registry, ForwardChainingEngine(store), termId)
    return {"code": 0, "message": "success", "data": impact}
