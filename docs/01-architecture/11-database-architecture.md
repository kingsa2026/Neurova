# 数据库架构设计（主副表与索引机制）

## 1. 概述

### 1.1 设计目标

数据库采用**主副表分离架构**，核心目标:
- **核心与扩展分离**: 主表存储高频访问的核心字段，副表存储低频/扩展字段，保持主表轻量
- **索引驱动查询**: 通过精心设计的关联索引、复合索引、覆盖索引，将复杂查询延迟控制在 `<10ms`
- **批量写入友好**: 适配缓存层 256KB/180秒 批量刷入机制，避免索引频繁更新导致的性能抖动
- **数据完整性**: 严格的外键约束、级联策略、软删除机制
- **记忆温度机制**: 模拟人类遗忘曲线，通过温度维度实现记忆的升温、降温、次要、归档、删除全生命周期管理

### 1.2 主副表架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                         主表 (Primary Tables)                    │
│  ┌──────────────────────┐          ┌──────────────────────┐     │
│  │   memories (记忆)    │◄────────►│   sessions (会话)    │     │
│  │ - 核心记忆字段       │          │ - 会话状态/统计      │     │
│  │ - 高频查询列         │          │ - 会话生命周期       │     │
│  └──────────┬───────────┘          └──────────┬───────────┘     │
│             │ 1:N                             │ 1:N              │
└─────────────┼─────────────────────────────────┼─────────────────┘
              │                                 │
┌─────────────▼─────────────────────────────────▼─────────────────┐
│                         副表 (Secondary Tables)                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────┐ │
│  │ memory_      │ │ memory_      │ │ memory_      │ │session_│ │
│  │ emotions     │ │ relations    │ │ keywords     │ │messages│ │
│  │ (情感)       │ │ (关联)       │ │ (关键词)     │ │(消息)  │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └────────┘ │
│  ┌──────────────────────┐  ┌──────────────────────┐             │
│  │ session_context_     │  │ memory_access_logs   │             │
│  │ snapshots            │  │ (访问日志-可选)      │             │
│  │ (上下文快照)         │  │                      │             │
│  └──────────────────────┘  └──────────────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

## 2. 主表设计

### 2.1 记忆主表 (`memories`)

存储记忆的核心元数据，保持字段精简，覆盖 90% 的查询场景。

```sql
CREATE TABLE memories (
    -- 主键
    id TEXT PRIMARY KEY,
    
    -- 归属与分类 (高频过滤)
    agent_id TEXT NOT NULL,
    user_id TEXT,
    type TEXT NOT NULL CHECK(type IN ('short_term', 'long_term', 'emotional')),
    category TEXT CHECK(category IN ('conversation', 'fact', 'skill', 'experience', 'instruction')),
    
    -- 核心内容
    content TEXT NOT NULL,
    content_hash TEXT, -- SHA256 摘要，用于去重
    
    -- 权重与状态
    weight REAL DEFAULT 1.0 CHECK(weight >= 0 AND weight <= 5.0),
    access_count INTEGER DEFAULT 0,
    is_archived INTEGER DEFAULT 0, -- 0: 活跃, 1: 归档
    
    -- 记忆温度系统 (遗忘曲线核心)
    temperature REAL DEFAULT 50.0 CHECK(temperature >= 0.0 AND temperature <= 100.0), -- 当前温度 0-100
    last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- 最后访问时间 (用于计算降温)
    lifecycle_stage TEXT DEFAULT 'active' CHECK(lifecycle_stage IN ('active', 'secondary', 'archived', 'deleted')), -- 生命周期阶段
    
    -- 记忆属性标记 (温度衍生)
    is_important INTEGER DEFAULT 0, -- 1: 重要记忆 (温度≥80°C 或手动标注)
    is_crystallized INTEGER DEFAULT 0, -- 1: 固化记忆 (永久保存，永不降温)
    crystallized_at TIMESTAMP, -- 固化时间
    
    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP -- 短期记忆过期时间
    
    -- 注意: metadata 移至副表或按需 JSON 扩展，保持主表紧凑
);

-- 主表核心索引
CREATE INDEX idx_memories_agent_type ON memories(agent_id, type, is_archived);
CREATE INDEX idx_memories_created_desc ON memories(agent_id, created_at DESC);
CREATE INDEX idx_memories_weight_hot ON memories(agent_id, weight DESC, access_count DESC) 
    WHERE is_archived = 0; -- 部分索引：仅索引活跃记忆
```

