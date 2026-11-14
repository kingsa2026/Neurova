"""SQLite FTS5 持久倒排索引（无新增第三方依赖）。

doc 粒度 = 知识条目（与 BM25/FTS 辅助路同粒度）；中文先走仓库现有 tokenize
（jieba 可选、缺席 n-gram）再写入 FTS，查询侧同样预分词，避免依赖 FTS5 对中文
分词的未验证假设。可见性、agent、category、tags、source、时间与生命周期过滤
都在 SQL 里完成；FTS 命中仍要经调用方可见集回映。

schema 归属（K-09，2026-11-07 裁定）：本索引的库文件就是 foundation 主库
（knowledge_facts.db），两表 DDL 由 v37 迁移持有（foundation_schema 注册）——
独立 knowledge_fts.db 与本文件自建 DDL 已退役，派生索引可由 reconcile 全量重建。
"""
from __future__ import annotations

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
from neurova.core.time_utils import nowIso as _nowIso

logger = get_logger(__name__)

# v37：FTS 两表进 foundation 主库（K-09 裁定 2026-11-07）。SQL 由本模块持有、
# foundation_schema 注册；source_modified_at 是条目源钟进倒排面——消费方是
# search() 的确定性同分 tie-break（同分命中里源文档更新者排前）。
_SCHEMA_V37_FTS = """
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
    source_modified_at TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(content);
"""


def _tokens(text: str) -> str:
    return " ".join(tokenize(text or ""))


class KnowledgeFtsIndex:
    def __init__(self, db_path: str) -> None:
        self._path = str(db_path)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # 与 facts/narratives/entry ledger 同开一个文件：busy_timeout 必须有，
        # 否则并发写即 SQLITE_BUSY 沿 ftsSearch 的不吞异常通道放大
        self._conn.execute("PRAGMA busy_timeout=5000")
        with self._lock:
            # schema 单一事实源在 v37 迁移链；这里只保证"先于任何写入就位"
            # （幂等：迁移器按 user_version 跳过已应用步骤）
            from .foundation.foundation_schema import applyTo

            applyTo(self._conn)

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
        "lifecycle_status", "valid_until", "source_modified_at",
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
            str(item.get("source_modified_at") or ""),
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
            str(item.get("title") or ""), str(item.get("content") or ""),
            event_summary=str(item.get("event_summary") or ""),
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
        categories: Optional[Iterable[str]] = None,
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
        # 部门分类白名单（specs/2026-11-07 批 C）：repository 层解析后下推；
        # 空列表 = 受限且无可见分类 → 显式零命中（1=0），不是"不过滤"
        if categories is not None:
            cat_list = [str(c) for c in categories if str(c)]
            if not cat_list:
                clauses.append("1 = 0")
            else:
                placeholders = ", ".join("?" for _ in cat_list)
                clauses.append(f"d.category IN ({placeholders})")
                params.extend(cat_list)
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
            # K-09 源钟消费方：bm25 同分的命中按源文档时间倒序排——确定性 tie-break，
            # 源文档更新者排前；无源钟（空串）排最后，不改变有钟命中的相对序
            + " ORDER BY bm25(knowledge_fts), d.source_modified_at DESC LIMIT ?"
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
