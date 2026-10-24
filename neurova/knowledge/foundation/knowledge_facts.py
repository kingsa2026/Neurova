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
from typing import Any, Dict, List, Optional, Tuple

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

# 批次 K2（断点 N2）：条目被物理清除时，断言行不能跟着删——它是审计链上的一跳，
# 删行会让 `seq` 出空洞、`ActivityDigestChain.verify` 判"链被削过"，巡检面从此常红。
# 所以擦除的落点是**正文置空 + 这一栏打标记**：摘要吃 `statement_hash` 不吃
# `statement_text`，改写正文不动任何一跳。"曾是链上跳"与"现在还在主张"是两件事，
# 置信度按独立来源数聚合，必须只数后者——来源数里留一条已经不存在的说法，
# 等于让死者替活人抬轿。
_SCHEMA_V13 = """
ALTER TABLE knowledge_assertions ADD COLUMN erased_at TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_assertion_erased ON knowledge_assertions(erased_at, fact_id);
"""

# 按知识命中的 token 归因（批次：反馈/评估剩余缺口）。一次回答命中多条事实时
# 按命中数均分；attribution 列把“均分估计”写成可读事实，不冒充逐条真实成本。
_SCHEMA_V14 = """
CREATE TABLE IF NOT EXISTS knowledge_fact_usage (
    usage_id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL,
    source_turn_id TEXT NOT NULL DEFAULT '',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    attribution TEXT NOT NULL DEFAULT 'even_split',
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fact_usage_fact ON knowledge_fact_usage(fact_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_fact_usage_turn ON knowledge_fact_usage(source_turn_id);
"""

# v15：每轮唯一 turn_id + 成本阶段。v14 的 source_turn_id 是会话级，
# 同会话第二轮会被幂等跳过；turn_id 与 (turn_id, fact_id, phase) 取代它做轮级键。
_SCHEMA_V15 = """
ALTER TABLE knowledge_fact_usage ADD COLUMN turn_id TEXT NOT NULL DEFAULT '';
ALTER TABLE knowledge_fact_usage ADD COLUMN phase TEXT NOT NULL DEFAULT 'generation';
ALTER TABLE knowledge_fact_usage ADD COLUMN model TEXT NOT NULL DEFAULT '';
ALTER TABLE knowledge_fact_usage ADD COLUMN estimated INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_usage_turn_phase
    ON knowledge_fact_usage(turn_id, fact_id, phase) WHERE turn_id <> '';
CREATE INDEX IF NOT EXISTS idx_fact_usage_phase ON knowledge_fact_usage(phase, recorded_at);
"""

# v16：每轮总量/已归因/未归因摘要。fact 行回答“分给谁”，这张表回答“这轮有多少没分出去”。
_SCHEMA_V16 = """
CREATE TABLE IF NOT EXISTS knowledge_turn_usage (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    attributed_tokens INTEGER NOT NULL DEFAULT 0,
    unattributed_tokens INTEGER NOT NULL DEFAULT 0,
    attribution TEXT NOT NULL DEFAULT 'even_split',
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turn_usage_time ON knowledge_turn_usage(recorded_at);
"""

# v17：检索侧未归因 token。检索命中里能映射到 fact 的行走 knowledge_fact_usage；
# 映射不到的文档命中不能摊到任何 fact，但成本总数不能丢，落这一列。
_SCHEMA_V17 = """
ALTER TABLE knowledge_turn_usage ADD COLUMN retrieval_unattributed_tokens INTEGER NOT NULL DEFAULT 0;
"""

# v18：无 fact lineage 的文档条目 token 账；entry 级与 fact 级分开记，
# 但轮总量新增 entry_attributed_tokens，避免文档生成 token 被当成未归因。
_SCHEMA_V18 = """
CREATE TABLE IF NOT EXISTS knowledge_entry_usage (
    usage_id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL,
    source_turn_id TEXT NOT NULL DEFAULT '',
    turn_id TEXT NOT NULL DEFAULT '',
    phase TEXT NOT NULL DEFAULT 'generation',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    attribution TEXT NOT NULL DEFAULT 'even_split',
    model TEXT NOT NULL DEFAULT '',
    estimated INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_entry_usage_turn_phase
    ON knowledge_entry_usage(turn_id, entry_id, phase) WHERE turn_id <> '';
CREATE INDEX IF NOT EXISTS idx_entry_usage_phase ON knowledge_entry_usage(phase, recorded_at);
ALTER TABLE knowledge_turn_usage ADD COLUMN entry_attributed_tokens INTEGER NOT NULL DEFAULT 0;
"""

# v19：事实变更历史与业务基线。历史只追加不覆盖，回滚也记一行；
# 基线只存事实 id 引用，不复制正文（正文仍以 knowledge_facts 为唯一权威）。
_SCHEMA_V19 = """
CREATE TABLE IF NOT EXISTS knowledge_fact_versions (
    version_id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL,
    version_no INTEGER NOT NULL,
    change_type TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    operator TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_version_no
    ON knowledge_fact_versions(fact_id, version_no);
CREATE INDEX IF NOT EXISTS idx_fact_version_fact
    ON knowledge_fact_versions(fact_id, version_no);
CREATE TABLE IF NOT EXISTS knowledge_baselines (
    baseline_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'global',
    scope_key TEXT NOT NULL DEFAULT '',
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_baseline_scope ON knowledge_baselines(scope, scope_key);
"""

# v20：租户分区。先做读隔离与写入归属；唯一索引也带 tenant，否则两个租户的
# 同一三元组会在同一 agent 下互相顶掉。活动（事件）同列，读侧按租户过滤。
_SCHEMA_V20 = """
ALTER TABLE knowledge_facts ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
DROP INDEX IF EXISTS ux_fact_triple;
CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_triple_tenant
    ON knowledge_facts(agent_id, tenant_id, subject_key, predicate_term_id, object_term, qualifier_hash);
DROP INDEX IF EXISTS ux_fact_agent_content;
CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_agent_content_tenant
    ON knowledge_facts(agent_id, tenant_id, content_key) WHERE content_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fact_tenant ON knowledge_facts(tenant_id, agent_id, status);
ALTER TABLE knowledge_activities ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
"""

