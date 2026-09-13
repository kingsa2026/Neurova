# -*- coding: utf-8 -*-
"""知识摄取持久队列（Yuxi 对比 P1 #9：Durable Task 化）。

channel_ingress_queue 同型、按知识面裁剪：
  - SQLite（版本域 knowledge_ingress）+ dedupe_key UNIQUE 幂等 + FIFO claim
    + 租约（过期可接管）+ max_attempts 死信 + 启动 reconcile（processing→
    pending 崩溃重跑）；
  - 上传字节落 `data/knowledge_ingress/files/<task_id>__<safe-name>`，任务行
    只存路径引用（不把 BLOB 塞 payload）；done 后文件删除，dead 保留供排查；
  - drain 循环由 app 启动装配（in-process asyncio + to_thread），失败 nack。

与同步路径的行为差异（如实）：异步任务不做图谱抽取（`_try_extract_to_graph`
依赖 Request/app state），result.graph="skipped_async"——需要图谱联动走
sync=true。SSRF 等安全校验保持在端点层（入队前），不因异步而后置。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.db_migration import migrate as apply_migrations, register_migration
from neurova.core.logger import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_ingress_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    dedupe_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    filename TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    storage_path TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT 'default',
    user_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    result_ids TEXT NOT NULL DEFAULT '[]',
    claimed_by TEXT,
    claimed_at REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_ingress_status ON knowledge_ingress_events(status, id);
"""
register_migration(1, _SCHEMA, domain="knowledge_ingress")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def task_status(row: Optional[Dict[str, Any]]) -> str:
    return (row or {}).get("status") or "unknown"


