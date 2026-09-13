"""
会话备份管理器
将对话内容按agent和session_id隔离，直接即时写入文件，无内存缓存
"""

import json
import re
from collections import OrderedDict
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

    # B-9: 摘要/反馈缓存条目上限（LRU，超限逐出最旧）
    _SUMMARY_CACHE_MAX = 2000
    _FEEDBACK_CACHE_MAX = 2000
    # B-9 (台账 2026-09-11): 摘要/反馈聚合的进程级读缓存，键 =
    # (文件路径, st_mtime_ns, st_size)。写路径 mtime/size 变化自然失效，
    # 无需主动失效；只挂读路径（_collect_summaries / get_feedback_counts），
    # S4/S3 写锁语义不受影响。挂在类上而非 __init__：存在
    # object.__new__ 绕过 __init__ 的实例构造路径（单例测试隔离），
    # 单例语义下缓存本就是进程级共享。
    _parse_cache_lock = RLock()
    _summary_cache: "OrderedDict" = OrderedDict()
    _feedback_cache: "OrderedDict" = OrderedDict()

    # ── B-9 v2（2026-09-11 拍板）：落盘摘要 sidecar 索引 ──────────────
    # 每 agent 目录一份 _summary_index.json：session_id → 摘要字段 +
    # like/dislike 聚合 + 最近反馈明细 + 指纹 fp（该会话全部日期文件的
    # st_mtime_ns+st_size 之和）。写路径在既有锁内同步维护；读路径优先
    # 读索引（零会话文件解析），索引缺失/损坏/版本不符/指纹失配 → 回退
    # 全量扫描并顺手重建（自愈）。锁序：会话文件锁 → sidecar 文件锁
    # （sidecar 锁为叶子锁，重建扫描不取会话锁，不成环）。
    _SIDECAR_NAME = "_summary_index.json"
    _SIDECAR_SCHEMA_VERSION = 1
    _SIDECAR_FEEDBACK_ITEMS_MAX = 20
    _SIDECAR_CACHE_MAX = 64
    _SUMMARY_FIELDS = (
        "id", "session_id", "agent_id", "title", "user_id",
        "created_at", "updated_at", "total_messages", "pinned", "sort_order",
    )
    _sidecar_cache: "OrderedDict" = OrderedDict()

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
            # 2026-09-07 根因修复（audit SUB-P0-6）：文件锁改 RLock——
            # _quarantine_broken_file 在 add_message 等持锁路径内被调用且
            # 自行再次取锁，非重入 Lock 会同线程永久死锁
            self._file_locks: Dict[str, RLock] = {}
            # S3 修复 (Critical #4 TOCTOU): 保护 _file_locks dict 的独立 RLock.
            # RLock 允许 _get_file_lock 在持锁时被同线程重入调用 (如 __init__ 内部).
            self._file_locks_lock = RLock()

    def _get_file_lock(self, file_path) -> RLock:
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
            # B-9 sidecar: 主索引移除条目（archived 侧由读路径指纹校验自愈重建）
            self._sidecar_mutate(agent_dir, session_id, remove=True)
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
            # B-9 sidecar: 存档索引移除条目（主索引由读路径指纹校验自愈重建）
            self._sidecar_mutate(archived_dir, session_id, remove=True)
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
        except json.JSONDecodeError as e:
            # 损坏文件（含 0 字节截断）：根因 = Windows 无 flock + 旧版
            # 先截断后写入的交叉写。坏文件若不隔离，每次读取请求都会
            # 重复打 ERROR 且永远解析失败——隔离留档（.corrupt-*.bak）后
            # 目录回归干净，sessions 列表/history 可正常跳过该会话。
            self._quarantine_broken_file(file_path)
            logger.warning(
                "读取session文件失败(非法JSON)，已隔离损坏文件 %s -> %s.corrupt-*.bak: %s",
                file_path, file_path, e,
            )
            return None
        except Exception as e:
            logger.error("读取session文件失败: %s", e)
            return None

    def _quarantine_broken_file(self, file_path: Path) -> None:
        """将损坏的 session 文件重命名隔离，避免后续每次请求重复报错。"""
        try:
            lock = self._get_file_lock(file_path)
            with lock:
                if not file_path.exists():
                    return
                quarantine = file_path.with_name(
                    "%s.corrupt-%s.bak" % (file_path.name, datetime.now().strftime("%Y%m%d%H%M%S"))
                )
                file_path.replace(quarantine)
                logger.warning("session 损坏文件已隔离: %s -> %s", file_path, quarantine)
        except Exception as e:
            # 隔离失败不致命：保持现状（后续请求仍会报错但不会崩溃）
            logger.debug("隔离损坏 session 文件失败: %s", e, exc_info=True)

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
            # 原子写（tmp + os.replace）：直接 open(file_path, "w") 会先截断
            # 目标文件；Windows 无 flock 可用的场景（HAS_FCNTL=False）下，
            # 两个进程同时写同一文件 → 交叉截断 → 磁盘留下非法 JSON（即
            # "读取session文件失败 Expecting value" 的根因）。tmp+replace 使
            # 读方永远看到完整文件（last-write-wins，最坏丢更新不损坏）。
            tmp_path = file_path.with_name(file_path.name + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, file_path)
            return True
        except Exception as e:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
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
        writer_claim=None,
        user_id: str = "",
    ) -> str:
        """添加一条对话（user + assistant 两条消息）到session

        S4 修复 (Critical #5 跨锁 RMW): read-modify-write 整体置于 file_lock 内.
        Bug: 原 read 在锁外, write 在锁内,两线程可同时 read 同一旧状态,
        后写者覆盖先写者的更新 (lost update).

        R-2 修复: 新增 assistant_metadata——assistant 专属元数据（思考过程
        reasoning_content、工具调用 tool_calls）。此前 reasoning 经 post_chat
        管线一路传递到 mem_core.save_to_session 后被静默丢弃，切换页面重开
        会话后思考过程不显示。不传时保持旧行为：metadata 仍写入双方消息。

        P1-10 写入围栏: writer_claim=(FenceClaim) 显式参与——check 失效时
        跳过写盘返回 ""（被夺权的 run 永远写不进陈旧数据），不抛异常；
        不传时行为与历史完全一致（等价性）。

        审计 2026-09-11 DATA-P1-1: 新建会话分支补 user_id/title 写入（与
        create_session/save_message 契约对齐）；存量会话缺 user_id 时回填。
        原实现新建会话不带 user_id → _collect_summaries 对空属主放行，
        会话对所有用户可见（越权展示）。
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        # P1-10 写入围栏: 参与 claim 已失效 → 拒绝写入（跳过,不抛异常）
        if writer_claim is not None:
            try:
                from neurova.agent.history_fence import get_history_write_fence

                _fence = get_history_write_fence()
                if not _fence.check(agent_id, session_id, writer_claim):
                    _fence.record_fenced_write()
                    logger.info(
                        "会话写入被围栏拒绝（陈旧 writer）: agent=%s, session=%s, writer=%s",
                        agent_id, session_id, getattr(writer_claim, "writer_id", "?"),
                    )
                    return ""
            except Exception as fence_err:  # noqa: BLE001 - 围栏故障绝不阻断正常写入
                logger.debug("围栏检查异常,降级放行: %s", fence_err)

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
                    "title": "新对话",
                    "user_id": str(user_id or ""),
                }
            else:
                # 更新现有session记录
                if "messages" not in session_data:
                    session_data["messages"] = []

                session_data["messages"].extend(new_messages)
                session_data["updated_at"] = now
                session_data["total_messages"] = len(session_data["messages"])
                # DATA-P1-1: 存量会话缺属主时回填（下次过滤即生效）
                if user_id and not session_data.get("user_id"):
                    session_data["user_id"] = str(user_id)

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

            # B-9 sidecar: 摘要/反馈同步索引（仍在会话文件锁内，锁序 =
            # 会话锁 → sidecar 锁；新增 assistant 消息若带 feedback 一并计入）
            fb = self._feedback_from_data({"messages": [assistant_msg]})
            self._sidecar_mutate(
                self._get_session_dir(agent_id),
                session_id,
                summary_data=session_data,
                like_delta=fb["like"],
                dislike_delta=fb["dislike"],
                add_items=fb["items"],
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
        # B-9 sidecar: 空会话摘要同步落盘索引
        self._sidecar_mutate(self._get_session_dir(agent_id), session_id, summary_data=session_data)
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
                        # B-9 sidecar: 移除索引条目；残留其他日期文件时
                        # 读路径指纹校验会自愈重建代表条目
                        self._sidecar_mutate(self._get_session_dir(agent_id), session_id, remove=True)
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
                # B-9 sidecar: 该会话全部日期文件已删除 → 移除索引条目
                self._sidecar_mutate(self._get_session_dir(agent_id), session_id, remove=True)
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

    def get_recent_context(self, agent_id: str, session_id: str, max_messages: Optional[int] = 20) -> List[Dict[str, str]]:
        """
        获取最近的对话上下文

        Args:
            agent_id: Agent ID
            session_id: 会话 ID
            max_messages: 最大消息数（None=不截断，返回全会话消息；/compact 命令用）

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
        # Yuxi 对比 P2 #14 不变量：模型上下文只含 user/assistant 轮次——
        # 工具/审计型行（save_message 写侧不设防，如 session fork 带入）
        # 不得回灌模型诱发幻觉。展示路径 get_history 不筛（UI 可见性不变）。
        all_messages = []
        for session in sessions:
            messages = session.get("messages", [])
            for msg in messages:
                if isinstance(msg, dict):
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role and content and role in ("user", "assistant"):
                        all_messages.append(
                            {
                                "role": role,
                                "content": content,
                            }
                        )

        # 返回最近的 max_messages 条消息（None=不截断）
        if max_messages is None:
            return all_messages
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
        # 2026-09-07 根因修复（audit SUB-P1-7）：read-modify-write 全程持
        # file_lock——原锁外读陈旧快照写回，并发 add_message 会静默回滚最后一轮
        file_lock = self._get_file_lock(file_path)
        with file_lock:
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

            # S4: 写入在 file_lock 内；B-9 sidecar 同步索引（assistant 消息
            # 携带 feedback 时计入增量——fork 复制带反馈历史的消息走此路径）
            write_ok = self._write_session_file_unlocked(file_path, session_data)
            if write_ok:
                fb = (
                    self._feedback_from_data({"messages": [msg]})
                    if role == "assistant"
                    else {"like": 0, "dislike": 0, "items": []}
                )
                self._sidecar_mutate(
                    self._get_session_dir(agent_id),
                    session_id,
                    summary_data=session_data,
                    like_delta=fb["like"],
                    dislike_delta=fb["dislike"],
                    add_items=fb["items"],
                )
            return write_ok

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

    def get_feedback_counts(self, agent_id: str, session_id: str) -> Dict[str, Any]:
        """单会话点赞/点踩聚合（B-9, 台账 2026-09-11）。

        优先读 sidecar 索引条目（指纹校验，O(索引)，零会话文件解析）；
        索引缺失/指纹失配/条目无反馈字段时回退逐文件
        (路径, mtime_ns, size) 缓存聚合。

        Returns:
            {"like": int, "dislike": int,
             "items": [{"session_id", "timestamp", "content"(≤100), "feedback"}]}
            （items 为最近 ≤_SIDECAR_FEEDBACK_ITEMS_MAX 条，按落盘顺序；
             跨会话聚合与排序由调用方完成）
        """
        agent_dir = self._get_session_dir(agent_id)
        index = self._load_sidecar(agent_dir)
        if index is not None:
            entry = index["sessions"].get(session_id)
            if (
                isinstance(entry, dict)
                and "like_count" in entry
                and entry.get("fp") == self._session_fingerprint(agent_dir, session_id)
            ):
                return {
                    "like": int(entry.get("like_count", 0)),
                    "dislike": int(entry.get("dislike_count", 0)),
                    "items": [
                        dict(it, session_id=session_id)
                        for it in entry.get("recent_feedback", [])
                        if isinstance(it, dict)
                    ],
                }
        like = 0
        dislike = 0
        items: List[Dict[str, Any]] = []
        for file_path in self._iter_session_files(agent_id, session_id):
            agg = self._get_cached_feedback(file_path)
            if not agg:
                continue
            like += agg["like"]
            dislike += agg["dislike"]
            for it in agg["items"]:
                item = dict(it)
                item["session_id"] = session_id
                items.append(item)
        return {"like": like, "dislike": dislike, "items": items}

    def _get_cached_feedback(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """单文件反馈聚合（缓存值不含 session_id，同一文件跨会话复用安全）。"""
        key = self._stat_cache_key(file_path)
        if key is None:
            return None
        cached = self._cache_get(self._feedback_cache, key)
        if cached is not None:
            return cached
        session_data = self._read_session_file(file_path)
        if not session_data:
            return None
        agg = self._feedback_from_data(session_data)
        self._cache_put(self._feedback_cache, key, agg, self._FEEDBACK_CACHE_MAX)
        return agg

    def find_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """按 session_id 定位会话摘要（审计 P1-F4 索引式查找）。

        原 delete/rename/auto-title/round-ops 每请求 repo.list_sessions()
        全库扫描——glob 所有 agent 目录的全部 session_*.json 并完整读入
        （含全部消息正文），只为定位一个会话。现按文件名 glob 直配
        （session_{id}_*.json 命中前零内容读取），命中仅读单个文件。
        """
        if not session_id:
            return None
        try:
            for agent_dir in self._sessions_dir.iterdir():
                if not agent_dir.is_dir():
                    continue
                matches = sorted(agent_dir.glob(f"session_{session_id}_*.json"))
                if not matches:
                    continue
                # 最新日期文件为代表（与 _collect_summaries 口径一致）
                data = self._read_session_file(matches[-1])
                if not data:
                    continue
                sid = data.get("session_id", "")
                return {
                    "session_id": sid or session_id,
                    "id": sid or session_id,
                    "agent_id": data.get("agent_id", "") or agent_dir.name,
                    "title": data.get("title", "新对话"),
                    "user_id": data.get("user_id", ""),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "total_messages": data.get("total_messages", 0),
                }
        except Exception as e:
            logger.warning("find_session(%s) failed: %s", session_id, e)
        return None

    def list_sessions(self, agent_id: str = "", user_id: str = "") -> List[Dict[str, Any]]:
        """列出所有会话摘要（按 agent_id/user_id 过滤）。

        返回字段：session_id / agent_id / title / created_at / updated_at / total_messages / user_id
        按 created_at 倒序（sort_order>0 升序在前）。

        B-9 v2：优先读落盘 sidecar 索引（O(索引)，零会话文件解析）；索引
        缺失/损坏/版本不符/指纹失配 → 回退全量扫描并顺手重建索引（自愈）。
        """
        # 确定扫描目录范围
        if agent_id:
            agent_dirs = [self._get_session_dir(agent_id)]
        else:
            agent_dirs = [d for d in self._sessions_dir.iterdir() if d.is_dir()]

        fast = self._summaries_via_sidecar(agent_dirs, user_id)
        if fast is not None:
            return fast
        summaries = self._collect_summaries(agent_dirs, user_id)
        # 自愈：回退扫描后顺手重建各目录索引（best-effort，失败不影响本次结果）
        for agent_dir in agent_dirs:
            self._rebuild_sidecar(agent_dir)
        return summaries

    def list_archived_sessions(self, agent_id: str = "", user_id: str = "") -> List[Dict[str, Any]]:
        """列出存档会话摘要（过滤规则与 list_sessions 一致，读路径同走 sidecar）。"""
        if agent_id:
            archived_dirs = [self._get_archived_dir(agent_id)]
        else:
            archived_dirs = [
                d / "archived"
                for d in self._sessions_dir.iterdir()
                if d.is_dir() and (d / "archived").is_dir()
            ]

        fast = self._summaries_via_sidecar(archived_dirs, user_id)
        if fast is not None:
            return fast
        summaries = self._collect_summaries(archived_dirs, user_id)
        for archived_dir in archived_dirs:
            self._rebuild_sidecar(archived_dir)
        return summaries

    # session_{session_id}_{date}.json 尾部日期后缀（YYYY-MM-DD）
    _SESSION_DATE_SUFFIX_RE = re.compile(r"_\d{4}-\d{2}-\d{2}$")

    @classmethod
    def _sid_from_filename(cls, file_path: Path) -> str:
        """从文件名解析 session_id（session_{sid}_{date}.json → sid，零内容读取）。"""
        name = file_path.stem
        if not name.startswith("session_"):
            return ""
        return cls._SESSION_DATE_SUFFIX_RE.sub("", name[len("session_"):])

    def count_sessions(self, agent_id: str = "", user_id: str = "") -> int:
        """会话总数（零 JSON 解析快路径）。

        RES-P1-4：home 统计此前 len(list_sessions()) 为取个数而全量
        json.load 所有会话消息（O(总历史字节)，随历史线性劣化）。
        session_id 编码在文件名中，无 user_id 过滤时直接 glob + 文件名去重；
        带 user_id 过滤需读内容，退回摘要路径。
        """
        if user_id:
            return len(self.list_sessions(agent_id=agent_id, user_id=user_id))
        if agent_id:
            agent_dirs = [self._get_session_dir(agent_id)]
        else:
            if not self._sessions_dir.is_dir():
                return 0
            agent_dirs = [d for d in self._sessions_dir.iterdir() if d.is_dir()]

        seen: set = set()
        for agent_dir in agent_dirs:
            if not agent_dir.is_dir():
                continue
            for fp in agent_dir.glob("session_*.json"):
                sid = self._sid_from_filename(fp)
                if sid:
                    seen.add(sid)
        return len(seen)

    # ── B-9: (路径, mtime_ns, size) 键的进程内读缓存 ──────────────────

    def _stat_cache_key(self, file_path: Path) -> Optional[tuple]:
        """构造缓存键 (路径, st_mtime_ns, st_size)；stat 失败（文件消失）返回 None。"""
        try:
            st = file_path.stat()
        except OSError:
            return None
        return (str(file_path), st.st_mtime_ns, st.st_size)

    def _cache_get(self, cache: OrderedDict, key: tuple) -> Any:
        with self._parse_cache_lock:
            value = cache.get(key)
            if value is not None:
                cache.move_to_end(key)
            return value

    def _cache_put(self, cache: OrderedDict, key: tuple, value: Any, max_entries: int) -> None:
        with self._parse_cache_lock:
            cache[key] = value
            cache.move_to_end(key)
            while len(cache) > max_entries:
                cache.popitem(last=False)

    @staticmethod
    def _summary_from_data(session_data: Dict[str, Any]) -> Dict[str, Any]:
        """从 session 文件数据提取摘要字段（纯函数，v1 _get_cached_summary 抽出）。"""
        sid = session_data.get("session_id", "")
        return {
            "id": sid,
            "session_id": sid,
            "agent_id": session_data.get("agent_id", ""),
            "title": session_data.get("title", "新对话"),
            "user_id": session_data.get("user_id", ""),
            "created_at": session_data.get("created_at", ""),
            "updated_at": session_data.get("updated_at", ""),
            "total_messages": session_data.get("total_messages", 0),
            "pinned": bool(session_data.get("pinned", False)),
            "sort_order": int(session_data.get("sort_order", 0) or 0),
        }

    @staticmethod
    def _feedback_from_data(session_data: Dict[str, Any]) -> Dict[str, Any]:
        """从 session 文件数据提取反馈聚合（纯函数，v1 _get_cached_feedback 抽出）。

        仅统计 assistant 消息的 metadata.feedback ∈ {like, dislike}。
        """
        like = 0
        dislike = 0
        items: List[Dict[str, Any]] = []
        for m in session_data.get("messages", []) or []:
            if not isinstance(m, dict) or m.get("role") != "assistant":
                continue
            fb = (m.get("metadata") or {}).get("feedback")
            if fb not in ("like", "dislike"):
                continue
            if fb == "like":
                like += 1
            else:
                dislike += 1
            items.append(
                {
                    "timestamp": m.get("timestamp", ""),
                    "content": (m.get("content") or "")[:100],
                    "feedback": fb,
                }
            )
        return {"like": like, "dislike": dislike, "items": items}

    def _get_cached_summary(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """单文件会话摘要；mtime/size 未变时复用上次解析，不再 json.load。"""
        key = self._stat_cache_key(file_path)
        if key is None:
            return None
        cached = self._cache_get(self._summary_cache, key)
        if cached is not None:
            return dict(cached)
        session_data = self._read_session_file(file_path)
        if not session_data:
            return None
        summary = self._summary_from_data(session_data)
        self._cache_put(self._summary_cache, key, summary, self._SUMMARY_CACHE_MAX)
        return dict(summary)

    def _collect_summaries(self, agent_dirs: List[Path], user_id: str = "") -> List[Dict[str, Any]]:
        """扫描目录收集会话摘要（list_sessions / list_archived_sessions 共用）。

        B-9: 单文件摘要经 (路径, mtime_ns, size) 缓存——文件未变不重复
        json.load（此前每次列表都全量解析所有会话的全部消息正文）。
        """
        seen_session_ids: Dict[str, Dict[str, Any]] = {}

        for agent_dir in agent_dirs:
            if not agent_dir.is_dir():
                continue
            for file_path in agent_dir.glob("session_*.json"):
                summary = self._get_cached_summary(file_path)
                if not summary:
                    continue

                sid = summary["session_id"]

                # user_id 过滤（空 user_id 不过滤）
                if user_id and summary["user_id"] and summary["user_id"] != user_id:
                    continue

                # 同一 session_id 多日期文件，取最新日期作为代表
                existing = seen_session_ids.get(sid)
                if existing is None or summary["created_at"] > existing.get("created_at", ""):
                    seen_session_ids[sid] = summary

        summaries = list(seen_session_ids.values())
        return self._order_summaries(summaries)

    @staticmethod
    def _order_summaries(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """拖拽排序落库:sort_order>0 的会话按其升序在前,未排序(0)按 created_at
        倒序垫底(新→旧)。951d8c0b 曾把此排序写成三键升序元组——未排序区
        created_at 变升序(最老在前),最新会话全部沉底,前端 loadSessions
        auto-select 列表第一项打开的是老空会话,用户感知"重启后会话全丢"。
        ISO 时间串无法取负,单一 sort 表达不出 ASC/DESC 混排,分区排序实现。
        （sidecar 读路径与全量扫描共用，保证两条路径排序逐字段一致。）
        """
        ordered = [x for x in summaries if int(x.get("sort_order", 0) or 0)]
        unsorted_ = [x for x in summaries if not int(x.get("sort_order", 0) or 0)]
        ordered.sort(key=lambda x: int(x.get("sort_order", 0) or 0))
        unsorted_.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return ordered + unsorted_

    # ── B-9 v2: 落盘摘要 sidecar 索引（_summary_index.json） ──────────

    @staticmethod
    def _read_json_plain(file_path: Path) -> Optional[Dict[str, Any]]:
        """sidecar 专用直读：不隔离、不取会话文件锁。

        重建/读路径可能持有 sidecar 锁，此时不得再取会话文件锁
        （写路径锁序为 会话锁→sidecar 锁，反向获取会成环死锁）；
        损坏索引交由读路径回退重建（原子写覆盖坏文件）处理。
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def _atomic_write_json(file_path: Path, data: Dict[str, Any]) -> bool:
        """小 JSON 文件原子写（tmp + os.replace + fsync，同会话文件写纪律）。"""
        try:
            text = json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError, OverflowError) as e:
            logger.debug("JSON 序列化失败, 跳过写入 %s: %s", file_path, e)
            return False
        try:
            tmp_path = file_path.with_name(file_path.name + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, file_path)
            return True
        except Exception as e:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            logger.debug("写入 %s 失败: %s", file_path, e)
            return False

    def _session_fingerprint(self, agent_dir: Path, session_id: str) -> int:
        """单会话指纹 = 全部日期文件的 st_mtime_ns + st_size 之和。

        内容级变更探测：任何绕过 manager 的写入都会改变 mtime/size →
        指纹失配 → 读路径回退重建。零 JSON 解析，仅 stat。
        """
        total = 0
        for fp in agent_dir.glob(f"session_{session_id}_*.json"):
            try:
                st = fp.stat()
            except OSError:
                continue
            total += st.st_mtime_ns + st.st_size
        return total

    def _dir_fingerprints(self, agent_dir: Path) -> Optional[Dict[str, int]]:
        """整目录 session_id → 指纹映射；stat 失败（文件正消失）返回 None。"""
        fps: Dict[str, int] = {}
        for fp in agent_dir.glob("session_*.json"):
            sid = self._sid_from_filename(fp)
            if not sid:
                continue
            try:
                st = fp.stat()
            except OSError:
                return None
            fps[sid] = fps.get(sid, 0) + st.st_mtime_ns + st.st_size
        return fps

    def _load_sidecar(self, agent_dir: Path) -> Optional[Dict[str, Any]]:
        """读取并校验 sidecar 索引（进程内按 (路径, mtime, size) 缓存）。

        缺失/损坏/版本不符返回 None（调用方回退全量扫描并重建）。
        """
        idx_path = agent_dir / self._SIDECAR_NAME
        key = self._stat_cache_key(idx_path)
        if key is None:
            return None
        cached = self._cache_get(self._sidecar_cache, key)
        if cached is not None:
            return cached
        data = self._read_json_plain(idx_path)
        if (
            not isinstance(data, dict)
            or data.get("schema_version") != self._SIDECAR_SCHEMA_VERSION
            or not isinstance(data.get("sessions"), dict)
        ):
            return None
        self._cache_put(self._sidecar_cache, key, data, self._SIDECAR_CACHE_MAX)
        return data

    def _compute_sidecar_entry(
        self, agent_dir: Path, session_id: str, quarantine: bool = True
    ) -> Optional[Dict[str, Any]]:
        """从该会话的全部日期文件重算索引条目（rep 摘要 + 全量反馈聚合 + 指纹）。

        quarantine=False（sidecar 锁内的 mutate 重算路径）跳过损坏文件隔离：
        隔离会取会话文件锁，与写路径「会话锁→sidecar 锁」次序成环；
        损坏文件由其他读路径（列表回退/历史读取）照常隔离，隔离后文件
        消失 → 指纹变化 → 下次读路径重建收敛。
        """
        rep: Optional[Dict[str, Any]] = None
        like = 0
        dislike = 0
        items: List[Dict[str, Any]] = []
        for fp in sorted(agent_dir.glob(f"session_{session_id}_*.json")):
            data = self._read_session_file(fp) if quarantine else self._read_json_plain(fp)
            if not data:
                continue
            summary = self._summary_from_data(data)
            if rep is None or str(summary.get("created_at", "")) >= str(rep.get("created_at", "")):
                rep = summary
            fb = self._feedback_from_data(data)
            like += fb["like"]
            dislike += fb["dislike"]
            items.extend(fb["items"])
        if rep is None:
            return None
        entry = dict(rep)
        entry["like_count"] = like
        entry["dislike_count"] = dislike
        entry["recent_feedback"] = items[-self._SIDECAR_FEEDBACK_ITEMS_MAX:]
        entry["fp"] = self._session_fingerprint(agent_dir, session_id)
        return entry

    def _rebuild_sidecar(self, agent_dir: Path) -> Optional[Dict[str, Any]]:
        """全量扫描重建索引并原子落盘（自愈出口）。

        扫描阶段不持 sidecar 锁（_read_session_file 可能隔离损坏文件、
        取会话文件锁）；落盘阶段持 sidecar 文件锁。并发写路径在扫描窗口
        内的增量可能被本次覆盖，但其会话文件 mtime 已变 → 指纹失配 →
        下次读路径自动再重建（收敛）。
        """
        if not agent_dir.is_dir():
            return None
        sids = set()
        for fp in agent_dir.glob("session_*.json"):
            sid = self._sid_from_filename(fp)
            if sid:
                sids.add(sid)
        entries: Dict[str, Dict[str, Any]] = {}
        for sid in sorted(sids):
            entry = self._compute_sidecar_entry(agent_dir, sid)
            if entry is not None:
                entries[sid] = entry
        index = {
            "schema_version": self._SIDECAR_SCHEMA_VERSION,
            "rebuilt_at": datetime.now().isoformat(),
            "sessions": entries,
        }
        idx_path = agent_dir / self._SIDECAR_NAME
        try:
            lock = self._get_file_lock(idx_path)
            with lock:
                self._atomic_write_json(idx_path, index)
        except Exception as e:
            logger.warning("sidecar 索引重建落盘失败（内存结果仍可用于本次请求）: %s", e)
        return index

    def _summary_from_entry(self, sid: str, entry: Dict[str, Any]) -> Dict[str, Any]:
        """索引条目 → 对外摘要视图（仅 _SUMMARY_FIELDS，不泄漏内部字段）。"""
        return {
            "id": sid,
            "session_id": sid,
            "agent_id": entry.get("agent_id", ""),
            "title": entry.get("title", "新对话"),
            "user_id": entry.get("user_id", ""),
            "created_at": entry.get("created_at", ""),
            "updated_at": entry.get("updated_at", ""),
            "total_messages": entry.get("total_messages", 0),
            "pinned": bool(entry.get("pinned", False)),
            "sort_order": int(entry.get("sort_order", 0) or 0),
        }

    def _summaries_via_sidecar(self, agent_dirs: List[Path], user_id: str = "") -> Optional[List[Dict[str, Any]]]:
        """B-9 v2 读路径：全部目录索引有效时返回摘要列表，否则 None（回退重建）。

        有效性 = 索引可读且版本匹配 + 目录文件集与索引键一致 + 每会话
        指纹匹配（探测一切绕过 manager 的内容改写）。user_id 过滤与
        跨目录同 sid 去重规则与 _collect_summaries 逐字段对齐。
        """
        seen: Dict[str, Dict[str, Any]] = {}
        for agent_dir in agent_dirs:
            if not agent_dir.is_dir():
                continue
            index = self._load_sidecar(agent_dir)
            if index is None:
                return None
            disk_fps = self._dir_fingerprints(agent_dir)
            if disk_fps is None:
                return None
            sessions = index["sessions"]
            if set(sessions.keys()) != set(disk_fps.keys()):
                return None
            for sid, entry in sessions.items():
                if not isinstance(entry, dict) or entry.get("fp") != disk_fps[sid]:
                    return None
                entry_user = str(entry.get("user_id", "") or "")
                if user_id and entry_user and entry_user != user_id:
                    continue
                summary = self._summary_from_entry(sid, entry)
                existing = seen.get(sid)
                if existing is None or summary["created_at"] > existing.get("created_at", ""):
                    seen[sid] = summary
        return self._order_summaries(list(seen.values()))

    def _sidecar_mutate(
        self,
        agent_dir: Path,
        session_id: str,
        *,
        remove: bool = False,
        summary_data: Optional[Dict[str, Any]] = None,
        like_delta: int = 0,
        dislike_delta: int = 0,
        add_items: Optional[List[Dict[str, Any]]] = None,
        remove_item_timestamps: Optional[List[str]] = None,
    ) -> None:
        """写路径同步更新 sidecar 索引（自身文件锁内读-改-写）。

        - remove=True：删除条目（delete/archive/unarchive 后调用）。
        - summary_data：写路径持有的该会话文件最新数据；仅当其 created_at
          ≥ 现条目（即写入的是代表文件）时更新摘要字段（与全量扫描
          "同 sid 取 created_at 最新文件"口径一致）。条目缺失时整体重算。
        - like/dislike_delta / add_items / remove_item_timestamps：反馈增量
          （会话级跨日期聚合，与代表文件无关，恒应用）。

        索引不存在/损坏时以空索引冷启动并写入本次变更（部分索引由读路径
        文件集/指纹校验自愈补全）；remove 遇缺失索引无事可做直接跳过。
        任何异常降级为移除索引文件（下次读路径全量重建），绝不阻断主写路径。
        """
        idx_path = agent_dir / self._SIDECAR_NAME
        try:
            lock = self._get_file_lock(idx_path)
            with lock:
                index = self._read_json_plain(idx_path)
                if (
                    not isinstance(index, dict)
                    or index.get("schema_version") != self._SIDECAR_SCHEMA_VERSION
                    or not isinstance(index.get("sessions"), dict)
                ):
                    if remove:
                        return
                    index = {
                        "schema_version": self._SIDECAR_SCHEMA_VERSION,
                        "rebuilt_at": datetime.now().isoformat(),
                        "sessions": {},
                    }
                sessions = index["sessions"]
                if remove:
                    sessions.pop(session_id, None)
                else:
                    entry = sessions.get(session_id)
                    if entry is None:
                        # 锁外不可行的重算：quarantine=False 避免持 sidecar
                        # 锁时取会话文件锁（锁序成环，见 _compute_sidecar_entry）
                        entry = self._compute_sidecar_entry(agent_dir, session_id, quarantine=False)
                        if entry is None:
                            return
                        sessions[session_id] = entry
                    else:
                        if summary_data is not None:
                            summary = self._summary_from_data(summary_data)
                            if str(summary.get("created_at", "")) >= str(entry.get("created_at", "")):
                                entry.update(summary)
                        if like_delta or dislike_delta or add_items or remove_item_timestamps:
                            entry["like_count"] = int(entry.get("like_count", 0)) + like_delta
                            entry["dislike_count"] = int(entry.get("dislike_count", 0)) + dislike_delta
                            items = entry.get("recent_feedback")
                            if not isinstance(items, list):
                                items = []
                            for ts in remove_item_timestamps or []:
                                for i, it in enumerate(items):
                                    if isinstance(it, dict) and it.get("timestamp") == ts:
                                        del items[i]
                                        break
                            for it in add_items or []:
                                items.append(dict(it))
                            entry["recent_feedback"] = items[-self._SIDECAR_FEEDBACK_ITEMS_MAX:]
                    entry["fp"] = self._session_fingerprint(agent_dir, session_id)
                if self._atomic_write_json(idx_path, index):
                    # 写后直刷进程内缓存：杜绝 mtime_ns+size 同刻不变导致的
                    # 读陈旧窗口（读路径本会因键变化失效，此为双保险）
                    new_key = self._stat_cache_key(idx_path)
                    if new_key is not None:
                        self._cache_put(self._sidecar_cache, new_key, index, self._SIDECAR_CACHE_MAX)
        except Exception as e:
            logger.warning("sidecar 索引更新失败（已失效，读路径将自愈重建）: %s", e)
            try:
                os.remove(idx_path)
            except OSError:
                pass

    def set_session_pinned(self, agent_id: str, session_id: str, pinned: bool) -> bool:
        """置顶/取消置顶 session（写入所有日期文件的 pinned 字段）。"""
        agent_dir = self._get_session_dir(agent_id)
        file_paths = list(agent_dir.glob(f"session_{session_id}_*.json"))
        if not file_paths:
            logger.warning("set_session_pinned: 未找到 session_id=%s 的文件", session_id)
            return False

        ok = True
        rep_data: Optional[Dict[str, Any]] = None
        for file_path in file_paths:
            file_lock = self._get_file_lock(file_path)
            with file_lock:
                session_data = self._read_session_file(file_path)
                if not session_data:
                    ok = False
                    continue
                session_data["pinned"] = bool(pinned)
                if not self._write_session_file_unlocked(file_path, session_data):
                    ok = False
                    continue
                # B-9: 记录代表文件（created_at 最新）数据供索引更新
                if rep_data is None or str(session_data.get("created_at", "")) >= str(rep_data.get("created_at", "")):
                    rep_data = session_data
        if rep_data is not None:
            self._sidecar_mutate(self._get_session_dir(agent_id), session_id, summary_data=rep_data)
        return ok

    def set_sessions_sort_order(self, agent_id: str, ordered_ids: List[str]) -> bool:
        """按用户拖拽顺序持久化会话排序（写入所有日期文件的 sort_order 字段）。

        ordered_ids 为完整有序 session_id 列表；未出现在列表中的会话保持
        sort_order=0（视为未排序，按 created_at 倒序垫底）。
        """
        agent_dir = self._get_session_dir(agent_id)
        if not agent_dir.is_dir():
            logger.warning("set_sessions_sort_order: agent 目录不存在 %s", agent_id)
            return False

        order_map = {sid: idx + 1 for idx, sid in enumerate(ordered_ids)}
        rep_by_sid: Dict[str, Dict[str, Any]] = {}
        ok = True
        for file_path in agent_dir.glob("session_*.json"):
            file_lock = self._get_file_lock(file_path)
            with file_lock:
                session_data = self._read_session_file(file_path)
                if not session_data:
                    continue
                sid = session_data.get("session_id", "")
                if sid not in order_map:
                    continue
                new_order = order_map[sid]
                if session_data.get("sort_order", 0) == new_order:
                    continue
                session_data["sort_order"] = new_order
                if not self._write_session_file_unlocked(file_path, session_data):
                    ok = False
                    continue
                prev = rep_by_sid.get(sid)
                if prev is None or str(session_data.get("created_at", "")) >= str(prev.get("created_at", "")):
                    rep_by_sid[sid] = session_data
        # B-9 sidecar: 被重排会话的索引逐条同步（重排低频，逐条 RMW 足够）
        for sid, data in rep_by_sid.items():
            self._sidecar_mutate(agent_dir, session_id=sid, summary_data=data)
        return ok

    def rename_session(self, agent_id: str, session_id: str, title: str) -> bool:
        """重命名 session（写入所有日期文件的 title 字段）。"""
        agent_dir = self._get_session_dir(agent_id)
        file_paths = list(agent_dir.glob(f"session_{session_id}_*.json"))
        if not file_paths:
            logger.warning("rename_session: 未找到 session_id=%s 的文件", session_id)
            return False

        ok = True
        rep_data: Optional[Dict[str, Any]] = None
        for file_path in file_paths:
            file_lock = self._get_file_lock(file_path)
            with file_lock:
                session_data = self._read_session_file(file_path)
                if not session_data:
                    ok = False
                    continue
                session_data["title"] = title
                if not self._write_session_file_unlocked(file_path, session_data):
                    ok = False
                    continue
                # B-9: 记录代表文件（created_at 最新）数据供索引更新
                if rep_data is None or str(session_data.get("created_at", "")) >= str(rep_data.get("created_at", "")):
                    rep_data = session_data
        if rep_data is not None:
            self._sidecar_mutate(self._get_session_dir(agent_id), session_id, summary_data=rep_data)
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
                    # B-9 sidecar: 摘要字段 + 被删轮次反馈增量同步索引
                    # （_feedback_from_data 只认 assistant 消息，被删 user
                    # 消息时间戳的明细移除是天然 no-op）
                    fb = self._feedback_from_data({"messages": deleted})
                    self._sidecar_mutate(
                        self._get_session_dir(agent_id),
                        session_id,
                        summary_data=session_data,
                        like_delta=-fb["like"],
                        dislike_delta=-fb["dislike"],
                        remove_item_timestamps=[m.get("timestamp", "") for m in deleted],
                    )
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
                # B-9: 捕获合并前的旧 feedback，供索引增量计算
                old_meta = msg.get("metadata") or {}
                meta = dict(old_meta)
                meta.update(metadata_patch)
                msg["metadata"] = meta
                session_data["updated_at"] = datetime.now().isoformat()
                if self._write_session_file_unlocked(file_path, session_data):
                    # B-9 sidecar: updated_at 随代表文件更新；feedback 增量
                    # 仅对 assistant 消息生效（与 _feedback_from_data 同口径，
                    # feedback=None 合法——取消反馈时计数/明细同步回落）
                    if msg.get("role") == "assistant":
                        old_fb = old_meta.get("feedback")
                        new_fb = metadata_patch.get("feedback", old_fb)
                        like_delta = int(new_fb == "like") - int(old_fb == "like")
                        dislike_delta = int(new_fb == "dislike") - int(old_fb == "dislike")
                        add_items = (
                            [{"timestamp": msg.get("timestamp", ""),
                              "content": (msg.get("content") or "")[:100],
                              "feedback": new_fb}]
                            if new_fb in ("like", "dislike") else []
                        )
                        remove_ts = (
                            [msg.get("timestamp", "")]
                            if old_fb in ("like", "dislike") else []
                        )
                    else:
                        like_delta = dislike_delta = 0
                        add_items = []
                        remove_ts = []
                    self._sidecar_mutate(
                        self._get_session_dir(agent_id),
                        session_id,
                        summary_data=session_data,
                        like_delta=like_delta,
                        dislike_delta=dislike_delta,
                        add_items=add_items,
                        remove_item_timestamps=remove_ts,
                    )
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