# v21：事实冲突账也按租户分区；检测候选与队列读取都带 tenant。
_SCHEMA_V21 = """
ALTER TABLE knowledge_conflicts ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS idx_conflict_tenant
    ON knowledge_conflicts(tenant_id, status, detected_at);
"""

# v22：业务基线也按租户分区；基线只含引用，但引用本身也不得跨租户可读。
_SCHEMA_V22 = """
ALTER TABLE knowledge_baselines ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS idx_baseline_tenant
    ON knowledge_baselines(tenant_id, scope, created_at);
"""

# v23：主体消解字典也按租户分区。主体表只有标签/别名，不含正文，但同名主体
# 跨租户共享会让图谱投影与消解候选串租户；唯一索引一并带上 tenant。
_SCHEMA_V23 = """
ALTER TABLE knowledge_subjects ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
DROP INDEX IF EXISTS ux_subject_label;
CREATE UNIQUE INDEX IF NOT EXISTS ux_subject_label_tenant
    ON knowledge_subjects(agent_id, tenant_id, normalized_label);
CREATE INDEX IF NOT EXISTS idx_subject_tenant
    ON knowledge_subjects(tenant_id, agent_id, status);
"""

# v24：事实带条目分类，供业务基线按 category 冻结；未知分类留空，不猜。
_SCHEMA_V24 = """
ALTER TABLE knowledge_facts ADD COLUMN category TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_fact_category
    ON knowledge_facts(tenant_id, category, status);
"""

# v25：本体按租户分区（已拍板：本体归属按租户隔离）。SQLite 改不了主键，
# 两表整体重建：存量行全部归 default 租户，各租户此后各自登记各自的
# 术语/规则——同 term_id/rule_id 跨租户不再冲突，读面也不再互见。
_SCHEMA_V25 = """
CREATE TABLE ontology_terms_t25 (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    term_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    parent_term_id TEXT,
    domain_terms TEXT NOT NULL DEFAULT '[]',
    range_terms TEXT NOT NULL DEFAULT '[]',
    range_kinds TEXT NOT NULL DEFAULT '[]',
    cardinality INTEGER,
    disjoint_with TEXT NOT NULL DEFAULT '[]',
    required_props TEXT NOT NULL DEFAULT '[]',
    version TEXT NOT NULL DEFAULT 'v1',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, term_id)
);
INSERT INTO ontology_terms_t25 (tenant_id, term_id, kind, label, parent_term_id,
    domain_terms, range_terms, range_kinds, cardinality, disjoint_with,
    required_props, version, created_at, updated_at)
SELECT 'default', term_id, kind, label, parent_term_id, domain_terms,
    range_terms, COALESCE(range_kinds, '[]'), cardinality, disjoint_with,
    required_props, version, created_at, updated_at FROM ontology_terms;
DROP TABLE ontology_terms;
ALTER TABLE ontology_terms_t25 RENAME TO ontology_terms;
CREATE INDEX IF NOT EXISTS idx_ontology_parent ON ontology_terms(tenant_id, parent_term_id);
CREATE INDEX IF NOT EXISTS idx_ontology_kind ON ontology_terms(tenant_id, kind);

CREATE TABLE ontology_rules_t25 (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    rule_id TEXT NOT NULL,
    head_predicate TEXT NOT NULL,
    head_subject_var TEXT NOT NULL,
    body_json TEXT NOT NULL DEFAULT '[]',
    negated_predicates TEXT NOT NULL DEFAULT '[]',
    stratification_level INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    version TEXT NOT NULL DEFAULT 'v1',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, rule_id)
);
INSERT INTO ontology_rules_t25 (tenant_id, rule_id, head_predicate, head_subject_var,
    body_json, negated_predicates, stratification_level, enabled, version,
    created_at, updated_at)
SELECT 'default', rule_id, head_predicate, head_subject_var, body_json,
    negated_predicates, stratification_level, enabled, version, created_at,
    updated_at FROM ontology_rules;
DROP TABLE ontology_rules;
ALTER TABLE ontology_rules_t25 RENAME TO ontology_rules;
CREATE INDEX IF NOT EXISTS idx_rule_head ON ontology_rules(tenant_id, head_predicate, enabled);
"""


