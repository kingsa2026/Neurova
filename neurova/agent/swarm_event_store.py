# -*- coding: utf-8 -*-
"""全局单调序事件库（参照系 ac 借鉴 A2）：append 全局 seq、按流重放、
预算内 replay 否则降级快照、保留窗口清理（先发布 pruned-through 边界）。

与 H-4 逐 run JSONL 账本（swarm_event_log）的关系：JSONL 仍是逐 run 投影，
本模块提供**全仓一条全局单调 seq** 的 SQLite 事件库，供断线重连重放
（after_seq 增量）与降级快照（cursor 过旧/超预算）使用；双写经
:func:`mirrorFromLedger` 按 event_id 幂等，不重放副作用。

schema 经 `db_migration.register_migration` 登记（domain=swarm_event_store），
应用入口复用 `db_migration.migrate`：user_version 按域推进、已应用版本自动
跳过、库版本高于代码已知版本时按防降级语义拒绝（SchemaVersionError）。

线程模型：单连接（check_same_thread=False）+ threading.RLock 短临界区
（AGENTS.md §3）；seq 由 SQLite AUTOINCREMENT 分配，即使修剪删行也绝不
回退复用。重放协议铁律：**绝不部分回放**——预算超限只返回从 after_seq+1
起的连续前缀并置 degraded=True；cursor 落在 pruned-through 之下（区间内
可能有已删空洞）同样置 degraded=True、events 置空，调用方据此降级快照。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.db_migration import migrate as _applyDomainMigrations
from neurova.core.db_migration import register_migration

EVENT_STORE_DB_DOMAIN = "swarm_event_store"

DEFAULT_KEEP_WINDOW_S = 24 * 3600.0        # D-E 拍板：保留 1 天
DEFAULT_REPLAY_MAX_EVENTS = 5000
DEFAULT_REPLAY_MAX_BYTES = 4 * 1024 * 1024

_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS swarm_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id TEXT NOT NULL,
    event_id TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    command_id TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL DEFAULT '',
    occurred_ts REAL NOT NULL DEFAULT 0
);
-- event_id 非空时全库唯一（幂等双写的根）；空串行不参与唯一约束
CREATE UNIQUE INDEX IF NOT EXISTS idx_swarm_events_event_id
    ON swarm_events(event_id) WHERE event_id <> '';
CREATE INDEX IF NOT EXISTS idx_swarm_events_stream_seq
    ON swarm_events(stream_id, seq);
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# 模块级登记（与 api/auth.py 的 auth_blacklist、core/command_receipt.py 同范式）：
# import 即入登记表可审计；register_migration 对同版本重复注册幂等忽略，
# SwarmEventStore.ensureSchema 内再注册一次亦安全。
register_migration(_SCHEMA_VERSION, _SCHEMA, domain=EVENT_STORE_DB_DOMAIN)

_EVENT_COLUMNS = (
    "seq, stream_id, event_id, type, payload_json, command_id, occurred_at"
)

_INSERT_SQL = (
    "INSERT INTO swarm_events "
    "(stream_id, event_id, type, payload_json, command_id, occurred_at, occurred_ts) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)

_META_PRUNED_THROUGH = "pruned_through"


class SwarmEventStoreError(Exception):
    """全局事件库基础异常（入参/数据完整性等本域错误）。"""


def _occurredTs(occurredAt: str) -> float:
    """把 ISO occurred_at 折算成 epoch 秒（无时区按 UTC；解析失败按当下）。

    pruneCovered 用数值比较判定保留窗口，避免在 SQL 里解析带时区的 ISO 串。
    """
    raw = str(occurredAt or "").strip()
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
    return time.time()


def _rowToEvent(row: Tuple) -> Dict[str, Any]:
    """行 → 契约事件形态：{seq, stream_id, event_id, type, payload,
    command_id, occurred_at}。列序与 _EVENT_COLUMNS 一致。"""
    try:
        payload = json.loads(row[4]) if row[4] else {}
    except (TypeError, ValueError):
        payload = {}
    return {
        "seq": int(row[0]),
        "stream_id": row[1],
        "event_id": row[2],
        "type": row[3],
        "payload": payload,
        "command_id": row[5],
        "occurred_at": row[6],
    }


class SwarmEventStore:
    """全局单调序事件库（SQLite）。每实例一条连接，内部 RLock 串行化。"""

    def __init__(self, db_path: str):
        self._path = str(db_path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self.ensureSchema()

    def ensureSchema(self) -> None:
        """注册并应用本域迁移（幂等；防降级遵循 db_migration 语义）。"""
        register_migration(_SCHEMA_VERSION, _SCHEMA, domain=EVENT_STORE_DB_DOMAIN)
        _applyDomainMigrations(self._conn, domain=EVENT_STORE_DB_DOMAIN)

    def close(self) -> None:
        """关闭连接（测试与停机路径用；之后的调用不再受支持）。"""
        with self._lock:
            self._conn.close()

    def append(self, stream_id: str, event_type: str, payload: dict, *,
               event_id: str = "", command_id: str = "", occurred_at: str = "") -> int:
        """追加一条事件，返回全局单调 seq。event_id 非空时唯一（重复 event_id
        幂等忽略并返回其既有 seq——镜像双写不重放副作用）。"""
        stream = str(stream_id or "")
        if not stream:
            raise SwarmEventStoreError("stream_id 不能为空：事件必须归属一条流")
        with self._lock:
            try:
                cursor = self._conn.execute(
                    _INSERT_SQL,
                    (
                        stream,
                        str(event_id or ""),
                        str(event_type or ""),
                        json.dumps(payload or {}, ensure_ascii=False),
                        str(command_id or ""),
                        str(occurred_at or ""),
                        _occurredTs(occurred_at),
                    ),
                )
                self._conn.commit()
                return int(cursor.lastrowid)
            except sqlite3.IntegrityError:
                self._conn.rollback()
                # 仅当命中 event_id 唯一索引时按幂等处理；其余完整性错误诚实上抛
                row = self._conn.execute(
                    "SELECT seq FROM swarm_events WHERE event_id = ?", (str(event_id),)
                ).fetchone()
                if row is not None:
                    return int(row[0])
                raise

    def highWater(self) -> int:
        """当前全局最大 seq（空库 0）。"""
        with self._lock:
            row = self._conn.execute("SELECT MAX(seq) FROM swarm_events").fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def readStream(self, stream_id: str, *, after_seq: int = 0,
                   limit: int = 1000) -> List[dict]:
        """按流读（seq 升序，after_seq 之后），每条形如
        {"seq", "stream_id", "event_id", "type", "payload", "command_id", "occurred_at"}。"""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_EVENT_COLUMNS} FROM swarm_events "
                "WHERE stream_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?",
                (str(stream_id or ""), int(after_seq), int(limit)),
            ).fetchall()
        return [_rowToEvent(row) for row in rows]

    def replayThrough(self, after_seq: int, *, stream_id: str = "",
                      max_events: int = DEFAULT_REPLAY_MAX_EVENTS,
                      max_bytes: int = DEFAULT_REPLAY_MAX_BYTES) -> dict:
        """断线重连重放协议：返回
        {"events": [...], "high_water": int, "degraded": bool}
        - 回放 (after_seq, high_water] 区间（stream_id 非空时限定该流）；
        - 事件数或编码字节数超预算 → degraded=True 且 events 只含**完整前缀**
          （从 after_seq+1 起的连续段——绝不跳条目部分回放）；调用方据此降级快照；
        - cursor 落在 pruned_through 之下（区间内可能有已删空洞）→ degraded=True
          且 events 置空，调用方降级快照；
        - after_seq >= high_water → events=[]（空闲线程无回放）。"""
        with self._lock:
            highWaterSeq = self.highWater()
            if int(after_seq) >= highWaterSeq:
                return {"events": [], "high_water": highWaterSeq, "degraded": False}
            if int(after_seq) < self.prunedThrough():
                # 过旧 cursor：区间内可能有已修剪空洞，增量必不完整——
                # 唯一诚实做法是置空并要求快照，绝不部分回放
                return {"events": [], "high_water": highWaterSeq, "degraded": True}
            sql = (
                f"SELECT {_EVENT_COLUMNS} FROM swarm_events "
                "WHERE seq > ? AND seq <= ?"
            )
            params: List[Any] = [int(after_seq), highWaterSeq]
            if stream_id:
                sql += " AND stream_id = ?"
                params.append(str(stream_id))
            sql += " ORDER BY seq ASC"
            rows = self._conn.execute(sql, params).fetchall()

        events: List[dict] = []
        usedBytes = 0
        degraded = False
        for row in rows:
            if len(events) >= int(max_events):
                degraded = True
                break
            event = _rowToEvent(row)
            encoded = json.dumps(event, ensure_ascii=False).encode("utf-8")
            if usedBytes + len(encoded) > int(max_bytes):
                degraded = True
                break
            events.append(event)
            usedBytes += len(encoded)
        return {"events": events, "high_water": highWaterSeq, "degraded": degraded}

    def snapshotStream(self, stream_id: str) -> dict:
        """降级用全量快照：{"snapshot_sequence": highWater(), "events": [该流全部]}。"""
        with self._lock:
            snapshotSequence = self.highWater()
            rows = self._conn.execute(
                f"SELECT {_EVENT_COLUMNS} FROM swarm_events "
                "WHERE stream_id = ? ORDER BY seq ASC",
                (str(stream_id or ""),),
            ).fetchall()
        return {
            "snapshot_sequence": snapshotSequence,
            "events": [_rowToEvent(row) for row in rows],
        }

    def markPrunedThrough(self, seq: int) -> None:
        """记录已安全修剪边界（store_meta 表 key=pruned_through）。单调推进不回退。"""
        with self._lock:
            current = self.prunedThrough()
            if int(seq) <= current:
                return
            self._conn.execute(
                "INSERT INTO store_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (_META_PRUNED_THROUGH, str(int(seq))),
            )
            self._conn.commit()

    def prunedThrough(self) -> int:
        """读 pruned_through（无则 0）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM store_meta WHERE key = ?", (_META_PRUNED_THROUGH,)
            ).fetchone()
        return int(row[0]) if row else 0

    def pruneCovered(self, *, keep_window_s: float = DEFAULT_KEEP_WINDOW_S,
                     now_ts: Optional[float] = None) -> int:
        """删除发生在保留窗口外的**非保护**事件，返回删除数。
        保护：每 stream 最新一条、pruned_through 之后的不删；
        删除前先推进 pruned_through 到"本次将删的最大 seq"（先发布边界再删——
        客户端 cursor 落在边界之下时会明确降级快照，绝不部分回放）。"""
        with self._lock:
            now = float(now_ts) if now_ts is not None else time.time()
            boundaryTs = now - float(keep_window_s)
            # 候选 = 窗口外（occurred_ts < 边界）且非本流最新一条（流头保护）。
            # "pruned_through 之后不删"由构造保证：删除集的最大 seq 就是
            # 本轮新发布的边界，边界之上的行从不在删除集里。
            rows = self._conn.execute(
                "SELECT seq FROM swarm_events "
                "WHERE occurred_ts < ? "
                "AND seq NOT IN (SELECT MAX(seq) FROM swarm_events GROUP BY stream_id) "
                "ORDER BY seq ASC",
                (boundaryTs,),
            ).fetchall()
            if not rows:
                return 0
            deleteSeqs = [int(row[0]) for row in rows]
            boundarySeq = deleteSeqs[-1]
            # 先发布边界（独立事务提交，崩溃在删之前也只会让客户端多降级、不丢数据）
            self.markPrunedThrough(boundarySeq)
            self._conn.execute(
                "DELETE FROM swarm_events "
                "WHERE seq <= ? AND occurred_ts < ? "
                "AND seq NOT IN (SELECT MAX(seq) FROM swarm_events GROUP BY stream_id)",
                (boundarySeq, boundaryTs),
            )
            self._conn.commit()
            return len(deleteSeqs)


def mirrorFromLedger(store: SwarmEventStore, events: List[dict]) -> int:
    """把 H-4 JSONL 账本事件（swarm_event_log.readRunEvents 的输出形态：
    {event_id, type, subagent_id, payload, occurred_at, seq, ...}）镜像写入
    store（stream_id=subagent_id）。按 event_id 幂等；返回新写入条数。
    缺失 event_id 的行跳过不计，由调用方决定是否补发；缺 subagent_id 的行
    同样跳过不计（事件必须归属一条流）。

    计数口径：新写入行恰使全局 highWater 各 +1（幂等重写不产生新行），
    故以前后 highWater 差计新写入条数（单线程镜像路径下精确）。
    """
    before = store.highWater()
    for record in events or []:
        if not isinstance(record, dict):
            continue
        eventId = str(record.get("event_id") or "")
        streamId = str(record.get("subagent_id") or "")
        if not eventId or not streamId:
            continue
        store.append(
            streamId,
            str(record.get("type") or ""),
            record.get("payload") or {},
            event_id=eventId,
            occurred_at=str(record.get("occurred_at") or ""),
        )
    return store.highWater() - before