class KnowledgeIngressQueue:
    """知识摄取任务队列（每实例一连接，threading.Lock 串行写）。"""

    def __init__(
        self,
        db_path=None,
        files_dir=None,
        max_attempts: int = 3,
        lease_seconds: float = 120.0,
    ):
        base = Path("data/knowledge_ingress")
        self.db_path = str(db_path or base / "ingress.db")
        self.files_dir = Path(files_dir or base / "files")
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        with self._lock, self._conn:
            apply_migrations(self._conn, "knowledge_ingress")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── 生产侧 ──────────────────────────────────────────────────

    def enqueue_upload(self, filename: str, data: bytes, agent_id: str, user_id: str) -> Dict[str, Any]:
        digest = hashlib.sha256(data).hexdigest()
        dedupe = f"up:{digest}:{agent_id}:{user_id}"
        task_id = f"kin_{digest[:12]}_{os.urandom(4).hex()}"
        safe = _SAFE_NAME.sub("_", filename or "imported")[:80]
        storage = self.files_dir / f"{task_id}__{safe}"
        storage.write_bytes(data)
        return self._insert(
            task_id=task_id, dedupe=dedupe, source="upload", filename=filename or "",
            url="", storage_path=str(storage), agent_id=agent_id, user_id=user_id,
            on_conflict_storage=storage,
        )

    def enqueue_url(self, url: str, title_hint: str, agent_id: str, user_id: str) -> Dict[str, Any]:
        digest = hashlib.sha256(url.encode()).hexdigest()
        dedupe = f"url:{digest}:{agent_id}:{user_id}"
        task_id = f"kin_{digest[:12]}_{os.urandom(4).hex()}"
        return self._insert(
            task_id=task_id, dedupe=dedupe, source="url", filename=title_hint or "",
            url=url, storage_path="", agent_id=agent_id, user_id=user_id, on_conflict_storage=None,
        )

    def _insert(self, *, task_id, dedupe, source, filename, url, storage_path,
                agent_id, user_id, on_conflict_storage) -> Dict[str, Any]:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO knowledge_ingress_events (task_id, dedupe_key, source,"
                " filename, url, storage_path, agent_id, user_id, status, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?, 'pending', ?, ?)",
                (task_id, dedupe, source, filename, url, storage_path, agent_id, user_id,
                 _now_iso(), _now_iso()),
            )
            if cur.rowcount == 0:
                # 重复内容：删本次临时文件，复用既有任务（幂等语义）
                if on_conflict_storage and on_conflict_storage.exists():
                    try:
                        on_conflict_storage.unlink()
                    except OSError:
                        pass
                row = self._conn.execute(
                    "SELECT * FROM knowledge_ingress_events WHERE dedupe_key=?", (dedupe,)
                ).fetchone()
                # done 的重投不复活（内容已入库）；其余状态原样返回
                d = dict(row)
                d["replayed"] = True
                return d
        return self.get(task_id) or {"task_id": task_id, "status": "pending"}

    # ── 消费侧 ──────────────────────────────────────────────────

    def claim(self, worker: str = "drain") -> Optional[Dict[str, Any]]:
        with self._lock, self._conn:
            now = time.time()
            row = self._conn.execute(
                "SELECT * FROM knowledge_ingress_events WHERE status='pending'"
                " OR (status='processing' AND (claimed_at IS NULL OR claimed_at < ?))"
                " ORDER BY id LIMIT 1",
                (now - self.lease_seconds,),
            ).fetchone()
            if not row:
                return None
            self._conn.execute(
                "UPDATE knowledge_ingress_events SET status='processing', claimed_by=?,"
                " claimed_at=?, attempt=attempt+1, updated_at=? WHERE task_id=?",
                (worker, now, _now_iso(), row["task_id"]),
            )
            return dict(row)

    def ack(self, task_id: str, item_ids: Optional[List[str]] = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE knowledge_ingress_events SET status='done', error=NULL, result_ids=?,"
                " claimed_by=NULL, claimed_at=NULL, updated_at=? WHERE task_id=?",
                (json.dumps(item_ids or []), _now_iso(), task_id),
            )
        self._cleanup_file(task_id)

    def nack(self, task_id: str, error: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE knowledge_ingress_events SET"
                " status=CASE WHEN attempt >= ? THEN 'dead' ELSE 'pending' END,"
                " error=?, claimed_by=NULL, claimed_at=NULL, updated_at=? WHERE task_id=?",
                (self.max_attempts, error[:500], _now_iso(), task_id),
            )

    def dead(self, task_id: str, error: str) -> None:
        """确定性失败直入死信（不耗尽 attempts——如抽取失败/暂存文件缺失，
        重试无意义）。文件保留供排查。"""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE knowledge_ingress_events SET status='dead', error=?,"
                " claimed_by=NULL, claimed_at=NULL, updated_at=? WHERE task_id=?",
                (error[:500], _now_iso(), task_id),
            )

    def _cleanup_file(self, task_id: str) -> None:
        row = self.get(task_id)
        path = (row or {}).get("storage_path")
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass

    # ── 对账/观测 ───────────────────────────────────────────────

    def reconcile_at_startup(self) -> List[str]:
        """崩溃恢复：processing 行归 pending（drain 重跑——_import_file_data
        以内容哈希 dedupe 幂等，不会重复建条目）。"""
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT task_id FROM knowledge_ingress_events WHERE status='processing'"
            ).fetchall()
            if rows:
                self._conn.execute(
                    "UPDATE knowledge_ingress_events SET status='pending', claimed_by=NULL,"
                    " claimed_at=NULL, updated_at=? WHERE status='processing'",
                    (_now_iso(),),
                )
        ids = [r["task_id"] for r in rows]
        if ids:
            logger.info("知识摄取队列启动收敛: %d 个 processing→pending", len(ids))
        return ids

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_ingress_events WHERE task_id=?", (task_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM knowledge_ingress_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            counts = {s: 0 for s in ("pending", "processing", "done", "dead")}
            for status, n in self._conn.execute(
                "SELECT status, COUNT(*) FROM knowledge_ingress_events GROUP BY status"
            ).fetchall():
                if status in counts:
                    counts[status] = int(n)
        return counts


# ── 单例工厂 ──────────────────────────────────────────────────────
_queue: Optional[KnowledgeIngressQueue] = None
_queue_lock = threading.Lock()


def get_ingress_queue() -> KnowledgeIngressQueue:
    global _queue
    with _queue_lock:
        if _queue is None:
            _queue = KnowledgeIngressQueue()
        return _queue


def reset_ingress_queue() -> None:
    global _queue
    with _queue_lock:
        _queue = None
