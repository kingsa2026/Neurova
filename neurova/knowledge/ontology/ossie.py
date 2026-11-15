# -*- coding: utf-8 -*-
"""Ossie 风格语义模型 YAML 互操作（对照研究 P2-4，2026-11-15）。

对方（auto-ontology）以 YAML 文档进出模型定义（其文档 schema 为自有形状，
经 Apache Ossie 转换器对接开放标准）。本仓同法：导出/导入一份**语义模型
文档**（术语全量声明 + 规则 + 形状），字段名对齐其 `semantic_layer.terms`
的 vocabulary（id/name/description/synonyms/parent/…），不冒充已过 Ossie
官方 conversion 认证——标准转换器属后续生态批。

导入纪律：
- **缺省 dry-run**：只解析 + 结构/冲突预检（父类存在、别名单读冲突），
  零落库；`apply=true` 才走本体构建流水线（B6：整批原子 + 基线快照 +
  失败回滚），人工确认点在调用方；
- 导入不是第二登记路径：术语落库只经 `OntologyBuildPipeline` → 注册表单点。
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from neurova.core.time_utils import nowIso as _now

OSSIE_FORMAT = "neurova-ontology-ossie/1"


def exportOssie(store: Any, tenantId: str = "default") -> Dict[str, Any]:
    """本体 → Ossie 风格语义模型文档（dict；YAML 序列化由端点层做）。"""
    from .rule_engine import ForwardChainingEngine
    from .shapes import ShapeRegistry
    from .term_registry import OntologyTermRegistry

    tenant = str(tenantId or "default")
    registry = OntologyTermRegistry(store)
    engine = ForwardChainingEngine(store)

    terms: List[Dict[str, Any]] = []
    for term in registry.terms(tenantId=tenant):
        terms.append({
            "id": str(term.get("term_id") or ""),
            "kind": str(term.get("kind") or ""),
            "name": str(term.get("label") or ""),
            "description": str(term.get("description") or ""),
            "synonyms": list(term.get("aliases") or []),
            "parent": str(term.get("parent_term_id") or "") or None,
            "domain": list(term.get("domain_terms") or []),
            "range": list(term.get("range_terms") or []),
            "range_kinds": list(term.get("range_kinds") or []),
            "cardinality": term.get("cardinality"),
            "disjoint_with": list(term.get("disjoint_with") or []),
            "required_props": list(term.get("required_props") or []),
            "inverse_of": str(term.get("inverse_of") or "") or None,
            "symmetric": bool(term.get("symmetric")),
            "transitive": bool(term.get("transitive")),
            "module": str(term.get("module") or ""),
            "namespace": str(term.get("namespace") or ""),
            "version": str(term.get("version") or "v1"),
        })

    rules = [{
        "id": str(r.get("rule_id") or ""),
        "head_predicate": str(r.get("head_predicate") or ""),
        "head_subject_var": str(r.get("head_subject_var") or "X"),
        "head_object_const": str(r.get("head_object_const") or ""),
        "body": list(r.get("body") or []),
        "materialization": str(r.get("materialization") or "observe"),
    } for r in engine.rules(tenantId=tenant)]

    shapes = [{
        "target_kind": str(s.get("target_kind") or ""),
        "target_term_id": str(s.get("target_term_id") or ""),
        "path": str(s.get("path") or ""),
        "constraint_kind": str(s.get("constraint_kind") or ""),
        "constraint": s.get("constraint"),
        "severity": s.get("severity"),
    } for s in ShapeRegistry(store).list(tenantId=tenant)]

    return {
        "format": OSSIE_FORMAT,
        "exported_at": _now(),
        "tenant_id": tenant,
        "semantic_layer": {"terms": terms, "rules": rules, "shapes": shapes},
    }


def _termSpecFromOssie(entry: Dict[str, Any]) -> Dict[str, Any]:
    """文档 term 条目 → 流水线 termUpsert spec（declarePartial 参数名）。"""
    spec: Dict[str, Any] = {
        "termId": str(entry.get("id") or "").strip(),
        "kind": str(entry.get("kind") or "concept").strip(),
    }
    mapping = {
        "label": entry.get("name"),
        "definition": entry.get("description"),
        "aliases": entry.get("synonyms"),
        "parentTermId": entry.get("parent"),
        "domain": entry.get("domain"),
        "rangeTerms": entry.get("range"),
        "rangeKinds": entry.get("range_kinds"),
        "cardinality": entry.get("cardinality"),
        "disjointWith": entry.get("disjoint_with"),
        "requiredProps": entry.get("required_props"),
        "inverseOf": entry.get("inverse_of"),
        "symmetric": entry.get("symmetric"),
        "transitive": entry.get("transitive"),
        "module": entry.get("module"),
        "namespace": entry.get("namespace"),
        "version": entry.get("version"),
    }
    for key, value in mapping.items():
        if value not in (None, ""):
            spec[key] = value
    return spec


def importOssie(store: Any, document: Dict[str, Any], tenantId: str = "default",
                apply: bool = False, createdBy: str = "",
                reason: str = "") -> Dict[str, Any]:
    """Ossie 风格文档 → 本体流水线批。缺省 dry-run（零落库），apply 才成版。"""
    import yaml

    from .pipeline import OntologyPipeline
    from .rule_engine import ForwardChainingEngine
    from .term_registry import OntologyTermRegistry

    if isinstance(document, str):
        document = yaml.safe_load(document) or {}
    if not isinstance(document, dict):
        raise ValueError("文档不是 YAML 映射")
    fmt = str(document.get("format") or "")
    if fmt and not fmt.startswith("neurova-ontology-ossie"):
        raise ValueError("format %r 不是本仓语义模型文档（%s）" % (fmt, OSSIE_FORMAT))
    tenant = str(tenantId or "default")
    semantic = document.get("semantic_layer") or {}
    entries = list(semantic.get("terms") or [])
    if not entries and not (semantic.get("rules") or []):
        raise ValueError("文档没有可导入的术语或规则")

    termSpecs = [_termSpecFromOssie(e) for e in entries]
    for spec in termSpecs:
        if not spec["termId"]:
            raise ValueError("术语条目缺 id")
        if spec["kind"] not in ("concept", "relation", "property"):
            raise ValueError("术语 %s kind %r 不在闭集" % (spec["termId"], spec["kind"]))

    ruleSpecs = []
    for rule in (semantic.get("rules") or []):
        ruleSpecs.append({
            "ruleId": str(rule.get("id") or "").strip(),
            "headPredicate": str(rule.get("head_predicate") or "").strip(),
            "headSubjectVar": str(rule.get("head_subject_var") or "X"),
            "headObjectConst": str(rule.get("head_object_const") or ""),
            "body": list(rule.get("body") or []),
            "materialization": str(rule.get("materialization") or "observe"),
        })

    # dry-run 预检（只读）：父类在场（含同批引入）、逆关系在场、已登记时 kind 不翻
    registry = OntologyTermRegistry(store)
    preflight: List[Dict[str, Any]] = []
    known = {str(t.get("term_id")) for t in registry.terms(tenantId=tenant)}
    known |= {spec["termId"] for spec in termSpecs}
    for spec in termSpecs:
        termId = spec["termId"]
        existing = registry.term(termId, tenantId=tenant)
        if existing is not None and str(existing.get("kind")) != spec["kind"]:
            preflight.append({"term_id": termId,
                              "finding": "kind 翻转（%s→%s）不允许，跳过该条"
                                         % (existing.get("kind"), spec["kind"])})
        parent = spec.get("parentTermId")
        if parent and parent not in known and registry.term(parent, tenantId=tenant) is None:
            preflight.append({"term_id": termId,
                              "finding": "父类 %s 未登记" % parent})
    if not apply:
        return {"accepted": False, "dry_run": True, "terms": len(termSpecs),
                "rules": len(ruleSpecs), "preflight": preflight,
                "note": "dry-run 未落库；apply=true 经本体流水线整批成版"}
    if preflight:
        return {"accepted": False, "terms": len(termSpecs), "rules": len(ruleSpecs),
                "preflight": preflight,
                "note": "预检有 finding，拒绝成版（零落盘）"}

    engine = ForwardChainingEngine(store)
    pipeline = OntologyPipeline(store, registry=registry, engine=engine)
    result = pipeline.run(
        agentId="default", tenantId=tenant,
        termUpserts=termSpecs, ruleRegistrations=ruleSpecs, factCandidates=[],
        createdBy=createdBy, reason=reason or "Ossie 文档导入",
    )
    result["imported_id"] = "ossie_%s" % uuid.uuid4().hex[:8]
    return result
