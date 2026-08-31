# 数据读写缓存机制架构设计

## 1. 概述

### 1.1 设计目标

缓存机制旨在优化 Neurova 框架的数据读写性能,核心目标:

- **减少数据库写操作**: 通过内存缓存批量写入,降低 I/O 频率
- **加速上下文读取**: 优先从内存缓存加载,避免重复数据库查询
- **保证数据完整性**: 确保会话内容完整写入,不截断关键对话
- **智能触发写入**: 基于容量阈值(256KB)或时间超时(180秒)自动批量写入
- **高效缓存淘汰**: 自动清理过期/低优先级缓存,控制内存占用

### 1.2 缓存架构定位

```
┌─────────────────────────────────────────────────────────────┐
│                      Application Layer                       │
│              (Agent, ContextBuilder, MemoryManager)          │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                    Cache Layer (新增)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Read Cache   │  │ Write Cache  │  │ Session Cache│      │
│  │ (上下文读取)  │  │ (批量写入)   │  │ (会话完整性) │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                   Storage Layer                              │
│              (SQLite Database, File System)                  │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 缓存分类

```
缓存系统
├── 读取缓存 (Read Cache)
│   ├── 上下文缓存 (Context Cache)
│   ├── 记忆缓存 (Memory Cache)
│   └── 配置缓存 (Config Cache)
│
├── 写入缓存 (Write Cache)
│   ├── 记忆写入缓冲 (Memory Write Buffer)
│   ├── 情感记录缓冲 (Emotion Write Buffer)
│   └── 索引更新缓冲 (Index Write Buffer)
│
└── 会话缓存 (Session Cache)
    ├── 活跃会话缓存 (Active Session Cache)
    ├── 会话历史缓存 (Session History Cache)
    └── 会话状态缓存 (Session State Cache)
```

## 2. 缓存数据模型

### 2.1 缓存项基础结构

```python
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
import json
import hashlib
import sys

class CachePriority(Enum):
    """缓存优先级"""
    CRITICAL = 0    # 关键数据,不可淘汰
    HIGH = 1        # 高优先级
    NORMAL = 2      # 普通优先级
    LOW = 3         # 低优先级,优先淘汰

class CacheStatus(Enum):
    """缓存状态"""
    ACTIVE = "active"           # 活跃,正在使用
    PENDING_FLUSH = "pending"   # 待刷入数据库
    FLUSHING = "flushing"       # 正在刷入
    STALE = "stale"             # 过期,待清理
    FLUSHED = "flushed"         # 已刷入

@dataclass
class CacheItem:
    """缓存项基础结构"""
    key: str
    data: Any
    priority: CachePriority = CachePriority.NORMAL
    status: CacheStatus = CacheStatus.ACTIVE
    
    # 时间信息
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_accessed_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    
    # 元数据
    size_bytes: int = 0
    access_count: int = 0
    session_id: Optional[str] = None
    agent_id: Optional[str] = None
    
    # 写入缓存专用
    flush_batch_id: Optional[str] = None  # 所属批次ID
    is_dirty: bool = False  # 是否有未保存的修改
    
    def __post_init__(self):
        """初始化时计算大小"""
        if self.size_bytes == 0:
            self.size_bytes = self._calculate_size()
    
    def _calculate_size(self) -> int:
        """计算数据占用的内存大小(字节)"""
        try:
            if isinstance(self.data, str):
                return len(self.data.encode('utf-8'))
            elif isinstance(self.data, bytes):
                return len(self.data)
            else:
                return len(json.dumps(self.data).encode('utf-8'))
        except:
            return sys.getsizeof(self.data)
    
    def touch(self):
        """访问缓存项,更新访问信息"""
        self.last_accessed_at = datetime.now()
        self.access_count += 1
    
    def mark_dirty(self):
        """标记为脏数据(需要写入数据库)"""
        self.is_dirty = True
        self.updated_at = datetime.now()
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.expires_at:
            return datetime.now() > self.expires_at
        return False
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'key': self.key,
            'data': self.data,
            'priority': self.priority.value,
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'last_accessed_at': self.last_accessed_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'size_bytes': self.size_bytes,
            'access_count': self.access_count,
            'session_id': self.session_id,
            'agent_id': self.agent_id,
            'is_dirty': self.is_dirty
        }
```

### 2.2 写入缓存项

```python
@dataclass
class WriteCacheItem(CacheItem):
    """写入缓存项 - 专门用于缓冲写操作"""
    
    # 数据库操作信息
    operation: str = "INSERT"  # INSERT, UPDATE, DELETE
    table_name: str = ""
    record_id: Optional[str] = None
    
    # 批次信息
    batch_sequence: int = 0  # 在批次中的顺序
    
    # 完整性标记
    is_session_boundary: bool = False  # 是否是会话边界
    session_complete: bool = False  # 会话是否完整结束
    
    def get_database_params(self) -> Dict:
        """获取数据库写入参数"""
        return {
            'table': self.table_name,
            'operation': self.operation,
            'data': self.data,
            'record_id': self.record_id
        }
```

### 2.3 会话缓存项

```python
@dataclass
class SessionCacheItem(CacheItem):
    """会话缓存项 - 保证会话完整性"""
    
    # 会话信息
    session_id: str = ""
    agent_id: str = ""
    conversation_turns: List[Dict] = field(default_factory=list)
    
    # 完整性标记
    is_session_complete: bool = False  # 会话是否完整结束
    last_user_message_time: Optional[datetime] = None
    
    # 统计信息
    total_messages: int = 0
    total_tokens: int = 0
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None):
        """添加消息到会话"""
        message = {
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata or {}
        }
        self.conversation_turns.append(message)
        self.total_messages += 1
        self.last_user_message_time = datetime.now()
        
        # 估算 token
        chinese_chars = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
        english_words = len([w for w in content.split() if w.isascii()])
        self.total_tokens += int(chinese_chars * 1.5 + english_words * 1.3)
        
        self.mark_dirty()
    
    def mark_session_complete(self):
        """标记会话结束"""
        self.is_session_complete = True
        self.status = CacheStatus.PENDING_FLUSH
