"""
认知图谱统一存储引擎 — LSM-Tree 五层架构

替代 mem_core.py + conversation_buffer.py + unified_vector_store.py，
提供统一的记忆节点模型和跨层检索能力。

层级:
  L0 Buffer  — WAL 缓冲区（秒级，内存 + JSONL 文件）
  L1 Hot     — SQLite 热存储（分钟级）
  L2 Warm    — JSON 温存储（NeurovaHebb 专用，小时级）
  L3 Cold    — 压缩冷存储（天级）
  L4 Crystal — 结晶经验（永久）
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────────────


class MemoryType(Enum):
    """记忆类型"""

    EPISODIC = "episodic"  # 事件记忆
    SEMANTIC = "semantic"  # 语义知识
    PROCEDURAL = "procedural"  # 程序性知识（工具使用）
    PATTERN = "pattern"  # 结晶经验
    TOOL_MEMORY = "tool_memory"  # 工具记忆


class StorageLayer(Enum):
    """存储层级"""

    L0_BUFFER = 0  # WAL 缓冲区（秒级）
    L1_HOT = 1  # SQLite 热存储（分钟级）
    L2_WARM = 2  # JSON 温存储（小时级）
    L3_COLD = 3  # 压缩冷存储（天级）
    L4_CRYSTAL = 4  # 结晶经验（永久）


@dataclass
class UnifiedMemoryNode:
    """统一记忆节点 — 所有记忆类型的唯一数据模型"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    memory_type: MemoryType = MemoryType.SEMANTIC
    category: str = "general"
    temperature: float = 100.0  # 0-100 scale，统一
    layer: StorageLayer = StorageLayer.L1_HOT
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    access_count: int = 0
    trace_id: Optional[str] = None  # 推理链溯源

    def touch(self):
        """访问一次，温度升高"""
        self.access_count += 1
        self.temperature = min(100.0, self.temperature + 10.0)
        self.updated_at = datetime.now(timezone.utc)

    def decay(self, hours: float = 1.0, rate: float = 1.0):
        """温度衰减"""
        self.temperature = max(0.0, self.temperature - rate * hours)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        d = asdict(self)
        d["memory_type"] = self.memory_type.value
        d["layer"] = self.layer.value
        d["created_at"] = self.created_at.isoformat()
        d["updated_at"] = self.updated_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedMemoryNode":
        """从字典反序列化"""
        data = dict(data)  # copy
        if "memory_type" in data and isinstance(data["memory_type"], str):
            data["memory_type"] = MemoryType(data["memory_type"])
        if "layer" in data and isinstance(data["layer"], int):
            data["layer"] = StorageLayer(data["layer"])
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "updated_at" in data and isinstance(data["updated_at"], str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


# ── 存储引擎 ──────────────────────────────────────────────────────────────────

# SQLite DDL for L1
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    temperature REAL NOT NULL DEFAULT 100.0,
    layer INTEGER NOT NULL DEFAULT 1,
    metadata TEXT DEFAULT '{}',
    embedding TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    access_count INTEGER DEFAULT 0,
    trace_id TEXT
)
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_cse_memory_type ON memories(memory_type)",
    "CREATE INDEX IF NOT EXISTS idx_cse_category ON memories(category)",
    "CREATE INDEX IF NOT EXISTS idx_cse_temperature ON memories(temperature)",
    "CREATE INDEX IF NOT EXISTS idx_cse_trace_id ON memories(trace_id)",
    "CREATE INDEX IF NOT EXISTS idx_cse_created_at ON memories(created_at)",
]

