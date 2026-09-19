"""事实底座：唯一权威源的知识存储（工单 003，设计文档 §4.2）。

形状承自 `temporal_knowledge_graph.py` 的时序事实表（四套既有存储里唯一已具备底座形状的），
并预留溯源 / 生命周期 / 使用回写列——后续工单只加行为，不再反复改表。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.db_migration import migrate as apply_migrations, register_migration
from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_FACT_DB = "./data/knowledge/knowledge_facts.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_subjects (
    subject_key TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    canonical_label TEXT NOT NULL,
    normalized_label TEXT NOT NULL,
    type_term_id TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    merged_into TEXT,
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_subject_label ON knowledge_subjects(agent_id, normalized_label);

CREATE TABLE IF NOT EXISTS knowledge_facts (
    fact_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    predicate_term_id TEXT NOT NULL,
    object_term TEXT NOT NULL,
    relation_kind TEXT NOT NULL DEFAULT 'literal',
    content TEXT NOT NULL DEFAULT '',
    content_key TEXT,
    qualifier_hash TEXT NOT NULL DEFAULT '',
    qualifier_json TEXT NOT NULL DEFAULT '{}',
    confidence REAL,
    evidence_state TEXT NOT NULL DEFAULT 'unevidenced',
    status TEXT NOT NULL DEFAULT 'active',
    supersedes_fact_id TEXT,
    contradicted_by_json TEXT NOT NULL DEFAULT '[]',
    valid_from TEXT,
    valid_until TEXT,
    recorded_at TEXT NOT NULL,
    retracted_at TEXT,
    assertions_json TEXT NOT NULL DEFAULT '[]',
    source_turn_id TEXT NOT NULL DEFAULT '',
    assertion_count INTEGER NOT NULL DEFAULT 0,
    injected_count INTEGER NOT NULL DEFAULT 0,
    last_injected_at TEXT,
    adoption_outcome TEXT,
    latest_adoption_outcome TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_triple
    ON knowledge_facts(agent_id, subject_key, predicate_term_id, object_term, qualifier_hash);
CREATE INDEX IF NOT EXISTS idx_fact_subject ON knowledge_facts(subject_key, status);
CREATE INDEX IF NOT EXISTS idx_fact_content ON knowledge_facts(agent_id, content_key);
"""
register_migration(1, _SCHEMA, domain="knowledge_foundation")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def normalizeLabel(label: str) -> str:
    """身份归一：大小写与首尾空白不敏感。相似度归并不在此（工单 006）。"""
    return (label or "").strip().lower()


