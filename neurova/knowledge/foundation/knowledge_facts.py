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

# ADR 0016 三态纪律：这三值是穷举，"没证据"（unevidenced）不等于"通过"（evidenced）。
EVIDENCE_STATES = ("evidenced", "failed", "unevidenced")

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
-- 内容去重必须是结构约束而不是"先查后插"：两个并发写同一内容会各插一行。
-- 空 content_key（无内容身份）不入索引，避免空写入互撞。
CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_agent_content
    ON knowledge_facts(agent_id, content_key) WHERE content_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS knowledge_activities (
    activity_id TEXT PRIMARY KEY,
    activity_kind TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    inputs_json TEXT NOT NULL DEFAULT '{}',
    outputs_json TEXT NOT NULL DEFAULT '{}',
    basis TEXT NOT NULL DEFAULT '',
    tool_version TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS knowledge_assertions (
    assertion_id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    activity_id TEXT,
    medium_ref TEXT NOT NULL DEFAULT '',
    statement_text TEXT NOT NULL DEFAULT '',
    statement_hash TEXT NOT NULL DEFAULT '',
    asserted_at TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    verification_state TEXT NOT NULL DEFAULT 'unverified'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_assertion_identity
    ON knowledge_assertions(fact_id, actor_type, actor_id, medium_ref, statement_hash);
CREATE INDEX IF NOT EXISTS idx_assertion_fact ON knowledge_assertions(fact_id);
"""
register_migration(1, _SCHEMA, domain="knowledge_foundation")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _instant(value) -> str:
    """时效判定比的是瞬时不是字面：混着 Z / +08:00 / 无时区写入时，
    文本序会把"已到期"读成"未到期"，所以进出都归一成 UTC ISO。naive 按 UTC 解读。
    """
    if isinstance(value, datetime.datetime):
        stamp = value
    else:
        stamp = datetime.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.timezone.utc)
    return stamp.astimezone(datetime.timezone.utc).isoformat()


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

    def listSubjects(self, agentId: str, includeMerged: bool = False) -> List[Dict[str, Any]]:
        """某 agent 下的主体清单——消解段要拿全量做候选，不能只看精确名。"""
        sql = "SELECT * FROM knowledge_subjects WHERE agent_id = ?"
        if not includeMerged:
            sql += " AND status != 'merged'"
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY canonical_label, subject_key", (agentId,)).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["aliases"] = json.loads(d.pop("aliases_json", "[]") or "[]")
            out.append(d)
        return out

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
            try:
                self._conn.execute(
                    "INSERT INTO knowledge_facts (fact_id, agent_id, subject_key, predicate_term_id,"
                    " object_term, relation_kind, content, content_key, qualifier_hash, qualifier_json,"
                    " confidence, source_turn_id, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (factId, agentId, subjectKey, predicateTermId, objectTerm, relationKind, content,
                     contentKey, qualifierHash, json.dumps(qualifier, ensure_ascii=False), confidence,
                     sourceTurnId, _now()),
                )
            except sqlite3.IntegrityError:
                # 唯一索引挡住竞态双写：改读先到的那一行，而不是让写入方看到崩
                if not contentKey:
                    raise
                winner = self._conn.execute(
                    "SELECT fact_id FROM knowledge_facts WHERE agent_id = ? AND content_key = ?",
                    (agentId, contentKey),
                ).fetchone()
                if winner is None:
                    raise
                return winner["fact_id"]
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

    # ── 溯源层 ────────────────────────────────────────────────

    def insertActivity(
        self, kind: str, inputs: Optional[Dict[str, Any]] = None,
        basis: str = "", toolVersion: str = "",
    ) -> str:
        activityId = "act_%s" % uuid.uuid4().hex[:12]
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO knowledge_activities (activity_id, activity_kind, started_at,"
                " inputs_json, basis, tool_version) VALUES (?,?,?,?,?,?)",
                (activityId, kind, _now(),
                 json.dumps(inputs or {}, ensure_ascii=False, sort_keys=True), basis, toolVersion),
            )
        return activityId

    def finishActivity(self, activityId: str, outputs: Optional[Dict[str, Any]] = None) -> None:
        with self._lock, self._conn:
            self._requireActivity(activityId)
            self._conn.execute(
                "UPDATE knowledge_activities SET finished_at = ?, outputs_json = ?"
                " WHERE activity_id = ?",
                (_now(), json.dumps(outputs or {}, ensure_ascii=False, sort_keys=True), activityId),
            )

    def activity(self, activityId: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_activities WHERE activity_id = ?", (activityId,)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["inputs"] = json.loads(d.pop("inputs_json", "{}") or "{}")
        d["outputs"] = json.loads(d.pop("outputs_json", "{}") or "{}")
        return d

    def _requireActivity(self, activityId: str) -> Dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM knowledge_activities WHERE activity_id = ?", (activityId,)
        ).fetchone()
        if row is None:
            raise LookupError("活动不存在: %s" % activityId)
        return dict(row)

    def insertAssertion(
        self, factId: str, actorType: str, actorId: str, mediumRef: str,
        statementText: str, statementHash: str, activityId: Optional[str] = None,
        weight: float = 1.0,
    ) -> Optional[str]:
        """幂等插断言；已存在返回 None（同主体同来源同陈述不重复计一次）。"""
        self._requireFact(factId)
        assertionId = "asrt_%s" % uuid.uuid4().hex[:12]
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO knowledge_assertions (assertion_id, fact_id, actor_type,"
                " actor_id, activity_id, medium_ref, statement_text, statement_hash, asserted_at,"
                " weight) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (assertionId, factId, actorType, actorId, activityId, mediumRef,
                 statementText, statementHash, _now(), weight),
            )
            if not cur.rowcount:
                return None
            self._conn.execute(
                "UPDATE knowledge_facts SET assertion_count = assertion_count + 1 WHERE fact_id = ?",
                (factId,),
            )
        return assertionId

    def assertions(self, factId: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM knowledge_assertions WHERE fact_id = ?"
                " ORDER BY asserted_at, assertion_id",
                (factId,),
            ).fetchall()
        return [dict(row) for row in rows]

    def setAssertionCount(self, factId: str, count: int) -> None:
        with self._lock, self._conn:
            self._requireFact(factId)
            self._conn.execute(
                "UPDATE knowledge_facts SET assertion_count = ? WHERE fact_id = ?",
                (int(count), factId),
            )

    def lineageRows(self, factId: str) -> List[Dict[str, Any]]:
        """断言 + 其所属活动，一跳取齐（溯源链的多跳展开在 ledger 里做）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT a.*, k.activity_kind, k.started_at AS activity_started_at,"
                " k.finished_at AS activity_finished_at, k.basis AS activity_basis,"
                " k.inputs_json AS activity_inputs"
                " FROM knowledge_assertions a"
                " LEFT JOIN knowledge_activities k ON k.activity_id = a.activity_id"
                " WHERE a.fact_id = ? ORDER BY a.asserted_at, a.assertion_id",
                (factId,),
            ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["activity_inputs"] = json.loads(d.get("activity_inputs") or "{}")
            out.append(d)
        return out

    # ── 生命周期（工单 008 / G06）─────────────────────────────
    # 状态是生命周期的唯一权威：读侧只看 status，不再各自拿 valid_until 比时钟，
    # 否则会出现"两处判定不一致"的第二真源。到期靠显式调用推进，不起后台线程。

    def _requireFact(self, factId: str) -> Dict[str, Any]:
        row = self._conn.execute(
            "SELECT status FROM knowledge_facts WHERE fact_id = ?", (factId,)
        ).fetchone()
        if row is None:
            raise LookupError("事实不存在: %s" % factId)
        return dict(row)

    def supersede(self, newFactId: str, oldFactId: str, reason: str = "") -> None:
        """新说法接管：旧事实出检索候选，但仍留在账上可溯源。"""
        if newFactId == oldFactId:
            raise ValueError("不能取代自身: %s" % newFactId)
        with self._lock, self._conn:
            newStatus = self._requireFact(newFactId)["status"]
            oldStatus = self._requireFact(oldFactId)["status"]
            for factId, status in ((newFactId, newStatus), (oldFactId, oldStatus)):
                if status != "active":
                    raise ValueError(
                        "取代只发生在 active 事实上（%s 当前为 %r）" % (factId, status)
                    )
            self._conn.execute(
                "UPDATE knowledge_facts SET supersedes_fact_id = ? WHERE fact_id = ?",
                (oldFactId, newFactId),
            )
            self._conn.execute(
                "UPDATE knowledge_facts SET status = 'superseded' WHERE fact_id = ?",
                (oldFactId,),
            )
        logger.info("事实取代 %s ← %s（%s）", newFactId, oldFactId, reason)

    def setValidUntil(self, factId: str, validUntil: Optional[str]) -> None:
        stored = None if validUntil is None else _instant(validUntil)
        with self._lock, self._conn:
            self._requireFact(factId)
            self._conn.execute(
                "UPDATE knowledge_facts SET valid_until = ? WHERE fact_id = ?",
                (stored, factId),
            )

    def expireDueFacts(self, now: Optional[str] = None) -> int:
        instant = _instant(now) if now is not None else _now()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE knowledge_facts SET status = 'expired'"
                " WHERE status = 'active' AND valid_until IS NOT NULL AND valid_until < ?",
                (instant,),
            )
            return int(cur.rowcount)

    def retract(self, factId: str, reason: str = "") -> None:
        """可撤销不可遗忘：行不删，只出候选，溯源查询永远读得到。"""
        with self._lock, self._conn:
            self._requireFact(factId)
            self._conn.execute(
                "UPDATE knowledge_facts SET status = 'retracted', retracted_at = ?"
                " WHERE fact_id = ?",
                (_now(), factId),
            )
        logger.info("事实撤回 %s（%s）", factId, reason)

    def setEvidenceState(self, factId: str, evidenceState: str) -> None:
        """本列 NOT NULL：NULL 在这里没有位置，"从未回写"由 adoption_outcome 的 NULL 承载（G07）。"""
        if evidenceState not in EVIDENCE_STATES:
            raise ValueError(
                "非法 evidence_state: %r（有效值: %s）" % (evidenceState, "/".join(EVIDENCE_STATES))
            )
        with self._lock, self._conn:
            self._requireFact(factId)
            self._conn.execute(
                "UPDATE knowledge_facts SET evidence_state = ? WHERE fact_id = ?",
                (evidenceState, factId),
            )


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