```

### 2.4 缓存批次

```python
@dataclass
class FlushBatch:
    """刷入批次 - 用于批量写入数据库"""
    batch_id: str
    items: List[WriteCacheItem] = field(default_factory=list)
    
    # 批次统计
    total_size_bytes: int = 0
    item_count: int = 0
    
    # 时间信息
    created_at: datetime = field(default_factory=datetime.now)
    first_item_time: Optional[datetime] = None
    last_item_time: Optional[datetime] = None
    
    # 状态
    is_flushing: bool = False
    is_complete: bool = False  # 是否包含完整会话结束标记
    
    # 触发原因
    trigger_reason: str = ""  # size_threshold, timeout, session_end, shutdown
    
    def add_item(self, item: WriteCacheItem):
        """添加缓存项到批次"""
        self.items.append(item)
        self.total_size_bytes += item.size_bytes
        self.item_count += 1
        
        if self.first_item_time is None:
            self.first_item_time = item.created_at
        self.last_item_time = item.updated_at
        
        # 检查是否包含完整会话
        if item.is_session_boundary and item.session_complete:
            self.is_complete = True
    
    def time_since_first_item(self) -> float:
        """距离第一个物品的时间(秒)"""
        if self.first_item_time:
            return (datetime.now() - self.first_item_time).total_seconds()
        return 0
    
    def should_flush_by_size(self, threshold_bytes: int = 262144) -> bool:
        """检查是否达到大小阈值 (256KB = 262144 bytes)"""
        return self.total_size_bytes >= threshold_bytes
    
    def should_flush_by_timeout(self, timeout_seconds: int = 180) -> bool:
        """检查是否达到超时阈值"""
        if self.last_item_time:
            idle_time = (datetime.now() - self.last_item_time).total_seconds()
            return idle_time >= timeout_seconds
        return False
    
    def should_flush(self, size_threshold: int = 262144, timeout_seconds: int = 180) -> tuple[bool, str]:
        """
        检查是否应该刷入
        返回: (是否刷入, 触发原因)
        """
        # 优先检查会话完整性
        if self.is_complete:
            return True, "session_complete"
        
        # 检查大小阈值
        if self.should_flush_by_size(size_threshold):
            return True, "size_threshold"
        
        # 检查超时阈值
        if self.should_flush_by_timeout(timeout_seconds):
            return True, "timeout"
        
        return False, ""
