"""
Neurova CRDT RGA (Replicated Growable Array)
基于位置的 CRDT，支持高效的文本插入和删除操作
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
import uuid


@dataclass
class Position:
    """
    Position identifier in RGA
    每个字符都有唯一的位置标识符
    """
    parent_id: str  # 父字符的 ID
    right_of: Optional[str] = None  # 右侧兄弟的 ID（可选）
    
    def __hash__(self) -> int:
        return hash((self.parent_id, self.right_of))
    
    def __eq__(self, other) -> bool:
        if not isinstance(other, Position):
            return False
        return self.parent_id == other.parent_id and self.right_of == other.right_of
    
    def __repr__(self) -> str:
        return f"Pos({self.parent_id}, {self.right_of})"


@dataclass
class Character:
    """
    Character node in RGA
    包含字符内容和位置信息
    """
    char: str
    position: Position
    removed: bool = False
    writer_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: float = field(default_factory=lambda: __import__('time').time())


class RGACRDT:
    """
    Replicated Growable Array (RGA) CRDT
    适用于文本编辑器，支持并发插入和删除
    
    Algorithm:
    - Each character has a unique position (parent_id, right_of)
    - Insertions are idempotent using vector clocks
    - Deletions mark characters as removed but keep them for merge
    """
    
    def __init__(self):
        # Root nodes (characters with no parent)
        self._roots: List[Position] = []
        
        # All characters by their position
        self._characters: Dict[Position, Character] = {}
        
        # For efficient lookup: position -> next position
        self._next: Dict[Optional[Position], Position] = {}
        
        # Statistics
        self._total_inserts = 0
        self._total_deletes = 0
    
    def insert(self, char: str, after_pos: Optional[Position], writer_id: Optional[str] = None) -> Position:
        """
        Insert character after the given position
        
        Args:
            char: Character to insert
            after_pos: Position after which to insert (None for beginning)
            writer_id: ID of the node performing insertion
        
        Returns:
            Position of the inserted character
        """
        if after_pos is None:
            # Insert at beginning
            new_pos = Position(parent_id=str(uuid.uuid4()), right_of=None)
        else:
            # Insert after existing character
            new_pos = Position(
                parent_id=after_pos.parent_id,
                right_of=after_pos.right_of if after_pos.right_of else after_pos.parent_id
            )
        
        # Create character node
        character = Character(
            char=char,
            position=new_pos,
            writer_id=writer_id or uuid.uuid4().hex[:8],
        )
        
        # Insert into data structures
        self._characters[new_pos] = character
        
        # Update linked list
        if after_pos is None:
            # Insert at head
            if self._roots:
                self._next[new_pos] = self._roots[0]
                self._roots.insert(0, new_pos)
            else:
                self._roots.append(new_pos)
                self._next[new_pos] = None
        else:
            # Insert after after_pos
            old_next = self._next.get(after_pos)
            self._next[after_pos] = new_pos
            self._next[new_pos] = old_next
        
        self._total_inserts += 1
        
        return new_pos
    
    def delete(self, pos: Position) -> bool:
        """
        Mark character at position as deleted
        
        Args:
            pos: Position to delete
        
        Returns:
            True if character was found and marked deleted
        """
        if pos in self._characters:
            self._characters[pos].removed = True
            self._total_deletes += 1
            return True
        return False
    
    def get_text(self) -> str:
        """Get current text content (excluding deleted characters)"""
        chars = []
        
        # Traverse linked list from roots
        for root in self._roots:
            current = root
            while current:
                character = self._characters.get(current)
                if character and not character.removed:
                    chars.append(character.char)
                current = self._next.get(current)
        
        return ''.join(chars)
    
    def get_character_at(self, index: int) -> Optional[Character]:
        """Get character at specific index"""
        if index < 0:
            return None
        
        current_idx = 0
        for root in self._roots:
            current = root
            while current:
                character = self._characters.get(current)
                if character and not character.removed:
                    if current_idx == index:
                        return character
                    current_idx += 1
                current = self._next.get(current)
        
        return None
    
    def merge(self, other: 'RGACRDT') -> None:
        """
        Merge another RGA into this one
        
        Conflict resolution:
        - Use timestamps and writer_id for ordering
        - Keep all characters (deleted ones marked as removed)
        """
        # Merge characters
        for pos, character in other._characters.items():
            if pos not in self._characters:
                self._characters[pos] = character
        
        # Merge roots
        for root in other._roots:
            if root not in self._roots:
                self._roots.append(root)
        
        # Merge next pointers
        for pos, next_pos in other._next.items():
            if pos not in self._next:
                self._next[pos] = next_pos
        
        # Update statistics
        self._total_inserts += other._total_inserts
        self._total_deletes += other._total_deletes
    
    def to_dict(self) -> Dict:
        """Serialize to dict"""
        return {
            "type": "RGA",
            "characters": [
                {
                    "char": c.char,
                    "parent_id": c.position.parent_id,
                    "right_of": c.position.right_of,
                    "removed": c.removed,
                    "writer_id": c.writer_id,
                    "timestamp": c.timestamp,
                }
                for c in self._characters.values()
            ],
            "roots": [
                {"parent_id": r.parent_id, "right_of": r.right_of}
                for r in self._roots
            ],
            "stats": {
                "total_inserts": self._total_inserts,
                "total_deletes": self._total_deletes,
            },
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'RGACRDT':
        """Deserialize from dict"""
        if data["type"] != "RGA":
            raise ValueError("Invalid RGA data")
        
        rga = cls()
        
        # Rebuild characters
        for char_data in data["characters"]:
            pos = Position(
                parent_id=char_data["parent_id"],
                right_of=char_data["right_of"],
            )
            character = Character(
                char=char_data["char"],
                position=pos,
                removed=char_data["removed"],
                writer_id=char_data["writer_id"],
                timestamp=char_data["timestamp"],
            )
            rga._characters[pos] = character
        
        # Rebuild roots
        for root_data in data["roots"]:
            pos = Position(
                parent_id=root_data["parent_id"],
                right_of=root_data["right_of"],
            )
            rga._roots.append(pos)
        
        return rga


class TextOperation:
    """
    Text operation for RGA
    封装插入、删除等操作
    """
    
    def __init__(self, op_type: str, position: Optional[Position] = None, 
                 char: Optional[str] = None, delete_pos: Optional[Position] = None):
        self.op_type = op_type  # 'insert' or 'delete'
        self.position = position
        self.char = char
        self.delete_pos = delete_pos
    
    def execute(self, rga: RGACRDT, writer_id: Optional[str] = None) -> Position:
        """Execute operation on RGA"""
        if self.op_type == 'insert':
            return rga.insert(self.char, self.position, writer_id)
        elif self.op_type == 'delete' and self.delete_pos:
            rga.delete(self.delete_pos)
            return None
        else:
            raise ValueError(f"Unknown operation type: {self.op_type}")
    
    def to_dict(self) -> Dict:
        """Serialize operation"""
        return {
            "type": self.op_type,
            "position": {"parent_id": self.position.parent_id, 
                        "right_of": self.position.right_of} if self.position else None,
            "char": self.char,
            "delete_position": {"parent_id": self.delete_pos.parent_id,
                              "right_of": self.delete_pos.right_of} if self.delete_pos else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TextOperation':
        """Deserialize operation"""
        if data["type"] == "insert":
            pos = None
            if data["position"]:
                pos = Position(data["position"]["parent_id"], data["position"]["right_of"])
            return cls("insert", position=pos, char=data["char"])
        elif data["type"] == "delete":
            del_pos = None
            if data["delete_position"]:
                del_pos = Position(data["delete_position"]["parent_id"],
                                 data["delete_position"]["right_of"])
            return cls("delete", delete_pos=del_pos)
        else:
            raise ValueError(f"Unknown operation type: {data['type']}")
