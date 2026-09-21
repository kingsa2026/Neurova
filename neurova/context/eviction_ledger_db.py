"""
驱逐台账持久化

SQLite WAL + FTS5：被驱逐/折叠的上下文 chunk 落库，重启后经 FTS 召回。
多用户分区：所有查询字面携带 user_id/agent_id 参数化条件——跨用户不可见
（非约定，是实现强制的；沿 _PersistDbStore 的隔离语义，但不做 SQL 字符串
拼接——所有隔离条件静态写死在每条查询里，天然通过参数化校验）。

设计：
- 每操作独立连接（WAL 已在 init 设置一次）
- FTS5 独立表 + 手动双写（rowid 对齐内容表，GC 时对齐清理）
- MATCH 语法错误安全降级为 LIKE 子串匹配
- **schema 走 `core/db_migration` 的 `context_ledger` 版本域**（B4/002）：本库
  此前只有 `CREATE TABLE IF NOT EXISTS`，没有 `user_version`，后续每次改 schema
  都是裸改。v1 = `content_digest` / `created_at` / `chat_scope` 三列 +
  `uniq_digest` 唯一索引 + `idx_scope_id` 索引，并回填既有行。
- **作用域与时间另有读侧兜底**：v1 之前写入的行没有列值，`resolveArchivedScope`
  / `resolveArchivedCreatedAt` 分别回退到 metadata（经单一事实源
  `collaboration.memory_scope.scope_from_metadata`）与 `evicted_at`——
  不新写第二份作用域规则。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.collaboration.memory_scope import scope_from_metadata
from neurova.core.db_migration import migrate as applyMigrations, register_migration

logger = logging.getLogger(__name__)

LEDGER_DOMAIN = "context_ledger"

# v1 基础结构（表 + 分区索引 + FTS 影子表）。后续 schema 变更只加新版本号，
# 不再改这份基线 SQL。
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
    evicted_at TEXT NOT NULL,
    content_digest TEXT,
    created_at TEXT,
    chat_scope TEXT
);
CREATE INDEX IF NOT EXISTS idx_evicted_user ON evicted_chunks(user_id, agent_id);
CREATE VIRTUAL TABLE IF NOT EXISTS evicted_fts USING fts5(
    content,
    tokenize='unicode61 remove_diacritics 2'
);
"""

# v1 之前的历史表结构（列是后加的）；用于迁移期加列判断，不参与新建库
_V1_COLUMNS = ("content_digest", "created_at", "chat_scope")

# `(user_id, agent_id, id)`：热集查询实测 0.9 ms；按 `session` 收尾是负优化
# （33.9–35.5 ms），故索引以 `id` 收尾（规格 U4 定案）。
_SCOPE_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_scope_id ON evicted_chunks(user_id, agent_id, id)"
)
_DIGEST_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_digest"
    " ON evicted_chunks(user_id, agent_id, content_digest)"
)


def contentDigest(content: str) -> str:
    """归档内容指纹：唯一索引与同内容去重的判据（非安全用途）。"""
    return hashlib.sha256((content or "").encode("utf-8", errors="replace")).hexdigest()


def archivedMetadata(row: sqlite3.Row) -> Dict[str, Any]:
    """把一行读成 metadata dict（JSON 解析失败按无 metadata 处理，不抛）。"""
    raw = _rowValue(row, "metadata")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("归档行的 metadata 不是合法 JSON，按无 metadata 处理")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def resolveArchivedScope(row: sqlite3.Row) -> str:
    """解出归档行的作用域：列优先，缺失时回退解析 metadata（U1 甲案的配套）。

    两路都经 `memory_scope.scope_from_metadata`——作用域规则只此一份，
    不在这里重写"room: 前缀 / direct"的判定。
    """
    md = archivedMetadata(row)
    if "chat_scope" not in md:
        column = _rowValue(row, "chat_scope")
        if column:
            md["chat_scope"] = column
    if "session_id" not in md:
        session_id = _rowValue(row, "session_id")
        if session_id:
            md["session_id"] = session_id
    return scope_from_metadata(md)


def resolveArchivedCreatedAt(row: sqlite3.Row) -> datetime.datetime:
    """归档时刻：`created_at` 列优先，旧行（NULL）回退 `evicted_at`。

    缺了它，freshness 打分只能拿 `evicted_at` 顶替——那会让"归档时刻"与
    "驱逐时刻"混为一谈。
    """
    for key in ("created_at", "evicted_at"):
        value = _rowValue(row, key)
        if value:
            try:
                return datetime.datetime.fromisoformat(str(value))
            except ValueError:
                logger.warning("归档行的 %s 不是 ISO 时间，继续回退", key)
    return datetime.datetime.now()


def _rowValue(row, key: str) -> Any:
    """按列取值：sqlite3.Row / dict 通用；旧库缺该列时返回 None。"""
    try:
        keys = row.keys()
    except AttributeError:
        return None
    return row[key] if key in keys else None


