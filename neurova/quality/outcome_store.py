"""会话质量事件账（接管 / 回答完成态）。

只存 id、类型、时间、原因码与低敏维度；不存消息正文。
事件是事实，指标只在读取时聚合；没有分母时返回 None，不回 0。
"""
from __future__ import annotations

import datetime
import json
import sqlite3
import threading
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional

from neurova.core.data_root import dataPath
from neurova.core.logger import get_logger
from neurova.knowledge.foundation.storage_fence import assertNotUnderProductionMemory

logger = get_logger(__name__)

EVENT_TYPES = ("human_takeover_started", "human_takeover_ended", "turn_outcome")
TAKEOVER_SOURCES = ("channel_event", "console_mark", "api")
TURN_OUTCOMES = ("answered", "safety_refusal", "insufficient_evidence", "tool_failure", "handoff", "unknown")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_quality_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    source_event_id TEXT NOT NULL DEFAULT '',
    actor_id TEXT NOT NULL DEFAULT '',
    reason_code TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_quality_source_event
    ON conversation_quality_events(source, source_event_id)
    WHERE source_event_id <> '';
CREATE INDEX IF NOT EXISTS idx_quality_session_time
    ON conversation_quality_events(session_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_quality_type_time
    ON conversation_quality_events(event_type, occurred_at);
"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _windowStart(seconds: int) -> str:
    moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=max(1, int(seconds))
    )
    return moment.isoformat()


