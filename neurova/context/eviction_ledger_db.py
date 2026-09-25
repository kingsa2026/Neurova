"""
驱逐台账持久化

SQLite WAL + FTS5：被驱逐/折叠的上下文 chunk 落库，重启后经 FTS 召回。
多用户分区：所有查询字面携带 user_id/agent_id 参数化条件——跨用户不可见
（非约定，是实现强制的；沿 _PersistDbStore 的隔离语义，但不做 SQL 字符串
拼接——所有隔离条件静态写死在每条查询里，天然通过参数化校验）。

设计：
- **一个常驻连接**（WAL + `synchronous=NORMAL` + `busy_timeout`）：写入口不再每次
  connect/close。改前每行一次 connect + commit + close，24 条一轮在 10 万行存量库上
  实测 214–318 ms/轮（规格 §2）；常驻连接 + 每轮一次事务为 0.78–0.91 ms/轮。
- **批量事务**：`beginBatch()` / `commitBatch()` 让一次归档调用内的全部条目共用
  一个事务，`commitBatch()` 返回前已提交（规格 D8 明确否掉异步/后台缓冲刷盘——
  那会把崩溃窗口内的内容连同"已归档"的承诺一起丢掉）。
- FTS5 独立表 + 手动双写（rowid 对齐内容表）；GC 时**分批**对齐清理
  （`delete-all` 对本表非法）
- 读侧预筛按**长度分流**：≥3 字符走 MATCH，<3 字符直接走 LIKE（trigram 索引不到
  短查询，强上 MATCH 是假阴性 = 漏召回；规格 §7 已知的坑第 1 条）
- **候选集有上限**（`CANDIDATE_LIMIT`）：MATCH 命中超限时降级为"最近 N 条候选 +
  候选内子串过滤"，不整库拉回内存（规格 U2 定案）
- LIKE 模式的 `%` `_` `\` 转义与 MATCH 短语规则**只此一份**（`core.sql_like`）：
  就地拼 `f"%{query}%"` 等于把用户输入当通配模式（实测 3 行全命中）
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
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.collaboration.memory_scope import scope_from_metadata
from neurova.core.db_migration import migrate as applyMigrations, register_migration
# 读侧查询判据按**模块属性**引用（而非 `from ... import`）：同源探针打事实源函数上，
# 若本模块把函数绑成模块级名字，复刻一份就地拼装就抓不到调用（008 的同源探针纪律）。
from neurova.core import sql_like

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

# D11：FTS 对齐走分批删除（5000/批）。整表 `NOT IN` 与分批量级相当（基线脚本 §7），
# 但分批不长时间持写锁。`delete-all` 对本表非法（普通 FTS5，实测 OperationalError）。
_FTS_ALIGN_BATCH = 5000

# D9 候选集上限（规格 U2 定案初值）：MATCH 命中超过它时降级为"最近 N 条候选 +
# 候选内子串过滤"。用于避免一次查询把整库拉回内存再逐条过滤。
CANDIDATE_LIMIT = 2000

# D12 v2：FTS 重建为 trigram 的回填批大小（规格实测值）。分批短事务——
# 一次性 `INSERT … SELECT` 会把并发写整段阻塞（基线脚本 §6 实测 0.84 s 全程持写锁）。
_FTS_REBUILD_BATCH = 5000

# v2 的影子表名与分词器（重建期用；切换完成后影子表被 RENAME 成正式表）
_FTS_SHADOW_TABLE = "evicted_fts_v2"
_FTS_TOKENIZE = "trigram"


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


def _rebuildFtsAsTrigram(conn: sqlite3.Connection) -> None:
    """v2：把 FTS 分词器从 `unicode61` 换成 `trigram`（中文可检索）。

    **只改 `tokenize` 参数不会改已有索引**，必须重建表。为什么影子表 + 分批：

    - `delete-all` 只对 contentless/external-content 表合法，本表是普通 FTS5，
      实测直接 `OperationalError`；
    - 一次性 `INSERT … SELECT` 回填是一条长事务，会把并发写整段阻塞
      （基线脚本 §6 实测 0.84 s 全程持写锁），与"零停机"判据 A7 冲突。

    顺序：建影子表 → **分批短事务**回填（每批独立提交）→ 最后一个事务里
    `DROP` 旧表 + `RENAME` 影子表。

    为什么整段写面走**独立连接**（`_sideConnection`）：

    1. `db_migration` 的 callable 步骤在迁移事务里，而 FTS 虚表的 `DROP`/`RENAME`
       无法在持事务的连接上执行（实测同连接内 `database is locked`）；
    2. 更关键的是**快照**：迁移连接的读快照看不到另一条连接的写入，若用它来读
       "影子表里还差哪些行"，循环永远取到同一批（实测：同批被重复插入 →
       `IntegrityError: constraint failed`）。故读取与写入必须在**同一条**连接上。

    迁移连接只负责最后推进 `user_version`（`db_migration` 的既有语义）。

    幂等/可重入：影子表 `IF NOT EXISTS` 建、回填按"影子表里还没有的行"取——
    中途失败留下的半成品影子表在重跑时被补齐，不会把行数算丢。
    """
    dbPath = _databasePath(conn)
    side = _openSideConnection(dbPath)
    try:
        side.execute("CREATE VIRTUAL TABLE IF NOT EXISTS %s USING fts5(content, tokenize='%s')"
                     % (_FTS_SHADOW_TABLE, _FTS_TOKENIZE))
        while True:
            side.execute("BEGIN IMMEDIATE")
            batch = side.execute(
                "SELECT id, content FROM evicted_chunks"
                " WHERE id NOT IN (SELECT rowid FROM %s) LIMIT ?" % _FTS_SHADOW_TABLE,
                (_FTS_REBUILD_BATCH,),
            ).fetchall()
            if not batch:
                side.execute("COMMIT")
                break
            side.executemany(
                "INSERT INTO %s(rowid, content) VALUES (?, ?)" % _FTS_SHADOW_TABLE,
                [(row["id"], row["content"]) for row in batch],
            )
            side.execute("COMMIT")
        # 切换窗口：**在同一个写事务里**补齐尾批 + DROP + RENAME。
        # 尾批不能留在上一次循环的读之后——那段时间里并发写可能已插入了新行，
        # 而它们的内容行在、索引行不在（实测迁移后两表差 1 行）。
        # 放进同一个 BEGIN IMMEDIATE 里，切换窗口内没有第三方写入的插缝。
        side.execute("BEGIN IMMEDIATE")
        side.execute(
            "INSERT INTO %s(rowid, content)"
            " SELECT id, content FROM evicted_chunks"
            " WHERE id NOT IN (SELECT rowid FROM %s)" % (_FTS_SHADOW_TABLE, _FTS_SHADOW_TABLE)
        )
        side.execute("DROP TABLE IF EXISTS evicted_fts")
        side.execute("ALTER TABLE %s RENAME TO evicted_fts" % _FTS_SHADOW_TABLE)
        side.execute("COMMIT")
    except Exception:
        try:
            side.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        side.close()


def _databasePath(conn: sqlite3.Connection) -> str:
    """取连接的实际库路径（`db_migration` 的步骤只拿到连接）。

    不用 `sqlite_master` 查询判存在性：那会在迁移事务里取读锁，与同库的 DDL 写锁
    冲突（实测 `database is locked`）。`PRAGMA database_list` 不取锁。
    """
    row = conn.execute("PRAGMA database_list").fetchone()
    path = row[2] if row else ""
    if not path:
        raise sqlite3.OperationalError("台账库是内存库/匿名库，无法做影子表迁移")
    return path


def _openSideConnection(dbPath: str) -> sqlite3.Connection:
    """重建用的独立连接：短事务（每批 `BEGIN IMMEDIATE` + `COMMIT`）。

    `BEGIN IMMEDIATE` 显式取写锁：默认 deferred 事务在"先读后写"升级锁时会撞上
    别的写者并直接失败（实测 `database is locked`）。短事务窗口让并发写在批次之间
    插得进来——这是 A7「迁移窗口内并发写不停」的落地形态。
    """
    side = sqlite3.connect(dbPath, timeout=30, isolation_level=None)
    side.row_factory = sqlite3.Row
    side.execute("PRAGMA busy_timeout=10000")
    return side


register_migration(1, _migrateToV1, domain=LEDGER_DOMAIN)
register_migration(2, _rebuildFtsAsTrigram, domain=LEDGER_DOMAIN)


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
        # B4/003：一个常驻连接 + 一把锁（批量写与并发读共用，句柄不随每次写重建）
        self._lock = threading.RLock()
        self._batchDepth = 0
        self._batchError: Optional[BaseException] = None
        self._inTransaction = False
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._openConnection()
        try:
            self._init_schema()
        except Exception:
            self.close()
            raise

    def _openConnection(self) -> sqlite3.Connection:
        """常驻连接：WAL + `synchronous=NORMAL` + `busy_timeout`，事务显式管理。

        `isolation_level=None` 关掉 sqlite3 的隐式 BEGIN：事务边界由
        `beginBatch`/`commitBatch` 与单条 `record` 显式决定，不再受"隐式 BEGIN
        与显式 BEGIN 打架"影响。
        """
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _requireConn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise sqlite3.ProgrammingError("台账连接已关闭（close() 后不可再写读）")
        return self._conn

    def close(self) -> None:
        """释放常驻连接（幂等）；未结束的批量事务在此回滚，不留半提交状态。"""
        with self._lock:
            if self._conn is None:
                return
            if self._inTransaction:
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    logger.warning("台账关闭时回滚未结束事务失败", exc_info=True)
            self._conn.close()
            self._conn = None
            self._inTransaction = False
            self._batchDepth = 0
            self._batchError = None

    def _init_schema(self) -> None:
        """WAL + 版本化迁移：schema 变更只经 `context_ledger` 版本域承载。

        Raises:
            SchemaVersionError: 库版本高于代码已知版本（防降级，沿用 db_migration 防护）
        """
        with self._lock:
            applyMigrations(self._requireConn(), LEDGER_DOMAIN)

    def beginBatch(self) -> None:
        """开启批量事务（可嵌套：只有最外层真正开/提交事务）。"""
        with self._lock:
            if self._batchError is not None:
                error, self._batchError = self._batchError, None
                raise error
            if self._batchDepth == 0:
                self._requireConn().execute("BEGIN")
                self._inTransaction = True
            self._batchDepth += 1

    def commitBatch(self) -> None:
        """提交批量事务。批内任一条写失败 → 不提交并上抛该失败（整批回滚）。"""
        with self._lock:
            if self._batchDepth == 0:
                return
            self._batchDepth -= 1
            if self._batchDepth > 0:
                return
            error, self._batchError = self._batchError, None
            if error is not None:
                self.rollbackBatch()
                raise error
            if self._inTransaction:
                self._requireConn().execute("COMMIT")
                self._inTransaction = False

    def rollbackBatch(self) -> None:
        """放弃批量事务（不抛）：调用方在批内失败时用它收口，避免留下半提交状态。"""
        with self._lock:
            if self._inTransaction:
                try:
                    self._requireConn().execute("ROLLBACK")
                except sqlite3.Error:
                    logger.warning("台账批量回滚失败", exc_info=True)
                self._inTransaction = False
            self._batchDepth = 0
            self._batchError = None

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
    ) -> bool:
        """记录一次归档；content 同时写入 FTS 表。

        Returns:
            本行是否真的落库（同内容去重命中时返回 False）——调用方据此维护库内
            条数读数，不靠"自己数调用次数"糊一份可能与库不符的账。

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
        with self._lock:
            conn = self._requireConn()
            if self._inTransaction:
                # 批量内：不提交，失败时把原因记在批次上——由 commitBatch 统一上抛
                # 并整批回滚（一次归档调用 = 一个事务，规格 D8）。
                try:
                    return self._insert(conn, content=content, turn_id=turn_id,
                                        session_id=session_id, source=source, metadata=metadata,
                                        evicted_at=now, scope=scope, created_at=created_at or now)
                except Exception as exc:
                    if self._batchError is None:
                        self._batchError = exc
                    raise
            conn.execute("BEGIN")
            try:
                inserted = self._insert(conn, content=content, turn_id=turn_id,
                                        session_id=session_id, source=source, metadata=metadata,
                                        evicted_at=now, scope=scope, created_at=created_at or now)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            return inserted

    def _insert(self, conn, *, content, turn_id, session_id, source, metadata,
                evicted_at, scope, created_at) -> bool:
        """单条落库（内容表 + FTS 影子表）；事务边界由调用方决定。"""
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
                "evicted_at": evicted_at,
                "content_digest": contentDigest(content),
                "created_at": created_at,
                "chat_scope": scope,
            },
        )
        if cur.rowcount == 0:
            return False
        conn.execute(
            "INSERT INTO evicted_fts(rowid, content) VALUES (:rowid, :content)",
            {"rowid": cur.lastrowid, "content": content},
        )
        return True

    def recentRows(self, limit: int) -> List[sqlite3.Row]:
        """按 `id DESC` 取最近 N 行（热集回载的唯一读入口，顺序稳定）。

        常驻集是视图层唯一来源（规格 §4 非目标：`draw` 不查 DB），本方法只服务
        调用方**显式**发起的回载（规格 D10）。
        """
        with self._lock:
            return self._requireConn().execute(
                "SELECT * FROM evicted_chunks"
                " WHERE user_id = :user_id AND agent_id = :agent_id"
                " ORDER BY id DESC LIMIT :limit",
                {"user_id": self.user_id, "agent_id": self.agent_id, "limit": int(limit)},
            ).fetchall()

    def rowsBySource(self, source: str, limit: int = CANDIDATE_LIMIT) -> List[sqlite3.Row]:
        """按来源域取行（T-11b 层索引的持久读面）。

        层索引（SUMMARY 节点）必须跨重启可读回：`covers` 只留在进程内折叠缓存里
        等于把"轨迹可寻址"建在一次重启就消失的事实上。本条与其它读路径同纪律：
        隔离条件静态写死在 SQL 里（user_id / agent_id），上限沿用 `CANDIDATE_LIMIT`
        （不另写一个数——两处上限各写一份必然漂移）。
        """
        with self._lock:
            return self._requireConn().execute(
                "SELECT *, id AS _row FROM evicted_chunks"
                " WHERE user_id = :user_id AND agent_id = :agent_id AND source = :source"
                " ORDER BY id DESC LIMIT :limit",
                {
                    "user_id": self.user_id,
                    "agent_id": self.agent_id,
                    "source": source,
                    "limit": int(limit),
                },
            ).fetchall()

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
        with self._lock:
            return self._search(query=query, session_id=session_id, limit=limit)

    def _search(
        self,
        query: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """召回主体（调用方须持 `_lock`：常驻连接不可并发使用）。

        查询侧判据（长度分流 / 转义 / 候选集上限）只经 `core.sql_like` 与本模块
        常量，不在此就地拼装第二份——转义规则改一处漏一处等于没改。
        """
        conn = self._requireConn()
        filters = {"user_id": self.user_id, "agent_id": self.agent_id}
        session_filter = " AND (:session_id IS NULL OR session_id = :session_id)"
        if not (query or "").strip():
            return conn.execute(
                "SELECT *, id AS _row FROM evicted_chunks"
                " WHERE user_id = :user_id AND agent_id = :agent_id"
                + session_filter
                + " ORDER BY id DESC LIMIT :limit",
                {**filters, "session_id": session_id, "limit": limit},
            ).fetchall()

        hits: List = []
        if sql_like.shouldMatch(query):
            hits = self._matchCandidates(conn, query, session_id, limit)
        if not hits:
            hits = self._likeCandidates(conn, query, session_id, limit)
        return hits

    def _matchCandidates(self, conn, query: str, session_id: Optional[str], limit: int) -> List:
        """MATCH 预筛：候选集**先按上限截断**，再在候选内取内容行。

        两个返回面合起来才是"候选集超上限时不得整库拉回"的可证伪形态：

        - 候选行数达到 `CANDIDATE_LIMIT` 时，说明命中超过上限 → 改为按 `id DESC`
          取最近 `CANDIDATE_LIMIT` 条，并在**候选内**做子串过滤（降级分支）；
        - 候选行数不足上限时，说明命中全在候选里 → 直取这些行（命中语义对齐 LIKE 真值）。

        不做单次 `JOIN` + `LIMIT`：SQLite 对 FTS 虚表的 `ORDER BY e.id DESC` 会退化成
        "扫全表匹配项再排序"（实测 5 万行库上零命中查询 336 ms vs 候选集查询 0.01 ms）。
        """
        try:
            candidates = conn.execute(
                "SELECT rowid FROM evicted_fts WHERE evicted_fts MATCH :fts_query"
                " ORDER BY rowid DESC LIMIT :cap",
                {"fts_query": sql_like.matchQuery(query), "cap": CANDIDATE_LIMIT + 1},
            ).fetchall()
        except sqlite3.OperationalError:
            logger.info("FTS MATCH 失败，降级 LIKE 子串匹配（query=%r）", query)
            return []
        if not candidates:
            return []
        if len(candidates) > CANDIDATE_LIMIT:
            return self._recentCandidates(conn, query, session_id, limit)
        return self._rowsByIds(conn, [row["rowid"] for row in candidates], session_id, limit)

    def _rowsByIds(self, conn, ids: List[int], session_id: Optional[str], limit: int) -> List:
        """按 id 集合取内容行（顺序按 `id DESC`，与既有召回序一致）。"""
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        return conn.execute(
            "SELECT *, id AS _row FROM evicted_chunks"
            " WHERE user_id = ? AND agent_id = ?"
            " AND id IN (" + placeholders + ")"
            " AND (? IS NULL OR session_id = ?)"
            " ORDER BY id DESC LIMIT ?",
            (self.user_id, self.agent_id, *ids, session_id, session_id, limit),
        ).fetchall()

    def _recentCandidates(self, conn, query: str, session_id: Optional[str], limit: int) -> List:
        """降级分支：按 `id DESC` 取最近 `CANDIDATE_LIMIT` 条，在候选内做子串过滤。

        用于"MATCH 命中超上限"的情形——不整库拉回，也不把命中整个丢掉。
        """
        recent = conn.execute(
            "SELECT *, id AS _row FROM evicted_chunks"
            " WHERE user_id = :user_id AND agent_id = :agent_id"
            " AND (:session_id IS NULL OR session_id = :session_id)"
            " ORDER BY id DESC LIMIT :cap",
            {"user_id": self.user_id, "agent_id": self.agent_id,
             "session_id": session_id, "cap": CANDIDATE_LIMIT},
        ).fetchall()
        needle = query.lower()
        return [row for row in recent if needle in row["content"].lower()][:limit]

    def _likeCandidates(self, conn, query: str, session_id: Optional[str], limit: int) -> List:
        """LIKE 子串分支（长度 <3 或 MATCH 空结果/语法错误时的兜底）。

        `%` `_` `\` 的转义只经 `core.sql_like.likePattern`——就地拼
        `f"%{query}%"` 等于把用户输入当通配模式（实测库内 3 行时 `%` 命中 3 行）。
        """
        return conn.execute(
            "SELECT *, id AS _row FROM evicted_chunks"
            " WHERE user_id = ? AND agent_id = ?"
            " AND " + sql_like.likePredicate("content") +
            " AND (? IS NULL OR session_id = ?)"
            " ORDER BY id DESC LIMIT ?",
            (self.user_id, self.agent_id, sql_like.likePattern(query), session_id, session_id, limit),
        ).fetchall()

    def count(self) -> int:
        with self._lock:
            return self._count()

    def _count(self) -> int:
        row = self._requireConn().execute(
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
        with self._lock:
            conn = self._requireConn()
            conn.execute("BEGIN")
            try:
                removed = self._purge(conn, keep_count=keep_count, keep_days=keep_days)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return removed

    def _purge(
        self, conn: sqlite3.Connection, *, keep_count: Optional[int], keep_days: Optional[int]
    ) -> int:
        """执行保留策略清理（调用方须已开启事务）。"""
        removed = 0
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

        self._alignFts(conn)
        return removed

    @staticmethod
    def _alignFts(conn: sqlite3.Connection) -> int:
        """把 FTS 影子行对齐到内容表（分批删除，短事务窗口）。

        FTS5 不随内容表删除而收缩（实测：删 2 万内容行后 FTS 仍 5 万行），
        不对齐就是两表脱节。分批而非整表 `NOT IN`：量级相当但不长时间持写锁。
        """
        removed = 0
        while True:
            cur = conn.execute(
                "DELETE FROM evicted_fts WHERE rowid IN ("
                "  SELECT rowid FROM evicted_fts"
                "  WHERE rowid NOT IN (SELECT id FROM evicted_chunks)"
                "  LIMIT :batch"
                ")",
                {"batch": _FTS_ALIGN_BATCH},
            )
            if not cur.rowcount:
                break
            removed += cur.rowcount
        return removed
