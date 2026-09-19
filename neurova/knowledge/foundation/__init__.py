"""知识底座（foundation）：唯一权威事实源与唯一写咽喉。"""

from .admission import (
    AdmissionReceipt,
    AdmissionRequest,
    AdmissionSegmentMissing,
    KnowledgeAdmissionGate,
    SEGMENTS,
)
from .knowledge_facts import (
    ADOPTION_OUTCOMES,
    DEFAULT_FACT_DB,
    KnowledgeFactStore,
    get_knowledge_fact_store,
    normalizeLabel,
    reset_knowledge_fact_store,
)
from .conflict_judge import CONFLICT_KINDS, RESOLUTION_POLICIES, KnowledgeConflictJudge
from .lineage import ACTIVITY_KINDS, ACTOR_TYPES, KnowledgeLineageLedger
from .reconcile import FoundationReconciler
from .redundancy import RedundancyAudit

__all__ = [
    "AdmissionReceipt",
    "AdmissionRequest",
    "AdmissionSegmentMissing",
    "DEFAULT_FACT_DB",
    "KnowledgeAdmissionGate",
    "KnowledgeConflictJudge",
    "KnowledgeFactStore",
    "CONFLICT_KINDS",
    "RESOLUTION_POLICIES",
    "KnowledgeLineageLedger",
    "ACTIVITY_KINDS",
    "ACTOR_TYPES",
    "FoundationReconciler",
    "RedundancyAudit",
    "SEGMENTS",
    "get_knowledge_fact_store",
    "normalizeLabel",
    "reset_knowledge_fact_store",
]