class ConversationQualityStore:
    def __init__(self, db_path: str) -> None:
        assertNotUnderProductionMemory(db_path, "会话质量事件账")
        self._path = str(db_path)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def recordEvent(
        self,
        eventType: str,
        sessionId: str,
        *,
        agentId: str = "",
        channel: str = "",
        source: str = "api",
        sourceEventId: str = "",
        actorId: str = "",
        reasonCode: str = "",
        occurredAt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if eventType not in EVENT_TYPES:
            raise ValueError("未知 event_type: %r" % eventType)
        if not str(sessionId or "").strip():
            raise ValueError("session_id 不能为空")
        if eventType.startswith("human_takeover") and source not in TAKEOVER_SOURCES:
            raise ValueError("接管事件 source 非法: %r" % source)
        stamp = str(occurredAt or _now())
        with self._lock, self._conn:
            if sourceEventId:
                row = self._conn.execute(
                    "SELECT * FROM conversation_quality_events"
                    " WHERE source = ? AND source_event_id = ? LIMIT 1",
                    (source, str(sourceEventId)),
                ).fetchone()
                if row:
                    return dict(row, duplicate=True)
            event_id = "cqe_%s" % uuid.uuid4().hex[:12]
            self._conn.execute(
                "INSERT INTO conversation_quality_events"
                " (event_id, event_type, session_id, agent_id, channel, source,"
                " source_event_id, actor_id, reason_code, occurred_at, recorded_at,"
                " metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, eventType, str(sessionId), str(agentId), str(channel),
                 str(source), str(sourceEventId), str(actorId), str(reasonCode),
                 stamp, _now(), json.dumps(metadata or {}, ensure_ascii=False)),
            )
            row = self._conn.execute(
                "SELECT * FROM conversation_quality_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            return dict(row, duplicate=False)

    def recordTurnOutcome(
        self,
        turnId: str,
        sessionId: str,
        *,
        agentId: str = "",
        channel: str = "",
        outcome: str = "unknown",
        source: str = "chat_pipeline",
        occurredAt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if outcome not in TURN_OUTCOMES:
            outcome = "unknown"
        payload = dict(metadata or {})
        if outcome == "insufficient_evidence":
            payload.setdefault("experimental", True)
        turnKey = str(turnId or "")
        sourceName = str(source or "chat_pipeline")
        # 显式裁定允许改判：同一 turn 的 explicit_api 行原地更新，
        # 自动分类行仍走 append-only 幂等（重复回放不新增事实）。
        if sourceName == "explicit_api" and turnKey:
            with self._lock, self._conn:
                existing = self._conn.execute(
                    "SELECT * FROM conversation_quality_events"
                    " WHERE event_type = 'turn_outcome' AND source = ?"
                    " AND source_event_id = ? LIMIT 1",
                    (sourceName, turnKey),
                ).fetchone()
                if existing:
                    stamp = str(occurredAt or _now())
                    self._conn.execute(
                        "UPDATE conversation_quality_events SET agent_id = ?, channel = ?,"
                        " reason_code = ?, occurred_at = ?, recorded_at = ?, metadata_json = ?"
                        " WHERE event_id = ?",
                        (str(agentId), str(channel), outcome, stamp, _now(),
                         json.dumps(payload, ensure_ascii=False), existing["event_id"]),
                    )
                    updated = self._conn.execute(
                        "SELECT * FROM conversation_quality_events WHERE event_id = ?",
                        (existing["event_id"],),
                    ).fetchone()
                    return dict(updated, duplicate=False, updated=True)
        return self.recordEvent(
            "turn_outcome", sessionId,
            agentId=agentId, channel=channel, source=sourceName,
            sourceEventId=turnKey, reasonCode=outcome,
            occurredAt=occurredAt, metadata=payload,
        )

    def takeoverState(self, sessionId: str) -> Dict[str, Any]:
        """最近一条接管事件＝当前状态；无事件时不把「未观测」读成「未接管」。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT event_type, source, actor_id, channel, occurred_at, recorded_at"
                " FROM conversation_quality_events"
                " WHERE session_id = ? AND event_type IN"
                " ('human_takeover_started', 'human_takeover_ended')"
                " ORDER BY recorded_at DESC, rowid DESC LIMIT 1",
                (str(sessionId),),
            ).fetchone()
        if not row:
            return {
                "session_id": str(sessionId),
                "active": False,
                "observed": False,
                "last_event": None,
            }
        last = dict(row)
        return {
            "session_id": str(sessionId),
            "active": last["event_type"] == "human_takeover_started",
            "observed": True,
            "last_event": last,
        }

    def metrics(self, windowSeconds: int = 7 * 86400) -> Dict[str, Any]:
        start = _windowStart(windowSeconds)
        with self._lock:
            rows = [dict(r) for r in self._conn.execute(
                "SELECT event_id, event_type, session_id, channel, source,"
                " reason_code, source_event_id, recorded_at, metadata_json"
                " FROM conversation_quality_events WHERE occurred_at >= ?",
                (start,),
            ).fetchall()]
        raw_turns = [r for r in rows if r["event_type"] == "turn_outcome"]
        # 同一轮可能先有管线自动分类、后被显式 outcome 覆盖；事件都保留，
        # 指标按轮去重且显式来源优先——否则两条各算一次，率会翻倍。
        priority = {"explicit_api": 2, "chat_pipeline": 1}
        by_turn: Dict[str, Dict[str, Any]] = {}
        for row in raw_turns:
            key = str(row.get("source_event_id") or row.get("event_id") or "")
            previous = by_turn.get(key)
            if previous is None:
                by_turn[key] = row
                continue
            row_rank = priority.get(row["source"], 0)
            prev_rank = priority.get(previous["source"], 0)
            if row_rank > prev_rank or (
                row_rank == prev_rank
                and str(row.get("recorded_at") or "") >= str(previous.get("recorded_at") or "")
            ):
                by_turn[key] = row
        turns = list(by_turn.values())
        takeover = [r for r in rows if r["event_type"] == "human_takeover_started"]
        counts = Counter(r["reason_code"] or "unknown" for r in turns)
        turn_count = len(turns)
        unknown = counts.get("unknown", 0)
        known = turn_count - unknown
        reply_sessions = {r["session_id"] for r in turns}
        takeover_sessions = {r["session_id"] for r in takeover}
        sources = Counter(r["source"] for r in takeover)
        by_channel = Counter(r["channel"] or "unknown" for r in takeover)

        def _rate(value: int, denom: int) -> Optional[float]:
            return round(value / denom, 6) if denom > 0 else None

        measured = turn_count > 0 or bool(takeover)
        takeover_rate = _rate(len(takeover_sessions), len(reply_sessions))
        result = {
            "measure_state": "measured" if measured else "unevidenced",
            "window_seconds": int(windowSeconds),
            "turns": turn_count,
            "turn_outcome_events": len(raw_turns),
            "sessions": len(reply_sessions),
            "outcomes": dict(counts),
            "safety_refusal_rate": _rate(counts.get("safety_refusal", 0), known),
            "insufficient_evidence_rate": _rate(counts.get("insufficient_evidence", 0), known),
            "tool_failure_rate": _rate(counts.get("tool_failure", 0), known),
            "unknown_outcome_rate": _rate(unknown, turn_count),
            "human_takeover_rate": takeover_rate,
            "takeover_sessions": len(takeover_sessions),
            "takeover_events": len(takeover),
            "takeover_sources": dict(sources),
            "takeover_by_channel": dict(by_channel),
            "coverage": {
                "channel_event": sources.get("channel_event", 0),
                "console_mark": sources.get("console_mark", 0),
                "api": sources.get("api", 0),
            },
        }
        if not measured:
            result["missing_reason"] = "窗口内没有 turn_outcome 或接管事件"
        if reply_sessions and not takeover:
            result["takeover_missing_reason"] = (
                "窗口内未观察到接管事件；渠道覆盖未证明，0 不读成无人接管"
            )
        if counts.get("tool_failure", 0) == 0:
            result.setdefault("uninstrumented", {})["tool_failure"] = "管线尚未产出该硬信号"
        return result


_store: Optional[ConversationQualityStore] = None
_store_lock = threading.Lock()


def get_quality_store() -> ConversationQualityStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = ConversationQualityStore(dataPath("quality", "conversation_quality.db"))
        return _store


def reset_quality_store() -> None:
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = None
