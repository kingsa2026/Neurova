"""叙述层入库（工单 019a）：条目文档存进底座库，`_items` 形状与 id 原值保持。

分工：叙述层是**文档**不是关系——按可见性/归属需要被查询的字段成列，正文与分块作为
整体载荷存取。关系的权威在 `knowledge_facts`，这里不重复建一套；分块也不立表，
它随条目整篇读写，拆表只会造出第二个权威。

分片索引不复刻：`_rebuild_indexes` 与 `_item_index_docs` 只读 `self._items`，
是它的纯函数。所以本模块的硬要求只有一条——load 出来的结构与 JSON 时代逐字段相同。

连接策略：每次操作开一条短连接，不长期持有。仓库实例满天飞且测试跑在 tmp_path 上，
句子攥在手里会让 Windows 清不掉临时目录。

墓碑（019b-2c）与条目同进同出：它记的是"这条知识被谁在什么时候收回了"，本来就是治理层的事。
形状纪律一致——`self._tombstones` 的 dict 一字不改，换的只有 `_load` / `_save_tombstones` 两个边界。
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


NARRATIVE_DOMAIN = "knowledge_foundation"
FOUNDATION_DB_NAME = "knowledge_facts.db"

_SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS knowledge_narratives (
    knowledge_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'private',
    shared_with_json TEXT NOT NULL DEFAULT '[]',
    category TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_narrative_agent ON knowledge_narratives(agent_id, knowledge_id);
CREATE INDEX IF NOT EXISTS idx_narrative_owner ON knowledge_narratives(owner_user_id, visibility);
"""

