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
    """咽喉段3 前半：写入前的结构校验。`violations` 非空即不得入库。"""

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def violations(self, request: Any, subjectKey: str) -> List[Dict[str, Any]]:
        """只回 violation 那条子集——`unregistered` 是"这一维免检"，不是不合法。"""
        return [f for f in self.findings(request, subjectKey) if f["kind"] == "violation"]

    def findings(self, request: Any, subjectKey: str) -> List[Dict[str, Any]]:
        registry = self._registry
        predicate = getattr(request, "predicateTermId", "") or ""
        agentId = getattr(request, "agentId", "") or ""
        subjectKey = subjectKey or ""
        if not predicate:
            return []
        qualifier = getattr(request, "qualifier", None) or {}
        out: List[Dict[str, Any]] = []
        term = registry.term(predicate)

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
            domain = registry.domainOf(predicate)
            if domain and not registry.matchesDomain(subjectType, domain):
                out.append(self._finding(
                    "violation", "domain",
                    "主体类型 %s 不在 %s 的定义域 %s 内" % (subjectType, predicate, domain),
                    predicate, subjectKey=subjectKey))

        rangeTerms = registry.rangeOf(predicate) if term else []
        objectTerm = str(getattr(request, "objectTerm", "") or "")
        if rangeTerms:
            objectType = registry.term(objectTerm)
            if objectType is None:
                out.append(self._finding(
                    "unregistered", "range",
                    "客体 %r 不是已登记术语，值域 %s 无法核对" % (objectTerm, rangeTerms),
                    predicate, subjectKey=subjectKey))
            elif not registry.matchesDomain(objectTerm, rangeTerms):
                out.append(self._finding(
                    "violation", "range",
                    "客体 %s 不在 %s 的值域 %s 内" % (objectTerm, predicate, rangeTerms),
                    predicate, subjectKey=subjectKey))

        # 父子一致性：主体类型的**祖先链**每一环都还得在表里。悬空边只能来自存量或手工
        # 改库（register 已挡新登记），链成环同理——不追就会被 isSubtypeOf 无限绕。
        for declared in registry.assertedTypesOf(agentId, subjectKey):
            chain: List[str] = []
            cursor = registry.term(declared)
            while cursor and cursor.get("parent_term_id"):
                parent = cursor["parent_term_id"]
                if parent in chain:
                    out.append(self._finding(
                        "violation", "parentConsistency",
                        "%s 的父类链成环（回到 %s）" % (declared, parent), predicate,
                        subjectKey=subjectKey))
                    break
                chain.append(parent)
                cursor = registry.term(parent)
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
                if right in registry.disjointWith(left):
                    out.append(self._finding(
                        "violation", "disjoint",
                        "主体同时被断言为不相交类型 %s 与 %s" % (left, right), predicate,
                        subjectKey=subjectKey))

        required = [p for p in (registry.requiredProps(predicate) if term else [])
                    if not str(qualifier.get(p, "") or "").strip()]
        if required:
            out.append(self._finding(
                "violation", "requiredProps",
                "%s 缺必填属性 %s" % (predicate, required), predicate, subjectKey=subjectKey))

        limit = registry.maxCardinality(predicate) if term else None
        if limit == 1 and subjectKey:
            rivals = [f for f in registry.activeFactsForPredicate(agentId, subjectKey, predicate)
                      if str(f.get("object_term")) != objectTerm]
            if rivals:
                out.append(self._finding(
                    "violation", "cardinality",
                    "%s 基数为 1，主体已有另一说法（fact_id=%s）"
                    % (predicate, rivals[0]["fact_id"]), predicate, subjectKey=subjectKey))
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
