# 记忆系统架构设计

## 1. 概述

### 1.1 记忆系统目标

记忆系统是智能体框架的核心组件，负责：

- 存储和管理 Agent 的所有记忆
- 支持短期记忆和长期记忆
- 情感关联和记忆权重
- 高效检索和关联
- 记忆遗忘和清理机制

### 1.2 记忆分类体系

```text
记忆系统 (11种分类)
├── 对话记忆 (conversation) - 聊天记录、讨论内容
├── 事实记忆 (fact) - 客观信息、常识、数据
├── 用户画像 (profile) - 性格、偏好、习惯、生日等个人信息
├── 人际关系 (relationship) - 朋友、同事、家人、社交关系
├── 技能记忆 (skill) - 工具使用、操作方法、代码写法
├── 经验记忆 (experience) - 解决问题的过程、项目经历
├── 教训记忆 (lesson) - 失败经验、踩过的坑、避免的错误
├── 任务记忆 (task) - 正在进行的项目、待办、目标
├── 创意记忆 (creative) - 灵感、想法、脑暴结果
├── 情感记忆 (emotional) - 触发强烈情感的事件
└── 指令记忆 (instruction) - 用户要求、规则、约束
```

## 2. 记忆数据模型

### 2.1 核心数据表结构

```sql
-- ==========================================
-- 主表: 记忆
-- ==========================================
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('short_term', 'long_term', 'emotional')),
    category TEXT NOT NULL CHECK(category IN (
        'conversation', 'fact', 'profile', 'relationship',
        'skill', 'experience', 'lesson', 'task',
        'creative', 'emotional', 'instruction'
    )),
    content TEXT NOT NULL,
    content_hash TEXT,
    weight REAL DEFAULT 1.0,

    -- 温度与生命周期 (第 9 章)
    temperature REAL DEFAULT 50.0 CHECK(temperature >= 0 AND temperature <= 100),
    lifecycle_stage TEXT DEFAULT 'active' CHECK(lifecycle_stage IN ('active', 'secondary', 'archived', 'deleted')),
    is_archived INTEGER DEFAULT 0,
    access_count INTEGER DEFAULT 0,
    last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 记忆属性标记 (第 9/10 章)
    is_important INTEGER DEFAULT 0,
    is_crystallized INTEGER DEFAULT 0,
    crystallized_at TIMESTAMP,
    perspective TEXT DEFAULT 'user_statement' CHECK(perspective IN ('user_statement', 'ai_inference', 'shared_experience', 'external_source', 'hypothetical')),
    perspective_confidence REAL DEFAULT 1.0,
    source TEXT,

    -- 情感与元数据
    emotion_score REAL DEFAULT 0.0,
    emotion_tags TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    metadata TEXT
);

-- 全文检索虚拟表
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content, content_hash,
    content='memories', content_rowid='rowid'
);

-- ==========================================
-- 副表: 会话记录
-- ==========================================
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    user_id TEXT,
    title TEXT DEFAULT 'New Session',
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'archived', 'closed')),
    message_count INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    summary TEXT,
    last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 副表: 会话消息
CREATE TABLE session_messages (
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

-- 副表: 上下文快照
CREATE TABLE session_context_snapshots (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    snapshot_data TEXT NOT NULL,
    token_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- ==========================================
-- 副表: 情感记录
-- ==========================================
CREATE TABLE memory_emotions (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    emotion_type TEXT NOT NULL CHECK(emotion_type IN ('joy', 'sadness', 'anger', 'fear', 'surprise', 'disgust', 'neutral')),
    intensity REAL NOT NULL CHECK(intensity >= 0.0 AND intensity <= 1.0),
    trigger_context TEXT,
    decay_rate REAL DEFAULT 0.05,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

-- ==========================================
-- 副表: 记忆关联
-- ==========================================
CREATE TABLE memory_relations (
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

-- ==========================================
-- 副表: 关键词索引
-- ==========================================
CREATE TABLE memory_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL,
    keyword TEXT NOT NULL,
    relevance REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

-- ==========================================
-- 智能增强机制副表 (第 10 章)
-- ==========================================

-- 冲突表
CREATE TABLE memory_conflicts (
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

-- 联想图
CREATE TABLE memory_associations (
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

-- 合并历史
CREATE TABLE memory_merge_history (
    id TEXT PRIMARY KEY,
    primary_memory_id TEXT NOT NULL,
    merged_memory_ids TEXT NOT NULL,
    merge_type TEXT NOT NULL,
    merge_summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT DEFAULT 'system',
    FOREIGN KEY (primary_memory_id) REFERENCES memories(id)
);

-- 溯源表
CREATE TABLE memory_provenance (
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
-- 高级增强副表 (第 11 章 - Phase 2)
-- ==========================================

-- 向量嵌入表
CREATE TABLE memory_embeddings (
    memory_id TEXT PRIMARY KEY,
    vector_json TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

-- 记忆版本历史表
CREATE TABLE memory_versions (
    version_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    content_snapshot TEXT NOT NULL,
    metadata_snapshot TEXT,
    change_type TEXT NOT NULL,
    change_reason TEXT,
    previous_version_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

-- 社交图谱: 人物实体表
CREATE TABLE social_entities (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    name TEXT NOT NULL,
    entity_type TEXT CHECK(entity_type IN ('person', 'group', 'organization', 'pet')),
    description TEXT,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES sessions(agent_id)
);

-- 社交图谱: 关系边表
CREATE TABLE social_relationships (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL CHECK(relationship_type IN (
        'family', 'friend', 'colleague', 'mentor', 'partner',
        'acquaintance', 'rival', 'pet_owner'
    )),
    strength REAL DEFAULT 0.5 CHECK(strength >= 0.0 AND strength <= 1.0),
    previous_strength REAL,
    strength_change_count INTEGER DEFAULT 0,
    since_date TIMESTAMP,
    last_interacted_at TIMESTAMP,
    tags TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_entity_id) REFERENCES social_entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_entity_id) REFERENCES social_entities(id) ON DELETE CASCADE,
    UNIQUE(source_entity_id, target_entity_id, relationship_type)
);

-- 社交图谱: 记忆-人物关联表
CREATE TABLE memory_social_links (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    role_in_memory TEXT,
    importance REAL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES social_entities(id) ON DELETE CASCADE
);

-- 敏感信息记录表
CREATE TABLE sensitive_info_records (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    category TEXT NOT NULL,
    sensitivity_level TEXT NOT NULL,
    original_content TEXT,
    masked_content TEXT,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

-- 隐私日志
CREATE TABLE privacy_logs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 时间模式表
CREATE TABLE time_patterns (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    description TEXT,
    memory_ids TEXT,
    confidence REAL,
    occurrences INTEGER,
    time_info TEXT,
    active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES sessions(agent_id)
);

-- 事件提醒表
CREATE TABLE time_event_reminders (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    description TEXT,
    event_date TIMESTAMP NOT NULL,
    reminder_time TIMESTAMP,
    related_memories TEXT,
    importance REAL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES sessions(agent_id)
);

-- ==========================================
-- 索引定义
-- ==========================================

-- 主表索引
CREATE INDEX idx_memories_agent_type ON memories(agent_id, type, is_archived);
CREATE INDEX idx_memories_created_desc ON memories(agent_id, created_at DESC);
CREATE INDEX idx_memories_weight_hot ON memories(agent_id, weight DESC, access_count DESC)
    WHERE is_archived = 0;
CREATE INDEX idx_memories_covering_hot ON memories(agent_id, weight DESC, type, category, created_at DESC)
    WHERE is_archived = 0;

-- 温度与生命周期索引
CREATE INDEX idx_memories_temp_active ON memories(agent_id, temperature DESC, lifecycle_stage) WHERE lifecycle_stage = 'active';
CREATE INDEX idx_memories_important ON memories(agent_id, temperature DESC) WHERE is_important = 1;
CREATE INDEX idx_memories_crystallized ON memories(agent_id, crystallized_at DESC) WHERE is_crystallized = 1;
CREATE INDEX idx_memories_decay_scan ON memories(lifecycle_stage, last_accessed_at ASC) WHERE is_crystallized = 0;

-- 会话索引
CREATE INDEX idx_sessions_agent_status ON sessions(agent_id, status, last_activity_at DESC);
CREATE INDEX idx_sessions_user_active ON sessions(user_id, status) WHERE status = 'active';
CREATE INDEX idx_messages_session_seq ON session_messages(session_id, sequence_num ASC);
CREATE INDEX idx_messages_session_recent ON session_messages(session_id, created_at DESC);
CREATE INDEX idx_snapshots_lookup ON session_context_snapshots(session_id, query_hash, expires_at);

-- 副表外键与查询索引
CREATE INDEX idx_emotions_memory ON memory_emotions(memory_id);
CREATE INDEX idx_emotions_type ON memory_emotions(memory_id, emotion_type, intensity DESC);
CREATE INDEX idx_relations_source ON memory_relations(source_memory_id, relation_type, strength DESC);
CREATE INDEX idx_relations_target ON memory_relations(target_memory_id);
CREATE INDEX idx_keywords_lookup ON memory_keywords(keyword, relevance DESC, memory_id);
CREATE INDEX idx_keywords_memory ON memory_keywords(memory_id);

-- 智能增强索引
CREATE INDEX idx_conflicts_status ON memory_conflicts(status, severity, created_at DESC);
CREATE INDEX idx_conflicts_memory ON memory_conflicts(memory_a_id, memory_b_id);
CREATE INDEX idx_associations_memory_a ON memory_associations(memory_a_id, weight DESC);
CREATE INDEX idx_associations_memory_b ON memory_associations(memory_b_id, weight DESC);
CREATE INDEX idx_associations_type ON memory_associations(association_type, weight DESC);
CREATE INDEX idx_merge_history_primary ON memory_merge_history(primary_memory_id);
CREATE INDEX idx_provenance_memory ON memory_provenance(memory_id);

-- 高级增强索引
CREATE INDEX idx_embeddings_model ON memory_embeddings(model_name);
CREATE INDEX idx_versions_memory ON memory_versions(memory_id, version_number DESC);
CREATE INDEX idx_versions_created_at ON memory_versions(created_at DESC);
CREATE INDEX idx_versions_change_type ON memory_versions(change_type);
CREATE INDEX idx_social_entities_agent ON social_entities(agent_id, entity_type);
CREATE INDEX idx_social_relationships_agent ON social_relationships(agent_id, relationship_type, strength DESC);
CREATE INDEX idx_social_relationships_source ON social_relationships(source_entity_id, strength DESC);
CREATE INDEX idx_social_relationships_target ON social_relationships(target_entity_id);
CREATE INDEX idx_social_memory_links ON memory_social_links(memory_id, entity_id);
CREATE INDEX idx_social_memory_entity ON memory_social_links(entity_id, importance DESC);
CREATE INDEX idx_sensitive_memory ON sensitive_info_records(memory_id);
CREATE INDEX idx_privacy_logs_agent ON privacy_logs(agent_id, timestamp DESC);
CREATE INDEX idx_time_patterns_agent ON time_patterns(agent_id, pattern_type);
CREATE INDEX idx_time_reminders_agent ON time_event_reminders(agent_id, event_date DESC);

-- 情感衰减视图
CREATE VIEW IF NOT EXISTS current_emotions AS
SELECT
    id, memory_id, emotion_type,
    intensity * EXP(-0.05 *
        JULIANDAY(CURRENT_TIMESTAMP) - JULIANDAY(created_at)) AS decayed_intensity,
    created_at
FROM memory_emotions;
```

### 2.2 记忆数据模型类

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
from enum import Enum
import json

