"""本体质量报告（B13 L9，升级计划 §12.10）：OOPS! 结构子集＋OQuaRE 风格指标。

只做可计算的子集：孤儿类/缺 label/父链成环/逆关系单边/悬空引用——按 severity 报告。
U6 质量门阈值化：metrics 全部由**同一趟 findings 扫描**派生（不建第二套判定），
consistency 由 violation 级 findings 计数按术语数比例折减，不再有静态 1.0；
`qualityGateCheck` 在报告之上做阈值判定（min_coverage/max_findings/max_orphan_rate）。
不做完整 OOPS!/OntoClean/OQuaRE 认证（§6 不纳入项）。

指标口径（全部四舍五入到 4 位，T=术语数，分母取 max(T,1) 防空库除零）：
- consistency   = max(0, 1 - V/T)，V = severity != "info" 的 findings 数（violation 级）；
- conciseness   = 1 - 重复 label 数/T（B13 既有口径，语义不变）；
- orphanRate    = 孤儿类 findings 数/T；
- missingLabelRate = 缺 label findings 数/T；
- inverseOneSidedCount = 逆关系单边 findings 数（计数型指标）；
- parentCycleCount     = 父链环个数（每个环只记一次）；
- referenceIntegrity   = 1 - 悬空引用数/总引用数（无引用时为 1.0）；
- coverage      = (T - 被 findings 点名的术语数)/T，即"无 findings 术语占比"，
                  供质量门 min_coverage 消费（单一口径在这里，门不另算）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# 质量门阈值闭集；顺序即 threshold_failures 的输出顺序（按序 Violation 描述）。
_GATE_CHECKS = ("min_coverage", "max_findings", "max_orphan_rate")

# 术语间引用列：悬空引用扫这些字段（range_kinds 是类别名、required_props 是属性名，
# 都不是术语引用，不入计数）。
_REFERENCE_LIST_FIELDS = ("domain_terms", "range_terms", "disjoint_with")

_METRIC_ROUND = 4


def ontologyQualityReport(store: Any, tenantId: str = "default",
                          thresholds: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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

    # 父链成环：登记面（_ensureNoParentCycle）本会拒环，这里抓绕过登记面的脏库
    # （手工改库/迁移残留）。每个环只记一条 finding，target 取环内最小 term_id 保确定。
    for cycle in _findParentCycles(terms):
        findings.append({"kind": "parentCycle", "severity": "warning",
                         "target": cycle[0],
                         "message": "父链成环：%s" % _cyclePathMessage(cycle, termsById)})

    # 悬空引用：parent/inverse_of/domain/range/disjoint/replaced_by 指向未登记术语。
    _scanDanglingReferences(terms, termsById, findings)

    duplicateLabels = {label: tid for label, tid in labels.items()
                       if sum(1 for t in terms
                              if (t.get("label") or "") == label) > 1}
    for label in duplicateLabels:
        findings.append({"kind": "duplicateLabel", "severity": "info",
                         "target": label, "message": "label %r 被多个术语共用" % label})

    total = len(terms)
    report = {
        "tenant_id": tenantId,
        "term_count": total,
        "findings": findings,
        "metrics": _computeMetrics(terms, findings, set(duplicateLabels)),
    }
    if thresholds is not None:
        # 可选 gate 键：只有调用方显式给阈值才出现，既有消费方零感知。
        report["gate"] = qualityGateCheck(report, thresholds)
    return report


def _findParentCycles(terms: List[Dict[str, Any]]) -> List[tuple]:
    """沿 parent_term_id 找环，返回去重后的环（每个环以排序后的 term_id 元组表示）。

    safe 集合记"已确认不在任何环上"的节点：一旦走过且未闭合，后续遍历不再重走。
    """
    parentOf = {str(t["term_id"]): str(t.get("parent_term_id") or "") for t in terms}
    cycles: List[tuple] = []
    seenCycles = set()
    safe = set()
    for start in parentOf:
        if start in safe:
            continue
        path: List[str] = []
        position: Dict[str, int] = {}
        cursor = start
        while cursor and cursor not in safe:
            if cursor in position:
                cycle = tuple(sorted(path[position[cursor]:]))
                if cycle not in seenCycles:
                    seenCycles.add(cycle)
                    cycles.append(cycle)
                break
            position[cursor] = len(path)
            path.append(cursor)
            cursor = parentOf.get(cursor, "")
        safe.update(path)
    return cycles


def _cyclePathMessage(cycle: tuple, termsById: Dict[str, Dict[str, Any]]) -> str:
    """把排序后的环还原成沿父链的路径文本（a → b → c → a），便于人工定位。"""
    parentOf = {str(t["term_id"]): str(t.get("parent_term_id") or "")
                for t in termsById.values()}
    start = cycle[0]
    path = [start]
    cursor = parentOf.get(start, "")
    while cursor and cursor != start and len(path) <= len(cycle):
        path.append(cursor)
        cursor = parentOf.get(cursor, "")
    path.append(start)
    return " → ".join(path)


def _scanDanglingReferences(terms: List[Dict[str, Any]],
                            termsById: Dict[str, Dict[str, Any]],
                            findings: List[Dict[str, Any]]) -> None:
    for term in terms:
        termId = str(term["term_id"])
        refs: List[str] = []
        for field in ("parent_term_id", "inverse_of", "replaced_by"):
            value = str(term.get(field) or "")
            if value:
                refs.append(value)
        for field in _REFERENCE_LIST_FIELDS:
            refs.extend(str(x) for x in (term.get(field) or []) if str(x))
        for ref in refs:
            if ref not in termsById:
                findings.append({"kind": "danglingReference", "severity": "warning",
                                 "target": termId,
                                 "message": "术语 %s 引用了未登记的 %r（悬空引用）"
                                            % (termId, ref)})


def _computeMetrics(terms: List[Dict[str, Any]], findings: List[Dict[str, Any]],
                    duplicateLabelKeys: set) -> Dict[str, Any]:
    total = len(terms)
    denom = max(total, 1)
    violationCount = sum(1 for f in findings if f.get("severity") != "info")
    kindCounts: Dict[str, int] = {}
    flagged = set()
    for f in findings:
        kindCounts[f["kind"]] = kindCounts.get(f["kind"], 0) + 1
        if f["kind"] != "duplicateLabel":
            flagged.add(str(f["target"]))
    for term in terms:
        # duplicateLabel 的 target 是 label 文本；覆盖率按"被点名的术语"计，
        # 这里把重复 label 折回持有它的术语。
        if str(term.get("label") or "") in duplicateLabelKeys:
            flagged.add(str(term["term_id"]))
    refTotal, refDangling = _referenceCounts(terms, findings)
    return {
        "consistency": round(max(0.0, 1.0 - violationCount / denom), _METRIC_ROUND),
        "conciseness": 1.0 if not duplicateLabelKeys
        else round(1.0 - len(duplicateLabelKeys) / denom, _METRIC_ROUND),
        "orphanRate": round(kindCounts.get("orphanClass", 0) / denom, _METRIC_ROUND),
        "missingLabelRate": round(kindCounts.get("missingLabel", 0) / denom,
                                  _METRIC_ROUND),
        "inverseOneSidedCount": kindCounts.get("inverseOneSided", 0),
        "parentCycleCount": kindCounts.get("parentCycle", 0),
        "referenceIntegrity": 1.0 if refTotal == 0
        else round(1.0 - refDangling / refTotal, _METRIC_ROUND),
        "coverage": round((total - len(flagged)) / denom, _METRIC_ROUND),
    }


def _referenceCounts(terms: List[Dict[str, Any]],
                     findings: List[Dict[str, Any]]) -> tuple:
    """总引用数与悬空引用数：与 _scanDanglingReferences 同一扫描口径。"""
    total = 0
    for term in terms:
        for field in ("parent_term_id", "inverse_of", "replaced_by"):
            if str(term.get(field) or ""):
                total += 1
        for field in _REFERENCE_LIST_FIELDS:
            total += sum(1 for x in (term.get(field) or []) if str(x))
    dangling = sum(1 for f in findings if f["kind"] == "danglingReference")
    return total, dangling


def qualityGateCheck(report: Dict[str, Any],
                     thresholds: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """质量门：对质量报告做阈值判定，返回 {passed, threshold_failures}。

    thresholds 全缺省（None/空 dict）即 passed=True。未知阈值键显式 ValueError——
    静默忽略拼错的门等于没设门。threshold_failures 按 _GATE_CHECKS 固定顺序输出。
    """
    limits = dict(thresholds or {})
    unknown = sorted(set(limits) - set(_GATE_CHECKS))
    if unknown:
        raise ValueError("未知阈值键 %s（有效值: %s）"
                         % (unknown, " / ".join(_GATE_CHECKS)))
    metrics = report.get("metrics") or {}
    findings = report.get("findings") or []
    failures: List[str] = []
    for check in _GATE_CHECKS:
        if check not in limits:
            continue
        limit = limits[check]
        if check == "min_coverage":
            _requireUnitInterval("min_coverage", limit)
            actual = metrics.get("coverage")
            if actual is None or float(actual) < float(limit) - 1e-9:
                failures.append(
                    "min_coverage 未达标：覆盖率 %s < 阈值 %s"
                    "（覆盖率=未被任何 findings 点名的术语占比）" % (actual, limit))
        elif check == "max_findings":
            limitInt = int(limit)
            if limitInt < 0:
                raise ValueError("max_findings 阈值须 ≥ 0，收到 %r" % (limit,))
            actual = len(findings)
            if actual > limitInt:
                failures.append("max_findings 超限：findings %d 条 > 阈值 %d"
                                % (actual, limitInt))
        elif check == "max_orphan_rate":
            _requireUnitInterval("max_orphan_rate", limit)
            actual = metrics.get("orphanRate")
            if actual is None or float(actual) > float(limit) + 1e-9:
                failures.append("max_orphan_rate 超限：孤儿类率 %s > 阈值 %s"
                                % (actual, limit))
    return {"passed": not failures, "threshold_failures": failures}


def _requireUnitInterval(name: str, value: Any) -> None:
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError("%s 阈值须落在 [0,1]，收到 %r" % (name, value))
