# -*- coding: utf-8 -*-
"""渠道出口失败台账（批 F）。

立项理由（docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md 批 F）：
`ChannelManager.send_message` 的失败片此前只有告警日志——无台账行、无重试、
无死信归宿，失败是半静默的。入站侧有持久队列（`channel_ingress_queue`）兜
可靠性，出口侧的失败连可查的记录都没有。本模块给失败片一个**可查的归宿**：
重试仍败 → 落一行（渠道/会话/agent/片序/尝试数/原因/内容头），按渠道与会话
可过滤读出。

域边界：本台账只记**出口**失败。回合级错误（chat_error）归
`core/agent_run_ledger`（回合结算点早于出站，两域不合并）；入站去重归
`channel_ingress_queue`。各自补域空白不是造第二份。

存储纪律：单 SQLite 文件 + `threading.RLock` + WAL（AGENTS.md §3）；路径走
`callerPath`（env `NEUROVA_CHANNEL_OUTBOUND_LEDGER_DB` 可覆盖），与入站队列
同款。打开失败由调用方退化为只告警（点名日志），台账问题不阻断发送主流程。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbound_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    channel_type TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT 'default',
    part_index INTEGER NOT NULL,
    total_parts INTEGER NOT NULL,
    attempts INTEGER NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    content_head TEXT NOT NULL DEFAULT ''
)
"""

#: 内容头截断长度——台账是定位线索不是全文存档（全文在会话回写与日志里）
CONTENT_HEAD_CHARS = 80


class OutboundFailureLedger:
    """出口失败片的持久归宿（追加写 + 过滤读）。"""

    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._conn:
            self._conn.execute(_SCHEMA)

    def recordFailure(
        self,
        *,
        channel_type: str,
        chat_id: str,
        agent_id: str = "default",
        part_index: int,
        total_parts: int,
        attempts: int,
        error: str = "",
        content: str = "",
    ) -> int:
        """落一行失败片；返回行 id（调用方只用于日志点名）。"""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO outbound_failures (ts, channel_type, chat_id, agent_id,"
                " part_index, total_parts, attempts, error, content_head)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    time.time(),
                    channel_type,
                    chat_id,
                    agent_id or "default",
                    int(part_index),
                    int(total_parts),
                    int(attempts),
                    error or "",
                    (content or "")[:CONTENT_HEAD_CHARS],
                ),
            )
            return int(cur.lastrowid)

    def queryFailures(
        self, *, channel_type: str = "", chat_id: str = "", limit: int = 100
    ) -> List[Dict[str, Any]]:
        """按渠道/会话过滤倒序读——"哪个会话在丢片"必须查得到。"""
        clauses, params = [], []
        if channel_type:
            clauses.append("channel_type = ?")
            params.append(channel_type)
        if chat_id:
            clauses.append("chat_id = ?")
            params.append(chat_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, channel_type, chat_id, agent_id, part_index,"
                " total_parts, attempts, error, content_head"
                f" FROM outbound_failures {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        keys = ("id", "ts", "channel_type", "chat_id", "agent_id", "part_index",
                "total_parts", "attempts", "error", "content_head")
        return [dict(zip(keys, r)) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_BYPASS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingress_bypass (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    channel_type TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT ''
)
"""


class ChannelBypassLedger:
    """入站旁路台账（批 D，T4 已裁有界直发）：队列不可用时的直发必须留痕——
    旁路计数成为常驻读数后，队列可用性本身有了事实判据。

    与 OutboundFailureLedger 同库同族（"出入口可观测单源族"）：一个 SQLite
    文件两张表，不另建第二份库。打开失败由调用方退化为只告警（点名退化）。
    """

    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._conn:
            self._conn.execute(_BYPASS_SCHEMA)

    def recordBypass(self, *, channel_type: str, chat_id: str,
                     message_id: str, reason: str = "") -> int:
        """落一行旁路直发；返回行 id。"""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO ingress_bypass (ts, channel_type, chat_id, message_id, reason)"
                " VALUES (?,?,?,?,?)",
                (time.time(), channel_type or "", chat_id or "", message_id or "", reason or ""),
            )
            return int(cur.lastrowid)

    def queryBypass(self, *, channel_type: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        """按渠道过滤倒序读。"""
        clauses, params = [], []
        if channel_type:
            clauses.append("channel_type = ?")
            params.append(channel_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, channel_type, chat_id, message_id, reason"
                f" FROM ingress_bypass {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        keys = ("id", "ts", "channel_type", "chat_id", "message_id", "reason")
        return [dict(zip(keys, r)) for r in rows]

    def countBypass(self) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM ingress_bypass").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()