```

## 3. 写入缓存架构

### 3.1 写入缓存管理器

```python
class WriteCacheManager:
    """
    写入缓存管理器
    负责缓冲写操作,批量写入数据库
    """
    
    def __init__(
        self,
        database_connection,
        config: Optional[Dict] = None
    ):
        self.db = database_connection
        self.config = config or {}
        
        # 配置参数
        self.size_threshold = self.config.get('size_threshold', 262144)  # 256KB
        self.timeout_seconds = self.config.get('timeout_seconds', 180)  # 180秒
        
        # 当前批次
        self.current_batch: Optional[FlushBatch] = None
        
        # 待刷入批次队列
        self.pending_batches: List[FlushBatch] = []
        
        # 写入统计
        self.stats = WriteCacheStats()
        
        # 锁(多线程安全)
        self.lock = threading.Lock()
    
    # ========== 写入操作 ==========
    
    def buffer_memory(
        self,
        memory: Memory,
        session_id: Optional[str] = None,
        operation: str = "INSERT"
    ) -> str:
        """
        缓冲记忆写入
        """
        with self.lock:
            # 确保有当前批次
            if self.current_batch is None:
                self._create_new_batch()
            
            # 创建写入缓存项
            cache_item = WriteCacheItem(
                key=f"memory:{memory.id}",
                data=memory.to_dict(),
                priority=CachePriority.NORMAL,
                operation=operation,
                table_name="memories",
                record_id=memory.id,
                session_id=session_id,
                agent_id=memory.agent_id
            )
            
            # 检查是否是会话边界
            if session_id:
                cache_item.is_session_boundary = self._is_session_boundary(
                    session_id, memory
                )
            
            # 添加到当前批次
            self.current_batch.add_item(cache_item)
            self.stats.record_buffered(memory.size_bytes)
            
            # 检查是否需要刷入
            should_flush, reason = self.current_batch.should_flush(
                self.size_threshold, self.timeout_seconds
            )
            
            if should_flush:
                self._flush_current_batch(reason)
            
            return cache_item.key
    
    def buffer_emotion_record(
        self,
        record: EmotionRecord,
        session_id: Optional[str] = None
    ) -> str:
        """缓冲情感记录写入"""
        with self.lock:
            if self.current_batch is None:
                self._create_new_batch()
            
            cache_item = WriteCacheItem(
                key=f"emotion:{record.id}",
                data=record.to_dict(),
                priority=CachePriority.LOW,
                operation="INSERT",
                table_name="emotion_records",
                record_id=record.id,
                session_id=session_id,
                agent_id=record.agent_id
            )
            
            self.current_batch.add_item(cache_item)
            
            should_flush, reason = self.current_batch.should_flush(
                self.size_threshold, self.timeout_seconds
            )
            
            if should_flush:
                self._flush_current_batch(reason)
            
            return cache_item.key
    
    def buffer_memory_relation(
        self,
        relation: MemoryRelation,
        session_id: Optional[str] = None
    ) -> str:
        """缓冲记忆关联写入"""
        with self.lock:
            if self.current_batch is None:
                self._create_new_batch()
            
            cache_item = WriteCacheItem(
                key=f"relation:{relation.id}",
                data=relation.to_dict(),
                priority=CachePriority.LOW,
                operation="INSERT",
                table_name="memory_relations",
                record_id=relation.id
            )
            
            self.current_batch.add_item(cache_item)
            
            should_flush, reason = self.current_batch.should_flush(
                self.size_threshold, self.timeout_seconds
            )
            
            if should_flush:
                self._flush_current_batch(reason)
            
            return cache_item.key
    
    # ========== 批次管理 ==========
    
    def _create_new_batch(self):
        """创建新的刷入批次"""
        self.current_batch = FlushBatch(
            batch_id=f"batch_{datetime.now().timestamp()}"
        )
    
    def _flush_current_batch(self, reason: str):
        """
        刷入当前批次到数据库
        注意: 如果批次未完成且不是因为大小阈值触发,需要等待会话完整
        """
        if self.current_batch is None or self.current_batch.item_count == 0:
            return
        
        # 检查会话完整性
        if not self.current_batch.is_complete and reason == "timeout":
            # 超时触发但会话未完成,需要进一步判断
            if not self._can_flush_incomplete_batch(self.current_batch):
                self.stats.record_flush_skipped("incomplete_session")
                return
        
        # 标记刷入原因
        self.current_batch.trigger_reason = reason
        self.current_batch.is_flushing = True
        
        # 加入待刷入队列
        self.pending_batches.append(self.current_batch)
        
        # 创建新批次
        self.current_batch = FlushBatch(
            batch_id=f"batch_{datetime.now().timestamp()}"
        )
        
        # 异步刷入
        self._execute_flush_batch(self.pending_batches[-1])
    
    def _can_flush_incomplete_batch(self, batch: FlushBatch) -> bool:
        """
        判断是否可以刷入不完整的批次
        策略:
        1. 如果已经超过最大等待时间(300秒),强制刷入
        2. 如果批次大小已超过阈值2倍,强制刷入
        3. 否则等待会话完整
        """
        max_wait_seconds = self.config.get('max_wait_seconds', 300)
        max_size_multiplier = self.config.get('max_size_multiplier', 2)
        
        # 超时强制刷入
        if batch.time_since_first_item() >= max_wait_seconds:
            return True
        
        # 超大强制刷入
        if batch.total_size_bytes >= self.size_threshold * max_size_multiplier:
            return True
        
        return False
    
    # ========== 数据库刷入 ==========
    
    def _execute_flush_batch(self, batch: FlushBatch):
        """
        执行批次刷入
        按顺序执行数据库写入操作
        """
        try:
            with self.db.transaction() as conn:
                cursor = conn.cursor()
                
                # 按顺序写入
                for item in sorted(batch.items, key=lambda x: x.batch_sequence):
                    self._execute_single_write(cursor, item)
                
                conn.commit()
            
            # 更新状态
            batch.is_complete = True
            batch.is_flushing = False
            
            # 更新统计
            self.stats.record_flush(
                items=batch.item_count,
                bytes=batch.total_size_bytes,
                reason=batch.trigger_reason
            )
            
            # 从队列移除
            if batch in self.pending_batches:
                self.pending_batches.remove(batch)
            
        except Exception as e:
            self.stats.record_flush_error(e)
            # 标记刷入失败,等待重试
            batch.is_flushing = False
            raise
    
    def _execute_single_write(self, cursor, item: WriteCacheItem):
        """执行单条写入操作"""
        if item.operation == "INSERT":
            self._execute_insert(cursor, item)
        elif item.operation == "UPDATE":
            self._execute_update(cursor, item)
        elif item.operation == "DELETE":
            self._execute_delete(cursor, item)
    
    def _execute_insert(self, cursor, item: WriteCacheItem):
        """执行插入操作"""
        data = item.data
        
        if item.table_name == "memories":
            cursor.execute("""
                INSERT INTO memories (
                    id, agent_id, type, category, content, content_hash,
                    weight, emotion_score, emotion_tags, access_count,
                    created_at, expires_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data['id'], data['agent_id'], data['type'], data['category'],
                data['content'], data.get('content_hash'),
                data.get('weight', 1.0), data.get('emotion_score', 0.0),
                json.dumps(data.get('emotion_tags', [])),
                data.get('access_count', 0),
                data.get('created_at'), data.get('expires_at'),
                json.dumps(data.get('metadata', {}))
            ))
        
        elif item.table_name == "emotion_records":
            cursor.execute("""
                INSERT INTO emotion_records (
                    id, agent_id, memory_id, emotion_type, intensity,
                    trigger, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                data['id'], data['agent_id'], data.get('memory_id'),
                data['emotion_type'], data['intensity'],
                data.get('trigger'), data.get('created_at')
            ))
        
        elif item.table_name == "memory_relations":
            cursor.execute("""
                INSERT INTO memory_relations (
                    id, source_memory_id, target_memory_id, relation_type,
                    strength, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                data['id'], data['source_memory_id'], data['target_memory_id'],
                data['relation_type'], data.get('strength', 1.0),
                data.get('created_at')
            ))
    
    def _execute_update(self, cursor, item: WriteCacheItem):
        """执行更新操作"""
        data = item.data
        
        if item.table_name == "memories":
            cursor.execute("""
                UPDATE memories SET
                    weight = ?, emotion_score = ?, emotion_tags = ?,
                    access_count = ?, last_accessed_at = ?, updated_at = ?,
                    metadata = ?
                WHERE id = ?
            """, (
                data.get('weight'), data.get('emotion_score'),
                json.dumps(data.get('emotion_tags', [])),
                data.get('access_count'), data.get('last_accessed_at'),
                data.get('updated_at'),
                json.dumps(data.get('metadata', {})),
                item.record_id
            ))
    
    def _execute_delete(self, cursor, item: WriteCacheItem):
        """执行删除操作"""
        cursor.execute(
            f"DELETE FROM {item.table_name} WHERE id = ?",
            (item.record_id,)
        )
    
    # ========== 会话完整性判断 ==========
    
    def _is_session_boundary(self, session_id: str, memory: Memory) -> bool:
        """
        判断是否是会话边界
        会话边界定义:
        1. 记忆类型为 conversation 且包含结束语关键词
        2. 对话间隔超过 30 分钟
        3. 明确包含会话结束标记
        """
        # 检查是否是会话结束消息
        if memory.category != MemoryCategory.CONVERSATION:
            return False
        
        # 检查内容是否包含结束语
        end_phrases = [
            '再见', '拜拜', '下次聊', '结束', '到这里',
            'bye', 'goodbye', 'see you', 'that's all'
        ]
        
        content_lower = memory.content.lower()
        for phrase in end_phrases:
            if phrase in content_lower:
                return True
        
        # 检查时间间隔 (需要通过缓存获取上一条消息时间)
        last_message_time = self._get_last_message_time(session_id)
        if last_message_time:
            interval = (memory.created_at - last_message_time).total_seconds()
            if interval > 1800:  # 30 分钟
                return True
        
        return False
    
    def _get_last_message_time(self, session_id: str) -> Optional[datetime]:
        """获取会话最后一条消息的时间"""
        # 优先从缓存获取
        cache_key = f"session_last_time:{session_id}"
        cached = self.read_cache.get(cache_key)
        if cached:
            return cached
        
        # 从数据库查询
        try:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT created_at FROM memories
                WHERE metadata LIKE ?
                ORDER BY created_at DESC LIMIT 1
            """, (f'%session_id":"{session_id}"%',))
            
            row = cursor.fetchone()
            if row:
                last_time = datetime.fromisoformat(row[0])
                # 缓存结果
                self.read_cache.set(cache_key, last_time, ttl=300)
                return last_time
        except:
            pass
        
        return None
    
    # ========== 生命周期管理 ==========
    
    def flush_all(self):
        """强制刷入所有缓存"""
        with self.lock:
            # 刷入当前批次
            if self.current_batch and self.current_batch.item_count > 0:
                self.current_batch.trigger_reason = "shutdown"
                self._flush_current_batch("shutdown")
            
            # 等待所有待刷入批次完成
            for batch in self.pending_batches:
                if not batch.is_complete:
                    self._execute_flush_batch(batch)
    
    def close(self):
        """关闭写入缓存"""
        self.flush_all()
        self.stats.log_stats()
    
    # ========== 读取支持 ==========
    
    def get_from_write_buffer(self, key: str) -> Optional[Any]:
        """从写入缓存中获取数据(用于读取自己的未刷入数据)"""
        with self.lock:
            # 检查当前批次
            if self.current_batch:
                for item in self.current_batch.items:
                    if item.key == key:
                        return item.data
            
            # 检查待刷入批次
            for batch in self.pending_batches:
                for item in batch.items:
                    if item.key == key:
                        return item.data
        
        return None
