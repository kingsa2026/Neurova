# -*- coding: utf-8 -*-
"""技能进化异步作业队列

动机：Neurova 的进化提案此前在 post_chat 同步
直跑——分析失败即丢、无重试、崩溃留半态。本队列把"提案产生"与"提案消费"
解耦为持久作业：

- SQLite 单表 + WAL/busy_timeout（对齐 skill_engine/store.py 纪律）；
- idempotency_key UNIQUE 去重（同回合重复 enqueue 不双行）；
- claim 用 BEGIN IMMEDIATE 原子领取 + 租约（locked_at/lease），并发 worker
  不会互抢同一作业；
- 租约过期 = 崩溃恢复：recover_stale 把 running 超时作业重置 pending；
- 失败可重试：attempts < max_attempts → failed_retryable，否则 failed。

开关默认**接管** post_chat 进化步（SettingPage 高级选项卡可关；
NEUROVA_EVOLUTION_QUEUE 显式值最优先，见 queue_enabled 三级优先级）。
2026-09-15 收口前曾默认关，用户拍板翻转。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_STATUS = ("pending", "running", "done", "failed_retryable", "failed")
_OPEN_STATUSES = ("pending", "running", "failed_retryable")
_DEFAULT_DB = Path("data/evolution/jobs.db")


def queue_enabled() -> bool:
    """进化队列开关，三级优先（2026-09-15 收口 SettingPage 高级选项卡）：

    1. env NEUROVA_EVOLUTION_QUEUE 显式值（运维/测试逃生门，最优先）；
    2. app_settings advanced.evolution_queue_enabled（SettingPage 面，默认开）；
    3. 存储故障回退 True——提案走队列与走 inline 等价可达，不因设置
       IO 异常丢进化。
    """
    raw = str(os.environ.get("NEUROVA_EVOLUTION_QUEUE", "")).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    try:
        from neurova.core.app_settings import get_advanced_settings

        return bool(get_advanced_settings().get("evolution_queue_enabled", True))
    except Exception:  # noqa: BLE001 - 设置存储故障默认开
        return True


class EvolutionJobQueue:
    """持久进化作业队列（线程安全，单例经 get_evolution_job_queue）。"""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        max_attempts: int = 3,
        lease_seconds: int = 300,
    ):
        self.db_path = Path(
            db_path or os.environ.get("NEUROVA_EVOLUTION_JOBS_DB", str(_DEFAULT_DB))
        )
        self.max_attempts = max(1, int(max_attempts))
        self.lease_seconds = max(1, int(lease_seconds))
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS evolution_jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','running','done','failed_retryable','failed')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    locked_by TEXT,
                    locked_at REAL,
                    result_json TEXT,
                    error TEXT,
                    idempotency_key TEXT UNIQUE,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ej_claim
                    ON evolution_jobs(status, created_at);
                """
            )
            self._conn.commit()

    # ── 生产端 ──────────────────────────────────────────

    def enqueue(
        self,
        kind: str,
        payload: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """入队（同 idempotency_key 重复调用不产生新行，返回既有作业）。

        Returns: {"job_id", "created": bool, "deduped": bool}
        """
        now = time.time()
        job_id = f"ej_{uuid.uuid4().hex[:12]}"
        key = idempotency_key or f"{kind}:{now}:{uuid.uuid4().hex[:6]}"
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO evolution_jobs (id, kind, payload_json, idempotency_key,"
                    " status, attempts, created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', 0, ?, ?)",
                    (job_id, kind, json.dumps(payload or {}, ensure_ascii=False, default=str), key, now, now),
                )
                self._conn.commit()
                return {"job_id": job_id, "created": True, "deduped": False}
            except sqlite3.IntegrityError:
                row = self._conn.execute(
                    "SELECT id FROM evolution_jobs WHERE idempotency_key=?", (key,)
                ).fetchone()
                self._conn.commit()
                return {
                    "job_id": row["id"] if row else "",
                    "created": False,
                    "deduped": True,
                }

    # ── 消费端 ──────────────────────────────────────────

    def claim(self, worker_id: str, exclude_ids: tuple = ()) -> Optional[Dict[str, Any]]:
        """原子领取一个可执行作业（pending/failed_retryable 且租约空或已过期）。

        exclude_ids：本轮 drain 已试过的作业——单轮内不得自旋重试同一条
        （失败作业回可重试池等**下一轮**，重试节奏由 max_attempts/租约管）。
        """
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            if exclude_ids:
                marks = ",".join("?" * len(exclude_ids))
                row = self._conn.execute(
                    "SELECT * FROM evolution_jobs WHERE status IN ('pending','failed_retryable')"
                    f" AND id NOT IN ({marks}) ORDER BY created_at ASC LIMIT 1",
                    tuple(exclude_ids),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM evolution_jobs WHERE status IN ('pending','failed_retryable')"
                    " ORDER BY created_at ASC LIMIT 1"
                ).fetchone()
            if row is None:
                self._conn.rollback()
                return None
            self._conn.execute(
                "UPDATE evolution_jobs SET status='running', attempts=attempts+1,"
                " locked_by=?, locked_at=?, updated_at=? WHERE id=?",
                (worker_id, now, now, row["id"]),
            )
            self._conn.commit()
            out = dict(row)
            out["attempts"] = int(row["attempts"]) + 1
            out["payload"] = self._load_payload(row["payload_json"])
            return out

    def complete(self, job_id: str, result: Optional[Dict[str, Any]] = None) -> None:
        self._set_status(job_id, "done", result=result, error=None)

    def fail(self, job_id: str, error: str) -> None:
        """失败：attempts<max → failed_retryable（可再 claim），否则终态 failed。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT attempts FROM evolution_jobs WHERE id=?", (job_id,)
            ).fetchone()
            attempts = int(row["attempts"]) if row else 0
            status = "failed_retryable" if attempts < self.max_attempts else "failed"
        self._set_status(job_id, status, result=None, error=str(error)[:500])

    def _set_status(
        self,
        job_id: str,
        status: str,
        result: Optional[Dict[str, Any]],
        error: Optional[str],
    ) -> None:
        assert status in _STATUS, f"非法作业状态: {status}"
        with self._lock:
            self._conn.execute(
                "UPDATE evolution_jobs SET status=?, result_json=?, error=?,"
                " locked_by=NULL, locked_at=NULL, updated_at=? WHERE id=?",
                (
                    status,
                    json.dumps(result or {}, ensure_ascii=False, default=str),
                    error,
                    time.time(),
                    job_id,
                ),
            )
            self._conn.commit()

    def recover_stale(self, lease_seconds: Optional[int] = None) -> int:
        """崩溃恢复：running 且租约超时的作业重置 failed_retryable（可再领取）。"""
        lease = lease_seconds or self.lease_seconds
        cutoff = time.time() - lease
        with self._lock:
            cur = self._conn.execute(
                "UPDATE evolution_jobs SET status='failed_retryable',"
                " locked_by=NULL, locked_at=NULL, updated_at=?"
                " WHERE status='running' AND (locked_at IS NULL OR locked_at < ?)",
                (time.time(), cutoff),
            )
            self._conn.commit()
            n = cur.rowcount
        if n:
            logger.info("进化作业租约恢复 %d 条 → failed_retryable", n)
        return n

    def pending_count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) c FROM evolution_jobs WHERE status IN ('pending','failed_retryable')"
            ).fetchone()
            return int(row["c"]) if row else 0

    def drain(
        self,
        worker_id: str,
        handler: Callable[[Dict[str, Any]], Any],
        max_jobs: int = 5,
    ) -> int:
        """同步消费至多 max_jobs 条：handler 抛错记 fail（可重试），否则 complete。

        Returns: 实际处理条数（handler 消费 job['payload'] 与 job['kind']）。
        """
        processed = 0
        tried: List[str] = []
        self.recover_stale()
        while processed < max_jobs:
            job = self.claim(worker_id, exclude_ids=tuple(tried))
            if job is None:
                break
            tried.append(job["id"])
            processed += 1
            try:
                handler(job)
                self.complete(job["id"])
            except Exception as e:  # noqa: BLE001 - 单作业失败不影响队列其余
                logger.warning("进化作业 %s 处理失败: %s", job["id"], e)
                self.fail(job["id"], str(e))
        return processed

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    @staticmethod
    def _load_payload(raw: str) -> Dict[str, Any]:
        try:
            data = json.loads(raw or "{}")
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}


# 单例工厂（AGENTS.md 生命周期约定）
_queue_singleton: Optional[EvolutionJobQueue] = None


def get_evolution_job_queue(db_path: Optional[Path] = None) -> EvolutionJobQueue:
    global _queue_singleton
    if _queue_singleton is None:
        _queue_singleton = EvolutionJobQueue(db_path=db_path)
    return _queue_singleton


def reset_evolution_job_queue() -> None:
    """测试隔离：关闭并重置单例。"""
    global _queue_singleton
    if _queue_singleton is not None:
        _queue_singleton.close()
    _queue_singleton = None
