"""渠道入站持久化队列（OpenClaw 启发 P0-5）

对位 OpenClaw `src/channels/message/ingress-queue.ts`：入站消息先持久化
再分发——SQLite channel_ingress_events 表 + claim 租约 + tombstone 幂等
去重 + attempt 计数 + dead-letter + requeue，重启不丢消息。

与 OpenClaw 的取舍差异：
  - OC 是多 lane 串行排水 + ack 策略四档；Neurova 14 渠道适配器入站是
    单线程事件回调，这里提供 start_drain 单排水循环（按 chat_id lane
    串行语义由"单 worker 顺序 claim"保证），ack 策略固定
    after_agent_dispatch（handler 返回即 ack，异常 nack 重试）。
  - 毒消息防护：max_attempts 次失败进 dead-letter，可人工 requeue。

接入契约（manager._on_channel_event）：
  enqueue() 只做持久化（fail-open：DB 不可用时返回 False，调用方直发）；
  排水循环由 start_drain 驱动； ChannelManager.start() 启动排水，
  停止时 stop_drain。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from neurova.channels.base import ChannelMessage
from neurova.core.logger import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_ingress_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_type TEXT NOT NULL,
    message_id TEXT NOT NULL,
    chat_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 0,
    dedupe_key TEXT NOT NULL UNIQUE,
    last_error TEXT,
    claimed_by TEXT,
    claimed_at REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingress_status ON channel_ingress_events(status, id);
"""

# payload ↔ ChannelMessage 的往返由 dataclasses.asdict/from_dict 承担
# （timestamp ISO 往返，raw_event/metadata JSON 内嵌）