```

### 3.2 会话完整性保障机制

```python
class SessionIntegrityGuard:
    """
    会话完整性守护者
    确保缓存刷入时不会截断会话内容
    """
    
    def __init__(self, write_cache: WriteCacheManager):
        self.write_cache = write_cache
        
        # 会话状态跟踪
        self.active_sessions: Dict[str, SessionState] = {}
        
        # 会话结束检测规则
        self.end_detection = SessionEndDetection()
    
    def track_session_start(self, session_id: str, agent_id: str):
        """跟踪会话开始"""
        self.active_sessions[session_id] = SessionState(
            session_id=session_id,
            agent_id=agent_id,
            status=SessionStatus.ACTIVE,
            started_at=datetime.now()
        )
    
    def track_session_activity(self, session_id: str):
        """跟踪会话活动"""
        if session_id in self.active_sessions:
            self.active_sessions[session_id].last_activity = datetime.now()
    
    def track_session_end(self, session_id: str):
        """跟踪会话结束"""
        if session_id in self.active_sessions:
            session = self.active_sessions[session_id]
            session.status = SessionStatus.COMPLETED
            session.completed_at = datetime.now()
            
            # 标记相关缓存项
            self._mark_session_items_complete(session_id)
    
    def _mark_session_items_complete(self, session_id: str):
        """标记会话相关缓存项为完整"""
        with self.write_cache.lock:
            # 标记当前批次中的会话项
            if self.write_cache.current_batch:
                for item in self.write_cache.current_batch.items:
                    if item.session_id == session_id:
                        item.session_complete = True
                        self.write_cache.current_batch.is_complete = True
            
            # 标记待刷入批次中的会话项
            for batch in self.write_cache.pending_batches:
                for item in batch.items:
                    if item.session_id == session_id:
                        item.session_complete = True
    
    def should_flush_session(self, session_id: str) -> bool:
        """判断会话是否可以刷入"""
        if session_id not in self.active_sessions:
            return True
        
        session = self.active_sessions[session_id]
        
        # 会话已完成
        if session.status == SessionStatus.COMPLETED:
            return True
        
        # 会话超时(无活动超过 10 分钟)
        idle_time = (datetime.now() - session.last_activity).total_seconds()
        if idle_time > 600:
            return True
        
        return False
    
    def check_idle_sessions(self) -> List[str]:
        """检查空闲会话,返回可以刷入的会话ID"""
        flushable = []
        
        for session_id, session in self.active_sessions.items():
            if session.status == SessionStatus.ACTIVE:
                idle_time = (datetime.now() - session.last_activity).total_seconds()
                if idle_time > 600:  # 10分钟无活动
                    flushable.append(session_id)
                    session.status = SessionStatus.IDLE
        
        return flushable
    
    def cleanup_completed_sessions(self):
        """清理已完成的会话状态"""
        completed = [
            sid for sid, session in self.active_sessions.items()
            if session.status == SessionStatus.COMPLETED
        ]
        
        for sid in completed:
            del self.active_sessions[sid]
```

### 3.3 会话状态枚举

```python
class SessionStatus(Enum):
    """会话状态"""
    ACTIVE = "active"         # 活跃
    IDLE = "idle"             # 空闲
    COMPLETED = "completed"   # 已完成
    FLUSHING = "flushing"     # 正在刷入

@dataclass
class SessionState:
    """会话状态"""
    session_id: str
    agent_id: str
    status: SessionStatus = SessionStatus.ACTIVE
    started_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    message_count: int = 0
