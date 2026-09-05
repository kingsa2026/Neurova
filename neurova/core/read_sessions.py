"""ReadSessionStore —— 续读游标的进程内存储（browser_read / dom_read 共用）。

对标 Dokobot 的 canContinue+sessionId 分页续读：长内容一次抓取、分片喂给 LLM，
尾部不再被截断丢弃。设计约束：

- 纯内存、有界：LRU 上限 max_sessions（默认 64）+ TTL（默认 30 分钟，懒清理），
  游标是易失缓存，过期即引导重新首读——不落盘、不进数据库
- 线程安全：browser_read 在工具线程池调用、dom_read 在事件循环调用，游标推进
  必须 RLock 保护（一次 read = 游标推进 + 切片，两步原子完成）
- domain 隔离命名空间：browser_read 与 dom_read 的 session_id 混用时会话内
  chunk_size/全文不同，read 前校验 domain 防串台
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_MAX_SESSIONS = 64
_DEFAULT_TTL_SECONDS = 1800.0


def _now() -> float:
    return time.monotonic()


@dataclass
class ReadSession:
    """一次读取会话：全文缓存的切片游标。"""

    session_id: str
    domain: str                      # "browser_read" / "dom_read"
    url: str
    title: str
    text: str
    chunk_size: int
    cursor: int = 0                  # 下一个待读分片的起始 offset
    target_id: Optional[str] = None  # dom_read 专用：绑定 tab
    generation: Optional[int] = None  # dom_read 专用：绑定页面代数（导航/交互后 stale）
    created_at: float = 0.0
    last_access: float = 0.0
    access_seq: int = 0              # LRU 序号（时钟粒度粗，平局时时间戳不可靠）


class ReadSessionStore:
    """有界 LRU+TTL 的读取会话存储。

    read() 的游标推进语义：
    - 不带 offset：顺序续读（读后游标推进到本片末尾）
    - 带 offset：显式重读任意片段，不影响游标序列（LLM 回看前文用）
    """

    def __init__(
        self,
        max_sessions: int = _DEFAULT_MAX_SESSIONS,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
    ):
        self._max_sessions = max(1, int(max_sessions))
        self._ttl = float(ttl_seconds)
        self._sessions: "Dict[str, ReadSession]" = {}
        self._lock = threading.RLock()
        self._seq = 0
        self._access_counter = 0

    # ── 内部 ──

    def _touch_locked(self, session: ReadSession) -> None:
        """刷新 LRU 序号 + 访问时间（须持锁调用）。"""
        self._access_counter += 1
        session.access_seq = self._access_counter
        session.last_access = _now()

    def _evict_locked(self) -> None:
        """LRU 驱逐：先清过期，仍超员则按 access_seq 最旧者出列。"""
        now = _now()
        expired = [k for k, s in self._sessions.items() if now - s.last_access > self._ttl]
        for k in expired:
            del self._sessions[k]
        while len(self._sessions) > self._max_sessions:
            oldest = min(self._sessions, key=lambda k: self._sessions[k].access_seq)
            del self._sessions[oldest]

    # ── 公共 API ──

    def create(
        self,
        domain: str,
        url: str,
        title: str,
        text: str,
        chunk_size: int,
        target_id: Optional[str] = None,
        generation: Optional[int] = None,
        served: int = 0,
    ) -> ReadSession:
        """创建会话。served = 首读调用方已直接返回给 LLM 的字节数
        （首片不经 store 吐出，游标须跳过它，否则续读重复喂首片）。"""
        chunk_size = max(1, int(chunk_size))
        served = max(0, min(int(served), len(text or "")))
        now = _now()
        with self._lock:
            self._seq += 1
            session = ReadSession(
                session_id=f"rs_{int(time.time() * 1000):x}_{self._seq:04x}",
                domain=domain,
                url=url or "",
                title=title or "",
                text=text or "",
                chunk_size=chunk_size,
                cursor=served,
                target_id=target_id,
                generation=generation,
                created_at=now,
                last_access=now,
            )
            self._touch_locked(session)
            self._sessions[session.session_id] = session
            self._evict_locked()  # 驱逐必须在插入后：否则新会话挤破上界无人检查
            return session

    def get(self, session_id: str) -> Optional[ReadSession]:
        if not session_id:
            return None
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                if _now() - session.last_access > self._ttl:
                    del self._sessions[session_id]
                    return None
                self._touch_locked(session)
            return session

    def read(self, session_id: str, offset: Optional[int] = None) -> Optional[Dict]:
        """读一个分片。返回游标契约 dict；会话不存在/过期返回 None。"""
        with self._lock:
            session = self.get(session_id)  # get 内部持同一把 RLock，可重入
            if session is None:
                return None
            if offset is None:
                start = session.cursor
            else:
                start = max(0, int(offset))
            end = min(start + session.chunk_size, len(session.text))
            piece = session.text[start:end]
            # 只有顺序续读推进游标；显式 offset 重读不影响序列
            if offset is None:
                session.cursor = end
            has_more = end < len(session.text)
            next_offset = end if has_more else None
            return {
                "text": piece,
                "offset": start,
                "next_offset": next_offset,
                "can_continue": has_more,
                "total_length": len(session.text),
                "session_id": session.session_id,
                "url": session.url,
                "title": session.title,
            }

    def size(self) -> int:
        with self._lock:
            return len(self._sessions)


# ── 进程单例 ──

_store_instance: Optional[ReadSessionStore] = None
_store_lock = threading.Lock()


def get_read_session_store() -> ReadSessionStore:
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = ReadSessionStore()
    return _store_instance


def reset_read_session_store() -> None:
    """重置单例（测试用）。"""
    global _store_instance
    with _store_lock:
        _store_instance = None
