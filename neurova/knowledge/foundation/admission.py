"""唯一写咽喉：`KnowledgeAdmissionGate.admit()`（工单 003，设计文档 §5）。

七段编排：内容归一 → 身份消解 → 类型与规则裁决 → 冲突判定 → 可信度与使用记账
→ 血缘与链式记账 → 入索引。本模块先立骨架：契约、段序、缺段可见性。
未接通的段一律点名报出，不静默跳过——半条链当成整条链用，是这批设计最想灭的病。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SEGMENTS: tuple = (
    "content_identity",     # 004
    "identity_resolution",  # 006
    "ontology_adjudication",  # 020/021
    "conflict_judgement",   # 007
    "credibility_record",   # 009/010
    "lineage",              # 005
    "indexing",             # 011
)

_REQUIRED_FIELDS = ("subjectLabel", "predicateTermId", "objectTerm", "content")


@dataclass
class AdmissionRequest:
    """咽喉入参契约。置信度与断言由段内产出，不接受调用方裸传。"""

    agentId: str
    subjectLabel: str
    predicateTermId: str
    objectTerm: str
    content: str
    relationKind: str = "literal"
    qualifier: Dict[str, Any] = field(default_factory=dict)
    sourceTurnId: str = ""
    aliases: List[str] = field(default_factory=list)
    validFrom: Optional[str] = None
    validUntil: Optional[str] = None


@dataclass
class AdmissionReceipt:
    factId: str
    subjectKey: str
    pendingSegments: List[str]
    segmentsApplied: List[str]


class AdmissionSegmentMissing(RuntimeError):
    """咽喉依赖未齐——缺哪段就点名哪段，禁止半链冒充全链。"""

    def __init__(self, segments: List[str]):
        super().__init__(
            "admit() 缺段未接通: %s；确需先落数据可传 allowPendingSegments=True，"
            "回执会带上 pending_segments 供下游识别" % ", ".join(segments)
        )
        self.segments = segments


class KnowledgeAdmissionGate:
    def __init__(
        self,
        store: Any,
        resolver: Any = None,
        conflictJudge: Any = None,
        lineageLedger: Any = None,
        termRegistry: Any = None,
    ) -> None:
        self._store = store
        self._collaborators = {
            "identity_resolution": resolver,
            "conflict_judgement": conflictJudge,
            "lineage": lineageLedger,
            "ontology_adjudication": termRegistry,
        }

    def pendingSegments(self) -> List[str]:
        """骨架期由段1（内容归一）与段5/7（记账、索引）自身尚未落地报缺。"""
        missing = [name for name, dep in self._collaborators.items() if dep is None]
        for always_pending in ("content_identity", "credibility_record", "indexing"):
            if always_pending not in missing:
                missing.append(always_pending)
        return [name for name in SEGMENTS if name in missing]

    def admit(self, request: AdmissionRequest, allowPendingSegments: bool = False) -> AdmissionReceipt:
        for name in _REQUIRED_FIELDS:
            if not str(getattr(request, name, "") or "").strip():
                raise ValueError("admit 缺必填字段: %s" % name)
        if not str(request.agentId or "").strip():
            raise ValueError("admit 缺必填字段: agentId")

        pending = self.pendingSegments()
        if pending and not allowPendingSegments:
            raise AdmissionSegmentMissing(pending)

        subjectKey = self._store.upsertSubject(
            request.agentId, request.subjectLabel, aliases=request.aliases,
        )
        factId = self._store.upsertFact(
            agentId=request.agentId,
            subjectKey=subjectKey,
            predicateTermId=request.predicateTermId,
            objectTerm=request.objectTerm,
            content=request.content,
            relationKind=request.relationKind,
            qualifier=request.qualifier,
            sourceTurnId=request.sourceTurnId,
            # confidence 留 None：G11 规定它只能由断言聚合得出，咽喉不代填
        )
        return AdmissionReceipt(
            factId=factId,
            subjectKey=subjectKey,
            pendingSegments=pending,
            segmentsApplied=["identity_resolution(base exact/alias)"],
        )