```

## 4. 读取缓存架构

### 4.1 读取缓存管理器

```python
class ReadCacheManager:
    """
    读取缓存管理器
    优先从缓存读取,未命中则查询数据库
    """
    
    def __init__(
        self,
        database_connection,
        config: Optional[Dict] = None
    ):
        self.db = database_connection
        self.config = config or {}
        
        # 缓存存储 (使用 OrderedDict 实现 LRU)
        self.cache: Dict[str, CacheItem] = {}
        self.cache_order: List[str] = []  # 访问顺序
        
        # 配置参数
        self.max_memory_bytes = self.config.get('max_memory_bytes', 10485760)  # 10MB
        self.default_ttl = self.config.get('default_ttl', 600)  # 10分钟
        self.max_items = self.config.get('max_items', 1000)
        
        # 统计
        self.stats = ReadCacheStats()
        
        # 锁
        self.lock = threading.Lock()
        
        # 与写入缓存关联
        self.write_cache: Optional[WriteCacheManager] = None
    
    def set_write_cache(self, write_cache: WriteCacheManager):
        """设置写入缓存引用"""
        self.write_cache = write_cache
    
    # ========== 读取操作 ==========
    
    def get_memory(self, memory_id: str) -> Optional[Memory]:
        """
        获取记忆 - 缓存优先
        """
        cache_key = f"memory:{memory_id}"
        
        with self.lock:
            # 1. 尝试从缓存读取
            cached = self._get_from_cache(cache_key)
            if cached is not None:
                self.stats.record_hit()
                return Memory.from_dict(cached)
            
            self.stats.record_miss()
        
        # 2. 检查写入缓存 (可能还未刷入数据库)
        if self.write_cache:
            from_write_buffer = self.write_cache.get_from_write_buffer(cache_key)
            if from_write_buffer is not None:
                return Memory.from_dict(from_write_buffer)
        
        # 3. 从数据库查询
        try:
            cursor = self.db.cursor()
            cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
            row = cursor.fetchone()
            
            if row:
                memory = self._row_to_memory(row)
                
                # 存入缓存
                with self.lock:
                    self._set_to_cache(cache_key, memory.to_dict())
                
                return memory
        except Exception as e:
            self.stats.record_error(e)
        
        return None
    
    def search_memories(
        self,
        query: str,
        agent_id: str,
        memory_type: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10
    ) -> List[Memory]:
        """
        搜索记忆 - 缓存优先
        """
        # 构建缓存键
        cache_key = self._build_search_cache_key(
            query, agent_id, memory_type, category, limit
        )
        
        with self.lock:
            # 1. 尝试从缓存读取
            cached = self._get_from_cache(cache_key)
            if cached is not None:
                self.stats.record_hit()
                return [Memory.from_dict(m) for m in cached]
            
            self.stats.record_miss()
        
        # 2. 从数据库查询
        try:
            memories = self._search_from_database(
                query, agent_id, memory_type, category, limit
            )
            
            # 存入缓存
            if memories:
                with self.lock:
                    self._set_to_cache(
                        cache_key,
                        [m.to_dict() for m in memories],
                        ttl=60  # 搜索结果缓存 1 分钟
                    )
            
            return memories
        except Exception as e:
            self.stats.record_error(e)
            return []
    
    def get_context_memories(
        self,
        agent_id: str,
        query: str,
        max_count: int = 5
    ) -> List[Memory]:
        """
        获取上下文记忆 - 缓存优先
        """
        cache_key = f"context:{agent_id}:{hashlib.md5(query.encode()).hexdigest()}"
        
        with self.lock:
            cached = self._get_from_cache(cache_key)
            if cached is not None:
                self.stats.record_hit()
                return [Memory.from_dict(m) for m in cached]
            
            self.stats.record_miss()
        
        # 从数据库查询
        try:
            memories = self._get_context_from_database(
                agent_id, query, max_count
            )
            
            if memories:
                with self.lock:
                    self._set_to_cache(cache_key, [m.to_dict() for m in memories])
            
            return memories
        except Exception as e:
            self.stats.record_error(e)
            return []
    
    # ========== 缓存操作 ==========
    
    def _get_from_cache(self, key: str) -> Optional[Any]:
        """从缓存获取数据"""
        if key not in self.cache:
            return None
        
        item = self.cache[key]
        
        # 检查过期
        if item.is_expired():
            self._remove_from_cache(key)
            return None
        
        # 更新访问信息
        item.touch()
        self._move_to_end(key)
        
        return item.data
    
    def _set_to_cache(
        self,
        key: str,
        data: Any,
        ttl: Optional[int] = None,
        priority: CachePriority = CachePriority.NORMAL
    ):
        """设置缓存"""
        # 检查是否需要淘汰
        while self._needs_eviction():
            self._evict_one()
        
        # 创建缓存项
        item = CacheItem(
            key=key,
            data=data,
            priority=priority,
            expires_at=datetime.now() + timedelta(seconds=ttl or self.default_ttl)
        )
        
        # 存入缓存
        self.cache[key] = item
        self.cache_order.append(key)
    
    def _remove_from_cache(self, key: str):
        """从缓存移除"""
        if key in self.cache:
            del self.cache[key]
        if key in self.cache_order:
            self.cache_order.remove(key)
    
    def _move_to_end(self, key: str):
        """将键移动到末尾(LRU)"""
        if key in self.cache_order:
            self.cache_order.remove(key)
        self.cache_order.append(key)
    
    # ========== 缓存淘汰 ==========
    
    def _needs_eviction(self) -> bool:
        """检查是否需要淘汰"""
        # 检查内存限制
        current_memory = sum(item.size_bytes for item in self.cache.values())
        if current_memory >= self.max_memory_bytes:
            return True
        
        # 检查项目数量限制
        if len(self.cache) >= self.max_items:
            return True
        
        return False
    
    def _evict_one(self):
        """淘汰一个缓存项"""
        if not self.cache:
            return
        
        # 优先淘汰低优先级、最久未访问的项
        evict_key = None
        best_score = -1
        
        for key, item in self.cache.items():
            # 跳过高优先级
            if item.priority in [CachePriority.CRITICAL, CachePriority.HIGH]:
                continue
            
            # 计算淘汰分数 (越低越应该淘汰)
            score = item.priority.value * 1000 + (
                datetime.now() - item.last_accessed_at
            ).total_seconds()
            
            if score > best_score:
                best_score = score
                evict_key = key
        
        if evict_key:
            self._remove_from_cache(evict_key)
            self.stats.record_eviction()
    
    # ========== 数据库查询辅助 ==========
    
    def _search_from_database(
        self,
        query: str,
        agent_id: str,
        memory_type: Optional[str],
        category: Optional[str],
        limit: int
    ) -> List[Memory]:
        """从数据库搜索记忆"""
        cursor = self.db.cursor()
        
        sql = "SELECT * FROM memories WHERE agent_id = ?"
        params = [agent_id]
        
        if memory_type:
            sql += " AND type = ?"
            params.append(memory_type)
        
        if category:
            sql += " AND category = ?"
            params.append(category)
        
        sql += " ORDER BY weight DESC, created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        return [self._row_to_memory(row) for row in rows]
    
    def _get_context_from_database(
        self,
        agent_id: str,
        query: str,
        max_count: int
    ) -> List[Memory]:
        """从数据库获取上下文记忆"""
        # 提取查询关键词
        keywords = self._extract_keywords(query)
        
        if not keywords:
            return []
        
        cursor = self.db.cursor()
        
        # 使用索引表快速查找
        keyword_placeholders = ','.join(['?' for _ in keywords])
        sql = f"""
            SELECT DISTINCT m.*
            FROM memories m
            INNER JOIN memory_index mi ON m.id = mi.memory_id
            WHERE m.agent_id = ?
              AND mi.keyword IN ({keyword_placeholders})
            ORDER BY m.weight DESC, mi.relevance DESC
            LIMIT ?
        """
        
        params = [agent_id] + keywords + [max_count * 2]
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        memories = [self._row_to_memory(row) for row in rows]
        
        # 计算相关性并排序
        scored = [
            (self._calculate_relevance(query, m), m)
            for m in memories
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        
        return [m for _, m in scored[:max_count]]
    
    def _row_to_memory(self, row) -> Memory:
        """将数据库行转换为 Memory 对象"""
        return Memory(
            id=row[0],
            agent_id=row[1],
            type=MemoryType(row[2]),
            category=MemoryCategory(row[3]),
            content=row[4],
            weight=row.get('weight', 1.0),
            emotion_score=row.get('emotion_score', 0.0),
            emotion_tags=json.loads(row.get('emotion_tags', '[]')),
            access_count=row.get('access_count', 0),
            last_accessed_at=row.get('last_accessed_at'),
            created_at=row.get('created_at'),
            expires_at=row.get('expires_at'),
            metadata=json.loads(row.get('metadata', '{}'))
        )
    
    def _build_search_cache_key(
        self,
        query: str,
        agent_id: str,
        memory_type: Optional[str],
        category: Optional[str],
        limit: int
    ) -> str:
        """构建搜索缓存键"""
        key_parts = [
            "search",
            agent_id,
            hashlib.md5(query.encode()).hexdigest()[:16]
        ]
        
        if memory_type:
            key_parts.append(memory_type)
        if category:
            key_parts.append(category)
        key_parts.append(str(limit))
        
        return ":".join(key_parts)
    
    def _extract_keywords(self, query: str) -> List[str]:
        """提取关键词"""
        # 简单分词 (可以使用 jieba 等库)
        # 这里使用空格和标点分词
        import re
        words = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', query)
        return [w for w in words if len(w) > 1]
    
    def _calculate_relevance(self, query: str, memory: Memory) -> float:
        """计算相关性"""
        # 简单实现: 关键词匹配度
        query_keywords = set(self._extract_keywords(query))
        memory_keywords = set(self._extract_keywords(memory.content))
        
        if not query_keywords:
            return 0
        
        intersection = query_keywords & memory_keywords
        return len(intersection) / len(query_keywords)
    
    # ========== 缓存管理 ==========
    
    def invalidate(self, key: str):
        """使缓存失效"""
        with self.lock:
            self._remove_from_cache(key)
    
    def invalidate_pattern(self, pattern: str):
        """按模式使缓存失效"""
        with self.lock:
            keys_to_remove = [
                key for key in self.cache.keys()
                if pattern in key
            ]
            for key in keys_to_remove:
                self._remove_from_cache(key)
    
    def clear(self):
        """清空缓存"""
        with self.lock:
            self.cache.clear()
            self.cache_order.clear()
    
    def get_stats(self) -> Dict:
        """获取缓存统计"""
        with self.lock:
            current_memory = sum(item.size_bytes for item in self.cache.values())
            return {
                'total_items': len(self.cache),
                'current_memory_bytes': current_memory,
                'max_memory_bytes': self.max_memory_bytes,
                'hit_rate': self.stats.get_hit_rate(),
                'hits': self.stats.hits,
                'misses': self.stats.misses
            }
```

## 5. 缓存协调器

### 5.1 缓存协调器

```python
class CacheCoordinator:
    """
    缓存协调器
    协调读取缓存和写入缓存的工作
    """
    
    def __init__(
        self,
        read_cache: ReadCacheManager,
        write_cache: WriteCacheManager,
        session_guard: SessionIntegrityGuard,
        config: Optional[Dict] = None
    ):
        self.read_cache = read_cache
        self.write_cache = write_cache
        self.session_guard = session_guard
        self.config = config or {}
        
        # 建立双向引用
        self.read_cache.set_write_cache(write_cache)
        
        # 后台任务
        self.flush_scheduler = FlushScheduler(write_cache, session_guard)
        self.cache_cleaner = CacheCleaner(read_cache)
        
        # 运行状态
        self.running = False
    
    def start(self):
        """启动缓存协调器"""
        self.running = True
        
        # 启动后台调度器
        self.flush_scheduler.start()
        self.cache_cleaner.start()
    
    def stop(self):
        """停止缓存协调器"""
        self.running = False
        
        # 停止后台任务
        self.flush_scheduler.stop()
        self.cache_cleaner.stop()
        
        # 强制刷入所有缓存
        self.write_cache.flush_all()
    
    def add_memory(self, memory: Memory, session_id: Optional[str] = None):
        """添加记忆 - 统一入口"""
        # 写入缓存
        self.write_cache.buffer_memory(memory, session_id)
        
        # 使相关读取缓存失效
        self.read_cache.invalidate_pattern(f"search:{memory.agent_id}")
        self.read_cache.invalidate_pattern(f"context:{memory.agent_id}")
    
    def get_memory(self, memory_id: str) -> Optional[Memory]:
        """获取记忆 - 统一入口"""
        return self.read_cache.get_memory(memory_id)
    
    def search_memories(self, **kwargs) -> List[Memory]:
        """搜索记忆 - 统一入口"""
        return self.read_cache.search_memories(**kwargs)
```

### 5.2 刷入调度器

```python
class FlushScheduler:
    """
    刷入调度器
    定期检查并触发缓存刷入
    """
    
    def __init__(
        self,
        write_cache: WriteCacheManager,
        session_guard: SessionIntegrityGuard
    ):
        self.write_cache = write_cache
        self.session_guard = session_guard
        self.running = False
        self.thread: Optional[threading.Thread] = None
    
    def start(self):
        """启动调度器"""
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
    
    def stop(self):
        """停止调度器"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
    
    def _run(self):
        """调度循环"""
        check_interval = self.write_cache.config.get('check_interval', 10)
        
        while self.running:
            try:
                # 检查空闲会话
                idle_sessions = self.session_guard.check_idle_sessions()
                
                # 刷入空闲会话的缓存
                for session_id in idle_sessions:
                    if self.session_guard.should_flush_session(session_id):
                        self._flush_session(session_id)
                
                # 检查当前批次超时
                if self.write_cache.current_batch:
                    should_flush, reason = self.write_cache.current_batch.should_flush(
                        self.write_cache.size_threshold,
                        self.write_cache.timeout_seconds
                    )
                    
                    if should_flush:
                        self.write_cache._flush_current_batch(reason)
                
                # 清理已完成会话
                self.session_guard.cleanup_completed_sessions()
                
            except Exception as e:
                logger.error(f"Flush scheduler error: {e}")
            
            time.sleep(check_interval)
    
    def _flush_session(self, session_id: str):
        """刷入指定会话的缓存"""
        # 标记会话完成
        self.session_guard.track_session_end(session_id)
        
        # 触发刷入
        with self.write_cache.lock:
            if self.write_cache.current_batch:
                for item in self.write_cache.current_batch.items:
                    if item.session_id == session_id:
                        item.session_complete = True
                        self.write_cache.current_batch.is_complete = True
                
                # 立即刷入
                self.write_cache._flush_current_batch("session_idle")
```

### 5.3 缓存清理器

```python
class CacheCleaner:
    """
    缓存清理器
    定期清理过期缓存项
    """
    
    def __init__(self, read_cache: ReadCacheManager):
        self.read_cache = read_cache
        self.running = False
        self.thread: Optional[threading.Thread] = None
    
    def start(self):
        """启动清理器"""
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
    
    def stop(self):
        """停止清理器"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
    
    def _run(self):
        """清理循环"""
        clean_interval = 30  # 每 30 秒清理一次
        
        while self.running:
            try:
                # 清理过期项
                expired_keys = []
                with self.read_cache.lock:
                    for key, item in self.read_cache.cache.items():
                        if item.is_expired():
                            expired_keys.append(key)
                    
                    for key in expired_keys:
                        self.read_cache._remove_from_cache(key)
                
                if expired_keys:
                    self.read_cache.stats.record_eviction(len(expired_keys))
            
            except Exception as e:
                logger.error(f"Cache cleaner error: {e}")
            
            time.sleep(clean_interval)
```

## 6. 统计监控

### 6.1 写入缓存统计

```python
class WriteCacheStats:
    """写入缓存统计"""
    
    def __init__(self):
        self.total_buffered = 0
        self.total_flushed = 0
        self.total_bytes_buffered = 0
        self.total_bytes_flushed = 0
        self.flush_count = 0
        self.flush_errors = 0
        self.flush_skipped = 0
        
        # 按触发原因统计
        self.flush_by_size = 0
        self.flush_by_timeout = 0
        self.flush_by_session = 0
        self.flush_by_shutdown = 0
        
        # 时间统计
        self.total_flush_time = 0.0
        self.avg_flush_time = 0.0
    
    def record_buffered(self, bytes_count: int):
        """记录缓冲"""
        self.total_buffered += 1
        self.total_bytes_buffered += bytes_count
    
    def record_flush(self, items: int, bytes_count: int, reason: str):
        """记录刷入"""
        self.total_flushed += items
        self.total_bytes_flushed += bytes_count
        self.flush_count += 1
        
        # 按原因统计
        if reason == "size_threshold":
            self.flush_by_size += 1
        elif reason == "timeout":
            self.flush_by_timeout += 1
        elif reason == "session_complete":
            self.flush_by_session += 1
        elif reason == "shutdown":
            self.flush_by_shutdown += 1
    
    def record_flush_error(self, error: Exception):
        """记录刷入错误"""
        self.flush_errors += 1
        logger.error(f"Flush error: {error}")
    
    def record_flush_skipped(self, reason: str):
        """记录跳过刷入"""
        self.flush_skipped += 1
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            'total_buffered': self.total_buffered,
            'total_flushed': self.total_flushed,
            'total_bytes_buffered': self.total_bytes_buffered,
            'total_bytes_flushed': self.total_bytes_flushed,
            'flush_count': self.flush_count,
            'flush_errors': self.flush_errors,
            'flush_skipped': self.flush_skipped,
            'flush_by_size': self.flush_by_size,
            'flush_by_timeout': self.flush_by_timeout,
            'flush_by_session': self.flush_by_session,
            'avg_flush_items': (
                self.total_flushed / self.flush_count if self.flush_count > 0 else 0
            )
        }
    
    def log_stats(self):
        """输出统计日志"""
        stats = self.get_stats()
        logger.info(f"Write Cache Stats: {json.dumps(stats, indent=2)}")
