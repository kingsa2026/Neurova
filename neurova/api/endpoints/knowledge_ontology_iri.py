# -*- coding: utf-8 -*-
"""B12 L6 稳定 IRI 解析（升级计划 §12.7）：kbg:/外部 IRI → 术语/主体。

独立路由模块：端点逻辑不塞 knowledge_ontology.py（尺寸纪律）；
注册走 `knowledge_ontology.router` 同一挂载面。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from neurova.api.auth import get_current_user_or_service

router = APIRouter()


def _resolveIri(store: Any, iri: str, tenantId: str) -> Dict[str, Any]:
    """kbg:<term> / 外部 IRI → term 行；其余 404（主体 IRI 解析归 B13 评估面）。"""
    if iri.startswith("kbg:"):
        termId = iri[len("kbg:"):]
        term = _termOf(store, termId, tenantId)
        if term is not None:
            return {"kind": "term", "term_id": termId, "term": term}
        raise LookupError(iri)
    for row in _termRows(store, tenantId):
        if "external_iris_json" not in row.keys():
            break
        import json as _json

        mapping = _json.loads(row["external_iris_json"] or "{}")
        if str(iri) in {str(v) for v in mapping.values()}:
            return {"kind": "term", "term_id": str(row["term_id"]),
                    "term": _termOf(store, str(row["term_id"]), tenantId)}
    raise LookupError(iri)


def _termRows(store: Any, tenantId: str):
    return store._conn.execute(
        "SELECT term_id, external_iris_json FROM ontology_terms WHERE tenant_id = ?"
        " ORDER BY term_id", (tenantId,)).fetchall()


def _termOf(store: Any, termId: str, tenantId: str):
    row = store._conn.execute(
        "SELECT * FROM ontology_terms WHERE tenant_id = ? AND term_id = ?",
        (tenantId, termId)).fetchone()
    import json as _json

    if row is None:
        return None
    term = dict(row)
    for key in ("domain_terms", "range_terms", "range_kinds", "disjoint_with",
                "required_props", "aliases_json"):
        if key in term:
            term[key] = _json.loads(term[key] or "[]")
    if "aliases_json" in term:
        term["aliases"] = term.pop("aliases_json")
    return term


@router.get("/ontology/iri/{iri:path}")
async def resolve_ontology_iri(
    iri: str,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """稳定 IRI 解析（登录可读）：kbg:<term> 与外部 IRI → 术语行；未知 404。"""
    store, _registry, _engine = _parts()
    tenantId = str(current_user.get("tenant_id") or "default")
    try:
        data = _resolveIri(store, str(iri or "").strip(), tenantId)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="IRI 无法解析: %s" % exc)
    return {"code": 0, "message": "success", "data": data}


def _parts():
    # 走门面路径（monkeypatch 目标与生产一致，测试隔离注入才生效）
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    store = get_knowledge_fact_store()
    return store, OntologyTermRegistry(store), None
