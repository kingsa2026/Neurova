# -*- coding: utf-8 -*-
"""U3 批量装载契约：`bulkLoadFacts` —— 事实行批量过咽喉的两段式装载体。

定位（不新造平行体系，只编排既有单点实现）：
  * **逐行仍走准入咽喉，绝不绕行**：第二段落库只调 `KnowledgeAdmissionGate.admit`，
    与单条写入同一条路径；本模块不复制任何一段准入判定。
  * **第一段（只读校验）**：必填项与逐字可核闸直接调咽喉自己的
    `_validate` / `_checkVerifiability`；本体校验复用唯一干跑路径
    `pipeline.dryRunFactCandidates`（B2 只读出口与 B6 流水线同源），
    按 (agentId, tenantId) 分组复用，不自造第二套判定。
  * **整批原子**：任一行在第一段被判不合法 → 整个装载零落盘，回执点名
    违规行号（0-based）与原因；不是只回滚违规所在批。
  * **第二段同边界**：第二段是"校验通过后仍失败"的兜底（理论上不该发生，
    例如批内先后依赖构成的基数冲突，只读干跑看不见）。整段套 foundation
    既有 `batchScope`（SAVEPOINT）——一旦发生立即停批，整批未提交的写入
    一次退净，不留半截事实/断言/推导；不靠事后补偿撤销（它撤不干净
    状态迁移与链式推导）。
  * **线程安全**：不引入新锁；行级写入的串行化由 store 既有 RLock 语义承担。
    极端并发下（他线程与本批同内容并发写入且本批恰在此时补偿）快照判新可能
    把他线程的新行误认作本批所写——那是共享库并发写同内容的病态场景，与
    `admitBatch` 的并发边界一致，不在此另立锁解决。
"""

from __future__ import annotations

from dataclasses import fields as dataclassFields
from dataclasses import replace as dataclassReplace
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.knowledge.foundation.admission import (
    NARRATIVE_PREDICATE,
    NARRATIVE_RECORD_KIND,
    AdmissionError,
    AdmissionRequest,
    AdmissionSegmentMissing,
    KnowledgeAdmissionGate,
    productionAdmissionGate,
)
from neurova.knowledge.ontology.pipeline import dryRunFactCandidates
from neurova.knowledge.ontology.shapes import ShapeRegistry
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.ontology.validation import OntologyValidationReport

__all__ = ["bulkLoadFacts"]

#: 行字段白名单 = AdmissionRequest 的字段名（单一事实源，不另立清单）
_ROW_FIELDS = frozenset(f.name for f in dataclassFields(AdmissionRequest))
_DEFAULT_BATCH_SIZE = 500


