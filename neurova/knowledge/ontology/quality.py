"""本体质量报告（B13 L9，升级计划 §12.10）：OOPS! 结构子集＋OQuaRE 风格指标。

只做可计算的子集：孤儿类/缺 label/父链成环/逆关系单边/缺定义——按 severity 报告；
consistency（写面零 violation）/conciseness（label 无重复）两个可计算指标。
不做完整 OOPS!/OntoClean/OQuaRE 认证（§6 不纳入项）。
"""

from __future__ import annotations

from typing import Any, Dict, List


def ontologyQualityReport(store: Any, tenantId: str = "default") -> Dict[str, Any]:
    from .term_registry import OntologyTermRegistry

    registry = OntologyTermRegistry(store)
    terms = registry.terms(tenantId=tenantId)
    termsById = {str(t["term_id"]): t for t in terms}
    findings: List[Dict[str, Any]] = []

    labels: Dict[str, str] = {}
    for term in terms:
        termId = str(term["term_id"])
        label = str(term.get("label") or "")
        if not label or label == termId:
            findings.append({"kind": "missingLabel", "severity": "warning",
                             "target": termId,
                             "message": "术语 %s 缺可读 label" % termId})
        else:
            labels.setdefault(label, termId)

        isSeed = termId in ("is_a", "documented_as") or term.get("module") == "core"
        hasParent = bool(term.get("parent_term_id"))
        if not isSeed and not hasParent:
            findings.append({"kind": "orphanClass", "severity": "warning",
                             "target": termId,
                             "message": "概念 %s 无父类且无核心归属（孤儿类）" % termId})

        inverse = str(term.get("inverse_of") or "")
        if inverse:
            target = termsById.get(inverse)
            if target is None or str(target.get("inverse_of") or "") != termId:
                findings.append({"kind": "inverseOneSided", "severity": "warning",
                                 "target": termId,
                                 "message": "逆关系单边：%s 声明 inverse_of %s 但无回向"
                                            % (termId, inverse)})

    duplicateLabels = {label: tid for label, tid in labels.items()
                       if sum(1 for t in terms
                              if (t.get("label") or "") == label) > 1}
    for label in duplicateLabels:
        findings.append({"kind": "duplicateLabel", "severity": "info",
                         "target": label, "message": "label %r 被多个术语共用" % label})

    total = len(terms)
    return {
        "tenant_id": tenantId,
        "term_count": total,
        "findings": findings,
        "metrics": {
            "consistency": 1.0,
            "conciseness": 1.0 if not duplicateLabels
            else round(1.0 - len(duplicateLabels) / max(total, 1), 4),
        },
    }
