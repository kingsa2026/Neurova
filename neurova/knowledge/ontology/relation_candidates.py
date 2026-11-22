"""未知关系候选（B8 ⑦，specs/2026-11-05 §5）：抽取出的未登记关系落审批面，不消失。

此前两层都吞：`admitExtractedFacts` 对 `custom` 直接跳过、投影只铺权威接纳的边——
模型抽出的新关系既进不了库，也没有任何一张账记着"有过这么个说法"。本模块把
未知关系变成一等对象：抽取只写候选、不写事实；批准走注册表登记并回填
`promoted_term_id`，事实仍由后续抽取经唯一咽喉落库；拒绝保留审计不删行。

去重口径：`(tenant_id, normalized_surface, source_entry_id)`——同一条目里同一词形
只记一次；不同条目重复出现是"这个词反复被用"的读数，不是噪声。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any, Dict, List, Optional
from neurova.core.time_utils import nowIso as _now
from neurova.core.tenant_scope import tenant_sql_where

_CANDIDATE_STATUSES = ("pending", "approved", "rejected")

_SCHEMA_V29_CANDIDATES = """
CREATE TABLE IF NOT EXISTS ontology_relation_candidates (
    candidate_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    surface TEXT NOT NULL,
    normalized_surface TEXT NOT NULL,
    source_entry_id TEXT NOT NULL DEFAULT '',
    source_text TEXT NOT NULL DEFAULT '',
    confidence REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    promoted_term_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_relation_candidates_review
    ON ontology_relation_candidates(tenant_id, status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_relation_candidates_dedupe
    ON ontology_relation_candidates(tenant_id, normalized_surface, source_entry_id);
"""

#: v54（对照研究 P3-1a，2026-11-19）：审批决策绑定证据内容哈希——候选生成时
#: 记下证据（source_text）的 sha256 截断，人工审批请求必须回带同一哈希，
#: 防「批准时看的 ≠ 生效时用的」。存量行（迁移前生成）为空串：不带哈希放行
#: （不阻断存量治理流），带哈希按不匹配拒。
_SCHEMA_V54_CANDIDATE_EVIDENCE = """
ALTER TABLE ontology_relation_candidates
    ADD COLUMN evidence_hash TEXT NOT NULL DEFAULT '';
"""


def normalizeSurface(text: str) -> str:
    """候选去重的词形归一口径（与 term_registry._normalizeSurface 同一规则，勿抄两份口径）。"""
    return re.sub(r"[\s\W_]+", "", str(text or "").lower())


class RelationCandidateStore:
    """`ontology_relation_candidates` 的唯一读写面。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._ensureTable()

    def _ensureTable(self) -> None:
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    def record(self, tenantId: str, surface: str, sourceEntryId: str = "",
               sourceText: str = "", confidence: Optional[float] = None) -> Optional[str]:
        """记一条候选。同 (租户, 词形, 条目) 重复时幂等跳过，返回既存 candidate_id。

        证据内容哈希（P3-1a）：sha256(source_text) 截断——审批面凭它绑定
        「批准人当时读到的证据」。
        """
        surface = str(surface or "").strip()
        if not surface:
            return None
        normalized = normalizeSurface(surface)
        if not normalized:
            return None
        tenant = str(tenantId or "default")
        evidenceHash = hashlib.sha256(
            str(sourceText or "").encode("utf-8")).hexdigest()[:16]
        with self._store._lock, self._store._conn:
            existClause, existParams = tenant_sql_where(tenant)
            existing = self._store._conn.execute(
                "SELECT candidate_id FROM ontology_relation_candidates"
                " WHERE %s AND normalized_surface = ? AND source_entry_id = ?" % existClause,
                (*existParams, normalized, str(sourceEntryId or ""))).fetchone()
            if existing:
                return existing["candidate_id"]
            candidateId = "relcand_%s" % uuid.uuid4().hex[:12]
            self._store._conn.execute(
                "INSERT INTO ontology_relation_candidates (candidate_id, tenant_id,"
                " surface, normalized_surface, source_entry_id, source_text, confidence,"
                " status, evidence_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (candidateId, tenant, surface, normalized, str(sourceEntryId or ""),
                 str(sourceText or ""), confidence, "pending", evidenceHash, _now()),
            )
        return candidateId

    def list(self, tenantId: str = "default", status: str = "pending",
             limit: int = 100) -> List[Dict[str, Any]]:
        if status not in _CANDIDATE_STATUSES:
            raise ValueError(
                "未知候选状态 %r（有效值: %s）" % (status, " / ".join(_CANDIDATE_STATUSES)))
        with self._store._lock:
            listClause, listParams = tenant_sql_where(str(tenantId or "default"))
            rows = self._store._conn.execute(
                "SELECT * FROM ontology_relation_candidates"
                " WHERE %s AND status = ?"
                " ORDER BY created_at, candidate_id LIMIT ?" % listClause,
                (*listParams, status, int(limit))).fetchall()
        return [dict(r) for r in rows]

    def approve(self, candidateId: str, tenantId: str = "default",
                reviewedBy: str = "", termRegistry: Any = None,
                evidenceHash: str = "") -> Dict[str, Any]:
        """批准：登记术语（term_id 即规范化的 surface）并回填 promoted_term_id。

        批准动作落在注册表 `register` 上——候选面只做审批流，不另造一条登记路径。
        证据哈希绑定（P3-1a）：候选带 evidence_hash 时审批请求必须回带同一哈希，
        防「批准时看的证据 ≠ 生效时用的证据」；存量空哈希行不带哈希放行。
        """
        row = self._requireCandidate(candidateId, tenantId)
        if row["status"] != "pending":
            raise ValueError("候选 %s 已是 %s 态，不能重复审批" % (candidateId, row["status"]))
        self._checkEvidenceHash(row, evidenceHash)
        termId = str(row["normalized_surface"])
        if termRegistry is not None:
            if termRegistry.term(termId, tenantId=tenantId) is None:
                termRegistry.register(termId, "relation", label=str(row["surface"]),
                                      tenantId=tenantId)
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "UPDATE ontology_relation_candidates SET status = 'approved',"
                " promoted_term_id = ?, reviewed_at = ?, reviewed_by = ?"
                " WHERE candidate_id = ?",
                (termId, _now(), str(reviewedBy or ""), candidateId))
        return self.get(candidateId, tenantId=tenantId) or {}

    def reject(self, candidateId: str, tenantId: str = "default",
               reviewedBy: str = "", evidenceHash: str = "") -> Dict[str, Any]:
        """拒绝：保留审计行不删除——"拒绝过什么"与"批准过什么"是同一本账的两面。"""
        row = self._requireCandidate(candidateId, tenantId)
        if row["status"] != "pending":
            raise ValueError("候选 %s 已是 %s 态，不能重复审批" % (candidateId, row["status"]))
        self._checkEvidenceHash(row, evidenceHash)
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "UPDATE ontology_relation_candidates SET status = 'rejected',"
                " reviewed_at = ?, reviewed_by = ? WHERE candidate_id = ?",
                (_now(), str(reviewedBy or ""), candidateId))
        return self.get(candidateId, tenantId=tenantId) or {}

    @staticmethod
    def _checkEvidenceHash(row: Dict[str, Any], evidenceHash: str) -> None:
        """证据哈希绑定（P3-1a）：有哈希的候选必须回带同值；空哈希（存量）放行。"""
        expected = str(row.get("evidence_hash") or "")
        if not expected:
            return
        if not str(evidenceHash or "").strip():
            raise ValueError(
                "候选 %s 绑定了证据哈希，审批请求必须回带 evidence_hash"
                "（防批准内容与生效内容不一致）" % row["candidate_id"])
        if str(evidenceHash).strip() != expected:
            raise ValueError(
                "候选 %s 的证据哈希不匹配：审批基于的证据已不是生成候选时的证据"
                "（expected %s, got %s）——请基于最新证据重新审阅"
                % (row["candidate_id"], expected, str(evidenceHash).strip()))

    def get(self, candidateId: str, tenantId: str = "default") -> Optional[Dict[str, Any]]:
        with self._store._lock:
            getClause, getParams = tenant_sql_where(str(tenantId or "default"))
            row = self._store._conn.execute(
                "SELECT * FROM ontology_relation_candidates"
                " WHERE %s AND candidate_id = ?" % getClause,
                (*getParams, candidateId)).fetchone()
        return dict(row) if row else None

    def _requireCandidate(self, candidateId: str, tenantId: str) -> Dict[str, Any]:
        row = self.get(candidateId, tenantId=tenantId)
        if row is None:
            raise LookupError("候选不存在: %s（租户 %s）" % (candidateId, tenantId))
        return row
