# -*- coding: utf-8 -*-
"""P1-9 steer 插话队列。

turn 进行中用户补充的消息先进会话级邮箱；工具轮间隙由 agent loop 排空，
以 user 角色并入下一轮采样消息。
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


class ActiveTurnRegistry:
    """会话级"回合进行中"注册表（P2，loop 对照 #5 的入队侧）。

    管线 `execute()` 进入/离开时登记；请求入口据此判定"这条新输入该作为
    **插话**并入正在跑的回合，还是开启一个新回合"。没有它，turn 进行中的
    第二条消息会与第一条**并发跑两个回合**（loop 是 per-agent 单例，轮次态
    互相踩踏——Issue #268 的形态），或被写围栏拒绝。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active: Dict[str, int] = {}

    def markStarted(self, session_id: str) -> None:
        sid = str(session_id or "")
        if not sid:
            return
        with self._lock:
            self._active[sid] = self._active.get(sid, 0) + 1

    def markEnded(self, session_id: str) -> None:
        sid = str(session_id or "")
        if not sid:
            return
        with self._lock:
            count = self._active.get(sid, 0) - 1
            if count <= 0:
                self._active.pop(sid, None)
            else:
                self._active[sid] = count

    def isActive(self, session_id: str) -> bool:
        with self._lock:
            return self._active.get(str(session_id or ""), 0) > 0


_REGISTRY: ActiveTurnRegistry = None
_REGISTRY_LOCK = threading.Lock()


def get_active_turn_registry() -> ActiveTurnRegistry:
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = ActiveTurnRegistry()
        return _REGISTRY


def reset_active_turn_registry() -> None:
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = None


def submitSteer(session_id: str, text: str) -> bool:
    """把 turn 进行中的用户输入作为插话投递；回合不在跑时返回 False（调用方
    按新回合处理）。入队成功即返回 True——loop 会在下一个工具轮间隙消费。"""
    sid = str(session_id or "")
    if not sid or not str(text or "").strip():
        return False
    if not get_active_turn_registry().isActive(sid):
        return False
    return get_steer_queue().push(sid, text)
