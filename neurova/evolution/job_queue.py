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
from typing import Any, Awaitable, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.core.db_migration import migrate as apply_migrations, register_migration
from neurova.core.data_root import get_data_root
from neurova.core.lazy_singleton import lazySingleton

logger = get_logger(__name__)

# schema 版本域：作业表建表/索引经注册表演进（审计 3.4-10）
EVOLUTION_JOBS_DOMAIN = "evolution_jobs"

register_migration(
    1,
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
    """,
    domain=EVOLUTION_JOBS_DOMAIN,
)
register_migration(
    2,
    "ALTER TABLE evolution_jobs ADD COLUMN lease_token TEXT",
    domain=EVOLUTION_JOBS_DOMAIN,
)

_STATUS = ("pending", "running", "done", "failed_retryable", "failed")
_OPEN_STATUSES = ("pending", "running", "failed_retryable")
_DEFAULT_DB = get_data_root() / "evolution" / "jobs.db"


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
            # 建表/索引经版本化迁移链（审计 3.4-10）：新库落 v1，旧库按
            # user_version 跳过；不再手拼 executescript
            apply_migrations(self._conn, EVOLUTION_JOBS_DOMAIN)
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
            leaseToken = uuid.uuid4().hex
            self._conn.execute(
                "UPDATE evolution_jobs SET status='running', attempts=attempts+1,"
                " locked_by=?, locked_at=?, lease_token=?, updated_at=? WHERE id=?",
                (worker_id, now, leaseToken, now, row["id"]),
            )
            self._conn.commit()
            out = dict(row)
            out["attempts"] = int(row["attempts"]) + 1
            out["lease_token"] = leaseToken
            out["payload"] = self._load_payload(row["payload_json"])
            return out

    def renewLease(self, jobId: str, leaseToken: str) -> bool:
        """续租当前领取；token 已失效或作业已换主时返回 False。"""
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE evolution_jobs SET locked_at=?, updated_at=?"
                " WHERE id=? AND status='running' AND lease_token=?",
                (now, now, jobId, leaseToken),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def complete(
        self, jobId: str, leaseToken: str, result: Optional[Dict[str, Any]] = None
    ) -> bool:
        return self._setStatus(jobId, leaseToken, "done", result=result, error=None)

    def fail(self, jobId: str, leaseToken: str, error: str) -> bool:
        """失败：attempts<max → failed_retryable（可再 claim），否则终态 failed。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT attempts FROM evolution_jobs"
                " WHERE id=? AND status='running' AND lease_token=?",
                (jobId, leaseToken),
            ).fetchone()
            if row is None:
                return False
            attempts = int(row["attempts"])
            status = "failed_retryable" if attempts < self.max_attempts else "failed"
            return self._setStatus(jobId, leaseToken, status, result=None, error=str(error)[:500])

    def _setStatus(
        self,
        jobId: str,
        leaseToken: str,
        status: str,
        result: Optional[Dict[str, Any]],
        error: Optional[str],
    ) -> bool:
        assert status in _STATUS, f"非法作业状态: {status}"
        with self._lock:
            cur = self._conn.execute(
                "UPDATE evolution_jobs SET status=?, result_json=?, error=?,"
                " locked_by=NULL, locked_at=NULL, lease_token=NULL, updated_at=?"
                " WHERE id=? AND status='running' AND lease_token=?",
                (
                    status,
                    json.dumps(result or {}, ensure_ascii=False, default=str),
                    error,
                    time.time(),
                    jobId,
                    leaseToken,
                ),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def recover_stale(self, lease_seconds: Optional[int] = None) -> int:
        """崩溃恢复：running 且租约超时的作业重置 failed_retryable（可再领取）。"""
        lease = lease_seconds or self.lease_seconds
        cutoff = time.time() - lease
        with self._lock:
            cur = self._conn.execute(
                "UPDATE evolution_jobs SET status='failed_retryable',"
                " locked_by=NULL, locked_at=NULL, lease_token=NULL, updated_at=?"
                " WHERE status='running' AND (locked_at IS NULL OR locked_at < ?)",
                (time.time(), cutoff),
            )
            self._conn.commit()
            n = cur.rowcount
        if n:
            logger.info("进化作业租约恢复 %d 条 → failed_retryable", n)
        return n

    def staleRunningJobs(self, lease_seconds: Optional[int] = None) -> List[Dict[str, Any]]:
        """卡死作业只读面：running 且租约已超时的作业（worker 崩溃遗留）。

        S4 driver dispatch_log 的可见性对应物：``recover_stale`` 负责修复，
        本读面负责让"有作业卡在 running"先被看见（age/attempts/locked_by
        随行）——看不见的卡死等于没有卡死。只读，不改任何状态。
        """
        lease = lease_seconds or self.lease_seconds
        cutoff = time.time() - lease
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, kind, locked_by, locked_at, attempts FROM evolution_jobs"
                " WHERE status='running' AND (locked_at IS NULL OR locked_at < ?)"
                " ORDER BY created_at ASC",
                (cutoff,),
            ).fetchall()
        now = time.time()
        out: List[Dict[str, Any]] = []
        for row in rows:
            lockedAt = row["locked_at"]
            out.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "lockedBy": row["locked_by"] or "",
                    "attempts": int(row["attempts"]),
                    "ageSeconds": (
                        round(max(0.0, now - float(lockedAt)), 3)
                        if lockedAt is not None
                        else None
                    ),
                }
            )
        return out

    def pending_count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) c FROM evolution_jobs WHERE status IN ('pending','failed_retryable')"
            ).fetchone()
            return int(row["c"]) if row else 0

    def _heartbeatLease(
        self,
        jobId: str,
        leaseToken: str,
        stopEvent: threading.Event,
        lostEvent: threading.Event,
    ) -> None:
        interval = max(0.05, self.lease_seconds / 3)
        while not stopEvent.wait(interval):
            try:
                renewed = self.renewLease(jobId, leaseToken)
            except Exception as e:  # noqa: BLE001 - 续租失败必须停止该 worker 的写回
                logger.warning("进化作业 %s 续租失败: %s", jobId, e)
                renewed = False
            if not renewed:
                lostEvent.set()
                return

    def _startLeaseHeartbeat(
        self, jobId: str, leaseToken: str
    ) -> tuple[threading.Event, threading.Event, threading.Thread]:
        stopEvent = threading.Event()
        lostEvent = threading.Event()
        thread = threading.Thread(
            target=self._heartbeatLease,
            args=(jobId, leaseToken, stopEvent, lostEvent),
            name=f"evolution-lease-{jobId}",
            daemon=True,
        )
        thread.start()
        return stopEvent, lostEvent, thread

    def _settleDrainedJob(
        self,
        job: Dict[str, Any],
        lostLease: threading.Event,
        handlerError: Optional[Exception],
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        if lostLease.is_set():
            logger.warning("进化作业 %s 租约已失效，丢弃旧 worker 状态回写", job["id"])
            return
        if handlerError is None:
            if not self.complete(job["id"], job["lease_token"], result=result):
                logger.warning("进化作业 %s 完成回写前已失去租约", job["id"])
        elif not self.fail(job["id"], job["lease_token"], str(handlerError)):
            logger.warning("进化作业 %s 失败回写前已失去租约", job["id"])

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
            stopHeartbeat, lostLease, heartbeat = self._startLeaseHeartbeat(
                job["id"], job["lease_token"]
            )
            handlerError = None
            try:
                handler(job)
            except Exception as e:  # noqa: BLE001 - 单作业失败不影响队列其余
                handlerError = e
                logger.warning("进化作业 %s 处理失败: %s", job["id"], e)
            finally:
                stopHeartbeat.set()
                heartbeat.join()
            self._settleDrainedJob(job, lostLease, handlerError)
        return processed

    async def drainAsync(
        self,
        workerId: str,
        handler: Callable[[Dict[str, Any]], Awaitable[Any]],
        max_jobs: int = 5,
    ) -> int:
        """异步消费入口；与同步 drain 共用租约心跳和 fencing 终态写回。"""
        processed = 0
        tried: List[str] = []
        self.recover_stale()
        while processed < max_jobs:
            job = self.claim(workerId, exclude_ids=tuple(tried))
            if job is None:
                break
            tried.append(job["id"])
            processed += 1
            stopHeartbeat, lostLease, heartbeat = self._startLeaseHeartbeat(
                job["id"], job["lease_token"]
            )
            handlerError = None
            handlerResult = None
            try:
                handlerResult = await handler(job)
            except Exception as e:  # noqa: BLE001 - 单作业失败不影响队列其余
                handlerError = e
                logger.warning("进化作业 %s 处理失败: %s", job["id"], e)
            finally:
                stopHeartbeat.set()
                heartbeat.join()
            self._settleDrainedJob(
                job,
                lostLease,
                handlerError,
                result=handlerResult if isinstance(handlerResult, dict) else None,
            )
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


@lazySingleton("_queue_singleton")
def get_evolution_job_queue(db_path: Optional[Path] = None) -> EvolutionJobQueue:
    return EvolutionJobQueue(db_path=db_path)


def reset_evolution_job_queue() -> None:
    """测试隔离：关闭并重置单例。"""
    global _queue_singleton
    if _queue_singleton is not None:
        _queue_singleton.close()
    _queue_singleton = None
