"""SQLite FTS5 持久倒排索引（无新增第三方依赖）。

doc 粒度 = 知识条目（与 BM25/FTS 辅助路同粒度）；中文先走仓库现有 tokenize
（jieba 可选、缺席 n-gram）再写入 FTS，查询侧同样预分词，避免依赖 FTS5 对中文
分词的未验证假设。可见性、agent、category、tags、source、时间与生命周期过滤
都在 SQL 里完成；FTS 命中仍要经调用方可见集回映。
"""
from __future__ import annotations

import datetime
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

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _fingerprint(item: Dict[str, Any]) -> str:
        return "%s:%d:%s:%s" % (
            item.get("updated_at", 0),
            len(str(item.get("content") or "")),
            item.get("lifecycle_status", "active"),
            item.get("valid_until") or "",
        )

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
        fingerprint = self._fingerprint(item)
        row = self._conn.execute(
            "SELECT rowid, fingerprint FROM knowledge_fts_docs WHERE doc_id = ?", (kid,)
        ).fetchone()
        if row is not None and row["fingerprint"] == fingerprint:
            return False
        visibility = str(item.get("visibility") or "private")
        shared = json.dumps(item.get("shared_with") or [], ensure_ascii=False)
        tags = json.dumps(item.get("tags") or [], ensure_ascii=False)
        tokens = _tokens(build_index_content(
            str(item.get("title") or ""), str(item.get("content") or "")
        ))
        if row is not None:
            rowid = int(row["rowid"])
            self._conn.execute("DELETE FROM knowledge_fts WHERE rowid = ?", (rowid,))
            self._conn.execute(
                "UPDATE knowledge_fts_docs SET knowledge_id=?, agent_id=?, visibility=?,"
                " owner_user_id=?, shared_with_json=?, category=?, tags_json=?, source=?,"
                " updated_at=?, lifecycle_status=?, valid_until=?, fingerprint=? WHERE rowid=?",
                (kid, str(agentId), visibility, str(item.get("owner_user_id") or ""), shared,
                 str(item.get("category") or ""), tags, str(item.get("source") or ""),
                 float(item.get("updated_at") or 0), str(item.get("lifecycle_status") or "active"),
                 str(item.get("valid_until") or ""), fingerprint, rowid),
            )
        else:
            cur = self._conn.execute(
                "INSERT INTO knowledge_fts_docs (doc_id, knowledge_id, agent_id, visibility,"
                " owner_user_id, shared_with_json, category, tags_json, source, updated_at,"
                " lifecycle_status, valid_until, fingerprint)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (kid, kid, str(agentId), visibility, str(item.get("owner_user_id") or ""), shared,
                 str(item.get("category") or ""), tags, str(item.get("source") or ""),
                 float(item.get("updated_at") or 0), str(item.get("lifecycle_status") or "active"),
                 str(item.get("valid_until") or ""), fingerprint),
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
