"""桌面动作审计（CUA Phase 3 立项 R3-4，docs/Neurova_CUA_Phase3立项_2026-09-12.md §3）

所有 computer_*/browser_* 动作（本地 / 远程会话平面 / MCP 导出三入口同源，
统一收口在 tool_executor 分发咽喉点）落一行**元数据白名单**审计。

隐私红线（立项书成文约束，机械测试强制）：
- 永不存截图 base64、键入文本、set_value 内容、shell 命令原文
- 表列集合 == ALLOWED_COLUMNS；目标字段只存窗口标题或 URL host（无路径/查询）

存储：data/desktop_action_audit.db（SQLite，WAL + RLock；与 approval/usage
同型）。审计失败只告警不抛出——审计永远不阻断工具执行。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_DB = "data/desktop_action_audit.db"

# 隐私白名单：审计表全部列（红线不可漂移——测试逐列比对）
ALLOWED_COLUMNS = (
    "ts",
    "user_id",
    "agent_id",
    "session_id",
    "tool_name",
    "success",
    "duration_ms",
    "effect",
    "route",
    "delivery",
    "refusal_code",
    "evidence",
    "target",
    "needs_human",
)

# 需人工关注的效果档位（unverifiable/suspected_noop=结果存疑；refused=被拒）
_HUMAN_EFFECTS = frozenset({"refused", "unverifiable", "suspected_noop"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS desktop_action_audit (
    ts REAL NOT NULL,
    user_id TEXT,
    agent_id TEXT,
    session_id TEXT,
    tool_name TEXT NOT NULL,
    success INTEGER,
    duration_ms REAL,
    effect TEXT,
    route TEXT,
    delivery TEXT,
    refusal_code TEXT,
    evidence TEXT,
    target TEXT,
    needs_human INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_daa_ts ON desktop_action_audit(ts);
CREATE INDEX IF NOT EXISTS idx_daa_user ON desktop_action_audit(user_id);
CREATE INDEX IF NOT EXISTS idx_daa_tool ON desktop_action_audit(tool_name);
"""


def _target_of(tool_name: str, params: Dict[str, Any]) -> Optional[str]:
    """目标事实：只取窗口标题或 URL host——路径/查询/参数一律丢弃（隐私红线）。"""
    if not isinstance(params, dict):
        return None
    title = params.get("window_title")
    if title:
        return str(title)[:200]
    # SSH 远程命令：审计目标记 host（命令内容按红线不存）
    host = params.get("host")
    if host:
        return str(host)[:200]
    url = params.get("url")
    if url:
        try:
            host = urlparse(str(url)).hostname  # hostname 不含端口（netloc 含）
            return host[:200] if host else None
        except Exception:
            return None
    return None


def extract_audit_meta(tool_name: str, params: Dict[str, Any], result: Any) -> Dict[str, Any]:
    """从工具结果提取审计元数据（白名单字段）。纯函数，供测试与写入共用。"""
    ar: Dict[str, Any] = {}
    success: Optional[int] = None
    if isinstance(result, dict):
        raw_ar = result.get("action_result")
        if isinstance(raw_ar, dict):
            ar = raw_ar
        if "success" in result:
            success = 1 if result.get("success") else 0
    effect = ar.get("effect")
    refusal = ar.get("refusal_code")
    evidence = ar.get("evidence")
    needs_human = 1 if (refusal or (effect in _HUMAN_EFFECTS)) else 0
    return {
        "effect": effect,
        "route": ar.get("route"),
        "delivery": ar.get("delivery"),
        "refusal_code": refusal,
        "evidence": json.dumps(evidence, ensure_ascii=False) if evidence else None,
        "target": _target_of(tool_name, params),
        "success": success,
        "needs_human": needs_human,
    }


class DesktopAuditStore:
    """桌面动作审计存储（元数据白名单，SQLite WAL）。"""

    def __init__(self, db_path: str = _DEFAULT_DB):
        self._db_path = db_path
        self._lock = threading.RLock()
        if db_path != ":memory:":
            from pathlib import Path as _P

            parent = _P(db_path).parent
            if str(parent) and str(parent) != ".":
                parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # :memory: 等模式不支持 WAL，默认 journal 即可
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── 写入 ──────────────────────────────────────────────────

    def record_computer_action(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: Any,
        duration_ms: float,
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[int]:
        """写一条审计；任何失败只告警返回 None（审计永不阻断工具流）。"""
        try:
            meta = extract_audit_meta(tool_name, params, result)
            row = (
                time.time(),
                user_id,
                agent_id,
                session_id,
                str(tool_name),
                meta["success"],
                float(duration_ms),
                meta["effect"],
                meta["route"],
                meta["delivery"],
                meta["refusal_code"],
                meta["evidence"],
                meta["target"],
                meta["needs_human"],
            )
            return self._insert(row)
        except Exception as e:  # noqa: BLE001
            logger.warning("桌面动作审计写入失败（不阻断）: %s", e)
            return None

    def _insert(self, row: tuple) -> int:
        with self._lock:
            cur = self._conn.execute(
                f"INSERT INTO desktop_action_audit ({','.join(ALLOWED_COLUMNS)}) "
                f"VALUES ({','.join('?' * len(ALLOWED_COLUMNS))})",
                row,
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    # ── 查询 ──────────────────────────────────────────────────

    def query_actions(
        self,
        *,
        tool: Optional[str] = None,
        user: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        needs_human: Optional[bool] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        args: List[Any] = []
        if tool:
            clauses.append("tool_name=?")
            args.append(tool)
        if user:
            clauses.append("user_id=?")
            args.append(user)
        if since is not None:
            clauses.append("ts>=?")
            args.append(since)
        if until is not None:
            clauses.append("ts<=?")
            args.append(until)
        if needs_human is not None:
            clauses.append("needs_human=?")
            args.append(1 if needs_human else 0)
        sql = "SELECT * FROM desktop_action_audit"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(max(1, min(int(limit), 5000)))
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    # ── 保留策略（TTL，防膨胀——立项 §3.4 风险行）──────────────

    def purge_older_than(self, days: int) -> int:
        cutoff = time.time() - days * 86400
        with self._lock:
            cur = self._conn.execute("DELETE FROM desktop_action_audit WHERE ts<?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass


# ── 单例工厂（get_*/reset_* 项目惯例）──────────────────────────

_store: Optional[DesktopAuditStore] = None
_store_lock = threading.Lock()


def get_desktop_audit_store(db_path: str = _DEFAULT_DB) -> DesktopAuditStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = DesktopAuditStore(db_path=db_path)
        return _store


def reset_desktop_audit_store() -> None:
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = None
