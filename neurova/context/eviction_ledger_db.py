"""
驱逐台账持久化（P1-1③，对标 QP scroll HistoryStore）

SQLite WAL + FTS5：被驱逐/折叠的上下文 chunk 落库，重启后经 FTS 召回。
多用户分区：所有查询字面携带 user_id/agent_id 参数化条件——跨用户不可见
（非约定，是实现强制的；沿 _PersistDbStore 的隔离语义，但不做 SQL 字符串
拼接——所有隔离条件静态写死在每条查询里，天然通过参数化校验）。

设计：
- 每操作独立连接（WAL 已在 init 设置一次）
- FTS5 独立表 + 手动双写（rowid 对齐内容表，GC 时对齐清理）
- MATCH 语法错误安全降级为 LIKE 子串匹配
"""

from __future__ import annotations

import datetime
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evicted_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    session_id TEXT,
    turn_id TEXT,
    source TEXT,
    content TEXT NOT NULL,
    metadata TEXT,
    evicted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evicted_user ON evicted_chunks(user_id, agent_id);
CREATE VIRTUAL TABLE IF NOT EXISTS evicted_fts USING fts5(
    content,
    tokenize='unicode61 remove_diacritics 2'
);
"""


class EvictionLedgerDB:
    """驱逐台账持久层（WAL + FTS5，隔离条件静态写死）。"""

    def __init__(
        self,
        db_path: Path | str,
        user_id: str,
        agent_id: str,
        keep_count: int = 5000,
        keep_days: int = 30,
    ):
        self.db_path = str(Path(db_path))
        self.user_id = user_id
        self.agent_id = agent_id
        self.keep_count = keep_count
        self.keep_days = keep_days
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def gc_stale(self) -> int:
        """按实例保留策略（keep_count/keep_days）清理；供定期触发调用。"""
        return self.gc(keep_count=self.keep_count, keep_days=self.keep_days)

    def _init_schema(self) -> None:
        """建表 + WAL：幂等（IF NOT EXISTS），WAL 提升并发读写。"""
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def record(
        self,
        *,
        content: str,
        turn_id: Optional[str] = None,
        session_id: Optional[str] = None,
        source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录一次驱逐；content 同时写入 FTS 表。"""
        now = datetime.datetime.now().isoformat()
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO evicted_chunks"
                " (user_id, agent_id, session_id, turn_id, source, content, metadata, evicted_at)"
                " VALUES (:user_id, :agent_id, :session_id, :turn_id, :source, :content, :metadata, :evicted_at)",
                {
                    "user_id": self.user_id,
                    "agent_id": self.agent_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "source": source,
                    "content": content,
                    "metadata": json.dumps(metadata, ensure_ascii=False, default=str) if metadata else None,
                    "evicted_at": now,
                },
            )
            conn.execute(
                "INSERT INTO evicted_fts(rowid, content) VALUES (:rowid, :content)",
                {"rowid": cur.lastrowid, "content": content},
            )
            conn.commit()
        finally:
            conn.close()

    def search(
        self,
        query: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """召回：query 非空走 FTS5 MATCH，空结果/语法错误降级 LIKE（CJK 友好）。

        unicode61 分词器不切 CJK（连续中文整块成词），中文查询在 FTS 下
        常返回空——空结果自动降级 LIKE 子串匹配。
        """
        if query:
            hits: List[Dict[str, Any]] = []
            try:
                hits = self._connect().execute(
                    "SELECT e.*, e.id AS _row FROM evicted_chunks e"
                    " JOIN evicted_fts f ON e.id = f.rowid"
                    " WHERE e.user_id = :user_id AND e.agent_id = :agent_id"
                    " AND evicted_fts MATCH :fts_query"
                    " AND (:session_id IS NULL OR e.session_id = :session_id)"
                    " ORDER BY e.id DESC LIMIT :limit",
                    {
                        "user_id": self.user_id,
                        "agent_id": self.agent_id,
                        "fts_query": self._fts_safe(query),
                        "session_id": session_id,
                        "limit": limit,
                    },
                ).fetchall()
            except sqlite3.OperationalError:
                logger.info("FTS query failed, fallback to LIKE search")

            if not hits:
                hits = self._connect().execute(
                    "SELECT *, id AS _row FROM evicted_chunks"
                    " WHERE user_id = :user_id AND agent_id = :agent_id"
                    " AND content LIKE :like"
                    " AND (:session_id IS NULL OR session_id = :session_id)"
                    " ORDER BY id DESC LIMIT :limit",
                    {
                        "user_id": self.user_id,
                        "agent_id": self.agent_id,
                        "like": f"%{query}%",
                        "session_id": session_id,
                        "limit": limit,
                    },
                ).fetchall()
            return hits

        return self._connect().execute(
            "SELECT *, id AS _row FROM evicted_chunks"
            " WHERE user_id = :user_id AND agent_id = :agent_id"
            " AND (:session_id IS NULL OR session_id = :session_id)"
            " ORDER BY id DESC LIMIT :limit",
            {"user_id": self.user_id, "agent_id": self.agent_id, "session_id": session_id, "limit": limit},
        ).fetchall()

    @staticmethod
    def _fts_safe(query: str) -> str:
        """FTS5 短语安全化：包裹双引号并转义内部引号，避免 MATCH 语法错误。"""
        escaped = (query or "").replace('"', '""')
        return f'"{escaped}"'

    def count(self) -> int:
        row = self._connect().execute(
            "SELECT COUNT(*) AS c FROM evicted_chunks"
            " WHERE user_id = :user_id AND agent_id = :agent_id",
            {"user_id": self.user_id, "agent_id": self.agent_id},
        ).fetchone()
        return int(row["c"]) if row else 0

    def gc(self, keep_count: Optional[int] = None, keep_days: Optional[int] = None) -> int:
        """按保留条数/天数清理本用户的过期台账；返回清理数量。"""
        removed = 0
        conn = self._connect()
        try:
            if keep_days is not None:
                cutoff = (
                    datetime.datetime.now() - datetime.timedelta(days=keep_days)
                ).isoformat()
                cur = conn.execute(
                    "DELETE FROM evicted_chunks"
                    " WHERE user_id = :user_id AND agent_id = :agent_id"
                    " AND evicted_at < :cutoff",
                    {"user_id": self.user_id, "agent_id": self.agent_id, "cutoff": cutoff},
                )
                removed += cur.rowcount
            if keep_count is not None:
                cur = conn.execute(
                    "DELETE FROM evicted_chunks WHERE id IN ("
                    "  SELECT id FROM evicted_chunks"
                    "  WHERE user_id = :user_id AND agent_id = :agent_id"
                    "  ORDER BY id DESC LIMIT -1 OFFSET :keep_count"
                    ")",
                    {"user_id": self.user_id, "agent_id": self.agent_id, "keep_count": keep_count},
                )
                removed += cur.rowcount

            # FTS 与内容表对齐：清掉不在内容表里的 FTS 行
            conn.execute(
                "DELETE FROM evicted_fts WHERE rowid NOT IN (SELECT id FROM evicted_chunks)"
            )
            conn.commit()
        finally:
            conn.close()
        return removed
