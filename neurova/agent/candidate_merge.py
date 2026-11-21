# -*- coding: utf-8 -*-
"""S4 结果候选制：member 产出先落候选，主侧 CAS 合入，冲突保留升级（B5 机制）。

机制形态："Subagent 私有 candidate → Main CAS 合入，人工可拦截，冲突保留
重议"：改前本仓的成员报告直传即成结果、integrationReport 只做核对——缺"候选→
合并"这道闸。现在：

- member 结果回传 → 先落 :class:`CandidateReport`（status=submitted），**不直接
  定案**；
- 既有验收门/评审门通过后，主侧 :meth:`CandidateMergeBoard.mergeCandidate` 按
  **CAS** 合入：候选的 ``baseRevision`` 与集成板当前 ``revision`` 一致才合入，
  不一致判冲突；
- 两个候选声明同一 ``artifactKey`` 且 ``baseRevision`` 相同 → 双方都保留、标记
  conflict，经 escalate/审批链升级人工裁决，**绝不静默覆盖**；
- 验收驳回 → 候选置 reviseRequired，走既有回炉链（不新造第二套验收判定器）；
- merge 动作经既有审批链分级（默认 L0 自动放行留痕，env 可调 L1/L2）。

本模块只做候选板与合入判定的纯逻辑（线程安全，RLock）；升级投递、事件归档、
审批链调用由 swarm 侧包装完成——这里不 import swarm（避免环），也不落盘
（候选的持久留痕走 H-4 run 事件账本：candidate_submitted/merged/conflict）。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 候选状态域：submitted（在途）→ accepted（已合入）/ rejected（人工否决）/
#: reviseRequired（验收驳回，回炉后可 resubmit 重新进入 submitted）
CANDIDATE_SUBMITTED = "submitted"
CANDIDATE_ACCEPTED = "accepted"
CANDIDATE_REJECTED = "rejected"
CANDIDATE_REVISE_REQUIRED = "reviseRequired"
CANDIDATE_STATUSES = frozenset({
    CANDIDATE_SUBMITTED, CANDIDATE_ACCEPTED, CANDIDATE_REJECTED, CANDIDATE_REVISE_REQUIRED,
})


class CandidateMergeError(Exception):
    """候选合入的常规失败（候选不存在/状态不允许/重复合入）。"""


class CandidateConflictError(CandidateMergeError):
    """CAS 冲突：候选基准版本与集成板当前版本不一致（或同 key 同基准撞车）。

    冲突**不覆盖任何一方**：双方候选都保留在板上，由调用方升级人工裁决。
    """

    def __init__(self, message: str, candidateId: str = "",
                 conflictWith: Optional[List[str]] = None):
        super().__init__(message)
        self.candidateId = str(candidateId or "")
        self.conflictWith = list(conflictWith or [])


@dataclass
class CandidateReport:
    """一份成员结果候选：合入前只是"主张"，合入后才成为集成事实。"""

    candidateId: str
    runId: str
    content: str  # 报告正文（全文在 member 会话；板上存定稿引用）
    artifactKeys: List[str] = field(default_factory=list)  # 主张触碰的产物/记忆键
    baseRevision: int = 0  # 提交时所见的集成版本（CAS 比较基准）
    status: str = CANDIDATE_SUBMITTED
    conflictWith: List[str] = field(default_factory=list)  # 冲突对象 candidateId（都保留）
    note: str = ""  # 驳回原因 / 冲突说明
    createdAt: float = field(default_factory=time.time)
    decidedAt: float = 0.0

    def toDict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidateId,
            "run_id": self.runId,
            "content": self.content,
            "artifact_keys": list(self.artifactKeys),
            "base_revision": self.baseRevision,
            "status": self.status,
            "conflict_with": list(self.conflictWith),
            "note": self.note,
            "created_at": self.createdAt,
            "decided_at": self.decidedAt,
        }


def artifactKeysFromOwnership(ownership: str) -> List[str]:
    """TaskUnit.artifactOwnership 自由文本 → 产物/记忆键列表。

    任务书里 artifactOwnership 是人写的一段话（如 ``"docs/api.md、记忆:auth"``），
    这里按中英文常见分隔符切键、去空白；解析不出分隔符时整段作一个键——
    键的意义是"主张触碰面"，粗粒度不漏报比精确更重要。
    """
    import re

    text = str(ownership or "").strip()
    if not text:
        return []
    pieces = re.split(r"[,;、；\n]+", text)
    keys = [p.strip() for p in pieces if p.strip()]
    return keys or [text]


class CandidateMergeBoard:
    """结果候选板：提交（submitted）→ CAS 合入（accepted）/ 驳回 / 冲突保留。

    revision 是集成版本的单源计数：每次合入 +1；候选提交时以当时的 revision
    作为 ``baseRevision``——合入时二者不一致即说明集成面已被别人推进（CAS 失败）。

    M7（修复计划 2026-11-21，拍板乙）：传 ``db_path`` 时整板落 SQLite（WAL，
    跨进程可见）——候选（含正文）与集成版本重启/跨进程均在，多副本部署下
    CAS 判定权随库；不传时保持进程内内存形态（单测零污染）。两种形态同一份
    判定逻辑与同一套公开接口。
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = str(db_path or "").strip()
        self._candidates: Dict[str, CandidateReport] = {}
        self._revision: int = 0
        self._lock = threading.RLock()
        self._conn: Any = None
        if self._db_path:
            self._initDb()

    # ── SQLite 形态（M7） ──────────────────────────────────────────────

    def _initDb(self) -> None:
        import json as _json
        import os as _os
        import sqlite3 as _sqlite3

        self._json = _json
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = _sqlite3.connect(self._db_path, check_same_thread=False, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
        except _sqlite3.Error:
            pass
        conn.execute(
            "CREATE TABLE IF NOT EXISTS swarm_board_meta ("
            " id INTEGER PRIMARY KEY CHECK (id=1),"
            " revision INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0)")
        conn.execute(
            "INSERT OR IGNORE INTO swarm_board_meta (id, revision, updated_at) VALUES (1, 0, 0)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS swarm_candidates ("
            " candidate_id TEXT PRIMARY KEY, run_id TEXT NOT NULL DEFAULT '',"
            " content TEXT NOT NULL DEFAULT '', artifact_keys TEXT NOT NULL DEFAULT '[]',"
            " base_revision INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'submitted',"
            " conflict_with TEXT NOT NULL DEFAULT '[]', note TEXT NOT NULL DEFAULT '',"
            " created_at REAL NOT NULL DEFAULT 0, decided_at REAL NOT NULL DEFAULT 0)")
        conn.commit()
        self._conn = conn
        # 依赖 os/pathlib 的旁路引用保留（未来清理任务用）；当前仅建目录。
        _ = (_os, Path)

    def _rowToReport(self, row: Any) -> CandidateReport:
        return CandidateReport(
            candidateId=str(row[0]),
            runId=str(row[1] or ""),
            content=str(row[2] or ""),
            artifactKeys=list(self._json.loads(row[3] or "[]")),
            baseRevision=int(row[4] or 0),
            status=str(row[5] or CANDIDATE_SUBMITTED),
            conflictWith=list(self._json.loads(row[6] or "[]")),
            note=str(row[7] or ""),
            createdAt=float(row[8] or 0.0),
            decidedAt=float(row[9] or 0.0),
        )

    def _dbLoad(self, candidateId: str) -> Optional[CandidateReport]:
        row = self._conn.execute(
            "SELECT candidate_id, run_id, content, artifact_keys, base_revision,"
            " status, conflict_with, note, created_at, decided_at"
            " FROM swarm_candidates WHERE candidate_id=?",
            (str(candidateId or "").strip(),),
        ).fetchone()
        return self._rowToReport(row) if row is not None else None

    def _dbPersist(self, candidate: CandidateReport) -> None:
        self._conn.execute(
            "INSERT INTO swarm_candidates (candidate_id, run_id, content, artifact_keys,"
            " base_revision, status, conflict_with, note, created_at, decided_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(candidate_id) DO UPDATE SET run_id=excluded.run_id,"
            " content=excluded.content, artifact_keys=excluded.artifact_keys,"
            " base_revision=excluded.base_revision, status=excluded.status,"
            " conflict_with=excluded.conflict_with, note=excluded.note,"
            " decided_at=excluded.decided_at",
            (candidate.candidateId, candidate.runId, candidate.content,
             self._json.dumps(candidate.artifactKeys), candidate.baseRevision,
             candidate.status, self._json.dumps(candidate.conflictWith),
             candidate.note, candidate.createdAt, candidate.decidedAt),
        )
        self._conn.commit()

    def _dbRevision(self) -> int:
        row = self._conn.execute(
            "SELECT revision FROM swarm_board_meta WHERE id=1").fetchone()
        return int(row[0] or 0)

    def _dbBumpRevision(self) -> int:
        self._conn.execute(
            "UPDATE swarm_board_meta SET revision=revision+1, updated_at=? WHERE id=1",
            (time.time(),))
        self._conn.commit()
        return self._dbRevision()

    # ── 公开接口（两形态共用签名） ─────────────────────────────────────

    @property
    def revision(self) -> int:
        with self._lock:
            if self._conn is not None:
                return self._dbRevision()
            return self._revision

    def candidate(self, candidateId: str) -> Optional[CandidateReport]:
        with self._lock:
            if self._conn is not None:
                return self._dbLoad(candidateId)
            return self._candidates.get(str(candidateId or "").strip())

    def candidatesForRun(self, runId: str) -> List[CandidateReport]:
        with self._lock:
            if self._conn is not None:
                rows = self._conn.execute(
                    "SELECT candidate_id, run_id, content, artifact_keys, base_revision,"
                    " status, conflict_with, note, created_at, decided_at"
                    " FROM swarm_candidates WHERE run_id=? ORDER BY created_at ASC",
                    (str(runId or ""),),
                ).fetchall()
                return [self._rowToReport(r) for r in rows]
            return [c for c in self._candidates.values() if c.runId == str(runId or "")]

    def allCandidates(self) -> List[CandidateReport]:
        with self._lock:
            if self._conn is not None:
                rows = self._conn.execute(
                    "SELECT candidate_id, run_id, content, artifact_keys, base_revision,"
                    " status, conflict_with, note, created_at, decided_at"
                    " FROM swarm_candidates ORDER BY created_at ASC").fetchall()
                return [self._rowToReport(r) for r in rows]
            return list(self._candidates.values())

    def conflicts(self) -> List[Dict[str, Any]]:
        """当前带冲突标记的候选（含已合入一方的历史标记）投影。"""
        with self._lock:
            if self._conn is not None:
                rows = self._conn.execute(
                    "SELECT candidate_id, run_id, content, artifact_keys, base_revision,"
                    " status, conflict_with, note, created_at, decided_at"
                    " FROM swarm_candidates WHERE conflict_with != '[]' ORDER BY created_at ASC"
                ).fetchall()
                return [self._rowToReport(r).toDict() for r in rows]
            return [c.toDict() for c in self._candidates.values() if c.conflictWith]

    def snapshot(self) -> Dict[str, Any]:
        """integrationReport 的 candidates/conflicts/revision 字段源。"""
        with self._lock:
            if self._conn is not None:
                allReports = self.allCandidates()
                return {
                    "revision": self._dbRevision(),
                    "candidates": [c.toDict() for c in allReports],
                    "conflicts": [c.toDict() for c in allReports if c.conflictWith],
                }
            return {
                "revision": self._revision,
                "candidates": [c.toDict() for c in self._candidates.values()],
                "conflicts": [c.toDict() for c in self._candidates.values() if c.conflictWith],
            }

    def submitCandidate(
        self, runId: str, content: str, artifactKeys: Optional[List[str]] = None,
        baseRevision: Optional[int] = None,
    ) -> CandidateReport:
        """落一份候选（submitted）。同 key 同基准的在途候选 → 双方标记冲突保留。"""
        with self._lock:
            if self._conn is not None:
                revision = self._dbRevision()
                candidate = CandidateReport(
                    candidateId=f"cand_{uuid.uuid4().hex[:12]}",
                    runId=str(runId or ""),
                    content=str(content or ""),
                    artifactKeys=[str(k) for k in (artifactKeys or []) if str(k or "").strip()],
                    baseRevision=int(baseRevision if baseRevision is not None else revision),
                    status=CANDIDATE_SUBMITTED,
                )
                self._dbPersist(candidate)
                self._dbFlagSameKeyClash(candidate)
                return self._dbLoad(candidate.candidateId) or candidate
            candidate = CandidateReport(
                candidateId=f"cand_{uuid.uuid4().hex[:12]}",
                runId=str(runId or ""),
                content=str(content or ""),
                artifactKeys=[str(k) for k in (artifactKeys or []) if str(k or "").strip()],
                baseRevision=int(baseRevision if baseRevision is not None else self._revision),
                status=CANDIDATE_SUBMITTED,
            )
            self._candidates[candidate.candidateId] = candidate
            self._flagSameKeyClash(candidate)
            return candidate

    def resubmitCandidate(
        self, candidateId: str, content: str, baseRevision: Optional[int] = None,
    ) -> CandidateReport:
        """回炉修正后重新提交：回到 submitted、换新基准；旧冲突标记随新基准清除。"""
        with self._lock:
            if self._conn is not None:
                candidate = self._dbMustGet(candidateId)
                candidate.content = str(content or "")
                candidate.baseRevision = int(
                    baseRevision if baseRevision is not None else self._dbRevision())
                candidate.status = CANDIDATE_SUBMITTED
                candidate.conflictWith = []
                candidate.note = ""
                candidate.decidedAt = 0.0
                self._dbPersist(candidate)
                self._dbFlagSameKeyClash(candidate)
                return self._dbLoad(candidate.candidateId) or candidate
            candidate = self._mustGet(candidateId)
            candidate.content = str(content or "")
            candidate.baseRevision = int(
                baseRevision if baseRevision is not None else self._revision)
            candidate.status = CANDIDATE_SUBMITTED
            candidate.conflictWith = []
            candidate.note = ""
            candidate.decidedAt = 0.0
            self._flagSameKeyClash(candidate)
            return candidate

    def mergeCandidate(self, candidateId: str) -> Dict[str, Any]:
        """CAS 合入：候选.baseRevision == 当前 revision 才合入；不一致判冲突。

        SQLite 形态下整个判定在 ``BEGIN IMMEDIATE`` 事务内完成——多进程并发
        合入由库级写锁串行化，CAS 判定权随库（M7 乙）。

        Returns:
            {"merged": True, "candidate_id": …, "revision": 合入后的新版本}
        Raises:
            CandidateMergeError: 候选不存在 / 状态不允许（未重提的 reviseRequired、
                已否决）/ 重复合入。
            CandidateConflictError: CAS 失败——集成面已被推进，候选保留待人工裁决。
        """
        with self._lock:
            if self._conn is not None:
                return self._dbMergeCandidate(candidateId)
            candidate = self._mustGet(candidateId)
            if candidate.status == CANDIDATE_ACCEPTED:
                raise CandidateMergeError(
                    f"候选 {candidate.candidateId} 已合入，不重复受理")
            if candidate.status != CANDIDATE_SUBMITTED:
                raise CandidateMergeError(
                    f"候选 {candidate.candidateId} 状态为 {candidate.status}，"
                    "不可合入（reviseRequired 请先 resubmitCandidate）")
            if candidate.baseRevision != self._revision:
                clashing = self._acceptedWithSameKeys(candidate)
                candidate.conflictWith = [c.candidateId for c in clashing]
                candidate.note = (
                    f"CAS 冲突：候选基准 {candidate.baseRevision} ≠ "
                    f"当前集成版本 {self._revision}；候选保留待人工裁决")
                raise CandidateConflictError(
                    candidate.note
                    + (f"（冲突对象：{candidate.conflictWith}）" if clashing else ""),
                    candidateId=candidate.candidateId,
                    conflictWith=candidate.conflictWith,
                )
            self._revision += 1
            candidate.status = CANDIDATE_ACCEPTED
            candidate.decidedAt = time.time()
            candidate.note = ""
            return {"merged": True, "candidate_id": candidate.candidateId,
                    "revision": self._revision}

    def _dbMergeCandidate(self, candidateId: str) -> Dict[str, Any]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            candidate = self._dbLoad(candidateId)
            if candidate is None:
                raise CandidateMergeError(f"候选不存在: {candidateId!r}")
            if candidate.status == CANDIDATE_ACCEPTED:
                raise CandidateMergeError(
                    f"候选 {candidate.candidateId} 已合入，不重复受理")
            if candidate.status != CANDIDATE_SUBMITTED:
                raise CandidateMergeError(
                    f"候选 {candidate.candidateId} 状态为 {candidate.status}，"
                    "不可合入（reviseRequired 请先 resubmitCandidate）")
            revision = self._dbRevision()
            if candidate.baseRevision != revision:
                clashing = self._dbAcceptedWithSameKeys(candidate)
                candidate.conflictWith = [c.candidateId for c in clashing]
                candidate.note = (
                    f"CAS 冲突：候选基准 {candidate.baseRevision} ≠ "
                    f"当前集成版本 {revision}；候选保留待人工裁决")
                self._dbPersist(candidate)
                raise CandidateConflictError(
                    candidate.note
                    + (f"（冲突对象：{candidate.conflictWith}）" if clashing else ""),
                    candidateId=candidate.candidateId,
                    conflictWith=candidate.conflictWith,
                )
            self._conn.execute(
                "UPDATE swarm_board_meta SET revision=revision+1, updated_at=? WHERE id=1",
                (time.time(),))
            candidate.status = CANDIDATE_ACCEPTED
            candidate.decidedAt = time.time()
            candidate.note = ""
            self._dbPersist(candidate)
            newRevision = self._dbRevision()
            return {"merged": True, "candidate_id": candidate.candidateId,
                    "revision": newRevision}
        except Exception:
            self._conn.rollback()
            raise

    def markReviseRequired(self, candidateId: str, reason: str = "") -> CandidateReport:
        """验收/评审驳回：候选置 reviseRequired（回炉链由 swarm/acceptance 侧既有机制承接）。"""
        with self._lock:
            if self._conn is not None:
                candidate = self._dbMustGet(candidateId)
                candidate.status = CANDIDATE_REVISE_REQUIRED
                candidate.note = str(reason or "验收驳回")
                candidate.decidedAt = time.time()
                self._dbPersist(candidate)
                return candidate
            candidate = self._mustGet(candidateId)
            candidate.status = CANDIDATE_REVISE_REQUIRED
            candidate.note = str(reason or "验收驳回")
            candidate.decidedAt = time.time()
            return candidate

    def rejectCandidate(self, candidateId: str, reason: str = "") -> CandidateReport:
        """人工否决一份候选（冲突裁决/审批拒绝的落点；结果不再进入集成）。"""
        with self._lock:
            if self._conn is not None:
                candidate = self._dbMustGet(candidateId)
                candidate.status = CANDIDATE_REJECTED
                candidate.note = str(reason or "人工否决")
                candidate.decidedAt = time.time()
                self._dbPersist(candidate)
                return candidate
            candidate = self._mustGet(candidateId)
            candidate.status = CANDIDATE_REJECTED
            candidate.note = str(reason or "人工否决")
            candidate.decidedAt = time.time()
            return candidate

    # ── SQLite 内部 ───────────────────────────────────────────

    def _dbMustGet(self, candidateId: str) -> CandidateReport:
        candidate = self._dbLoad(candidateId)
        if candidate is None:
            raise CandidateMergeError(f"候选不存在: {candidateId!r}")
        return candidate

    def _dbFlagSameKeyClash(self, candidate: CandidateReport) -> None:
        """同 artifactKey 且同 baseRevision 的在途候选互相标记冲突（都保留，不裁决）。"""
        if not candidate.artifactKeys:
            return
        rows = self._conn.execute(
            "SELECT candidate_id, run_id, content, artifact_keys, base_revision,"
            " status, conflict_with, note, created_at, decided_at"
            " FROM swarm_candidates WHERE base_revision=? AND candidate_id != ?",
            (candidate.baseRevision, candidate.candidateId),
        ).fetchall()
        for row in rows:
            other = self._rowToReport(row)
            if other.baseRevision != candidate.baseRevision:
                continue
            if not set(other.artifactKeys) & set(candidate.artifactKeys):
                continue
            for a, b in ((candidate, other), (other, candidate)):
                if a.candidateId not in a.conflictWith:
                    a.conflictWith.append(b.candidateId)
                if not a.note:
                    a.note = (f"与候选 {b.candidateId} 主张同一产物 "
                              f"{sorted(set(a.artifactKeys) & set(b.artifactKeys))}"
                              f" 且基准版本相同（{a.baseRevision}），待人工裁决")
                self._dbPersist(a)

    def _dbAcceptedWithSameKeys(self, candidate: CandidateReport) -> List[CandidateReport]:
        if not candidate.artifactKeys:
            return []
        rows = self._conn.execute(
            "SELECT candidate_id, run_id, content, artifact_keys, base_revision,"
            " status, conflict_with, note, created_at, decided_at"
            " FROM swarm_candidates WHERE status=? AND candidate_id != ?",
            (CANDIDATE_ACCEPTED, candidate.candidateId),
        ).fetchall()
        return [
            self._rowToReport(r) for r in rows
            if set(self._rowToReport(r).artifactKeys) & set(candidate.artifactKeys)
        ]

    # ── 内存形态内部 ─────────────────────────────────────────

    def _mustGet(self, candidateId: str) -> CandidateReport:
        candidate = self._candidates.get(str(candidateId or "").strip())
        if candidate is None:
            raise CandidateMergeError(f"候选不存在: {candidateId!r}")
        return candidate

    def _flagSameKeyClash(self, candidate: CandidateReport) -> None:
        """同 artifactKey 且同 baseRevision 的在途候选互相标记冲突（都保留，不裁决）。"""
        if not candidate.artifactKeys:
            return
        for other in self._candidates.values():
            if other.candidateId == candidate.candidateId:
                continue
            if other.baseRevision != candidate.baseRevision:
                continue
            if not set(other.artifactKeys) & set(candidate.artifactKeys):
                continue
            for a, b in ((candidate, other), (other, candidate)):
                if a.candidateId not in a.conflictWith:
                    a.conflictWith.append(b.candidateId)
                if not a.note:
                    a.note = (f"与候选 {b.candidateId} 主张同一产物 "
                              f"{sorted(set(a.artifactKeys) & set(b.artifactKeys))}"
                              f" 且基准版本相同（{a.baseRevision}），待人工裁决")

    def _acceptedWithSameKeys(self, candidate: CandidateReport) -> List[CandidateReport]:
        if not candidate.artifactKeys:
            return []
        return [
            c for c in self._candidates.values()
            if c.candidateId != candidate.candidateId
            and c.status == CANDIDATE_ACCEPTED
            and set(c.artifactKeys) & set(candidate.artifactKeys)
        ]
