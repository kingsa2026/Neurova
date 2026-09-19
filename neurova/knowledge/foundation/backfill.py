"""历史条目回填底座（工单 011 的前置件）。

回填必须走咽喉而不是直插 SQL：否则绕过内容去重与身份消解，把 B03 的 38 行原样搬进新库，
"统一底座"当场变成第二套真相。入参映射与断言合成不在这里另写一套——它和对账器共用
`reconcile._requestsFromRepository`，两处各写一份映射就等于没有对账。
"""

from __future__ import annotations

from typing import Any, Dict, List

from neurova.core.logger import get_logger

from .admission import productionAdmissionGate
from .knowledge_facts import KnowledgeFactStore
from .reconcile import _requestsFromRepository

logger = get_logger(__name__)


class LegacyFactBackfill:
    @staticmethod
    def run(repo: Any, store: KnowledgeFactStore, dryRun: bool = False) -> Dict[str, Any]:
        requests = _requestsFromRepository(repo)

        if dryRun:
            keys = set()
            for request in requests:
                keys.add((request.agentId, request.content))
            return {"mode": "dry_run", "legacy_rows": len(requests),
                    "would_admit": len(requests), "facts_before": store.factCount(),
                    "facts_after": store.factCount(), "collapsed_unique_contents": len(keys)}

        gate = productionAdmissionGate(store, toolVersion="legacy-backfill")
        created: List[str] = []
        idMap: Dict[str, str] = {}
        folded = 0
        failures: List[str] = []
        for request in requests:
            try:
                receipt = gate.admit(request, allowPendingSegments=True)
            except ValueError as exc:
                failures.append("%s: %s" % (request.objectTerm, exc))
                continue
            idMap[request.objectTerm] = receipt.factId
            if receipt.dedupedByContent:
                folded += 1
            else:
                created.append(receipt.factId)
        factsAfter = store.factCount()
        logger.info("历史回填完成：旧库 %d 行 → 底座 %d 事实（折叠 %d 行，失败 %d 行）",
                    len(requests), factsAfter, folded, len(failures))
        return {
            "mode": "apply",
            "legacy_rows": len(requests),
            "admitted": len(created),
            "folded_rows": folded,
            "failures": failures,
            "facts_before": factsAfter - len(created),
            "facts_after": factsAfter,
            "subjects": store.subjectCount(),
            "pending_conflicts": store.pendingConflictCount(),
            # 旧 id → 新 fact_id：没有这张表，开闸态的 recall 会因为 id 空间换掉而假跌
            "id_map": idMap,
        }
