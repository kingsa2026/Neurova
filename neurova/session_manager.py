"""
会话备份管理器
将对话内容按agent和session_id隔离，直接即时写入文件，无内存缓存
"""

import json
from neurova.core.logger import get_logger
from neurova.session_repository import SessionRepository
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
import os
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Dict, List, Optional

try:
    import fcntl  # type: ignore[import-not-found]  # Unix only

    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

logger = get_logger(__name__)

# 净化时标记"应丢弃"的哨兵值（与 None 区分——None 是合法 JSON 值）
_JSON_DROP = object()


def _json_safe(value: Any) -> Any:
    """递归剔除不可 JSON 序列化的值，返回净化后的副本。

    持久化边界防御: 运行时 metadata 可能携带仅供进程内使用的对象
    （如 console SSE 桥接注入的 event_emitter 回调函数）。这类值若进入
    json.dump 会抛 TypeError，配合"先截断后写"将损坏 session 文件。
    规则: callable 丢弃；dict/list 递归清理；JSON 原生类型原样保留；
    其他类型尝试序列化，失败则丢弃。
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if callable(value):
        return _JSON_DROP
    if isinstance(value, dict):
        cleaned = {}
        for k, v in value.items():
            cv = _json_safe(v)
            if cv is _JSON_DROP:
                continue
            cleaned[k if isinstance(k, str) else str(k)] = cv
        return cleaned
    if isinstance(value, (list, tuple)):
        return [cv for cv in (_json_safe(v) for v in value) if cv is not _JSON_DROP]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError, OverflowError):
        return _JSON_DROP


@dataclass
class SessionMessage:
    """会话消息"""

    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class SessionRecord:
    """会话记录"""

    agent_id: str
    session_id: str
    session_date: str
    messages: List[SessionMessage] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    total_messages: int = 0
    title: str = ""
    user_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["messages"] = [msg.to_dict() if isinstance(msg, SessionMessage) else msg for msg in self.messages]
        return data


class SessionManager(SessionRepository):
    """会话管理器 - 直接即时写入文件，无内存缓存。

    实现 SessionRepository ABC，作为文件层 adapter（FileSessionRepository 等价物）。
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, sessions_dir: Optional[str] = None):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            # NEUROVA_SESSIONS_DIR 环境变量供测试隔离（单例 __new__ 下
            # 构造参数只在首次生效，env 是唯一可靠覆盖通道）
            self._sessions_dir = Path(
                sessions_dir or os.environ.get("NEUROVA_SESSIONS_DIR") or "sessions"
            )
            self._sessions_dir.mkdir(parents=True, exist_ok=True)
            self._file_locks: Dict[str, Lock] = {}
            # S3 修复 (Critical #4 TOCTOU): 保护 _file_locks dict 的独立 RLock.
            # RLock 允许 _get_file_lock 在持锁时被同线程重入调用 (如 __init__ 内部).
            self._file_locks_lock = RLock()

    def _get_file_lock(self, file_path) -> Lock:
        """获取文件的线程锁 (S3 修复 TOCTOU: DCL 双重检查锁定).

        Bug (Critical #4): 原 `if key not in dict: dict[key] = Lock()` 是
        check-then-act 模式,两线程可同时通过检查,各自创建 Lock 并覆盖,
        导致两线程拿到不同 Lock 实例 → 文件竞态.

        修复: 用 _file_locks_lock (RLock) 保护 dict,双重检查锁定:
        - Fast path: 无锁检查 dict.get(key) → 命中直接返回
        - Slow path: 持锁后再次检查 (double-check) → 未命中则创建
        """
        key = str(file_path)
        # Fast path: 无锁读 (命中率高时避免加锁开销)
        lock = self._file_locks.get(key)
        if lock is not None:
            return lock
        # Slow path: 持锁创建 (DCL)
        with self._file_locks_lock:
            lock = self._file_locks.get(key)
            if lock is None:
                lock = Lock()
                self._file_locks[key] = lock
            return lock

    def _get_session_dir(self, agent_id: str) -> Path:
        """获取agent的session目录（agent_id 为空时归入 "default"）。

        #1 改造：console 接入后允许 agent_id="" 创建会话，但根目录不能放 session
        文件（会被 list_sessions 漏扫），统一归入 default/。
        """
        effective_agent_id = agent_id or "default"
        agent_dir = self._sessions_dir / effective_agent_id
        agent_dir.mkdir(exist_ok=True)
        return agent_dir

    def _get_session_file(self, agent_id: str, session_id: str, date: str = None) -> Path:
        """获取session文件路径"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        agent_dir = self._get_session_dir(agent_id)
        return agent_dir / f"session_{session_id}_{date}.json"

    def _get_archived_dir(self, agent_id: str) -> Path:
        """获取agent的存档目录（sessions/{agent_id}/archived/）。

        存档 = 会话文件整体移入该子目录：现有 list/get/delete/rename 均基于
        agent_dir 的 session_*.json glob（不递归），移入即从所有现有查询消失，
        恢复即移回，无需改动任何既有方法。
        """
        archived_dir = self._get_session_dir(agent_id) / "archived"
        archived_dir.mkdir(exist_ok=True)
        return archived_dir

    def archive_session(self, agent_id: str, session_id: str) -> bool:
        """存档会话：该 session 的所有日期文件移入 archived/ 子目录。"""
        agent_dir = self._get_session_dir(agent_id)
        archived_dir = self._get_archived_dir(agent_id)

        moved = 0
        for file_path in agent_dir.glob(f"session_{session_id}_*.json"):
            try:
                file_lock = self._get_file_lock(file_path)
                with file_lock:
                    # os.replace 同卷原子覆盖：恢复时 archived 版本覆盖主目录残留
                    file_path.replace(archived_dir / file_path.name)
                    moved += 1
            except Exception as e:
                logger.error("存档session文件失败: %s", e)
                continue

        if moved > 0:
            logger.info("Session已存档: agent=%s, session=%s, 文件数=%s", agent_id, session_id, moved)
            return True
        logger.warning("未找到可存档的session文件（agent_id=%s, session_id=%s）", agent_id, session_id)
        return False

    def unarchive_session(self, agent_id: str, session_id: str) -> bool:
        """恢复存档会话：所有日期文件从 archived/ 移回主目录。"""
        agent_dir = self._get_session_dir(agent_id)
        archived_dir = self._get_archived_dir(agent_id)

        moved = 0
        for file_path in archived_dir.glob(f"session_{session_id}_*.json"):
            try:
                file_lock = self._get_file_lock(file_path)
                with file_lock:
                    file_path.replace(agent_dir / file_path.name)
                    moved += 1
            except Exception as e:
                logger.error("恢复session文件失败: %s", e)
                continue

        if moved > 0:
            logger.info("Session已恢复: agent=%s, session=%s, 文件数=%s", agent_id, session_id, moved)
            return True
        logger.warning("未找到可恢复的存档文件（agent_id=%s, session_id=%s）", agent_id, session_id)
        return False

    def _read_session_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """读取session文件"""
        if not file_path.exists():
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("读取session文件失败: %s", e)
            return None

    def _write_session_file(self, file_path: Path, data: Dict[str, Any]) -> bool:
        """写入session文件 (向后兼容: 内部获取 file_lock).

        新代码应直接调用 _write_session_file_unlocked 并在调用前持有 file_lock,
        以保证 read-modify-write 原子性 (S4 修复).
        """
        file_lock = self._get_file_lock(file_path)
        with file_lock:
            return self._write_session_file_unlocked(file_path, data)

    def _write_session_file_unlocked(self, file_path: Path, data: Dict[str, Any]) -> bool:
        """写入session文件 (无锁版本,调用方必须已持有 file_lock).

        S4 修复 (Critical #5 跨锁 RMW): 从 _write_session_file 抽出无锁版本,
        供 add_message 在 `with file_lock:` 块内调用,避免:
        1. read-modify-write 跨锁边界 (read 无锁, write 有锁 → lost update)
        2. Lock 不可重入 (add_message 持锁后调 _write_session_file 会再次获取
           同一 file_lock → 死锁)

        先序列化后写文件: 原实现先 open("w") 截断文件再 json.dump 流式写入,
        序列化中途抛异常（如 metadata 混入函数对象）会把文件截断成非法 JSON,
        损坏已有会话历史。现在先在内存中完成序列化,失败则不触碰文件。
        """
        try:
            text = json.dumps(data, ensure_ascii=False, indent=2)
        except (TypeError, ValueError, OverflowError) as e:
            logger.debug("session 数据序列化失败, 跳过写入以保护现有文件 (内层详情): %s", e, exc_info=True)
            return False

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                if HAS_FCNTL:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                        f.write(text)
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        f.write(text)
                else:
                    f.write(text)
            return True
        except Exception as e:
            # WARN #4 优化 (摘要+详情分层): 内层降级为 debug,保留诊断细节.
            # 外层 add_message 失败时已 logger.error (带 agent_id/session_id/file_path
            # 上下文),内层重复 error 会产生双 error 日志 noise. 内层 debug = 详情层.
            logger.debug("写入 session 文件失败 (内层详情): %s", e, exc_info=True)
            return False

    def add_message(
        self,
        agent_id: str,
        session_id: str,
        user_content: str,
        assistant_content: str,
        metadata: Dict[str, Any] = None,
        assistant_metadata: Dict[str, Any] = None,
        date: str = None,
    ) -> str:
        """添加一条对话（user + assistant 两条消息）到session

        S4 修复 (Critical #5 跨锁 RMW): read-modify-write 整体置于 file_lock 内.
        Bug: 原 read 在锁外, write 在锁内,两线程可同时 read 同一旧状态,
        后写者覆盖先写者的更新 (lost update).

        R-2 修复: 新增 assistant_metadata——assistant 专属元数据（思考过程
        reasoning_content、工具调用 tool_calls）。此前 reasoning 经 post_chat
        管线一路传递到 mem_core.save_to_session 后被静默丢弃，切换页面重开
        会话后思考过程不显示。不传时保持旧行为：metadata 仍写入双方消息。
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        file_path = self._get_session_file(agent_id, session_id, date)
        file_lock = self._get_file_lock(file_path)

        # 持久化边界净化: metadata 来自调用方（如 console SSE 桥接注入的
        # event_emitter 函数），不可序列化的运行时对象必须在此剔除，
        # 否则整轮对话历史无法落盘（见 _json_safe 文档）。
        if metadata:
            metadata = _json_safe(metadata)
        if assistant_metadata:
            assistant_metadata = _json_safe(assistant_metadata)

        # S4: 整个 read-modify-write 在 file_lock 内,保证原子性
        with file_lock:
            # 读取现有数据
            session_data = self._read_session_file(file_path)

            now = datetime.now().isoformat()
            user_msg = {
                "role": "user",
                "content": user_content,
                "timestamp": now,
            }
            assistant_msg = {
                "role": "assistant",
                "content": assistant_content,
                "timestamp": now,
            }
            # R-2: assistant_metadata 存在时分别写入各消息；否则保留旧行为
            #（metadata 写入双方，client_timestamp 等轮次定位键依赖此语义）。
            if assistant_metadata is not None:
                if metadata:
                    user_msg["metadata"] = metadata
                if assistant_metadata:
                    assistant_msg["metadata"] = assistant_metadata
            elif metadata:
                user_msg["metadata"] = metadata
                assistant_msg["metadata"] = metadata

            new_messages = [user_msg, assistant_msg]

            if session_data is None:
                # 创建新的session记录
                session_data = {
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "session_date": date,
                    "messages": new_messages,
                    "created_at": now,
                    "updated_at": now,
                    "total_messages": len(new_messages),
                }
            else:
                # 更新现有session记录
                if "messages" not in session_data:
                    session_data["messages"] = []

                session_data["messages"].extend(new_messages)
                session_data["updated_at"] = now
                session_data["total_messages"] = len(session_data["messages"])

            # 写入文件 (无锁版本,避免重入死锁)
            # WARN #4 修复: 检查返回值,失败时 logger.error + 抛 IOError.
            # 原代码静默忽略写入失败 → lost update 用户无感.
            write_ok = self._write_session_file_unlocked(file_path, session_data)
            if not write_ok:
                logger.error(
                    "add_message 写入 session 文件失败: agent_id=%s, session_id=%s, file=%s",
                    agent_id, session_id, file_path,
                )
                raise IOError(
                    f"写入 session 文件失败: agent_id={agent_id}, session_id={session_id}"
                )

        return f"{agent_id}_{session_id}"

    def get_session(self, agent_id: str, session_id: str, date: str = None) -> SessionRecord:
        """获取session记录"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        file_path = self._get_session_file(agent_id, session_id, date)
        session_data = self._read_session_file(file_path)

        if session_data is None:
            return SessionRecord(
                agent_id=agent_id,
                session_id=session_id,
                session_date=date,
            )

        # 转换为SessionRecord对象
        messages = []
        for msg_data in session_data.get("messages", []):
            if isinstance(msg_data, dict):
                messages.append(
                    SessionMessage(
                        role=msg_data.get("role", ""),
                        content=msg_data.get("content", ""),
                        timestamp=msg_data.get("timestamp", ""),
                        metadata=msg_data.get("metadata"),
                    )
                )
            else:
                messages.append(msg_data)

        return SessionRecord(
            agent_id=session_data.get("agent_id", agent_id),
            session_id=session_data.get("session_id", session_id),
            session_date=session_data.get("session_date", date),
            messages=messages,
            created_at=session_data.get("created_at", ""),
            updated_at=session_data.get("updated_at", ""),
            total_messages=session_data.get("total_messages", 0),
        )

    def get_sessions_by_agent(self, agent_id: str) -> List[Dict[str, Any]]:
        """获取agent的所有session文件"""
        agent_dir = self._get_session_dir(agent_id)
        sessions = []

        for file_path in agent_dir.glob("session_*.json"):
            session_data = self._read_session_file(file_path)
            if session_data:
                sessions.append(session_data)

        return sessions

    def get_sessions(self, agent_id: str) -> List[Dict[str, Any]]:
        """获取agent的所有session文件"""
        return self.get_sessions_by_agent(agent_id)

    def get_sessions_by_id(self, agent_id: str, session_id: str) -> List[str]:
        """获取指定session_id的所有日期文件路径"""
        agent_dir = self._get_session_dir(agent_id)
        return [str(fp) for fp in agent_dir.glob(f"session_{session_id}_*.json")]

    def _get_session_data_list(self, agent_id: str, session_id: str) -> List[Dict[str, Any]]:
        """获取指定session_id的所有日期文件数据"""
        agent_dir = self._get_session_dir(agent_id)
        sessions = []
        for file_path in agent_dir.glob(f"session_{session_id}_*.json"):
            session_data = self._read_session_file(file_path)
            if session_data:
                sessions.append(session_data)
        return sessions

    def search_session(self, agent_id: str, session_id: str, keyword: str, date: str = None) -> List[Dict[str, Any]]:
        """搜索session中的内容 - 直接从文件读取"""
        if date is None:
            # 搜索所有日期
            sessions = self._get_session_data_list(agent_id, session_id)
        else:
            # 搜索指定日期
            file_path = self._get_session_file(agent_id, session_id, date)
            session_data = self._read_session_file(file_path)
            sessions = [session_data] if session_data else []

        results = []
        for session in sessions:
            for message in session.get("messages", []):
                if keyword.lower() in message.get("content", "").lower():
                    results.append(message)

        return results

    def create_session(self, agent_id: str = "", user_id: str = "", title: str = "") -> str:
        """创建新的 session_id 并落盘空 session 文件。

        Args:
            agent_id: Agent ID（用于分目录存储）
            user_id: 用户 ID（写入 user_id 字段，便于 list_sessions 过滤）
            title: 会话标题（默认 "新对话"）

        Returns:
            session_id（8 位短 uuid）
        """
        session_id = str(uuid.uuid4())[:8]
        date = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now().isoformat()
        file_path = self._get_session_file(agent_id, session_id, date)
        session_data = {
            "agent_id": agent_id,
            "session_id": session_id,
            "session_date": date,
            "messages": [],
            "created_at": now,
            "updated_at": now,
            "total_messages": 0,
            "title": title or "新对话",
            "user_id": user_id,
        }
        # 幽灵 session 防御 (chat.loadHistoryFailed toast 后端根因修复):
        # _write_session_file_unlocked except 块只 logger.debug 返回 False,
        # 若不检查返回值, create_session 仍返回 session_id 给前端 → 前端拿到
        # ID 加入 sidebar → 用户点击 GET /history → 404 → toast.
        # fail-fast: 文件写入失败时抛 RuntimeError, 让 HTTP 端点返回 500,
        # 前端 onError 弹 toast, 不创建幽灵 session.
        # 详见 docs/bugfix-delete-session-userid-mismatch.md "§8 幽灵 session 自愈".
        if not self._write_session_file(file_path, session_data):
            logger.error("create_session 持久化失败 (silent failure antipattern 修复): session_id=%s, file=%s", session_id, file_path)
            raise RuntimeError(f"Failed to persist session file: {file_path}")
        return session_id

    def delete_session(self, agent_id: str, session_id: str, date: str = None) -> bool:
        """删除指定的session文件"""
        agent_dir = self._get_session_dir(agent_id)

        if date:
            # 删除指定日期的文件
            file_path = self._get_session_file(agent_id, session_id, date)
            if file_path.exists():
                try:
                    file_lock = self._get_file_lock(file_path)
                    with file_lock:
                        file_path.unlink()
                        logger.info("Session已删除: %s", file_path)
                        return True
                except Exception as e:
                    logger.error("删除session文件失败: %s", e)
                    return False
            else:
                logger.warning("未找到 session_id=%s 的文件（date=%s）", session_id, date)
                return False
        else:
            # 删除所有日期的文件
            deleted_count = 0
            for file_path in agent_dir.glob(f"session_{session_id}_*.json"):
                try:
                    file_lock = self._get_file_lock(file_path)
                    with file_lock:
                        file_path.unlink()
                        deleted_count += 1
                        logger.info("Session已删除: %s", file_path)
                except Exception as e:
                    logger.error("删除session文件失败: %s", e)
                    continue

            if deleted_count > 0:
                logger.info("共删除 %s 个文件（session_id=%s）", deleted_count, session_id)
                return True
            else:
                logger.warning("未找到 session_id=%s 的任何文件（agent_id=%s）", session_id, agent_id)
                return False

    def get_session_stats(self, agent_id: str, session_id: str) -> Dict[str, Any]:
        """获取session统计信息"""
        sessions = self._get_session_data_list(agent_id, session_id)

        if not sessions:
            return {
                "agent_id": agent_id,
                "session_id": session_id,
                "total_files": 0,
                "total_messages": 0,
                "total_size_bytes": 0,
                "dates": [],
            }

        total_messages = 0
        total_size_bytes = 0
        dates = []

        for session in sessions:
            total_messages += session.get("total_messages", 0)
            # 计算文件大小
            file_path = self._get_session_file(agent_id, session_id, session.get("session_date"))
            if file_path.exists():
                total_size_bytes += file_path.stat().st_size
            dates.append(session.get("session_date"))

        return {
            "agent_id": agent_id,
            "session_id": session_id,
            "total_files": len(sessions),
            "total_messages": total_messages,
            "total_size_bytes": total_size_bytes,
            "dates": sorted(dates),
        }

    def get_recent_context(self, agent_id: str, session_id: str, max_messages: int = 20) -> List[Dict[str, str]]:
        """
        获取最近的对话上下文

        Args:
            agent_id: Agent ID
            session_id: 会话 ID
            max_messages: 最大消息数

        Returns:
            消息列表，格式为 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        """
        # 获取所有日期的 session 数据
        sessions = self._get_session_data_list(agent_id, session_id)

        if not sessions:
            return []

        # 按日期排序，获取最新的
        sessions.sort(key=lambda x: x.get("session_date", ""), reverse=True)

        # 收集所有消息
        all_messages = []
        for session in sessions:
            messages = session.get("messages", [])
            for msg in messages:
                if isinstance(msg, dict):
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role and content:
                        all_messages.append(
                            {
                                "role": role,
                                "content": content,
                            }
                        )

        # 返回最近的 max_messages 条消息
        return all_messages[-max_messages:] if len(all_messages) > max_messages else all_messages

    # ══════════════════════════════════════════════════════════════
    # SessionRepository 接口实现（补全方法）
    # ══════════════════════════════════════════════════════════════

    def save_message(
        self,
        agent_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """保存单条消息到 session（不要求 user+assistant 配对）。

        与现有 add_message（配对写入）共存：本方法供 SessionRepository 接口使用。
        """
        date = datetime.now().strftime("%Y-%m-%d")
        file_path = self._get_session_file(agent_id, session_id, date)
        session_data = self._read_session_file(file_path)

        now = datetime.now().isoformat()
        msg: Dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": now,
        }
        if metadata:
            msg["metadata"] = metadata

        if session_data is None:
            # 文件不存在（可能跨日），创建新记录
            session_data = {
                "agent_id": agent_id,
                "session_id": session_id,
                "session_date": date,
                "messages": [msg],
                "created_at": now,
                "updated_at": now,
                "total_messages": 1,
                "title": "新对话",
                "user_id": "",
            }
        else:
            if "messages" not in session_data:
                session_data["messages"] = []
            session_data["messages"].append(msg)
            session_data["updated_at"] = now
            session_data["total_messages"] = len(session_data["messages"])

        return self._write_session_file(file_path, session_data)

    def get_history(self, agent_id: str, session_id: str, max_messages: int = 0) -> List[Dict[str, Any]]:
        """获取 session 所有日期的所有消息（聚合）。

        Args:
            max_messages: 0 表示全部；>0 取最近 N 条
        """
        sessions = self._get_session_data_list(agent_id, session_id)
        if not sessions:
            return []

        # 按日期升序聚合（旧→新）
        sessions.sort(key=lambda x: x.get("session_date", ""))
        all_messages: List[Dict[str, Any]] = []
        for session in sessions:
            for msg in session.get("messages", []):
                if isinstance(msg, dict):
                    all_messages.append(msg)

        if max_messages > 0 and len(all_messages) > max_messages:
            return all_messages[-max_messages:]
        return all_messages

    def list_sessions(self, agent_id: str = "", user_id: str = "") -> List[Dict[str, Any]]:
        """列出所有会话摘要（按 agent_id/user_id 过滤）。

        返回字段：session_id / agent_id / title / created_at / updated_at / total_messages / user_id
        按 created_at 倒序。
        """
        # 确定扫描目录范围
        if agent_id:
            agent_dirs = [self._get_session_dir(agent_id)]
        else:
            agent_dirs = [d for d in self._sessions_dir.iterdir() if d.is_dir()]

        return self._collect_summaries(agent_dirs, user_id)

    def list_archived_sessions(self, agent_id: str = "", user_id: str = "") -> List[Dict[str, Any]]:
        """列出存档会话摘要（过滤规则与 list_sessions 一致）。"""
        if agent_id:
            archived_dirs = [self._get_archived_dir(agent_id)]
        else:
            archived_dirs = [
                d / "archived"
                for d in self._sessions_dir.iterdir()
                if d.is_dir() and (d / "archived").is_dir()
            ]

        return self._collect_summaries(archived_dirs, user_id)

    def _collect_summaries(self, agent_dirs: List[Path], user_id: str = "") -> List[Dict[str, Any]]:
        """扫描目录收集会话摘要（list_sessions / list_archived_sessions 共用）。"""
        summaries: List[Dict[str, Any]] = []
        seen_session_ids: Dict[str, Dict[str, Any]] = {}

        for agent_dir in agent_dirs:
            if not agent_dir.is_dir():
                continue
            for file_path in agent_dir.glob("session_*.json"):
                session_data = self._read_session_file(file_path)
                if not session_data:
                    continue

                sid = session_data.get("session_id", "")
                s_user_id = session_data.get("user_id", "")
                s_agent_id = session_data.get("agent_id", "")

                # user_id 过滤（空 user_id 不过滤）
                if user_id and s_user_id and s_user_id != user_id:
                    continue

                # 同一 session_id 多日期文件，取最新日期作为代表
                created_at = session_data.get("created_at", "")
                existing = seen_session_ids.get(sid)
                if existing is None or created_at > existing.get("created_at", ""):
                    summary = {
                        "id": sid,
                        "session_id": sid,
                        "agent_id": s_agent_id,
                        "title": session_data.get("title", "新对话"),
                        "user_id": s_user_id,
                        "created_at": created_at,
                        "updated_at": session_data.get("updated_at", ""),
                        "total_messages": session_data.get("total_messages", 0),
                        "pinned": bool(session_data.get("pinned", False)),
                    }
                    seen_session_ids[sid] = summary

        summaries = list(seen_session_ids.values())
        summaries.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return summaries

    def set_session_pinned(self, agent_id: str, session_id: str, pinned: bool) -> bool:
        """置顶/取消置顶 session（写入所有日期文件的 pinned 字段）。"""
        agent_dir = self._get_session_dir(agent_id)
        file_paths = list(agent_dir.glob(f"session_{session_id}_*.json"))
        if not file_paths:
            logger.warning("set_session_pinned: 未找到 session_id=%s 的文件", session_id)
            return False

        ok = True
        for file_path in file_paths:
            session_data = self._read_session_file(file_path)
            if not session_data:
                ok = False
                continue
            session_data["pinned"] = bool(pinned)
            if not self._write_session_file(file_path, session_data):
                ok = False
        return ok

    def rename_session(self, agent_id: str, session_id: str, title: str) -> bool:
        """重命名 session（写入所有日期文件的 title 字段）。"""
        agent_dir = self._get_session_dir(agent_id)
        file_paths = list(agent_dir.glob(f"session_{session_id}_*.json"))
        if not file_paths:
            logger.warning("rename_session: 未找到 session_id=%s 的文件", session_id)
            return False

        ok = True
        for file_path in file_paths:
            session_data = self._read_session_file(file_path)
            if not session_data:
                ok = False
                continue
            session_data["title"] = title
            if not self._write_session_file(file_path, session_data):
                ok = False
        return ok


    # ── 轮次操作（前端 chat 页：编辑最后一条用户消息 = 删旧轮+重发；删除一轮；消息反馈） ──

    @staticmethod
    def _locate_message(
        messages: List[Dict[str, Any]],
        timestamp: str,
        role: Optional[str] = None,
    ) -> Optional[int]:
        """按时间戳定位消息索引。

        双路定位: msg.timestamp（后端落盘时间）或 msg.metadata.client_timestamp
        （前端发送时携带、随 metadata 持久化）。后者兜底"实时轮次客户端
        时间戳不落盘"的定位失败问题。
        """
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                continue
            if role is not None and msg.get("role") != role:
                continue
            if msg.get("timestamp") == timestamp:
                return i
            meta = msg.get("metadata")
            if isinstance(meta, dict) and meta.get("client_timestamp") == timestamp:
                return i
        return None

    def _iter_session_files(self, agent_id: str, session_id: str) -> List[Path]:
        """按日期升序返回该 session 的所有文件（旧→新，跨日轮次定位需要）。"""
        agent_dir = self._get_session_dir(agent_id)
        return sorted(agent_dir.glob(f"session_{session_id}_*.json"))

    def delete_round(self, agent_id: str, session_id: str, timestamp: str) -> List[Dict[str, Any]]:
        """删除一轮对话（user 消息 + 其后相邻的 assistant 回复）。

        用于"编辑最后一条用户消息"（删旧轮后由前端走原发送链路重发，
        管线写入新轮 session 记录与记忆，实现覆写）和"删除任意一轮记录"。

        Returns:
            被删除的消息 dict 列表（供调用方清除对应记忆）；未定位到轮次
            或写入失败时返回空列表。
        """
        for file_path in self._iter_session_files(agent_id, session_id):
            file_lock = self._get_file_lock(file_path)
            with file_lock:
                session_data = self._read_session_file(file_path)
                if not session_data:
                    continue
                messages = session_data.get("messages", [])
                idx = self._locate_message(messages, timestamp, role="user")
                if idx is None:
                    continue

                deleted = [messages[idx]]
                # 配对 assistant: add_message 成对相邻写入；流式中断的孤立
                # user 消息没有后继 assistant，循环自然只删 1 条
                j = idx + 1
                while j < len(messages) and messages[j].get("role") == "assistant":
                    deleted.append(messages[j])
                    j += 1

                session_data["messages"] = messages[:idx] + messages[j:]
                session_data["total_messages"] = len(session_data["messages"])
                session_data["updated_at"] = datetime.now().isoformat()
                if self._write_session_file_unlocked(file_path, session_data):
                    return deleted
                logger.error(
                    "delete_round 写入失败: agent_id=%s, session_id=%s, file=%s",
                    agent_id, session_id, file_path,
                )
                return []
        return []

    def get_round(self, agent_id: str, session_id: str, timestamp: str) -> Optional[Dict[str, Any]]:
        """按轮次定位键读取一轮对话（user + assistant 消息 dict，含 content）。

        先按 role=assistant 双路定位（同轮 user/assistant 共享落盘时间戳或
        client_timestamp），user 取其前最近一条；无 assistant 命中时回退按
        role=user 定位（孤立尾 user 消息场景），assistant 返回 None。

        Returns:
            {"user": msg | None, "assistant": msg | None}；未定位到返回 None。
        """
        for file_path in self._iter_session_files(agent_id, session_id):
            file_lock = self._get_file_lock(file_path)
            with file_lock:
                session_data = self._read_session_file(file_path)
                if not session_data:
                    continue
                messages = session_data.get("messages", [])

                idx = self._locate_message(messages, timestamp, role="assistant")
                if idx is not None:
                    user_idx = None
                    for k in range(idx - 1, -1, -1):
                        if isinstance(messages[k], dict) and messages[k].get("role") == "user":
                            user_idx = k
                            break
                    return {
                        "user": messages[user_idx] if user_idx is not None else None,
                        "assistant": messages[idx],
                    }

                idx = self._locate_message(messages, timestamp, role="user")
                if idx is not None:
                    next_msg = messages[idx + 1] if idx + 1 < len(messages) else None
                    assistant = (
                        next_msg
                        if isinstance(next_msg, dict) and next_msg.get("role") == "assistant"
                        else None
                    )
                    return {"user": messages[idx], "assistant": assistant}
        return None

    def update_message_metadata(
        self,
        agent_id: str,
        session_id: str,
        timestamp: str,
        metadata_patch: Dict[str, Any],
        role: Optional[str] = None,
    ) -> bool:
        """按时间戳（+可选 role）定位单条消息，合并 metadata 补丁。

        用于点赞/点踩反馈持久化到 session 消息 metadata（role="assistant"）。

        Returns:
            定位并写入成功返回 True；未找到或写入失败返回 False。
        """
        for file_path in self._iter_session_files(agent_id, session_id):
            file_lock = self._get_file_lock(file_path)
            with file_lock:
                session_data = self._read_session_file(file_path)
                if not session_data:
                    continue
                messages = session_data.get("messages", [])
                idx = self._locate_message(messages, timestamp, role=role)
                if idx is None:
                    continue

                msg = messages[idx]
                meta = dict(msg.get("metadata") or {})
                meta.update(metadata_patch)
                msg["metadata"] = meta
                session_data["updated_at"] = datetime.now().isoformat()
                if self._write_session_file_unlocked(file_path, session_data):
                    return True
                logger.error(
                    "update_message_metadata 写入失败: agent_id=%s, session_id=%s, file=%s",
                    agent_id, session_id, file_path,
                )
                return False
        return False


def get_session_manager() -> SessionManager:
    """获取SessionManager单例"""
    return SessionManager()