# FTS5 for full-text search
_CREATE_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content)
"""

_CREATE_FTS_TRIGGER_SQL = [
    """
    CREATE TRIGGER IF NOT EXISTS cse_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS cse_ad AFTER DELETE ON memories BEGIN
        DELETE FROM memories_fts WHERE rowid = old.rowid;
    END
    """,
]

_FLUSH_THRESHOLD = 100  # L0 buffer max size


class CognitiveStorageEngine:
    """统一存储引擎 — LSM-Tree 五层架构"""

    def __init__(self, agent_id: str, data_dir: str = None):
        self.agent_id = agent_id
        self.data_dir = Path(data_dir or f"data/{agent_id}")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # L0: WAL 缓冲区（内存 + 文件）
        self._l0_buffer: List[UnifiedMemoryNode] = []
        self._wal_path = self.data_dir / "wal.jsonl"
        self._wal_lock = threading.Lock()

        # L1: SQLite 热存储
        self._db_path = self.data_dir / "memory.db"
        self._db_lock = threading.RLock()
        self._db: sqlite3.Connection = self._init_db()

        # 内存向量索引（简单实现，后续可换 FAISS）
        self._vector_index: Dict[str, List[float]] = {}
        self._embed_fn = None  # 延迟初始化

        # 恢复 WAL 中未 flush 的数据
        self._recover_wal()

        logger.info(
            f"CognitiveStorageEngine initialized: agent={agent_id}, "
            f"L0={len(self._l0_buffer)} nodes, db={self._db_path}"
        )

    def _init_db(self) -> sqlite3.Connection:
        """初始化 SQLite 数据库"""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        with self._db_lock:
            conn.executescript(_CREATE_TABLE_SQL)
            for idx_sql in _CREATE_INDEXES_SQL:
                try:
                    conn.execute(idx_sql)
                except sqlite3.OperationalError:
                    pass
            try:
                conn.executescript(_CREATE_FTS_SQL)
                for trigger_sql in _CREATE_FTS_TRIGGER_SQL:
                    conn.execute(trigger_sql)
            except sqlite3.OperationalError:
                logger.warning("FTS5 not available")
            conn.commit()
        return conn

    def _recover_wal(self):
        """S-1: 从 WAL 文件恢复未 flush 的数据(整体在锁内保护)"""
        if not self._wal_path.exists():
            return
        recovered = 0
        try:
            # S-1: 整个恢复过程在 db_lock 内,防止与并发 store 操作竞态
            with self._db_lock, self._wal_lock:
                with open(self._wal_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            node = UnifiedMemoryNode.from_dict(data)
                            # Only recover nodes not already in L1
                            existing = self._db.execute(
                                "SELECT id FROM memories WHERE id = ?", (node.id,)
                            ).fetchone()
                            if existing is None:
                                self._l0_buffer.append(node)
                                if node.embedding:
                                    self._vector_index[node.id] = node.embedding
                                recovered += 1
                        except (json.JSONDecodeError, Exception) as e:
                            logger.warning("WAL recovery: skip bad entry: %s", e)
                # Rewrite WAL with only recovered entries
                if recovered > 0:
                    with open(self._wal_path, "w", encoding="utf-8") as f:
                        for node in self._l0_buffer:
                            f.write(json.dumps(node.to_dict(), ensure_ascii=False) + "\n")
                    logger.info("WAL recovery: restored %s nodes", recovered)
        except Exception as e:
            logger.error("WAL recovery failed: %s", e)

    _WAL_MAX_SIZE_BYTES = 10 * 1024 * 1024  # S-2: WAL 最大 10MB

    def _wal_append(self, node: UnifiedMemoryNode):
        """追加到 WAL 文件"""
        with self._wal_lock:
            try:
                with open(self._wal_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(node.to_dict(), ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error("WAL append failed: %s", e)

            # S-2: WAL 文件大小监控,超限时强制 flush + rotate
            try:
                wal_size = self._wal_path.stat().st_size if self._wal_path.exists() else 0
                if wal_size > self._WAL_MAX_SIZE_BYTES:
                    logger.warning("WAL file size %.1f MB exceeds limit, forcing flush", wal_size / 1024 / 1024)
                    self._flush_l0_to_l1()
            except Exception as e:
                logger.warning("WAL size check failed: %s", e)

    def _flush_l0_to_l1(self):
        """将 L0 缓冲区 flush 到 L1 SQLite"""
        if not self._l0_buffer:
            return
        nodes = self._l0_buffer[:]
        self._l0_buffer.clear()
        with self._db_lock:
            for node in nodes:
                self._db.execute(
                    """INSERT OR REPLACE INTO memories
                       (id, content, memory_type, category, temperature, layer,
                        metadata, embedding, created_at, updated_at, access_count, trace_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        node.id,
                        node.content,
                        node.memory_type.value,
                        node.category,
                        node.temperature,
                        node.layer.value,
                        json.dumps(node.metadata, ensure_ascii=False),
                        json.dumps(node.embedding) if node.embedding else None,
                        node.created_at.isoformat(),
                        node.updated_at.isoformat(),
                        node.access_count,
                        node.trace_id,
                    ),
                )
            self._db.commit()
        # Clear WAL after successful flush
        with self._wal_lock:
            try:
                with open(self._wal_path, "w", encoding="utf-8") as f:
                    pass  # truncate
            except Exception as e:
                logger.error("WAL clear failed: %s", e)
        logger.debug("Flushed %s nodes from L0 to L1", len(nodes))

    def store(self, node: UnifiedMemoryNode) -> str:
        """写入记忆节点"""
        # 1. 写 WAL（崩溃恢复）
        self._wal_append(node)
        # 2. 写 L0 缓冲
        self._l0_buffer.append(node)
        # 3. 更新向量索引
        if node.embedding:
            self._vector_index[node.id] = node.embedding
        # 4. L0 满了就 flush 到 L1
        if len(self._l0_buffer) >= _FLUSH_THRESHOLD:
            self._flush_l0_to_l1()
        return node.id

    def _apply_filters(self, node: UnifiedMemoryNode, filters: Dict) -> bool:
        """检查节点是否满足过滤条件，返回 True 表示应跳过"""
        if not filters:
            return False
        for key, val in filters.items():
            if val is not None:
                if key == "memory_type" and node.memory_type.value != val:
                    return True
                elif key == "category" and node.category != val:
                    return True
        return False

    def retrieve(self, query: str, limit: int = 10, filters: Dict = None) -> List[UnifiedMemoryNode]:
        """跨层检索"""
        results: List[UnifiedMemoryNode] = []

        # 1. L0 缓冲搜索（文本匹配 + 过滤）
        for node in self._l0_buffer:
            if self._apply_filters(node, filters):
                continue
            if query.lower() in node.content.lower():
                results.append(node)

        # 2. L1 SQLite 搜索（FTS + 结构化）
        with self._db_lock:
            try:
                # FTS search
                rows = self._db.execute(
                    """SELECT m.id, m.content, m.memory_type, m.category,
                              m.temperature, m.layer, m.metadata, m.embedding,
                              m.created_at, m.updated_at, m.access_count, m.trace_id
                       FROM memories m
                       JOIN memories_fts f ON m.rowid = f.rowid
                       WHERE memories_fts MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    (query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                # Fallback to LIKE search
                rows = self._db.execute(
                    """SELECT id, content, memory_type, category,
                              temperature, layer, metadata, embedding,
                              created_at, updated_at, access_count, trace_id
                       FROM memories
                       WHERE content LIKE ?
                       ORDER BY temperature DESC
                       LIMIT ?""",
                    (f"%{query}%", limit),
                ).fetchall()

            for row in rows:
                node = self._row_to_node(row)
                if self._apply_filters(node, filters):
                    continue
                results.append(node)

        # S-4: 去重(按 id), 保留温度更高的那份
        seen: Dict[str, UnifiedMemoryNode] = {}
        for node in results:
            if node.id not in seen or node.temperature > seen[node.id].temperature:
                seen[node.id] = node
        deduped = list(seen.values())

        # 3. 排序（温度优先）
        deduped.sort(key=lambda n: n.temperature, reverse=True)
        return deduped[:limit]

    def _row_to_node(self, row: tuple) -> UnifiedMemoryNode:
        """SQLite 行转 UnifiedMemoryNode"""
        return UnifiedMemoryNode(
            id=row[0],
            content=row[1],
            memory_type=MemoryType(row[2]),
            category=row[3],
            temperature=row[4],
            layer=StorageLayer(row[5]),
            metadata=json.loads(row[6]) if row[6] else {},
            embedding=json.loads(row[7]) if row[7] else None,
            created_at=datetime.fromisoformat(row[8]),
            updated_at=datetime.fromisoformat(row[9]),
            access_count=row[10],
            trace_id=row[11],
        )

    def update_temperature(self, node_id: str, delta: float) -> None:
        """更新温度"""
        # 先查 L0
        for node in self._l0_buffer:
            if node.id == node_id:
                node.temperature = max(0.0, min(100.0, node.temperature + delta))
                # S-4: L0 命中时也同步更新 L1,避免 flush 前 retrieve 拿到旧值
                with self._db_lock:
                    self._db.execute(
                        "UPDATE memories SET temperature = MAX(0, MIN(100, temperature + ?)) WHERE id = ?",
                        (delta, node_id),
                    )
                    self._db.commit()
                return
        # 再查 L1
        with self._db_lock:
            self._db.execute(
                "UPDATE memories SET temperature = MAX(0, MIN(100, temperature + ?)) WHERE id = ?",
                (delta, node_id),
            )
            self._db.commit()

    def get_statistics(self) -> Dict[str, Any]:
        """各层统计"""
        with self._db_lock:
            l1_count = self._db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        return {
            "l0_buffer": len(self._l0_buffer),
            "l1_hot": l1_count,
            "vector_index_size": len(self._vector_index),
        }

    def close(self):
        """关闭引擎，确保数据持久化"""
        self._flush_l0_to_l1()
        self._db.close()
