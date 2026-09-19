"""历史条目回填底座（工单 011 的前置件）。

回填必须走咽喉而不是直插 SQL：否则绕过内容去重与身份消解，把 B03 的 38 行原样搬进新库，
"统一底座"当场变成第二套真相。断言按旧行已有字段如实合成（来源串 + 属主 + 标题），
不为回填行编造置信度——那是 G11 要灭的病，不能由迁移脚本重新犯。
"""

from __future__ import annotations

from typing import Any, Dict, List

from neurova.core.logger import get_logger

from .admission import AdmissionRequest, KnowledgeAdmissionGate
from .credibility import ConfidenceAggregator
from .knowledge_facts import KnowledgeFactStore
from .lineage import KnowledgeLineageLedger
from .reconcile import _requestsFromRepository

logger = get_logger(__name__)

_IMPORTER_PREFIXES = ("import:", "url:", "datasource:", "kb_builder")


def _assertionFor(agentId: str, item: Dict[str, Any]) -> Dict[str, Any]:
    source = str(item.get("source", "") or "").strip()
    owner = str(item.get("owner_user_id", "") or "").strip()
    lowered = source.lower()
    if lowered.startswith(_IMPORTER_PREFIXES):
        actorType = "importer"
    elif owner:
        actorType = "user"
    else:
        actorType = "pipeline"
    return {
        "actorType": actorType,
        "actorId": owner or "legacy-unknown",
        "mediumRef": source or "legacy:knowledge.json",
        "statementText": str(item.get("title", "") or "").strip() or "(untitled legacy entry)",
        "verification_state": "unverified",
    }


class LegacyFactBackfill:
    @staticmethod
    def run(repo: Any, store: KnowledgeFactStore, dryRun: bool = False) -> Dict[str, Any]:
        requests = _requestsFromRepository(repo)
        itemsByKnowledgeId: Dict[str, Dict[str, Any]] = {
            str(item.get("knowledge_id")): item
            for bucket in getattr(repo, "_items", {}).values() for item in bucket
        }

        if dryRun:
            keys = set()
            for request in requests:
                keys.add((request.agentId, request.content))
            return {"mode": "dry_run", "legacy_rows": len(requests),
                    "would_admit": len(requests), "facts_before": store.factCount(),
                    "facts_after": store.factCount(), "collapsed_unique_contents": len(keys)}

        ledger = KnowledgeLineageLedger(store, toolVersion="legacy-backfill")
        gate = KnowledgeAdmissionGate(store, lineageLedger=ledger,
                                      credibility=ConfidenceAggregator(store))
        created: List[str] = []
        idMap: Dict[str, str] = {}
        folded = 0
        failures: List[str] = []
        for request in requests:
            item = itemsByKnowledgeId.get(request.objectTerm, {})
            try:
                receipt = gate.admit(
                    AdmissionRequest(
                        agentId=request.agentId, subjectLabel=request.subjectLabel,
                        predicateTermId=request.predicateTermId, objectTerm=request.objectTerm,
                        content=request.content, assertions=[_assertionFor(request.agentId, item)],
                        sourceTurnId="legacy:%s" % request.objectTerm,
                    ),
                    allowPendingSegments=True,
                )
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
