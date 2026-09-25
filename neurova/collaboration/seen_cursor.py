"""
Seen-Cursor Tracking System - Freshness Preflight Implementation
"""

import json
import hashlib
import threading
import time
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field

from neurova.core.logger import get_logger
from neurova.core.data_root import callerPath

logger = get_logger(__name__)

@dataclass
class SeenCursor:
    """
    Seen Cursor: 记录 agent 已看到的原子操作

    - cursor_id: unique identifier for this seen state
    - hash: SHA256 hash of the atomic operations
    - timestamp: when this cursor was created
    """

    cursor_id: str = field(default_factory=lambda: f"seen_{hashlib.sha256(str(time.time()).encode()).hexdigest()[:16]}")
    agent_id: str = ""
    session_id: Optional[str] = None
    turn_id: Optional[str] = None

    # Atomic operation hashes (deterministic)
    op_hashes: List[str] = field(default_factory=list)

    # Metadata
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "cursor_id": self.cursor_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "op_hashes": self.op_hashes.copy(),
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SeenCursor":
        """从字典创建"""
        return cls(
            cursor_id=data.get("cursor_id", ""),
            agent_id=data.get("agent_id", ""),
            session_id=data.get("session_id"),
            turn_id=data.get("turn_id"),
            op_hashes=data.get("op_hashes", []),
            created_at=data.get("created_at", time.time()),
            metadata=data.get("metadata", {}),
        )

    def add_operation_hash(self, hash_value: str) -> None:
        """添加操作哈希"""
        if hash_value not in self.op_hashes:
            self.op_hashes.append(hash_value)

    def compute_hash(self) -> str:
        """计算整个 cursor 的哈希值"""
        content = f"{self.agent_id}:{self.session_id}:{self.turn_id}:{','.join(sorted(self.op_hashes))}"
        return hashlib.sha256(content.encode()).hexdigest()

