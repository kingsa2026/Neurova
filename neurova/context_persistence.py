"""
上下文持久化引擎

负责将对话上下文保存到磁盘，支持跨渠道、跨会话恢复
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ContextPersistence:
    """
    上下文持久化引擎
    
    将对话上下文保存到磁盘，支持：
    - 跨渠道上下文恢复
    - 跨会话上下文延续
    - 上下文统计和清理
    """
    
    def __init__(self, data_dir: Path):
        """
        Args:
            data_dir: 数据存储目录
        """
        self._data_dir = Path(data_dir)
        self._contexts_dir = self._data_dir / "contexts"
        self._lock = threading.RLock()
        self._contexts_dir.mkdir(parents=True, exist_ok=True)
    
    def save_context(
        self,
        session_id: str,
        agent_id: str,
        context_data: Dict[str, Any],
        channel: str = "default",
        user_id: Optional[str] = None,
    ) -> bool:
        """
        保存上下文
        
        Args:
            session_id: 会话ID
            agent_id: Agent ID
            context_data: 上下文数据
            channel: 渠道标识
            user_id: 用户ID
            
        Returns:
            是否保存成功
        """
        try:
            context_record = {
                "session_id": session_id,
                "agent_id": agent_id,
                "channel": channel,
                "user_id": user_id,
                "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "data": context_data,
            }
            
            # 按 agent_id 分目录存储
            agent_dir = self._contexts_dir / agent_id
            agent_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f"{session_id}_{channel}.json"
            filepath = agent_dir / filename
            
            with self._lock:
                filepath.write_text(
                    json.dumps(context_record, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            
            logger.debug(f"Saved context for session '{session_id}' (agent='{agent_id}')")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save context: {e}")
            return False
    
    def save_context_from_data(
        self,
        session_id: str,
        agent_id: str,
        messages: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        channel: str = "default",
    ) -> bool:
        """
        从消息列表保存上下文
        
        Args:
            session_id: 会话ID
            agent_id: Agent ID
            messages: 消息列表
            metadata: 额外元数据
            channel: 渠道标识
            
        Returns:
            是否保存成功
        """
        context_data = {
            "messages": messages,
            "metadata": metadata or {},
            "message_count": len(messages),
        }
        return self.save_context(session_id, agent_id, context_data, channel)
    
    def load_context(
        self,
        session_id: str,
        agent_id: str,
        channel: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        加载上下文
        
        Args:
            session_id: 会话ID
            agent_id: Agent ID
            channel: 渠道标识
            
        Returns:
            上下文数据，不存在返回 None
        """
        agent_dir = self._contexts_dir / agent_id
        filename = f"{session_id}_{channel}.json"
        filepath = agent_dir / filename
        
        if not filepath.exists():
            return None
        
        try:
            with self._lock:
                data = json.loads(filepath.read_text(encoding="utf-8"))
            
            logger.debug(f"Loaded context for session '{session_id}' (agent='{agent_id}')")
            return data
            
        except Exception as e:
            logger.error(f"Failed to load context: {e}")
            return None
    
    def load_context_by_channel(
        self,
        agent_id: str,
        channel: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        按渠道加载上下文列表
        
        Args:
            agent_id: Agent ID
            channel: 渠道标识
            limit: 返回数量限制
            
        Returns:
            上下文列表
        """
        agent_dir = self._contexts_dir / agent_id
        if not agent_dir.exists():
            return []
        
        results = []
        try:
            with self._lock:
                for filepath in agent_dir.glob(f"*_{channel}.json"):
                    try:
                        data = json.loads(filepath.read_text(encoding="utf-8"))
                        results.append(data)
                    except Exception:
                        continue
            
            # 按保存时间排序
            results.sort(key=lambda x: x.get("saved_at", ""), reverse=True)
            return results[:limit]
            
        except Exception as e:
            logger.error(f"Failed to load contexts by channel: {e}")
            return []
    
    def delete_context(
        self,
        session_id: str,
        agent_id: str,
        channel: str = "default",
    ) -> bool:
        """删除上下文"""
        agent_dir = self._contexts_dir / agent_id
        filename = f"{session_id}_{channel}.json"
        filepath = agent_dir / filename
        
        try:
            with self._lock:
                if filepath.exists():
                    filepath.unlink()
                    logger.debug(f"Deleted context for session '{session_id}'")
                    return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to delete context: {e}")
            return False
    
    def list_contexts(
        self,
        agent_id: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列出上下文"""
        results = []
        
        try:
            with self._lock:
                if agent_id:
                    agent_dirs = [self._contexts_dir / agent_id]
                else:
                    agent_dirs = [d for d in self._contexts_dir.iterdir() if d.is_dir()]
                
                for agent_dir in agent_dirs:
                    if not agent_dir.exists():
                        continue
                    
                    pattern = f"*_{channel}.json" if channel else "*.json"
                    for filepath in agent_dir.glob(pattern):
                        try:
                            data = json.loads(filepath.read_text(encoding="utf-8"))
                            results.append({
                                "session_id": data.get("session_id"),
                                "agent_id": data.get("agent_id"),
                                "channel": data.get("channel"),
                                "saved_at": data.get("saved_at"),
                            })
                        except Exception:
                            continue
            
            results.sort(key=lambda x: x.get("saved_at", ""), reverse=True)
            return results
            
        except Exception as e:
            logger.error(f"Failed to list contexts: {e}")
            return []
    
    def get_context_stats(self, agent_id: str) -> Dict[str, Any]:
        """获取上下文统计"""
        agent_dir = self._contexts_dir / agent_id
        if not agent_dir.exists():
            return {"agent_id": agent_id, "total_contexts": 0}
        
        try:
            with self._lock:
                files = list(agent_dir.glob("*.json"))
                
                channel_counts = {}
                for f in files:
                    parts = f.stem.split("_")
                    channel = parts[-1] if len(parts) > 1 else "default"
                    channel_counts[channel] = channel_counts.get(channel, 0) + 1
                
                return {
                    "agent_id": agent_id,
                    "total_contexts": len(files),
                    "by_channel": channel_counts,
                }
                
        except Exception as e:
            logger.error(f"Failed to get context stats: {e}")
            return {"agent_id": agent_id, "error": str(e)}
    
    def get_context_stats_by_channel(self) -> Dict[str, Any]:
        """获取所有渠道的上下文统计"""
        try:
            with self._lock:
                channel_counts = {}
                total = 0
                
                for agent_dir in self._contexts_dir.iterdir():
                    if not agent_dir.is_dir():
                        continue
                    
                    for filepath in agent_dir.glob("*.json"):
                        total += 1
                        parts = filepath.stem.split("_")
                        channel = parts[-1] if len(parts) > 1 else "default"
                        channel_counts[channel] = channel_counts.get(channel, 0) + 1
                
                return {
                    "total_contexts": total,
                    "by_channel": channel_counts,
                }
                
        except Exception as e:
            logger.error(f"Failed to get channel stats: {e}")
            return {"error": str(e)}
    
    def cleanup_old_contexts(
        self,
        max_age_days: int = 30,
        agent_id: Optional[str] = None,
    ) -> int:
        """
        清理旧上下文
        
        Args:
            max_age_days: 最大保留天数
            agent_id: 可选的 agent 过滤
            
        Returns:
            删除的上下文数量
        """
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=max_age_days)
        deleted = 0
        
        try:
            with self._lock:
                if agent_id:
                    agent_dirs = [self._contexts_dir / agent_id]
                else:
                    agent_dirs = [d for d in self._contexts_dir.iterdir() if d.is_dir()]
                
                for agent_dir in agent_dirs:
                    if not agent_dir.exists():
                        continue
                    
                    for filepath in agent_dir.glob("*.json"):
                        try:
                            data = json.loads(filepath.read_text(encoding="utf-8"))
                            saved_at = datetime.datetime.fromisoformat(data.get("saved_at", ""))
                            
                            if saved_at < cutoff:
                                filepath.unlink()
                                deleted += 1
                                
                        except Exception:
                            continue
            
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old contexts (max_age={max_age_days} days)")
            return deleted
            
        except Exception as e:
            logger.error(f"Failed to cleanup contexts: {e}")
            return 0


# 全局单例
_context_persistence: Optional[ContextPersistence] = None
_persistence_lock = threading.Lock()


def get_context_persistence(data_dir: Optional[Path] = None) -> ContextPersistence:
    """获取全局上下文持久化引擎单例"""
    global _context_persistence
    if _context_persistence is None:
        with _persistence_lock:
            if _context_persistence is None:
                if data_dir is None:
                    data_dir = Path("data")
                _context_persistence = ContextPersistence(data_dir=data_dir)
    return _context_persistence


def reset_context_persistence() -> None:
    """重置全局上下文持久化引擎（用于测试）"""
    global _context_persistence
    with _persistence_lock:
        _context_persistence = None
