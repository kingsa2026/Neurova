"""Supervisor 任务结果的持久幂等账本（SQLite）。

内存缓存只能保证单进程生命周期内不重放；重启或多 Worker 场景下同 `task_id`
会再次执行。这里把最终结果落盘，`SupervisorOrchestrator` 生产装配接本账本，
测试默认仍可用内存缓存。
"""
from __future__ import annotations

import datetime
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from neurova.core.data_root import dataPath
from neurova.core.db_migration import migrate as applyMigrations, register_migration

_DOMAIN = "agent_supervisor_tasks"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_supervisor_tasks (
    task_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_supervisor_tasks_updated
    ON agent_supervisor_tasks(updated_at);
"""
register_migration(1, _SCHEMA, domain=_DOMAIN)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class SupervisorTaskLedger:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._path = db_path or dataPath("agent_supervisor", "tasks.db")
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        applyMigrations(self._conn, _DOMAIN)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get(self, taskId: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agent_supervisor_tasks WHERE task_id = ?", (taskId,)
            ).fetchone()
        if row is None:
            return None
        try:
            result = json.loads(row["result_json"] or "{}")
        except (ValueError, TypeError):
            return None
        if not isinstance(result, dict):
            return None
        return result

    def save(self, taskId: str, result: Dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO agent_supervisor_tasks (task_id, trace_id, result_json,"
                " updated_at) VALUES (?,?,?,?)"
                " ON CONFLICT(task_id) DO UPDATE SET trace_id = excluded.trace_id,"
                " result_json = excluded.result_json, updated_at = excluded.updated_at",
                (taskId, str(result.get("trace_id") or ""),
                 json.dumps(result, ensure_ascii=False), _now()),
            )

    def clear(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM agent_supervisor_tasks")


_ledger: Optional[SupervisorTaskLedger] = None
_ledger_lock = threading.Lock()


def get_supervisor_ledger(dbPath: Optional[str] = None) -> SupervisorTaskLedger:
    global _ledger
    with _ledger_lock:
        if _ledger is None or dbPath:
            _ledger = SupervisorTaskLedger(dbPath)
        return _ledger


def reset_supervisor_ledger() -> None:
    global _ledger
    with _ledger_lock:
        if _ledger is not None:
            _ledger.close()
        _ledger = None
