"""函数引擎（specs/2026-11-12 §4 W2）：FunctionEngine.fireFor 与 ForwardChainingEngine
同契约（agentId, predicate, tenantId）——由 admission dispatch 唯一接线点点燃。

- 结论落库：派生事实 `(subject, output_predicate, 数值)` 经 gateFactory 进
  admission 唯一咽喉（rule_engine._admitDerivedFact 同款先例），qualifier 带
  `derived_by=function:<id>` 与物化档标注；推导账本记
  `knowledge_derivation_edges`（source_kind=function）＋`ontology_rule_fires`
  同款行（rule_id 位写 function:<id>）——**不建第二账本**。
- 物化档 observe/enforce 复用 v35 语义：缺省 observe＝只作解释链/审计
  （derivedExclusionClause 的 source_kind 分支把它摘出检索主路），enforce 才进。
- dryEval：ontology_compute 的只读承载——返回值＋输入快照＋表达式回显，零落库。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_SUBJECT_FIRE_CAP = 500


class FunctionEngine:
    """与 ForwardChainingEngine 同契约的函数求值引擎（同一咽喉、同一账本）。"""

    def __init__(self, store: Any, gateFactory: Any = None) -> None:
        self._store = store
        self._gateFactory = gateFactory

    # ── 求值 ──────────────────────────────────────────────────

    def fireFor(self, agentId: str, predicate: str,
                tenantId: str = "default") -> List[str]:
        """点燃依赖 `predicate` 的已启用函数：对有该谓词事实的主体逐一求值。

        依赖来自登记时写进 scope_json['depends_on'] 的 selector 静态依赖。"""
        produced: List[str] = []
        for fn in self._functions(tenantId=tenantId):
            if predicate not in (fn.get("scope") or {}).get("depends_on", []):
                continue
            for subjectKey in self._subjectsFor(agentId, predicate, tenantId):
                factId = self._fireFunction(fn, agentId, subjectKey, tenantId)
                if factId:
                    produced.append(factId)
        return produced

    def dryEval(self, functionId: str, subject: str = "",
                tenantId: str = "default",
                bindings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """只读 dry 求值（ontology_compute 承载）：零落库，带输入快照与表达式回显。"""
        from .function_registry import FunctionRegistry

        fn = FunctionRegistry(self._store).get(functionId, tenantId=tenantId)
        if fn is None:
            raise LookupError("函数未登记: %s" % functionId)
        agentId = "default"
        compiled, runner = self._compile(fn, agentId, tenantId)
        merged = dict(fn.get("input_bindings") or {})
        merged.update({k: self._bindingValue(v, subject) for k, v in merged.items()})
        merged.update(dict(bindings or {}))
        from .function_eval import SelectorCapError, evaluateFunction

        inputs = self._inputSnapshot(agentId, fn, merged, tenantId, runner)
        try:
            value = evaluateFunction(compiled, merged, runner)
        except SelectorCapError as exc:
            return {"function_id": functionId, "expr_text": fn["expr_text"],
                    "rejected": True, "detail": str(exc)}
        return {"function_id": functionId, "expr_text": fn["expr_text"],
                "value": value, "inputs": inputs,
                "materialization": fn.get("materialization")}

    # ── 内部 ──────────────────────────────────────────────────

    def _functions(self, tenantId: str) -> List[Dict[str, Any]]:
        from .function_registry import FunctionRegistry

        return FunctionRegistry(self._store).list(tenantId=tenantId)

    def _compile(self, fn: Dict[str, Any], agentId: str, tenantId: str):
        from .function_eval import makeSelectorRunner

        allowed = tuple((fn.get("input_bindings") or {}).keys())
        compiled = self._compiledCache(fn, allowed, tenantId)
        runner = makeSelectorRunner(self._store, agentId=agentId, tenantId=tenantId)
        return compiled, runner

    def _compiledCache(self, fn: Dict[str, Any], allowed: Tuple[str, ...],
                       tenantId: str):
        """编译结果按 (expr, bindings, version) 进程内缓存——fireFor 高频重入。"""
        cache = getattr(self, "_compileCache", None)
        if cache is None:
            cache = self._compileCache = {}
        key = (fn["expr_text"], tuple(sorted(allowed)), fn.get("version"))
        hit = cache.get(key)
        if hit is not None:
            return hit
        from .function_eval import compileFunction

        from .term_registry import OntologyTermRegistry

        registry = OntologyTermRegistry(self._store)
        allowedPredicates = tuple(str(t.get("term_id") or "") for t in
                                  registry.terms(kind="relation", tenantId=tenantId))
        compiled = compileFunction(fn["expr_text"], allowedNames=allowed,
                                   allowedPredicates=allowedPredicates)
        cache[key] = compiled
        return compiled

    def _subjectsFor(self, agentId: str, predicate: str, tenantId: str) -> List[str]:
        """依赖谓词上有 active 事实的主体（规范标签作 subject 绑定值）。"""
        sql = ("SELECT DISTINCT s.canonical_label FROM knowledge_facts f"
               " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
               " WHERE f.predicate_term_id = ? AND f.status = 'active'"
               " AND f.record_kind = 'triple' AND f.agent_id = ? AND s.agent_id = ?")
        params: List[Any] = [predicate, agentId, agentId]
        if tenantId:
            sql += " AND f.tenant_id = ? AND s.tenant_id = ?"
            params.extend([str(tenantId or "default"), str(tenantId or "default")])
        sql += " LIMIT ?"
        params.append(_SUBJECT_FIRE_CAP)
        with self._store._lock:
            rows = self._store._conn.execute(sql, params).fetchall()
        return [str(r["canonical_label"]) for r in rows]

    def _bindingValue(self, declared: Any, subject: str) -> Any:
        """input_bindings 值语义：'subject' 名义绑当前主体规范标签（W2 主语变元）。"""
        if isinstance(declared, str) and declared.casefold() in ("subject", "仓库"):
            return subject
        return declared

    def _inputSnapshot(self, agentId: str, fn: Dict[str, Any],
                       bindings: Dict[str, Any], tenantId: str,
                       runner: Any = None) -> Dict[str, Any]:
        """dry 求值的输入快照：每个 selector 的命中行数（数值明细不展开，量值敏感面）。"""
        if runner is None:
            _, runner = self._compile(fn, agentId, tenantId)
        snapshot: Dict[str, Any] = {}
        from .function_eval import SELECTOR_ROW_CAP

        for predicate in (fn.get("scope") or {}).get("depends_on", []):
            try:
                snapshot[predicate] = runner({"predicate": predicate}, bindings).matchedCount
            except Exception as exc:  # noqa: BLE001 - 快照失败如实记名
                snapshot[predicate] = "error: %s" % exc
        snapshot["selector_row_cap"] = SELECTOR_ROW_CAP
        return snapshot

    def _fireFunction(self, fn: Dict[str, Any], agentId: str, subject: str,
                      tenantId: str) -> Optional[str]:
        """单函数单主体求值并经咽喉落结论；求值失败/None 结论如实跳过不落。

        溯源前提＝本次求值实际消费的事实（selector 命中行），与结论一起进
        推导账本——删函数/改函数按源撤销才有依据。"""
        gate = self._gateFactory(self._store) if self._gateFactory else None
        if gate is None:
            from ..foundation.admission import productionAdmissionGate

            gate = productionAdmissionGate(self._store)
        compiled, baseRunner = self._compile(fn, agentId, tenantId)
        premiseBox: List[str] = []

        def runner(selector: Dict[str, Any], bindings: Dict[str, Any]):
            result = baseRunner(selector, bindings)
            premiseBox.extend(result.factIds)
            return result

        bindings = {k: self._bindingValue(v, subject)
                    for k, v in (fn.get("input_bindings") or {}).items()}
        from .function_eval import evaluateFunction

        try:
            value = evaluateFunction(compiled, bindings, runner)
        except Exception as exc:  # noqa: BLE001 - 单函数失败不连坐其他函数，但必须留名
            logger.warning("function_engine: 函数 %s 对主体 %s 求值失败: %s",
                           fn["function_id"], subject, exc)
            return None
        if value is None:
            return None  # 空集 avg/min/max：诚实不猜，不出结论
        functionRef = "function:%s" % fn["function_id"]
        objectTerm = self._formatValue(value)
        from ..foundation.admission import AdmissionRequest

        content = "%s %s %s（由函数 %s 推出）" % (
            subject, fn["output_predicate"], objectTerm, fn["function_id"])
        try:
            receipt = gate.admit(AdmissionRequest(
                agentId=agentId or "default", tenantId=str(tenantId or "default"),
                subjectLabel=subject, predicateTermId=str(fn["output_predicate"]),
                objectTerm=objectTerm, content=content,
                qualifier={"derived_by": functionRef,
                           "materialization": str(fn.get("materialization") or "observe"),
                           "value": float(value)},
                assertions=[{"actorType": "pipeline", "actorId": functionRef,
                             "mediumRef": functionRef, "statementText": content}],
                activityKind="derive",
                activityBasis="FunctionEngine._fireFunction（函数 %s 推导）"
                              % fn["function_id"]))
        except ValueError:
            return None  # 本体/基数拒绝推导结果：与原始写入同一口径，不开例外
        ledger = self._store._derivationLedger
        ruleLike = {"rule_id": functionRef, "version": fn.get("version") or "v1",
                    "stratification_level": 0,
                    "head_predicate": str(fn["output_predicate"])}
        premises = list(dict.fromkeys(premiseBox))
        if receipt.dedupedByContent:
            if (self._store.fact(receipt.factId) or {}).get("status") != "retracted":
                return None
            self._store.reviveRetracted(receipt.factId, reason="函数前提重新齐备")
            ledger.recordDerivation(receipt.factId, premises, ruleLike, sourceKind="function")
            ledger.recordFire(ruleLike, [receipt.factId])
            return receipt.factId
        ledger.recordDerivation(receipt.factId, premises, ruleLike, sourceKind="function")
        ledger.recordFire(ruleLike, [receipt.factId])
        return receipt.factId

    @staticmethod
    def _formatValue(value: float) -> str:
        """结论客体＝数值文本：整值去小数尾，浮值 repr（parseQuantity 可回读）。"""
        if float(value).is_integer():
            return str(int(value))
        return repr(float(value))