def bulkLoadFacts(
    store: Any,
    rows: List[Dict[str, Any]],
    *,
    batchSize: int = _DEFAULT_BATCH_SIZE,
    onProgress: Optional[Callable[[int, int], None]] = None,
    dryRun: bool = True,
    gate: Any = None,
) -> Dict[str, Any]:
    """批量装载事实行：第一段全量只读校验，第二段逐行经咽喉 admit 落库。

    参数：
      * `rows`：行 dict 列表，键名为 `AdmissionRequest` 的字段（camelCase）——
        agentId / tenantId / subjectLabel / predicateTermId / objectTerm /
        content / qualifier 等。行未带 `assertions` 时由装载器代为声明
        （actorType=pipeline, actorId=bulk_load），并如实挂账来路
        （activityBasis=ontology.bulkLoadFacts），满足血缘段"不接受匿名知识"。
      * `batchSize`：第二段逐行 admit 的分批粒度（只影响提交节奏与回调次数），
        缺省 500。
      * `onProgress(done, total)`：每批结束回调一次，done 为已处理行数、
        total 为总行数；批数 = ceil(n/batchSize)。rows 为空时不回调。
      * `dryRun=True`：只跑第一段，零写入，回执带 `precheck` 逐行预检摘要。
      * `gate`：准入咽喉实例；缺省在内部调 `productionAdmissionGate(store)`
        按生产口径装配。

    返回回执：`{total, admitted, failed: [{index, reason}], dryRun}`；
    dry-run 另带 `precheck: [{index, verdict, violations}]`。成功时 failed=[]。

    任何一行不合法（结构、必填、逐字可核、本体 violation）→ 整批零落盘；
    第二段若仍有异常行 → 立即停批，整批经 batchScope 事务回滚零落盘，
    回执仍判 failed。
    """
    if isinstance(batchSize, bool) or not isinstance(batchSize, int) or batchSize < 1:
        raise ValueError("batchSize 必须是 >= 1 的整数，得到 %r" % (batchSize,))
    if onProgress is not None and not callable(onProgress):
        raise TypeError("onProgress 必须可调用，签名 onProgress(done, total)，得到 %r"
                        % (onProgress,))
    rowList = list(rows or [])
    total = len(rowList)
    if total == 0:
        receipt: Dict[str, Any] = {"total": 0, "admitted": 0, "failed": [],
                                   "dryRun": bool(dryRun)}
        if dryRun:
            receipt["precheck"] = []
        return receipt

    gate = gate if gate is not None else productionAdmissionGate(store)
    # 咽喉装配缺段就当场点名：带病装配装到第二段才炸，只会留下更难归因的半截数据
    pending = gate.pendingSegments()
    if pending:
        raise AdmissionSegmentMissing(pending)

    failed, precheck, requests = _precheckRows(store, rowList)
    if failed or dryRun:
        receipt = {"total": total, "admitted": 0, "failed": failed,
                   "dryRun": bool(dryRun)}
        if dryRun:
            receipt["precheck"] = precheck
        return receipt
    return _admitAll(store, gate, requests, total, batchSize, onProgress)


def _rowToRequest(row: Any) -> AdmissionRequest:
    """行 dict → AdmissionRequest。未知字段 / 形状不符当场报错，不静默吞。"""
    if not isinstance(row, dict):
        raise ValueError("行必须是 dict（键值映射），得到 %s" % type(row).__name__)
    unknown = sorted(str(key) for key in set(row) - _ROW_FIELDS)
    if unknown:
        raise ValueError("行含未知字段: %s（只收 AdmissionRequest 字段: %s）"
                         % (", ".join(unknown), ", ".join(sorted(_ROW_FIELDS))))
    payload = {name: row[name] for name in _ROW_FIELDS if name in row}
    qualifier = payload.get("qualifier")
    if qualifier is None:
        payload["qualifier"] = {}
    elif not isinstance(qualifier, dict):
        raise ValueError("qualifier 必须是 dict，得到 %s" % type(qualifier).__name__)
    for listField in ("aliases", "assertions"):
        value = payload.get(listField)
        if value is not None and not isinstance(value, list):
            raise ValueError("%s 必须是 list，得到 %s"
                             % (listField, type(value).__name__))
    request = AdmissionRequest(**payload)
    if not request.assertions:
        # 血缘段硬要求非匿名；行未声明断言时由装载器代声明，正文取本行内容
        statement = str(request.content or "").strip() or "%s %s %s" % (
            request.subjectLabel, request.predicateTermId, request.objectTerm)
        request = dataclassReplace(request, assertions=[{
            "actorType": "pipeline", "actorId": "bulk_load",
            "mediumRef": "bulk_load", "statementText": statement,
        }])
    if not str(request.activityKind or "").strip():
        request = dataclassReplace(request, activityKind="admit")
    if not str(request.activityBasis or "").strip():
        request = dataclassReplace(request,
                                   activityBasis="ontology.bulkLoadFacts（批量装载）")
    return request


def _effectivePredicate(request: AdmissionRequest) -> str:
    """咽喉对叙述记录固定谓词（admission._normalizedRecord 同判），干跑同口径。"""
    if request.recordKind == NARRATIVE_RECORD_KIND:
        return NARRATIVE_PREDICATE
    return request.predicateTermId


