"""
SessionRepository 统一接口（Deep Module）

将多套会话存储统一到 ABC 后面：
- _CHAT_SESSIONS（console.py 内存字典 + data/console_sessions.json）
- SessionManager（neurova/session_manager.py 文件层）
- SessionSyncManager（neurova/api/endpoints/session_sync.py 纯内存）
- agent.conversation_history（裸 list 属性）
- SQLite sessions/session_messages（孤儿表）

每个 adapter 实现此接口，调用方通过 get_session_repository() 获取实例。

设计决策详见 ADR-0008: docs/adr/0008-session-repository.md
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock
from typing import Dict, List, Optional


class SessionRepository(ABC):
    """会话存储统一接口。

    所有会话存储 adapter 必须实现此接口。
    调用方通过 get_session_repository() 获取实例，不直接依赖具体实现。

    接口契约：
    - create_session 返回字符串 session_id（唯一）
    - save_message 接受单条消息（不要求 user+assistant 配对）
    - get_history 返回 List[Dict]，每条 dict 至少含 role/content/timestamp
    - list_sessions 返回会话摘要列表，按 created_at 倒序
    - delete_session 删除该 session_id 的所有日期文件
    - rename_session 修改 title 字段（写入所有日期文件）
    - get_session 返回单会话 dict（含 messages 字段）
    """

    @abstractmethod
    def create_session(self, agent_id: str, user_id: str = "", title: str = "") -> str:
        """创建新会话，返回 session_id。"""

    @abstractmethod
    def save_message(
        self,
        agent_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None,
    ) -> bool:
        """保存单条消息到会话。"""

    @abstractmethod
    def get_history(self, agent_id: str, session_id: str, max_messages: int = 0) -> List[Dict]:
        """获取会话历史消息。max_messages=0 表示全部。"""

    @abstractmethod
    def list_sessions(self, agent_id: str = "", user_id: str = "") -> List[Dict]:
        """列出会话（按 agent_id/user_id 过滤），返回摘要列表。"""

    @abstractmethod
    def delete_session(self, agent_id: str, session_id: str) -> bool:
        """删除会话（所有日期文件）。"""

    @abstractmethod
    def rename_session(self, agent_id: str, session_id: str, title: str) -> bool:
        """重命名会话标题。"""

    @abstractmethod
    def get_session(self, agent_id: str, session_id: str) -> Optional[Dict]:
        """获取单个会话记录（含 messages 字段）。"""


# ── 工厂函数（单例） ──────────────────────────────────────

_repository_instance: Optional[SessionRepository] = None
_repository_lock = Lock()


def get_session_repository() -> SessionRepository:
    """获取 SessionRepository 单例实例。

    当前返回 SessionManager（等价于 FileSessionRepository）。
    未来可切换为 MemorySessionRepository / SqliteSessionRepository。
    """
    global _repository_instance
    if _repository_instance is None:
        with _repository_lock:
            if _repository_instance is None:
                from neurova.session_manager import SessionManager

                _repository_instance = SessionManager()
    return _repository_instance


def reset_session_repository() -> None:
    """重置单例（主要用于测试）。"""
    global _repository_instance
    with _repository_lock:
        _repository_instance = None