```

### 6.2 读取缓存统计

```python
class ReadCacheStats:
    """读取缓存统计"""
    
    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.errors = 0
    
    def record_hit(self):
        """记录命中"""
        self.hits += 1
    
    def record_miss(self):
        """记录未命中"""
        self.misses += 1
    
    def record_eviction(self, count: int = 1):
        """记录淘汰"""
        self.evictions += count
    
    def record_error(self, error: Exception):
        """记录错误"""
        self.errors += 1
    
    def get_hit_rate(self) -> float:
        """获取命中率"""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': self.get_hit_rate(),
            'evictions': self.evictions,
            'errors': self.errors
        }
```

## 7. 配置示例

### 7.1 完整缓存配置

```yaml
# cache.yaml
cache:
  # 写入缓存配置
  write_cache:
    enabled: true
    
    # 触发阈值
    size_threshold: 262144  # 256KB
    timeout_seconds: 180    # 180秒
    
    # 强制刷入限制
    max_wait_seconds: 300        # 最大等待时间 5 分钟
    max_size_multiplier: 2       # 最大大小倍数
    
    # 后台调度
    check_interval: 10           # 检查间隔 10 秒
    
    # 批量写入优化
    batch_insert: true           # 使用批量 INSERT
    batch_size: 100              # 批量大小
    use_transaction: true        # 使用事务
  
  # 读取缓存配置
  read_cache:
    enabled: true
    
    # 内存限制
    max_memory_bytes: 10485760   # 10MB
    max_items: 1000              # 最大项目数
    
    # 过期时间
    default_ttl: 600             # 默认 10 分钟
    search_result_ttl: 60        # 搜索结果缓存 1 分钟
    context_ttl: 300             # 上下文缓存 5 分钟
    
    # 淘汰策略
    eviction_policy: "lru"       # LRU 淘汰
    protect_critical: true       # 保护关键数据
  
  # 会话完整性配置
  session_integrity:
    enabled: true
    
    # 会话结束检测
    idle_timeout: 600            # 空闲 10 分钟视为结束
    max_duration: 3600           # 最大会话时长 1 小时
    
    # 结束语检测
    end_phrases:
      - "再见"
      - "拜拜"
      - "下次聊"
      - "结束"
      - "bye"
      - "goodbye"
  
  # 统计监控
  monitoring:
    enabled: true
    log_interval: 300            # 每 5 分钟输出统计
    metrics_endpoint: "/cache/stats"
