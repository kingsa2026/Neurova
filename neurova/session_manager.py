"""
会话备份管理器
将对话内容按agent和session_id隔离，直接即时写入文件，无内存缓存
"""

import os
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from threading import Lock
from dataclasses import dataclass, field, asdict

try:
    import fcntl  # type: ignore[import-not-found]  # Unix only
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

logger = logging.getLogger(__name__)

@dataclass
class SessionMessage:
    """会话消息"""
    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            'role': self.role,
            'content': self.content,
            'timestamp': self.timestamp,
        }
        if self.metadata:
            d['metadata'] = self.metadata
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

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['messages'] = [msg.to_dict() if isinstance(msg, SessionMessage) else msg for msg in self.messages]
        return data

class SessionManager:
    """会话管理器 - 直接即时写入文件，无内存缓存"""

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._sessions_dir = Path("sessions")
            self._sessions_dir.mkdir(exist_ok=True)
            self._file_locks: Dict[str, Lock] = {}

    def _get_file_lock(self, file_path) -> Lock:
        """获取文件的线程锁"""
        key = str(file_path)
        if key not in self._file_locks:
            self._file_locks[key] = Lock()
        return self._file_locks[key]

    def _get_session_dir(self, agent_id: str) -> Path:
        """获取agent的session目录"""
        agent_dir = self._sessions_dir / agent_id
        agent_dir.mkdir(exist_ok=True)
        return agent_dir

    def _get_session_file(self, agent_id: str, session_id: str, date: str = None) -> Path:
        """获取session文件路径"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        agent_dir = self._get_session_dir(agent_id)
        return agent_dir / f"session_{session_id}_{date}.json"

    def _read_session_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """读取session文件"""
        if not file_path.exists():
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取session文件失败: {e}")
            return None

    def _write_session_file(self, file_path: Path, data: Dict[str, Any]) -> bool:
        """写入session文件"""
        try:
            file_lock = self._get_file_lock(file_path)
            with file_lock:
                with open(file_path, 'w', encoding='utf-8') as f:
                    if HAS_FCNTL:
                        try:
                            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                            json.dump(data, f, ensure_ascii=False, indent=2)
                            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                        except OSError:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                    else:
                        json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"写入session文件失败: {e}")
            return False

    def add_message(self, agent_id: str, session_id: str, user_content: str, assistant_content: str, metadata: Dict[str, Any] = None, date: str = None) -> str:
        """添加一条对话（user + assistant 两条消息）到session"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        file_path = self._get_session_file(agent_id, session_id, date)

        # 读取现有数据
        session_data = self._read_session_file(file_path)

        now = datetime.now().isoformat()
        user_msg = {
            'role': 'user',
            'content': user_content,
            'timestamp': now,
        }
        assistant_msg = {
            'role': 'assistant',
            'content': assistant_content,
            'timestamp': now,
        }
        if metadata:
            user_msg['metadata'] = metadata
            assistant_msg['metadata'] = metadata

        new_messages = [user_msg, assistant_msg]

        if session_data is None:
            # 创建新的session记录
            session_data = {
                'agent_id': agent_id,
                'session_id': session_id,
                'session_date': date,
                'messages': new_messages,
                'created_at': now,
                'updated_at': now,
                'total_messages': len(new_messages),
            }
        else:
            # 更新现有session记录
            if 'messages' not in session_data:
                session_data['messages'] = []

            session_data['messages'].extend(new_messages)
            session_data['updated_at'] = now
            session_data['total_messages'] = len(session_data['messages'])

        # 写入文件
        self._write_session_file(file_path, session_data)

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
        for msg_data in session_data.get('messages', []):
            if isinstance(msg_data, dict):
                messages.append(SessionMessage(
                    role=msg_data.get('role', ''),
                    content=msg_data.get('content', ''),
                    timestamp=msg_data.get('timestamp', ''),
                    metadata=msg_data.get('metadata'),
                ))
            else:
                messages.append(msg_data)

        return SessionRecord(
            agent_id=session_data.get('agent_id', agent_id),
            session_id=session_data.get('session_id', session_id),
            session_date=session_data.get('session_date', date),
            messages=messages,
            created_at=session_data.get('created_at', ''),
            updated_at=session_data.get('updated_at', ''),
            total_messages=session_data.get('total_messages', 0),
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
            for message in session.get('messages', []):
                if keyword.lower() in message.get('content', '').lower():
                    results.append(message)

        return results

    def create_session(self, agent_id: str) -> str:
        """创建新的session_id"""
        return str(uuid.uuid4())[:8]

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
                        logger.info(f"Session已删除: {file_path}")
                        return True
                except Exception as e:
                    logger.error(f"删除session文件失败: {e}")
                    return False
            else:
                logger.warning(f"未找到 session_id={session_id} 的文件（date={date}）")
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
                        logger.info(f"Session已删除: {file_path}")
                except Exception as e:
                    logger.error(f"删除session文件失败: {e}")
                    continue

            if deleted_count > 0:
                logger.info(f"共删除 {deleted_count} 个文件（session_id={session_id}）")
                return True
            else:
                logger.warning(f"未找到 session_id={session_id} 的任何文件（agent_id={agent_id}）")
                return False

    def get_session_stats(self, agent_id: str, session_id: str) -> Dict[str, Any]:
        """获取session统计信息"""
        sessions = self._get_session_data_list(agent_id, session_id)

        if not sessions:
            return {
                'agent_id': agent_id,
                'session_id': session_id,
                'total_files': 0,
                'total_messages': 0,
                'total_size_bytes': 0,
                'dates': [],
            }

        total_messages = 0
        total_size_bytes = 0
        dates = []

        for session in sessions:
            total_messages += session.get('total_messages', 0)
            # 计算文件大小
            file_path = self._get_session_file(agent_id, session_id, session.get('session_date'))
            if file_path.exists():
                total_size_bytes += file_path.stat().st_size
            dates.append(session.get('session_date'))

        return {
            'agent_id': agent_id,
            'session_id': session_id,
            'total_files': len(sessions),
            'total_messages': total_messages,
            'total_size_bytes': total_size_bytes,
            'dates': sorted(dates),
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
        sessions.sort(key=lambda x: x.get('session_date', ''), reverse=True)
        
        # 收集所有消息
        all_messages = []
        for session in sessions:
            messages = session.get('messages', [])
            for msg in messages:
                if isinstance(msg, dict):
                    role = msg.get('role', '')
                    content = msg.get('content', '')
                    if role and content:
                        all_messages.append({
                            "role": role,
                            "content": content,
                        })
        
        # 返回最近的 max_messages 条消息
        return all_messages[-max_messages:] if len(all_messages) > max_messages else all_messages

def get_session_manager() -> SessionManager:
    """获取SessionManager单例"""
    return SessionManager()