"""
Neurova CRDT Document
CRDT 文档类，整合所有 CRDT 类型实现完整文档协作
"""

from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from datetime import datetime
import uuid

from neurova.cdt.core import (
    GSetCRDT, PNCounterCRDT, LWWRegisterCRDT, ORSetCRDT,
    UniqueID,
)
from neurova.cdt.rga import RGACRDT, TextOperation


@dataclass
class DocumentMetadata:
    """Document metadata using CRDT types"""
    title: LWWRegisterCRDT = field(default_factory=lambda: LWWRegisterCRDT("Untitled"))
    description: LWWRegisterCRDT = field(default_factory=lambda: LWWRegisterCRDT(""))
    tags: ORSetCRDT = field(default_factory=ORSetCRDT)
    authors: GSetCRDT = field(default_factory=GSetCRDT)
    version: PNCounterCRDT = field(default_factory=lambda: PNCounterCRDT(1))
    created_at: LWWRegisterCRDT = field(default_factory=lambda: LWWRegisterCRDT(""))
    updated_at: LWWRegisterCRDT = field(default_factory=lambda: LWWRegisterCRDT(""))


class CRDTDocument:
    """
    CRDT-based collaborative document
    
    Features:
    - Real-time collaboration with automatic conflict resolution
    - Version tracking and history
    - Metadata management
    - Operation logging for sync
    
    Usage:
        doc = CRDTDocument(document_id="doc_123", node_id="node_1")
        
        # Insert text
        pos = doc.insert_text(0, "Hello ", "user_1")
        pos2 = doc.insert_text(6, "World!", "user_2")
        
        # Delete text
        doc.delete_text(pos)
        
        # Get current content
        print(doc.get_text())  # "Hello!"
        
        # Update metadata
        doc.set_title("My Document", "user_1")
        doc.add_tag("important", "user_1")
        
        # Sync with other replicas
        other_doc = CRDTDocument.from_dict(doc.to_dict())
        doc.merge(other_doc)
    """
    
    def __init__(self, document_id: str, node_id: str):
        self.document_id = document_id
        self.node_id = node_id
        
        # Main text content (RGA)
        self._text: RGACRDT = RGACRDT()
        
        # Metadata
        self._metadata = DocumentMetadata()
        
        # Operation log for sync
        self._operation_log: List[TextOperation] = []
        
        # Vector clock for each node
        self._vector_clock: Dict[str, int] = {}
        
        # Statistics
        self._stats = {
            "total_inserts": 0,
            "total_deletes": 0,
            "total_metadata_updates": 0,
            "sync_count": 0,
        }
    
    def insert_text(self, index: int, text: str, user_id: Optional[str] = None) -> List[Any]:
        """
        Insert text at position
        
        Args:
            index: Character index to insert at
            text: Text to insert
            user_id: ID of user performing insertion
        
        Returns:
            List of positions of inserted characters
        """
        positions = []
        
        # Find the position after which to insert
        after_pos = None
        if index > 0:
            char = self._text.get_character_at(index - 1)
            if char:
                after_pos = char.position
        
        # Insert each character
        for char in text:
            new_pos = self._text.insert(char, after_pos, user_id or self.node_id)
            positions.append(new_pos)
            
            # Create operation for sync
            op = TextOperation("insert", position=new_pos, char=char)
            self._operation_log.append(op)
        
        self._stats["total_inserts"] += len(text)
        
        return positions
    
    def delete_text(self, pos: Any) -> bool:
        """
        Delete character at position
        
        Args:
            pos: Position returned from insert_text
        
        Returns:
            True if deleted successfully
        """
        success = self._text.delete(pos)
        
        if success:
            op = TextOperation("delete", delete_pos=pos)
            self._operation_log.append(op)
            self._stats["total_deletes"] += 1
        
        return success
    
    def get_text(self) -> str:
        """Get current document text"""
        return self._text.get_text()
    
    def set_title(self, title: str, user_id: Optional[str] = None) -> None:
        """Update document title"""
        self._metadata.title.write(title, user_id or self.node_id)
        self._metadata.updated_at.write(datetime.utcnow().isoformat(), user_id or self.node_id)
        self._stats["total_metadata_updates"] += 1
    
    def set_description(self, description: str, user_id: Optional[str] = None) -> None:
        """Update document description"""
        self._metadata.description.write(description, user_id or self.node_id)
        self._stats["total_metadata_updates"] += 1
    
    def add_tag(self, tag: str, user_id: Optional[str] = None) -> None:
        """Add tag to document"""
        self._metadata.tags.add(tag, user_id or self.node_id)
        self._stats["total_metadata_updates"] += 1
    
    def remove_tag(self, tag: str, user_id: Optional[str] = None) -> None:
        """Remove tag from document"""
        self._metadata.tags.remove(tag, user_id or self.node_id)
        self._stats["total_metadata_updates"] += 1
    
    def add_author(self, author_id: str) -> None:
        """Add author to document"""
        self._metadata.authors.add(author_id)
        self._stats["total_metadata_updates"] += 1
    
    def increment_version(self) -> None:
        """Increment document version"""
        self._metadata.version.increment(self.node_id)
        self._metadata.updated_at.write(datetime.utcnow().isoformat(), self.node_id)
        self._stats["total_metadata_updates"] += 1
    
    def merge(self, other: 'CRDTDocument') -> None:
        """
        Merge another document into this one
        
        Conflict resolution handled automatically by CRDT properties
        """
        # Merge text content
        self._text.merge(other._text)
        
        # Merge metadata
        self._metadata.title.merge(other._metadata.title)
        self._metadata.description.merge(other._metadata.description)
        self._metadata.tags.union(other._metadata.tags)
        self._metadata.authors.union(other._metadata.authors)
        self._metadata.version.merge(other._metadata.version)
        
        # Merge vector clocks (take max)
        for node_id, clock in other._vector_clock.items():
            self._vector_clock[node_id] = max(
                self._vector_clock.get(node_id, 0),
                clock
            )
        
        # Merge operation logs
        self._operation_log.extend(other._operation_log)
        
        # Update stats
        self._stats["total_inserts"] += other._stats["total_inserts"]
        self._stats["total_deletes"] += other._stats["total_deletes"]
        self._stats["sync_count"] += 1
    
    def get_sync_operations(self) -> List[TextOperation]:
        """Get operations since last sync"""
        ops = self._operation_log.copy()
        self._operation_log.clear()
        return ops
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize document to dict"""
        return {
            "document_id": self.document_id,
            "node_id": self.node_id,
            "text": self._text.to_dict(),
            "metadata": {
                "title": self._metadata.title.to_dict(),
                "description": self._metadata.description.to_dict(),
                "tags": self._metadata.tags.to_dict(),
                "authors": self._metadata.authors.to_dict(),
                "version": self._metadata.version.to_dict(),
                "created_at": self._metadata.created_at.to_dict(),
                "updated_at": self._metadata.updated_at.to_dict(),
            },
            "vector_clock": dict(self._vector_clock),
            "stats": dict(self._stats),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CRDTDocument':
        """Deserialize document from dict"""
        doc = cls(data["document_id"], data["node_id"])
        
        doc._text = RGACRDT.from_dict(data["text"])
        
        # Deserialize metadata
        meta_data = data["metadata"]
        doc._metadata.title = LWWRegisterCRDT.from_dict(meta_data["title"])
        doc._metadata.description = LWWRegisterCRDT.from_dict(meta_data["description"])
        doc._metadata.tags = ORSetCRDT.from_dict(meta_data["tags"])
        doc._metadata.authors = GSetCRDT.from_dict(meta_data["authors"])
        doc._metadata.version = PNCounterCRDT.from_dict(meta_data["version"])
        doc._metadata.created_at = LWWRegisterCRDT.from_dict(meta_data["created_at"])
        doc._metadata.updated_at = LWWRegisterCRDT.from_dict(meta_data["updated_at"])
        
        doc._vector_clock = data["vector_clock"]
        doc._stats = data["stats"]
        
        return doc
    
    def get_stats(self) -> Dict[str, Any]:
        """Get document statistics"""
        return {
            **self._stats,
            "text_length": len(self.get_text()),
            "character_count": self._text._total_inserts - self._text._total_deletes,
            "operation_log_size": len(self._operation_log),
            "version": self._metadata.version.value(),
        }


# Global manager for documents
_document_registry: Dict[str, CRDTDocument] = {}
_registry_lock = __import__('threading').RLock()


def get_document(document_id: str, node_id: str) -> CRDTDocument:
    """Get or create document instance"""
    global _document_registry
    
    with _registry_lock:
        key = f"{document_id}:{node_id}"
        
        if key not in _document_registry:
            _document_registry[key] = CRDTDocument(document_id, node_id)
        
        return _document_registry[key]


def reset_document_registry() -> None:
    """Reset document registry (for testing)"""
    global _document_registry
    with _registry_lock:
        _document_registry.clear()