```

### 7.2 Agent 级缓存配置

```yaml
# agents/assistant_cache.yaml
agent:
  id: "assistant"
  
  cache:
    # 覆盖全局配置
    write_cache:
      size_threshold: 131072     # 128KB (更频繁刷入)
      timeout_seconds: 120       # 120秒
    
    read_cache:
      max_memory_bytes: 5242880  # 5MB
      default_ttl: 300           # 5 分钟
```

## 8. 数据流图

### 8.1 写入流程

```
应用层写入请求
        ↓
   [写入缓存管理器]
        ↓
   添加到当前批次
        ↓
   检查触发条件
   ├─ 大小 >= 256KB?
   ├─ 空闲 >= 180秒?
   └─ 会话完整?
        ↓
   [满足任一条件]
        ↓
   检查会话完整性
   ├─ 完整 → 立即刷入
   └─ 不完整 → 判断是否强制刷入
        ↓
   [数据库事务写入]
        ↓
   更新统计信息
        ↓
   使相关读取缓存失效
```

### 8.2 读取流程

```
应用层读取请求
        ↓
   [读取缓存管理器]
        ↓
   检查读取缓存
   ├─ 命中 → 返回数据
   └─ 未命中 ↓
        ↓
   检查写入缓存 (未刷入数据)
   ├─ 找到 → 返回数据
   └─ 未找到 ↓
        ↓
   [数据库查询]
        ↓
   存入读取缓存
        ↓
   返回数据
```

## 9. 性能优化

### 9.1 批量写入优化

```python
class BatchInsertOptimizer:
    """批量插入优化器"""
    
    def optimize_inserts(self, items: List[WriteCacheItem]) -> str:
        """
        将多条 INSERT 合并为一条
        例如: 
        INSERT INTO memories (...) VALUES (...), (...), (...)
        """
        if not items:
            return ""
        
        # 按表分组
        grouped = {}
        for item in items:
            if item.operation == "INSERT":
                if item.table_name not in grouped:
                    grouped[item.table_name] = []
                grouped[item.table_name].append(item)
        
        # 生成批量 SQL
        sql_parts = []
        for table, table_items in grouped.items():
            sql_parts.append(self._build_batch_insert(table, table_items))
        
        return "; ".join(sql_parts)
    
    def _build_batch_insert(self, table: str, items: List[WriteCacheItem]) -> str:
        """构建批量 INSERT 语句"""
        if not items:
            return ""
        
        columns = items[0].data.keys()
        columns_str = ", ".join(columns)
        
        values_list = []
        params = []
        
        for item in items:
            placeholders = ", ".join(["?" for _ in columns])
            values_list.append(f"({placeholders})")
            params.extend(item.data.values())
        
        values_str = ", ".join(values_list)
        
        return f"INSERT INTO {table} ({columns_str}) VALUES {values_str}"
```

### 9.2 缓存预热

```python
class CacheWarmer:
    """缓存预热器"""
    
    def warmup(self, read_cache: ReadCacheManager, agent_id: str):
        """
        预热缓存 - 加载常用数据
        """
        # 预加载高频访问的记忆
        self._warmup_frequent_memories(read_cache, agent_id)
        
        # 预加载配置
        self._warmup_config(read_cache, agent_id)
    
    def _warmup_frequent_memories(
        self,
        read_cache: ReadCacheManager,
        agent_id: str
    ):
        """预加载高频记忆"""
        cursor = read_cache.db.cursor()
        cursor.execute("""
            SELECT id FROM memories
            WHERE agent_id = ? AND access_count > 10
            ORDER BY access_count DESC
            LIMIT 50
        """, (agent_id,))
        
        rows = cursor.fetchall()
        for row in rows:
            memory_id = row[0]
            read_cache.get_memory(memory_id)
    
    def _warmup_config(
        self,
        read_cache: ReadCacheManager,
        agent_id: str
    ):
        """预加载配置"""
        # 加载 Agent 配置
        cache_key = f"config:agent:{agent_id}"
        # ... 加载配置到缓存
