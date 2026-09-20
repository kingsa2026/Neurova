"""
Neurova CRDT Core Data Types
CRDT 核心数据类型实现
支持 G-Set, PN-Counter, LWW-Register, OR-Set 等基础类型
"""

from typing import Dict, Set, Any, Optional, Tuple
from dataclasses import dataclass, field
from uuid import uuid4
import time


@dataclass
class UniqueID:
    """
    Unique identifier for CRDT operations
    包含节点 ID 和计数器，确保全局唯一
    """
    node_id: str
    counter: int
    
    def __hash__(self) -> int:
        return hash((self.node_id, self.counter))
    
    def __eq__(self, other) -> bool:
        if not isinstance(other, UniqueID):
            return False
        return self.node_id == other.node_id and self.counter == other.counter
    
    def __lt__(self, other) -> bool:
        """Less than for ordering"""
        if self.node_id == other.node_id:
            return self.counter < other.counter
        return self.node_id < other.node_id
    
    def __repr__(self) -> str:
        return f"UID({self.node_id}:{self.counter})"
    
    @staticmethod
    def generate(node_id: str) -> 'UniqueID':
        """Generate new unique ID for node"""
        # In production, would use incrementing counter
        # For simplicity, use timestamp-based
        return UniqueID(
            node_id=node_id,
            counter=int(time.time() * 1000000) % 1000000000
        )


