# -*- coding: utf-8 -*-
"""Dreaming 式规则自改进（实施计划项 7：夜间 clue→candidate→active）。

参照系对照报告 §10-7 的准入纪律：自主行为与其后的用户反馈是"线索"（clue）；
同 kind 的线索累计到门槛才合并为**候选规则**（candidate），用户**直接点名**
（显式反馈）单次即候选；夜间 sweep 把候选升格为 **active**；次日判定面
（proactive/审批提示/回复策略）只读转正规则，**读不到 clue**——判定不建立在
未证实的单次观察上。

三层结构（对齐 ``core/agent_run_store.py`` 的已验证惯例）：

- ``DreamRuleStore``：SQLite 存储层。库文件在数据根（``NEUROVA_DREAMING_DB``
  可覆盖），RLock 串行写 + WAL + 版本化迁移链（domain=``dreaming_rules``）。
  两张表：``rule_clues``（线索，按 kind+decision 聚合计数）与
  ``behavior_rules``（规则，kind+decision 唯一，candidate/active 两态）。
- 规则生命周期：``recordClue`` 落线索并按门槛生成候选 → ``dreamSweep``
  （夜间睡眠窗口）把候选升格 active → ``activeRules`` 供判定面只读。
- 转正闸：复用 S16/S7 的敏感筛查单源 :func:`memory_admission.screenMemoryContent`
  ——判定文本命中敏感模式族的候选**不自动转正**（fail-closed），留 candidate
  并审计留痕，等人工处置；不另造第二套审阅体系。

门控：``NEUROVA_DREAMING``（默认开；置 0/off/false/no 直通停用）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.db_migration import migrate as apply_migrations
from neurova.core.db_migration import register_migration
from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "DreamRuleStore",
    "dreamingEnabled",
    "recordClue",
    "dreamSweep",
    "activeRules",
    "candidateRules",
    "get_dream_rule_store",
    "reset_dream_rule_store",
    "dreamingCounters",
]

# ──────────────────────────────────────────────────────────────
# 常量（阈值/开关一律具名，不散落字面量）
# ──────────────────────────────────────────────────────────────

#: 功能门控环境变量（默认开；回滚时置 0）
DREAMING_ENV = "NEUROVA_DREAMING"

#: 候选生成门槛：同 kind+decision 的普通线索累计 ≥2 次才成候选规则
CANDIDATE_MIN_COUNT = 2

#: 规则状态（对齐 S16 候选/转正语义的两态裁剪）
RULE_STATUS_CANDIDATE = "candidate"
RULE_STATUS_ACTIVE = "active"

#: 转正审计在审计单源里的 action 标识（敏感候选被扣留时留痕）
AUDIT_RULE_HELD_ACTION = "dreaming.rule_held_for_review"

#: 线索/决策文本送敏感筛查前的截断上限（判定面文本，非存储截断）
_SCREEN_TEXT_MAX = 500

_TRUTHY_OFF = ("0", "false", "off", "no")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rule_clues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    decision TEXT NOT NULL,
    evidence_ref TEXT NOT NULL DEFAULT '',
    count INTEGER NOT NULL DEFAULT 0,
    explicit_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    UNIQUE(kind, decision)
);
CREATE INDEX IF NOT EXISTS idx_rule_clues_kind
    ON rule_clues(kind, updated_at);

CREATE TABLE IF NOT EXISTS behavior_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    decision TEXT NOT NULL,
    source_clue_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at REAL NOT NULL DEFAULT 0,
    activated_at REAL,
    UNIQUE(kind, decision)
);
CREATE INDEX IF NOT EXISTS idx_behavior_rules_status
    ON behavior_rules(status, kind);
"""

# 迁移链（对齐 agent_run_store 的版本化惯例；v1 即全量 schema）
register_migration(1, _SCHEMA, domain="dreaming_rules")


# ──────────────────────────────────────────────────────────────
# 进程内计数（观测面；与 S16 纪律计数同形）
# ──────────────────────────────────────────────────────────────

_counters: Dict[str, int] = {
    "cluesRecorded": 0,
    "candidateRulesCreated": 0,
    "rulesPromoted": 0,
    "rulesHeldForReview": 0,
}
_countersLock = threading.Lock()


