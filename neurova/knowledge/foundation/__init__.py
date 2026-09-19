"""知识底座（foundation）：唯一权威事实源与唯一写咽喉。"""

from .admission import (
    AdmissionReceipt,
    AdmissionRequest,
    AdmissionSegmentMissing,
    KnowledgeAdmissionGate,
    SEGMENTS,
)
from .knowledge_facts import (
    DEFAULT_FACT_DB,
    KnowledgeFactStore,
    get_knowledge_fact_store,
    normalizeLabel,
    reset_knowledge_fact_store,
)

__all__ = [
    "AdmissionReceipt",
    "AdmissionRequest",
    "AdmissionSegmentMissing",
    "DEFAULT_FACT_DB",
    "KnowledgeAdmissionGate",
    "KnowledgeFactStore",
    "SEGMENTS",
    "get_knowledge_fact_store",
    "normalizeLabel",
    "reset_knowledge_fact_store",
]