def _mergeDuplicateContent(conn: sqlite3.Connection) -> int:
    """合并 `(user_id, agent_id, content_digest)` 内的历史重复行（保留最早一条）。

    唯一索引必须在合并之后建，否则旧库带重复行时迁移直接失败。被合并的
    FTS 影子行同批删掉（否则两表行数脱节）。
    """
    rows = conn.execute(
        "SELECT user_id, agent_id, content_digest, COUNT(*) AS c, MIN(id) AS keep_id"
        " FROM evicted_chunks WHERE content_digest IS NOT NULL"
        " GROUP BY user_id, agent_id, content_digest HAVING c > 1"
    ).fetchall()
    removed = 0
    for row in rows:
        victims = conn.execute(
            "SELECT id FROM evicted_chunks"
            " WHERE user_id = ? AND agent_id = ? AND content_digest = ? AND id != ?",
            (row["user_id"], row["agent_id"], row["content_digest"], row["keep_id"]),
        ).fetchall()
        for victim in victims:
            conn.execute("DELETE FROM evicted_chunks WHERE id = ?", (victim["id"],))
            conn.execute("DELETE FROM evicted_fts WHERE rowid = ?", (victim["id"],))
            removed += 1
    if removed:
        logger.info("归档库迁移：合并同内容重复行 %d 条（保留最早一条）", removed)
    return removed


def _backfillContentDigest(conn: sqlite3.Connection) -> int:
    """既有行按内容重算 `content_digest`（唯一索引的判据来源）。

    逐行 `executemany` 而非 50 万次单条 round-trip：大库上这是迁移耗时的主项
    （实测 5 万行 0.52 s → 0.13 s），且仍在同一个迁移事务内，不引入长事务之外的
    额外持锁窗口。
    """
    pending = conn.execute(
        "SELECT id, content FROM evicted_chunks WHERE content_digest IS NULL"
    ).fetchall()
    if pending:
        conn.executemany(
            "UPDATE evicted_chunks SET content_digest = ? WHERE id = ?",
            [(contentDigest(row["content"]), row["id"]) for row in pending],
        )
        logger.info("归档库迁移：回填 content_digest %d 行", len(pending))
    return len(pending)


def _migrateToV1(conn: sqlite3.Connection) -> None:
    """v1：基础结构 + 三列 + 回填 + 唯一/作用域索引（旧库就地升级）。

    用 `conn.execute` 而非 `executescript`：executescript 会先隐式提交当前事务，
    迁移的显式事务与回滚语义就没了（`db_migration` 的 callable 步骤依赖它）。
    """
    for statement in filter(None, (s.strip() for s in _SCHEMA.split(";"))):
        conn.execute(statement)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(evicted_chunks)")}
    for name in _V1_COLUMNS:
        if name not in columns:
            conn.execute("ALTER TABLE evicted_chunks ADD COLUMN %s TEXT" % name)
    _backfillContentDigest(conn)
    _mergeDuplicateContent(conn)
    conn.execute(_DIGEST_INDEX)
    conn.execute(_SCOPE_INDEX)


register_migration(1, _migrateToV1, domain=LEDGER_DOMAIN)


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
        # P1-1③ 增强②：实例级保留参数（gc_stale 语义化封装用）
        self.keep_count = keep_count
        self.keep_days = keep_days
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        """WAL + 版本化迁移：schema 变更只经 `context_ledger` 版本域承载。

        Raises:
            SchemaVersionError: 库版本高于代码已知版本（防降级，沿用 db_migration 防护）
        """
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            applyMigrations(conn, LEDGER_DOMAIN)
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
        chat_scope: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> None:
        """记录一次归档；content 同时写入 FTS 表。

        `chat_scope` / `created_at` 落独立列（U1/U3 定案），读侧另有对旧行的
        兜底（见 `resolveArchivedScope` / `resolveArchivedCreatedAt`）。未显式传入
        `chat_scope` 时按 metadata 经**同一份**作用域规则（`scope_from_metadata`）
        解出——不在这里重写第二份判定。

        同 `(user_id, agent_id, content_digest)` 重复归档按去重语义忽略
        （`ON CONFLICT ... DO NOTHING` 只吞这一条唯一约束，其余约束冲突照常上抛——
        不写成 `INSERT OR IGNORE`，那会把真正的写入错误一起吞掉）。
        """
        now = datetime.datetime.now().isoformat()
        scopeSource = dict(metadata or {})
        if session_id is not None:
            scopeSource["session_id"] = session_id
        scope = chat_scope or scope_from_metadata(scopeSource)
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO evicted_chunks"
                " (user_id, agent_id, session_id, turn_id, source, content, metadata,"
                "  evicted_at, content_digest, created_at, chat_scope)"
                " VALUES (:user_id, :agent_id, :session_id, :turn_id, :source, :content, :metadata,"
                "  :evicted_at, :content_digest, :created_at, :chat_scope)"
                " ON CONFLICT (user_id, agent_id, content_digest) DO NOTHING",
                {
                    "user_id": self.user_id,
                    "agent_id": self.agent_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "source": source,
                    "content": content,
                    "metadata": json.dumps(metadata, ensure_ascii=False, default=str) if metadata else None,
                    "evicted_at": now,
                    "content_digest": contentDigest(content),
                    "created_at": created_at or now,
                    "chat_scope": scope,
                },
            )
            if cur.rowcount == 0:
                conn.commit()
                return
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

    def gc_stale(self) -> int:
        """语义化 GC：按实例保留参数（keep_count/keep_days，默认 5000 条/30 天）。"""
        return self.gc(keep_count=self.keep_count, keep_days=self.keep_days)

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