```

## 10. 测试用例

### 10.1 单元测试

```python
def test_write_cache_threshold():
    """测试大小阈值触发刷入"""
    write_cache = WriteCacheManager(mock_db, {
        'size_threshold': 1000,  # 1KB 用于测试
        'timeout_seconds': 180
    })
    
    # 添加数据直到达到阈值
    for i in range(20):
        memory = Memory(
            id=f"test_{i}",
            agent_id="test_agent",
            type=MemoryType.SHORT_TERM,
            category=MemoryCategory.CONVERSATION,
            content="Test message " * 10
        )
        write_cache.buffer_memory(memory)
    
    # 检查是否触发刷入
    assert len(write_cache.pending_batches) > 0

def test_write_cache_timeout():
    """测试超时触发刷入"""
    write_cache = WriteCacheManager(mock_db, {
        'size_threshold': 1000000,  # 1MB
        'timeout_seconds': 1  # 1秒用于测试
    })
    
    # 添加一条数据
    memory = Memory(
        id="test_1",
        agent_id="test_agent",
        type=MemoryType.SHORT_TERM,
        category=MemoryCategory.CONVERSATION,
        content="Test message"
    )
    write_cache.buffer_memory(memory)
    
    # 等待超时
    time.sleep(2)
    
    # 检查是否触发刷入
    assert len(write_cache.pending_batches) > 0

def test_read_cache_hit():
    """测试读取缓存命中"""
    read_cache = ReadCacheManager(mock_db)
    
    # 先写入一条数据到数据库
    test_memory = Memory(
        id="test_1",
        agent_id="test_agent",
        type=MemoryType.SHORT_TERM,
        category=MemoryCategory.CONVERSATION,
        content="Test content"
    )
    # ... 保存到数据库
    
    # 第一次读取 (未命中,从数据库加载)
    result1 = read_cache.get_memory("test_1")
    assert result1 is not None
    assert read_cache.stats.misses == 1
    
    # 第二次读取 (命中缓存)
    result2 = read_cache.get_memory("test_1")
    assert result2 is not None
    assert read_cache.stats.hits == 1

def test_session_integrity():
    """测试会话完整性保障"""
    write_cache = WriteCacheManager(mock_db)
    session_guard = SessionIntegrityGuard(write_cache)
    
    # 开始会话
    session_guard.track_session_start("session_1", "agent_1")
    
    # 添加消息
    memory1 = Memory(
        id="msg_1",
        agent_id="agent_1",
        type=MemoryType.SHORT_TERM,
        category=MemoryCategory.CONVERSATION,
        content="Hello"
    )
    write_cache.buffer_memory(memory1, session_id="session_1")
    
    # 结束会话
    session_guard.track_session_end("session_1")
    
    # 检查批次是否标记为完整
    assert write_cache.current_batch.is_complete == True
```

### 10.2 集成测试

```python
def test_full_cache_flow():
    """测试完整缓存流程"""
    # 初始化缓存系统
    db = create_test_database()
    write_cache = WriteCacheManager(db)
    read_cache = ReadCacheManager(db)
    read_cache.set_write_cache(write_cache)
    
    coordinator = CacheCoordinator(read_cache, write_cache, SessionIntegrityGuard(write_cache))
    coordinator.start()
    
    # 1. 写入数据 (应该进入缓存)
    memory = Memory(
        id="test_mem_1",
        agent_id="test_agent",
        type=MemoryType.SHORT_TERM,
        category=MemoryCategory.CONVERSATION,
        content="Test conversation"
    )
    coordinator.add_memory(memory, session_id="test_session")
    
    # 2. 立即读取 (应该从缓存读取)
    result = coordinator.get_memory("test_mem_1")
    assert result is not None
    assert result.content == "Test conversation"
    
    # 3. 等待刷入
    time.sleep(3)
    
    # 4. 检查数据库
    cursor = db.cursor()
    cursor.execute("SELECT * FROM memories WHERE id = ?", ("test_mem_1",))
    row = cursor.fetchone()
    assert row is not None
    
    coordinator.stop()
```

## 11. 故障处理

### 11.1 异常恢复

```python
class CacheRecovery:
    """缓存恢复机制"""
    
    def recover_from_crash(self, write_cache: WriteCacheManager):
        """
        从崩溃中恢复
        """
        # 检查是否有未刷入的批次
        if write_cache.current_batch:
            logger.warning(f"Recovering {write_cache.current_batch.item_count} pending items")
            
            # 尝试刷入
            try:
                write_cache._flush_current_batch("recovery")
            except Exception as e:
                logger.error(f"Recovery flush failed: {e}")
                # 记录到恢复日志,下次启动时重试
                self._log_pending_items(write_cache.current_batch)
    
    def _log_pending_items(self, batch: FlushBatch):
        """记录待刷入项"""
        recovery_log = {
            'batch_id': batch.batch_id,
            'item_count': batch.item_count,
            'items': [item.to_dict() for item in batch.items]
        }
        
        # 写入恢复日志文件
        with open('cache_recovery.log', 'a') as f:
            f.write(json.dumps(recovery_log) + "\n")
```

### 11.2 优雅关闭

```python
class GracefulShutdown:
    """优雅关闭"""
    
    def shutdown(self, coordinator: CacheCoordinator):
        """
        优雅关闭缓存系统
        """
        logger.info("Starting graceful shutdown...")
        
        # 1. 停止接受新请求
        coordinator.running = False
        
        # 2. 等待后台任务完成
        coordinator.flush_scheduler.stop()
        coordinator.cache_cleaner.stop()
        
        # 3. 刷入所有缓存
        try:
            coordinator.write_cache.flush_all()
            logger.info("All caches flushed successfully")
        except Exception as e:
            logger.error(f"Shutdown flush error: {e}")
            # 记录未刷入项
            self._log_unflushed_items(coordinator.write_cache)
        
        # 4. 输出统计
        coordinator.write_cache.stats.log_stats()
        
        logger.info("Graceful shutdown complete")
```

## 12. 最佳实践

### 12.1 使用建议

1. **合理配置阈值**: 根据服务器内存和数据库性能调整阈值
2. **监控缓存命中率**: 命中率低于 70% 时需要优化
3. **会话完整性优先**: 宁可延迟刷入,不可截断会话
4. **定期清理缓存**: 避免内存泄漏
5. **优雅关闭**: 确保服务停止时刷入所有缓存

### 12.2 性能调优

| 场景 | 建议配置 |
|------|----------|
| 高并发写入 | 增大批次大小 (512KB), 延长超时 (300 秒) |
| 低延迟要求 | 减小批次大小 (128KB), 缩短超时 (60 秒) |
| 内存受限 | 减小读取缓存 (5MB), 缩短 TTL |
| 会话较长 | 增加会话超时检测时间 (600 秒) |