MANUAL_RESOLUTIONS: tuple = ("keep_both", "supersede_old", "dismiss")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _instant(value) -> Optional[str]:
    """时效判定比的是瞬时不是字面：混着 Z / +08:00 / 无时区写入时，
    文本序会把"已到期"读成"未到期"，所以进出都归一成 UTC ISO。naive 按 UTC 解读。

    「没声明时刻」一律落 `None`（空串与缺省同义），调用方不必各自再判一次空——
    判空散进各写入路径，就等于同一语义有了多份实现。
    """
    if not value:
        return None
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
        typeTermId: Optional[str] = None, tenantId: str = "default",
    ) -> str:
        normalized = normalizeLabel(label)
        if not normalized:
            raise ValueError("subject_label 不能为空")
        tenant = str(tenantId or "default")
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT subject_key, aliases_json FROM knowledge_subjects"
                " WHERE agent_id = ? AND tenant_id = ? AND normalized_label = ?",
                (agentId, tenant, normalized),
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
                ("%s|%s|%s" % (agentId, tenant, normalized)).encode("utf-8")
            ).hexdigest()[:16]
            self._conn.execute(
                "INSERT INTO knowledge_subjects (subject_key, agent_id, tenant_id,"
                " canonical_label, normalized_label, type_term_id, aliases_json,"
                " first_seen_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (key, agentId, tenant, label.strip(), normalized, typeTermId,
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

    def resolveSubjectKey(
        self, agentId: str, labelOrAlias: str, tenantId: str = "default"
    ) -> Optional[str]:
        normalized = normalizeLabel(labelOrAlias)
        tenant = str(tenantId or "default")
        with self._lock:
            row = self._conn.execute(
                "SELECT subject_key FROM knowledge_subjects"
                " WHERE agent_id = ? AND tenant_id = ? AND normalized_label = ?",
                (agentId, tenant, normalized),
            ).fetchone()
            if row is None:
                for cand in self._conn.execute(
                    "SELECT subject_key, aliases_json FROM knowledge_subjects"
                    " WHERE agent_id = ? AND tenant_id = ?",
                    (agentId, tenant),
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
            oldRow = self._conn.execute(
                "SELECT tenant_id FROM knowledge_subjects WHERE subject_key = ?", (oldKey,)
            ).fetchone()
            if oldRow is None:
                raise LookupError("源主体不存在: %s" % oldKey)
            newRow = self._conn.execute(
                "SELECT tenant_id FROM knowledge_subjects WHERE subject_key = ?", (newKey,)
            ).fetchone()
            if newRow is None:
                raise LookupError("目标主体不存在: %s" % newKey)
            if str(oldRow["tenant_id"] or "default") != str(newRow["tenant_id"] or "default"):
                raise ValueError("不能跨租户合并主体")
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

    def listSubjects(
        self, agentId: str, includeMerged: bool = False, tenantId: str = "default"
    ) -> List[Dict[str, Any]]:
        """某 agent/租户下的主体清单——消解段要拿全量做候选，不能只看精确名。"""
        sql = "SELECT * FROM knowledge_subjects WHERE agent_id = ? AND tenant_id = ?"
        params: List[Any] = [agentId, str(tenantId or "default")]
        if not includeMerged:
            sql += " AND status != 'merged'"
        with self._lock:
            rows = self._conn.execute(
                sql + " ORDER BY canonical_label, subject_key", tuple(params)
            ).fetchall()
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
        tenantId: str = "default",
        category: str = "",
    ) -> str:
        """同 (主体, 谓词, 客体, 限定) 或同 content_key 重放返回同一 fact_id。

        content_key 先查：B03 的 38 行纯冗余正是"三元组不同但内容相同"各开一行，
        口径必须是内容而不是三元组。空 key（无内容身份）不参与去重。

        时效窗口在这里落库：`admission` 的入参契约早就带着 `validFrom` / `validUntil`，
        底座表也早有这两列，中间那一跳却没收参数——于是两列永远是 NULL，
        `conflict_judge` 的 temporal 分类与 `expireDueFacts()` 双双没有输入。
        调用方声明过窗口就补进已存在的行（只补 NULL，不覆盖既有窗口）。
        """
        windowFrom = _instant(validFrom)
        windowUntil = _instant(validUntil)
        tenant = str(tenantId or "default")
        if contentKey:
            existing = self.findFactByContentKey(agentId, contentKey, tenant)
            if existing:
                self.fillValidityWindow(existing["fact_id"], windowFrom, windowUntil)
                return existing["fact_id"]
        qualifier = qualifier or {}
        qualifierHash = hashlib.sha256(
            json.dumps(qualifier, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12] if qualifier else ""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT fact_id FROM knowledge_facts WHERE agent_id = ? AND tenant_id = ?"
                " AND subject_key = ? AND predicate_term_id = ? AND object_term = ?"
                " AND qualifier_hash = ?",
                (agentId, tenant, subjectKey, predicateTermId, objectTerm, qualifierHash),
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
                if str(category or "").strip():
                    self._conn.execute(
                        "UPDATE knowledge_facts SET category = ?"
                        " WHERE fact_id = ? AND (category IS NULL OR category = '')",
                        (str(category).strip(), row["fact_id"]),
                    )
                self.fillValidityWindow(row["fact_id"], windowFrom, windowUntil)
                return row["fact_id"]
            factId = "fact_%s" % uuid.uuid4().hex[:12]
            try:
                self._conn.execute(
                    "INSERT INTO knowledge_facts (fact_id, agent_id, tenant_id, subject_key,"
                    " predicate_term_id, object_term, relation_kind, content, content_key,"
                    " qualifier_hash, qualifier_json, confidence, source_turn_id, recorded_at,"
                    " record_kind, valid_from, valid_until, category)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (factId, agentId, tenant, subjectKey, predicateTermId, objectTerm, relationKind,
                     content, contentKey, qualifierHash,
                     json.dumps(qualifier, ensure_ascii=False), confidence, sourceTurnId,
                     _instant(recordedAt) if recordedAt else _now(), recordKind,
                     windowFrom, windowUntil, str(category or "").strip()),
                )
            except sqlite3.IntegrityError:
                # 唯一索引挡住竞态双写：改读先到的那一行，而不是让写入方看到崩
                if not contentKey:
                    raise
                winner = self._conn.execute(
                    "SELECT fact_id FROM knowledge_facts WHERE agent_id = ? AND tenant_id = ?"
                    " AND content_key = ?",
                    (agentId, tenant, contentKey),
                ).fetchone()
                if winner is None:
                    raise
                return winner["fact_id"]
            self._recordVersionLocked(factId, "create", operator=sourceTurnId)
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
        verdict = _AGGREGATOR.aggregate(fact, self.liveAssertions(factId))
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

    def recordTokenUsage(
        self,
        factIds: List[str],
        promptTokens: int = 0,
        completionTokens: int = 0,
        sourceTurnId: str = "",
        turnId: str = "",
        phase: str = "generation",
        model: str = "",
        estimated: bool = False,
    ) -> int:
        """按命中事实均分一次回答的 token。

        轮级幂等优先用 `turnId`（同会话第二轮不会因 source_turn_id 相同被跳过）；
        没有 turnId 的旧调用仍按 sourceTurnId 幂等。均分是明确估计
        （attribution='even_split'），不冒充逐条真实成本。
        """
        ids = list(dict.fromkeys(str(f) for f in (factIds or []) if f))
        prompt = max(0, int(promptTokens or 0))
        completion = max(0, int(completionTokens or 0))
        if not ids or (prompt == 0 and completion == 0):
            return 0
        with self._lock, self._conn:
            if turnId:
                for factId in ids:
                    exists = self._conn.execute(
                        "SELECT 1 FROM knowledge_fact_usage"
                        " WHERE turn_id = ? AND fact_id = ? AND phase = ? LIMIT 1",
                        (str(turnId), factId, str(phase)),
                    ).fetchone()
                    if exists:
                        return 0
            elif sourceTurnId:
                exists = self._conn.execute(
                    "SELECT 1 FROM knowledge_fact_usage"
                    " WHERE source_turn_id = ? AND phase = ? LIMIT 1",
                    (str(sourceTurnId), str(phase)),
                ).fetchone()
                if exists:
                    return 0
            valid: List[str] = []
            for factId in ids:
                try:
                    self._requireFact(factId)
                    valid.append(factId)
                except LookupError:
                    continue
            if not valid:
                return 0
            n = len(valid)
            pBase, pRem = divmod(prompt, n)
            cBase, cRem = divmod(completion, n)
            stamp = _now()
            for index, factId in enumerate(valid):
                p = pBase + (1 if index < pRem else 0)
                c = cBase + (1 if index < cRem else 0)
                self._conn.execute(
                    "INSERT INTO knowledge_fact_usage (usage_id, fact_id, source_turn_id,"
                    " prompt_tokens, completion_tokens, total_tokens, attribution, recorded_at,"
                    " turn_id, phase, model, estimated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("kus_%s" % uuid.uuid4().hex[:12], factId, str(sourceTurnId),
                     p, c, p + c, "even_split", stamp,
                     str(turnId), str(phase), str(model), int(bool(estimated))),
                )
            if turnId and phase == "generation":
                self._recordTurnUsage(
                    turnId, sourceTurnId, model, prompt, completion,
                    prompt + completion, 0, "even_split",
                )
        return len(valid)

    def _recordTurnUsage(
        self, turnId: str, sessionId: str, model: str,
        prompt: int, completion: int, attributed: int,
        unattributed: int, attribution: str,
        retrievalUnattributed: int = 0,
    ) -> None:
        if not turnId:
            return
        self._conn.execute(
            "INSERT INTO knowledge_turn_usage"
            " (turn_id, session_id, model, prompt_tokens, completion_tokens,"
            " attributed_tokens, unattributed_tokens, attribution,"
            " retrieval_unattributed_tokens, recorded_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(turn_id) DO UPDATE SET"
            " session_id = excluded.session_id, model = excluded.model,"
            " prompt_tokens = excluded.prompt_tokens,"
            " completion_tokens = excluded.completion_tokens,"
            " attributed_tokens = excluded.attributed_tokens,"
            " unattributed_tokens = excluded.unattributed_tokens,"
            " attribution = excluded.attribution",
            (str(turnId), str(sessionId), str(model), int(prompt), int(completion),
             int(attributed), int(unattributed), str(attribution),
             max(0, int(retrievalUnattributed)), _now()),
        )

    def recordRetrievalUnattributed(
        self,
        turnId: str,
        tokens: int,
        *,
        sessionId: str = "",
        model: str = "",
    ) -> int:
        """记检索侧未归因 token（无生成行时也立行）；返回写入的 token 数。"""
        count = max(0, int(tokens or 0))
        if not turnId or count <= 0:
            return 0
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO knowledge_turn_usage"
                " (turn_id, session_id, model, recorded_at, retrieval_unattributed_tokens)"
                " VALUES (?,?,?,?,?)",
                (str(turnId), str(sessionId), str(model), _now(), count),
            )
            self._conn.execute(
                "UPDATE knowledge_turn_usage SET retrieval_unattributed_tokens = ?,"
                " session_id = CASE WHEN session_id = '' THEN ? ELSE session_id END,"
                " model = CASE WHEN model = '' THEN ? ELSE model END"
                " WHERE turn_id = ?",
                (count, str(sessionId), str(model), str(turnId)),
            )
        return count

    def recordEntryTokenUsage(
        self,
        entryIds: List[str],
        promptTokens: int = 0,
        completionTokens: int = 0,
        sourceTurnId: str = "",
        turnId: str = "",
        phase: str = "generation",
        model: str = "",
        estimated: bool = False,
    ) -> int:
        """文档条目的均分 token 账；与 fact 表分表，轮级幂等键相同。"""
        ids = list(dict.fromkeys(str(e) for e in (entryIds or []) if e))
        prompt = max(0, int(promptTokens or 0))
        completion = max(0, int(completionTokens or 0))
        if not ids or (prompt == 0 and completion == 0):
            return 0
        with self._lock, self._conn:
            if turnId:
                for entryId in ids:
                    exists = self._conn.execute(
                        "SELECT 1 FROM knowledge_entry_usage"
                        " WHERE turn_id = ? AND entry_id = ? AND phase = ? LIMIT 1",
                        (str(turnId), entryId, str(phase)),
                    ).fetchone()
                    if exists:
                        return 0
            n = len(ids)
            pBase, pRem = divmod(prompt, n)
            cBase, cRem = divmod(completion, n)
            stamp = _now()
            for index, entryId in enumerate(ids):
                p = pBase + (1 if index < pRem else 0)
                c = cBase + (1 if index < cRem else 0)
                self._conn.execute(
                    "INSERT INTO knowledge_entry_usage (usage_id, entry_id, source_turn_id,"
                    " turn_id, phase, prompt_tokens, completion_tokens, total_tokens,"
                    " attribution, model, estimated, recorded_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("kes_%s" % uuid.uuid4().hex[:12], entryId, str(sourceTurnId),
                     str(turnId), str(phase), p, c, p + c, "even_split",
                     str(model), int(bool(estimated)), stamp),
                )
        return len(ids)

    def _recordEntryTurnAttribution(
        self, turnId: str, sessionId: str, model: str, attributed: int
    ) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO knowledge_turn_usage"
            " (turn_id, session_id, model, recorded_at) VALUES (?,?,?,?)",
            (str(turnId), str(sessionId), str(model), _now()),
        )
        self._conn.execute(
            "UPDATE knowledge_turn_usage SET entry_attributed_tokens = ?"
            " WHERE turn_id = ?",
            (max(0, int(attributed)), str(turnId)),
        )

    def recordEntryTokenUsageAllocations(
        self,
        turnId: str,
        allocations: Dict[str, Tuple[int, int]],
        *,
        promptTokens: int,
        completionTokens: int,
        sourceTurnId: str = "",
        model: str = "",
        estimated: bool = False,
        attribution: str = "even_split",
    ) -> int:
        """文档条目的生成 token 分摊；差额由调用方的轮总量统一收口。"""
        if not turnId:
            return 0
        prompt = max(0, int(promptTokens or 0))
        completion = max(0, int(completionTokens or 0))
        with self._lock, self._conn:
            exists = self._conn.execute(
                "SELECT 1 FROM knowledge_entry_usage"
                " WHERE turn_id = ? AND phase = 'generation' LIMIT 1",
                (str(turnId),),
            ).fetchone()
            if exists:
                return 0
            valid: Dict[str, Tuple[int, int]] = {
                str(entryId): (max(0, int(p or 0)), max(0, int(c or 0)))
                for entryId, (p, c) in (allocations or {}).items()
                if str(entryId)
            }
            stamp = _now()
            attributed = 0
            for entryId, (p, c) in valid.items():
                self._conn.execute(
                    "INSERT INTO knowledge_entry_usage (usage_id, entry_id, source_turn_id,"
                    " turn_id, phase, prompt_tokens, completion_tokens, total_tokens,"
                    " attribution, model, estimated, recorded_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("kes_%s" % uuid.uuid4().hex[:12], entryId, str(sourceTurnId),
                     str(turnId), "generation", p, c, p + c, str(attribution),
                     str(model), int(bool(estimated)), stamp),
                )
                attributed += p + c
            if attributed:
                self._recordEntryTurnAttribution(
                    turnId, sourceTurnId, model, attributed
                )
        return len(valid)

    def recordTokenUsageAllocations(
        self,
        turnId: str,
        allocations: Dict[str, Tuple[int, int]],
        *,
        promptTokens: int,
        completionTokens: int,
        sourceTurnId: str = "",
        model: str = "",
        estimated: bool = False,
        attribution: str = "even_split",
        additionalAttributed: int = 0,
    ) -> int:
        """按给定 fact→(prompt, completion) 分摊写账；差额进 unattributed。

        与 recordTokenUsage 的均分路径互斥：同一 (turn_id, phase=generation)
        已有行即幂等返回；不把未归因部分硬塞给某条事实。
        """
        if not turnId:
            return 0
        prompt = max(0, int(promptTokens or 0))
        completion = max(0, int(completionTokens or 0))
        with self._lock, self._conn:
            exists = self._conn.execute(
                "SELECT 1 FROM knowledge_turn_usage WHERE turn_id = ? LIMIT 1",
                (str(turnId),),
            ).fetchone()
            if exists:
                return 0
            valid: Dict[str, Tuple[int, int]] = {}
            for factId, (p, c) in (allocations or {}).items():
                try:
                    self._requireFact(str(factId))
                except LookupError:
                    continue
                valid[str(factId)] = (max(0, int(p or 0)), max(0, int(c or 0)))
            stamp = _now()
            attributed = 0
            for factId, (p, c) in valid.items():
                self._conn.execute(
                    "INSERT INTO knowledge_fact_usage (usage_id, fact_id, source_turn_id,"
                    " prompt_tokens, completion_tokens, total_tokens, attribution, recorded_at,"
                    " turn_id, phase, model, estimated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("kus_%s" % uuid.uuid4().hex[:12], factId, str(sourceTurnId),
                     p, c, p + c, str(attribution), stamp,
                     str(turnId), "generation", str(model), int(bool(estimated))),
                )
                attributed += p + c
            total = prompt + completion
            self._recordTurnUsage(
                turnId, sourceTurnId, model, prompt, completion,
                attributed,
                max(0, total - attributed - max(0, int(additionalAttributed or 0))),
                attribution,
            )
        return len(valid)

    def tokenUsageMetrics(self, limit: int = 20) -> Dict[str, Any]:
        """按事实聚合的归因 token；均分口径随读数一起返回。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS events,"
                " COUNT(DISTINCT COALESCE(NULLIF(turn_id, ''), source_turn_id)) AS turns,"
                " COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,"
                " COALESCE(SUM(completion_tokens), 0) AS completion_tokens,"
                " COALESCE(SUM(total_tokens), 0) AS total_tokens"
                " FROM knowledge_fact_usage"
            ).fetchone()
            top = self._conn.execute(
                "SELECT fact_id, SUM(total_tokens) AS total_tokens, COUNT(*) AS events"
                " FROM knowledge_fact_usage GROUP BY fact_id"
                " ORDER BY total_tokens DESC, fact_id LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            phases = self._conn.execute(
                "SELECT phase, SUM(total_tokens) AS total_tokens, COUNT(*) AS events"
                " FROM knowledge_fact_usage GROUP BY phase ORDER BY phase"
            ).fetchall()
            attrs = self._conn.execute(
                "SELECT attribution, COUNT(*) AS events, SUM(total_tokens) AS total_tokens"
                " FROM knowledge_fact_usage GROUP BY attribution ORDER BY attribution"
            ).fetchall()
            turn = self._conn.execute(
                "SELECT COUNT(*) AS turns,"
                " COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,"
                " COALESCE(SUM(completion_tokens), 0) AS completion_tokens,"
                " COALESCE(SUM(attributed_tokens), 0) AS attributed_tokens,"
                " COALESCE(SUM(unattributed_tokens), 0) AS unattributed_tokens,"
                " COALESCE(SUM(entry_attributed_tokens), 0) AS entry_attributed_tokens,"
                " COALESCE(SUM(retrieval_unattributed_tokens), 0)"
                " AS retrieval_unattributed_tokens"
                " FROM knowledge_turn_usage"
            ).fetchone()
            retrieval_attributed = int(self._conn.execute(
                "SELECT COALESCE(SUM(total_tokens), 0) AS total FROM knowledge_fact_usage"
                " WHERE phase = 'retrieval'"
            ).fetchone()["total"] or 0)
            entry_retrieval_attributed = int(self._conn.execute(
                "SELECT COALESCE(SUM(total_tokens), 0) AS total FROM knowledge_entry_usage"
                " WHERE phase = 'retrieval'"
            ).fetchone()["total"] or 0)
            entry_row = self._conn.execute(
                "SELECT COUNT(*) AS events,"
                " COUNT(DISTINCT COALESCE(NULLIF(turn_id, ''), source_turn_id)) AS turns,"
                " COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,"
                " COALESCE(SUM(completion_tokens), 0) AS completion_tokens,"
                " COALESCE(SUM(total_tokens), 0) AS total_tokens"
                " FROM knowledge_entry_usage"
            ).fetchone()
            entry_phases = self._conn.execute(
                "SELECT phase, SUM(total_tokens) AS total_tokens, COUNT(*) AS events"
                " FROM knowledge_entry_usage GROUP BY phase ORDER BY phase"
            ).fetchall()
            entry_top = self._conn.execute(
                "SELECT entry_id, SUM(total_tokens) AS total_tokens, COUNT(*) AS events"
                " FROM knowledge_entry_usage GROUP BY entry_id"
                " ORDER BY total_tokens DESC, entry_id LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            estimated = self._conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN estimated = 1 THEN total_tokens ELSE 0 END), 0)"
                " AS estimated_tokens, COALESCE(SUM(total_tokens), 0) AS total_tokens"
                " FROM knowledge_fact_usage"
            ).fetchone()
        attributions = [r["attribution"] for r in attrs]
        turn_total = int(turn["prompt_tokens"] or 0) + int(turn["completion_tokens"] or 0)
        fact_total = int(estimated["total_tokens"] or 0)
        return {
            "events": int(row["events"] or 0),
            "turns": int(row["turns"] or 0),
            "prompt_tokens": int(row["prompt_tokens"] or 0),
            "completion_tokens": int(row["completion_tokens"] or 0),
            "attributed_total_tokens": int(row["total_tokens"] or 0),
            "attribution": (
                attributions[0] if len(attributions) == 1
                else ("mixed" if attributions else None)
            ),
            "by_fact": [dict(r) for r in top],
            "by_phase": [dict(r) for r in phases],
            "attribution_breakdown": [dict(r) for r in attrs],
            "turn_totals": {
                "turns": int(turn["turns"] or 0),
                "prompt_tokens": int(turn["prompt_tokens"] or 0),
                "completion_tokens": int(turn["completion_tokens"] or 0),
                "attributed_tokens": int(turn["attributed_tokens"] or 0),
                "unattributed_tokens": int(turn["unattributed_tokens"] or 0),
                "entry_attributed_tokens": int(turn["entry_attributed_tokens"] or 0),
                "unattributed_share": (
                    round(int(turn["unattributed_tokens"] or 0) / turn_total, 6)
                    if turn_total else None
                ),
                "retrieval_unattributed_tokens": int(
                    turn["retrieval_unattributed_tokens"] or 0
                ),
                "retrieval_unattributed_share": (
                    round(
                        int(turn["retrieval_unattributed_tokens"] or 0)
                        / (retrieval_attributed + entry_retrieval_attributed
                           + int(turn["retrieval_unattributed_tokens"] or 0)),
                        6,
                    )
                    if (retrieval_attributed + entry_retrieval_attributed
                        + int(turn["retrieval_unattributed_tokens"] or 0))
                    else None
                ),
            },
            "entry_usage": {
                "events": int(entry_row["events"] or 0),
                "turns": int(entry_row["turns"] or 0),
                "prompt_tokens": int(entry_row["prompt_tokens"] or 0),
                "completion_tokens": int(entry_row["completion_tokens"] or 0),
                "total_tokens": int(entry_row["total_tokens"] or 0),
                "by_entry": [dict(r) for r in entry_top],
                "by_phase": [dict(r) for r in entry_phases],
            },
            "estimated_token_share": (
                round(int(estimated["estimated_tokens"] or 0) / fact_total, 6)
                if fact_total else None
            ),
        }

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
            # 一条回执都没有时，读数必须自带成因，不能只留一个 0。
            # 写入面现已接两条：/chat/feedback（服务端 lineage）与
            # /knowledge/facts/{id}/adoption（显式管理端）。因此 0 的含义是
            # “尚未发生回写”，不是“写面未接线”，更不是“没人采纳”。
            **({
                "missing_reason": (
                    "outcome_written=0：全库没有一条采纳回执。写入面已接"
                    "（/chat/feedback 按服务端 lineage、/knowledge/facts/{id}/adoption 显式）；"
                    "这个 0 表示尚未发生回写，不等于「没人采纳」。"
                )
            } if int(row["never_written"] or 0) == total else {}),
        }

    def searchableFacts(
        self, agentId: Optional[str] = None, includeNarratives: bool = False,
        tenantId: str = "default",
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
        params: List[Any] = [_now(), str(tenantId or "default")]
        sql += " AND f.tenant_id = ?"
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

    def findFactByContentKey(
        self, agentId: str, contentKey: str, tenantId: str = "default"
    ) -> Optional[Dict[str, Any]]:
        """按内容键找该行（含已被取代的）。

        刻意不过滤 status：一旦只看 active，"折叠"就变成裁决顺序的函数——回放里某行被
        自动取代后，同内容会另开一行，静态预测与实跑当场对不上（实测 92 vs 102）。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_facts WHERE agent_id = ? AND tenant_id = ?"
                " AND content_key = ? LIMIT 1",
                (agentId, str(tenantId or "default"), contentKey),
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
        basis: str = "", toolVersion: str = "", tenantId: str = "default",
    ) -> str:
        activityId = "act_%s" % uuid.uuid4().hex[:12]
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO knowledge_activities (activity_id, activity_kind, started_at,"
                " inputs_json, basis, tool_version, tenant_id) VALUES (?,?,?,?,?,?,?)",
                (activityId, kind, _now(),
                 json.dumps(inputs or {}, ensure_ascii=False, sort_keys=True), basis, toolVersion,
                 str(tenantId or "default")),
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

    def liveAssertions(self, factId: str) -> List[Dict[str, Any]]:
        """只回仍在主张这行的断言——已擦除的那跳留在链上，但不再是一个来源。

        与 `assertions()` 分开，是因为两批读者要的是不同的东西：溯源面必须看得见
        "谁曾经主张过"（擦除不是遗忘的借口），而置信度聚合数的是"现在有几路在说"。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM knowledge_assertions WHERE fact_id = ?"
                " AND erased_at = '' ORDER BY asserted_at, assertion_id",
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
        winnerFactId: Optional[str] = None, tenantId: str = "default",
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
                " recommended_policy, policy_basis, status, detected_at, winner_fact_id,"
                " tenant_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (conflictId, kind, subjectKey, predicateTermId,
                 json.dumps(members, ensure_ascii=False), "|".join(members), float(severity),
                 recommendedPolicy, policyBasis, status, _now(), winnerFactId,
                 str(tenantId or "default")),
            )
        return conflictId if cur.rowcount else None

    def conflict(
        self, conflictId: str, tenantId: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_conflicts WHERE conflict_id = ?",
                (str(conflictId or ""),),
            ).fetchone()
        if row is None:
            return None
        rec = self._hydrateConflict(row)
        if tenantId is not None and str(rec.get("tenant_id") or "default") != str(
            tenantId or "default"
        ):
            return None
        return rec

    def conflicts(
        self, status: str = "pending", tenantId: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM knowledge_conflicts WHERE status = ?"
        params: List[Any] = [status]
        if tenantId is not None:
            sql += " AND tenant_id = ?"
            params.append(str(tenantId or "default"))
        sql += " ORDER BY severity DESC, detected_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
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

    def candidateFactsForConflict(
        self, subjectLabel: str, predicateTermId: str, tenantId: str = "default"
    ) -> List[Dict[str, Any]]:
        """按归一化标签跨 agent 取候选。

        旧实现只在同 agent 桶内比对（`repository.py:1119`），跨库分歧因此永远不成账。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT f.*, s.agent_id AS subject_agent_id, s.canonical_label,"
                " s.normalized_label FROM knowledge_facts f"
                " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
                " WHERE s.normalized_label = ? AND f.predicate_term_id = ?"
                " AND f.tenant_id = ?"
                " AND s.merged_into IS NULL AND f.status != 'retracted'"
                " ORDER BY f.recorded_at, f.fact_id",
                (normalizeLabel(subjectLabel), predicateTermId, str(tenantId or "default")),
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

    # ── 版本历史与回滚（v19）─────────────────────────────────────
    # 历史只追加：每次写路径变化落一行快照，回滚本身也落一行。
    # 回读只认 knowledge_facts（正文唯一权威），历史表不参与检索。

    _VERSION_RESTORE_FIELDS = (
        "subject_key", "predicate_term_id", "object_term", "relation_kind", "content",
        "content_key", "qualifier_hash", "qualifier_json", "confidence", "evidence_state",
        "status", "supersedes_fact_id", "contradicted_by_json", "valid_from", "valid_until",
        "retracted_at", "assertions_json", "assertion_count", "record_kind",
    )

    def _recordVersionLocked(
        self, factId: str, changeType: str, *, operator: str = "", reason: str = ""
    ) -> int:
        """调用方必须已持有 `self._lock` 与事务（`with self._conn`）。"""
        snapshot = self._conn.execute(
            "SELECT * FROM knowledge_facts WHERE fact_id = ?", (factId,)
        ).fetchone()
        if snapshot is None:
            raise LookupError("事实不存在: %s" % factId)
        row = self._conn.execute(
            "SELECT COALESCE(MAX(version_no), 0) FROM knowledge_fact_versions WHERE fact_id = ?",
            (factId,),
        ).fetchone()
        versionNo = int(row[0] or 0) + 1
        self._conn.execute(
            "INSERT INTO knowledge_fact_versions (version_id, fact_id, version_no,"
            " change_type, snapshot_json, operator, reason, recorded_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            ("fv_%s" % uuid.uuid4().hex[:12], factId, versionNo, changeType,
             json.dumps(dict(snapshot), ensure_ascii=False, sort_keys=True),
             operator or "", reason or "", _now()),
        )
        return versionNo

    def history(
        self, factId: str, limit: Optional[int] = None, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """事实版本历史，最新在前。

        **默认返回全量**：历史是溯源事实源，不靠默认分页截断。调用方要分页时
        显式给 limit/offset；事实不存在时抛 LookupError（空历史不等于没事实）。
        """
        params: List[Any] = [factId]
        sql = ("SELECT * FROM knowledge_fact_versions WHERE fact_id = ?"
               " ORDER BY version_no DESC")
        if limit is not None and int(limit) > 0:
            sql += " LIMIT ? OFFSET ?"
            params.extend([int(limit), max(0, int(offset))])
        with self._lock:
            self._requireFact(factId)
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        out = []
        for row in rows:
            entry = dict(row)
            try:
                entry["snapshot"] = json.loads(entry.pop("snapshot_json") or "{}")
            except (ValueError, TypeError):
                # 快照坏掉不伪装成空：原样保留字符串，让读方看得见
                entry["snapshot"] = {}
            out.append(entry)
        return out

    def historyCount(self, factId: str) -> int:
        with self._lock:
            self._requireFact(factId)
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM knowledge_fact_versions WHERE fact_id = ?",
                (factId,),
            ).fetchone()[0])

    def rollback(
        self, factId: str, versionNo: int, *, operator: str, reason: str
    ) -> Dict[str, Any]:
        """把事实恢复到指定版本，并追加一行 rollback 历史。理由与操作人必填。

        语义边界（本轮拍板：只恢复目标事实）：不回滚推导账本，也不会自动复活
        已被 `_retireDerived` 撤下的派生事实。派生结论要恢复须重跑推导规则，
        避免"回滚一条前提却悄悄唤醒一串结论"的隐式级联。
        """
        if not str(operator or "").strip() or not str(reason or "").strip():
            raise ValueError("回滚必须记录操作人与依据")
        with self._lock, self._conn:
            self._requireFact(factId)
            row = self._conn.execute(
                "SELECT snapshot_json FROM knowledge_fact_versions"
                " WHERE fact_id = ? AND version_no = ?",
                (factId, int(versionNo)),
            ).fetchone()
            if row is None:
                raise LookupError("版本不存在: %s@%s" % (factId, versionNo))
            try:
                snapshot = json.loads(row["snapshot_json"] or "{}")
            except (ValueError, TypeError) as exc:
                raise ValueError("版本快照不可解析: %s@%s" % (factId, versionNo)) from exc
            fields = [name for name in self._VERSION_RESTORE_FIELDS if name in snapshot]
            if not fields:
                raise ValueError("版本快照没有可恢复字段: %s@%s" % (factId, versionNo))
            self._conn.execute(
                "UPDATE knowledge_facts SET %s WHERE fact_id = ?"
                % ", ".join("%s = ?" % name for name in fields),
                tuple(snapshot[name] for name in fields) + (factId,),
            )
            self._recordVersionLocked(
                factId, "rollback", operator=operator, reason=reason
            )
            restored = self._requireFact(factId)
        logger.info("事实回滚 %s → v%s（%s: %s）", factId, versionNo, operator, reason)
        return restored

    # ── 业务基线：只冻结引用，不复制正文 ──────────────────────────

    def createBaseline(
        self,
        *,
        scope: str = "global",
        scopeKey: str = "",
        factIds: Optional[List[str]] = None,
        createdBy: str = "",
        reason: str = "",
        tenantId: str = "default",
        timeFrom: Optional[str] = None,
        timeTo: Optional[str] = None,
        category: str = "",
    ) -> Dict[str, Any]:
        scope = str(scope or "global").strip() or "global"
        tenant = str(tenantId or "default")
        with self._lock, self._conn:
            if factIds is None:
                sql = "SELECT fact_id FROM knowledge_facts WHERE status = 'active'"
                params: List[Any] = []
                if scopeKey:
                    sql += " AND agent_id = ?"
                    params.append(scopeKey)
                sql += " AND tenant_id = ?"
                params.append(tenant)
                if timeFrom:
                    sql += " AND recorded_at >= ?"
                    params.append(_instant(timeFrom))
                if timeTo:
                    sql += " AND recorded_at <= ?"
                    params.append(_instant(timeTo))
                if str(category or "").strip():
                    sql += " AND category = ?"
                    params.append(str(category).strip())
                factIds = [r["fact_id"] for r in self._conn.execute(sql, tuple(params)).fetchall()]
            ids = sorted({str(fid) for fid in factIds if fid})
            if ids:
                placeholders = ",".join("?" * len(ids))
                foreign = self._conn.execute(
                    "SELECT COUNT(*) FROM knowledge_facts WHERE fact_id IN (%s)"
                    " AND tenant_id != ?" % placeholders,
                    tuple(ids) + (tenant,),
                ).fetchone()[0]
                if foreign:
                    raise ValueError("基线包含其他租户的事实引用，拒绝冻结")
            baselineId = "kb_%s" % uuid.uuid4().hex[:12]
            snapshot = {
                "fact_ids": ids, "count": len(ids),
                "time_from": _instant(timeFrom), "time_to": _instant(timeTo),
            }
            self._conn.execute(
                "INSERT INTO knowledge_baselines (baseline_id, scope, scope_key,"
                " snapshot_json, created_by, reason, created_at, tenant_id)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (baselineId, scope, str(scopeKey or ""),
                 json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                 str(createdBy or ""), str(reason or ""), _now(), tenant),
            )
        return {
            "baseline_id": baselineId,
            "scope": scope,
            "scope_key": str(scopeKey or ""),
            "fact_count": len(ids),
            "created_by": str(createdBy or ""),
            "reason": str(reason or ""),
        }

    def listBaselines(
        self, scope: Optional[str] = None, tenantId: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if scope:
            clauses.append("scope = ?")
            params.append(str(scope))
        if tenantId is not None:
            clauses.append("tenant_id = ?")
            params.append(str(tenantId or "default"))
        sql = "SELECT * FROM knowledge_baselines"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        out = []
        for row in rows:
            entry = dict(row)
            snapshot = json.loads(entry.pop("snapshot_json") or "{}")
            entry["fact_count"] = snapshot.get("count", 0)
            entry["fact_ids"] = snapshot.get("fact_ids", [])
            out.append(entry)
        return out

    def baseline(self, baselineId: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_baselines WHERE baseline_id = ?", (baselineId,)
            ).fetchone()
        if row is None:
            return None
        entry = dict(row)
        entry["snapshot"] = json.loads(entry.pop("snapshot_json") or "{}")
        return entry

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
            self._recordVersionLocked(newFactId, "supersede", reason=reason)
            self._recordVersionLocked(oldFactId, "supersede", reason=reason)
        logger.info("事实取代 %s ← %s（%s）", newFactId, oldFactId, reason)
        self._retireDerived(oldFactId, reason or "推导前提已被取代")

    def fillValidityWindow(self, factId: str, validFrom: Optional[str],
                           validUntil: Optional[str]) -> None:
        """补窗口只填 NULL——既有窗口是已成立的时效声明，重放不得把它改写掉。

        咽喉的两条路径都调它：新建行走 `upsertFact`，按内容键折回旧行时走这里。
        同一个方法，不各写一套"只补空"的判据。

        窗口→瞬时的转换只走 `_instant`，与新建路径同一实现：库列上的比较是文本序，
        而同一个瞬时有无穷多种合法写法，混着落库就会出现「`20:00+08:00` 与
        `12:00+00:00` 是同一瞬时、却不是同一串」——读面按文本序判真假，会把"已到期"
        读成"未到期"。此前折回路径把调用方原样字符串直接落库、只有新建路径归一，
        于是同一句事实的窗口随"哪条路径先写"而变。
        """
        windowFrom = _instant(validFrom)
        windowUntil = _instant(validUntil)
        if windowFrom is None and windowUntil is None:
            return
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE knowledge_facts SET"
                " valid_from = COALESCE(valid_from, ?),"
                " valid_until = COALESCE(valid_until, ?)"
                " WHERE fact_id = ?",
                (windowFrom, windowUntil, factId),
            )

    def setValidUntil(self, factId: str, validUntil: Optional[str]) -> None:
        stored = _instant(validUntil)
        with self._lock, self._conn:
            self._requireFact(factId)
            self._conn.execute(
                "UPDATE knowledge_facts SET valid_until = ? WHERE fact_id = ?",
                (stored, factId),
            )

    def expireDueFacts(
        self, now: Optional[str] = None, tenantId: Optional[str] = None
    ) -> int:
        instant = _instant(now) if now is not None else _now()
        tenantSql = ""
        params: List[Any] = [instant]
        if tenantId is not None:
            tenantSql = " AND tenant_id = ?"
            params.append(str(tenantId or "default"))
        with self._lock, self._conn:
            due = [r["fact_id"] for r in self._conn.execute(
                "SELECT fact_id FROM knowledge_facts"
                " WHERE status = 'active' AND valid_until IS NOT NULL AND valid_until < ?"
                + tenantSql,
                tuple(params)).fetchall()]
            cur = self._conn.execute(
                "UPDATE knowledge_facts SET status = 'expired'"
                " WHERE status = 'active' AND valid_until IS NOT NULL AND valid_until < ?"
                + tenantSql,
                tuple(params),
            )
            for factId in due:
                self._recordVersionLocked(factId, "expire", reason="valid_until 到期")
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
            self._recordVersionLocked(factId, "retract", reason=reason)
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
            self._recordVersionLocked(factId, "revive", reason=reason)
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
