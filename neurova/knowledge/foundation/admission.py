"""唯一写咽喉：`KnowledgeAdmissionGate.admit()`（工单 003，设计文档 §5）。

七段编排：内容归一 → 身份消解 → 类型与规则裁决 → 冲突判定 → 可信度与使用记账
→ 血缘与链式记账 → 入索引。本模块先立骨架：契约、段序、缺段可见性。
未接通的段一律点名报出，不静默跳过——半条链当成整条链用，是这批设计最想灭的病。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from neurova.core.content_identity import normalized_key as normalizedKey

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
    assertions: List[Dict[str, Any]] = field(default_factory=list)
    validFrom: Optional[str] = None
    validUntil: Optional[str] = None


@dataclass
class AdmissionReceipt:
    factId: str
    subjectKey: str
    pendingSegments: List[str]
    segmentsApplied: List[str]
    dedupedByContent: Optional[str] = None
    needsHumanReview: bool = False
    lineageApplied: bool = False


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
        """段1（内容归一）已在 004 接通；其余缺段按协作者是否注入如实报出。"""
        missing = [name for name, dep in self._collaborators.items() if dep is None]
        for always_pending in ("credibility_record", "indexing"):
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

        lineage = self._collaborators.get("lineage")
        # 匿名知识在写入前就被拒，不是写完再回滚——回滚路径总会留一条漏网事实。
        if lineage is not None and not request.assertions:
            raise ValueError(
                "admit 缺断言：溯源段已接通，必须声明 actorType / actorId / statementText，"
                "不接受匿名知识"
            )

        # 段1 内容归一：口径是抽取后内容，不是原始字节/URL 串。
        # 空键 = 没有内容身份（纯标点/空白），不参与去重，否则空写入会互相吞没。
        contentKey = normalizedKey(request.content) or None
        dupe = self._store.findFactByContentKey(request.agentId, contentKey) if contentKey else None
        if dupe:
            applied = ["content_identity"]
            if lineage is not None:
                self._attachLineage(lineage, dupe["fact_id"], request, deduped=True)
                applied.append("lineage")
            applied += self._judgeConflicts(request)
            return AdmissionReceipt(
                factId=dupe["fact_id"],
                subjectKey=dupe["subject_key"],
                pendingSegments=pending,
                segmentsApplied=applied + self._resolutionLabel(),
                dedupedByContent=dupe["fact_id"],
                lineageApplied=lineage is not None,
            )

        subjectKey, needsReview, applied = self._resolveSubject(request)
        factId = self._store.upsertFact(
            agentId=request.agentId,
            subjectKey=subjectKey,
            predicateTermId=request.predicateTermId,
            objectTerm=request.objectTerm,
            content=request.content,
            relationKind=request.relationKind,
            qualifier=request.qualifier,
            sourceTurnId=request.sourceTurnId,
            contentKey=contentKey,
            # confidence 留 None：G11 规定它只能由断言聚合得出，咽喉不代填
        )
        if lineage is not None:
            self._attachLineage(lineage, factId, request, deduped=False)
        applied += self._judgeConflicts(request)
        return AdmissionReceipt(
            factId=factId,
            subjectKey=subjectKey,
            pendingSegments=pending,
            segmentsApplied=["content_identity"] + applied
                            + (["lineage"] if lineage is not None else []),
            needsHumanReview=needsReview,
            lineageApplied=lineage is not None,
        )

    def _judgeConflicts(self, request: AdmissionRequest) -> List[str]:
        """段4：同 (主体, 谓词) 上的新旧分歧升成一等对象。

        未注入判定器就不假装判过——冲突漏报是"账本永远是空的"那种病。
        """
        judge = self._collaborators.get("conflict_judgement")
        if judge is None:
            return []
        judge.record(request.subjectLabel, request.predicateTermId)
        return ["conflict_judgement"]

    def _attachLineage(self, lineage, factId: str, request: AdmissionRequest, deduped: bool) -> None:
        """咽喉自己开一条活动记录。

        不建活动，溯源四问里的"经哪条管线进来"就恒空——2026-09-20 端到端冒烟实测到这一点。
        调用方自带 activityId 的断言仍优先，这里是给"没有上层管线"的直写路径兜出可见的一跳。
        """
        activityId = lineage.openActivity(
            "admit",
            inputs={
                "agent_id": request.agentId,
                "subject_label": request.subjectLabel,
                "predicate_term_id": request.predicateTermId,
                "object_term": request.objectTerm,
                "source_turn_id": request.sourceTurnId,
            },
            basis="KnowledgeAdmissionGate.admit",
        )
        lineage.attach(factId, request.assertions, activityId=activityId)
        lineage.closeActivity(activityId, outputs={"fact_id": factId, "content_deduped": deduped})

    def _resolutionLabel(self) -> List[str]:
        resolver = self._collaborators.get("identity_resolution")
        return ["identity_resolution"] if resolver is not None \
            else ["identity_resolution(base exact/alias)"]

    def _resolveSubject(self, request: AdmissionRequest):
        """段2 身份消解：注入了 resolver 走确定性相似度，否则退回精确名+别名。

        退回时如实报告"相似度层未生效"，不冒充跑过了多因子合并。
        """
        resolver = self._collaborators.get("identity_resolution")
        if resolver is None:
            return (self._store.upsertSubject(
                request.agentId, request.subjectLabel, aliases=request.aliases,
            ), False, ["identity_resolution(base exact/alias)"])
        outcome = resolver.resolve(
            request.subjectLabel,
            self._store.listSubjects(request.agentId),
            aliases=request.aliases,
        )
        subjectKey = outcome.subjectKey or self._store.upsertSubject(
            request.agentId, request.subjectLabel, aliases=request.aliases,
        )
        return (subjectKey, outcome.needsHumanReview, ["identity_resolution"])
