"""
上下文缓存管理器 - 智能内存缓存层

核心特性:
1. 优先读缓存 - 减少磁盘IO
2. 批量写入 - 定期刷新到磁盘
3. 会话完整性保护 - 不截断对话轮次
4. LRU淘汰策略 - 自动清理最少使用的缓存
5. 内存限制 - 防止内存溢出
"""

import collections
import datetime
import json
import logging
import time
import threading
import typing
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from collections import OrderedDict

from neurova.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    context_data: Dict[str, Any]
    channel: str
    agent_id: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    created_at: float = None
    last_accessed: float = None
    last_modified: float = None
    access_count: int = 0
    size_bytes: int = 0
    is_dirty: bool = False
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.last_accessed is None:
            self.last_accessed = self.created_at
        if self.last_modified is None:
            self.last_modified = self.created_at
        if self.size_bytes == 0:
            self.size_bytes = self._estimate_size()
    
    def _estimate_size(self) -> int:
        """估算上下文数据大小"""
        try:
            return len(json.dumps(self.context_data, ensure_ascii=False).encode('utf-8'))
        except:
            return 0
    
    def touch(self):
        """更新访问信息"""
        self.last_accessed = time.time()
        self.access_count += 1
    
    def mark_dirty(self):
        """标记为脏数据"""
        self.is_dirty = True
        self.last_modified = time.time()
    
    def mark_clean(self):
        """标记为干净数据"""
        self.is_dirty = False
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