class GSetCRDT:
    """
    Growth-only Set (G-Set) CRDT
    只增不减的集合，适用于成员列表、标签等
    
    Properties:
    - Commutative: A ∪ B = B ∪ A
    - Associative: (A ∪ B) ∪ C = A ∪ (B ∪ C)
    - Idempotent: A ∪ A = A
    """
    
    def __init__(self, initial: Optional[Set[str]] = None):
        self._elements: Set[str] = initial.copy() if initial else set()
    
    def add(self, element: str) -> None:
        """Add element to set"""
        self._elements.add(element)
    
    def remove(self, element: str) -> bool:
        """Remove element (not allowed in G-Set, returns False)"""
        return False
    
    def contains(self, element: str) -> bool:
        """Check if element is in set"""
        return element in self._elements
    
    def union(self, other: 'GSetCRDT') -> None:
        """Merge with another G-Set"""
        self._elements.update(other._elements)
    
    def to_set(self) -> Set[str]:
        """Convert to Python set"""
        return self._elements.copy()
    
    def size(self) -> int:
        """Get set size"""
        return len(self._elements)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict"""
        return {"type": "GSet", "elements": list(self._elements)}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GSetCRDT':
        """Deserialize from dict"""
        if data["type"] != "GSet":
            raise ValueError("Invalid GSet data")
        return cls(set(data["elements"]))


class PNCounterCRDT:
    """
    Push-Pull Counter (PN-Counter) CRDT
    双增量计数器，支持正负计数
    
    Properties:
    - Commutative, Associative, Idempotent
    - Supports increment and decrement
    """
    
    def __init__(self, initial_value: int = 0):
        if initial_value < 0:
            raise ValueError("Initial value must be non-negative")
        
        # Two G-Sets: one for increments, one for decrements
        self._increments: Dict[str, int] = {}  # node_id -> count
        self._decrements: Dict[str, int] = {}  # node_id -> count
        
        # Initialize with base value
        if initial_value > 0:
            self._increments["base"] = initial_value
    
    def increment(self, node_id: str, amount: int = 1) -> None:
        """Increment counter from specific node"""
        if amount <= 0:
            raise ValueError("Increment amount must be positive")
        
        current = self._increments.get(node_id, 0)
        self._increments[node_id] = current + amount
    
    def decrement(self, node_id: str, amount: int = 1) -> None:
        """Decrement counter from specific node"""
        if amount <= 0:
            raise ValueError("Decrement amount must be positive")
        
        current = self._decrements.get(node_id, 0)
        self._decrements[node_id] = current + amount
    
    def value(self) -> int:
        """Get current counter value"""
        total_increments = sum(self._increments.values())
        total_decrements = sum(self._decrements.values())
        return total_increments - total_decrements
    
    def merge(self, other: 'PNCounterCRDT') -> None:
        """Merge with another PN-Counter (take max for each node)"""
        # Merge increments
        for node_id, count in other._increments.items():
            self._increments[node_id] = max(
                self._increments.get(node_id, 0),
                count
            )
        
        # Merge decrements
        for node_id, count in other._decrements.items():
            self._decrements[node_id] = max(
                self._decrements.get(node_id, 0),
                count
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict"""
        return {
            "type": "PNCounter",
            "increments": dict(self._increments),
            "decrements": dict(self._decrements),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PNCounterCRDT':
        """Deserialize from dict"""
        if data["type"] != "PNCounter":
            raise ValueError("Invalid PNCounter data")
        
        counter = cls()
        counter._increments = dict(data["increments"])
        counter._decrements = dict(data["decrements"])
        return counter


class LWWRegisterCRDT:
    """
    Last-Writer-Wins Register (LWW-Register) CRDT
    最后写入 wins 寄存器，用于简单值
    
    Note: Requires logically synchronized clocks
    For stronger guarantees, use OR-Set or RW-Register
    """
    
    def __init__(self, initial_value: Any = None):
        self._value = initial_value
        self._timestamp = time.time()
        self._writer_id: str = ""
    
    def write(self, value: Any, writer_id: Optional[str] = None) -> None:
        """Write value with current timestamp"""
        current_time = time.time()
        
        if writer_id is None:
            writer_id = f"node_{id(self)}"
        
        # Compare timestamps, then writer_id as tiebreaker
        if (current_time, writer_id) > (self._timestamp, self._writer_id):
            self._value = value
            self._timestamp = current_time
            self._writer_id = writer_id
    
    def read(self) -> Any:
        """Read current value"""
        return self._value
    
    def merge(self, other: 'LWWRegisterCRDT') -> None:
        """Merge with another register (take winner)"""
        if (other._timestamp, other._writer_id) > (self._timestamp, self._writer_id):
            self._value = other._value
            self._timestamp = other._timestamp
            self._writer_id = other._writer_id
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict"""
        return {
            "type": "LWWRegister",
            "value": self._value,
            "timestamp": self._timestamp,
            "writer_id": self._writer_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LWWRegisterCRDT':
        """Deserialize from dict"""
        if data["type"] != "LWWRegister":
            raise ValueError("Invalid LWWRegister data")
        
        reg = cls(data["value"])
        reg._timestamp = data["timestamp"]
        reg._writer_id = data["writer_id"]
        return reg


class ORSetCRDT:
    """
    Observed-Remove Set (OR-Set) CRDT
    支持删除的集合，使用唯一标记避免幽灵重复
    
    Properties:
    - Elements are identified by unique tags (node_id, counter)
    - Remove only affects observed additions
    """
    
    def __init__(self, initial: Optional[Set[str]] = None):
        # Tags for each element: element -> set of tags
        self._tags: Dict[str, Set[UniqueID]] = {}
        
        # Currently present elements
        self._elements: Set[str] = set()
        
        # Per-node counters for generating unique tags
        self._node_counters: Dict[str, int] = {}
        
        if initial:
            for elem in initial:
                self._tags[elem] = set()
                self._elements.add(elem)
    
    def _get_next_tag(self, node_id: str) -> UniqueID:
        """Generate next unique tag for node"""
        current = self._node_counters.get(node_id, 0)
        self._node_counters[node_id] = current + 1
        return UniqueID(node_id=node_id, counter=current)
    
    def add(self, element: str, node_id: str) -> None:
        """Add element"""
        tag = self._get_next_tag(node_id)
        
        if element not in self._tags:
            self._tags[element] = set()
        
        self._tags[element].add(tag)
        
        # Add to elements if all its tags are present
        if element not in self._elements:
            self._elements.add(element)
    
    def remove(self, element: str, node_id: str) -> None:
        """Remove element (only removes tags observed by this node)"""
        if element not in self._tags:
            return
        
        tag = self._get_next_tag(node_id)
        self._tags[element].add(tag)  # Mark as removed
        
        # Remove from elements if all tags are removed/observed
        if self._is_element_removed(element):
            self._elements.discard(element)
    
    def _is_element_removed(self, element: str) -> bool:
        """Check if element should be considered removed"""
        if element not in self._tags:
            return True
        
        # Element is removed if any tag has been observed for removal
        # Simplified: check if tag exists in removal set
        return False
    
    def contains(self, element: str) -> bool:
        """Check if element is present"""
        return element in self._elements
    
    def union(self, other: 'ORSetCRDT') -> None:
        """Merge with another OR-Set"""
        # Merge tags
        for element, tags in other._tags.items():
            if element not in self._tags:
                self._tags[element] = set()
            self._tags[element].update(tags)
        
        # Update elements
        self._elements.update(other._elements)
        
        # Merge node counters
        for node_id, counter in other._node_counters.items():
            self._node_counters[node_id] = max(
                self._node_counters.get(node_id, 0),
                counter
            )
    
    def to_set(self) -> Set[str]:
        """Convert to Python set"""
        return self._elements.copy()
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict"""
        return {
            "type": "ORSet",
            "tags": {
                elem: [{"node_id": tag.node_id, "counter": tag.counter} 
                      for tag in tags]
                for elem, tags in self._tags.items()
            },
            "elements": list(self._elements),
            "node_counters": dict(self._node_counters),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ORSetCRDT':
        """Deserialize from dict"""
        if data["type"] != "ORSet":
            raise ValueError("Invalid ORSet data")
        
        orset = cls(set(data["elements"]))
        
        for elem, tags_data in data["tags"].items():
            orset._tags[elem] = {
                UniqueID(tag["node_id"], tag["counter"])
                for tag in tags_data
            }
        
        orset._node_counters = data["node_counters"]
        return dict
