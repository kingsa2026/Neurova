"""本体构建流水线（B6）与候选事实 dry-run 校验路径（B2）的共享落点。

dry-run 校验路径**只有一份**（本模块 `dryRunFactCandidates`）：
  * 逐条候选构造 `AdmissionRequest`——evidenceText 与 assertions 留空。dry-run
    没有证据可核，逐字可核闸的契约是"没声明就不查、也不自称查过"（admission
    `_checkVerifiability`），这里同样不假装验过；
  * subjectKey 缺省时按**规范标签精确匹配**已有主体（只读，不 similarity、不
    alias——那两条是写入链消解段的本职，dry-run 不替调用方猜身份）；匹配不到
    传空串。空 subjectKey 落在写入链上是"新建主体、未挂类型"，dry-run 据此
    如实补一条 unregistered(domain) 发现，消息形态沿用 validation.py；
  * 调 `OntologyValidationReport(registry).findings(...)`——五条校验判据的唯一
    事实源仍是 validation.py，本模块不复制任何一条校验规则。

violation 在 dry-run 里**不抛异常**：只读出口（B2 `/ontology/validate`）的职责
是如实报告，拒写是唯一写咽喉的职责；B6 的 `OntologyPipeline.run` 拿这里的
violations 当整批闸——任一候选违规即整批拒绝、零落盘。
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any, Dict, List, Optional

from neurova.knowledge.foundation.admission import AdmissionRequest

from .rule_engine import ForwardChainingEngine
from .term_registry import OntologyTermRegistry
from .validation import OntologyValidationReport

#: 本体流水线基线在 `knowledge_baselines.scope` 上的分区值（复用既有表，无新表）
ONTOLOGY_PIPELINE_SCOPE = "ontology_pipeline"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()



def _exactSubjectKey(store: Any, agentId: str, tenantId: str, label: str) -> str:
    """规范标签精确匹配已有主体（只读）。匹配不到回空串，让 findings 如实报。"""
    from ..foundation.knowledge_facts import normalizeLabel

    normalized = normalizeLabel(str(label or ""))
    if not normalized:
        return ""
    for row in store.listSubjects(str(agentId or ""), tenantId=tenantId):
        if str(row.get("normalized_label") or "") == normalized:
            return str(row.get("subject_key") or "")
    return ""


def _unregisteredSubjectFinding(subjectLabel: str, predicate: str) -> Dict[str, Any]:
    """空 subjectKey 的如实投影：写入链会新建主体（必无类型），定义域无从校验。

    消息形态沿用 validation.py 的 unregistered(domain) 行——这里只补
    "dry-run 眼里还没有这个主体"这一事实，不发明新判据、不改任何违规语义。
    """
    return {
        "kind": "unregistered",
        "rule": "domain",
        "message": "主体 %s 未登记（dry-run 时点无此主体），定义域无法校验" % subjectLabel,
        "term_id": predicate,
        "subject_key": "",
    }


def dryRunFactCandidates(
    store: Any,
    agentId: str,
    tenantId: str,
    factCandidates: Optional[List[Dict[str, Any]]] = None,
    registry: Any = None,
    report: Any = None,
) -> List[Dict[str, Any]]:
    """B2/B6 共用的只读校验路径（唯一实现，教义第 6 条）。

    逐条候选回一行 `{index, subjectKey, findings, violations, verdict}`；
    verdict ∈ {"pass", "violation"}，unregistered 不构成 violation（保守原则）。
    纯只读：不建主体、不落事实、不写活动。
    """
    tenant = str(tenantId or "default")
    registry = registry if registry is not None else OntologyTermRegistry(store)
    report = report if report is not None else OntologyValidationReport(registry)
    rows: List[Dict[str, Any]] = []
    for index, candidate in enumerate(factCandidates or []):
        subjectLabel = str(candidate.get("subjectLabel") or "").strip()
        predicate = str(candidate.get("predicateTermId") or "").strip()
        subjectKey = str(candidate.get("subjectKey") or "").strip()
        if not subjectKey:
            subjectKey = _exactSubjectKey(store, agentId, tenant, subjectLabel)
        request = AdmissionRequest(
            agentId=str(agentId or ""),
            tenantId=tenant,
            subjectLabel=subjectLabel,
            predicateTermId=predicate,
            objectTerm=str(candidate.get("objectTerm") or ""),
            qualifier=dict(candidate.get("qualifier") or {}),
            recordKind="triple",
            evidenceText="",
            assertions=[],
        )
        findings = report.findings(request, subjectKey)
        if not subjectKey:
            findings = [_unregisteredSubjectFinding(subjectLabel, predicate)] + [
                f for f in findings
                if not (f.get("kind") == "unregistered" and f.get("rule") == "domain")
            ]
        violations = [f for f in findings if f.get("kind") == "violation"]
        rows.append({
            "index": index,
            "subjectKey": subjectKey,
            "findings": findings,
            "violations": violations,
            "verdict": "violation" if violations else "pass",
        })
    return rows


class OntologyPipeline:
    """本体构建流水线（B6）：术语 upsert ＋ 规则登记 ＋ 候选事实 dry-run 一次成版。

    单批次原子的实现口径（在既有组件各自的事务之上，不改它们）：
      * 拒绝零落盘——候选**先全部** dry-run（复用 B2 路径），任一 violation
        整批拒绝，此刻还没有任何写入；
      * 应用不落半态——术语/规则逐条应用并记账，中途失败**回滚本批已应用**的
        变更再抛错；基线快照最后写，没有基线行就等于没有"发布"过；
      * 基线复用 `knowledge_baselines`（scope=`ontology_pipeline`），快照存
        应用后的 terms/rules 全量声明，作为回滚点与 diff 端点。
    """

    _TERM_DIFF_FIELDS = ("kind", "label", "parent_term_id", "domain_terms",
                         "range_terms", "range_kinds", "cardinality",
                         "disjoint_with", "required_props", "version")
    # 规则的 diff 只看**声明**字段。stratification_level / depends_on 是引擎按
    # 当前规则图派生的记账值（重登记时会把自身旧行计入 producer，层号随之
    # 0→1）——同声明重放被它们判成"变更"，幂等 rerun 的 diff 就永远不空。
    _RULE_DIFF_FIELDS = ("head_predicate", "head_subject_var", "head_object_const",
                         "body", "negated_predicates", "enabled", "version")

    def __init__(self, store: Any, registry: Any = None, engine: Any = None,
                 validator: Any = None) -> None:
        self._store = store
        self._registry = registry if registry is not None else OntologyTermRegistry(store)
        self._engine = engine if engine is not None else ForwardChainingEngine(store)
        self._validator = validator if validator is not None \
            else OntologyValidationReport(self._registry)

    def run(
        self,
        agentId: str,
        tenantId: str = "default",
        termUpserts: Optional[List[Dict[str, Any]]] = None,
        ruleRegistrations: Optional[List[Dict[str, Any]]] = None,
        factCandidates: Optional[List[Dict[str, Any]]] = None,
        createdBy: str = "",
        reason: str = "",
    ) -> Dict[str, Any]:
        """一批变更成版。返回 `{accepted, baselineId, applied, summary[, rejections]}`。"""
        tenant = str(tenantId or "default")
        termUpserts = list(termUpserts or [])
        ruleRegistrations = list(ruleRegistrations or [])
        factCandidates = list(factCandidates or [])
        for index, candidate in enumerate(factCandidates):
            if not str(candidate.get("subjectLabel") or "").strip() \
                    or not str(candidate.get("predicateTermId") or "").strip():
                raise ValueError(
                    "factCandidates[%d] 缺 subjectLabel/predicateTermId，无法 dry-run"
                    % index)

        # 非 default 租户的种子按本租户幂等补齐（与写咽喉首跳同款；default 已由
        # 注册表构造期种过）——这是基础设施补种，不属于"候选落盘"。
        if tenant != "default":
            self._validator.ensureTenantSeeds(tenant)
            self._engine.ensureRuleSeeds(tenant)

        # ① 先全部 dry-run：任一违规整批拒绝，零落盘
        dryRunRows = dryRunFactCandidates(
            self._store, agentId, tenant, factCandidates,
            registry=self._registry, report=self._validator)
        rejections = [row for row in dryRunRows if row["violations"]]
        if rejections:
            return {
                "accepted": False,
                "baselineId": "",
                "applied": {"terms": 0, "rules": 0, "facts": 0},
                "rejections": rejections,
                "summary": "整批拒绝：%d/%d 条候选事实违规，零落盘"
                           % (len(rejections), len(dryRunRows)),
            }

        # ② 依次应用术语 upsert 与规则登记（registerRule 只登记，不触发求值）
        appliedTermIds: List[str] = []
        appliedRuleIds: List[str] = []
        try:
            for spec in termUpserts:
                term = self._registry.register(
                    str(spec.get("termId") or "").strip(),
                    str(spec.get("kind") or "").strip(),
                    label=str(spec.get("label") or ""),
                    parentTermId=spec.get("parentTermId"),
                    domain=spec.get("domain"), rangeTerms=spec.get("rangeTerms"),
                    rangeKinds=spec.get("rangeKinds"),
                    cardinality=spec.get("cardinality"),
                    disjointWith=spec.get("disjointWith"),
                    requiredProps=spec.get("requiredProps"),
                    version=str(spec.get("version") or "v1"), tenantId=tenant)
                appliedTermIds.append(term["term_id"])
            for spec in ruleRegistrations:
                rule = self._engine.registerRule(
                    str(spec.get("ruleId") or "").strip(),
                    str(spec.get("headPredicate") or "").strip(),
                    list(spec.get("body") or []),
                    headSubjectVar=str(spec.get("headSubjectVar") or "X"),
                    headObjectConst=str(spec.get("headObjectConst") or ""),
                    enabled=bool(spec.get("enabled", True)),
                    version=str(spec.get("version") or "v1"), tenantId=tenant)
                appliedRuleIds.append(rule["rule_id"])
        except ValueError as exc:
            rollback = self._rollbackApplied(appliedTermIds, appliedRuleIds, tenant)
            raise ValueError(
                "本体流水线应用失败，本批已回滚（不落半态）：%s；回滚回执：%s"
                % (exc, json.dumps(rollback, ensure_ascii=False))) from exc

        applied = {"terms": len(appliedTermIds), "rules": len(appliedRuleIds),
                   "facts": len(factCandidates)}

        # ③ 基线快照：应用后的 terms/rules 全量声明（回滚点即发布点）
        baselineId = "kb_%s" % uuid.uuid4().hex[:12]
        snapshot = {
            "terms": self._registry.terms(tenantId=tenant),
            "rules": self._engine.rules(tenantId=tenant),
            "agentId": str(agentId or ""),
            "applied": applied,
        }
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "INSERT INTO knowledge_baselines (baseline_id, scope, scope_key,"
                " snapshot_json, created_by, reason, created_at, tenant_id)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (baselineId, ONTOLOGY_PIPELINE_SCOPE, str(agentId or ""),
                 json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                 str(createdBy or ""), str(reason or ""), _now(), tenant))
        return {
            "accepted": True,
            "baselineId": baselineId,
            "applied": applied,
            "summary": "应用术语 %d 条、规则 %d 条；候选事实 %d 条 dry-run 全部通过，"
                       "基线已冻结" % (len(appliedTermIds), len(appliedRuleIds),
                                       len(factCandidates)),
        }

    def _rollbackApplied(self, appliedTermIds: List[str], appliedRuleIds: List[str],
                         tenantId: str) -> Dict[str, Any]:
        """应用中途失败的补偿：逆序撤掉本批已登记的规则与术语。"""
        failures: List[Dict[str, Any]] = []
        for ruleId in reversed(appliedRuleIds):
            try:
                self._engine.dropRule(ruleId, "本体流水线应用失败回滚", tenantId=tenantId)
            except Exception as exc:  # noqa: BLE001 — 回滚失败点名，不静默
                failures.append({"kind": "rule", "id": ruleId, "reason": str(exc)})
        for termId in reversed(appliedTermIds):
            try:
                self._registry.dropTerm(termId, tenantId=tenantId)
            except Exception as exc:  # noqa: BLE001 — 回滚失败点名，不静默
                failures.append({"kind": "term", "id": termId, "reason": str(exc)})
        return {"terms": list(appliedTermIds), "rules": list(appliedRuleIds),
                "failures": failures}

    def diff(self, fromBaselineId: str,
             toBaselineId: Optional[str] = None) -> Dict[str, Any]:
        """两基线间 terms/rules 差异；`toBaselineId` 缺省对比当前实况（toState=live）。"""
        fromRow = self._store.baseline(str(fromBaselineId or "").strip())
        if fromRow is None:
            raise LookupError("基线不存在: %s" % fromBaselineId)
        if str(fromRow.get("scope") or "") != ONTOLOGY_PIPELINE_SCOPE:
            raise ValueError(
                "基线 %s 不是本体流水线基线（scope=%r）——事实基线不参与 terms/rules diff"
                % (fromBaselineId, fromRow.get("scope")))
        tenant = str(fromRow.get("tenant_id") or "default")
        fromSnapshot = fromRow.get("snapshot") or {}
        if toBaselineId:
            toRow = self._store.baseline(str(toBaselineId).strip())
            if toRow is None:
                raise LookupError("基线不存在: %s" % toBaselineId)
            if str(toRow.get("scope") or "") != ONTOLOGY_PIPELINE_SCOPE:
                raise ValueError(
                    "基线 %s 不是本体流水线基线（scope=%r）"
                    % (toBaselineId, toRow.get("scope")))
            if str(toRow.get("tenant_id") or "default") != tenant:
                raise ValueError(
                    "跨租户基线 diff 拒绝：%s（%s）vs %s（%s）"
                    % (fromBaselineId, tenant, toBaselineId, toRow.get("tenant_id")))
            toState = "baseline"
            toTerms = (toRow.get("snapshot") or {}).get("terms") or []
            toRules = (toRow.get("snapshot") or {}).get("rules") or []
            toBaselineOut = str(toRow.get("baseline_id") or "")
        else:
            toState = "live"
            toTerms = self._registry.terms(tenantId=tenant)
            toRules = self._engine.rules(tenantId=tenant)
            toBaselineOut = ""

        def delta(fromRows: List[Dict[str, Any]], toRows: List[Dict[str, Any]],
                  idKey: str, fields: tuple) -> Dict[str, Any]:
            fromMap = {row[idKey]: row for row in fromRows}
            toMap = {row[idKey]: row for row in toRows}
            projection = lambda row: {name: row.get(name) for name in fields}
            added = sorted(set(toMap) - set(fromMap))
            removed = sorted(set(fromMap) - set(toMap))
            changed = [
                {"id": key, "from": projection(fromMap[key]),
                 "to": projection(toMap[key])}
                for key in sorted(set(fromMap) & set(toMap))
                if projection(fromMap[key]) != projection(toMap[key])]
            return {"added": added, "removed": removed, "changed": changed}

        return {
            "fromBaselineId": str(fromRow.get("baseline_id") or ""),
            "toBaselineId": toBaselineOut,
            "toState": toState,
            "tenantId": tenant,
            "terms": delta(fromSnapshot.get("terms") or [], toTerms,
                           "term_id", self._TERM_DIFF_FIELDS),
            "rules": delta(fromSnapshot.get("rules") or [], toRules,
                           "rule_id", self._RULE_DIFF_FIELDS),
        }