class ContextCacheManager:
    """
    上下文缓存管理器
    
    管理对话上下文的内存缓存，提供智能缓存策略和批量写入功能。
    """
    
    def __init__(
        self,
        max_entries: int = 1000,
        max_memory_mb: float = 100.0,
        write_batch_size: int = 50,
        write_interval_seconds: float = 30.0,
        cleanup_threshold: float = 0.8,
        enable_persistence: bool = True
    ):
        """
        初始化缓存管理器
        
        Args:
            max_entries: 最大缓存条目数
            max_memory_mb: 最大内存使用量(MB)
            write_batch_size: 批量写入大小
            write_interval_seconds: 写入间隔(秒)
            cleanup_threshold: 清理阈值(0-1)
            enable_persistence: 是否启用持久化
        """
        self._lock = threading.RLock()
        
        # 缓存配置
        self.max_entries = max_entries
        self.max_memory_bytes = int(max_memory_mb * 1024 * 1024)
        self.write_batch_size = write_batch_size
        self.write_interval_seconds = write_interval_seconds
        self.cleanup_threshold = cleanup_threshold
        self.enable_persistence = enable_persistence
        
        # 缓存存储 (LRU)
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        
        # 写入队列
        self._write_queue: List[str] = []
        
        # 统计信息
        self._stats = {
            'hits': 0,
            'misses': 0,
            'writes': 0,
            'evictions': 0,
            'memory_usage': 0,
            'last_cleanup': None,
            'last_write_batch': None
        }
        
        # 持久化引擎
        self._persistence = None
        if enable_persistence:
            try:
                from neurova.context_persistence import ContextPersistence
                self._persistence = ContextPersistence()
            except ImportError as e:
                logger.warning(f"无法加载持久化引擎: {e}")
        
        # 后台写入线程
        self._write_thread = None
        self._running = False
        
        logger.info(f"ContextCacheManager 初始化，最大条目: {max_entries}，最大内存: {max_memory_mb}MB")
    
    def start(self):
        """启动缓存管理器"""
        with self._lock:
            if self._running:
                return
            
            self._running = True
            
            # 启动后台写入线程
            if self.enable_persistence:
                self._write_thread = threading.Thread(
                    target=self._background_write_loop,
                    daemon=True,
                    name="context-cache-writer"
                )
                self._write_thread.start()
                logger.info("缓存后台写入线程已启动")
    
    def stop(self):
        """停止缓存管理器"""
        with self._lock:
            self._running = False
            
            # 刷新所有脏数据
            self.flush_all()
            
            logger.info("缓存管理器已停止")
    
    def get_context(
        self,
        agent_id: str,
        channel: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取上下文
        
        Args:
            agent_id: Agent ID
            channel: 渠道
            user_id: 用户ID
            session_id: 会话ID
            
        Returns:
            上下文数据，不存在返回 None
        """
        with self._lock:
            cache_key = self._make_cache_key(agent_id, channel, user_id, session_id)
            
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                entry.touch()
                
                # LRU: 移动到末尾
                self._cache.move_to_end(cache_key)
                
                self._stats['hits'] += 1
                logger.debug(f"缓存命中: {cache_key}")
                return entry.context_data
            
            self._stats['misses'] += 1
            logger.debug(f"缓存未命中: {cache_key}")
            
            # 尝试从持久化加载
            if self._persistence and self.enable_persistence:
                try:
                    context_data = self._persistence.load_context(
                        agent_id=agent_id,
                        channel=channel,
                        user_id=user_id,
                        session_id=session_id
                    )
                    
                    if context_data:
                        # 放入缓存
                        self._put_to_cache(cache_key, context_data, channel, agent_id, user_id, session_id)
                        return context_data
                except Exception as e:
                    logger.warning(f"从持久化加载上下文失败: {e}")
            
            return None
    
    def get_context_by_channel(
        self,
        agent_id: str,
        channel: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        按渠道获取上下文列表
        
        Args:
            agent_id: Agent ID
            channel: 渠道
            limit: 返回数量限制
            
        Returns:
            上下文数据列表
        """
        with self._lock:
            results = []
            
            for key, entry in self._cache.items():
                if entry.agent_id == agent_id and entry.channel == channel:
                    entry.touch()
                    results.append(entry.context_data)
                    
                    if len(results) >= limit:
                        break
            
            return results
    
    def get_context_with_agent(
        self,
        agent_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取指定Agent的所有上下文
        
        Args:
            agent_id: Agent ID
            limit: 返回数量限制
            
        Returns:
            上下文数据列表
        """
        with self._lock:
            results = []
            
            for key, entry in self._cache.items():
                if entry.agent_id == agent_id:
                    entry.touch()
                    results.append(entry.context_data)
                    
                    if len(results) >= limit:
                        break
            
            return results
    
    def put_context(
        self,
        agent_id: str,
        channel: str,
        context_data: Dict[str, Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        immediate_write: bool = False
    ) -> bool:
        """
        存储上下文
        
        Args:
            agent_id: Agent ID
            channel: 渠道
            context_data: 上下文数据
            user_id: 用户ID
            session_id: 会话ID
            immediate_write: 是否立即写入磁盘
            
        Returns:
            是否成功
        """
        with self._lock:
            cache_key = self._make_cache_key(agent_id, channel, user_id, session_id)
            
            # 存入缓存
            self._put_to_cache(cache_key, context_data, channel, agent_id, user_id, session_id)
            
            # 检查是否需要清理
            self._ensure_space()
            
            # 标记为脏数据
            if cache_key in self._cache:
                self._cache[cache_key].mark_dirty()
            
            # 加入写入队列
            if cache_key not in self._write_queue:
                self._write_queue.append(cache_key)
            
            # 立即写入
            if immediate_write:
                self._write_to_disk(cache_key)
            
            return True
    
    def update_context_field(
        self,
        agent_id: str,
        channel: str,
        field_name: str,
        field_value: Any,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """
        更新上下文字段
        
        Args:
            agent_id: Agent ID
            channel: 渠道
            field_name: 字段名
            field_value: 字段值
            user_id: 用户ID
            session_id: 会话ID
            
        Returns:
            是否成功
        """
        with self._lock:
            cache_key = self._make_cache_key(agent_id, channel, user_id, session_id)
            
            if cache_key not in self._cache:
                # 尝试加载
                context_data = self.get_context(agent_id, channel, user_id, session_id)
                if not context_data:
                    context_data = {}
            
            # 更新字段
            entry = self._cache[cache_key]
            entry.context_data[field_name] = field_value
            entry.mark_dirty()
            entry.size_bytes = entry._estimate_size()
            
            # 加入写入队列
            if cache_key not in self._write_queue:
                self._write_queue.append(cache_key)
            
            return True
    
    def batch_write_if_needed(self) -> int:
        """
        按需批量写入
        
        Returns:
            写入的条目数
        """
        with self._lock:
            if len(self._write_queue) >= self.write_batch_size:
                return self.batch_write()
            return 0
    
    def batch_write(self) -> int:
        """
        批量写入到磁盘
        
        Returns:
            写入的条目数
        """
        with self._lock:
            if not self._write_queue:
                return 0
            
            # 获取待写入的键
            keys_to_write = self._write_queue[:self.write_batch_size]
            self._write_queue = self._write_queue[self.write_batch_size:]
            
            written_count = 0
            
            for key in keys_to_write:
                if key in self._cache:
                    if self._write_to_disk(key):
                        written_count += 1
            
            self._stats['writes'] += written_count
            self._stats['last_write_batch'] = time.time()
            
            logger.info(f"批量写入完成，写入 {written_count} 个条目")
            return written_count
    
    def flush_all(self) -> int:
        """
        刷新所有脏数据到磁盘
        
        Returns:
            写入的条目数
        """
        with self._lock:
            written_count = 0
            
            # 写入队列中的所有条目
            while self._write_queue:
                key = self._write_queue.pop(0)
                if key in self._cache and self._cache[key].is_dirty:
                    if self._write_to_disk(key):
                        written_count += 1
            
            # 写入所有脏数据
            for key, entry in self._cache.items():
                if entry.is_dirty:
                    if self._write_to_disk(key):
                        written_count += 1
            
            logger.info(f"刷新所有数据，写入 {written_count} 个条目")
            return written_count
    
    def evict_if_needed(self) -> int:
        """
        按需淘汰缓存
        
        Returns:
            淘汰的条目数
        """
        with self._lock:
            evicted_count = 0
            
            # 检查条目数
            while len(self._cache) > self.max_entries * self.cleanup_threshold:
                if self._cache:
                    key, entry = self._cache.popitem(last=False)  # LRU
                    
                    # 写入磁盘
                    if entry.is_dirty and self.enable_persistence:
                        self._write_to_disk(key)
                    
                    evicted_count += 1
                else:
                    break
            
            # 检查内存使用
            current_memory = self._estimate_memory_usage()
            while current_memory > self.max_memory_bytes * self.cleanup_threshold:
                if self._cache:
                    key, entry = self._cache.popitem(last=False)
                    
                    if entry.is_dirty and self.enable_persistence:
                        self._write_to_disk(key)
                    
                    current_memory -= entry.size_bytes
                    evicted_count += 1
                else:
                    break
            
            if evicted_count > 0:
                self._stats['evictions'] += evicted_count
                self._stats['last_cleanup'] = time.time()
                logger.info(f"淘汰 {evicted_count} 个缓存条目")
            
            return evicted_count
    
    def evict_inactive(self, max_inactive_seconds: float = 3600.0) -> int:
        """
        淘汰不活跃的缓存
        
        Args:
            max_inactive_seconds: 最大不活跃时间(秒)
            
        Returns:
            淘汰的条目数
        """
        with self._lock:
            evicted_count = 0
            current_time = time.time()
            
            keys_to_remove = []
            
            for key, entry in self._cache.items():
                if current_time - entry.last_accessed > max_inactive_seconds:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                entry = self._cache.pop(key)
                
                if entry.is_dirty and self.enable_persistence:
                    self._write_to_disk(key)
                
                evicted_count += 1
            
            if evicted_count > 0:
                self._stats['evictions'] += evicted_count
                logger.info(f"淘汰 {evicted_count} 个不活跃条目")
            
            return evicted_count
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            stats = self._stats.copy()
            stats['current_entries'] = len(self._cache)
            stats['current_memory_mb'] = self._estimate_memory_usage() / (1024 * 1024)
            stats['write_queue_size'] = len(self._write_queue)
            stats['hit_rate'] = (
                stats['hits'] / (stats['hits'] + stats['misses']) 
                if (stats['hits'] + stats['misses']) > 0 
                else 0.0
            )
            return stats
    
    def get_cache_summary(self) -> Dict[str, Any]:
        """获取缓存摘要"""
        with self._lock:
            summary = {
                'total_entries': len(self._cache),
                'dirty_entries': sum(1 for e in self._cache.values() if e.is_dirty),
                'memory_usage_mb': self._estimate_memory_usage() / (1024 * 1024),
                'oldest_entry': None,
                'newest_entry': None,
                'most_accessed': None,
                'channels': set(),
                'agents': set()
            }
            
            if self._cache:
                oldest_time = float('inf')
                newest_time = 0
                max_access = 0
                most_accessed_key = None
                
                for key, entry in self._cache.items():
                    if entry.created_at < oldest_time:
                        oldest_time = entry.created_at
                        summary['oldest_entry'] = key
                    
                    if entry.created_at > newest_time:
                        newest_time = entry.created_at
                        summary['newest_entry'] = key
                    
                    if entry.access_count > max_access:
                        max_access = entry.access_count
                        most_accessed_key = key
                    
                    summary['channels'].add(entry.channel)
                    summary['agents'].add(entry.agent_id)
                
                summary['most_accessed'] = most_accessed_key
                summary['channels'] = list(summary['channels'])
                summary['agents'] = list(summary['agents'])
            
            return summary
    
    def _make_cache_key(
        self,
        agent_id: str,
        channel: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> str:
        """生成缓存键"""
        parts = [agent_id, channel]
        
        if user_id:
            parts.append(user_id)
        
        if session_id:
            parts.append(session_id)
        
        return ":".join(parts)
    
    def _put_to_cache(
        self,
        key: str,
        context_data: Dict[str, Any],
        channel: str,
        agent_id: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ):
        """放入缓存"""
        # 如果已存在，更新
        if key in self._cache:
            entry = self._cache[key]
            entry.context_data = context_data
            entry.mark_dirty()
            entry.size_bytes = entry._estimate_size()
            entry.touch()
            self._cache.move_to_end(key)
        else:
            # 创建新条目
            entry = CacheEntry(
                key=key,
                context_data=context_data,
                channel=channel,
                agent_id=agent_id,
                user_id=user_id,
                session_id=session_id
            )
            self._cache[key] = entry
        
        # 更新内存统计
        self._stats['memory_usage'] = self._estimate_memory_usage()
    
    def _ensure_space(self):
        """确保有足够空间"""
        # 检查条目数
        while len(self._cache) >= self.max_entries:
            if self._cache:
                key, entry = self._cache.popitem(last=False)
                
                if entry.is_dirty and self.enable_persistence:
                    self._write_to_disk(key)
                
                self._stats['evictions'] += 1
            else:
                break
        
        # 检查内存使用
        current_memory = self._estimate_memory_usage()
        while current_memory > self.max_memory_bytes:
            if self._cache:
                key, entry = self._cache.popitem(last=False)
                
                if entry.is_dirty and self.enable_persistence:
                    self._write_to_disk(key)
                
                current_memory -= entry.size_bytes
                self._stats['evictions'] += 1
            else:
                break
    
    def _write_to_disk(self, key: str) -> bool:
        """写入磁盘"""
        if not self._persistence or not self.enable_persistence:
            return False
        
        if key not in self._cache:
            return False
        
        entry = self._cache[key]
        
        try:
            # 调用持久化引擎
            self._persistence.save_context_from_data(
                session_id=entry.session_id or key,
                agent_id=entry.agent_id,
                messages=entry.context_data.get('messages', []) if isinstance(entry.context_data, dict) else [],
                channel=entry.channel,
            )
            
            entry.mark_clean()
            logger.debug(f"写入磁盘: {key}")
            return True
        except Exception as e:
            logger.error(f"写入磁盘失败 {key}: {e}")
            return False
    
    def _estimate_memory_usage(self) -> int:
        """估算内存使用量"""
        total_size = 0
        
        for entry in self._cache.values():
            total_size += entry.size_bytes
        
        return total_size
    
    def _background_write_loop(self):
        """后台写入循环"""
        logger.info("后台写入循环开始")
        
        while self._running:
            try:
                time.sleep(self.write_interval_seconds)
                
                with self._lock:
                    # 批量写入
                    written = self.batch_write()
                    
                    # 清理不活跃条目
                    self.evict_inactive()
                    
                    # 淘汰过多条目
                    self.evict_if_needed()
                
                if written > 0:
                    logger.debug(f"后台写入 {written} 个条目")
            except Exception as e:
                logger.error(f"后台写入循环异常: {e}")
        
        logger.info("后台写入循环结束")
    
    def __del__(self):
        """析构函数"""
        self.stop()


# 单例管理
_cache_manager_instance: Optional[ContextCacheManager] = None
_cache_manager_lock = threading.Lock()


def get_context_cache_manager(**kwargs) -> ContextCacheManager:
    """获取上下文缓存管理器单例"""
    global _cache_manager_instance
    
    if _cache_manager_instance is None:
        with _cache_manager_lock:
            if _cache_manager_instance is None:
                _cache_manager_instance = ContextCacheManager(**kwargs)
                _cache_manager_instance.start()
    
    return _cache_manager_instance


def reset_context_cache_manager():
    """重置上下文缓存管理器单例"""
    global _cache_manager_instance
    
    with _cache_manager_lock:
        if _cache_manager_instance is not None:
            _cache_manager_instance.stop()
            _cache_manager_instance = None