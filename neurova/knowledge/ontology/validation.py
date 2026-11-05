"""入库五条校验（工单 020，G08）：脏事实进不了底座。

五条都读同一张 `ontology_terms`，且都遵循同一条保守原则：**判不了就说判不了**。
主体没挂类型、客体不是已登记术语、限定信息缺失——这些都不构成违规，只记进
`unregistered` 面由巡检报出。把"没数据"报成"不合法"，注册表覆盖率一变，
写入的可用性就跟着抖，那不是治理是抽签。

违规一律带**定位串**（术语、主体、冲突对象），因为报错只说"不合法"等于让人重新
把整条链查一遍。
"""

from __future__ import annotations

from typing import Any, Dict, List

RULES = ("domain", "range", "parentConsistency", "disjoint", "cardinality", "requiredProps")


class OntologyValidationReport:
    """咽喉段3 前半：写入前的结构校验。`violations` 非空即不得入库。

    B10：构造时可注入 `ShapeRegistry`——用户 shape 的 findings 经同一求值器
    追加进本报告（violation 阻断 / warning 记账 / info 遥测）；不注入则只有
    内置 6 项（裸门与既有调用方零漂移）。
    """

    def __init__(self, registry: Any, shapes: Any = None) -> None:
        self._registry = registry
        self._shapes = shapes

    def ensureTenantSeeds(self, tenantId: str) -> None:
        """非 default 租户的种子谓词在写入首跳补齐（闸的调用点，不暴露注册表内部）。"""
        self._registry.ensureSeedPredicates(tenantId)

    def violations(self, request: Any, subjectKey: str) -> List[Dict[str, Any]]:
        """只回 violation 那条子集——`unregistered` 是"这一维免检"，不是不合法。"""
        return [f for f in self.findings(request, subjectKey) if f["kind"] == "violation"]

    def findings(self, request: Any, subjectKey: str) -> List[Dict[str, Any]]:
        registry = self._registry
        predicate = getattr(request, "predicateTermId", "") or ""
        agentId = getattr(request, "agentId", "") or ""
        # 本体按租户分区（v25）：五条校验只看本租户的类型表。
        tenantId = str(getattr(request, "tenantId", "") or "default")
        subjectKey = subjectKey or ""
        if not predicate:
            return []
        qualifier = getattr(request, "qualifier", None) or {}
        out: List[Dict[str, Any]] = []
        term = registry.term(predicate, tenantId=tenantId)

        if term is None:
            out.append(self._finding("unregistered", "term",
                                     "谓词 %s 未登记，五条校验对它免检" % predicate, predicate))
        if not subjectKey:
            return out

        subjectType = registry.subjectType(subjectKey)
        if subjectType is None:
            out.append(self._finding("unregistered", "domain",
                                     "主体 %s 未挂类型，定义域无法校验" % subjectKey, predicate))
        else:
            domain = registry.domainOf(predicate, tenantId=tenantId)
            if domain and not registry.matchesDomain(subjectType, domain, tenantId=tenantId):
                out.append(self._finding(
                    "violation", "domain",
                    "主体类型 %s 不在 %s 的定义域 %s 内" % (subjectType, predicate, domain),
                    predicate, subjectKey=subjectKey))

        rangeTerms = registry.rangeOf(predicate, tenantId=tenantId) if term else []
        objectTerm = str(getattr(request, "objectTerm", "") or "")
        if rangeTerms:
            objectType = registry.term(objectTerm, tenantId=tenantId)
            if objectType is None:
                out.append(self._finding(
                    "unregistered", "range",
                    "客体 %r 不是已登记术语，值域 %s 无法核对" % (objectTerm, rangeTerms),
                    predicate, subjectKey=subjectKey))
            elif not registry.matchesDomain(objectTerm, rangeTerms, tenantId=tenantId):
                out.append(self._finding(
                    "violation", "range",
                    "客体 %s 不在 %s 的值域 %s 内" % (objectTerm, predicate, rangeTerms),
                    predicate, subjectKey=subjectKey))

        # 父子一致性：主体类型的**祖先链**每一环都还得在表里。悬空边只能来自存量或手工
        # 改库（register 已挡新登记），链成环同理——不追就会被 isSubtypeOf 无限绕。
        for declared in registry.assertedTypesOf(agentId, subjectKey):
            chain: List[str] = []
            cursor = registry.term(declared, tenantId=tenantId)
            while cursor and cursor.get("parent_term_id"):
                parent = cursor["parent_term_id"]
                if parent in chain:
                    out.append(self._finding(
                        "violation", "parentConsistency",
                        "%s 的父类链成环（回到 %s）" % (declared, parent), predicate,
                        subjectKey=subjectKey))
                    break
                chain.append(parent)
                cursor = registry.term(parent, tenantId=tenantId)
                if cursor is None:
                    out.append(self._finding(
                        "violation", "parentConsistency",
                        "%s 声明的父类 %s 不存在" % (declared, parent), predicate,
                        subjectKey=subjectKey))
                    break

        # 不相交：同一主体被断言成两个互斥类型。判定看 is_a 断言集而不是那一列，
        # 因为"同时是 A 与 B"本来就写不进单列。
        declaredTypes = registry.assertedTypesOf(agentId, subjectKey)
        for index, left in enumerate(declaredTypes):
            for right in declaredTypes[index + 1:]:
                if right in registry.disjointWith(left, tenantId=tenantId):
                    out.append(self._finding(
                        "violation", "disjoint",
                        "主体同时被断言为不相交类型 %s 与 %s" % (left, right), predicate,
                        subjectKey=subjectKey))

        required = [p for p in (registry.requiredProps(predicate, tenantId=tenantId) if term else [])
                    if not str(qualifier.get(p, "") or "").strip()]
        if required:
            out.append(self._finding(
                "violation", "requiredProps",
                "%s 缺必填属性 %s" % (predicate, required), predicate, subjectKey=subjectKey))

        limit = registry.maxCardinality(predicate, tenantId=tenantId) if term else None
        if limit == 1 and subjectKey:
            rivals = [f for f in registry.activeFactsForPredicate(agentId, subjectKey, predicate)
                      if str(f.get("object_term")) != objectTerm]
            if rivals:
                out.append(self._finding(
                    "violation", "cardinality",
                    "%s 基数为 1，主体已有另一说法（fact_id=%s）"
                    % (predicate, rivals[0]["fact_id"]), predicate, subjectKey=subjectKey))

        # B11 L3：限定关系 schema——必填缺失=violation（写前阻断），
        # 未知键=warning（不阻断）；未声明 schema 的关系 qualifier 自由 JSON
        # （存量零漂移）。schema 读术语行的 qualifier_schema 列（v32），
        # 门是 schema 本身非空——不是 term 存在（否则全谓词误报未知键）。
        if term:
            schema = term.get("qualifier_schema") or {}
            if schema:
                allowed = schema.get("allowed") or {}
                required = schema.get("required") or []
                missing = [k for k in required if not str(qualifier.get(k, "") or "").strip()]
                if missing:
                    out.append(self._finding(
                        "violation", "qualifierSchema",
                        "%s 缺必填限定 %s" % (predicate, missing), predicate,
                        subjectKey=subjectKey))
                unknown = [k for k in qualifier if k not in allowed and k not in required]
                if unknown:
                    out.append(self._finding(
                        "warning", "qualifierSchema",
                        "%s 的限定键 %s 未在 schema 内" % (predicate, unknown), predicate,
                        subjectKey=subjectKey))

        # B9 punning 守卫：term_id 当 subject_key 用（类型与实例混用）——本体腐化
        # 的起点。记 warning 不阻断：存量同名共存是显式选择，写面硬拒会把迁移卡死。
        # violations() 只收 violation，warning 进巡检读数。
        if subjectKey and registry.term(subjectKey, tenantId=tenantId) is not None:
            out.append(self._finding(
                "warning", "punning",
                "主体 %s 与已登记术语同名（term/instance 混用）" % subjectKey,
                predicate, subjectKey=subjectKey))

        # B10 L4：用户 shape 与内置 6 项共用同一 findings 流（violation 阻断/
        # warning 记账/info 遥测）；shape 只判数据，不触发推导。
        if self._shapes is not None:
            out.extend(self._shapes.evaluateForRequest(request, subjectKey, registry))
        return out

    @staticmethod
    def _finding(kind: str, rule: str, message: str, term: str,
                 subjectKey: str = "") -> Dict[str, Any]:
        return {"kind": kind, "rule": rule, "message": message,
                "term_id": term, "subject_key": subjectKey}

    @staticmethod
    def summarize(findings: List[Dict[str, Any]]) -> str:
        if not findings:
            return "本体校验无发现"
        return "；".join("%s[%s] %s" % (f["kind"], f["rule"], f["message"]) for f in findings)