@dataclass
class IngressEvent:
    """排水循环交付给 handler 的事件。"""

    event_id: int
    message: ChannelMessage
    attempt: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ChannelIngressQueue:
    """入站持久化队列（每实例一个 SQLite 连接，threading.Lock 串行写）。"""

    def __init__(self, db_path, max_attempts: int = 3, lease_seconds: float = 120.0):
        self.db_path = str(db_path)
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)
            # 启动恢复（重启不丢消息）：崩溃时遗留的 processing 租约重置回
            # pending，排水循环可重新 claim。单实例内 claim 由 drain 任务
            # 立即消费，重置不产生重复投递。
            self._conn.execute(
                "UPDATE channel_ingress_events SET status='pending', claimed_by=NULL,"
                " claimed_at=NULL WHERE status='processing'"
            )
        self._drain_task: Optional[asyncio.Task] = None
        self._stopping = False
        self._processed_total = 0

    def close(self):
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # 生产侧
    # ------------------------------------------------------------------

    def enqueue(self, message: ChannelMessage) -> bool:
        """消息持久化。tombstone 去重：同 (channel_type, message_id) 幂等。

        已 done 的重复投递（平台消息重发）重开为 pending 再投一次。

        Returns:
            True=新入队/重开；False=重复消息（去重忽略）
        """
        from dataclasses import asdict

        payload = asdict(message)
        payload["timestamp"] = message.timestamp.isoformat()
        dedupe_key = f"{message.channel_type}:{message.message_id}"
        with self._lock:
            try:
                with self._conn:
                    cur = self._conn.execute(
                        "INSERT OR IGNORE INTO channel_ingress_events"
                        " (channel_type, message_id, chat_id, payload, status, dedupe_key,"
                        "  created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                        (
                            message.channel_type,
                            message.message_id,
                            message.chat_id,
                            json.dumps(payload, ensure_ascii=False, default=str),
                            "pending",
                            dedupe_key,
                            _now_iso(),
                            _now_iso(),
                        ),
                    )
                    if cur.rowcount > 0:
                        return True
                    # 已存在：终态 done 的重投重开，其余（pending/processing/dead）去重
                    row = self._conn.execute(
                        "SELECT status FROM channel_ingress_events WHERE dedupe_key=?",
                        (dedupe_key,),
                    ).fetchone()
                    if row and row[0] == "done":
                        self._conn.execute(
                            "UPDATE channel_ingress_events SET status='pending', attempt=0,"
                            " updated_at=? WHERE dedupe_key=?",
                            (_now_iso(), dedupe_key),
                        )
                        return True
            except sqlite3.Error as e:
                logger.error("Ingress enqueue failed (fail-open to direct dispatch): %s", e)
                return False
            return False

    # ------------------------------------------------------------------
    # 消费侧
    # ------------------------------------------------------------------

    def claim(self, worker: str = "drain") -> Optional[IngressEvent]:
        """按 FIFO claim 一条 pending/过期租约的消息（租约防并发重复投递）。"""
        with self._lock:
            now = time.time()
            row = self._conn.execute(
                "SELECT id, payload, attempt, status, claimed_at FROM channel_ingress_events"
                " WHERE status='pending'"
                "    OR (status='processing' AND (claimed_at IS NULL OR claimed_at < ?))"
                " ORDER BY id LIMIT 1",
                (now - self.lease_seconds,),
            ).fetchone()
            if not row:
                return None
            event_id, payload, attempt, status, _ = row
            with self._conn:
                self._conn.execute(
                    "UPDATE channel_ingress_events SET status='processing', claimed_by=?,"
                    " claimed_at=?, attempt=?, updated_at=? WHERE id=?",
                    (worker, now, attempt + 1, _now_iso(), event_id),
                )
        try:
            msg = self._payload_to_message(json.loads(payload))
        except Exception as e:
            logger.error("Ingress payload decode failed for #%s: %s", event_id, e)
            self.nack(event_id)
            return None
        return IngressEvent(event_id=event_id, message=msg, attempt=attempt + 1)

    @staticmethod
    def _payload_to_message(data: dict) -> ChannelMessage:
        from datetime import datetime as _dt

        data = dict(data)
        ts = data.get("timestamp")
        if isinstance(ts, str):
            try:
                data["timestamp"] = _dt.fromisoformat(ts)
            except ValueError:
                data["timestamp"] = datetime.now(timezone.utc)
        return ChannelMessage(**data)

    def ack(self, event_id: int):
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE channel_ingress_events SET status='done', updated_at=? WHERE id=?",
                (_now_iso(), event_id),
            )
        self._processed_total += 1

    def nack(self, event_id: int, error: str = ""):
        """失败回列；超过 max_attempts 进 dead-letter。"""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE channel_ingress_events SET"
                " status=CASE WHEN attempt >= ? THEN 'dead' ELSE 'pending' END,"
                " last_error=?, claimed_by=NULL, claimed_at=NULL, updated_at=? WHERE id=?",
                (self.max_attempts, error[:500], _now_iso(), event_id),
            )

    # ------------------------------------------------------------------
    # 排水循环
    # ------------------------------------------------------------------

    def start_drain(self, handler: Callable, poll_interval: float = 0.5):
        """启动排水循环（handler: async (ChannelMessage) -> reply|None）。

        在 running loop 缺席时（同步上下文/重启恢复）退化为按需排空。
        """
        if self._drain_task is not None:
            return
        self._stopping = False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            self._drain_task = loop.create_task(self._drain_loop(handler, poll_interval))

    async def _drain_loop(self, handler: Callable, poll_interval: float):
        while not self._stopping:
            ev = await asyncio.to_thread(self.claim, "drain")
            if ev is None:
                await asyncio.sleep(poll_interval)
                continue
            try:
                await handler(ev.message)
            except Exception as e:  # noqa: BLE001 - 失败 nack 重试，绝不丢消息
                logger.warning("Ingress handler failed (attempt=%s): %s", ev.attempt, e)
                await asyncio.to_thread(self.nack, ev.event_id, str(e))
            else:
                await asyncio.to_thread(self.ack, ev.event_id)

    async def stop_drain(self):
        self._stopping = True
        if self._drain_task is not None:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except (asyncio.CancelledError, Exception):
                pass
            self._drain_task = None

    # ------------------------------------------------------------------
    # 观测与运维
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT"
                " SUM(status='pending'), SUM(status='processing'), SUM(status='dead')"
                " FROM channel_ingress_events"
            ).fetchone()
            processed = self._conn.execute(
                "SELECT COUNT(*) FROM channel_ingress_events WHERE status='done'"
            ).fetchone()[0]
        return {
            "pending": int(row[0] or 0),
            "processing": int(row[1] or 0),
            "dead_letter": int(row[2] or 0),
            "processed_total": processed,
        }

    def list_dead_letters(self, limit: int = 50) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, channel_type, message_id, last_error, created_at"
                " FROM channel_ingress_events WHERE status='dead' ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "channel_type": r[1],
                "message_id": r[2],
                "last_error": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    def requeue_dead_letters(self) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE channel_ingress_events SET status='pending', attempt=0,"
                " last_error=NULL, updated_at=? WHERE status='dead'",
                (_now_iso(),),
            )
            return cur.rowcount
