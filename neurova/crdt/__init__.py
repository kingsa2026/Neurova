"""
Neurova CRDT Module
CRDT-based real-time collaboration system
"""

from neurova.crdt.core import (
    GSetCRDT,
    PNCounterCRDT,
    LWWRegisterCRDT,
    ORSetCRDT,
    UniqueID,
)

from neurova.crdt.rga import (
    RGACRDT,
    TextOperation,
    Position,
    Character,
)

from neurova.crdt.document import (
    CRDTDocument,
    DocumentMetadata,
    get_document,
    reset_document_registry,
)

__all__ = [
    # Core CRDT types
    "GSetCRDT",
    "PNCounterCRDT",
    "LWWRegisterCRDT",
    "ORSetCRDT",
    "UniqueID",
    
    # RGA for text editing
    "RGACRDT",
    "TextOperation",
    "Position",
    "Character",
    
    # Document class
    "CRDTDocument",
    "DocumentMetadata",
    "get_document",
    "reset_document_registry",
]