### 2.2 会话主表 (`sessions`)

管理会话生命周期与统计信息。

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    
    -- 会话状态
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'idle', 'completed', 'aborted')),
    source_channel TEXT, -- wechat, telegram, web, internal
    
    -- 统计信息
    message_count INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    last_user_message_at TIMESTAMP,
    
    -- 时间戳
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 关联
    parent_session_id TEXT, -- 支持会话继承/分支
    
    FOREIGN KEY (parent_session_id) REFERENCES sessions(id) ON DELETE SET NULL
);

-- 会话查询索引
CREATE INDEX idx_sessions_agent_status ON sessions(agent_id, status, last_activity_at DESC);
CREATE INDEX idx_sessions_user_active ON sessions(user_id, status) WHERE status = 'active';
CREATE INDEX idx_sessions_idle_timeout ON sessions(status, last_activity_at) 
    WHERE status IN ('active', 'idle'); -- 用于空闲会话检测与刷入
```

## 3. 副表设计

### 3.1 情感记录副表 (`memory_emotions`)

与 `memories` 1:N 关联，按需查询，不污染主表。

```sql
CREATE TABLE memory_emotions (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    
    emotion_type TEXT NOT NULL CHECK(emotion_type IN ('joy', 'sadness', 'anger', 'fear', 'surprise', 'disgust', 'neutral')),
    intensity REAL NOT NULL CHECK(intensity >= 0.0 AND intensity <= 1.0),
    trigger_context TEXT, -- 触发原因/上下文摘要
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

-- 情感查询索引
CREATE INDEX idx_emotions_memory ON memory_emotions(memory_id);
CREATE INDEX idx_emotions_agent_type ON memory_emotions(memory_id, emotion_type, intensity DESC);
```

### 3.2 记忆关联副表 (`memory_relations`)

记录记忆间的图谱关系 (N:N)。

```sql
CREATE TABLE memory_relations (
    id TEXT PRIMARY KEY,
    source_memory_id TEXT NOT NULL,
    target_memory_id TEXT NOT NULL,
    
    relation_type TEXT NOT NULL CHECK(relation_type IN ('related', 'caused_by', 'part_of', 'similar_to', 'contradicts')),
    strength REAL DEFAULT 1.0 CHECK(strength >= 0.0 AND strength <= 1.0),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (source_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (target_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    
    -- 防止重复关联
    UNIQUE(source_memory_id, target_memory_id, relation_type)
);

-- 关联图谱查询索引
CREATE INDEX idx_relations_source ON memory_relations(source_memory_id, relation_type, strength DESC);
CREATE INDEX idx_relations_target ON memory_relations(target_memory_id);
```

### 3.3 关键词索引副表 (`memory_keywords`)

替代 SQLite FTS 的部分场景，提供精确的倒排索引控制。

```sql
CREATE TABLE memory_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL,
    keyword TEXT NOT NULL,
    relevance REAL DEFAULT 1.0,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

-- 关键词检索索引 (核心)
CREATE INDEX idx_keywords_lookup ON memory_keywords(keyword, relevance DESC, memory_id);
CREATE INDEX idx_keywords_memory ON memory_keywords(memory_id);
```

### 3.4 会话消息副表 (`session_messages`)

记录会话内的逐轮对话，与 `sessions` 1:N 关联。

```sql
CREATE TABLE session_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    token_count INTEGER DEFAULT 0,
    
    -- 路由与状态
    sequence_num INTEGER, -- 消息顺序
    is_summary INTEGER DEFAULT 0, -- 是否为历史摘要
    metadata TEXT, -- JSON: 包含 original_message_id, channel_info 等
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- 消息查询索引
CREATE INDEX idx_messages_session_seq ON session_messages(session_id, sequence_num ASC);
CREATE INDEX idx_messages_session_recent ON session_messages(session_id, created_at DESC);
```

### 3.5 社交图谱关联索引副表 (`social_graph`)

记录用户的人际关系网络，支持人物关系的强度变化追踪与图谱查询。

```sql
-- 人物实体表
CREATE TABLE social_entities (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    name TEXT NOT NULL,
    entity_type TEXT CHECK(entity_type IN ('person', 'group', 'organization', 'pet')),
    description TEXT,
    metadata TEXT,  -- JSON: 包含 birthday, occupation, avatar 等
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);

-- 关系边表 (N:N 图谱)
CREATE TABLE social_relationships (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    
    relationship_type TEXT NOT NULL CHECK(relationship_type IN (
        'family', 'friend', 'colleague', 'mentor', 'partner', 
        'acquaintance', 'rival', 'pet_owner'
    )),
    
    -- 关系强度 (0.0 - 1.0)
    strength REAL DEFAULT 0.5 CHECK(strength >= 0.0 AND strength <= 1.0),
    
    -- 关系演变追踪
    previous_strength REAL,
    strength_change_count INTEGER DEFAULT 0,
    
    -- 时间信息
    since_date TIMESTAMP,  -- 关系建立时间
    last_interacted_at TIMESTAMP,
    
    -- 关系标签
    tags TEXT,  -- JSON数组: ["close", "long_time_no_see"]
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    FOREIGN KEY (source_entity_id) REFERENCES social_entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_entity_id) REFERENCES social_entities(id) ON DELETE CASCADE,
    
    UNIQUE(source_entity_id, target_entity_id, relationship_type)
);

-- 记忆-人物关联表
CREATE TABLE memory_social_links (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    role_in_memory TEXT,  -- 该人物在记忆中的角色 (如"参与者", "提及者")
    importance REAL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES social_entities(id) ON DELETE CASCADE
);

-- 社交图谱索引
CREATE INDEX idx_social_entities_agent ON social_entities(agent_id, entity_type);
CREATE INDEX idx_social_relationships_agent ON social_relationships(agent_id, relationship_type, strength DESC);
CREATE INDEX idx_social_relationships_source ON social_relationships(source_entity_id, strength DESC);
CREATE INDEX idx_social_relationships_target ON social_relationships(target_entity_id);
CREATE INDEX idx_social_relationships_strength ON social_relationships(agent_id, strength DESC);
CREATE INDEX idx_social_memory_links ON memory_social_links(memory_id, entity_id);
CREATE INDEX idx_social_memory_entity ON memory_social_links(entity_id, importance DESC);
```

### 3.6 上下文快照副表 (`session_context_snapshots`)

缓存上下文构建结果，加速重复查询。

```sql
CREATE TABLE session_context_snapshots (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    query_hash TEXT NOT NULL, -- 用户查询的哈希
    snapshot_data TEXT NOT NULL, -- JSON: 构建好的完整上下文
    token_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX idx_snapshots_lookup ON session_context_snapshots(session_id, query_hash, expires_at);
```

## 4. 主副表关联索引机制

### 4.1 外键物理索引

SQLite 外键默认不自动创建索引，需显式创建以优化 JOIN 和级联操作:

```sql
-- 已在上文副表 DDL 中包含，此处统一说明:
-- 所有副表均包含: FOREIGN KEY (xxx_id) REFERENCES main_table(id)
-- 并配套创建: CREATE INDEX idx_{table}_{fk_column} ON {table}({fk_column});
```

### 4.2 逻辑关联映射表 (`entity_associations`)

处理跨主表的灵活关联 (如: 会话 ↔ 记忆 ↔ Agent)。

```sql
CREATE TABLE entity_associations (
    id TEXT PRIMARY KEY,
    entity_type_a TEXT NOT NULL, -- 'memory', 'session', 'agent'
    entity_id_a TEXT NOT NULL,
    entity_type_b TEXT NOT NULL,
    entity_id_b TEXT NOT NULL,
    association_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 多维关联查询索引
CREATE INDEX idx_associations_a ON entity_associations(entity_type_a, entity_id_a, association_type);
CREATE INDEX idx_associations_b ON entity_associations(entity_type_b, entity_id_b);
CREATE INDEX idx_associations_cross ON entity_associations(entity_type_a, entity_id_a, entity_type_b, entity_id_b);
```

### 4.3 覆盖索引 (Covering Indexes)

避免回表查询，直接在索引中返回所需数据:

```sql
-- 场景: 获取 Agent 的高权重记忆 ID 和类型 (无需查 content)
CREATE INDEX idx_memories_covering_hot ON memories(
    agent_id, weight DESC, type, category, created_at DESC
) WHERE is_archived = 0;

-- 场景: 会话状态检查 (无需查 ended_at 等)
CREATE INDEX idx_sessions_covering_active ON sessions(
    agent_id, user_id, status, last_activity_at
);
```

## 5. 复合索引与查询优化策略

### 5.1 高频查询模式与索引映射

| 查询场景 | SQL 模式 | 使用索引 | 预期延迟 |
|---------|---------|---------|---------|
| Agent 最新记忆 | `WHERE agent_id=? ORDER BY created_at DESC LIMIT ?` | `idx_memories_created_desc` | `<2ms` |
| 上下文检索 | `WHERE agent_id=? AND type=? AND weight>? ORDER BY weight DESC` | `idx_memories_agent_type` + `idx_memories_weight_hot` | `<3ms` |
| 活跃会话查找 | `WHERE agent_id=? AND status='active' ORDER BY last_activity_at` | `idx_sessions_agent_status` | `<1ms` |
| 关键词匹配 | `JOIN memory_keywords k ON m.id=k.memory_id WHERE k.keyword=?` | `idx_keywords_lookup` | `<4ms` |
| 情感关联查询 | `JOIN memory_emotions e ON m.id=e.memory_id WHERE e.emotion_type=?` | `idx_emotions_agent_type` | `<3ms` |
| 会话消息分页 | `WHERE session_id=? ORDER BY sequence_num LIMIT ? OFFSET ?` | `idx_messages_session_seq` | `<2ms` |

### 5.2 FTS5 全文检索集成 (可选增强)

当关键词索引无法满足模糊/语义搜索时，启用 FTS5:

```sql
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content,
    content='memories',
    content_rowid='rowid_placeholder', -- 需通过触发器同步
    tokenize='unicode61 remove_diacritics 2'
);

-- 同步触发器 (保持 FTS 与主表一致)
CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;

CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.rowid, old.content);
    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;
```

### 5.3 部分索引 (Partial Indexes) 优化

仅索引活跃/高频数据，减小索引体积，加速更新:

```sql
-- 仅索引近期活跃会话 (用于超时检测与缓存刷入)
CREATE INDEX idx_sessions_idle_partial ON sessions(last_activity_at, id)
    WHERE status IN ('active', 'idle') AND last_activity_at < datetime('now', '-180 seconds');

-- 仅索引未过期记忆
CREATE INDEX idx_memories_active_partial ON memories(agent_id, type, created_at DESC)
    WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP;
```

## 6. 索引维护与生命周期管理

### 6.1 自动维护策略

```python
class IndexMaintenanceManager:
    """索引维护管理器"""
    
    def analyze_indexes(self, db_connection):
        """
        运行 ANALYZE 更新查询计划器统计信息
        建议在批量刷入后或低峰期执行
        """
        cursor = db_connection.cursor()
        cursor.execute("ANALYZE memories")
        cursor.execute("ANALYZE sessions")
        cursor.execute("ANALYZE memory_keywords")
        db_connection.commit()
    
    def rebuild_fragmented_indexes(self, db_connection):
        """
        重建碎片化索引 (VACUUM 后自动重建)
        """
        # 检查索引碎片率
        cursor = db_connection.cursor()
        cursor.execute("PRAGMA freelist_count")
        free_pages = cursor.fetchone()[0]
        
        if free_pages > 100:  # 阈值可调
            db_connection.execute("VACUUM")
            self.analyze_indexes(db_connection)
    
    def schedule_maintenance(self):
        """调度维护任务"""
        # 每日低峰期执行
        # 每周执行一次完整 VACUUM + ANALYZE
        pass
```

### 6.2 索引健康监控

```sql
-- 查询未使用的索引 (可考虑删除以节省空间)
SELECT name, tbl_name FROM sqlite_master 
WHERE type='index' 
AND name NOT LIKE 'sqlite_%'
AND name NOT IN (
    -- 此处可通过 EXPLAIN QUERY PLAN 实际查询日志对比
    'idx_memories_agent_type', 'idx_sessions_agent_status' -- 示例
);

-- 检查索引大小
SELECT name, 
       (SELECT page_count FROM pragma_page_count()) * (SELECT page_size FROM pragma_page_size()) / 1024 AS db_size_kb
FROM sqlite_master WHERE type='index';
```

## 7. 与缓存层协同设计

### 7.1 批量写入索引优化

缓存层 256KB/180秒 批量刷入时，采用以下策略减少索引更新开销:

```sql
-- 1. 临时关闭外键检查 (批量插入时)
PRAGMA foreign_keys = OFF;

-- 2. 使用事务包裹批量插入
BEGIN TRANSACTION;
    -- 插入主表
    INSERT INTO memories (...) VALUES (...), (...), (...);
    -- 插入副表
    INSERT INTO memory_keywords (...) VALUES (...), (...);
    INSERT INTO memory_emotions (...) VALUES (...), (...);
COMMIT;

-- 3. 恢复外键检查
PRAGMA foreign_keys = ON;

-- 4. 批量更新统计信息 (ANALYZE)
```

### 7.2 读写分离索引策略

| 操作类型 | 索引策略 | 说明 |
|---------|---------|------|
| **批量写入** | 延迟索引维护 | 先插数据，事务提交后统一 ANALYZE |
| **实时读取** | 覆盖索引优先 | 直接走索引，不回表 |
| **上下文构建** | 复合索引 + JOIN | `agent_id + type + weight` 联合过滤 |
| **会话刷入** | 部分索引命中 | `WHERE status='active'` 精准定位 |

### 7.3 缓存失效与索引同步

```python
def invalidate_cache_on_db_update(db_event):
    """
    数据库更新后，使相关缓存失效
    利用索引快速定位受影响的缓存键
    """
    if db_event.table == 'memories':
        # 使 Agent 搜索缓存失效
        read_cache.invalidate_pattern(f"search:{db_event.agent_id}")
        # 使上下文缓存失效
        read_cache.invalidate_pattern(f"context:{db_event.agent_id}")
        
    elif db_event.table == 'sessions':
        # 使会话状态缓存失效
        read_cache.invalidate(f"session:{db_event.session_id}")
```

## 8. 完整 DDL 脚本

```sql
-- ==========================================
-- Neurova Database Schema v1.0
-- 主副表架构 + 关联索引设计
-- ==========================================

-- 启用 WAL 模式与外键
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -8000; -- 8MB 缓存页
PRAGMA temp_store = MEMORY;

-- 1. 主表: 记忆
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    user_id TEXT,
    type TEXT NOT NULL CHECK(type IN ('short_term', 'long_term', 'emotional')),
    category TEXT CHECK(category IN ('conversation', 'fact', 'skill', 'experience', 'instruction')),
    content TEXT NOT NULL,
    content_hash TEXT,
    weight REAL DEFAULT 1.0 CHECK(weight >= 0 AND weight <= 5.0),
    access_count INTEGER DEFAULT 0,
    is_archived INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

-- 2. 主表: 会话
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'idle', 'completed', 'aborted')),
    source_channel TEXT,
    message_count INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    last_user_message_at TIMESTAMP,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    parent_session_id TEXT,
    FOREIGN KEY (parent_session_id) REFERENCES sessions(id) ON DELETE SET NULL
);

