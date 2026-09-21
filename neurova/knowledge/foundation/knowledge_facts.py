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

from neurova.core.logger import get_logger

from .credibility import ConfidenceAggregator
from .narratives import FOUNDATION_DB_NAME
from .storage_fence import PRODUCTION_STORAGE_DIR, assertNotUnderProductionStorage

logger = get_logger(__name__)

# 置信度聚合只有一处算法源；store 在输入变化处回算，避免派生列腐烂
_AGGREGATOR = ConfidenceAggregator()

# 生产路径只有 storage_fence 一处定义；这里派生，不再抄第二份字面量。
DEFAULT_FACT_DB = str(Path(PRODUCTION_STORAGE_DIR) / FOUNDATION_DB_NAME)

# ADR 0016 三态纪律：这三值是穷举，"没证据"（unevidenced）不等于"通过"（evidenced）。
EVIDENCE_STATES = ("evidenced", "failed", "unevidenced")

# 采纳侧三值：与形成侧的 evidence_state 正交；列上的 NULL 另占一义 = "从未回写"
ADOPTION_OUTCOMES = ("success", "failure", "unevidenced")

# 断言的校验侧三值（工单 023 的闭环）：`unverified` 是"还没验过"，
# `failed` 是"验过、没通过"。两者混成一个值，读数就把"没测过"报成"测过没问题"。
ASSERTION_VERIFICATIONS = ("unverified", "verified", "failed")

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

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS knowledge_conflicts (
    conflict_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    predicate_term_id TEXT NOT NULL,
    member_fact_ids_json TEXT NOT NULL DEFAULT '[]',
    member_signature TEXT NOT NULL DEFAULT '',
    severity REAL NOT NULL DEFAULT 0.5,
    recommended_policy TEXT NOT NULL DEFAULT 'manual',
    policy_basis TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT,
    resolved_by TEXT NOT NULL DEFAULT '',
    winner_fact_id TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_conflict_members ON knowledge_conflicts(member_signature);
CREATE INDEX IF NOT EXISTS idx_conflict_status ON knowledge_conflicts(status, detected_at);
"""

# v1 发布之后补的结构必须另起版本：已存在的库 user_version 已经是 1，
# 再往 _SCHEMA 里加东西永远不会被重放（工单 011 首次真数据回填就是这样炸的）。
_SCHEMA_V3 = """
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

-- 内容去重是结构约束而不是"先查后插"：并发写同一内容会各插一行。
-- 空 content_key（无内容身份）不入索引，避免空写入互撞。
CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_agent_content
    ON knowledge_facts(agent_id, content_key) WHERE content_key IS NOT NULL;
"""

# 工单 019b-1：条目（叙述记录）也经咽喉，但正文只有一份、留在叙述层，
# 事实行因此需要种类标记。默认 'triple' 让既有行与既有调用方一字不改。
# 版本号 5 与注册顺序由 foundation_schema 统一持有。
_SCHEMA_V5 = """
ALTER TABLE knowledge_facts ADD COLUMN record_kind TEXT NOT NULL DEFAULT 'triple';
"""


MANUAL_RESOLUTIONS: tuple = ("keep_both", "supersede_old", "dismiss")


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
        assertNotUnderProductionStorage(db_path, "事实底座库")
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._ensureSchema()
        from ..ontology.derivation_ledger import DerivationLedger
        from .digest_chain import ActivityDigestChain

        self._derivationLedger = DerivationLedger(self)
        self._digestChain = ActivityDigestChain(self)

    def _ensureSchema(self) -> None:
        with self._lock:
            from .foundation_schema import applyTo  # 惰性：链的单主注册处反过来依赖本模块

            applyTo(self._conn)

    def _retireDerived(self, factId: str, reason: str) -> int:
        """让前提离开 active 的每一条路径都必须在事务外叫它一次。

        级联算法只准有账本一处；这里只负责在正确的时机叫，且在锁外叫——
        在 `with self._conn` 里回调会把外层事务提前提交掉。
        """
        return self._derivationLedger.retractAllDerivedFrom(factId, reason)

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
        recordedAt: Optional[str] = None,
        recordKind: str = "triple",
        validFrom: Optional[str] = None,
        validUntil: Optional[str] = None,
    ) -> str:
        """同 (主体, 谓词, 客体, 限定) 或同 content_key 重放返回同一 fact_id。

        content_key 先查：B03 的 38 行纯冗余正是"三元组不同但内容相同"各开一行，
        口径必须是内容而不是三元组。空 key（无内容身份）不参与去重。

        时效窗口在这里落库：`admission` 的入参契约早就带着 `validFrom` / `validUntil`，
        底座表也早有这两列，中间那一跳却没收参数——于是两列永远是 NULL，
        `conflict_judge` 的 temporal 分类与 `expireDueFacts()` 双双没有输入。
        调用方声明过窗口就补进已存在的行（只补 NULL，不覆盖既有窗口）。
        """
        windowFrom = _instant(validFrom) if validFrom else None
        windowUntil = _instant(validUntil) if validUntil else None
        if contentKey:
            existing = self.findFactByContentKey(agentId, contentKey)
            if existing:
                self.fillValidityWindow(existing["fact_id"], windowFrom, windowUntil)
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
                self.fillValidityWindow(row["fact_id"], windowFrom, windowUntil)
                return row["fact_id"]
            factId = "fact_%s" % uuid.uuid4().hex[:12]
            try:
                self._conn.execute(
                    "INSERT INTO knowledge_facts (fact_id, agent_id, subject_key, predicate_term_id,"
                    " object_term, relation_kind, content, content_key, qualifier_hash, qualifier_json,"
                    " confidence, source_turn_id, recorded_at, record_kind, valid_from, valid_until)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (factId, agentId, subjectKey, predicateTermId, objectTerm, relationKind, content,
                     contentKey, qualifierHash, json.dumps(qualifier, ensure_ascii=False), confidence,
                     sourceTurnId, _instant(recordedAt) if recordedAt else _now(), recordKind,
                     windowFrom, windowUntil),
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

    def setConfidence(self, factId: str, confidence: Optional[float],
                      evidenceState: Optional[str] = None) -> None:
        with self._lock, self._conn:
            self._requireFact(factId)
            if evidenceState is not None and evidenceState not in EVIDENCE_STATES:
                raise ValueError("未知 evidence_state: %r（有效值: %s）"
                                 % (evidenceState, " / ".join(EVIDENCE_STATES)))
            if confidence is not None and not 0.0 <= float(confidence) <= 1.0:
                raise ValueError("confidence 必须落在 [0,1] 或 None，收到 %r" % (confidence,))
            if evidenceState is None:
                self._conn.execute(
                    "UPDATE knowledge_facts SET confidence = ? WHERE fact_id = ?",
                    (confidence, factId),
                )
            else:
                self._conn.execute(
                    "UPDATE knowledge_facts SET confidence = ?, evidence_state = ?"
                    " WHERE fact_id = ?",
                    (confidence, evidenceState, factId),
                )

    def _refreshConfidence(self, factId: str) -> None:
        """派生列会在输入变化处腐烂——断言增删、矛盾标记都必须就地重算。

        算法只有一份，在 `ConfidenceAggregator`；这里不重复实现第二套口径。
        证据态只做单向升级（unevidenced → evidenced）：人为标记的 failed/unevidenced
        是判定结论，不能被"后来多了一条断言"这种输入变化抹掉。
        """
        fact = self.fact(factId)
        verdict = _AGGREGATOR.aggregate(fact, self.assertions(factId))
        evidenceState = verdict["evidence_state"] if fact.get("evidence_state") == "unevidenced" \
            else None
        self.setConfidence(factId, verdict["confidence"], evidenceState)

    def markContradicted(self, factId: str, counterpartIds: List[str]) -> None:
        """记下与哪些事实相对立。读侧看不到矛盾，就等于矛盾从未发生。"""
        row = self._requireFact(factId)
        merged = sorted({*(row.get("contradicted_by") or []),
                         *(str(c) for c in counterpartIds if c and c != factId)})
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE knowledge_facts SET contradicted_by_json = ? WHERE fact_id = ?",
                (json.dumps(merged, ensure_ascii=False), factId),
            )
        self._refreshConfidence(factId)

    # ── 使用与采纳回流（工单 010 / G07、B06）──────────────────

    def recordInjection(self, factIds: List[str]) -> int:
        """检索命中即计数。先全量校验再写，避免"记了一半"的现场。"""
        ids = [str(f) for f in factIds if f]
        if not ids:
            return 0
        for factId in ids:
            self._requireFact(factId)
        stamp = _now()
        with self._lock, self._conn:
            for factId in ids:
                # UPDATE 自增在持锁事务内完成，不读改写——那会丢并发计数
                self._conn.execute(
                    "UPDATE knowledge_facts SET injected_count = injected_count + 1,"
                    " last_injected_at = ? WHERE fact_id = ?",
                    (stamp, factId),
                )
        return len(ids)

    def recordAdoption(self, factId: str, outcome: str) -> None:
        """采纳结局回写。NULL 专用于"从未发生过回写"，`unevidenced` 是"回写过但无依据"。"""
        if outcome not in ADOPTION_OUTCOMES:
            raise ValueError("未知 adoption_outcome: %r（有效值: %s）"
                             % (outcome, " / ".join(ADOPTION_OUTCOMES)))
        with self._lock, self._conn:
            self._requireFact(factId)
            self._conn.execute(
                "UPDATE knowledge_facts SET adoption_outcome = ?, latest_adoption_outcome = ?"
                " WHERE fact_id = ?",
                (outcome, outcome, factId),
            )

    def usageMetrics(self) -> Dict[str, Any]:
        """零使用占比 / 回写盲区 / 三态分布——治理面的读数，不是排序依据。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS total,"
                " SUM(CASE WHEN injected_count = 0 THEN 1 ELSE 0 END) AS never_injected,"
                " SUM(CASE WHEN adoption_outcome IS NULL THEN 1 ELSE 0 END) AS never_written,"
                " SUM(CASE WHEN adoption_outcome = 'success' THEN 1 ELSE 0 END) AS ok,"
                " SUM(CASE WHEN adoption_outcome = 'failure' THEN 1 ELSE 0 END) AS bad,"
                " SUM(CASE WHEN adoption_outcome = 'unevidenced' THEN 1 ELSE 0 END) AS blind"
                " FROM knowledge_facts"
            ).fetchone()
        total = int(row["total"] or 0)
        if not total:
            return {
                "measure_state": "unevidenced", "fact_count": 0, "never_injected_count": 0,
                "never_injected_share": None, "outcome_written": 0, "outcome_never_written": 0,
                "outcome_success": 0, "outcome_failure": 0, "outcome_unevidenced": 0,
                "missing_reason": "底座还没有任何事实，使用度量无依据可依",
            }
        return {
            "measure_state": "measured",
            "fact_count": total,
            "never_injected_count": int(row["never_injected"] or 0),
            "never_injected_share": round(int(row["never_injected"] or 0) / total, 4),
            "outcome_written": total - int(row["never_written"] or 0),
            "outcome_never_written": int(row["never_written"] or 0),
            "outcome_success": int(row["ok"] or 0),
            "outcome_failure": int(row["bad"] or 0),
            "outcome_unevidenced": int(row["blind"] or 0),
        }

    def searchableFacts(
        self, agentId: Optional[str] = None, includeNarratives: bool = False
    ) -> List[Dict[str, Any]]:
        """读面候选：仅 active 且未过期的事实，带主体规范名。

        时效权威仍是 `status`（工单 008 定的唯一真源），这里只额外挡掉已到期但尚未
        被 `expireDueFacts()` 推进的行——否则读面会跑在巡检前头。

        叙述记录默认不进池：它的事实行**有意**不存正文（正文唯一副本在
        `knowledge_narratives`），混进来就是一池空文本。等读路径接上按 knowledge_id
        回查正文的那一刀（019b-3）再放开，而不是先放进来让排序对着空内容打分。
        """
        sql = ("SELECT f.*, s.canonical_label FROM knowledge_facts f"
               " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
               " WHERE f.status = 'active' AND s.status != 'merged'"
               " AND (f.valid_until IS NULL OR f.valid_until > ?)")
        params: List[Any] = [_now()]
        if not includeNarratives:
            sql += " AND f.record_kind != 'narrative'"
        if agentId:
            sql += " AND f.agent_id = ?"
            params.append(agentId)
        sql += " ORDER BY f.recorded_at DESC, f.fact_id"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._hydrate(r) for r in rows]

    def factCount(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM knowledge_facts").fetchone()[0])

    def findFactByContentKey(self, agentId: str, contentKey: str) -> Optional[Dict[str, Any]]:
        """按内容键找该行（含已被取代的）。

        刻意不过滤 status：一旦只看 active，"折叠"就变成裁决顺序的函数——回放里某行被
        自动取代后，同内容会另开一行，静态预测与实跑当场对不上（实测 92 vs 102）。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_facts WHERE agent_id = ? AND content_key = ? LIMIT 1",
                (agentId, contentKey),
            ).fetchone()
        return self._hydrate(row) if row else None

    def narrativeFactForEntry(self, knowledgeId: str) -> Optional[Dict[str, Any]]:
        """条目 id → 当前治理行（跨 agent）。

        条目 id 现在只是溯源串（`entry:` / `legacy:` 前缀）与无内容身份时的客体；
        取最新一代，因为"改回原样"会开新行。不按 agent 收窄与 `find_item` 同口径——
        knowledge_id 本来就是全局 uuid。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_facts WHERE record_kind = 'narrative'"
                " AND status = 'active' AND (object_term = ?"
                " OR source_turn_id IN ('entry:' || ?, 'legacy:' || ?))"
                " ORDER BY recorded_at DESC, fact_id LIMIT 1",
                (knowledgeId, knowledgeId, knowledgeId),
            ).fetchone()
        return self._hydrate(row) if row else None

    def activeNarrativeFact(
        self, agentId: str, knowledgeId: str, contentKey: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """条目 → 当前治理行。内容键与客体一起认，两种立身方式都能查到。

        传内容键时只认内容键/客体——同内容即同一知识，两条正文相同的条目共享一行；
        不传时按"这个条目当前主张的是什么"回退，客体或溯源前缀（`entry:` 与回填的
        `legacy:`）任一命中都算。两种口径分开，是为了让投影分得清"已对齐"与"待改写"。
        """
        clauses = ["agent_id = ?", "record_kind = 'narrative'", "status = 'active'"]
        params: List[Any] = [agentId]
        if contentKey:
            # 给了内容键就必须按内容键认：旧说法也带着同一个条目的 source_turn_id，
            # 允许它靠溯源回退命中，投影就会把"还没改写"当成"已经对齐"。
            clauses.append("(content_key = ? OR object_term = ?)")
            params += [contentKey, contentKey]
        else:
            clauses.append("(object_term = ? OR source_turn_id IN ('entry:' || ?, 'legacy:' || ?))")
            params += [knowledgeId, knowledgeId, knowledgeId]
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_facts WHERE %s ORDER BY recorded_at, fact_id LIMIT 1"
                % " AND ".join(clauses), params,
            ).fetchone()
        return self._hydrate(row) if row else None

    def activeNarrativeFacts(self, agentId: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = ("SELECT * FROM knowledge_facts WHERE record_kind = 'narrative'"
               " AND status = 'active'")
        params: List[Any] = []
        if agentId:
            sql += " AND agent_id = ?"
            params.append(agentId)
        sql += " ORDER BY recorded_at, fact_id"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._hydrate(r) for r in rows]

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
            slot = self._digestChain.nextSlot(self._conn, activityId)
            item = {"assertion_id": assertionId, "fact_id": factId,
                    "actor_type": actorType, "actor_id": actorId,
                    "activity_id": activityId or "", "medium_ref": mediumRef,
                    "statement_hash": statementHash,
                    "seq": (slot or {}).get("seq", 0),
                    "prev_digest": (slot or {}).get("prevDigest", "")}
            digest = "" if slot is None else self._digestChain.digestFor(item)
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO knowledge_assertions (assertion_id, fact_id, actor_type,"
                " actor_id, activity_id, medium_ref, statement_text, statement_hash, asserted_at,"
                " weight, seq, digest, prev_digest) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (assertionId, factId, actorType, actorId, activityId, mediumRef,
                 statementText, statementHash, _now(), weight,
                 item["seq"], digest, item["prev_digest"]),
            )
            if not cur.rowcount:
                return None
            if slot is not None:
                self._digestChain.commit(self._conn, str(activityId), slot["seq"], digest)
            self._conn.execute(
                "UPDATE knowledge_facts SET assertion_count = assertion_count + 1 WHERE fact_id = ?",
                (factId,),
            )
        self._refreshConfidence(factId)
        return assertionId

    def assertions(self, factId: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM knowledge_assertions WHERE fact_id = ?"
                " ORDER BY asserted_at, assertion_id",
                (factId,),
            ).fetchall()
        return [dict(row) for row in rows]

    def setAssertionVerification(self, assertionId: str, state: str) -> None:
        """回写一条断言的校验结论。校验器是唯一写入者，列上的值域在这里收口。"""
        if state not in ASSERTION_VERIFICATIONS:
            raise ValueError(
                "未知 verification_state: %r（有效值: %s）"
                % (state, " / ".join(ASSERTION_VERIFICATIONS))
            )
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE knowledge_assertions SET verification_state = ?"
                " WHERE assertion_id = ?", (state, assertionId))
        if not cur.rowcount:
            raise LookupError("断言不存在: %s" % assertionId)

    def assertionVerificationCounts(self) -> Dict[str, int]:
        """三态分布读数：巡检与读面都吃它，不各写一套统计。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT verification_state, COUNT(*) AS n FROM knowledge_assertions"
                " GROUP BY verification_state").fetchall()
        counts = {state: 0 for state in ASSERTION_VERIFICATIONS}
        for row in rows:
            counts[str(row["verification_state"])] = int(row["n"])
        return counts

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

    # ── 治理层：冲突一等对象（工单 007 / G03、G04）────────────

    def insertConflict(
        self, kind: str, subjectKey: str, predicateTermId: str, memberFactIds: List[str],
        severity: float, recommendedPolicy: str, policyBasis: str, status: str = "pending",
        winnerFactId: Optional[str] = None,
    ) -> Optional[str]:
        """写一条冲突账；同组成员重复检测不再另开。

        auto_resolved 无依据即在落库处被拒——调用方忘传 basis 是常态，库不能放过。
        """
        if status == "auto_resolved" and not str(policyBasis or "").strip():
            raise ValueError("auto_resolved 必须带 policy_basis，无依据即不得自动关闭冲突")
        members = sorted({str(m) for m in memberFactIds if m})
        if len(members) < 2:
            raise ValueError("冲突至少需要 2 个成员事实，收到 %d 个" % len(members))
        conflictId = "cnf_%s" % uuid.uuid4().hex[:12]
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO knowledge_conflicts (conflict_id, kind, subject_key,"
                " predicate_term_id, member_fact_ids_json, member_signature, severity,"
                " recommended_policy, policy_basis, status, detected_at, winner_fact_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (conflictId, kind, subjectKey, predicateTermId,
                 json.dumps(members, ensure_ascii=False), "|".join(members), float(severity),
                 recommendedPolicy, policyBasis, status, _now(), winnerFactId),
            )
        return conflictId if cur.rowcount else None

    def conflicts(self, status: str = "pending") -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM knowledge_conflicts WHERE status = ?"
                " ORDER BY severity DESC, detected_at DESC",
                (status,),
            ).fetchall()
        return [self._hydrateConflict(r) for r in rows]

    def pendingConflictCount(self) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM knowledge_conflicts WHERE status = 'pending'"
            ).fetchone()[0])

    def conflictMembers(self, conflictId: str) -> List[Dict[str, Any]]:
        conflict = self._conflictRow(conflictId)
        return self.factsByIds(conflict["member_fact_ids"])

    def factsByIds(self, factIds: List[str]) -> List[Dict[str, Any]]:
        if not factIds:
            return []
        placeholders = ",".join("?" * len(factIds))
        with self._lock:
            rows = self._conn.execute(
                "SELECT f.*, s.agent_id AS agent_id FROM knowledge_facts f"
                " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
                " WHERE f.fact_id IN (%s) ORDER BY f.recorded_at, f.fact_id" % placeholders,
                list(factIds),
            ).fetchall()
        return [self._hydrate(r) for r in rows]

    def conflictWinner(self, conflictId: str) -> Optional[str]:
        return self._conflictRow(conflictId).get("winner_fact_id")

    def resolveConflict(self, conflictId: str, resolution: str, resolvedBy: str = "",
                        winnerFactId: Optional[str] = None) -> bool:
        """人工裁决一条治理层分歧。

        `supersede_old` 不只是记一笔：它必须真把败方退出活动集——否则队列清空了而两条
        矛盾事实还在同时进上下文，那是假干净。因此这种裁决要求显式指明胜方，
        且胜方必须是本条冲突的成员事实。
        """
        if resolution not in MANUAL_RESOLUTIONS:
            raise ValueError("未知裁决: %r（有效值: %s）" % (resolution, " / ".join(MANUAL_RESOLUTIONS)))
        winner = str(winnerFactId or "").strip()
        if resolution == "supersede_old" and not winner:
            raise ValueError("supersede_old 需要 winner_fact_id：得有人指明哪条说法胜出")
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT status, member_fact_ids_json FROM knowledge_conflicts"
                " WHERE conflict_id = ?", (conflictId,)
            ).fetchone()
            if row is None or row["status"] != "pending":
                return False
            members = json.loads(row["member_fact_ids_json"] or "[]")
            if resolution == "supersede_old" and winner not in members:
                raise ValueError("winner_fact_id 必须是本冲突的成员事实之一: %r" % winner)
            self._conn.execute(
                "UPDATE knowledge_conflicts SET status = 'resolved', resolution = ?,"
                " resolved_by = ?, resolved_at = ?, winner_fact_id = COALESCE(?, winner_fact_id)"
                " WHERE conflict_id = ?",
                (resolution, str(resolvedBy or ""), _now(), winner or None, conflictId),
            )
            for member in members:
                if resolution != "supersede_old" or member == winner:
                    continue
                fact = self.fact(member)
                if fact and fact.get("status") == "active":
                    self.supersede(winner, member, reason="conflict manual_resolved")
        return True

    def _conflictRow(self, conflictId: str) -> Dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_conflicts WHERE conflict_id = ?", (conflictId,)
            ).fetchone()
        if row is None:
            raise LookupError("冲突不存在: %s" % conflictId)
        return self._hydrateConflict(row)

    @staticmethod
    def _hydrateConflict(row) -> Dict[str, Any]:
        d = dict(row)
        d["member_fact_ids"] = json.loads(d.pop("member_fact_ids_json", "[]") or "[]")
        return d

    def candidateFactsForConflict(self, subjectLabel: str, predicateTermId: str) -> List[Dict[str, Any]]:
        """按归一化标签跨 agent 取候选。

        旧实现只在同 agent 桶内比对（`repository.py:1119`），跨库分歧因此永远不成账。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT f.*, s.agent_id AS subject_agent_id, s.canonical_label,"
                " s.normalized_label FROM knowledge_facts f"
                " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
                " WHERE s.normalized_label = ? AND f.predicate_term_id = ?"
                " AND s.merged_into IS NULL AND f.status != 'retracted'"
                " ORDER BY f.recorded_at, f.fact_id",
                (normalizeLabel(subjectLabel), predicateTermId),
            ).fetchall()
        return [self._hydrate(r) for r in rows]

    # ── 生命周期（工单 008 / G06）─────────────────────────────
    # 状态是生命周期的唯一权威：读侧只看 status，不再各自拿 valid_until 比时钟，
    # 否则会出现"两处判定不一致"的第二真源。到期靠显式调用推进，不起后台线程。

    def _requireFact(self, factId: str) -> Dict[str, Any]:
        """读整行并回传，且必须持锁。

        不持锁就是绕过 `threading.RLock` 直接摸共享连接：并发下游标互相踩，
        存在的事实会被读成"不存在"（工单 010 的并发计数用例实测到）。
        只回 status 一列则会让调用方以为拿得到整行——`markContradicted` 的合并曾被它静默架空。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_facts WHERE fact_id = ?", (factId,)
            ).fetchone()
        if row is None:
            raise LookupError("事实不存在: %s" % factId)
        return self._hydrate(row)

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
        self._retireDerived(oldFactId, reason or "推导前提已被取代")

    def fillValidityWindow(self, factId: str, validFrom: Optional[str],
                           validUntil: Optional[str]) -> None:
        """补窗口只填 NULL——既有窗口是已成立的时效声明，重放不得把它改写掉。

        咽喉的两条路径都调它：新建行走 `upsertFact`，按内容键折回旧行时走这里。
        同一个方法，不各写一套"只补空"的判据。
        """
        if validFrom is None and validUntil is None:
            return
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE knowledge_facts SET"
                " valid_from = COALESCE(valid_from, ?),"
                " valid_until = COALESCE(valid_until, ?)"
                " WHERE fact_id = ?",
                (validFrom, validUntil, factId),
            )

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
            due = [r["fact_id"] for r in self._conn.execute(
                "SELECT fact_id FROM knowledge_facts"
                " WHERE status = 'active' AND valid_until IS NOT NULL AND valid_until < ?",
                (instant,)).fetchall()]
            cur = self._conn.execute(
                "UPDATE knowledge_facts SET status = 'expired'"
                " WHERE status = 'active' AND valid_until IS NOT NULL AND valid_until < ?",
                (instant,),
            )
        for factId in due:
            self._retireDerived(factId, "推导前提已到期")
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
        self._retireDerived(factId, reason or "推导前提已撤回")

    def reviveRetracted(self, factId: str, reason: str = "") -> bool:
        """撤回过的内容被重新主张 ⇒ 同一行回到 active，历史留在活动与断言账上。

        只处理 `retracted`：那是"这条说法被收回了"，如今又有了活条目来认领它。
        `superseded` 不在此列——那意味着存在更新的说法，谁该生效是
        "改回原样"的时间语义问题（A→B→A），另立一片处理，这里不猜。
        """
        with self._lock, self._conn:
            fact = self._requireFact(factId)
            if fact["status"] != "retracted":
                return False
            self._conn.execute(
                "UPDATE knowledge_facts SET status = 'active', retracted_at = NULL"
                " WHERE fact_id = ?", (factId,))
        logger.info("事实复活 %s（%s）", factId, reason)
        return True

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
