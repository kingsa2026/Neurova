"""SQLite FTS5 持久倒排索引（无新增第三方依赖）。

doc 粒度 = 知识条目（与 BM25/FTS 辅助路同粒度）；中文先走仓库现有 tokenize
（jieba 可选、缺席 n-gram）再写入 FTS，查询侧同样预分词，避免依赖 FTS5 对中文
分词的未验证假设。可见性、agent、category、tags、source、时间与生命周期过滤
都在 SQL 里完成；FTS 命中仍要经调用方可见集回映。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from neurova.core.logger import get_logger
from neurova.knowledge.lifecycle import isRetrievable
from neurova.knowledge.search import tokenize
from neurova.knowledge.splitter import build_index_content

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_fts_docs (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL UNIQUE,
    knowledge_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'private',
    owner_user_id TEXT NOT NULL DEFAULT '',
    tenant_id TEXT NOT NULL DEFAULT 'default',
    shared_with_json TEXT NOT NULL DEFAULT '[]',
    category TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL DEFAULT 0,
    lifecycle_status TEXT NOT NULL DEFAULT 'active',
    valid_until TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(content);
"""


def _nowIso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _tokens(text: str) -> str:
    return " ".join(tokenize(text or ""))


class KnowledgeFtsIndex:
    def __init__(self, db_path: str) -> None:
        self._path = str(db_path)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)
            # 旧库补列：executescript 的 CREATE IF NOT EXISTS 不会给已存在的表加列
            columns = {
                row[1]
                for row in self._conn.execute("PRAGMA table_info(knowledge_fts_docs)").fetchall()
            }
            if "tenant_id" not in columns:
                self._conn.execute(
                    "ALTER TABLE knowledge_fts_docs ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
                )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    #: 索引行里「随条目走」的列——**这张清单是唯一事实源**：写库的参数、写库的列名、
    #: 行指纹三处都从它取。旧版把指纹写成手抄的 5 个字段，而 `source` 会由治理层在
    #: **不动 `updated_at`** 的前提下改写（`repository._syncEntryGovernance` ←
    #: `entry_ledger._mediumOf` 取最近断言的 medium_ref），于是 docs.source 变脏，
    #: `search(source=...)` 按脏列过滤就查不到本该命中的条目。
    _ROW_VALUE_KEYS = (
        "knowledge_id", "agent_id", "visibility", "owner_user_id", "tenant_id",
        "shared_with_json", "category", "tags_json", "source", "updated_at",
        "lifecycle_status", "valid_until",
    )

    @classmethod
    def _rowValues(cls, agentId: str, item: Dict[str, Any]) -> tuple:
        """按 `_ROW_VALUE_KEYS` 的顺序取这一行的值。"""
        return (
            str(item.get("knowledge_id") or ""),
            str(agentId),
            str(item.get("visibility") or "private"),
            str(item.get("owner_user_id") or ""),
            str(item.get("tenant_id") or "default"),
            json.dumps(item.get("shared_with") or [], ensure_ascii=False),
            str(item.get("category") or ""),
            json.dumps(item.get("tags") or [], ensure_ascii=False),
            str(item.get("source") or ""),
            float(item.get("updated_at") or 0),
            str(item.get("lifecycle_status") or "active"),
            str(item.get("valid_until") or ""),
        )

    @classmethod
    def _fingerprint(cls, agentId: str, item: Dict[str, Any], tokens: str) -> str:
        """行指纹＝那一整列值＋实际入库文本 的哈希。

        入库文本也在内：`title` 与 `content` 都不落在 docs 列上，只进倒排表，
        旧指纹用 `len(content)` 量它——同长度改正文、只改标题，都是「索引看得见、
        指纹看不见」。
        """
        payload = repr(cls._rowValues(agentId, item)) + "\n" + tokens
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def _deleteDoc(self, docId: str) -> None:
        row = self._conn.execute(
            "SELECT rowid FROM knowledge_fts_docs WHERE doc_id = ?", (docId,)
        ).fetchone()
        if row is None:
            return
        self._conn.execute("DELETE FROM knowledge_fts WHERE rowid = ?", (row["rowid"],))
        self._conn.execute("DELETE FROM knowledge_fts_docs WHERE doc_id = ?", (docId,))

    def _upsertDoc(self, agentId: str, item: Dict[str, Any]) -> bool:
        kid = str(item.get("knowledge_id") or "")
        if not kid or not isRetrievable(item):
            self._deleteDoc(kid)
            return False
        values = self._rowValues(agentId, item)
        tokens = _tokens(build_index_content(
            str(item.get("title") or ""), str(item.get("content") or "")
        ))
        fingerprint = self._fingerprint(agentId, item, tokens)
        row = self._conn.execute(
            "SELECT rowid, fingerprint FROM knowledge_fts_docs WHERE doc_id = ?", (kid,)
        ).fetchone()
        if row is not None and row["fingerprint"] == fingerprint:
            return False
        # 列名与占位符由 `_ROW_VALUE_KEYS` 现场生成：再手抄一份就是第二张字段表
        if row is not None:
            rowid = int(row["rowid"])
            self._conn.execute("DELETE FROM knowledge_fts WHERE rowid = ?", (rowid,))
            assignments = ", ".join("%s=?" % col for col in self._ROW_VALUE_KEYS)
            self._conn.execute(
                "UPDATE knowledge_fts_docs SET %s, fingerprint=? WHERE rowid=?" % assignments,
                values + (fingerprint, rowid),
            )
        else:
            columns = ", ".join(self._ROW_VALUE_KEYS)
            marks = ", ".join(["?"] * (len(self._ROW_VALUE_KEYS) + 2))
            cur = self._conn.execute(
                "INSERT INTO knowledge_fts_docs (doc_id, %s, fingerprint) VALUES (%s)"
                % (columns, marks),
                (kid,) + values + (fingerprint,),
            )
            rowid = int(cur.lastrowid)
        self._conn.execute(
            "INSERT INTO knowledge_fts (rowid, content) VALUES (?,?)", (rowid, tokens)
        )
        return True

    def reconcile(self, itemsByAgent: Dict[str, List[Dict[str, Any]]]) -> Dict[str, int]:
        """把索引对齐到当前条目集合；只重算指纹变化的条目。"""
        desired: Dict[str, Dict[str, Any]] = {}
        for agentId, items in (itemsByAgent or {}).items():
            for item in items:
                kid = str(item.get("knowledge_id") or "")
                if kid:
                    desired[kid] = (agentId, item)
        with self._lock, self._conn:
            existing = {r["doc_id"] for r in self._conn.execute(
                "SELECT doc_id FROM knowledge_fts_docs"
            ).fetchall()}
            changed = 0
            for kid, (agentId, item) in desired.items():
                if self._upsertDoc(agentId, item):
                    changed += 1
            removed = 0
            for kid in existing - set(desired):
                self._deleteDoc(kid)
                removed += 1
        return {"indexed": len(desired), "changed": changed, "removed": removed}

    def deleteEntry(self, knowledgeId: str) -> None:
        with self._lock, self._conn:
            self._deleteDoc(str(knowledgeId))

    def search(
        self,
        query: str,
        user: Optional[Dict[str, Any]] = None,
        *,
        scope: str = "all",
        agent_id: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
        source: Optional[str] = None,
        updated_after: Optional[float] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        terms = [t.replace('"', '""') for t in tokenize(query or "") if t]
        if not terms:
            return []
        match = " OR ".join('"%s"' % term for term in terms)
        clauses = [
            "knowledge_fts MATCH ?",
            "d.lifecycle_status = 'active'",
            "(d.valid_until = '' OR d.valid_until > ?)",
        ]
        params: List[Any] = [match, _nowIso()]
        user = user or {}
        uid = str(user.get("user_id") or "")
        tenant = str(user.get("tenant_id") or "default")
        clauses.append("d.tenant_id = ?")
        params.append(tenant)
        admin = str(user.get("role") or "") == "admin"
        if not admin:
            if scope == "public":
                clauses.append("d.visibility = 'public'")
            elif scope == "private":
                clauses.append("d.visibility = 'private' AND d.owner_user_id = ?")
                params.append(uid)
            elif scope == "shared":
                clauses.append(
                    "d.visibility = 'private' AND EXISTS"
                    " (SELECT 1 FROM json_each(d.shared_with_json) WHERE value = ?)"
                )
                params.append(uid)
            else:
                clauses.append(
                    "(d.visibility = 'public' OR (d.visibility = 'private'"
                    " AND (d.owner_user_id = ? OR EXISTS"
                    " (SELECT 1 FROM json_each(d.shared_with_json) WHERE value = ?))))"
                )
                params.extend([uid, uid])
        if agent_id:
            clauses.append("d.agent_id = ?")
            params.append(str(agent_id))
        if category:
            clauses.append("d.category = ?")
            params.append(str(category))
        if source:
            clauses.append("d.source = ?")
            params.append(str(source))
        if updated_after is not None:
            clauses.append("d.updated_at >= ?")
            params.append(float(updated_after))
        for tag in tags or []:
            clauses.append(
                "EXISTS (SELECT 1 FROM json_each(d.tags_json) WHERE value = ?)"
            )
            params.append(str(tag))
        sql = (
            "SELECT d.knowledge_id AS id, d.knowledge_id AS knowledge_id,"
            " -bm25(knowledge_fts) AS score"
            " FROM knowledge_fts JOIN knowledge_fts_docs d ON d.rowid = knowledge_fts.rowid"
            " WHERE " + " AND ".join(clauses)
            + " ORDER BY bm25(knowledge_fts) LIMIT ?"
        )
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def health(self) -> Dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS docs,"
                " SUM(CASE WHEN lifecycle_status = 'active' THEN 1 ELSE 0 END) AS active"
                " FROM knowledge_fts_docs"
            ).fetchone()
        return {"docs": int(row["docs"] or 0), "active": int(row["active"] or 0)}
