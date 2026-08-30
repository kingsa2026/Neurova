"""
SessionRepository 统一接口（Deep Module）

将多套会话存储统一到 ABC 后面：
- ~~_CHAT_SESSIONS（console.py 内存字典 + data/console_sessions.json）~~ — 已删除 (D1/ADR 0008 候选 #1, S1 修复副产品)
- SessionManager（neurova/session_manager.py 文件层）— 已实现 SessionRepository (ADR 0008 落地)
- SessionSyncManager（neurova/sync/session_sync_manager.py 纯内存）— 部分接入 (S2 `register_or_create_session` 落地,SessionSyncManager 不实现 SessionRepository ABC:其核心 API `broadcast_event`/`register_or_create_session` 与 ABC CRUD 契约语义不匹配,完整 ABC 包裹会丢失广播语义 → 候选 #5 永久 deferred,详见 ADR 0008)
- agent.conversation_history（裸 list 属性）— 待封装 (D3/候选 #6)
- ~~SQLite sessions/session_messages（孤儿表）~~ — 已删除 (D4/候选 #4): `neurova/memory/scripts/init_db.py:76-79` 标注三张孤儿表 (sessions / session_messages / session_context_snapshots) 已删除,会话持久化由 SessionManager 文件层负责

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

    @abstractmethod
    def archive_session(self, agent_id: str, session_id: str) -> bool:
        """存档会话：从历史会话列表隐藏，可随时恢复（不删数据）。"""

    @abstractmethod
    def unarchive_session(self, agent_id: str, session_id: str) -> bool:
        """恢复存档会话为正常会话。"""

    @abstractmethod
    def list_archived_sessions(self, agent_id: str = "", user_id: str = "") -> List[Dict]:
        """列出存档会话（过滤规则与 list_sessions 一致），返回摘要列表。"""

    @abstractmethod
    def delete_round(self, agent_id: str, session_id: str, timestamp: str) -> List[Dict]:
        """删除一轮对话（user 消息 + 相邻 assistant 回复），返回被删消息列表。

        轮次定位键：msg.timestamp 或 msg.metadata.client_timestamp。
        未找到返回空列表。供 chat 页"编辑最后一条用户消息（删旧轮+重发）"
        与"删除一轮记录"使用。
        """

    @abstractmethod
    def update_message_metadata(
        self,
        agent_id: str,
        session_id: str,
        timestamp: str,
        metadata_patch: Dict,
        role: Optional[str] = None,
    ) -> bool:
        """按时间戳（+可选 role）定位单条消息并合并 metadata 补丁。

        供点赞/点踩反馈持久化（role="assistant"）使用。未找到返回 False。
        """

    @abstractmethod
    def get_round(self, agent_id: str, session_id: str, timestamp: str) -> Optional[Dict]:
        """按轮次定位键读取一轮对话（{"user": msg|None, "assistant": msg|None}）。

        供反馈质量闭环读取该轮内容（定位对应记忆）使用。未找到返回 None。
        """


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