def _precheckRows(store: Any, rowList: List[Dict[str, Any]]):
    """第一段：全量只读校验。返回 (failed, precheck, requests)。

    判据全部同源：结构/必填用咽喉 `_validate`，逐字可核用 `_checkVerifiability`，
    本体五条+shape 用唯一干跑路径 `dryRunFactCandidates`。本函数零写入。
    """
    total = len(rowList)
    requests: List[Optional[AdmissionRequest]] = [None] * total
    problems: List[List[str]] = [[] for _ in range(total)]
    ontologyChecked = [False] * total

    for index, row in enumerate(rowList):
        try:
            requests[index] = _rowToRequest(row)
        except ValueError as exc:
            problems[index].append(str(exc))
    for index, request in enumerate(requests):
        if request is None:
            continue
        try:
            KnowledgeAdmissionGate._validate(request)
        except ValueError as exc:
            problems[index].append(str(exc))
            continue
        try:
            KnowledgeAdmissionGate._checkVerifiability(request)
        except AdmissionError as exc:
            problems[index].append(str(exc))
            continue
        ontologyChecked[index] = True

    # 本体校验按 (agentId, tenantId) 分组，走同一份干跑实现；registry/report
    # 与 productionAdmissionGate 的本体段同款装配（含 shapes 求值器）
    groups: Dict[Tuple[str, str], List[int]] = {}
    for index, request in enumerate(requests):
        if request is not None and ontologyChecked[index]:
            groups.setdefault((request.agentId, request.tenantId), []).append(index)
    registry = None
    report = None
    for (agentId, tenantId), indices in groups.items():
        candidates = []
        for index in indices:
            request = requests[index]
            candidates.append({
                "subjectLabel": request.subjectLabel,
                "predicateTermId": _effectivePredicate(request),
                "objectTerm": request.objectTerm,
                "qualifier": dict(request.qualifier or {}),
            })
        if registry is None:
            registry = OntologyTermRegistry(store)
            report = OntologyValidationReport(registry, shapes=ShapeRegistry(store))
        dryRows = dryRunFactCandidates(store, agentId, tenantId, candidates,
                                       registry=registry, report=report)
        for index, dryRow in zip(indices, dryRows):
            violations = dryRow.get("violations") or []
            problems[index].extend(
                OntologyValidationReport.summarize([violation])
                for violation in violations)

    failed: List[Dict[str, str]] = []
    precheck: List[Dict[str, Any]] = []
    for index in range(total):
        if requests[index] is None or not ontologyChecked[index]:
            verdict = "invalid"
        elif problems[index]:
            verdict = "violation"
        else:
            verdict = "pass"
        if verdict == "pass":
            precheck.append({"index": index, "verdict": verdict, "violations": []})
            continue
        if verdict == "violation":
            reason = "本体校验未过：%s" % "；".join(problems[index])
        else:
            reason = "；".join(problems[index])
        failed.append({"index": index, "reason": reason})
        precheck.append({"index": index, "verdict": verdict,
                         "violations": list(problems[index])})
    return failed, precheck, requests


def _admitAll(store: Any, gate: Any, requests: List[AdmissionRequest], total: int,
              batchSize: int,
              onProgress: Optional[Callable[[int, int], None]]) -> Dict[str, Any]:
    """第二段：逐行 admit 落库（不开第二条写路径），按批回调进度。

    整批套 store 既有 `batchScope`（SAVEPOINT）：事实/断言/活动/推导全部折成
    一次提交，任一行异常 → 立即停批，整批未提交的写入一次退净——不留半截
    事实/冲突/推导，也不再依赖事后补偿撤销（KNOW-09：补偿撤不干净状态迁移
    与链式推导，事务回滚才是完整边界）。
    """
    failedIndex = -1
    try:
        with store.batchScope():
            for startIndex in range(0, total, batchSize):
                endIndex = min(startIndex + batchSize, total)
                for index in range(startIndex, endIndex):
                    failedIndex = index
                    gate.admit(requests[index])
                if onProgress is not None:
                    onProgress(endIndex, total)
    except Exception as exc:  # noqa: BLE001 - 停批如实点名；整批已回滚，零落盘
        return {
            "total": total, "admitted": 0, "dryRun": False,
            "failed": [{"index": failedIndex,
                        "reason": "第二段写入失败（行 %d）：%s: %s；"
                                  "整批经 batchScope 事务回滚，零落盘"
                                  % (failedIndex, type(exc).__name__, exc)}],
        }
    return {"total": total, "admitted": total, "failed": [],
            "dryRun": False}