# 一次性搬家的归档后缀：搬完的 JSON 留在原地但不复权，
# 否则"删空后重启"会拿快照把已删条目（或删除史）复活。
# 前缀挂在**原文件名之后**，条目与墓碑各自留名，否则两份归档互相顶替、事后认不出谁是谁。
ARCHIVE_PREFIX = ".pre-narrative-store-"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class NarrativeStore:
    """`KnowledgeRepository._items` 的 SQLite 网关（同形状、同 id、无状态）。"""

    def __init__(self, db_path: str) -> None:
        if not db_path:
            raise ValueError("NarrativeStore 需显式传入 db_path，不给默认值")
        self._db_path = db_path

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            from .foundation_schema import applyTo  # 惰性：链的单主注册处依赖本模块

            applyTo(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── 读 ────────────────────────────────────────────────────

    def tombstoneCount(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM knowledge_tombstones").fetchone()[0])

    def loadTombstones(self) -> Dict[str, Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT knowledge_id, payload_json FROM knowledge_tombstones ORDER BY rowid"
            ).fetchall()
        return {str(r["knowledge_id"]): json.loads(r["payload_json"]) for r in rows}

    def replaceAllTombstones(self, tombstones: Dict[str, Dict[str, Any]]) -> int:
        stamp = _now()
        with self._conn() as conn:
            conn.execute("DELETE FROM knowledge_tombstones")
            for knowledgeId, rec in tombstones.items():
                conn.execute(
                    "INSERT INTO knowledge_tombstones (knowledge_id, agent_id, deleted_at,"
                    " deleted_by, superseded_by, payload_json, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (str(knowledgeId), str(rec.get("agent_id", "") or ""),
                     float(rec.get("deleted_at", 0) or 0), str(rec.get("deleted_by", "") or ""),
                     rec.get("superseded_by"),
                     json.dumps(rec, ensure_ascii=False, sort_keys=True), stamp),
                )
        return len(tombstones)

    def importTombstonesFromJson(self, jsonPath: str) -> Dict[str, Any]:
        path = Path(jsonPath)
        if not path.exists():
            return {"imported": 0, "skipped_existing": 0}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("墓碑账本顶层必须是 {knowledge_id: 记录}，收到 %r" % type(raw).__name__)
        stamp = _now()
        imported = 0
        with self._conn() as conn:
            for knowledgeId, rec in raw.items():
                if not isinstance(rec, dict):
                    raise ValueError("墓碑记录形状不对: %r" % knowledgeId)
                cur = conn.execute(
                    "INSERT OR IGNORE INTO knowledge_tombstones (knowledge_id, agent_id,"
                    " deleted_at, deleted_by, superseded_by, payload_json, updated_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (str(knowledgeId), str(rec.get("agent_id", "") or ""),
                     float(rec.get("deleted_at", 0) or 0), str(rec.get("deleted_by", "") or ""),
                     rec.get("superseded_by"),
                     json.dumps(rec, ensure_ascii=False, sort_keys=True), stamp),
                )
                imported += 1 if cur.rowcount else 0
        return {"imported": imported,
                "skipped_existing": len(raw) - imported, "rows_in_store": self.tombstoneCount()}

    def archiveSidecar(self, jsonPath: str) -> Optional[str]:
        """搬完让旁账文件退出读路径；留档可回退，与条目搬家同一纪律。"""
        return self.archiveImportedJson(jsonPath)

    def loadAll(self) -> Dict[str, List[Dict[str, Any]]]:
        """按 agent_id 分组回 `self._items` 形状；成序按写入序（rowid），与 JSON 时代一致。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT agent_id, payload_json FROM knowledge_narratives ORDER BY rowid"
            ).fetchall()
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row["agent_id"]), []).append(
                json.loads(row["payload_json"]))
        return grouped

    def count(self) -> int:
        with self._conn() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM knowledge_narratives").fetchone()[0])

    # ── 写 ────────────────────────────────────────────────────

    def replaceAll(self, itemsByAgent: Dict[str, List[Dict[str, Any]]]) -> int:
        """全量替换。叙述层整体即 `_items` 的投影，不做逐行 diff——
        分块等子结构会被整篇改写，逐行 diff 反而会漏字段。

        失败必须抛出而不是记一条日志：吞掉写失败会让内存与库永久分叉，
        而下一次成功写入会把分叉期间的编辑抹平。
        """
        rows = _projectRows(itemsByAgent)
        stamp = _now()
        with self._conn() as conn:
            conn.execute("DELETE FROM knowledge_narratives")
            conn.executemany(
                "INSERT INTO knowledge_narratives (knowledge_id, agent_id, owner_user_id,"
                " visibility, shared_with_json, category, title, payload_json, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                [r + (stamp,) for r in rows],
            )
        return len(rows)

    def importFromJson(self, jsonPath: str) -> Dict[str, Any]:
        """一次性搬 JSON，id 原值保留；已有行一律不覆盖，所以重跑不会回滚已发生的编辑。"""
        path = Path(jsonPath)
        if not path.exists():
            return {"imported": 0, "skipped_existing": 0, "rows_in_store": self.count()}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(
                "knowledge.json 顶层必须是 {agent_id: [条目]}，收到 %r" % type(raw).__name__)
        try:
            rows = _projectRows(raw)
        except ValueError as e:
            raise ValueError("搬 %s 失败：%s" % (path, e)) from e
        if not rows:
            return {"imported": 0, "skipped_existing": 0, "rows_in_store": self.count()}
        stamp = _now()
        imported = 0
        with self._conn() as conn:
            for row in rows:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO knowledge_narratives (knowledge_id, agent_id,"
                    " owner_user_id, visibility, shared_with_json, category, title,"
                    " payload_json, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    row + (stamp,),
                )
                imported += 1 if cur.rowcount else 0
        return {
            "imported": imported,
            "skipped_existing": len(rows) - imported,
            "rows_in_store": self.count(),
        }

    def archiveImportedJson(self, jsonPath: str) -> Optional[str]:
        """搬完让旧文件退出读路径（复权留档，可回退）。"""
        path = Path(jsonPath)
        if not path.exists():
            return None
        archived = path.with_name(path.name + ARCHIVE_PREFIX + _now().replace(":", "").replace(".", ""))
        path.rename(archived)
        return str(archived)

    @staticmethod
    def findArchivedJson(storageDir: str) -> List[str]:
        return sorted(str(p) for p in Path(storageDir).glob("*" + ARCHIVE_PREFIX + "*"))


def _projectRows(itemsByAgent: Dict[str, List[Dict[str, Any]]]) -> List[tuple]:
    """条目 → 行元组；缺 knowledge_id 直接拒绝——全量替换下它会静默删行。"""
    rows: List[tuple] = []
    for agentId, items in itemsByAgent.items():
        for item in items:
            knowledgeId = str(item.get("knowledge_id", "") or "")
            if not knowledgeId:
                raise ValueError(
                    "agent=%r 分组下有条目缺 knowledge_id（title=%r），拒绝写库："
                    "全量替换会把这一行静默丢掉。先补上 id 再写。" % (agentId, item.get("title"))
                )
            rows.append((
                knowledgeId,
                str(agentId),
                str(item.get("owner_user_id", "") or ""),
                str(item.get("visibility", "private") or "private"),
                json.dumps(item.get("shared_with") or [], ensure_ascii=False),
                str(item.get("category", "") or ""),
                str(item.get("title", "") or ""),
                json.dumps(item, ensure_ascii=False, sort_keys=True),
            ))
    return rows


# ── 墓碑（工单 019b-2c）───────────────────────────────────────
# 整份条目快照随墓碑留存：restore 要把条目原样放回去，只存 id 就回不了。
_SCHEMA_V6 = """
CREATE TABLE IF NOT EXISTS knowledge_tombstones (
    knowledge_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL DEFAULT '',
    deleted_at REAL NOT NULL DEFAULT 0,
    deleted_by TEXT NOT NULL DEFAULT '',
    superseded_by TEXT,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tombstone_agent ON knowledge_tombstones(agent_id, knowledge_id);
"""