class MemoryType(Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    EMOTIONAL = "emotional"

class MemoryCategory(Enum):
    CONVERSATION = "conversation"       # 对话记忆 - 聊天记录、讨论内容
    FACT = "fact"                       # 事实记忆 - 客观信息、常识、数据
    PROFILE = "profile"                 # 用户画像 - 性格、偏好、习惯、生日等个人信息
    RELATIONSHIP = "relationship"       # 人际关系 - 朋友、同事、家人、社交关系
    SKILL = "skill"                     # 技能记忆 - 工具使用、操作方法、代码写法
    EXPERIENCE = "experience"           # 经验记忆 - 解决问题的过程、项目经历
    LESSON = "lesson"                   # 教训记忆 - 失败经验、踩过的坑、避免的错误
    TASK = "task"                       # 任务记忆 - 正在进行的项目、待办、目标
    CREATIVE = "creative"               # 创意记忆 - 灵感、想法、脑暴结果
    EMOTIONAL = "emotional"             # 情感记忆 - 触发强烈情感的事件
    INSTRUCTION = "instruction"         # 指令记忆 - 用户要求、规则、约束

class LifecycleStage(Enum):
    ACTIVE = "active"           # 活跃 (50-100°C)
    SECONDARY = "secondary"     # 次要 (20-50°C)
    ARCHIVED = "archived"       # 归档 (5-20°C)
    DELETED = "deleted"         # 删除 (0°C)

class MemoryPerspective(Enum):
    USER_STATEMENT = "user_statement"       # 用户明确说的
    AI_INFERENCE = "ai_inference"           # AI 推断的
    SHARED_EXPERIENCE = "shared_experience"  # 共同经历的
    EXTERNAL_SOURCE = "external_source"     # 外部获取的
    HYPOTHETICAL = "hypothetical"           # 假设/想象的

class EmotionType(Enum):
    JOY = "joy"
    SADNESS = "sadness"
    ANGER = "anger"
    FEAR = "fear"
    SURPRISE = "surprise"
    DISGUST = "disgust"
    NEUTRAL = "neutral"

@dataclass
class Memory:
    """记忆对象 (完整版，融合温度与智能增强机制)"""
    id: str
    agent_id: str
    type: MemoryType
    category: MemoryCategory
    content: str
    weight: float = 1.0
    
    # 温度与生命周期
    temperature: float = 50.0
    lifecycle_stage: LifecycleStage = LifecycleStage.ACTIVE
    is_archived: bool = False
    access_count: int = 0
    last_accessed_at: Optional[datetime] = None
    
    # 记忆属性 (第 9/10 章)
    is_important: bool = False
    is_crystallized: bool = False
    crystallized_at: Optional[datetime] = None
    perspective: MemoryPerspective = MemoryPerspective.USER_STATEMENT
    perspective_confidence: float = 1.0
    source: Optional[str] = None
    
    # 情感与元数据
    emotion_score: float = 0.0
    emotion_tags: List[EmotionType] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """转换为字典 (用于序列化/缓存)"""
        return {
            'id': self.id,
            'agent_id': self.agent_id,
            'type': self.type.value,
            'category': self.category.value,
            'content': self.content,
            'weight': self.weight,
            'temperature': self.temperature,
            'lifecycle_stage': self.lifecycle_stage.value,
            'is_archived': self.is_archived,
            'access_count': self.access_count,
            'last_accessed_at': self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            'is_important': self.is_important,
            'is_crystallized': self.is_crystallized,
            'crystallized_at': self.crystallized_at.isoformat() if self.crystallized_at else None,
            'perspective': self.perspective.value,
            'perspective_confidence': self.perspective_confidence,
            'source': self.source,
            'emotion_score': self.emotion_score,
            'emotion_tags': [e.value for e in self.emotion_tags],
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Memory':
        """从字典创建 (用于反序列化/数据库加载)"""
        return cls(
            id=data['id'],
            agent_id=data['agent_id'],
            type=MemoryType(data['type']),
            category=MemoryCategory(data['category']),
            content=data['content'],
            weight=data.get('weight', 1.0),
            temperature=data.get('temperature', 50.0),
            lifecycle_stage=LifecycleStage(data.get('lifecycle_stage', 'active')),
            is_archived=data.get('is_archived', False),
            access_count=data.get('access_count', 0),
            last_accessed_at=datetime.fromisoformat(data['last_accessed_at']) if data.get('last_accessed_at') else None,
            is_important=data.get('is_important', False),
            is_crystallized=data.get('is_crystallized', False),
            crystallized_at=datetime.fromisoformat(data['crystallized_at']) if data.get('crystallized_at') else None,
            perspective=MemoryPerspective(data.get('perspective', 'user_statement')),
            perspective_confidence=data.get('perspective_confidence', 1.0),
            source=data.get('source'),
            emotion_score=data.get('emotion_score', 0.0),
            emotion_tags=[EmotionType(e) for e in data.get('emotion_tags', [])],
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(data['updated_at']) if data.get('updated_at') else datetime.now(),
            expires_at=datetime.fromisoformat(data['expires_at']) if data.get('expires_at') else None,
            metadata=data.get('metadata', {})
        )

@dataclass
class MemoryRelation:
    """记忆关联"""
    id: str
    source_memory_id: str
    target_memory_id: str
    relation_type: str
    strength: float = 1.0
    created_at: datetime = field(default_factory=datetime.now)

@dataclass
class EmotionRecord:
    """情感记录"""
    id: str
    agent_id: str
    memory_id: Optional[str]
    emotion_type: EmotionType
    intensity: float
    trigger: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
```

## 3. 记忆分类体系

### 3.1 完整分类定义

| 分类 | 代码 | 说明 | 典型内容 | 生命周期特征 | 温度特征 |
|------|------|------|---------|-------------|---------|
| **对话记忆** | `conversation` | 聊天记录、讨论内容 | "用户说今天天气不错" | 较短，易降温 | 一般较低 |
| **事实记忆** | `fact` | 客观信息、常识、数据 | "用户叫张三，住在北京" | 长，不易过期 | 中等偏高 |
| **用户画像** | `profile` | 性格、偏好、习惯、生日 | "用户喜欢喝咖啡，不爱吃辣" | 极长，会演变 | 偏高 |
| **人际关系** | `relationship` | 朋友、同事、家人关系 | "张四是用户的高中同学" | 长，稳定 | 偏高 |
| **技能记忆** | `skill` | 工具使用、操作方法 | "使用 Git 提交代码的步骤" | 较长 | 取决于使用频率 |
| **经验记忆** | `experience` | 解决问题的过程、经历 | "上次项目部署遇到了坑" | 长，可转化为固化 | 高 |
| **教训记忆** | `lesson` | 失败经验、踩过的坑 | "不要在周五下午发布代码" | 极长 | 高，易固化 |
| **任务记忆** | `task` | 项目、待办、目标 | "完成 API 接口开发" | 中等，完成后降温 | 动态变化 |
| **创意记忆** | `creative` | 灵感、想法、脑暴 | "可以做个 AI 记账助手" | 较短，未实现则降温 | 不稳定 |
| **情感记忆** | `emotional` | 触发强烈情感的事件 | "用户生日时很开心" | 极长，情感保护 | 极高，易固化 |
| **指令记忆** | `instruction` | 用户要求、规则、约束 | "回复不要超过 200 字" | 长，直到用户更改 | 偏高 |

### 3.2 分类使用指南

#### 3.2.1 分类选择策略

```python
def classify_memory(content: str, context: Dict) -> MemoryCategory:
    """
    智能记忆分类
    
    判断逻辑:
    1. 情感触发? → EMOTIONAL
    2. 失败/错误? → LESSON
    3. 用户个人信息? → PROFILE
    4. 人际关系? → RELATIONSHIP
    5. 灵感/想法? → CREATIVE
    6. 任务/目标? → TASK
    7. 技能/方法? → SKILL
    8. 客观事实? → FACT
    9. 用户指令/规则? → INSTRUCTION
    10. 经历/过程? → EXPERIENCE
    11. 其他对话? → CONVERSATION
    """
    # 情感检测
    if context.get('emotion_intensity', 0) > 0.8:
        return MemoryCategory.EMOTIONAL
    
    # 教训检测
    if any(kw in content for kw in ['失败', '错误', '坑', '教训', '不要', '避免']):
        return MemoryCategory.LESSON
    
    # 画像检测
    if any(kw in content for kw in ['喜欢', '讨厌', '偏好', '习惯', '生日', '性格']):
        return MemoryCategory.PROFILE
    
    # 关系检测
    if any(kw in content for kw in ['朋友', '同事', '同学', '家人', '爸爸', '妈妈']):
        return MemoryCategory.RELATIONSHIP
    
    # 创意检测
    if any(kw in content for kw in ['想法', '灵感', '可以试试', '也许', '脑暴']):
        return MemoryCategory.CREATIVE
    
    # 任务检测
    if any(kw in content for kw in ['要完成', '待办', '计划', '目标', '项目']):
        return MemoryCategory.TASK
    
    # 技能检测
    if any(kw in content for kw in ['步骤', '方法', '如何使用', '技巧', '教程']):
        return MemoryCategory.SKILL
    
    # 指令检测
    if any(kw in content for kw in ['请', '要求', '规则', '不要', '必须']):
        return MemoryCategory.INSTRUCTION
    
    # 事实检测
    if context.get('is_objective_fact'):
        return MemoryCategory.FACT
    
    # 经验检测
    if context.get('is_past_experience'):
        return MemoryCategory.EXPERIENCE
    
    # 默认: 对话
    return MemoryCategory.CONVERSATION
```

#### 3.2.2 分类示例

```python
# 示例 1: 用户画像
memory = Memory(
    agent_id="assistant_1",
    type=MemoryType.LONG_TERM,
    category=MemoryCategory.PROFILE,
    content="用户喜欢喝拿铁咖啡，不喜欢美式",
    temperature=60.0,
    lifecycle_stage=LifecycleStage.ACTIVE,
    perspective=MemoryPerspective.USER_STATEMENT
)

# 示例 2: 教训记忆
memory = Memory(
    agent_id="assistant_1",
    type=MemoryType.LONG_TERM,
    category=MemoryCategory.LESSON,
    content="用户说上周五发布代码导致系统崩溃，以后避免周五发布",
    temperature=85.0,
    lifecycle_stage=LifecycleStage.ACTIVE,
    is_important=True,
    emotion_score=0.7,
    emotion_tags=[EmotionType.FEAR]
)

# 示例 3: 人际关系
memory = Memory(
    agent_id="assistant_1",
    type=MemoryType.LONG_TERM,
    category=MemoryCategory.RELATIONSHIP,
    content="李四是用户的大学同学，现在在同一公司工作",
    temperature=55.0,
    lifecycle_stage=LifecycleStage.ACTIVE,
    perspective=MemoryPerspective.USER_STATEMENT
)

# 示例 4: 创意记忆
memory = Memory(
    agent_id="assistant_1",
    type=MemoryType.SHORT_TERM,
    category=MemoryCategory.CREATIVE,
    content="用户想做一个 AI 记账助手，可以自动分类消费",
    temperature=50.0,
    lifecycle_stage=LifecycleStage.ACTIVE,
    expires_at=datetime.now() + timedelta(days=30)
)

# 示例 5: 情感记忆 (可能固化为永久记忆)
memory = Memory(
    agent_id="assistant_1",
    type=MemoryType.EMOTIONAL,
    category=MemoryCategory.EMOTIONAL,
    content="用户提到今天是结婚纪念日，非常开心",
    temperature=90.0,
    lifecycle_stage=LifecycleStage.ACTIVE,
    is_important=True,
    emotion_score=0.95,
    emotion_tags=[EmotionType.JOY, EmotionType.SURPRISE]
)
```

#### 3.2.3 分类优先级

```
固化优先级 (从高到低):
1. EMOTIONAL   - 情感记忆，最易固化
2. LESSON      - 教训记忆，高保护
3. PROFILE     - 用户画像，长期保留
4. RELATIONSHIP - 人际关系，长期保留
5. EXPERIENCE  - 经验记忆，可能转化为教训
6. FACT        - 事实记忆，稳定保留
7. SKILL       - 技能记忆，取决于使用
8. INSTRUCTION - 指令记忆，直到用户更改
9. TASK        - 任务记忆，完成后降温
10. CREATIVE   - 创意记忆，未实现则遗忘
11. CONVERSATION - 对话记忆，最易降温归档
```

## 4. 记忆系统架构

### 3.1 记忆管理器

```python
class MemoryManager:
    """
    记忆系统核心管理器
    负责记忆的存储、检索、更新和删除
    """
    
    def __init__(self, db_path: str, agent_id: str):
        self.db_path = db_path
        self.agent_id = agent_id
        self.connection = self._init_database()
        self.short_term_cache = LRUCache(max_size=100)
        self.emotion_engine = EmotionEngine()
    
    # ========== 记忆操作 ==========
    
    def add_memory(self, memory: Memory) -> str:
        """
        添加记忆
        1. 检查是否重复
        2. 存储到数据库
        3. 更新索引
        4. 创建情感关联
        """
        # 去重检查
        if self._is_duplicate(memory):
            return None
        
        # 存储记忆
        self._save_memory(memory)
        
        # 提取关键词并建立索引
        self._index_memory(memory)
        
        # 计算情感评分
        emotion_analysis = self.emotion_engine.analyze(memory.content)
        if emotion_analysis:
            memory.emotion_score = emotion_analysis.score
            memory.emotion_tags = emotion_analysis.tags
            self._update_emotion(memory, emotion_analysis)
        
        # 创建记忆关联
        self._create_relations(memory)
        
        # 短期记忆加入缓存
        if memory.type == MemoryType.SHORT_TERM:
            self.short_term_cache.put(memory.id, memory)
        
        return memory.id
    
    def get_memory(self, memory_id: str) -> Optional[Memory]:
        """获取记忆"""
        # 先查缓存
        if memory := self.short_term_cache.get(memory_id):
            return memory
        
        # 查询数据库
        return self._load_memory(memory_id)
    
    def search_memories(
        self,
        query: str,
        memory_type: Optional[MemoryType] = None,
        category: Optional[MemoryCategory] = None,
        limit: int = 10,
        min_weight: float = 0.0
    ) -> List[Memory]:
        """
        搜索记忆
        支持：
        - 关键词搜索
        - 语义搜索 (未来)
        - 过滤条件
        - 权重排序
        """
        # 关键词匹配
        keywords = self._extract_keywords(query)
        
        # 查询相关记忆
        memories = self._search_by_keywords(
            keywords=keywords,
            agent_id=self.agent_id,
            memory_type=memory_type,
            category=category,
            min_weight=min_weight,
            limit=limit * 2  # 多取一些用于排序
        )
        
        # 计算相关性评分
        scored_memories = []
        for memory in memories:
            score = self._calculate_relevance(query, memory)
            scored_memories.append((score, memory))
        
        # 按评分排序
        scored_memories.sort(key=lambda x: x[0], reverse=True)
        
        return [m for _, m in scored_memories[:limit]]
    
    def update_memory(self, memory_id: str, updates: Dict) -> bool:
        """更新记忆"""
        memory = self.get_memory(memory_id)
        if not memory:
            return False
        
        # 应用更新
        for key, value in updates.items():
            if hasattr(memory, key):
                setattr(memory, key, value)
        
        # 保存到数据库
        self._save_memory(memory)
        return True
    
    def delete_memory(self, memory_id: str) -> bool:
        """删除记忆"""
        # 删除关联
        self._delete_relations(memory_id)
        
        # 删除记忆
        return self._remove_memory(memory_id)
    
    # ========== 记忆管理 ==========
    
    def consolidate_memories(self):
        """
        记忆巩固
        将重要的短期记忆转化为长期记忆
        """
        # 查找访问频繁的短期记忆
        short_term_memories = self._get_memories_by_type(
            MemoryType.SHORT_TERM,
            min_access_count=3
        )
        
        for memory in short_term_memories:
            # 提升权重
            memory.weight *= 1.5
            
            # 转换为长期记忆
            memory.type = MemoryType.LONG_TERM
            memory.expires_at = None
            
            # 保存更新
            self._save_memory(memory)
    
    def forget_memories(self):
        """
        遗忘机制
        清理过期或低权重的记忆
        """
        # 删除过期的短期记忆
        self._delete_expired_memories()
        
        # 降低长期未访问记忆的权重
        self._decay_unused_memories()
        
        # 删除权重过低的记忆
        self._delete_low_weight_memories(threshold=0.1)
    
    def get_context_memories(
        self,
        query: str,
        max_count: int = 5
    ) -> List[Memory]:
        """
        获取上下文相关记忆
        用于提供给 LLM 作为上下文
        """
        # 搜索相关记忆
        relevant = self.search_memories(
            query=query,
            limit=max_count * 2
        )
        
        # 获取关联记忆
        expanded = []
        for memory in relevant[:max_count]:
            expanded.append(memory)
            relations = self._get_related_memories(memory.id)
            expanded.extend(relations[:2])
        
        # 去重和排序
        unique_memories = {m.id: m for m in expanded}
        sorted_memories = sorted(
            unique_memories.values(),
            key=lambda m: m.weight * (1 + m.emotion_score),
            reverse=True
        )
        
        return sorted_memories[:max_count]
    
    # ========== 内部方法 ==========
    
    def _init_database(self) -> sqlite3.Connection:
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self._create_tables(conn)
        return conn
    
    def _create_tables(self, conn: sqlite3.Connection):
        """创建数据表"""
        # 执行 SQL 建表语句
        pass
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        # 使用 NLP 技术提取关键词
        # 可以使用 jieba, spacy 等库
        pass
    
    def _calculate_relevance(
        self,
        query: str,
        memory: Memory
    ) -> float:
        """计算相关性评分"""
        # 基于关键词匹配、权重、情感等计算
        pass
    
    def _create_relations(self, memory: Memory):
        """创建记忆关联"""
        # 查找相似记忆并建立关联
        similar = self._find_similar_memories(memory)
        for sim in similar:
            relation = MemoryRelation(
                id=generate_id(),
                source_memory_id=memory.id,
                target_memory_id=sim.id,
                relation_type='similar_to',
                strength=0.8
            )
            self._save_relation(relation)
```

### 3.2 情感引擎

```python
class EmotionEngine:
    """
    情感分析引擎
    分析内容的情感倾向并生成情感标签
    """
    
    def __init__(self):
        self.emotion_model = self._load_emotion_model()
    
    def analyze(self, text: str) -> Optional[EmotionAnalysis]:
        """
        分析文本情感
        返回情感评分和标签
        """
        # 使用 NLP 模型分析情感
        # 可以使用 transformers, textblob 等库
        pass
    
    def update_agent_emotion(
        self,
        agent_id: str,
        emotion_record: EmotionRecord
    ):
        """更新 Agent 的情感状态"""
        pass
    
    def get_current_emotion_state(self, agent_id: str) -> EmotionState:
        """获取 Agent 当前情感状态"""
        pass
```

### 3.3 记忆存储接口

```python
class MemoryStorage(ABC):
    """记忆存储抽象接口"""
    
    @abstractmethod
    def save(self, memory: Memory) -> bool:
        pass
    
    @abstractmethod
    def load(self, memory_id: str) -> Optional[Memory]:
        pass
    
    @abstractmethod
    def search(self, query: Dict) -> List[Memory]:
        pass
    
    @abstractmethod
    def delete(self, memory_id: str) -> bool:
        pass

class SQLiteMemoryStorage(MemoryStorage):
    """SQLite 实现"""
    pass

class RedisMemoryStorage(MemoryStorage):
    """Redis 实现 (未来扩展)"""
    pass
```

## 4. 记忆使用流程

### 4.1 对话记忆流程

```
用户输入 → Agent 接收
            ↓
      查询相关记忆 (get_context_memories)
            ↓
      构建上下文 (系统提示 + 相关记忆 + 对话历史)
            ↓
      调用 LLM
            ↓
      生成响应
            ↓
      存储对话到短期记忆
            ↓
      更新情感状态
            ↓
      发送响应给用户
```

### 4.2 记忆巩固流程

```
定期任务 (每 30 分钟)
      ↓
检查短期记忆访问频率
      ↓
筛选高价值记忆 (access_count >= 3)
      ↓
转换为长期记忆
      ↓
建立记忆关联
      ↓
清理过期记忆
```

## 5. 性能优化

### 5.1 缓存策略

- LRU 缓存短期记忆
- 热点记忆预加载
- 查询结果缓存

### 5.2 索引优化

- 关键词倒排索引
- 复合索引 (agent_id + type + created_at)
- 定期重建索引

### 5.3 批量操作

- 批量插入记忆
- 批量更新权重
- 异步删除

## 6. 记忆可视化

### 6.1 记忆图谱

```python
class MemoryGraph:
    """记忆图谱可视化"""
    
    def generate_graph_data(self) -> Dict:
        """生成图谱数据"""
        nodes = []
        edges = []
        
        # 获取所有记忆
        memories = self.memory_manager.get_all_memories()
        for m in memories:
            nodes.append({
                'id': m.id,
                'label': m.content[:50],
                'type': m.type.value,
                'weight': m.weight,
                'emotion': m.emotion_score
            })
        
        # 获取所有关联
        relations = self.memory_manager.get_all_relations()
        for r in relations:
            edges.append({
                'source': r.source_memory_id,
                'target': r.target_memory_id,
                'strength': r.strength,
                'type': r.relation_type
            })
        
        return {'nodes': nodes, 'edges': edges}
```

## 7. 测试用例

### 7.1 单元测试

```python
def test_add_memory():
    manager = MemoryManager(":memory:", "test_agent")
    memory = Memory(
        id="test_1",
        agent_id="test_agent",
        type=MemoryType.SHORT_TERM,
        category=MemoryCategory.CONVERSATION,
        content="今天天气很好"
    )
    memory_id = manager.add_memory(memory)
    assert memory_id is not None

def test_search_memories():
    manager = MemoryManager(":memory:", "test_agent")
    # 添加测试数据
    # ...
    results = manager.search_memories("天气")
    assert len(results) > 0

def test_memory_consolidation():
    manager = MemoryManager(":memory:", "test_agent")
    # 测试记忆巩固
    # ...
```

### 7.2 集成测试

```python
def test_full_conversation_flow():
    # 测试完整的对话记忆流程
    # ...
```

## 8. 监控指标

### 8.1 关键指标

- 记忆总数 (按类型)
- 记忆增长率
- 平均查询延迟
- 缓存命中率
- 记忆巩固率
- 遗忘率

### 8.2 告警规则

- 记忆数据库大小超过阈值
- 查询延迟超过阈值
- 缓存命中率过低

## 9. 记忆温度机制 (Memory Temperature)

### 9.1 设计理念

记忆温度机制模拟**人类记忆的遗忘曲线**，通过动态温度维度实现记忆的智能生命周期管理。

> **频繁使用的记忆保持高温，长期不用的记忆自然降温，重要记忆通过情感和意义关联保持恒温，最终遗忘的记忆优雅退场。**

### 9.2 记忆温度生命周期

```
温度 100°C ───────────────────────────────────────────────
              │
          70°C│  ╭──╮    ╭─╮         ╭─╮
              │  │  │    │ │         │ │  ← 活跃期 (升温/恒温)
          50°C│  │  │    │ │    ╭────╯ │
              │  ╰──╯    │ │    │      │
          30°C│          ╰─╯    │      │  ← 次要期 (缓慢降温)
              │                 │      │
              │                 ╰──────╯
          10°C│                        │  ← 归档期 (接近遗忘)
              │                        │
           0°C│                        ╰── 删除
              └────────┬───────┬───────┬───────→ 时间
                    7天未中  30天未中  60天未中
```

### 9.3 记忆属性分类（温度衍生）

| 属性类型     | 触发条件                         | 数据库标记                               | 保护级别   | 降温策略              |
| -------- | ---------------------------- | ----------------------------------- | ------ | ----------------- |
| **普通记忆** | 默认                           | `is_important=0, is_crystallized=0` | 标准     | 正常遗忘曲线            |
| **重要记忆** | 温度 ≥80°C 或 手动标注              | `is_important=1, is_crystallized=0` | 高级     | 减缓 60% 降温，最低 30°C |
| **固化记忆** | 温度 ≥90°C + 特殊意义 或 Agent/用户锁定 | `is_crystallized=1`                 | **最高** | **永不降温，永久保存**     |

### 9.4 记忆属性升级路径

```
普通记忆 ──温度≥80°C──→ 重要记忆 ──温度≥90°C + 特殊意义──→ 固化记忆
    ↑                      ↑                                ↑
  新创建              频繁访问/强情感                     Agent 自主判断
  (50°C)              经验总结/关联多                     用户手动锁定
                      自动升级                          永久保存，永不遗忘
```

### 9.5 记忆数据模型更新（温度字段）

```python
@dataclass
class Memory:
    """记忆对象（完整版，含温度机制）"""
    id: str
    agent_id: str
    type: MemoryType
    category: MemoryCategory
    content: str
    weight: float = 1.0
    emotion_score: float = 0.0
    emotion_tags: List[EmotionType] = field(default_factory=list)
    access_count: int = 0
    last_accessed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    metadata: Dict = field(default_factory=dict)
    
    # ========== 温度系统字段 ==========
    temperature: float = 50.0  # 当前温度 0-100，默认 50
    lifecycle_stage: str = 'active'  # active/secondary/archived/deleted
    
    # 温度衍生属性
    is_important: bool = False  # 重要记忆标记
    is_crystallized: bool = False  # 固化永久记忆标记
    crystallized_at: Optional[datetime] = None  # 固化时间
```

### 9.6 温度计算引擎

```python
class MemoryTemperatureEngine:
    """
    记忆温度计算引擎
    综合情感、关联、命中次数、时间衰减
    """
    
    # 生命周期阶段阈值
    ACTIVE_THRESHOLD = 50.0       # 50°C 以上为活跃
    SECONDARY_THRESHOLD = 20.0    # 20-50°C 为次要
    ARCHIVED_THRESHOLD = 5.0      # 5-20°C 为归档
    DELETE_THRESHOLD = 0.0        # 0°C 触发删除
    
    # 时间阈值 (天)
    DAYS_TO_SECONDARY = 7         # 7 天未命中降为次要
    DAYS_TO_ARCHIVED = 30         # 30 天未命中降为归档
    DAYS_TO_DELETE = 60           # 60 天未命中触发删除
    
    def update_temperature(self, memory: Memory) -> Memory:
        """
        更新记忆温度
        T(t) = T_base + ΔT_hit + ΔT_emotion + ΔT_relation + ΔT_decay
        """
        # 1. 升温因素
        hit_boost = self._calculate_hit_boost(memory)
        emotion_bonus = self._calculate_emotion_bonus(memory)
        relation_bonus = self._calculate_relation_bonus(memory)
        
        # 2. 降温因素 (遗忘曲线)
        days_idle = (datetime.now() - memory.last_accessed_at).days
        decay = self._calculate_decay(
            memory.temperature, days_idle,
            has_emotion=emotion_bonus > 0,
            has_relation=relation_bonus > 0
        )
        
        # 3. 综合计算
        new_temp = (
            memory.temperature 
            + hit_boost + emotion_bonus + relation_bonus - decay
        )
        new_temp = max(0.0, min(100.0, new_temp))
        
        # 4. 更新
        memory.temperature = new_temp
        memory.lifecycle_stage = self._determine_lifecycle_stage(
            new_temp, days_idle, memory
        )
        memory.last_accessed_at = datetime.now()
        
        # 5. 检查属性升级
        self._check_attribute_upgrade(memory)
        
        return memory
    
    def _calculate_hit_boost(self, memory: Memory) -> float:
        """
        每次查询命中，温度上升一个维度
        采用对数增长，避免无限升温
        """
        base_boost = 5.0
        combo_multiplier = 1.0 + (memory.access_count % 10) * 0.1
        saturation_factor = 1.0 - (memory.temperature / 100.0) ** 2
        return base_boost * combo_multiplier * saturation_factor
    
    def _calculate_decay(self, current_temp, days_idle, has_emotion, has_relation) -> float:
        """
        时间衰减计算 (模拟艾宾浩斯遗忘曲线)
        - 初期衰减快 (24 小时内遗忘 50%)
        - 后期衰减慢 (30 天后遗忘速度减缓)
        - 情感/关联记忆衰减更慢
        """
        if days_idle <= 0:
            return 0.0
        
        base_decay_rate = 0.05  # 每日基础衰减 5%
        
        if days_idle <= 1:
            curve_factor = 2.0  # 24 小时内快速衰减
        elif days_idle <= 7:
            curve_factor = 1.0
        elif days_idle <= 30:
            curve_factor = 0.5
        else:
            curve_factor = 0.2
        
        emotion_protect = 0.6 if has_emotion else 1.0
        relation_protect = 0.7 if has_relation else 1.0
        
        return current_temp * base_decay_rate * curve_factor * emotion_protect * relation_protect
```

### 9.7 重要记忆升级机制

```python
def should_upgrade_to_important(memory: Memory) -> bool:
    """
    判断是否升级为重要记忆
    条件 (满足任一):
    1. 温度 ≥ 80°C
    2. 访问次数 ≥ 10 且温度 ≥ 70°C
    3. 强情感 (emotion_score ≥ 0.8) 且温度 ≥ 65°C
    4. 关联数 ≥ 5 且温度 ≥ 60°C
    """
    if memory.temperature >= 80.0:
        return True
    
    if memory.access_count >= 10 and memory.temperature >= 70.0:
        return True
    
    if memory.emotion_score >= 0.8 and memory.temperature >= 65.0:
        return True
    
    relation_count = get_relation_count(memory.id)
    if relation_count >= 5 and memory.temperature >= 60.0:
        return True
    
    return False
```

### 9.8 固化永久记忆机制

```python
def should_crystallize(memory: Memory) -> bool:
    """
    判断是否固化为永久记忆
    固化后: 永不降温，永久保存，永不遗忘
    
    条件 (满足任一):
    1. 温度 ≥ 90°C + 特殊意义 (情感≥0.9 / 关联≥10 / 经验总结)
    2. Agent 自主判断有特殊意义
    3. 用户手动锁定
    4. 包含特殊关键词 (纪念日、生日、结婚等)
    """
    # 温度 + 特殊意义
    if memory.temperature >= 90.0 and memory.is_important:
        if has_special_meaning(memory):
            return True
    
    # Agent 自主标记
    if memory.metadata.get('agent_marked_important'):
        return True
    
    # 用户手动锁定
    if memory.metadata.get('user_locked'):
        return True
    
    # 特殊关键词检测
    special_keywords = [
        '纪念日', '生日', '结婚', '周年', '毕业',
        'anniversary', 'birthday', 'wedding', 'graduation'
    ]
    for keyword in special_keywords:
        if keyword in memory.content.lower():
            return True
    
    return False

def has_special_meaning(memory: Memory) -> bool:
    """判断记忆是否有特殊意义"""
    if memory.emotion_score >= 0.9:
        return True
    
    if get_relation_count(memory.id) >= 10:
        return True
    
    if memory.category == 'experience' and memory.access_count >= 15:
        return True
    
    return memory.metadata.get('special_meaning', False)
```

### 9.9 生命周期状态转换规则

```python
def determine_lifecycle_stage(temperature, days_idle, memory) -> str:
    """
    生命周期阶段转换规则
    
    固化记忆不参与阶段转换，始终保持在 active 状态
    """
    # 固化记忆: 永不降温，永远活跃
    if memory.is_crystallized:
        return 'active'
    
    # 重要记忆: 最低保持 secondary，不归档
    if memory.is_important:
        if temperature < 20.0:
            return 'secondary'  # 重要记忆最低到次要
        return 'active' if temperature >= 50.0 else 'secondary'
    
    # 普通记忆: 正常生命周期
    if memory.lifecycle_stage == 'active' and \
       days_idle >= 7 and temperature < 50.0:
        return 'secondary'
    
    if memory.lifecycle_stage in ['active', 'secondary'] and \
       days_idle >= 30 and temperature < 20.0:
        return 'archived'
    
    if memory.lifecycle_stage == 'archived' and \
       days_idle >= 60 and temperature < 5.0:
        return 'deleted'
    
    return memory.lifecycle_stage
```

### 9.10 记忆生命周期状态机

```
                ┌─────────────────────────────────────┐
                │                                     │
                ▼  创建 (50°C)                        │
            ┌────────┐                                │
            │ ACTIVE │                                │
            │ 50-100°│                                │
            └───┬────┘                                │
                │ 7 天未命中 + T<50°C                 │
                ▼                                     │
            ┌────────────┐                            │
            │ SECONDARY  │                            │
            │ 20-50°C    │                            │
            └───┬────────┘                            │
                │ 30 天未命中 + T<20°C                │
                ▼                                     │
            ┌────────┐                                │
            │ARCHIVED│                                │
            │ 5-20°C │                                │
            └───┬────┘                                │
                │ 60 天未命中 + T<5°C                 │
                ▼                                     │
            ┌────────┐                                │
            │ DELETED│────────────────────────────────┘
            │ 0°C    │  (物理删除)
            └────────┘
                
    ←─── 命中升温可逆向转换 ───→
    
    ⭐ 固化记忆 (Crystallized): 锁定在 ACTIVE，永不进入其他阶段
    ⭐ 重要记忆 (Important):  最低 SECONDARY，永不归档/删除
```

### 9.11 自动衰减调度器

```python
class TemperatureDecayScheduler:
    """
    温度衰减调度器
    定期扫描并更新所有记忆温度
    建议: 每小时或每天低峰期执行
    """
    
    def run_decay_cycle(self):
        """执行一轮温度衰减"""
        cursor = self.db.cursor()
        
        # 按生命周期分批处理 (固化记忆跳过)
        for stage in ['active', 'secondary', 'archived']:
            cursor.execute("""
                SELECT id, temperature, last_accessed_at, 
                       access_count, lifecycle_stage, is_crystallized
                FROM memories
                WHERE lifecycle_stage = ?
                  AND is_crystallized = 0  -- 跳过固化记忆
                  AND last_accessed_at < datetime('now', '-1 hours')
                ORDER BY temperature ASC
                LIMIT 1000
            """, (stage,))
            
            for row in cursor.fetchall():
                memory = self._row_to_memory(row)
                updated = self.engine.update_temperature(memory)
                
                if updated.lifecycle_stage != memory.lifecycle_stage:
                    self._handle_stage_transition(memory, updated)
                
                self._save_temperature_update(updated)
            
            self.db.commit()
        
        # 清理已删除的记忆
        self._cleanup_deleted_memories()
    
    def _handle_stage_transition(self, old_memory, new_memory):
        """处理生命周期阶段转换"""
        old_stage = old_memory.lifecycle_stage
        new_stage = new_memory.lifecycle_stage
        
        logger.info(
            f"Memory {new_memory.id} transition: "
            f"{old_stage} → {new_stage} "
            f"(T: {old_memory.temperature:.1f}°C → {new_memory.temperature:.1f}°C)"
        )
        
        if new_stage == 'archived':
            self._archive_memory(new_memory)
        elif new_stage == 'deleted':
            self._schedule_deletion(new_memory)
```

### 9.12 温度加权查询

```python
def get_context_memories_with_temperature(agent_id, query, max_count=5):
    """
    基于温度的上下文记忆检索
    优先返回高温、重要、固化记忆
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, content, temperature, weight, is_important, is_crystallized
        FROM memories
        WHERE agent_id = ? 
          AND lifecycle_stage = 'active'
        ORDER BY 
            is_crystallized DESC,          -- 固化记忆优先
            is_important DESC,             -- 重要记忆次之
            (temperature * 0.4 + weight * 0.3 + access_count * 0.3) DESC
        LIMIT ?
    """, (agent_id, max_count))
    
    return [self._row_to_memory(row) for row in cursor.fetchall()]
```

### 9.13 记忆温度相关索引

```sql
-- 活跃记忆温度索引 (高频使用)
CREATE INDEX idx_memories_temp_active ON memories(
    agent_id, temperature DESC, lifecycle_stage
) WHERE lifecycle_stage = 'active' AND temperature >= 30;

-- 重要记忆索引 (优先查询)
CREATE INDEX idx_memories_important ON memories(
    agent_id, temperature DESC, is_important
) WHERE is_important = 1;

-- 固化记忆索引 (永久保存，最高优先级)
CREATE INDEX idx_memories_crystallized ON memories(
    agent_id, crystallized_at DESC, temperature DESC
) WHERE is_crystallized = 1;

-- 降温扫描索引 (用于衰减调度器)
CREATE INDEX idx_memories_decay_scan ON memories(
    lifecycle_stage, last_accessed_at ASC, temperature
) WHERE is_crystallized = 0;  -- 跳过固化记忆

-- 待固化候选索引 (温度≥85°C 的重要记忆)
CREATE INDEX idx_memories_crystallization_candidates ON memories(
    is_important, temperature DESC, access_count DESC
) WHERE is_important = 1 AND temperature >= 85 AND is_crystallized = 0;
```

### 9.14 温度监控指标

| 指标         | 健康范围    | 说明              |
| ---------- | ------- | --------------- |
| **高温记忆占比** | 20-40%  | 活跃记忆应保持一定比例     |
| **遗忘率**    | < 10%/天 | 每日降温记忆不超过 10%   |
| **平均温度**   | 40-60°C | 整体温度保持适中        |
| **重要记忆占比** | 10-25%  | 重要记忆占总量的 10-25% |
| **固化记忆数量** | 无上限     | 永久保存，按需增长       |
| **归档率**    | < 20%   | 归档记忆不超过 20%     |

### 9.15 温度系统配置示例

```yaml
# temperature.yaml
temperature:
  default_temperature: 50.0
  hit_boost_base: 5.0
  emotion_protection_factor: 0.6
  relation_protection_factor: 0.7
  decay_rate_base: 0.05
  
  lifecycle_thresholds:
    active:
      min_temperature: 50.0
      max_idle_days: 7
    secondary:
      min_temperature: 20.0
      max_idle_days: 30
    archived:
      min_temperature: 5.0
      max_idle_days: 60
  
  important_upgrade:
    min_temperature: 80.0
    min_access_count: 10
    min_emotion_score: 0.8
    min_relation_count: 5
  
  crystallization:
    min_temperature: 90.0
    min_emotion_score: 0.9
    min_relation_count: 10
    special_keywords:
      - 纪念日
      - 生日
      - 结婚
      - anniversary
      - birthday
      - wedding
  
  scheduler:
    run_interval_minutes: 60
    batch_size: 1000
```

## 10. 记忆智能增强机制

### 10.1 设计理念

在基础记忆系统和温度机制之上，增加**智能增强层**，让记忆系统具备类似人类的认知能力：

- **冲突检测** - 识别矛盾记忆，避免自相矛盾
- **睡眠整理** - 定期提炼洞察，发现规律
- **联想能力** - 基于关联图谱实现"突然想到"
- **元认知** - 知道自己"记得什么"和"不记得什么"
- **情感衰减** - 情感独立于内容衰减，避免"记仇"
- **视角标记** - 区分事实、观点、推断
- **可解释性** - 能解释"为什么我记得这个"
- **遗忘恢复** - 从归档中恢复记忆
- **记忆合并** - 相似记忆聚类去重，生成摘要

### 10.2 记忆冲突检测与消解机制

#### 10.2.1 冲突类型

```python
class ConflictType(Enum):
    DIRECT_CONTRADICTION = "direct_contradiction"  # 直接矛盾
    TEMPORAL_CONFLICT = "temporal_conflict"        # 时间冲突
    PREFERENCE_CONFLICT = "preference_conflict"    # 偏好冲突
    FACTUAL_CONFLICT = "factual_conflict"          # 事实冲突

@dataclass
class MemoryConflict:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conflict_type: ConflictType
    memory_a_id: str
    memory_b_id: str
    conflict_description: str
    severity: str = "medium"  # low/medium/high/critical
    confidence: float = 1.0
    status: str = "detected"  # detected/resolved/ignored
    resolution_strategy: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None
```

#### 10.2.2 冲突检测引擎

```python
class ConflictDetector:
    """记忆冲突检测引擎"""
    
    # 矛盾词对
    CONTRADICTION_PAIRS = {
        ('喜欢', '不喜欢'), ('喜欢', '讨厌'), ('是', '不是'),
        ('会', '不会'), ('能', '不能'), ('有', '没有'),
        ('yes', 'no'), ('like', 'dislike'),
    }
    
    def detect_conflicts(self, new_memory: Memory, existing_memories: List[Memory]) -> List[MemoryConflict]:
        """检测新记忆与现有记忆的冲突"""
        conflicts = []
        for existing in existing_memories:
            if existing.lifecycle_stage in ['archived', 'deleted']:
                continue
            
            # 直接矛盾检测
            if self._is_direct_contradiction(new_memory, existing):
                conflicts.append(MemoryConflict(
                    conflict_type=ConflictType.DIRECT_CONTRADICTION,
                    memory_a_id=new_memory.id,
                    memory_b_id=existing.id,
                    conflict_description=f"直接矛盾: '{new_memory.content}' vs '{existing.content}'",
                    severity=self._calculate_severity(new_memory, existing),
                    confidence=0.9
                ))
            
            # 偏好冲突检测
            elif self._is_preference_conflict(new_memory, existing):
                conflicts.append(MemoryConflict(
                    conflict_type=ConflictType.PREFERENCE_CONFLICT,
                    memory_a_id=new_memory.id,
                    memory_b_id=existing.id,
                    conflict_description=f"偏好变化",
                    severity="low",
                    confidence=0.7
                ))
        
        return conflicts
```

#### 10.2.3 冲突消解策略

```python
class ConflictResolver:
    """冲突消解器"""
    
    def resolve_conflict(self, conflict: MemoryConflict, mem_a: Memory, mem_b: Memory):
        """根据冲突类型选择消解策略"""
        
        if conflict.conflict_type == ConflictType.DIRECT_CONTRADICTION:
            # 策略: 新覆盖旧 + 温度优先
            newer = max([mem_a, mem_b], key=lambda m: m.created_at)
            older = min([mem_a, mem_b], key=lambda m: m.created_at)
            
            temp_diff = abs(newer.temperature - older.temperature)
            if temp_diff > 20:
                winner = max([newer, older], key=lambda m: m.temperature)
            else:
                winner = newer
            
            # 标记旧记忆为失效
            older.is_archived = True
            older.metadata['superseded_by'] = winner.id
        
        elif conflict.conflict_type == ConflictType.PREFERENCE_CONFLICT:
            # 偏好会变化，保留两条记忆，标记时间有效性
            older = min([mem_a, mem_b], key=lambda m: m.created_at)
            newer = max([mem_a, mem_b], key=lambda m: m.created_at)
            older.metadata['preference_valid_until'] = newer.created_at.isoformat()
            newer.metadata['preference_current'] = True
```

### 10.3 睡眠-整理机制

```python
class MemorySleepProcessor:
    """
    记忆睡眠整理器
    定期执行记忆整理、模式发现、关联强化
    建议: 每日凌晨 2-4 点执行
    """
    
    def run_nightly_consolidation(self, agent_id: str):
        """
        夜间记忆整理流程:
        1. 合并相似记忆
        2. 提取模式/规律
        3. 强化重要关联
        4. 清理无用碎片
        5. 生成会话摘要
        """
        # 1. 合并相似记忆
        merge_count = self._merge_similar_memories(agent_id)
        
        # 2. 发现模式并生成洞察
        new_insights = self._discover_patterns(agent_id)
        
        # 3. 强化重要关联
        strengthened = self._strengthen_relations(agent_id)
        
        # 4. 清理碎片
        cleaned = self._clean_fragments(agent_id)
        
        # 5. 生成会话摘要
        summaries = self._generate_session_summaries(agent_id)
    
    def _merge_similar_memories(self, agent_id: str) -> int:
        """合并相似记忆 (详见 10.9 记忆合并机制)"""
        pass
    
    def _discover_patterns(self, agent_id: str) -> List[Memory]:
        """发现模式并生成洞察"""
        # 重复行为模式
        # 偏好演变模式
        # 时间规律模式
        # 情感模式
        pass
    
    def _clean_fragments(self, agent_id: str) -> int:
        """清理无用碎片记忆"""
        cursor = self.db.cursor()
        # 查找短小、低温、无关联、无情感的碎片记忆
        cursor.execute("""
            SELECT id FROM memories
            WHERE agent_id = ?
              AND lifecycle_stage IN ('secondary', 'archived')
              AND LENGTH(content) < 20
              AND temperature < 10
              AND is_important = 0
              AND is_crystallized = 0
              AND access_count < 2
              AND created_at < datetime('now', '-30 days')
        """, (agent_id,))
        
        fragment_ids = [row[0] for row in cursor.fetchall()]
        if fragment_ids:
            cursor.execute("""
                UPDATE memories SET lifecycle_stage = 'deleted'
                WHERE id IN ({})
            """.format(','.join(['?' for _ in fragment_ids])), fragment_ids)
            self.db.commit()
        
        return len(fragment_ids)
```

### 10.4 记忆联想能力

#### 10.4.1 记忆联想图

```python
class MemoryAssociationGraph:
    """
    记忆联想图
    基于共现、时间邻近、情感一致性建立联想边
    """
    
    def build_association_graph(self, agent_id: str):
        """构建记忆联想图"""
        # 1. 基于共现频率建立联想
        self._build_cooccurrence_associations(agent_id)
        # 2. 基于时间邻近性建立联想
        self._build_temporal_proximity_associations(agent_id)
        # 3. 基于情感一致性建立联想
        self._build_emotion_consistency_associations(agent_id)
    
    def get_associated_memories(self, memory_id: str, top_k: int = 5) -> List[Tuple[Memory, float]]:
        """获取与指定记忆关联的记忆"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT m.*, a.weight
            FROM memory_associations a
            JOIN memories m ON (
                (a.memory_a_id = ? AND m.id = a.memory_b_id) OR
                (a.memory_b_id = ? AND m.id = a.memory_a_id)
            )
            WHERE a.weight > 0.1
            ORDER BY a.weight DESC
            LIMIT ?
        """, (memory_id, memory_id, top_k))
        
        return [(self._row_to_memory(row), row[-1]) for row in cursor.fetchall()]
    
    def get_chain_association(self, memory_id: str, depth: int = 2) -> List[Memory]:
        """获取链式联想 (A→B→C)"""
        visited = {memory_id}
        current_level = [memory_id]
        result = []
        
        for _ in range(depth):
            next_level = []
            for mem_id in current_level:
                associated = self.get_associated_memories(mem_id, top_k=3)
                for mem, weight in associated:
                    if mem.id not in visited:
                        visited.add(mem.id)
                        result.append(mem)
                        next_level.append(mem.id)
            current_level = next_level
        
        return result
