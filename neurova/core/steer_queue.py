# -*- coding: utf-8 -*-
"""P1-9 steer 插话队列（Codex TurnInputMode::Steer 对齐）。

turn 进行中用户补充的消息先进会话级邮箱；工具轮间隙由 agent loop 排空，
以 user 角色并入下一轮采样消息（Codex pending input 语义）。
TTL 过期自动丢弃（无 turn 消费时不出积压）；会话队列有上限防刷。
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_TTL_SECONDS = 300
_DEFAULT_MAX_PER_SESSION = 10


class SteerQueue:
    """会话级插话邮箱（单例经 get_steer_queue() 获取）。"""

    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS, max_per_session: int = _DEFAULT_MAX_PER_SESSION):
        self.ttl_seconds = ttl_seconds
        self.max_per_session = max_per_session
        self._lock = threading.RLock()
        self._queues: Dict[str, List[Dict]] = {}

    def push(self, session_id: str, text: str) -> bool:
        text = str(text or "").strip()
        sid = str(session_id or "")
        if not sid or not text:
            return False
        with self._lock:
            bucket = self._queues.setdefault(sid, [])
            # 过期清理（防无 turn 消费时的慢积压）
            now = time.time()
            bucket[:] = [e for e in bucket if now - e["ts"] < self.ttl_seconds]
            if len(bucket) >= self.max_per_session:
                return False
            bucket.append({"text": text, "ts": now})
            return True

    def drain(self, session_id: str) -> List[str]:
        sid = str(session_id or "")
        if not sid:
            return []
        with self._lock:
            bucket = self._queues.pop(sid, [])
            now = time.time()
            return [e["text"] for e in bucket if now - e["ts"] < self.ttl_seconds]

    def pending(self, session_id: str) -> int:
        with self._lock:
            return len(self._queues.get(str(session_id or ""), []))


_QUEUE: SteerQueue = None
_QUEUE_LOCK = threading.Lock()


def get_steer_queue() -> SteerQueue:
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is None:
            _QUEUE = SteerQueue()
        return _QUEUE


def reset_steer_queue() -> None:
    global _QUEUE
    with _QUEUE_LOCK:
        _QUEUE = None