-- 3. 副表: 情感记录
CREATE TABLE IF NOT EXISTS memory_emotions (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    emotion_type TEXT NOT NULL CHECK(emotion_type IN ('joy', 'sadness', 'anger', 'fear', 'surprise', 'disgust', 'neutral')),
    intensity REAL NOT NULL CHECK(intensity >= 0.0 AND intensity <= 1.0),
    trigger_context TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

-- 4. 副表: 记忆关联
CREATE TABLE IF NOT EXISTS memory_relations (
    id TEXT PRIMARY KEY,
    source_memory_id TEXT NOT NULL,
    target_memory_id TEXT NOT NULL,
    relation_type TEXT NOT NULL CHECK(relation_type IN ('related', 'caused_by', 'part_of', 'similar_to', 'contradicts')),
    strength REAL DEFAULT 1.0 CHECK(strength >= 0.0 AND strength <= 1.0),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (target_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    UNIQUE(source_memory_id, target_memory_id, relation_type)
);

-- 5. 副表: 关键词索引
CREATE TABLE IF NOT EXISTS memory_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL,
    keyword TEXT NOT NULL,
    relevance REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

-- 6. 副表: 会话消息
CREATE TABLE IF NOT EXISTS session_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    token_count INTEGER DEFAULT 0,
    sequence_num INTEGER,
    is_summary INTEGER DEFAULT 0,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- 7. 副表: 上下文快照
CREATE TABLE IF NOT EXISTS session_context_snapshots (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    snapshot_data TEXT NOT NULL,
    token_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- 8. 逻辑关联映射表
CREATE TABLE IF NOT EXISTS entity_associations (
    id TEXT PRIMARY KEY,
    entity_type_a TEXT NOT NULL,
    entity_id_a TEXT NOT NULL,
    entity_type_b TEXT NOT NULL,
    entity_id_b TEXT NOT NULL,
    association_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- 智能增强机制副表 (新增)
-- ==========================================

-- 9. 冲突表
CREATE TABLE IF NOT EXISTS memory_conflicts (
    id TEXT PRIMARY KEY,
    conflict_type TEXT NOT NULL,
    memory_a_id TEXT NOT NULL,
    memory_b_id TEXT NOT NULL,
    conflict_description TEXT,
    severity TEXT DEFAULT 'medium',
    confidence REAL DEFAULT 1.0,
    status TEXT DEFAULT 'detected',
    resolution_strategy TEXT,
    resolved_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (memory_a_id) REFERENCES memories(id),
    FOREIGN KEY (memory_b_id) REFERENCES memories(id)
);

-- 10. 联想图
CREATE TABLE IF NOT EXISTS memory_associations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_a_id TEXT NOT NULL,
    memory_b_id TEXT NOT NULL,
    association_type TEXT NOT NULL CHECK(association_type IN (
        'cooccurrence', 'temporal_proximity', 'emotion_consistency',
        'semantic_similar', 'user_defined'
    )),
    weight REAL DEFAULT 0.5 CHECK(weight >= 0 AND weight <= 1.0),
    supporting_count INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_a_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (memory_b_id) REFERENCES memories(id) ON DELETE CASCADE,
    UNIQUE(memory_a_id, memory_b_id, association_type)
);

-- 11. 合并历史
CREATE TABLE IF NOT EXISTS memory_merge_history (
    id TEXT PRIMARY KEY,
    primary_memory_id TEXT NOT NULL,
    merged_memory_ids TEXT NOT NULL,
    merge_type TEXT NOT NULL,
    merge_summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT DEFAULT 'system',
    FOREIGN KEY (primary_memory_id) REFERENCES memories(id)
);

-- 12. 溯源表
CREATE TABLE IF NOT EXISTS memory_provenance (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    original_content TEXT,
    transformations TEXT,
    creation_context TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

-- ==========================================
-- 索引定义 (按查询频率优化)
-- ==========================================

-- 主表索引
CREATE INDEX IF NOT EXISTS idx_memories_agent_type ON memories(agent_id, type, is_archived);
CREATE INDEX IF NOT EXISTS idx_memories_created_desc ON memories(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_weight_hot ON memories(agent_id, weight DESC, access_count DESC) 
    WHERE is_archived = 0;
CREATE INDEX IF NOT EXISTS idx_memories_covering_hot ON memories(agent_id, weight DESC, type, category, created_at DESC)
    WHERE is_archived = 0;

-- 会话索引
CREATE INDEX IF NOT EXISTS idx_sessions_agent_status ON sessions(agent_id, status, last_activity_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_user_active ON sessions(user_id, status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_sessions_idle_partial ON sessions(last_activity_at, id)
    WHERE status IN ('active', 'idle');

-- 副表外键与查询索引
CREATE INDEX IF NOT EXISTS idx_emotions_memory ON memory_emotions(memory_id);
CREATE INDEX IF NOT EXISTS idx_emotions_type ON memory_emotions(memory_id, emotion_type, intensity DESC);

CREATE INDEX IF NOT EXISTS idx_relations_source ON memory_relations(source_memory_id, relation_type, strength DESC);
CREATE INDEX IF NOT EXISTS idx_relations_target ON memory_relations(target_memory_id);

CREATE INDEX IF NOT EXISTS idx_keywords_lookup ON memory_keywords(keyword, relevance DESC, memory_id);
CREATE INDEX IF NOT EXISTS idx_keywords_memory ON memory_keywords(memory_id);

CREATE INDEX IF NOT EXISTS idx_messages_session_seq ON session_messages(session_id, sequence_num ASC);
CREATE INDEX IF NOT EXISTS idx_messages_session_recent ON session_messages(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_snapshots_lookup ON session_context_snapshots(session_id, query_hash, expires_at);

CREATE INDEX IF NOT EXISTS idx_associations_a ON entity_associations(entity_type_a, entity_id_a, association_type);
CREATE INDEX IF NOT EXISTS idx_associations_b ON entity_associations(entity_type_b, entity_id_b);

-- 智能增强索引
CREATE INDEX IF NOT EXISTS idx_conflicts_status ON memory_conflicts(status, severity, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conflicts_memory ON memory_conflicts(memory_a_id, memory_b_id);
CREATE INDEX IF NOT EXISTS idx_associations_memory_a ON memory_associations(memory_a_id, weight DESC);
CREATE INDEX IF NOT EXISTS idx_associations_memory_b ON memory_associations(memory_b_id, weight DESC);
CREATE INDEX IF NOT EXISTS idx_associations_type ON memory_associations(association_type, weight DESC);
CREATE INDEX IF NOT EXISTS idx_merge_history_primary ON memory_merge_history(primary_memory_id);
CREATE INDEX IF NOT EXISTS idx_provenance_memory ON memory_provenance(memory_id);

-- 情感衰减视图
CREATE VIEW IF NOT EXISTS current_emotions AS
SELECT 
    id, memory_id, emotion_type,
    intensity * EXP(-0.05 * 
        JULIANDAY(CURRENT_TIMESTAMP) - JULIANDAY(created_at)) AS decayed_intensity,
    created_at
FROM memory_emotions;
```

## 9. 性能基准与调优建议

### 9.1 预期性能指标

| 操作 | 数据量 | 索引命中 | 预期延迟 |
|------|--------|---------|---------|
| 单条记忆插入 | 10万条 | 无 | `<1ms` (批量 `<0.1ms`) |
| 上下文记忆检索 | 10万条 | 复合索引 | `3-5ms` |
| 会话状态查询 | 5万条 | 部分索引 | `<1ms` |
| 关键词倒排查询 | 50万条 | 倒排索引 | `5-8ms` |
| 情感关联查询 | 20万条 | 外键索引 | `2-4ms` |

### 9.2 调优 Checklist

- [ ] `PRAGMA journal_mode = WAL` 已启用 (并发读写优化)
- [ ] `PRAGMA cache_size` 设置为 `-8000` 或更高 (匹配服务器内存)
- [ ] 定期执行 `ANALYZE` (每周或批量刷入 10 次后)
- [ ] 监控 `sqlite_stat1` 确认查询计划器使用正确索引
- [ ] 对 `memories.content` 考虑启用 FTS5 (若需模糊搜索)
- [ ] 归档策略: `is_archived = 1` 的记忆移至历史表或压缩存储

## 10. 与现有架构集成关系

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  缓存层 (Cache) │───▶│  数据库主副表    │◀───│  上下文构建器   │
│  256KB/180s     │    │  memories/sessions│    │  ContextBuilder │
│  批量刷入       │    │  副表+索引       │    │  读取缓存优先   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                    ┌──────────────────────┐
                    │  索引维护与查询优化   │
                    │  - 复合索引命中      │
                    │  - 覆盖索引避免回表  │
                    │  - 部分索引减体积    │
                    └──────────────────────┘
```

该数据库架构完全兼容前序设计的**缓存机制**与**上下文处理系统**，通过主副表分离降低主表写入压力，通过精准的关联索引将查询延迟控制在毫秒级，为 Neurova 的高性能运行提供坚实的数据层基础。
