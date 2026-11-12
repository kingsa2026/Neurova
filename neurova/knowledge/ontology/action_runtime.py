"""动作运行时（specs/2026-11-12 §6 W4）：动作语义的求值与两段执行。

门面（MCP ontology_act / REST）只做接线，语义在本模块：
- **precondition 求值**（只读）：`facts` 存在性（subjectParam 从动作参数解析，
  op=equals/exists）＋ `expr` 函数比较（复用 function_eval 只读求值——D1 行数
  上限与谓词在册判据自动继承）。不满足 → `ActionPreconditionError`，**不触工具**。
- **工具执行**：转交注入的 executor.execute（ToolExecutor.execute 单管道——
  治理预检/审批/审计/mcp_grants 全继承，本模块零复制判定语义，D5 已裁）。
- **state_change**：工具成功后经 admission 写 has_state（W3 迁移约束自动继承——
  非法迁移 → 回执诚实失败，工具执行与状态写是两段，如实呈现）。
- 回执：impact 声明＋工具结果＋state_change 读数＋fact_id/溯源。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_HAS_STATE_PREDICATE = "has_state"


class ActionPreconditionError(ValueError):
    """前置条件不满足——显式拒，不触工具。"""


def evaluatePrecondition(action: Dict[str, Any], params: Dict[str, Any],
                         store: Any, agentId: str, tenantId: str) -> None:
    """前置求值：facts 存在性＋expr 函数比较。不满足即抛 ActionPreconditionError。"""
    precondition = action.get("precondition") or {}
    from .term_registry import OntologyTermRegistry

    termRegistry = OntologyTermRegistry(store)
    for spec in precondition.get("facts") or []:
        predicate = str((spec or {}).get("predicate") or "").strip()
        subjectParam = str((spec or {}).get("subjectParam") or "").strip()
        op = str((spec or {}).get("op") or "exists").strip()
        expected = (spec or {}).get("value")
        subjectKey = ""
        if subjectParam:
            label = str((params or {}).get(subjectParam) or "").strip()
            if label:
                key = store.resolveSubjectKey(agentId, label, tenantId=tenantId) \
                    if hasattr(store, "resolveSubjectKey") else ""
                row = None
                with store._lock:
                    row = store._conn.execute(
                        "SELECT subject_key FROM knowledge_subjects"
                        " WHERE agent_id = ? AND tenant_id = ? AND normalized_label = ?"
                        " AND status = 'active'",
                        (agentId, tenantId, label.casefold())).fetchone()
                subjectKey = str(row["subject_key"]) if row is not None else ""
        facts = termRegistry.activeFactsForPredicate(
            agentId, subjectKey, predicate) if subjectKey else []
        if op == "equals" and expected is not None:
            ok = any(str(f.get("object_term")) == str(expected) for f in facts)
        else:
            ok = bool(facts)
        if not ok:
            raise ActionPreconditionError(
                "前置不满足：%s 在主体 %r 上 %s%s（动作 %s 不执行工具）"
                % (predicate, subjectParam or "*", op,
                   "，期望 %r" % expected if op == "equals" else "",
                   action.get("action_id")))
    expr = str(precondition.get("expr") or "").strip()
    if expr:
        from .function_eval import (
            SelectorCapError,
            compileFunction,
            evaluateFunction,
            makeSelectorRunner,
        )

        from .term_registry import OntologyTermRegistry as _OTR

        allowedPredicates = tuple(str(t.get("term_id") or "") for t in
                                  _OTR(store).terms(kind="relation", tenantId=tenantId))
        compiled = compileFunction(expr, allowedPredicates=allowedPredicates)
        runner = makeSelectorRunner(store, agentId=agentId, tenantId=tenantId)
        try:
            value = evaluateFunction(compiled, {}, runner)
        except SelectorCapError as exc:
            raise ActionPreconditionError(str(exc))
        if not value:
            raise ActionPreconditionError(
                "前置函数 %r 求值为 %r（动作 %s 不执行工具）"
                % (expr, value, action.get("action_id")))


async def executeAction(action: Dict[str, Any], params: Dict[str, Any],
                        executor: Any, store: Any, agentId: str,
                        tenantId: str = "default",
                        machineRegistry: Any = None) -> Dict[str, Any]:
    """动作两段执行：前置求值 → 工具（单管道）→ state_change 经 admission。

    `executor` 是注入的执行器（ToolExecutor.execute 同契约）——治理链全在
    executor 内，本函数零复制。`machineRegistry` 可注入替身（测试）；缺省
    StateMachineRegistry(store)。"""
    params = dict(params or {})
    evaluatePrecondition(action, params, store, agentId, tenantId)
    boundTool = str(action.get("bound_tool") or "")
    result = await executor.execute(boundTool, params)
    ok = bool(result) and not result.get("error") and result.get("success") is not False
    receipt: Dict[str, Any] = {
        "action_id": action.get("action_id"),
        "bound_tool": boundTool,
        "impact": list(action.get("impact") or []),
        "executed": ok,
        "tool_result": result,
    }
    if not ok:
        return receipt
    stateChange = action.get("state_change") or {}
    if stateChange:
        subjectParam = str(stateChange.get("subjectParam") or "").strip()
        toState = str(stateChange.get("toState") or "").strip()
        subjectLabel = str(params.get(subjectParam) or "").strip()
        if machineRegistry is None:
            from .state_machine_registry import StateMachineRegistry

            machineRegistry = StateMachineRegistry(store)
        factId = ""
        detail = ""
        if not subjectLabel:
            detail = "state_change.subjectParam %r 在动作参数中缺失" % subjectParam
        else:
            from ..foundation.admission import AdmissionRequest, productionAdmissionGate

            gate = productionAdmissionGate(store, toolVersion="ontology_act")
            content = "%s has_state %s（动作 %s 执行后状态写入）" % (
                subjectLabel, toState, action.get("action_id"))
            try:
                receiptRow = gate.admit(AdmissionRequest(
                    agentId=agentId, tenantId=tenantId,
                    subjectLabel=subjectLabel, predicateTermId=_HAS_STATE_PREDICATE,
                    objectTerm=toState, content=content,
                    assertions=[{"actorType": "pipeline",
                                 "actorId": "action:%s" % action.get("action_id"),
                                 "mediumRef": "action:%s" % action.get("action_id"),
                                 "statementText": content}],
                    activityKind="admit",
                    activityBasis="action_runtime.executeAction（动作 %s 的 state_change）"
                                  % action.get("action_id")))
                factId = receiptRow.factId
            except ValueError as exc:
                detail = str(exc)  # W3 迁移约束继承：非法迁移诚实失败
        current = ""
        if subjectLabel:
            row = None
            with store._lock:
                row = store._conn.execute(
                    "SELECT s2.canonical_label, f.object_term FROM knowledge_facts f"
                    " JOIN knowledge_subjects s2 ON s2.subject_key = f.subject_key"
                    " WHERE s2.agent_id = ? AND s2.canonical_label = ?"
                    " AND f.predicate_term_id = ? AND f.status = 'active'"
                    " AND f.agent_id = ? ORDER BY f.recorded_at DESC LIMIT 1",
                    (agentId, subjectLabel, _HAS_STATE_PREDICATE, agentId)).fetchone()
            current = str(row["object_term"]) if row is not None else ""
        receipt["state_change"] = {
            "ok": bool(factId), "fact_id": factId, "detail": detail,
            "to_state": toState, "current_state": current,
        }
    return receipt