def _bumpCounter(name: str) -> None:
    with _countersLock:
        _counters[name] = _counters.get(name, 0) + 1


def dreamingCounters() -> dict:
    """进程内 dreaming 计数快照（线索/候选/转正/扣留）。"""
    with _countersLock:
        return dict(_counters)


def dreamingEnabled() -> bool:
    """功能门控（默认开）。``NEUROVA_DREAMING`` 置 0/off/false/no 时停用。"""
    return str(os.environ.get(DREAMING_ENV, "")).strip().lower() not in _TRUTHY_OFF


def _now() -> float:
    return time.time()


# ──────────────────────────────────────────────────────────────
# 存储层
# ──────────────────────────────────────────────────────────────


class DreamRuleStore:
    """规则/线索账本（每实例一个 SQLite 连接，RLock 串行写，WAL）。"""

    def __init__(self, db_path: Any = None):
        from neurova.core.data_root import get_data_root

        self.db_path = str(
            db_path
            or os.environ.get("NEUROVA_DREAMING_DB")
            or (get_data_root() / "dreaming_rules.db")
        )
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # SQLite 多线程访问持 RLock（AGENTS.md §3；可重入不改变串行语义）
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        with self._lock, self._conn:
            apply_migrations(self._conn, "dreaming_rules")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── 线索写入与候选生成 ────────────────────────────────────────

    def recordClue(
        self,
        kind: str,
        decision: str,
        evidence_ref: str = "",
        explicit: bool = False,
    ) -> Dict[str, Any]:
        """落一条线索（同 kind+decision 聚合计数），达门槛即生成候选规则。

        - 聚合键 = (kind, decision) 二元组：同 kind 不同 decision 不互并，
          不同 kind 同 decision 也不互并（判据 d）；
        - 候选生成判定单点：``explicit=True``（用户直接点名）单次即候选；
          普通线索累计 ≥ ``CANDIDATE_MIN_COUNT`` 次成候选；
        - 同一 (kind, decision) 只有一条规则行——重复观测只累加线索计数，
          不重复建规则（单一事实源）。
        """
        kind = str(kind or "").strip()
        decision = str(decision or "").strip()
        if not kind or not decision:
            raise ValueError("recordClue 需要 kind 与 decision 均非空")
        now = _now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO rule_clues"
                " (kind, decision, evidence_ref, count, explicit_count,"
                "  created_at, updated_at)"
                " VALUES (?,?,?,1,?,?,?)"
                " ON CONFLICT(kind, decision) DO UPDATE SET"
                "  count = count + 1,"
                "  explicit_count = explicit_count + ?,"
                "  evidence_ref = excluded.evidence_ref,"
                "  updated_at = ?",
                (
                    kind,
                    decision,
                    str(evidence_ref or ""),
                    1 if explicit else 0,
                    now,
                    now,
                    1 if explicit else 0,
                    now,
                ),
            )
            row = self._conn.execute(
                "SELECT * FROM rule_clues WHERE kind=? AND decision=?",
                (kind, decision),
            ).fetchone()
            clue = dict(row)
            rule: Optional[Dict[str, Any]] = None
            if clue["count"] >= CANDIDATE_MIN_COUNT or clue["explicit_count"] >= 1:
                rule = self._ensureCandidateRuleLocked(kind, decision, int(clue["id"]))
        _bumpCounter("cluesRecorded")
        return {"clue": clue, "rule": rule, "recorded": True}

    def _ensureCandidateRuleLocked(
        self, kind: str, decision: str, clueId: int
    ) -> Dict[str, Any]:
        """取既有规则或建候选规则（调用方必须已持锁；kind/decision 已校验）。"""
        existing = self._conn.execute(
            "SELECT * FROM behavior_rules WHERE kind=? AND decision=?",
            (kind, decision),
        ).fetchone()
        if existing is not None:
            return self._ruleToDict(existing)
        self._conn.execute(
            "INSERT INTO behavior_rules (kind, decision, source_clue_ids, status,"
            " created_at) VALUES (?,?,?,'candidate',?)",
            (kind, decision, json.dumps([clueId]), _now()),
        )
        row = self._conn.execute(
            "SELECT * FROM behavior_rules WHERE kind=? AND decision=?",
            (kind, decision),
        ).fetchone()
        _bumpCounter("candidateRulesCreated")
        logger.info(
            "Dreaming：候选规则已生成 kind=%s decision=%s（来源线索 id=%s）",
            kind,
            decision,
            clueId,
        )
        return self._ruleToDict(row)

    @staticmethod
    def _ruleToDict(row: sqlite3.Row) -> Dict[str, Any]:
        """规则行转 dict：source_clue_ids 由 JSON 串解码为列表（读面统一形态）。"""
        rule = dict(row)
        try:
            rule["source_clue_ids"] = json.loads(rule.get("source_clue_ids") or "[]")
        except (ValueError, TypeError):
            rule["source_clue_ids"] = []
        return rule

    # ── 夜间 sweep：候选 → active ────────────────────────────────

    def dreamSweep(self) -> Dict[str, Any]:
        """把候选规则升格 active（对齐 S16 的转正语义 + 同一道敏感审阅闸）。

        - 逐条过 S16 敏感筛查单源（``screenMemoryContent``）：命中即**不转正**
          （fail-closed），保持 candidate 并审计留痕，等人工处置；
        - 筛查能力不可用时同样扣留（宁可慢转正，不可静默放行）；
        - 幂等：active 行不再进入扫描，重复 sweep 无副作用。
        """
        promoted: List[Dict[str, Any]] = []
        heldForReview: List[Dict[str, Any]] = []
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT * FROM behavior_rules WHERE status=? ORDER BY id",
                (RULE_STATUS_CANDIDATE,),
            ).fetchall()
            for row in rows:
                rule = self._ruleToDict(row)
                hit, hitReason = self._screenRuleTextLocked(rule)
                if hit:
                    heldForReview.append(
                        {
                            "rule": {
                                "id": rule["id"],
                                "kind": rule["kind"],
                                "decision": rule["decision"],
                                "status": rule["status"],
                            },
                            "reason": hitReason,
                        }
                    )
                    _bumpCounter("rulesHeldForReview")
                    self._auditHeldRule(rule, hitReason)
                    continue
                activatedAt = _now()
                self._conn.execute(
                    "UPDATE behavior_rules SET status=?, activated_at=?"
                    " WHERE id=? AND status=?",
                    (RULE_STATUS_ACTIVE, activatedAt, rule["id"], RULE_STATUS_CANDIDATE),
                )
                rule["status"] = RULE_STATUS_ACTIVE
                rule["activated_at"] = activatedAt
                promoted.append(rule)
                _bumpCounter("rulesPromoted")
        if promoted:
            logger.info(
                "Dreaming sweep：%d 条候选规则转正 active（kind=%s）",
                len(promoted),
                [r["kind"] for r in promoted],
            )
        if heldForReview:
            logger.warning(
                "Dreaming sweep：%d 条候选规则命中敏感闸，留候审不转正（kind=%s）",
                len(heldForReview),
                [h["rule"]["kind"] for h in heldForReview],
            )
        return {
            "scanned": len(promoted) + len(heldForReview),
            "promoted": promoted,
            "heldForReview": heldForReview,
        }

    def _screenRuleTextLocked(self, rule: Dict[str, Any]):
        """S16 同闸：规则判定文本过敏感筛查单源。返回 (命中?, 原因)。

        筛查单源不可用时按命中处理（fail-closed，扣留待人工）。
        """
        try:
            from neurova.memory_admission import screenMemoryContent
        except Exception as exc:  # noqa: BLE001 - 闸缺席时宁可扣留
            return True, f"sensitive_gate_unavailable: {type(exc).__name__}"
        text = f"{rule.get('kind') or ''}\n{rule.get('decision') or ''}"[:_SCREEN_TEXT_MAX]
        try:
            hit = screenMemoryContent(text)
        except Exception as exc:  # noqa: BLE001 - 筛查异常按扣留处理
            return True, f"sensitive_gate_error: {type(exc).__name__}"
        if hit is None:
            return False, ""
        return True, str(getattr(hit, "ruleName", "") or "sensitive_pattern")

    def _auditHeldRule(self, rule: Dict[str, Any], reason: str) -> None:
        """敏感候选扣留的审计留痕（复用仓内审计单源；失败只留日志不阻断）。"""
        try:
            from neurova.core.identity_context import get_request_user_id
            from neurova.security.audit_logger import (
                AuditEventType,
                AuditSeverity,
                log_audit,
            )

            ok = log_audit(
                AuditEventType.SECURITY_EVENT,
                AuditSeverity.MEDIUM,
                user_id=str(get_request_user_id() or ""),
                action=AUDIT_RULE_HELD_ACTION,
                details={
                    "ruleId": int(rule.get("id") or 0),
                    "kind": str(rule.get("kind") or ""),
                    "reason": reason,
                },
                resource_type="dreaming_rule",
            )
            if not ok:
                logger.error("Dreaming 扣留审计未落库（rule=%s）——须人工复核", rule.get("id"))
        except Exception as exc:  # noqa: BLE001 - 审计异常不影响 sweep 主流程
            logger.error("Dreaming 扣留审计异常（rule=%s）：%s", rule.get("id"), exc)

    # ── 判定面（只读 active 规则，读不到 clue）────────────────────

    def activeRules(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        """转正规则读面（判定面专用）：只查 behavior_rules 的 active 行。

        不 join 线索表——clue 字段（evidence_ref/count）不出现在本读面，
        "判定不读未证实线索"的纪律由读法本身保证。
        """
        with self._lock:
            if kind is not None:
                rows = self._conn.execute(
                    "SELECT * FROM behavior_rules WHERE status=? AND kind=? ORDER BY id",
                    (RULE_STATUS_ACTIVE, str(kind)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM behavior_rules WHERE status=? ORDER BY id",
                    (RULE_STATUS_ACTIVE,),
                ).fetchall()
        return [self._ruleToDict(r) for r in rows]

    def candidateRules(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        """候选规则读面（审阅/观测用，不供判定面消费）。"""
        with self._lock:
            if kind is not None:
                rows = self._conn.execute(
                    "SELECT * FROM behavior_rules WHERE status=? AND kind=? ORDER BY id",
                    (RULE_STATUS_CANDIDATE, str(kind)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM behavior_rules WHERE status=? ORDER BY id",
                    (RULE_STATUS_CANDIDATE,),
                ).fetchall()
        return [self._ruleToDict(r) for r in rows]


# ── 进程级单例（DCL + RLock，仓规）─────────────────────────────────

_store_instance: Optional[DreamRuleStore] = None
_store_lock = threading.RLock()


def get_dream_rule_store() -> DreamRuleStore:
    global _store_instance
    if _store_instance is not None:
        return _store_instance
    with _store_lock:
        if _store_instance is None:
            _store_instance = DreamRuleStore()
        return _store_instance


def reset_dream_rule_store() -> None:
    """重置单例（测试专用；换库文件的测试先改 env 再 reset）。"""
    global _store_instance
    with _store_lock:
        if _store_instance is not None:
            try:
                _store_instance.close()
            except Exception:  # noqa: BLE001 - 释放失败不阻断重置
                pass
            _store_instance = None


# ──────────────────────────────────────────────────────────────
# 模块级 API（门控 + 单例委托）
# ──────────────────────────────────────────────────────────────


def recordClue(
    kind: str,
    decision: str,
    evidence_ref: str = "",
    explicit: bool = False,
) -> Dict[str, Any]:
    """记录一条行为线索；达门槛（或显式点名）自动生成候选规则。

    门控关闭时直通不做（返回 recorded=False）。
    """
    if not dreamingEnabled():
        return {"recorded": False, "reason": "dreaming_disabled", "clue": None, "rule": None}
    return get_dream_rule_store().recordClue(kind, decision, evidence_ref, explicit)


def dreamSweep() -> Dict[str, Any]:
    """夜间 sweep：把候选规则升格 active。门控关闭时空转。"""
    if not dreamingEnabled():
        return {"scanned": 0, "promoted": [], "heldForReview": [], "enabled": False}
    result = get_dream_rule_store().dreamSweep()
    result["enabled"] = True
    return result


def activeRules(kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """判定面：只读 active 规则（读不到 clue）。"""
    return get_dream_rule_store().activeRules(kind)


def candidateRules(kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """候选规则读面（审阅/观测用）。"""
    return get_dream_rule_store().candidateRules(kind)