```

### 10.5 元认知能力

#### 10.5.1 记忆置信度计算

```python
class MemoryMetaCognition:
    """记忆元认知系统"""
    
    def calculate_confidence(self, memory: Memory) -> float:
        """
        计算记忆置信度 (0.0 - 1.0)
        
        因子:
        1. 温度权重 (30%)
        2. 访问次数 (20%)
        3. 内容完整度 (20%)
        4. 情感强度 (10%)
        5. 关联数量 (10%)
        6. 来源可靠性 (10%)
        """
        temp_factor = memory.temperature / 100.0
        access_factor = min(1.0, math.log10(max(1, memory.access_count)) / 2)
        content_factor = min(1.0, len(memory.content) / 200)
        emotion_factor = abs(memory.emotion_score)
        relation_count = self._get_relation_count(memory.id)
        relation_factor = min(1.0, relation_count / 10)
        
        perspective = memory.metadata.get('perspective', 'ai_inference')
        source_factor = {
            'user_statement': 0.9,
            'shared_experience': 0.8,
            'external_source': 0.7,
            'ai_inference': 0.5
        }.get(perspective, 0.5)
        
        confidence = (
            temp_factor * 0.30 +
            access_factor * 0.20 +
            content_factor * 0.20 +
            emotion_factor * 0.10 +
            relation_factor * 0.10 +
            source_factor * 0.10
        )
        
        return min(1.0, max(0.0, confidence))
    
    def generate_uncertainty_response(self, memory: Memory, query: str) -> str:
        """生成不确定性回复"""
        confidence = self.calculate_confidence(memory)
        
        if confidence >= 0.8:
            return f"我记得很清楚，{memory.content}"
        elif confidence >= 0.6:
            return f"我隐约记得{memory.content}，但不太确定"
        elif confidence >= 0.4:
            return f"我模糊记得你提过相关的事情，但细节不太清楚了"
        else:
            return f"抱歉，这件事我可能没有记住，能再告诉我一次吗？"
    
    def explain_why_remember(self, memory: Memory) -> str:
        """解释为什么记得这个记忆"""
        reasons = []
        if memory.access_count > 0:
            reasons.append(f"你提到过 {memory.access_count} 次")
        if memory.emotion_score > 0.7:
            reasons.append(f"你说的时候情绪很强烈")
        if memory.is_important:
            reasons.append("我把它标记为了重要记忆")
        if memory.is_crystallized:
            reasons.append("这是你的核心记忆之一")
        relation_count = self._get_relation_count(memory.id)
        if relation_count > 3:
            reasons.append(f"这和你的 {relation_count} 个其他记忆相关联")
        
        if reasons:
            return "我记得这个是因为: " + "，".join(reasons) + "。"
        return "我只是正常记录了这个信息。"
