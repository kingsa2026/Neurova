"""唯一写咽喉：`KnowledgeAdmissionGate.admit()`（工单 003，设计文档 §5）。

七段编排：内容归一 → 身份消解 → 类型与规则裁决 → 冲突判定 → 可信度与使用记账
→ 血缘与链式记账 → 入索引。本模块先立骨架：契约、段序、缺段可见性。
未接通的段一律点名报出，不静默跳过——半条链当成整条链用，是这批设计最想灭的病。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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

# 段名册：每段的当前状态只有两种取值，且必须在 SEGMENTS 里穷举。
# `wired` = 已接通的协作者，缺它说明**这次造门漏接了一段**（必须拒写）；
# `planned` = 尚未建成的段，缺它是常态（写数据仍要能写）。
#
# 这两种故障此前共用一个 `pending_segments` 字段（旧实现把 `indexing` 硬编码成永远缺），
# 后果是每个真实调用点都只能传 `allowPendingSegments=True` 绕开纪律——
# 「缺段即拒」在真实链路上等于不存在。分开之后，逃生开关在真实写入链上被删干净。
SEGMENT_STATUS: dict = {
    "content_identity": "wired",       # 段1 在 admit() 内联实现
    "identity_resolution": "wired",
    "ontology_adjudication": "wired",
    "conflict_judgement": "wired",
    "credibility_record": "wired",
    "lineage": "wired",
    # 段7 尚未建成：事实池由读面在查询时对库内行实时打分（`read_surface.searchableFacts`
    # → `bm25_rank`），叙述/分块两路另有条目侧索引，因此这一格不接也不缺读面能力，
    # 但它**不是**"这次装配漏了一段"，不许混进拒写判据。
    "indexing": "planned",
}

_REQUIRED_FIELDS = ("subjectLabel", "predicateTermId", "objectTerm", "content")

# 记录种类（工单 019b-1）。triple 是"主体-谓词-客体"；narrative 是"一条知识文档"——
# 它要的是内容身份、消解后的主体、断言与置信，**不是**被伪造成三元组。
RECORD_KINDS: tuple = ("triple", "narrative")
NARRATIVE_RECORD_KIND = "narrative"
# 叙述记录的事实行统一挂在这个谓词下，客体是正文的内容键（无内容身份才退回条目 id）。
# 条目 id 记在 source_turn_id 上（`entry:<kid>`）——它编辑前后不变，当客体就把"改写"
# 吞成同一行了。谓词与客体形状都由咽喉固定，不让调用方自由填：治理身份不是自由文本。
NARRATIVE_PREDICATE = "documented_as"
_NARRATIVE_REQUIRED_FIELDS = ("subjectLabel", "objectTerm", "content")


@dataclass
class AdmissionRequest:
    """咽喉入参契约。置信度与断言由段内产出，不接受调用方裸传。"""

    agentId: str
    subjectLabel: str
    predicateTermId: str = ""
    objectTerm: str = ""
    content: str = ""
    recordKind: str = "triple"
    relationKind: str = "literal"
    qualifier: Dict[str, Any] = field(default_factory=dict)
    sourceTurnId: str = ""
    aliases: List[str] = field(default_factory=list)
    assertions: List[Dict[str, Any]] = field(default_factory=list)
    validFrom: Optional[str] = None
    validUntil: Optional[str] = None
    # 来路声明（工单 005 的"经哪条管线进来"）：调用方自陈它的活动种类与依据。
    # 不声明时由咽喉兜底开一条 `admit`，但 basis 会写明是兜底——生产读数里
    # 92/92 条活动都等于咽喉自己，正是因为这一栏此前不存在。
    activityKind: str = ""
    activityBasis: str = ""
    # 调用方已经开好活动时直接接上，咽喉不再另开一条同义活动。
    activityId: str = ""


@dataclass
class AdmissionReceipt:
    factId: str
    subjectKey: str
    pendingSegments: List[str]
    segmentsApplied: List[str]
    dedupedByContent: Optional[str] = None
    needsHumanReview: bool = False
    lineageApplied: bool = False
    # 尚未建成的段另立一栏：`pendingSegments` 只报"这次装配漏接"，
    # 两者混报就等于回执不再指认故障。
    plannedSegments: List[str] = field(default_factory=list)
    # 本条事实挂在哪条活动上：调用方要顺着自己的账往下记，得拿得到这个 id。
    activityId: str = ""


import threading

_deriveState = threading.local()


class AdmissionSegmentMissing(RuntimeError):
    """咽喉依赖未齐——缺哪段就点名哪段，禁止半链冒充全链。

    只报**这次造门漏接**的段。尚未建成的段（见 `SEGMENT_STATUS`）不在此列：
    把"还没做"报成"做漏了"，拒写判据就永远响着，纪律也就没人再看。
    """

    def __init__(self, segments: List[str]):
        super().__init__(
            "admit() 缺段未接通: %s；这属于装配漏段，必须补齐协作者——"
            "尚未建成的段不在此列（见 admission.SEGMENT_STATUS）" % ", ".join(segments)
        )
        self.segments = segments


def _normalizedRecord(request: AdmissionRequest) -> AdmissionRequest:
    """叙述记录的治理身份由咽喉固定，且事实行不留正文副本。

    - 谓词与关系种类由咽喉赋值：治理身份不能是调用方的自由文本；
    - `content` 清空：条目的正文唯一副本在 `knowledge_narratives.payload_json`，
      内容身份已经在上游算成 `content_key` 带下来了。在同一个库里再抄一份正文，
      就是这次改造要消灭的那个病。

    复制而不是就地改：调用方拿着同一个请求体重试时，不该看到字段被人动过。
    """
    if request.recordKind != NARRATIVE_RECORD_KIND:
        return request
    return replace(request, predicateTermId=NARRATIVE_PREDICATE,
                   relationKind="document", content="")


class KnowledgeAdmissionGate:
    def __init__(
        self,
        store: Any,
        resolver: Any = None,
        conflictJudge: Any = None,
        lineageLedger: Any = None,
        ontology: Any = None,
        credibility: Any = None,
        reasoning: Any = None,
    ) -> None:
        self._store = store
        self._collaborators = {
            "identity_resolution": resolver,
            "conflict_judgement": conflictJudge,
            "lineage": lineageLedger,
            "ontology_adjudication": ontology,
            "credibility_record": credibility,
            # 推导属段3（类型与规则裁决）的后半，不另立一段：段序是设计定的，
            # 多一格就把"校验与推导是一件事的两面"拆成了两段。
            "forward_chaining": reasoning,
        }

    def pendingSegments(self) -> List[str]:
        """只报本次装配漏接的段：协作者已注入的段按注入实况，`planned` 段一律不报。"""
        missing = [name for name, dep in self._collaborators.items() if dep is None]
        return [name for name in SEGMENTS
                if name in missing and SEGMENT_STATUS.get(name) == "wired"]

    @staticmethod
    def plannedSegments() -> List[str]:
        """尚未建成的段。与 `pendingSegments()` 正交，回执两栏分列。"""
        return [name for name in SEGMENTS if SEGMENT_STATUS.get(name) == "planned"]

    @staticmethod
    def _validate(request: AdmissionRequest) -> None:
        """必填项按记录种类判。

        三元组要谓词；叙述记录不要（谓词由咽喉固定），但它必须说清自己挂在哪条
        条目上——`object_term` 就是那个 knowledge_id。
        """
        kind = request.recordKind or "triple"
        if kind not in RECORD_KINDS:
            raise ValueError(
                "admit 不认记录种类 record_kind=%r（可选：%s）"
                % (kind, " / ".join(RECORD_KINDS)))
        if not str(request.agentId or "").strip():
            raise ValueError("admit 缺必填字段: agentId")
        required = _NARRATIVE_REQUIRED_FIELDS if kind == "narrative" else _REQUIRED_FIELDS
        for name in required:
            if not str(getattr(request, name, "") or "").strip():
                raise ValueError("admit 缺必填字段: %s（record_kind=%s）" % (name, kind))
        if kind == "narrative" and request.predicateTermId \
                and request.predicateTermId != NARRATIVE_PREDICATE:
            raise ValueError(
                "叙述记录的谓词由咽喉固定为 %r，不接受调用方传 %r——治理身份不是自由文本"
                % (NARRATIVE_PREDICATE, request.predicateTermId))

    def admit(self, request: AdmissionRequest, allowPendingSegments: bool = False) -> AdmissionReceipt:
        """写入。`allowPendingSegments` 只在测试里搭裸门时用——真实写入链的装配
        已经齐全（见 `SEGMENT_STATUS`），四个生产调用点一律不带它。"""
        self._validate(request)

        pending = self.pendingSegments()
        planned = self.plannedSegments()
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
        request = _normalizedRecord(request)
        if request.recordKind == NARRATIVE_RECORD_KIND:
            # 叙述记录的身份必须是"这条说法的内容"，不是条目 id：条目 id 在编辑前后不变，
            # 若拿它当客体，(主体, 谓词, 客体) 三元组就条条相同，upsertFact 会把每一次
            # 正文改写吞回同一行——旧说法永远不被取代，编辑在治理层完全隐身（019b-2 实测）。
            # 无内容身份的条目仍按 id 立身，那条说法没有"改一次算一次"可言。
            entryId = request.objectTerm
            if not str(request.sourceTurnId or "").strip():
                # 客体换成内容键之后，"这是哪条条目"只剩 source_turn_id 一个落点；
                # 让它由咽喉兜底而不是要求每个调用方自觉，否则条目再也找不回自己的治理行。
                request = replace(request, sourceTurnId="entry:%s" % entryId)
            request = replace(request, objectTerm=contentKey or request.objectTerm)
        dupe = self._store.findFactByContentKey(request.agentId, contentKey) if contentKey else None
        if dupe:
            # 折回旧行也要补窗口：同一句话第一次带窗口、第二次不带，行为不该随调用顺序漂移
            self._store.fillValidityWindow(dupe["fact_id"], request.validFrom, request.validUntil)
            applied = ["content_identity"]
            activityId = ""
            if lineage is not None:
                activityId = self._attachLineage(lineage, dupe["fact_id"], request, deduped=True)
                applied.append("lineage")
            applied += self._judgeConflicts(request)
            applied += self._applyCredibility(dupe["fact_id"])
            return AdmissionReceipt(
                factId=dupe["fact_id"],
                subjectKey=dupe["subject_key"],
                pendingSegments=pending,
                segmentsApplied=applied + self._resolutionLabel(),
                dedupedByContent=dupe["fact_id"],
                lineageApplied=lineage is not None,
                plannedSegments=planned,
                activityId=activityId,
            )

        subjectKey, needsReview, applied = self._resolveSubject(request)
        # 段3 前半：本体校验。放在消解之后、写入之前——校验要看的是"这条说法挂在谁身上"，
        # 而主体还没定就校验等于校验一个还不存在的落点。违规即拒（G08 的硬判据）。
        ontology = self._collaborators.get("ontology_adjudication")
        if ontology is not None:
            violations = ontology.violations(request, subjectKey)
            if violations:
                raise ValueError("本体校验未过：%s" % ontology.summarize(violations))
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
            recordKind=request.recordKind,
            # 时效窗口是调用方声明的，咽喉原样落到两列上——收了不落库等于断点
            validFrom=request.validFrom,
            validUntil=request.validUntil,
            # confidence 留 None：G11 规定它只能由断言聚合得出，咽喉不代填
        )
        activityId = ""
        if lineage is not None:
            activityId = self._attachLineage(lineage, factId, request, deduped=False)
        applied += self._judgeConflicts(request)
        applied += self._applyCredibility(factId)
        applied += self._derive(request, subjectKey)
        return AdmissionReceipt(
            factId=factId,
            subjectKey=subjectKey,
            pendingSegments=pending,
            segmentsApplied=["content_identity"] + applied
                            + (["lineage"] if lineage is not None else []),
            needsHumanReview=needsReview,
            lineageApplied=lineage is not None,
            plannedSegments=planned,
            activityId=activityId,
        )

    def _derive(self, request: AdmissionRequest, subjectKey: str) -> List[str]:
        """段3 后半：按规则推导。嵌套写不再点燃规则——推导事实又触发推导，
        等于给自己造一个没有终点的循环（分层只管结论正确，不管重入）。"""
        reasoning = self._collaborators.get("forward_chaining")
        if reasoning is None or getattr(_deriveState, "inside", False):
            return []
        _deriveState.inside = True
        try:
            reasoning.fireFor(request.agentId, request.predicateTermId)
        finally:
            _deriveState.inside = False
        return ["forward_chaining"]

    def _applyCredibility(self, factId: str) -> List[str]:
        """段5：置信度由断言聚合回写，读实况而非增量累加。"""
        credibility = self._collaborators.get("credibility_record")
        if credibility is None:
            return []
        credibility.apply(factId)
        return ["credibility_record"]

    def _judgeConflicts(self, request: AdmissionRequest) -> List[str]:
        """段4：同 (主体, 谓词) 上的新旧分歧升成一等对象。

        未注入判定器就不假装判过——冲突漏报是"账本永远是空的"那种病。
        """
        judge = self._collaborators.get("conflict_judgement")
        if judge is None:
            return []
        judge.record(request.subjectLabel, request.predicateTermId)
        return ["conflict_judgement"]

    def _attachLineage(self, lineage, factId: str, request: AdmissionRequest,
                       deduped: bool) -> str:
        """把事实挂到一条活动上，返回该活动 id。

        「经哪条管线进来」这一问只有调用方答得出来（导入 / 抽取 / 对账回放 / 推导各是
        一条）。所以活动的种类与依据由 `request.activityKind` / `activityBasis` 声明，
        调用方已开好的活动（`request.activityId`）优先复用。

        只有**没有上层管线**的直写才由咽喉兜底开一条 `admit`，且 basis 上自陈是兜底——
        生产库里 92/92 条活动都记着 `KnowledgeAdmissionGate.admit`，就是这一栏缺席的物证：
        四种来路长得一模一样，溯源读数失去区分力。
        """
        deferred = str(request.activityId or "").strip()
        if deferred:
            lineage.attach(factId, request.assertions, activityId=deferred)
            lineage.closeActivity(deferred, outputs={"fact_id": factId,
                                                    "content_deduped": deduped})
            return deferred
        kind = str(request.activityKind or "").strip() or "admit"
        declared = str(request.activityBasis or "").strip()
        basis = declared or "KnowledgeAdmissionGate.admit（直写兜底：调用方未声明来路）"
        activityId = lineage.openActivity(
            kind,
            inputs={
                "agent_id": request.agentId,
                "subject_label": request.subjectLabel,
                "predicate_term_id": request.predicateTermId,
                "object_term": request.objectTerm,
                "source_turn_id": request.sourceTurnId,
            },
            basis=basis,
        )
        lineage.attach(factId, request.assertions, activityId=activityId)
        lineage.closeActivity(activityId, outputs={"fact_id": factId, "content_deduped": deduped})
        return activityId

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


def productionAdmissionGate(store: Any, toolVersion: str = "foundation-gate") -> KnowledgeAdmissionGate:
    """真写入口的唯一装配口径。

    造门散在各调用点各写一遍，就会各差一段：回填漏接 resolver 时身份消解退回精确名，
    对账漏接血缘时回放不像生产。同一个"唯一咽喉"被各自装配，就再也不是一个咽喉。
    缺的段（本体裁决、入索引）不硬凑——`pendingSegments()` 会如实报出它们还没接通。
    """
    from neurova.knowledge.identity.subject_resolver import SubjectResolver

    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
    from neurova.knowledge.ontology.validation import OntologyValidationReport

    from .credibility import ConfidenceAggregator
    from .conflict_judge import KnowledgeConflictJudge
    from .lineage import KnowledgeLineageLedger

    from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine

    registry = OntologyTermRegistry(store)
    engine = ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(
        st, toolVersion=toolVersion))
    return KnowledgeAdmissionGate(
        store,
        resolver=SubjectResolver(),
        conflictJudge=KnowledgeConflictJudge(store),
        lineageLedger=KnowledgeLineageLedger(store, toolVersion=toolVersion),
        credibility=ConfidenceAggregator(store),
        ontology=OntologyValidationReport(registry),
        reasoning=engine,
    )