class SeenCursorManager:
    """
    Seen-Cursor Manager

    功能:
    1. 记录每个 agent 已看到的原子操作
    2. 检测碰撞 (collision detection)
    3. 提供新鲜度检查 (freshness preflight)
    """

    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, data_dir: Optional[str] = None):
        if self._initialized:
            return

        self.data_dir = callerPath(data_dir, "seen-cursors")

        # Thread safety
        self._lock = threading.RLock()

        # Storage: {agent_id: {cursor_id: SeenCursor}}
        self._cursors: Dict[str, Dict[str, SeenCursor]] = {}

        # Indexes: {agent_id: set(cursor_ids)}
        self._agent_cursors: Dict[str, Set[str]] = {}

        # Latest cursor per agent: {agent_id: cursor_id}
        self._latest_cursors: Dict[str, str] = {}

        # Initialize
        self._on_init()

        logger.info("SeenCursorManager initialized")

    def _on_init(self) -> None:
        """初始化回调"""
        self._init_dirs()
        self._load_cursors()

    def _init_dirs(self) -> None:
        """初始化目录结构"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            (self.data_dir / "agents").mkdir(exist_ok=True)
            (self.data_dir / "backups").mkdir(exist_ok=True)

            logger.info(f"Initialized seen-cursor directories: {self.data_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize directories: {e}")

    def _load_cursors(self) -> None:
        """加载所有 Seen Cursors"""
        try:
            agents_dir = self.data_dir / "agents"
            if not agents_dir.exists():
                return

            for agent_file in agents_dir.glob("*.json"):
                try:
                    with open(agent_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    agent_id = data["agent_id"]
                    self._agent_cursors[agent_id] = set()

                    for cursor_data in data.get("cursors", []):
                        cursor = SeenCursor.from_dict(cursor_data)
                        self._cursors.setdefault(agent_id, {})[cursor.cursor_id] = cursor
                        self._agent_cursors[agent_id].add(cursor.cursor_id)

                        # Track latest
                        if cursor.cursor_id not in self._latest_cursors or \
                           cursor.created_at > self._cursors[agent_id][self._latest_cursors[agent_id]].created_at:
                            self._latest_cursors[agent_id] = cursor.cursor_id

                except Exception as e:
                    logger.warning(f"Failed to load cursor file {agent_file}: {e}")

            logger.info(f"Loaded cursors for {len(self._agent_cursors)} agents")

        except Exception as e:
            logger.error(f"Failed to load cursors: {e}")

    def _save_agent_cursors(self, agent_id: str) -> bool:
        """保存 agent 的所有 cursors"""
        try:
            agents_dir = self.data_dir / "agents"
            agent_file = agents_dir / f"{agent_id}.json"

            data = {
                "agent_id": agent_id,
                "cursors": [
                    c.to_dict() for c in self._cursors.get(agent_id, {}).values()
                ],
                "latest_cursor_id": self._latest_cursors.get(agent_id),
            }

            with open(agent_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.debug(f"Saved cursors for agent: {agent_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to save cursors for {agent_id}: {e}")
            return False

    def create_cursor(
        self,
        agent_id: str,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        op_hashes: Optional[List[str]] = None,
    ) -> SeenCursor:
        """
        创建新的 Seen Cursor

        Args:
            agent_id: Agent ID
            session_id: Session ID
            turn_id: Turn ID
            op_hashes: 初始操作哈希列表

        Returns:
            新创建的 SeenCursor
        """
        with self._lock:
            cursor = SeenCursor(
                agent_id=agent_id,
                session_id=session_id,
                turn_id=turn_id,
                op_hashes=op_hashes or [],
            )

            # Store
            self._cursors.setdefault(agent_id, {})[cursor.cursor_id] = cursor

            # Update indexes
            self._agent_cursors.setdefault(agent_id, set()).add(cursor.cursor_id)
            self._latest_cursors[agent_id] = cursor.cursor_id

            # Save
            self._save_agent_cursors(agent_id)

            logger.debug(f"Created cursor {cursor.cursor_id} for agent {agent_id}")
            return cursor

    def add_operation_to_cursor(
        self,
        agent_id: str,
        cursor_id: str,
        operation_hash: str,
    ) -> bool:
        """
        将操作添加到现有 cursor

        Args:
            agent_id: Agent ID
            cursor_id: Cursor ID
            operation_hash: 操作哈希

        Returns:
            是否成功
        """
        with self._lock:
            agent_cursors = self._cursors.get(agent_id, {})
            cursor = agent_cursors.get(cursor_id)

            if not cursor:
                logger.warning(f"Cursor not found: {cursor_id}")
                return False

            cursor.add_operation_hash(operation_hash)
            self._save_agent_cursors(agent_id)

            return True

    def get_latest_cursor(self, agent_id: str) -> Optional[SeenCursor]:
        """
        获取 agent 的最新 cursor

        Args:
            agent_id: Agent ID

        Returns:
            Latest SeenCursor 或 None
        """
        with self._lock:
            cursor_id = self._latest_cursors.get(agent_id)
            if not cursor_id:
                return None

            return self._cursors.get(agent_id, {}).get(cursor_id)

    def check_freshness(
        self,
        agent_id: str,
        expected_op_hashes: List[str],
    ) -> Tuple[bool, Optional[str]]:
        """
        新鲜度预检 (Freshness Preflight)

        Check if proposed operations are fresh (not seen before)

        Args:
            agent_id: Agent ID
            expected_op_hashes: 期望的操作哈希列表

        Returns:
            (is_fresh, collision_reason)
            - is_fresh: 是否新鲜 (未见过)
            - collision_reason: 如果碰撞，返回原因
        """
        with self._lock:
            latest_cursor = self.get_latest_cursor(agent_id)

            if not latest_cursor:
                # No history, everything is fresh
                return True, None

            # Compute hash of expected operations
            expected_hash = self._compute_operations_hash(expected_op_hashes)

            # Check if any expected operation has been seen
            for op_hash in expected_op_hashes:
                if op_hash in latest_cursor.op_hashes:
                    # Collision detected!
                    return False, f"Operation {op_hash[:16]} already seen in cursor {latest_cursor.cursor_id[:16]}"

            # Check if entire set matches
            if len(expected_op_hashes) == len(latest_cursor.op_hashes):
                if set(expected_op_hashes) == set(latest_cursor.op_hashes):
                    return False, f"Identical operations already processed in cursor {latest_cursor.cursor_id[:16]}"

            return True, None

    def record_operations(
        self,
        agent_id: str,
        session_id: str,
        turn_id: str,
        operation_hashes: List[str],
    ) -> SeenCursor:
        """
        记录操作到最新 cursor

        Args:
            agent_id: Agent ID
            session_id: Session ID
            turn_id: Turn ID
            operation_hashes: 操作哈希列表

        Returns:
            Updated SeenCursor
        """
        with self._lock:
            # Get or create cursor
            cursor = self.get_latest_cursor(agent_id)

            if not cursor:
                cursor = self.create_cursor(
                    agent_id=agent_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    op_hashes=operation_hashes,
                )
                # Update metadata for new cursor
                cursor.metadata["last_session"] = session_id
                cursor.metadata["last_turn"] = turn_id
                cursor.created_at = time.time()

                self._save_agent_cursors(agent_id)
            else:
                # Add new operations
                for op_hash in operation_hashes:
                    cursor.add_operation_hash(op_hash)

                # Update metadata
                cursor.metadata["last_session"] = session_id
                cursor.metadata["last_turn"] = turn_id
                cursor.created_at = time.time()

                self._save_agent_cursors(agent_id)

            logger.debug(f"Recorded {len(operation_hashes)} operations for agent {agent_id}")
            return cursor

    def detect_collision(
        self,
        agent_id: str,
        proposed_operations: List[str],
    ) -> Optional[str]:
        """
        检测碰撞

        Args:
            agent_id: Agent ID
            proposed_operations: 提议的操作列表

        Returns:
            Collision reason if detected, None otherwise
        """
        is_fresh, reason = self.check_freshness(agent_id, proposed_operations)

        if not is_fresh:
            return reason

        return None

    def _compute_operations_hash(self, operation_hashes: List[str]) -> str:
        """计算操作集合的哈希"""
        sorted_ops = sorted(operation_hashes)
        content = ",".join(sorted_ops)
        return hashlib.sha256(content.encode()).hexdigest()

    def cleanup_old_cursors(self, keep_count: int = 100) -> int:
        """
        清理旧的 cursors

        Args:
            keep_count: 保留最新的数量

        Returns:
            清理数量
        """
        with self._lock:
            cleaned_count = 0

            for agent_id in list(self._cursors.keys()):
                cursors = sorted(
                    self._cursors[agent_id].values(),
                    key=lambda c: c.created_at,
                    reverse=True,
                )

                if len(cursors) > keep_count:
                    # Remove old cursors
                    for old_cursor in cursors[keep_count:]:
                        del self._cursors[agent_id][old_cursor.cursor_id]
                        self._agent_cursors[agent_id].discard(old_cursor.cursor_id)
                        cleaned_count += 1

                    self._save_agent_cursors(agent_id)

            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} old cursors")

            return cleaned_count

# Global instance management
_seen_cursor_manager_instance: Optional[SeenCursorManager] = None
_seen_cursor_manager_lock = threading.Lock()

def get_seen_cursor_manager() -> SeenCursorManager:
    """获取全局 SeenCursorManager 实例 (Singleton)"""
    global _seen_cursor_manager_instance

    if _seen_cursor_manager_instance is None:
        with _seen_cursor_manager_lock:
            if _seen_cursor_manager_instance is None:
                _seen_cursor_manager_instance = SeenCursorManager()

    return _seen_cursor_manager_instance

def reset_seen_cursor_manager() -> None:
    """重置 SeenCursorManager 实例 (用于测试)"""
    global _seen_cursor_manager_instance
    _seen_cursor_manager_instance = None