```

### 10.6 情感独立衰减机制

```python
class EmotionDecayEngine:
    """情感独立衰减引擎"""
    
    EMOTION_DECAY_RATES = {
        'joy': 0.03,        # 快乐衰减较慢
        'surprise': 0.05,   # 惊喜衰减中等
        'anger': 0.08,      # 愤怒衰减较快 (避免记仇)
        'fear': 0.06,       # 恐惧衰减较快
        'sadness': 0.04,    # 悲伤衰减较慢
        'disgust': 0.07,    # 厌恶衰减较快
        'neutral': 0.02,    # 中性几乎不衰减
    }
    
    def decay_emotions(self, memory: Memory, days_passed: int) -> Memory:
        """对记忆的情感进行衰减"""
        if days_passed <= 0 or not memory.emotion_tags:
            return memory
        
        for emotion_tag in memory.emotion_tags:
            decay_rate = self.EMOTION_DECAY_RATES.get(emotion_tag.value, 0.05)
            new_intensity = memory.emotion_score * math.exp(-decay_rate * days_passed)
            memory.emotion_score = max(0.0, new_intensity)
        
        return memory
```

### 10.7 记忆视角标记系统

```python
class MemoryPerspective(Enum):
    USER_STATEMENT = "user_statement"       # 用户明确说的
    AI_INFERENCE = "ai_inference"           # AI 推断的
    SHARED_EXPERIENCE = "shared_experience"  # 共同经历的
    EXTERNAL_SOURCE = "external_source"     # 外部获取的
    HYPOTHETICAL = "hypothetical"           # 假设/想象的

