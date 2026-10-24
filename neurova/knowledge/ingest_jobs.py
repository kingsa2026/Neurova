"""知识入站持久任务队列（SQLite，单机先落地）。

与上传任务队列分开：这里存的是"渠道事件 → 知识条目"的入站作业，载荷是
JSON（媒体字节 base64），`dedupe_key` 是渠道消息的稳定身份。语义照现有上传队列：
`pending/running/done/dead`、attempts + 退避、lease 超时回收。
"""
from __future__ import annotations

import datetime
import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.data_root import dataPath
from neurova.core.db_migration import migrate as applyMigrations, register_migration
from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DOMAIN = "knowledge_ingest_jobs"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_ingest_jobs (
    job_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_error TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    next_attempt_at REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status
    ON knowledge_ingest_jobs(status, next_attempt_at);
"""
register_migration(1, _SCHEMA, domain=_DOMAIN)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class KnowledgeIngestQueue:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._path = db_path or dataPath("knowledge_ingest", "jobs.db")
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        applyMigrations(self._conn, _DOMAIN)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def enqueue(
        self, dedupeKey: str, payload: Dict[str, Any], maxAttempts: int = 3
    ) -> Tuple[str, bool]:
        """幂等入队：同 dedupe_key 返回既有 job，不重复建。"""
        key = str(dedupeKey or "").strip()
        if not key:
            raise ValueError("dedupe_key 不能为空")
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT job_id FROM knowledge_ingest_jobs WHERE dedupe_key = ?", (key,)
            ).fetchone()
            if row is not None:
                return str(row["job_id"]), False
            jobId = "kij_%s" % uuid.uuid4().hex[:12]
            stamp = _now()
            self._conn.execute(
                "INSERT INTO knowledge_ingest_jobs (job_id, dedupe_key, payload_json,"
                " status, max_attempts, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (jobId, key, json.dumps(payload, ensure_ascii=False, default=str),
                 "pending", max(1, int(maxAttempts)), stamp, stamp),
            )
            return jobId, True

    def claim(
        self, leaseSeconds: float = 60.0, jobId: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """领取一个到期作业；lease 超时的 running 先回收为 pending。

        给了 jobId 时只领这一条（新消息入队后立即处理，不排在积压队尾）。
        """
        import time

        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE knowledge_ingest_jobs SET status = 'pending', updated_at = ?"
                " WHERE status = 'running' AND next_attempt_at <= ?",
                (_now(), now),
            )
            if jobId:
                row = self._conn.execute(
                    "SELECT * FROM knowledge_ingest_jobs"
                    " WHERE job_id = ? AND status = 'pending' AND next_attempt_at <= ?",
                    (jobId, now),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM knowledge_ingest_jobs"
                    " WHERE status = 'pending' AND next_attempt_at <= ?"
                    " ORDER BY created_at LIMIT 1",
                    (now,),
                ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE knowledge_ingest_jobs SET status = 'running',"
                " attempts = attempts + 1, next_attempt_at = ?, updated_at = ?"
                " WHERE job_id = ?",
                (now + leaseSeconds, _now(), row["job_id"]),
            )
            claimed = self._conn.execute(
                "SELECT * FROM knowledge_ingest_jobs WHERE job_id = ?", (row["job_id"],)
            ).fetchone()
        return dict(claimed)

    def ack(self, jobId: str, result: Dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE knowledge_ingest_jobs SET status = 'done', result_json = ?,"
                " last_error = '', updated_at = ? WHERE job_id = ?",
                (json.dumps(result, ensure_ascii=False), _now(), jobId),
            )

    def nack(self, jobId: str, error: str, retryable: bool = True) -> str:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT attempts, max_attempts FROM knowledge_ingest_jobs WHERE job_id = ?",
                (jobId,),
            ).fetchone()
            if row is None:
                return "missing"
            attempts = int(row["attempts"] or 0)
            maxAttempts = int(row["max_attempts"] or 1)
            if not retryable or attempts >= maxAttempts:
                status = "dead"
                nextAt = 0.0
            else:
                import time

                status = "pending"
                nextAt = time.time() + min(300.0, 2.0 ** attempts)
            self._conn.execute(
                "UPDATE knowledge_ingest_jobs SET status = ?, last_error = ?,"
                " next_attempt_at = ?, updated_at = ? WHERE job_id = ?",
                (status, str(error or "")[:500], nextAt, _now(), jobId),
            )
        return status

    def job(self, jobId: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_ingest_jobs WHERE job_id = ?", (jobId,)
            ).fetchone()
        return dict(row) if row else None

    def pendingJobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM knowledge_ingest_jobs WHERE status = 'pending'"
                " ORDER BY created_at LIMIT ?", (max(1, int(limit)),)
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> Dict[str, Any]:
        import time

        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM knowledge_ingest_jobs GROUP BY status"
            ).fetchall()
            counts = {row["status"]: int(row["n"]) for row in rows}
            oldest = self._conn.execute(
                "SELECT MIN(created_at) FROM knowledge_ingest_jobs WHERE status = 'pending'"
            ).fetchone()[0]
            dead = self._conn.execute(
                "SELECT last_error FROM knowledge_ingest_jobs WHERE status = 'dead'"
                " ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        age = None
        if oldest:
            try:
                age = round(time.time() - _parse(oldest).timestamp(), 1)
            except (ValueError, TypeError):
                age = None
        return {
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "done": counts.get("done", 0),
            "dead": counts.get("dead", 0),
            "oldest_pending_age_seconds": age,
            "last_dead_error": (dead["last_error"] if dead else ""),
        }


def _parse(stamp: str) -> datetime.datetime:
    value = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value


_queue: Optional[KnowledgeIngestQueue] = None
_queue_lock = threading.Lock()


def get_knowledge_ingest_queue(dbPath: Optional[str] = None) -> KnowledgeIngestQueue:
    global _queue
    with _queue_lock:
        if _queue is None or dbPath:
            _queue = KnowledgeIngestQueue(dbPath)
        return _queue


def reset_knowledge_ingest_queue() -> None:
    global _queue
    with _queue_lock:
        if _queue is not None:
            _queue.close()
        _queue = None
