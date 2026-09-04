"""MetaLedger — 元认知统一台账（V3 融合的单一事实源）

四套元认知实现（反思引擎/认知负荷/事件记录器/API stub）收敛于此：
- meta_events  : 认知事件（工具调用、过程事件；C 写穿透 + tool_executor 挂点）
- meta_records : 面向前端的记录（手动创建 + 反思报告产出）
- meta_states  : 认知负荷快照（B 写穿透，节流落库）

线程安全（RLock）、SQLite 落底、per-agent 保留上限裁剪、
env NEUROVA_META_LEDGER_DB 可覆盖路径（测试隔离，仿 NEUROVA_USAGE_HISTORY_DB 惯例）。

设计约束（修复教义）：所有元认知消费者只通过本台账读写，禁止再造平行存储。
"""

import datetime
import json
import os
import sqlite3
import threading

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_DB = os.path.join("data", "metacognition.db")

_DEFAULT_MAX_EVENTS = 2000
_DEFAULT_MAX_RECORDS = 1000
_DEFAULT_MAX_STATES = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    process_type TEXT NOT NULL,
    description TEXT,
    duration_ms REAL DEFAULT 0.0,
    success INTEGER DEFAULT 1,
    metadata TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meta_events_agent ON meta_events(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_meta_events_tool ON meta_events(agent_id, process_type, description);

CREATE TABLE IF NOT EXISTS meta_records (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    type TEXT NOT NULL,
    content TEXT,
    context TEXT,
    confidence REAL DEFAULT 0.5,
    metadata TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meta_records_agent ON meta_records(agent_id, created_at);

CREATE TABLE IF NOT EXISTS meta_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    load_level TEXT,
    load_score REAL,
    active_tasks INTEGER DEFAULT 0,
    memory_usage REAL DEFAULT 0.0,
    response_time_ms REAL DEFAULT 0.0,
    error_rate REAL DEFAULT 0.0,
    metadata TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meta_states_agent ON meta_states(agent_id, created_at);
"""


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class MetaLedger:
    """元认知统一台账：SQLite 三表 + RLock + per-agent 裁剪"""

    def __init__(
        self,
        db_path: str = "",
        max_events_per_agent: int = _DEFAULT_MAX_EVENTS,
        max_records_per_agent: int = _DEFAULT_MAX_RECORDS,
        max_states_per_agent: int = _DEFAULT_MAX_STATES,
    ):
        self._db_path = db_path or os.environ.get("NEUROVA_META_LEDGER_DB") or _DEFAULT_DB
        self._max_events = max_events_per_agent
        self._max_records = max_records_per_agent
        self._max_states = max_states_per_agent
        self._lock = threading.RLock()
        self._ensure_dir()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        logger.info("MetaLedger initialized: %s", self._db_path)

    def _ensure_dir(self) -> None:
        if self._db_path != ":memory:":
            parent = os.path.dirname(os.path.abspath(self._db_path))
            if parent:
                os.makedirs(parent, exist_ok=True)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # ────── events（C 语义：过程/工具事件） ──────

    def write_event(
        self,
        agent_id: str,
        process_type: str,
        description: str = "",
        duration_ms: float = 0.0,
        success: bool = True,
        metadata: dict = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta_events (agent_id, process_type, description, duration_ms, success, metadata, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    agent_id,
                    process_type,
                    description or "",
                    float(duration_ms or 0.0),
                    1 if success else 0,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    _now_iso(),
                ),
            )
            self._prune("meta_events", agent_id, self._max_events)
            self._conn.commit()

    def list_events(self, agent_id: str, limit: int = 100) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT process_type, description, duration_ms, success, metadata, created_at"
                " FROM meta_events WHERE agent_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
                (agent_id, int(limit)),
            ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "process_type": r[0],
                    "description": r[1],
                    "duration_ms": r[2],
                    "success": bool(r[3]),
                    "metadata": json.loads(r[4] or "{}"),
                    "created_at": r[5],
                }
            )
        return out

    def tool_success_rates(self, agent_id: str, min_calls: int = 5) -> dict:
        """按工具名聚合成功率（工具事件 = process_type='tool'）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT description, COUNT(*) AS calls, SUM(success) AS ok"
                " FROM meta_events WHERE agent_id=? AND process_type='tool'"
                " GROUP BY description HAVING calls >= ?",
                (agent_id, int(min_calls)),
            ).fetchall()
        return {r[0]: (r[2] / r[1]) if r[1] else 0.0 for r in rows}

    # ────── records（前端可见记录：手动创建 + 反思报告） ──────

    def create_record(
        self,
        agent_id: str,
        kind: str,
        type: str,
        content: str = "",
        context: str = "",
        confidence: float = 0.5,
        metadata: dict = None,
    ) -> str:
        import uuid

        rid = str(uuid.uuid4())[:12]
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta_records (id, agent_id, kind, type, content, context, confidence, metadata, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    agent_id,
                    kind,
                    type,
                    content or "",
                    context or "",
                    float(confidence),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    _now_iso(),
                ),
            )
            self._prune("meta_records", agent_id, self._max_records)
            self._conn.commit()
        return rid

    def list_records(
        self, agent_id: str, page: int = 1, size: int = 20, record_type: str = None, kind: str = None
    ) -> dict:
        with self._lock:
            where = "WHERE agent_id=?"
            args: list = [agent_id]
            if record_type:
                where += " AND type=?"
                args.append(record_type)
            if kind:
                where += " AND kind=?"
                args.append(kind)
            total = self._conn.execute(
                f"SELECT COUNT(*) FROM meta_records {where}", args
            ).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT id, kind, type, content, context, confidence, metadata, created_at"
                f" FROM meta_records {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                args + [int(size), (int(page) - 1) * int(size)],
            ).fetchall()
        items = [
            {
                "id": r[0],
                "kind": r[1],
                "type": r[2],
                "content": r[3],
                "context": r[4],
                "confidence": r[5],
                "metadata": json.loads(r[6] or "{}"),
                "created_at": r[7],
            }
            for r in rows
        ]
        return {"items": items, "total": total, "page": int(page), "size": int(size)}

    def record_stats(self, agent_id: str) -> dict:
        """统计投影 — 字段与前端 TS 契约逐字对齐：
        total_entries / by_type[{type,count}] / avg_confidence / recent_trend[{date,count}]
        只统计 kind='thought'（洞察/反思记录不计入条目统计）。"""
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM meta_records WHERE agent_id=? AND kind='thought'", (agent_id,)
            ).fetchone()[0]
            by_type_rows = self._conn.execute(
                "SELECT type, COUNT(*) FROM meta_records WHERE agent_id=? AND kind='thought' GROUP BY type",
                (agent_id,),
            ).fetchall()
            avg_conf = self._conn.execute(
                "SELECT AVG(confidence) FROM meta_records WHERE agent_id=? AND kind='thought'", (agent_id,)
            ).fetchone()[0]
            trend_rows = self._conn.execute(
                "SELECT substr(created_at, 1, 10) AS day, COUNT(*) FROM meta_records"
                " WHERE agent_id=? AND kind='thought' AND created_at >= ? GROUP BY day ORDER BY day",
                (agent_id, self._cutoff_iso(days=7)),
            ).fetchall()
        return {
            "total_entries": total,
            "by_type": [{"type": r[0], "count": r[1]} for r in by_type_rows],
            "avg_confidence": round(avg_conf, 3) if avg_conf is not None else 0,
            "recent_trend": [{"date": r[0], "count": r[1]} for r in trend_rows],
        }

    @staticmethod
    def _cutoff_iso(days: int) -> str:
        return (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        ).isoformat()

    def reflection_history(self, agent_id: str, limit: int = 20) -> list:
        """反思报告时间线（kind='reflection' 的记录，供前端历史表）。"""
        result = self.list_records(agent_id=agent_id, page=1, size=limit)
        return [
            {
                "created_at": it["created_at"],
                "confidence": it["confidence"],
                "trigger": (it["metadata"] or {}).get("trigger", "manual"),
                "summary": it["content"][:200],
            }
            for it in result["items"]
            if it["kind"] == "reflection"
        ]

    # ────── states（B 语义：认知负荷快照） ──────

    def write_state(
        self,
        agent_id: str,
        load_level: str,
        load_score: float,
        active_tasks: int = 0,
        memory_usage: float = 0.0,
        response_time_ms: float = 0.0,
        error_rate: float = 0.0,
        metadata: dict = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta_states (agent_id, load_level, load_score, active_tasks,"
                " memory_usage, response_time_ms, error_rate, metadata, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    agent_id,
                    load_level,
                    float(load_score),
                    int(active_tasks),
                    float(memory_usage),
                    float(response_time_ms),
                    float(error_rate),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    _now_iso(),
                ),
            )
            self._prune("meta_states", agent_id, self._max_states)
            self._conn.commit()

    def latest_state(self, agent_id: str):
        with self._lock:
            row = self._conn.execute(
                "SELECT load_level, load_score, active_tasks, memory_usage, response_time_ms,"
                " error_rate, metadata, created_at FROM meta_states WHERE agent_id=?"
                " ORDER BY created_at DESC, id DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "load_level": row[0],
            "load_score": row[1],
            "active_tasks": row[2],
            "memory_usage": row[3],
            "response_time_ms": row[4],
            "error_rate": row[5],
            "metadata": json.loads(row[6] or "{}"),
            "created_at": row[7],
        }

    def state_history(self, agent_id: str, limit: int = 30) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT load_level, load_score, active_tasks, memory_usage, response_time_ms,"
                " error_rate, metadata, created_at FROM meta_states WHERE agent_id=?"
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (agent_id, int(limit)),
            ).fetchall()
        return [
            {
                "load_level": r[0],
                "load_score": r[1],
                "active_tasks": r[2],
                "memory_usage": r[3],
                "response_time_ms": r[4],
                "error_rate": r[5],
                "metadata": json.loads(r[6] or "{}"),
                "created_at": r[7],
            }
            for r in rows
        ]

    # ────── 内部 ──────

    def _prune(self, table: str, agent_id: str, max_rows: int) -> None:
        """per-agent 保留上限裁剪（调用方必须已持锁）。"""
        if max_rows <= 0:
            return
        self._conn.execute(
            f"DELETE FROM {table} WHERE agent_id=? AND id NOT IN ("
            f"  SELECT id FROM {table} WHERE agent_id=? ORDER BY created_at DESC, id DESC LIMIT ?"
            f")",
            (agent_id, agent_id, max_rows),
        )


# ────── 单例注册表 ──────

_ledger_instances: dict = {}
_ledger_lock = threading.Lock()


def get_meta_ledger(name: str = "default", db_path: str = "") -> MetaLedger:
    """获取台账单例（per-name；chat 管线/工具执行器/API 全走这里）。"""
    with _ledger_lock:
        if name not in _ledger_instances:
            _ledger_instances[name] = MetaLedger(db_path=db_path) if db_path else MetaLedger()
        return _ledger_instances[name]


def reset_meta_ledger(name: str = None) -> None:
    """重置单例（测试隔离用；不删磁盘数据）。"""
    with _ledger_lock:
        if name is None:
            for inst in _ledger_instances.values():
                inst.close()
            _ledger_instances.clear()
        else:
            inst = _ledger_instances.pop(name, None)
            if inst:
                inst.close()