@dataclass
class Memory:
    # ... 原有字段 ...
    perspective: MemoryPerspective = MemoryPerspective.USER_STATEMENT
    perspective_confidence: float = 1.0
    source: Optional[str] = None
    inference_reasoning: Optional[str] = None

def format_memory_for_response(memory: Memory) -> str:
    """根据视角格式化记忆回复"""
    if memory.perspective == MemoryPerspective.USER_STATEMENT:
        return f"我记得你说过: {memory.content}"
    elif memory.perspective == MemoryPerspective.AI_INFERENCE:
        return f"我推测{memory.content}"
    elif memory.perspective == MemoryPerspective.SHARED_EXPERIENCE:
        return f"我们一起经历过: {memory.content}"
    elif memory.perspective == MemoryPerspective.EXTERNAL_SOURCE:
        return f"我从{memory.source}了解到: {memory.content}"
```

### 10.8 记忆可解释性追踪

```python
@dataclass
class MemoryProvenance:
    """记忆溯源信息"""
    memory_id: str
    origin: str
    original_content: str
    transformations: List[Dict]
    creation_context: Dict
    created_at: datetime
    created_by: str
    
    def get_explanation(self) -> str:
        """生成可解释性描述"""
        parts = [f"这条记忆来自{self.origin}"]
        parts.append(f"创建于{self.created_at.strftime('%Y-%m-%d %H:%M')}")
        parts.append(f"由{self.created_by}创建")
        if self.transformations:
            parts.append(f"经过了{len(self.transformations)}次更新")
        return "。".join(parts) + "。"