class KnowledgeFactStore:
    """SPO 事实 + 主体身份的唯一权威源。不持写权外的任何旁路。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        # B01 的成因就是"无参构造悄悄落到内存库"：这里不留默认值，逼调用方表态。
        if not db_path:
            raise ValueError(
                "KnowledgeFactStore 需显式传入 db_path（生产用 %r，测试用 ':memory:'）；"
                "不给默认是为了不再复现『检索分支对着空表跑』。" % DEFAULT_FACT_DB
            )
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._ensureSchema()

    def _ensureSchema(self) -> None:
        with self._lock:
            apply_migrations(self._conn, "knowledge_foundation")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── 身份层 ────────────────────────────────────────────────

    def upsertSubject(
        self, agentId: str, label: str, aliases: Optional[List[str]] = None,
        typeTermId: Optional[str] = None,
    ) -> str:
        normalized = normalizeLabel(label)
        if not normalized:
            raise ValueError("subject_label 不能为空")
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT subject_key, aliases_json FROM knowledge_subjects"
                " WHERE agent_id = ? AND normalized_label = ?",
                (agentId, normalized),
            ).fetchone()
            stamp = _now()
            if row:
                key = row["subject_key"]
                merged = self._mergeAliases(json.loads(row["aliases_json"]), aliases or [])
                self._conn.execute(
                    "UPDATE knowledge_subjects SET aliases_json = ?, updated_at = ?,"
                    " type_term_id = COALESCE(?, type_term_id) WHERE subject_key = ?",
                    (json.dumps(merged, ensure_ascii=False), stamp, typeTermId, key),
                )
                return key
            key = "subj_" + hashlib.sha256(
                ("%s|%s" % (agentId, normalized)).encode("utf-8")
            ).hexdigest()[:16]
            self._conn.execute(
                "INSERT INTO knowledge_subjects (subject_key, agent_id, canonical_label,"
                " normalized_label, type_term_id, aliases_json, first_seen_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (key, agentId, label.strip(), normalized, typeTermId,
                 json.dumps(aliases or [], ensure_ascii=False), stamp, stamp),
            )
            return key

    @staticmethod
    def _mergeAliases(existing: List[str], added: List[str]) -> List[str]:
        merged = list(existing)
        for alias in added:
            if alias and alias not in merged:
                merged.append(alias)
        return merged

    def resolveSubjectKey(self, agentId: str, labelOrAlias: str) -> Optional[str]:
        normalized = normalizeLabel(labelOrAlias)
        with self._lock:
            row = self._conn.execute(
                "SELECT subject_key FROM knowledge_subjects"
                " WHERE agent_id = ? AND normalized_label = ?",
                (agentId, normalized),
            ).fetchone()
            if row is None:
                for cand in self._conn.execute(
                    "SELECT subject_key, aliases_json FROM knowledge_subjects WHERE agent_id = ?",
                    (agentId,),
                ).fetchall():
                    if normalized in [normalizeLabel(a) for a in json.loads(cand["aliases_json"])]:
                        row = cand
                        break
            if row is None:
                return None
            return self._followMerge(row["subject_key"])

    def _followMerge(self, subjectKey: str, maxHops: int = 16) -> str:
        current = subjectKey
        for _ in range(maxHops):
            with self._lock:
                row = self._conn.execute(
                    "SELECT merged_into FROM knowledge_subjects WHERE subject_key = ?", (current,)
                ).fetchone()
            if row is None or not row["merged_into"]:
                return current
            current = row["merged_into"]
        raise RuntimeError("主体合并链超 %d 跳，疑似成环: %s" % (maxHops, subjectKey))

    def mergeSubjects(self, oldKey: str, newKey: str, reason: str = "") -> None:
        if oldKey == newKey:
            raise ValueError("不能把主体并入自身")
        with self._lock, self._conn:
            if self._conn.execute(
                "SELECT 1 FROM knowledge_subjects WHERE subject_key = ?", (newKey,)
            ).fetchone() is None:
                raise LookupError("目标主体不存在: %s" % newKey)
            self._conn.execute(
                "UPDATE knowledge_subjects SET merged_into = ?, status = 'merged', updated_at = ?"
                " WHERE subject_key = ?",
                (newKey, _now(), oldKey),
            )
            self._conn.execute(
                "UPDATE knowledge_facts SET subject_key = ? WHERE subject_key = ?",
                (newKey, oldKey),
            )
        logger.info("主体合并 %s → %s（%s）", oldKey, newKey, reason)

    def subjectFor(self, subjectKey: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_subjects WHERE subject_key = ?", (subjectKey,)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["aliases"] = json.loads(d.pop("aliases_json", "[]") or "[]")
        return d

    def subjectCount(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM knowledge_subjects").fetchone()[0])

    # ── 事实层 ────────────────────────────────────────────────

    def upsertFact(
        self,
        agentId: str,
        subjectKey: str,
        predicateTermId: str,
        objectTerm: str,
        content: str,
        relationKind: str = "literal",
        qualifier: Optional[Dict[str, Any]] = None,
        sourceTurnId: str = "",
        confidence: Optional[float] = None,
        contentKey: Optional[str] = None,
    ) -> str:
        """同 (主体, 谓词, 客体, 限定) 或同 content_key 重放返回同一 fact_id。

        content_key 先查：B03 的 38 行纯冗余正是"三元组不同但内容相同"各开一行，
        口径必须是内容而不是三元组。空 key（无内容身份）不参与去重。
        """
        if contentKey:
            existing = self.findFactByContentKey(agentId, contentKey)
            if existing:
                return existing["fact_id"]
        qualifier = qualifier or {}
        qualifierHash = hashlib.sha256(
            json.dumps(qualifier, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12] if qualifier else ""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT fact_id FROM knowledge_facts WHERE agent_id = ? AND subject_key = ?"
                " AND predicate_term_id = ? AND object_term = ? AND qualifier_hash = ?",
                (agentId, subjectKey, predicateTermId, objectTerm, qualifierHash),
            ).fetchone()
            if row:
                if contentKey:
                    # 存量行可能还没有内容身份键（019 迁移前后都会出现）：
                    # 不补就会有一条永远绕过去重的行。
                    self._conn.execute(
                        "UPDATE knowledge_facts SET content_key = COALESCE(content_key, ?)"
                        " WHERE fact_id = ?",
                        (contentKey, row["fact_id"]),
                    )
                return row["fact_id"]
            factId = "fact_%s" % uuid.uuid4().hex[:12]
            self._conn.execute(
                "INSERT INTO knowledge_facts (fact_id, agent_id, subject_key, predicate_term_id,"
                " object_term, relation_kind, content, content_key, qualifier_hash, qualifier_json,"
                " confidence, source_turn_id, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (factId, agentId, subjectKey, predicateTermId, objectTerm, relationKind, content,
                 contentKey, qualifierHash, json.dumps(qualifier, ensure_ascii=False), confidence,
                 sourceTurnId, _now()),
            )
            return factId

    def fact(self, factId: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_facts WHERE fact_id = ?", (factId,)
            ).fetchone()
        return self._hydrate(row) if row else None

    def factsForSubject(self, subjectKey: str, includeInactive: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM knowledge_facts WHERE subject_key = ?"
        if not includeInactive:
            sql += " AND status = 'active'"
        with self._lock:
            rows = self._conn.execute(sql, (subjectKey,)).fetchall()
        return [self._hydrate(r) for r in rows]

    @staticmethod
    def _hydrate(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        d["assertions"] = json.loads(d.pop("assertions_json", "[]") or "[]")
        d["qualifier"] = json.loads(d.pop("qualifier_json", "{}") or "{}")
        d["contradicted_by"] = json.loads(d.pop("contradicted_by_json", "[]") or "[]")
        return d

    def setContentKey(self, factId: str, contentKey: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE knowledge_facts SET content_key = ? WHERE fact_id = ?",
                (contentKey, factId),
            )

    def factCount(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM knowledge_facts").fetchone()[0])

    def findFactByContentKey(self, agentId: str, contentKey: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_facts WHERE agent_id = ? AND content_key = ? LIMIT 1",
                (agentId, contentKey),
            ).fetchone()
        return self._hydrate(row) if row else None


_store_singleton: Optional[KnowledgeFactStore] = None
_store_lock = threading.Lock()


def get_knowledge_fact_store(db_path: Optional[str] = None) -> KnowledgeFactStore:
    global _store_singleton
    with _store_lock:
        if _store_singleton is None:
            _store_singleton = KnowledgeFactStore(db_path or DEFAULT_FACT_DB)
        return _store_singleton


def reset_knowledge_fact_store() -> None:
    global _store_singleton
    with _store_lock:
        if _store_singleton is not None:
            _store_singleton.close()
        _store_singleton = None