```

### 10.9 记忆合并机制

```python
class MemoryMerger:
    """记忆合并引擎"""
    
    def merge_similar_memories(self, agent_id: str) -> int:
        """
        合并相似记忆
        
        流程:
        1. 获取活跃记忆
        2. 计算相似度矩阵 (Jaccard/Cosine)
        3. 聚类相似记忆
        4. 对每个聚类生成摘要
        5. 创建合并记忆，标记原始记忆为已合并
        """
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, content, temperature, access_count
            FROM memories
            WHERE agent_id = ?
              AND lifecycle_stage = 'active'
              AND is_crystallized = 0
        """, (agent_id,))
        
        memories = cursor.fetchall()
        
        # 计算相似度矩阵
        similarity_matrix = self._calculate_similarity_matrix(memories)
        
        # 聚类 (连通分量)
        clusters = self._cluster_memories(similarity_matrix, threshold=0.7)
        
        merged_count = 0
        for cluster in clusters:
            if len(cluster) >= 2:
                self._merge_cluster(cluster)
                merged_count += len(cluster) - 1
        
        return merged_count
    
    def _calculate_similarity(self, text_a: str, text_b: str) -> float:
        """计算文本相似度 (Jaccard)"""
        words_a = set(jieba.lcut(text_a))
        words_b = set(jieba.lcut(text_b))
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union) if union else 0.0
    
    def _merge_cluster(self, memory_ids: List[str]):
        """合并一个聚类中的记忆"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, content, temperature, access_count
            FROM memories WHERE id IN ({})
        """.format(','.join(['?' for _ in memory_ids])), memory_ids)
        
        memories = cursor.fetchall()
        
        # 找到温度最高的记忆作为主记忆
        primary = max(memories, key=lambda m: m[2])
        primary_id = primary[0]
        
        # 生成合并摘要 (可调用 LLM)
        merged_content = self._generate_merge_summary([m[1] for m in memories])
        
        # 更新主记忆
        cursor.execute("""
            UPDATE memories
            SET content = ?,
                temperature = MAX(temperature, ?),
                access_count = access_count + ?,
                updated_at = CURRENT_TIMESTAMP,
                metadata = json_set(metadata, '$.merged_from', ?)
            WHERE id = ?
        """, (
            merged_content, primary[2],
            sum(m[3] for m in memories),
            json.dumps([m[0] for m in memories if m[0] != primary_id]),
            primary_id
        ))
        
        # 标记其他记忆为已合并
        other_ids = [m[0] for m in memories if m[0] != primary_id]
        if other_ids:
            cursor.execute("""
                UPDATE memories
                SET lifecycle_stage = 'archived',
                    is_archived = 1,
                    metadata = json_set(metadata, '$.merged_into', ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({})
            """.format(','.join(['?' for _ in other_ids])), [primary_id] + other_ids)
        
        self.db.commit()
```

### 10.10 智能增强调度器

```python
class IntelligenceScheduler:
    """智能增强调度器"""
    
    def start(self):
        """启动调度器"""
        # 1. 冲突检测: 每次写入后
        # 2. 睡眠整理: 每日凌晨 2:00
        # 3. 联想图更新: 每 6 小时
        # 4. 情感衰减: 每日一次
        # 5. 元认知更新: 实时
        pass
    
    def run_nightly_tasks(self):
        """夜间任务"""
        for agent_id in self._get_active_agents():
            self.sleep_processor.run_nightly_consolidation(agent_id)
            self.emotion_decay.run_daily_decay(agent_id)
```

### 10.11 智能增强监控指标

| 指标        | 说明         | 健康范围     |
| --------- | ---------- | -------- |
| **冲突检测率** | 每日新发现冲突数   | 5-20/天   |
| **冲突解决率** | 已解决冲突占比    | > 80%    |
| **记忆合并率** | 每日合并的记忆数   | 总记忆 1-3% |
| **模式发现数** | 每日发现的模式/洞察 | 1-5/天    |
| **联想图密度** | 平均每个记忆的关联数 | 3-10     |
| **情感衰减率** | 每日情感强度衰减比例 | 3-8%     |
| **平均置信度** | 所有记忆的平均置信度 | 0.6-0.8  |
| **记忆去重率** | 合并后减少的记忆比例 | 10-20%   |

### 10.12 智能增强配置示例

```yaml
# intelligence.yaml
intelligence:
  conflict_detection:
    enabled: true
    auto_resolve: true
    resolve_strategies: [recency, temperature_priority]
  
  sleep_consolidation:
    enabled: true
    run_at_hour: 2
    merge_similarity_threshold: 0.7
    pattern_discovery: true
    summary_generation: true
  
  association_graph:
    enabled: true
    update_interval_hours: 6
    min_weight_threshold: 0.1
    max_associations_per_memory: 20
  
  emotion_decay:
    enabled: true
    run_daily: true
    decay_rates:
      joy: 0.03
      anger: 0.08
      sadness: 0.04
  
  meta_cognition:
    enabled: true
    confidence_thresholds:
      high: 0.8
      medium: 0.6
      low: 0.4
  
  memory_merge:
    enabled: true
    min_similarity: 0.7
    min_cluster_size: 2
    use_llm_summary: true
    auto_merge: false
```

## 11. 完整记忆系统分层架构

### 11.1 系统全景图

记忆系统采用**四层分层架构**，从底层数据存储到顶层应用交互，逐层提供增强的记忆能力：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        应用层 (Application Layer)                            │
│                    Agent │ ContextBuilder │ 对话系统 │ 回复生成               │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ 请求/响应
┌────────────────────────────────▼────────────────────────────────────────────┐
│                     高级增强层 (Advanced Layer - Phase 2)                    │
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ 主动回忆机制  │  │ 情感共鸣引擎  │  │ 向量检索机制  │  │ 版本控制演进  │    │
│  │              │  │              │  │              │  │              │    │
│  │ ·上下文触发   │  │ ·Agent情感   │  │ ·语义嵌入    │  │ ·版本快照    │    │
│  │ ·定时回忆    │  │ ·情感共鸣    │  │ ·RRF混合检索 │  │ ·偏好演变    │    │
│  │ ·联想链式    │  │ ·回复风格    │  │ ·FAISS存储   │  │ ·版本回滚    │    │
│  │ ·任务驱动    │  │ ·情感演变    │  │ ·检索协调    │  │ ·冲突融合    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ 记忆压缩机制  │  │ 安全隐私控制  │  │ 时间感知模块  │  │ 社交图谱关联  │    │
│  │              │  │              │  │              │  │              │    │
│  │ ·层级压缩    │  │ ·敏感检测    │  │ ·模式识别    │  │ ·人物实体    │    │
│  │ ·语义压缩    │  │ ·AES加密     │  │ ·事件预测    │  │ ·关系边表    │    │
│  │ ·记忆聚合    │  │ ·被遗忘权    │  │ ·季节偏好    │  │ ·记忆关联    │    │
│  │ ·压缩触发    │  │ ·访问控制    │  │ ·时间检索    │  │ ·图谱索引    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ 增强查询/处理结果
┌────────────────────────────────▼────────────────────────────────────────────┐
│                     智能增强层 (Intelligence Layer - Phase 1)                 │
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ 冲突检测消解  │  │ 睡眠整理机制  │  │ 记忆联想图谱  │  │ 元认知能力   │    │
│  │              │  │              │  │              │  │              │    │
│  │ ·矛盾检测    │  │ ·记忆合并    │  │ ·共现关联    │  │ ·置信度计算  │    │
│  │ ·偏好冲突    │  │ ·模式发现    │  │ ·时间邻近    │  │ ·不确定性    │    │
│  │ ·消解策略    │  │ ·关联强化    │  │ ·情感一致    │  │ ·可解释性    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ 情感独立衰减  │  │ 记忆视角标记  │  │ 可解释性追踪  │  │ 记忆合并引擎  │    │
│  │              │  │              │  │              │  │              │    │
│  │ ·情感衰减    │  │ ·用户陈述    │  │ ·溯源信息    │  │ ·相似度计算  │    │
│  │ ·避免记仇    │  │ ·AI推断      │  │ ·变换历史    │  │ ·聚类摘要    │    │
│  │ ·独立衰减    │  │ ·共同经历    │  │ ·来源追踪    │  │ ·去重去冗余  │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ 基础记忆操作
┌────────────────────────────────▼────────────────────────────────────────────┐
│                       基础记忆层 (Core Layer)                                 │
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ 记忆管理器    │  │ 温度引擎      │  │ 读写缓存层    │  │ 数据库层      │    │
│  │              │  │              │  │              │  │              │    │
│  │ ·CRUD操作    │  │ ·温度计算    │  │ ·LRU缓存     │  │ ·SQLite主表  │    │
│  │ ·分类管理    │  │ ·升温/降温   │  │ ·256KB阈值   │  │ ·副表索引    │    │
│  │ ·搜索检索    │  │ ·生命周期    │  │ ·180s超时    │  │ ·FTS5全文检索│    │
│  │ ·索引维护    │  │ ·遗忘曲线    │  │ ·批量刷入    │  │ ·WAL模式     │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 11.2 各层职责详述

#### 11.2.1 基础记忆层（Core Layer）

记忆系统的**基础设施**，提供数据存储、检索、生命周期管理的核心能力。

| 组件 | 职责 | 关键技术 | 性能指标 |
|------|------|---------|---------|
| **记忆管理器** | 记忆CRUD、分类、搜索 | SQLite、LRU缓存 | 查询<5ms |
| **温度引擎** | 温度计算、生命周期管理 | 遗忘曲线、情感保护 | 衰减周期: 1小时 |
| **读写缓存层** | 批量写入、读取加速 | LRU、256KB/180s刷入 | 写入<0.1ms |
| **数据库层** | 持久化存储、索引维护 | SQLite、FTS5、WAL | 10万条<5ms |

#### 11.2.2 智能增强层（Intelligence Layer）

赋予记忆系统**类人认知能力**，使记忆具备智能处理、推理和演化能力。

| 组件 | 核心能力 | 触发时机 | 效果 |
|------|---------|---------|------|
| **冲突检测** | 识别矛盾记忆 | 每次写入后 | 避免自相矛盾 |
| **睡眠整理** | 记忆合并、模式发现 | 每日凌晨2:00 | 提炼洞察 |
| **联想图谱** | 记忆关联网络 | 每6小时更新 | 实现"突然想到" |
| **元认知** | 置信度计算 | 实时 | 知道"记得什么" |
| **情感衰减** | 情感独立衰减 | 每日一次 | 避免"记仇" |
| **记忆合并** | 相似记忆去重 | 睡眠整理期间 | 减少冗余10-20% |

#### 11.2.3 高级增强层（Advanced Layer）

让记忆系统具备**类人情感、主动回忆、语义理解**等高级能力。

| 模块 | 核心能力 | 应用场景 | 优先级 |
|------|---------|---------|--------|
| **主动回忆** | 上下文触发、定时回忆、联想链 | 用户说"天气"→想起"用户喜欢晴天" | 🔴 高 |
| **情感共鸣** | Agent情感状态、共鸣回复 | 用户难过→Agent表达关心 | 🔴 高 |
| **向量检索** | 语义相似度、混合检索 | "心情不好"→匹配"最近有点抑郁" | 🔴 高 |
| **版本控制** | 版本快照、演变追踪 | 偏好从"喜欢咖啡"→"讨厌咖啡" | 🔴 高 |
| **记忆压缩** | 层级压缩、聚合 | 100条对话→10条摘要→3个主题 | 🟡 中 |
| **安全隐私** | 敏感检测、加密 | 自动脱敏手机号、身份证号 | 🟡 中 |
| **时间感知** | 时间模式、事件预测 | "明天是纪念日"提醒 | 🟡 中 |
| **检索与上下文** | 类人认知检索、上下文注入 | 语义理解+主动回忆+置信度评估 | 🔴 高 |
| **社交图谱** | 人物关系图谱 | 人物关系强度变化追踪 | 🟢 低 |

### 11.3 完整数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│                          用户输入                                    │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 阶段1: 情感分析                                                       │
│   输入: 用户消息                                                      │
│   处理: 情感共鸣引擎 → 分析情感类型/强度                                │
│   输出: {emotion_type, intensity}                                     │
│   影响: Agent情感状态更新                                             │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 阶段2: 记忆检索                                                       │
│   输入: 用户消息 + 情感上下文                                          │
│   处理: 混合检索引擎                                                  │
│     ├─ 关键词检索 (倒排索引, <5ms)                                    │
│     ├─ 向量检索 (语义相似度, 50-100ms)                                │
│     ├─ 时间感知加权 (当前时段匹配)                                     │
│     └─ RRF融合 (关键词50% + 向量50%)                                  │
│   输出: Top-K 相关记忆列表                                            │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 阶段3: 主动回忆                                                       │
│   输入: 检索结果 + 当前上下文                                          │
│   处理: 主动回忆引擎                                                  │
│     ├─ 上下文触发回忆 (关键词/时间/情感)                               │
│     ├─ 联想链式回忆 (A→B→C, 最多3层)                                  │
│     └─ 任务驱动回忆 (相关经验/教训)                                    │
│   输出: 扩展回忆列表                                                  │
│   副作用: 回忆记忆温度提升                                            │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 阶段4: 冲突检测                                                       │
│   输入: 新记忆(如果有) + 现有记忆                                      │
│   处理: 版本感知冲突检测                                               │
│     ├─ 直接矛盾检测                                                   │
│     ├─ 偏好演变判断 (是否为正常变化)                                    │
│     └─ 版本快照创建 (如果冲突)                                         │
│   输出: 冲突列表 + 消解建议                                            │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 阶段5: 上下文构建                                                      │
│   输入: 检索记忆 + 回忆记忆                                            │
│   处理: 上下文构建引擎                                                  │
│     ├─ 记忆压缩 (层级压缩, 保留关键信息)                                │
│     ├─ 敏感信息过滤 (脱敏/加密)                                         │
│     ├─ 去重与排序 (温度加权)                                            │
│     └─ 情感风格调整 (根据共鸣结果)                                      │
│   输出: 压缩后的上下文 (<4000 tokens)                                   │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 阶段6: LLM调用                                                        │
│   输入: 系统提示 + 压缩上下文 + 用户消息                               │
│   处理: LLM推理                                                       │
│   输出: Agent回复                                                     │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 阶段7: 响应生成                                                       │
│   输入: LLM回复 + 情感共鸣结果                                         │
│   处理: 回复后处理                                                     │
│     ├─ 情感化修饰 (根据共鸣风格)                                        │
│     └─ 安全过滤 (敏感信息检查)                                         │
│   输出: 最终用户回复                                                   │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 阶段8: 记忆更新                                                       │
│   输入: 本轮对话内容                                                  │
│   处理: 记忆系统更新                                                   │
│     ├─ 存储新记忆 (温度初始化50°C)                                     │
│     ├─ 生成向量嵌入 (异步)                                            │
│     ├─ 创建版本快照                                                   │
│     ├─ 检测敏感信息                                                   │
│     ├─ 更新社交图谱 (如果涉及人物)                                     │
│     └─ 更新时间模式 (如果涉及时间)                                     │
│   副作用: 缓存写入 → 256KB/180s后批量刷入                              │
└─────────────────────────────────────────────────────────────────────┘
```

### 11.4 模块依赖关系图

```
                    ┌──────────────┐
                    │   应用层      │
                    │  (Agent等)   │
                    └──────┬───────┘
                           │ 调用
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │  主动回忆     │ │  情感共鸣     │ │  向量检索     │
    └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
           │                │                │
           ▼                ▼                ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │  版本控制     │ │  时间感知     │ │  记忆压缩     │
    └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
           │                │                │
           ▼                ▼                ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │  安全隐私     │ │  社交图谱     │ │  冲突检测     │
    └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
           │                │                │
           └────────────────┼────────────────┘
                            ▼
                    ┌──────────────┐
                    │  记忆管理器   │
                    └──────┬───────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │  温度引擎     │ │  缓存层       │ │  数据库层     │
    └──────────────┘ └──────────────┘ └──────────────┘
```

依赖说明:

- **核心依赖**（必须）: 记忆管理器、温度引擎、缓存层、数据库层
- **一级依赖**（建议启用）: 冲突检测、联想图谱、情感衰减、元认知、**检索与上下文注入**
- **二级依赖**（按需启用）: 主动回忆、情感共鸣、向量检索、版本控制、语义理解层、混合检索层
- **三级依赖**（按需启用）: 记忆压缩、安全隐私、时间感知、社交图谱

### 11.5 记忆系统完整能力矩阵

| 能力维度 | 基础功能 | 温度机制 | 智能增强 | 高级模块 |
|---------|---------|---------|---------|---------|
| **记忆存储** | ✅ 短期/长期/情感 | ✅ 温度属性 | ✅ 视角标记 | ✅ 版本快照、加密 |
| **记忆检索** | ✅ 关键词搜索 | ✅ 温度加权 | ✅ 联想扩展 | ✅ 向量检索、时间加权 |
| **记忆更新** | ✅ 内容更新 | ✅ 温度计算 | ✅ 冲突消解 | ✅ 版本控制、演变追踪 |
| **记忆删除** | ✅ 过期清理 | ✅ 生命周期管理 | ✅ 遗忘恢复 | ✅ 隐私删除、软删除 |
| **记忆分类** | ✅ 11种分类 | ✅ 分类温度特征 | ✅ 分类合并 | ✅ 分类压缩 |
| **情感处理** | ✅ 情感标签 | ✅ 情感保护 | ✅ 情感衰减 | ✅ Agent情感、共鸣 |
| **时间处理** | ✅ 时间戳 | ✅ 时间衰减 | ✅ 时间冲突 | ✅ 模式识别、预测 |
| **关系处理** | ✅ 基础关联 | ✅ 关联保护 | ✅ 联想图谱 | ✅ 社交图谱 |
| **安全隐私** | ❌ | ❌ | ❌ | ✅ 敏感检测、加密 |
| **记忆压缩** | ❌ | ❌ | ✅ 基础合并 | ✅ 层级压缩、聚合 |
| **主动回忆** | ❌ | ❌ | ❌ | ✅ 触发回忆、定时回忆 |

### 11.6 模块文档索引

| 模块 | 架构文档 | 状态 |
|------|---------|------|
| 基础记忆系统 | [02-memory-system.md](file:///e:/项目/Neurova/docs/architecture/02-memory-system.md) | ✅ 已完成 |
| 上下文处理 | [09-context-processing.md](file:///e:/项目/Neurova/docs/architecture/09-context-processing.md) | ✅ 已完成 |
| 缓存机制 | [10-cache-mechanism.md](file:///e:/项目/Neurova/docs/architecture/10-cache-mechanism.md) | ✅ 已完成 |
| 数据库架构 | [11-database-architecture.md](file:///e:/项目/Neurova/docs/architecture/11-database-architecture.md) | ✅ 已完成 |
| 记忆温度 | [12-memory-temperature-mechanism.md](file:///e:/项目/Neurova/docs/architecture/12-memory-temperature-mechanism.md) | ✅ 已完成 |
| 智能增强 | [13-memory-intelligence-enhancements.md](file:///e:/项目/Neurova/docs/architecture/13-memory-intelligence-enhancements.md) | ✅ 已完成 |
| 主动回忆 | [14-proactive-recall-mechanism.md](file:///e:/项目/Neurova/docs/architecture/14-proactive-recall-mechanism.md) | ✅ 新增 |
| 版本控制 | [14a-version-control-evolution.md](file:///e:/项目/Neurova/docs/architecture/14a-version-control-evolution.md) | ✅ 新增 |
| 情感共鸣 | [15-emotion-resonance-engine.md](file:///e:/项目/Neurova/docs/architecture/15-emotion-resonance-engine.md) | ✅ 新增 |
| 向量检索 | [16-vector-retrieval-system.md](file:///e:/项目/Neurova/docs/architecture/16-vector-retrieval-system.md) | ✅ 新增 |
| 记忆压缩 | [17-memory-compression-mechanism.md](file:///e:/项目/Neurova/docs/architecture/17-memory-compression-mechanism.md) | ✅ 新增 |
| 安全隐私 | [18-memory-security-privacy.md](file:///e:/项目/Neurova/docs/architecture/18-memory-security-privacy.md) | ✅ 新增 |
| 时间感知 | [19-time-awareness-mechanism.md](file:///e:/项目/Neurova/docs/architecture/19-time-awareness-mechanism.md) | ✅ 新增 |
| 检索与上下文 | [20-retrieval-context-injection.md](file:///e:/项目/Neurova/docs/architecture/20-retrieval-context-injection.md) | ✅ 新增 |

### 11.7 完整配置总览

```yaml
# memory_system.yaml - 完整记忆系统配置
memory_system:
  # ============================================================
  # 基础配置
  # ============================================================
  database:
    type: sqlite
    path: data/memory.db
    wal_mode: true
    cache_size: 8000
    foreign_keys: true
  
  cache:
    write_threshold_kb: 256
    write_timeout_seconds: 180
    max_short_term_cache: 100
    read_cache_ttl: 300
  
  # ============================================================
  # 温度机制
  # ============================================================
  temperature:
    default_temperature: 50.0
    hit_boost_base: 5.0
    emotion_protection_factor: 0.6
    relation_protection_factor: 0.7
    decay_rate_base: 0.05
    
    lifecycle_thresholds:
      active: { min_temperature: 50.0, max_idle_days: 7 }
      secondary: { min_temperature: 20.0, max_idle_days: 30 }
      archived: { min_temperature: 5.0, max_idle_days: 60 }
    
    important_upgrade:
      min_temperature: 80.0
      min_access_count: 10
      min_emotion_score: 0.8
    
    crystallization:
      min_temperature: 90.0
      min_emotion_score: 0.9
      special_keywords: [纪念日, 生日, 结婚, anniversary, birthday]
  
  # ============================================================
  # 智能增强 (Phase 1)
  # ============================================================
  intelligence:
    conflict_detection:
      enabled: true
      auto_resolve: true
      strategies: [recency, temperature_priority]
    
    sleep_consolidation:
      enabled: true
      run_at_hour: 2
      merge_similarity_threshold: 0.7
      pattern_discovery: true
    
    association_graph:
      enabled: true
      update_interval_hours: 6
      min_weight_threshold: 0.1
      max_associations_per_memory: 20
    
    emotion_decay:
      enabled: true
      run_daily: true
      decay_rates:
        joy: 0.03
        anger: 0.08
        sadness: 0.04
    
    meta_cognition:
      enabled: true
      confidence_thresholds: { high: 0.8, medium: 0.6, low: 0.4 }
    
    memory_merge:
      enabled: true
      min_similarity: 0.7
      use_llm_summary: true
  
  # ============================================================
  # 高级模块 (Phase 2)
  # ============================================================
  advanced:
    # 主动回忆
    proactive_recall:
      enabled: true
      max_recall_count: 10
      min_relevance_score: 0.3
      max_chain_depth: 3
      max_branches: 3
      scheduled_interval_hours: 6
    
    # 情感共鸣
    emotion_resonance:
      enabled: true
      empathy_coefficient: 0.6
      max_emotions: 5
      history_length: 100
      baseline_update_interval: 86400
    
    # 向量检索
    vector_retrieval:
      enabled: true
      embedding_model:
        type: local
        model: "all-MiniLM-L6-v2"
      vector_store: json
      hybrid_search:
        keyword_weight: 0.5
        vector_weight: 0.5
        rrf_k: 60
      batch:
        size: 100
        interval_seconds: 300
    
    # 版本控制
    version_control:
      enabled: true
      max_versions_per_memory: 10
      retention:
        cleanup_interval_days: 30
        keep_important_versions: true
      rollback:
        enabled: true
        require_confirmation: true
        max_rollback_depth: 5
    
    # 记忆压缩
    compression:
      enabled: true
      hierarchical:
        time_threshold_days: 30
        count_threshold: 100
        target_ratio: 0.1
      semantic:
        min_similarity: 0.7
        max_summary_length: 500
      triggers:
        time_interval_hours: 24
        memory_count_threshold: 1000
        storage_size_threshold_mb: 100
    
    # 安全隐私
    security:
      enabled: true
      sensitive_detection:
        auto_detect: true
        reject_critical: true
        categories: [id_card, phone, email, bank_card, password, api_key]
      encryption:
        enabled: true
        algorithm: AES-256-GCM
      privacy:
        user_deletion:
          enabled: true
          soft_delete: true
          retention_days: 30
        data_export:
          enabled: true
          format: json
    
    # 时间感知
    time_awareness:
      enabled: true
      pattern_detection:
        min_occurrences: 3
        confidence_threshold: 0.7
      event_prediction:
        days_ahead: 7
        advance_reminder_hours: 24
      seasonal_preferences:
        enabled: true
        categories: [food, activity, clothing]
      retrieval:
        time_weight: 0.3
    
    # 社交图谱
    social_graph:
      enabled: true
      entity_types: [person, group, organization, pet]
      relationship_types: [family, friend, colleague, mentor, partner, acquaintance]
      max_relationships_per_entity: 50
    
    # 检索与上下文注入
    retrieval_context_injection:
      enabled: true
      semantic_understanding:
        emotion_threshold: 0.3
        intent_patterns:
          complaint: ['不好', '太差', '烦', '郁闷']
          question: ['为什么', '怎么', '如何']
      
      hybrid_retrieval:
        weights:
          keyword: 0.30
          vector: 0.35
          time_aware: 0.15
          emotion: 0.15
          social: 0.05
        rrf_k: 60
        top_k: 20
      
      proactive_recall:
        max_chain_depth: 3
        max_branches: 3
        association_threshold: 0.3
        max_expanded: 30
      
      memory_understanding:
        confidence_thresholds:
          high: 0.8
          medium: 0.5
          low: 0.0
        conflict_penalty: 0.3
        crystallized_bonus: 0.2
      
      context_builder:
        max_tokens: 4000
        show_temperature: true
        show_confidence: true
        show_conflicts: true
        show_empathy: true
```

## 12. 进阶增强机制 (Phase 3)

### 12.1 高级优先级增强模块

#### 12.1.1 记忆意图图谱 (Memory Intent Graph)

```python
class MemoryIntentGraph:
    """
    记忆意图图谱
    不仅知道"做了什么"，更理解"为什么做"、"想要什么"
    
    意图类别:
    - information_seeking: 寻求信息
    - emotional_support: 情感支持
    - task_completion: 任务完成
    - social_interaction: 社交互动
    - creative_brainstorming: 创意脑暴
    """
    
    def build_intent_graph(self, agent_id: str):
        """构建用户意图图谱"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT m.id, m.content, m.category, m.emotion_score,
                   s.title as session_title
            FROM memories m
            LEFT JOIN session_messages sm ON m.id = sm.metadata
            LEFT JOIN sessions s ON sm.session_id = s.id
            WHERE m.agent_id = ?
              AND m.lifecycle_stage = 'active'
        """, (agent_id,))
        
        memories = cursor.fetchall()
        
        for memory in memories:
            intent = self._classify_intent(memory.content, memory.emotion_score)
            self._link_memory_to_intent(memory.id, intent)
        
        self._discover_intent_patterns(agent_id)
    
    def _classify_intent(self, content: str, emotion_score: float) -> str:
        """分类记忆意图"""
        question_keywords = ['怎么', '如何', '为什么', '是什么', 'where', 'how', 'what']
        emotional_keywords = ['难过', '开心', '烦', '焦虑', 'sad', 'happy', 'anxious']
        task_keywords = ['完成', '任务', '目标', 'deadline', 'finish', 'complete']
        creative_keywords = ['想法', '灵感', '创意', 'idea', 'brainstorm', 'maybe']
        
        for keyword in question_keywords:
            if keyword in content.lower():
                return 'information_seeking'
        
        if emotion_score > 0.6:
            for keyword in emotional_keywords:
                if keyword in content.lower():
                    return 'emotional_support'
        
        for keyword in task_keywords:
            if keyword in content.lower():
                return 'task_completion'
        
        for keyword in creative_keywords:
            if keyword in content.lower():
                return 'creative_brainstorming'
        
        return 'social_interaction'
    
    def predict_next_intent(self, recent_memories: List[Memory]) -> Dict:
        """基于历史意图模式预测下一步意图"""
        recent_intents = [self._classify_intent(m.content, m.emotion_score) for m in recent_memories]
        
        intent_sequences = self._get_historical_sequences(recent_intents)
        
        most_likely_next = Counter([
            seq[-1] for seq in intent_sequences
            if seq[:-1] == recent_intents[-3:]
        ]).most_common(1)
        
        if most_likely_next:
            return {
                'predicted_intent': most_likely_next[0][0],
                'confidence': most_likely_next[0][1] / len(intent_sequences),
                'suggested_preparation': self._get_intent_preparation(most_likely_next[0][0])
            }
        
        return {'predicted_intent': None, 'confidence': 0.0}
    
    def get_intent_behavior_patterns(self, intent_type: str, agent_id: str) -> List[Dict]:
        """获取某类意图下的行为模式"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT 
                m.category,
                COUNT(*) as occurrence_count,
                AVG(m.emotion_score) as avg_emotion,
                AVG(m.temperature) as avg_temperature,
                GROUP_CONCAT(DISTINCT m.content) as sample_contents
            FROM memories m
            WHERE m.agent_id = ?
              AND m.intent_type = ?
            GROUP BY m.category
            ORDER BY occurrence_count DESC
            LIMIT 10
        """, (agent_id, intent_type))
        
        patterns = []
        for row in cursor.fetchall():
            patterns.append({
                'category': row[0],
                'occurrences': row[1],
                'avg_emotion': row[2],
                'avg_temperature': row[3],
                'samples': row[4].split(',')[:3]
            })
        
        return patterns
```

#### 12.1.2 记忆反馈闭环 (Memory Feedback Loop)

```python
class MemoryFeedbackLoop:
    """
    记忆反馈闭环
    验证记忆有效性，持续优化检索准确率
    
    反馈信号来源:
    1. 显式反馈: 用户直接评价
    2. 隐式反馈: 行为分析
    3. 对话延续: 用户是否追问
    """
    
    def collect_feedback(self, agent_id: str, query: str, retrieved_memories: List[Memory], response: str) -> Dict:
        """收集记忆反馈"""
        feedback = {
            'query': query,
            'retrieved_ids': [m.id for m in retrieved_memories],
            'timestamp': datetime.now(),
            'metrics': {}
        }
        
        feedback['metrics']['retrieval_precision'] = self._calculate_precision(query, retrieved_memories)
        feedback['metrics']['response_quality'] = self._estimate_response_quality(response)
        
        return feedback
    
    def analyze_feedback_trends(self, agent_id: str, window_days: int = 7) -> Dict:
        """分析反馈趋势"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT 
                DATE(timestamp) as date,
                AVG(retrieval_precision) as avg_precision,
                AVG(response_quality) as avg_quality,
                COUNT(*) as query_count
            FROM memory_feedback
            WHERE agent_id = ?
              AND timestamp > datetime('now', ?)
            GROUP BY DATE(timestamp)
            ORDER BY date DESC
        """, (agent_id, f'-{window_days} days'))
        
        trends = []
        for row in cursor.fetchall():
            trends.append({
                'date': row[0],
                'avg_precision': row[1],
                'avg_quality': row[2],
                'query_count': row[3]
            })
        
        return {
            'trends': trends,
            'overall_precision': sum(t['avg_precision'] for t in trends) / len(trends) if trends else 0,
            'overall_quality': sum(t['avg_quality'] for t in trends) / len(trends) if trends else 0,
            'total_queries': sum(t['query_count'] for t in trends)
        }
    
    def adjust_retrieval_strategy(self, feedback_analysis: Dict) -> Dict:
        """根据反馈调整检索策略"""
        adjustments = {}
        
        if feedback_analysis['overall_precision'] < 0.6:
            adjustments['vector_weight'] = '+0.1'
            adjustments['keyword_weight'] = '-0.1'
        
        if feedback_analysis['overall_quality'] < 0.5:
            adjustments['context_tokens'] = '+500'
            adjustments['proactive_recall'] = 'enabled'
        
        return adjustments
    
    def create_feedback_database(self):
        """创建反馈数据库表"""
        return """
            CREATE TABLE memory_feedback (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                query TEXT NOT NULL,
                retrieved_ids TEXT NOT NULL,
                retrieval_precision REAL,
                response_quality REAL,
                user_satisfaction INTEGER CHECK(user_satisfaction >= 1 AND user_satisfaction <= 5),
                implicit_signals TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES sessions(agent_id)
            );
            
            CREATE INDEX idx_feedback_agent_date ON memory_feedback(agent_id, timestamp DESC);
            CREATE INDEX idx_feedback_precision ON memory_feedback(retrieval_precision);
        """
```

#### 12.1.3 个性化记忆策略 (Personalized Memory Strategy)

```python
class PersonalizedMemoryStrategy:
    """
    个性化记忆策略
    根据用户特点调整记忆系统行为
    
    学习维度:
    1. 沟通风格偏好 (正式/随意/幽默/严肃)
    2. 回复长度偏好 (简短/中等/详细)
    3. 情感表达偏好 (高情感/低情感)
    4. 信息密度偏好 (高密度/低密度)
    5. 交互频率偏好 (高频/低频)
    """
    
    def learn_user_preferences(self, agent_id: str) -> Dict:
        """学习用户偏好"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT 
                metadata,
                emotion_score,
                LENGTH(content) as response_length,
                created_at
            FROM memories
            WHERE agent_id = ?
              AND category IN ('conversation', 'interaction')
            ORDER BY created_at DESC
            LIMIT 1000
        """, (agent_id,))
        
        memories = cursor.fetchall()
        
        preferences = {
            'communication_style': self._infer_communication_style(memories),
            'response_length': self._infer_response_length(memories),
            'emotional_tone': self._infer_emotional_tone(memories),
            'detail_level': self._infer_detail_level(memories),
            'interaction_frequency': self._infer_interaction_frequency(memories)
        }
        
        return preferences
    
    def apply_personalization(self, preferences: Dict) -> Dict:
        """应用个性化设置到记忆系统"""
        config = {}
        
        if preferences['communication_style'] == 'casual':
            config['context_tone'] = 'informal'
            config['response_style'] = 'conversational'
        
        if preferences['response_length'] == 'short':
            config['max_context_tokens'] = 2000
            config['summary_length'] = 'brief'
        elif preferences['response_length'] == 'detailed':
            config['max_context_tokens'] = 6000
            config['summary_length'] = 'comprehensive'
        
        if preferences['emotional_tone'] == 'high':
            config['emotion_resonance_enabled'] = True
            config['empathy_coefficient'] = 0.8
        else:
            config['emotion_resonance_enabled'] = False
            config['empathy_coefficient'] = 0.3
        
        return config
    
    def _infer_communication_style(self, memories: List) -> str:
        """推断沟通风格"""
        formal_keywords = ['请', '谢谢', '您好', '请问', '感谢']
        casual_keywords = ['哈哈', '嗯', '好的', '哦', '呀']
        
        formal_count = 0
        casual_count = 0
        
        for mem in memories:
            content = mem[0].lower() if mem[0] else ''
            for keyword in formal_keywords:
                formal_count += content.count(keyword)
            for keyword in casual_keywords:
                casual_count += content.count(keyword)
        
        if formal_count > casual_count * 1.5:
            return 'formal'
        elif casual_count > formal_count * 1.5:
            return 'casual'
        return 'balanced'
```

### 12.2 中级优先级增强模块

#### 12.2.1 梦境整理机制 (Dream Consolidation)

```python
class DreamConsolidationEngine:
    """
    梦境整理机制
    模拟人类睡眠时的记忆整理和创意连接
    
    触发时机: 系统空闲期或定时任务
    处理内容:
    1. 跨领域连接: 发现不同类别记忆间的隐含联系
    2. 抽象提炼: 从具体记忆中提取普遍规律
    3. 创意孵化: 组合看似无关的记忆产生新想法
    4. 情感整合: 统一情感记忆的认知
    """
    
    def run_dream_session(self, agent_id: str) -> Dict:
        """执行一次梦境整理"""
        results = {
            'cross_domain_links': 0,
            'abstract_insights': 0,
            'creative_ideas': 0,
            'emotional_integrations': 0
        }
        
        results['cross_domain_links'] = self._discover_cross_domain_links(agent_id)
        results['abstract_insights'] = self._extract_abstract_insights(agent_id)
        results['creative_ideas'] = self._generate_creative_combinations(agent_id)
        results['emotional_integrations'] = self._integrate_emotional_memories(agent_id)
        
        return results
    
    def _discover_cross_domain_links(self, agent_id: str) -> int:
        """发现跨领域连接"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT category, COUNT(*) as count, GROUP_CONCAT(id) as ids
            FROM memories
            WHERE agent_id = ? AND lifecycle_stage = 'active'
            GROUP BY category
            HAVING count > 3
        """, (agent_id,))
        
        categories = cursor.fetchall()
        new_links = 0
        
        for i, cat_a in enumerate(categories):
            for cat_b in categories[i+1:]:
                links = self._find_semantic_connections(cat_a[2].split(','), cat_b[2].split(','))
                new_links += len(links)
                
                for link in links:
                    self._create_cross_domain_link(link['source'], link['target'], link['relation'])
        
        return new_links
    
    def _generate_creative_combinations(self, agent_id: str) -> int:
        """生成创意组合"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, content, category
            FROM memories
            WHERE agent_id = ?
              AND category IN ('creative', 'idea', 'experience')
              AND temperature > 30
            ORDER BY temperature DESC
            LIMIT 20
        """, (agent_id,))
        
        memories = cursor.fetchall()
        new_ideas = 0
        
        for i, mem_a in enumerate(memories):
            for mem_b in memories[i+1:]:
                if self._is_creative_combination_possible(mem_a, mem_b):
                    new_idea = self._generate_creative_idea(mem_a, mem_b)
                    self._store_new_idea(new_idea, agent_id)
                    new_ideas += 1
        
        return new_ideas
    
    def _integrate_emotional_memories(self, agent_id: str) -> int:
        """整合情感记忆"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, content, emotion_score, emotion_tags
            FROM memories
            WHERE agent_id = ?
              AND emotion_score > 0.7
              AND lifecycle_stage = 'active'
            ORDER BY created_at DESC
            LIMIT 50
        """, (agent_id,))
        
        emotional_memories = cursor.fetchall()
        integrations = 0
        
        emotion_clusters = self._cluster_by_emotion(emotional_memories)
        for cluster in emotion_clusters:
            if len(cluster) >= 3:
                integrated = self._synthesize_emotional_narrative(cluster)
                self._store_integrated_emotion(integrated, agent_id)
                integrations += 1
        
        return integrations
```

#### 12.2.2 情感调节机制 (Emotion Regulation)

```python
class EmotionRegulationEngine:
    """
    情感调节引擎
    模拟人类情感自我调节能力
    
    触发条件:
    1. 连续负面情绪超过阈值
    2. 情感强度极端 (>0.9 或 <0.1)
    3. 单一情感持续过久
    """
    
    def regulate_emotion_state(self, agent_id: str) -> Dict:
        """定期执行情感调节"""
        current_emotion = self._get_current_emotion(agent_id)
        
        if self._is_negative_accumulation(current_emotion):
            regulation = self._neutralize_negative(current_emotion)
            self._apply_regulation(agent_id, regulation)
        
        if self._is_extreme_emotion(current_emotion):
            regulation = self._moderate_extreme(current_emotion)
            self._apply_regulation(agent_id, regulation)
        
        if self._is_stale_emotion(current_emotion):
            regulation = self._refresh_stale_emotion(current_emotion)
            self._apply_regulation(agent_id, regulation)
        
        return self._get_regulated_emotion(agent_id)
    
    def _neutralize_negative(self, emotion_state: Dict) -> Dict:
        """负面情感中和"""
        negative_emotions = ['sadness', 'anger', 'fear', 'disgust']
        total_negative = sum(emotion_state.get(e, 0) for e in negative_emotions)
        
        if total_negative > 0.7:
            positive_memories = self._retrieve_positive_memories(
                emotion_state['agent_id'], top_k=5
            )
            
            return {
                'action': 'neutralize',
                'method': 'positive_memory_injection',
                'memories': [m.id for m in positive_memories],
                'target_reduction': 0.3
            }
        return None
    
    def _moderate_extreme(self, emotion_state: Dict) -> Dict:
        """极端情感调节"""
        for emotion, intensity in emotion_state.items():
            if intensity > 0.9:
                return {
                    'action': 'moderate',
                    'emotion': emotion,
                    'target_intensity': intensity * 0.7,
                    'method': 'cognitive_reappraisal'
                }
            elif intensity < 0.1 and emotion != 'neutral':
                return {
                    'action': 'amplify',
                    'emotion': emotion,
                    'target_intensity': intensity * 1.5,
                    'method': 'emotion_recognition'
                }
        return None
    
    def _refresh_stale_emotion(self, emotion_state: Dict) -> Dict:
        """情感僵化刷新"""
        dominant_emotion = max(emotion_state.items(), key=lambda x: x[1])
        
        if dominant_emotion[1] > 0.6:
            duration = self._get_emotion_duration(emotion_state['agent_id'], dominant_emotion[0])
            
            if duration > 7:
                return {
                    'action': 'refresh',
                    'current_emotion': dominant_emotion[0],
                    'duration_days': duration,
                    'method': 'emotion_diversity_injection',
                    'target': 'introduce_variety'
                }
        return None
    
    def _retrieve_positive_memories(self, agent_id: str, top_k: int = 5) -> List[Memory]:
        """检索积极记忆用于情感调节"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, content, emotion_score, temperature
            FROM memories
            WHERE agent_id = ?
              AND emotion_score > 0.5
              AND lifecycle_stage = 'active'
            ORDER BY emotion_score DESC, temperature DESC
            LIMIT ?
        """, (agent_id, top_k))
        
        return [self._row_to_memory(row) for row in cursor.fetchall()]
```

#### 12.2.3 多粒度检索 (Multi-Granularity Retrieval)

```python
class MultiGranularityRetrieval:
    """
    多粒度记忆检索
    根据查询复杂度动态调整检索粒度
    
    粒度级别:
    1. 原子级: 单条记忆，精确匹配
    2. 会话级: 相关会话片段
    3. 主题级: 话题聚类摘要
    4. 模式级: 长期行为模式
    """
    
    def retrieve_with_granularity(self, query: str, analysis: SemanticAnalysis) -> Dict:
        """智能选择检索粒度"""
        granularity = self._determine_granularity(query, analysis)
        
        if granularity == 'atomic':
            return self._atomic_retrieval(query, analysis)
        elif granularity == 'session':
            return self._session_retrieval(query, analysis)
        elif granularity == 'topic':
            return self._topic_retrieval(query, analysis)
        else:
            return self._pattern_retrieval(query, analysis)
    
    def _determine_granularity(self, query: str, analysis: SemanticAnalysis) -> str:
        """判断检索粒度"""
        if analysis.intent_type == 'fact_query':
            return 'atomic'
        if analysis.intent_type == 'conversation_history':
            return 'session'
        if analysis.intent_type in ['topic_discussion', 'summary_request']:
            return 'topic'
        if analysis.intent_type in ['pattern_query', 'habit_query']:
            return 'pattern'
        
        if len(query) < 10:
            return 'atomic'
        elif len(query) < 30:
            return 'session'
        else:
            return 'topic'
    
    def _topic_retrieval(self, query: str, analysis: SemanticAnalysis) -> Dict:
        """主题级检索 - 返回话题聚类摘要"""
        topics = self._identify_topics(query, analysis)
        
        topic_summaries = []
        for topic in topics:
            summary = self._get_topic_summary(topic, analysis.agent_id)
            topic_summaries.append(summary)
        
        return {
            'granularity': 'topic',
            'topics': topic_summaries,
            'total_memories': sum(s['memory_count'] for s in topic_summaries)
        }
    
    def _pattern_retrieval(self, query: str, analysis: SemanticAnalysis) -> Dict:
        """模式级检索 - 返回行为模式"""
        patterns = self._identify_patterns(query, analysis)
        
        return {
            'granularity': 'pattern',
            'patterns': [
                {
                    'pattern_type': p.type,
                    'description': p.description,
                    'confidence': p.confidence,
                    'supporting_memories': p.memory_ids[:5],
                    'occurrences': p.occurrences
                }
                for p in patterns
            ]
        }
```

#### 12.2.4 记忆遗忘策略优化 (Forgetting Strategy)

```python
class AdvancedForgettingStrategy:
    """
    高级遗忘策略
    超越简单的时间衰减，实现智能遗忘
    
    因子:
    1. 时间衰减 (基础)
    2. 使用频率
    3. 情感强度
    4. 关联密度
    5. 信息冗余度
    6. 可替代性
    """
    
    def calculate_forgetting_probability(self, memory: Memory) -> float:
        """计算记忆遗忘概率"""
        time_decay = self._time_decay_factor(memory)
        usage_protection = self._usage_protection_factor(memory)
        emotion_protection = self._emotion_protection_factor(memory)
        association_protection = self._association_protection_factor(memory)
        redundancy_penalty = self._redundancy_penalty(memory)
        replaceability_penalty = self._replaceability_penalty(memory)
        
        forgetting_prob = (
            time_decay * 
            (1 - usage_protection * 0.3) *
            (1 - emotion_protection * 0.2) *
            (1 - association_protection * 0.2) *
            (1 + redundancy_penalty * 0.15) *
            (1 + replaceability_penalty * 0.15)
        )
        
        return min(1.0, max(0.0, forgetting_prob))
    
    def _redundancy_penalty(self, memory: Memory) -> float:
        """计算信息冗余惩罚"""
        similar_count = self._count_similar_memories(memory)
        
        if similar_count == 0:
            return 0.0
        elif similar_count <= 2:
            return 0.1
        elif similar_count <= 5:
            return 0.3
        else:
            return 0.5
    
    def _replaceability_penalty(self, memory: Memory) -> float:
        """计算可替代性惩罚"""
        if self._is_common_knowledge(memory):
            return 0.4
        if memory.category == MemoryCategory.PROFILE:
            return 0.0
        if memory.emotion_score > 0.7:
            return 0.0
        if memory.category in [MemoryCategory.EXPERIENCE, MemoryCategory.LESSON]:
            return 0.2
        return 0.3
    
    def execute_selective_forgetting(self, agent_id: str) -> int:
        """执行选择性遗忘"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, content, temperature, access_count, 
                   emotion_score, lifecycle_stage
            FROM memories
            WHERE agent_id = ?
              AND is_crystallized = 0
              AND is_important = 0
              AND lifecycle_stage IN ('secondary', 'archived')
        """, (agent_id,))
        
        forgotten_count = 0
        for row in cursor.fetchall():
            memory = self._row_to_memory(row)
            prob = self.calculate_forgetting_probability(memory)
            
            if prob > 0.7:
                self._execute_forgetting(memory)
                forgotten_count += 1
        
        return forgotten_count
```

### 12.3 低级优先级增强模块

#### 12.3.1 既视感检测 (Déjà Vu Detection)

```python
class DejaVuDetector:
    """
    既视感检测器
    检测"似曾相识"的体验，触发深度回忆
    
    触发条件:
    1. 当前场景与历史记忆高度相似
    2. 但用户未明确提及该记忆
    3. 时间/地点/人物存在重叠
    """
    
    def detect_deja_vu(self, current_context: Dict, agent_id: str) -> Optional[Dict]:
        """检测既视感"""
        current_features = self._extract_scene_features(current_context)
        
        similar_scenes = self._search_similar_scenes(
            current_features, agent_id, similarity_threshold=0.75
        )
        
        if not similar_scenes:
            return None
        
        deja_vu_strength = self._calculate_deja_vu_strength(current_features, similar_scenes[0])
        
        if deja_vu_strength < 0.6:
            return None
        
        return {
            'detected': True,
            'strength': deja_vu_strength,
            'trigger_memory': similar_scenes[0],
            'similarity_aspects': self._compare_features(current_features, similar_scenes[0]),
            'suggested_action': self._suggest_deja_vu_action(deja_vu_strength, similar_scenes[0])
        }
    
    def _suggest_deja_vu_action(self, strength: float, trigger_memory: Memory) -> str:
        """建议既视感处理动作"""
        if strength > 0.9:
            return f"我有个强烈的感觉，这和你之前经历过的某件事很像... ({trigger_memory.content[:50]})"
        elif strength > 0.7:
            return f"这让我想起了一些熟悉的事情..."
        else:
            return "这种场景似乎在哪里见过..."
```

#### 12.3.2 记忆自我进化 (Memory Self-Evolution)

```python
class MemorySelfEvolution:
    """
    记忆自我进化系统
    记忆系统从经验中学习，优化自身策略
    
    进化方向:
    1. 调整温度参数
    2. 优化检索权重
    3. 改进遗忘策略
    4. 调整分类阈值
    """
    
    def evaluate_and_evolve(self, agent_id: str) -> Dict:
        """评估记忆系统表现并进化"""
        metrics = self._collect_performance_metrics(agent_id)
        trends = self._analyze_trends(metrics)
        improvement_areas = self._identify_improvements(trends)
        evolution_plan = self._generate_evolution_plan(improvement_areas)
        
        if self.config.get('auto_evolve', False):
            self._execute_evolution(evolution_plan)
        
        return evolution_plan
    
    def _analyze_trends(self, metrics: Dict) -> Dict:
        """分析性能趋势"""
        trends = {}
        
        for metric_name, values in metrics.items():
            if len(values) < 10:
                continue
            
            trend = self._calculate_trend(values)
            trends[metric_name] = {
                'direction': 'up' if trend > 0.01 else ('down' if trend < -0.01 else 'stable'),
                'slope': trend,
                'current_value': values[-1],
                'average': sum(values) / len(values)
            }
        
        return trends
    
    def _generate_evolution_plan(self, improvements: List[Dict]) -> Dict:
        """生成进化计划"""
        plan = {
            'timestamp': datetime.now(),
            'evolutions': []
        }
        
        for improvement in improvements:
            if improvement['metric'] == 'retrieval_accuracy':
                if improvement['trend'] == 'down':
                    plan['evolutions'].append({
                        'type': 'adjust_retrieval_weights',
                        'action': 'increase_vector_weight',
                        'reason': '关键词检索准确率下降，需要增强语义检索'
                    })
            
            elif improvement['metric'] == 'memory_utilization':
                if improvement['trend'] == 'down':
                    plan['evolutions'].append({
                        'type': 'adjust_temperature',
                        'action': 'reduce_decay_rate',
                        'reason': '记忆利用率下降，减缓遗忘速度'
                    })
            
            elif improvement['metric'] == 'user_satisfaction':
                if improvement['trend'] == 'down':
                    plan['evolutions'].append({
                        'type': 'adjust_context_building',
                        'action': 'increase_context_tokens',
                        'reason': '用户满意度下降，可能需要更多上下文'
                    })
        
        return plan
```

### 12.4 改进模块数据流

```
用户查询
    ↓
┌─────────────────────────────────────────────────────┐
│ 1. 语义理解 + 意图分析                                │
│    输出: {intent, emotion, entities, granularity}    │
└───────────────────────┬─────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 2. 多粒度检索选择                                     │
│    原子级 → 会话级 → 主题级 → 模式级                  │
└───────────────────────┬─────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 3. 混合检索执行                                       │
│    关键词 + 向量 + 时间 + 情感 + 社交                  │
└───────────────────────┬─────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 4. 既视感检测 (可选)                                  │
│    检测似曾相识场景 → 触发深度回忆                     │
└───────────────────────┬─────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 5. 意图图谱扩展                                       │
│    用户意图 → 行为模式 → 相关记忆                      │
└───────────────────────┬─────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 6. 主动回忆 + 联想扩展                                │
│    链式回忆 → 分支扩展 → 情感共鸣                      │
└───────────────────────┬─────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 7. 记忆理解 + 过滤                                    │
│    置信度评估 → 冲突检测 → 相关性排序                  │
└───────────────────────┬─────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 8. 情感调节 (可选)                                    │
│    检测情感状态 → 调节负面情感 → 注入积极记忆          │
└───────────────────────┬─────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 9. 上下文构建                                         │
│    压缩 + 排序 + 格式化 → LLM输入                     │
└───────────────────────┬─────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 10. 反馈收集 + 系统进化                               │
│     用户满意度 → 性能指标 → 自我进化                   │
└─────────────────────────────────────────────────────┘
```

### 12.5 完整记忆系统能力矩阵 (更新版)

| 能力维度 | 基础功能 | 温度机制 | 智能增强 | 高级模块 | 进阶增强 |
|---------|---------|---------|---------|---------|---------|
| **记忆存储** | ✅ 短期/长期/情感 | ✅ 温度属性 | ✅ 视角标记 | ✅ 版本快照 | ✅ 个性化偏好 |
| **记忆检索** | ✅ 关键词搜索 | ✅ 温度加权 | ✅ 联想扩展 | ✅ 向量检索 | ✅ 多粒度检索 |
| **记忆理解** | ❌ | ❌ | ✅ 置信度 | ✅ 冲突检测 | ✅ 意图图谱 |
| **记忆更新** | ✅ 内容更新 | ✅ 温度计算 | ✅ 冲突消解 | ✅ 版本控制 | ✅ 自我进化 |
| **记忆删除** | ✅ 过期清理 | ✅ 生命周期 | ✅ 遗忘恢复 | ✅ 隐私删除 | ✅ 智能遗忘 |
| **情感处理** | ✅ 情感标签 | ✅ 情感保护 | ✅ 情感衰减 | ✅ Agent情感 | ✅ 情感调节 |
| **时间处理** | ✅ 时间戳 | ✅ 时间衰减 | ✅ 时间冲突 | ✅ 模式识别 | ✅ 梦境整理 |
| **关系处理** | ✅ 基础关联 | ✅ 关联保护 | ✅ 联想图谱 | ✅ 社交图谱 | ✅ 意图图谱 |
| **元认知** | ❌ | ❌ | ✅ 置信度 | ✅ 可解释性 | ✅ 既视感检测 |
| **自我进化** | ❌ | ❌ | ❌ | ❌ | ✅ 性能优化 |
| **反馈闭环** | ❌ | ❌ | ❌ | ❌ | ✅ 效果验证 |

### 12.6 进阶增强配置示例

```yaml
advanced_enhancements:
  intent_graph:
    enabled: true
    intent_categories:
      - information_seeking
      - emotional_support
      - task_completion
      - social_interaction
      - creative_brainstorming
    behavior_patterns:
      min_occurrences: 3
      confidence_threshold: 0.7
    max_patterns_per_intent: 20
  
  feedback_loop:
    enabled: true
    collection_methods:
      - explicit_rating
      - implicit_behavior
      - conversation_continuation
    analysis_interval_hours: 24
    improvement_threshold: 0.05
  
  personalization:
    enabled: true
    learning_rate: 0.1
    adaptation_interval_hours: 168
    user_preference_categories:
      - communication_style
      - response_length
      - formality_level
      - emotional_tone
      - detail_level
  
  dream_consolidation:
    enabled: true
    run_frequency: weekly
    run_at_hour: 3
    creativity_boost: true
    cross_domain_links: true
    insight_generation: true
  
  emotion_regulation:
    enabled: true
    check_interval_hours: 6
    negative_threshold: 0.7
    extreme_threshold: 0.9
    stale_emotion_days: 7
    positive_memory_injection: true
  
  multi_granularity:
    enabled: true
    granularity_levels:
      - atomic
      - session
      - topic
      - pattern
    auto_select: true
  
  forgetting_strategy:
    enabled: true
    advanced_factors:
      redundancy_penalty: true
      replaceability_penalty: true
      usage_protection: true
      emotion_protection: true
    forgetting_threshold: 0.7
  
  deja_vu_detection:
    enabled: true
    similarity_threshold: 0.75
    deja_vu_strength_threshold: 0.6
    trigger_deep_recall: true
  
  self_evolution:
    enabled: true
    evaluation_interval_hours: 168
    auto_evolve: false
    evolution_areas:
      - retrieval_weights
      - temperature_params
      - forgetting_strategy
      - context_building
```

### 12.7 记忆系统演进路线

```
Phase 0: 基础记忆系统
  ├── 记忆存储 (短期/长期/情感)
  ├── 基础检索 (关键词)
  └── 简单生命周期

Phase 1: 温度与智能增强
  ├── 记忆温度机制
  ├── 冲突检测与消解
  ├── 睡眠整理机制
  ├── 记忆联想图谱
  └── 元认知能力

Phase 2: 高级增强
  ├── 主动回忆机制
  ├── 情感共鸣引擎
  ├── 向量检索系统
  ├── 版本控制与演进
  ├── 记忆压缩机制
  ├── 安全隐私控制
  ├── 时间感知模块
  ├── 检索与上下文注入
  └── 社交图谱关联

Phase 3: 进阶增强 (本章)
  ├── 记忆意图图谱
  ├── 记忆反馈闭环
  ├── 个性化记忆策略
  ├── 梦境整理机制
  ├── 情感调节机制
  ├── 多粒度检索
  ├── 遗忘策略优化
  ├── 既视感检测
  └── 记忆自我进化

未来展望:
  ├── 跨Agent记忆共享 (可选)
  ├── 多模态记忆 (图片/音频/视频)
  ├── 实时记忆流处理
  ├── 记忆可解释性增强
  └── 记忆伦理与价值观对齐
```

## 13. 总结与最佳实践

### 13.1 记忆系统设计原则

1. **类人化**: 模拟人类记忆的温度、遗忘、情感、联想等特性
2. **可解释**: 每条记忆都有溯源信息，能解释"为什么记得"
3. **自适应**: 通过反馈闭环和自我进化不断优化
4. **个性化**: 根据用户特点调整记忆策略和交互风格
5. **安全隐私**: 敏感信息自动检测和保护，支持被遗忘权

### 13.2 实施建议

1. **分阶段实施**: 按照 Phase 0 → Phase 1 → Phase 2 → Phase 3 逐步推进
2. **优先级排序**: 先实现核心功能，再逐步添加高级特性
3. **监控指标**: 建立完整的监控体系，及时发现和解决问题
4. **用户反馈**: 重视用户反馈，持续优化记忆系统表现
5. **性能优化**: 关注查询延迟、数据库大小、缓存命中率等关键指标

### 13.3 关键成功因素

- **温度机制的合理设计**: 平衡记忆保留和遗忘
- **检索准确率**: 确保快速准确地找到相关记忆
- **情感处理**: 让记忆系统具备情感智能
- **自我进化能力**: 持续优化，适应用户需求变化
- **隐私保护**: 建立用户信任
