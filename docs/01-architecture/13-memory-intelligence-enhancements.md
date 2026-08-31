# 记忆智能增强机制架构设计

## 实现对齐说明

> **注意**: 本文档描述的是设计理论和概念模型。以下为文档术语与实际代码实现的对应关系：

| 文档术语 | 实际代码类/方法 | 文件位置 |
|---------|---------------|---------|
| `ConflictDetector` / `ConflictResolver` | `MemoryConflictDetector` | `neurova/cognitive_layers/memory_layer/conflict_detector.py` |
| `MemoryMerger` | `SleepConsolidation.merge_cluster()` | `neurova/cognitive_layers/memory_layer/sleep.py` |
| `HierarchicalCompressionEngine` | `MemoryCompressor` | `neurova/cognitive_layers/memory_layer/compression.py` |

实际实现以代码为准。

## 1. 概述

### 1.1 设计理念

在基础记忆系统之上，增加**智能增强层**，让记忆系统具备类似人类的认知能力：
- **冲突检测** - 识别矛盾记忆，避免自相矛盾
- **睡眠整理** - 定期提炼洞察，发现规律
- **联想能力** - 基于关联图谱实现"突然想到"
- **元认知** - 知道自己"记得什么"和"不记得什么"
- **情感衰减** - 情感独立于内容衰减，避免"记仇"
- **视角标记** - 区分事实、观点、推断
- **可解释性** - 能解释"为什么我记得这个"
- **遗忘恢复** - 从归档中恢复记忆
- **记忆合并** - 相似记忆聚类去重，生成摘要

### 1.2 智能增强层架构

```
┌─────────────────────────────────────────────────────────┐
│                    Application Layer                      │
│              (Agent, ContextBuilder, 对话系统)             │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│              智能增强层 (Intelligence Layer)              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Conflict │ │ Sleep    │ │ Associ-  │ │ Meta-    │   │
│  │Detector  │ │Processor │ │ ation    │ │cognition │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Emotion  │ │Perspec-  │ │ Explain- │ │ Memory   │   │
│  │ Decay    │ │ tive     │ │ ability  │ │Merge     │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│              基础记忆层 (Core Memory Layer)                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Memory   │ │Temperature│ │  Cache   │ │ Database │   │
│  │ Manager  │ │  Engine   │ │  Layer   │ │  Layer   │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
└─────────────────────────────────────────────────────────┘
```

## 2. 记忆冲突检测与消解机制

### 2.1 冲突类型定义

```python
class ConflictType(Enum):
    """冲突类型"""
    DIRECT_CONTRADICTION = "direct_contradiction"  # 直接矛盾
    TEMPORAL_CONFLICT = "temporal_conflict"        # 时间冲突
    CONTEXTUAL_CONFLICT = "contextual_conflict"    # 上下文冲突
    PREFERENCE_CONFLICT = "preference_conflict"    # 偏好冲突
    FACTUAL_CONFLICT = "factual_conflict"          # 事实冲突

@dataclass
class MemoryConflict:
    """记忆冲突对象"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conflict_type: ConflictType
    memory_a_id: str
    memory_b_id: str
    conflict_description: str  # 冲突描述
    severity: str = "medium"  # low/medium/high/critical
    confidence: float = 1.0   # 冲突检测置信度
    status: str = "detected"  # detected/resolved/ignored
    resolution_strategy: Optional[str] = None  # 消解策略
    resolved_by: Optional[str] = None  # 解决方式
    created_at: datetime = field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None
    metadata: Dict = field(default_factory=dict)
```

### 2.2 冲突检测引擎

```python
class ConflictDetector:
    """
    记忆冲突检测引擎
    """
    
    # 矛盾词对
    CONTRADICTION_PAIRS = {
        ('喜欢', '不喜欢'), ('喜欢', '讨厌'), ('爱', '恨'),
        ('是', '不是'), ('会', '不会'), ('能', '不能'),
        ('有', '没有'), ('去过', '没去过'), ('同意', '反对'),
        ('yes', 'no'), ('like', 'dislike'), ('love', 'hate'),
    }
    
    # 偏好类关键词
    PREFERENCE_KEYWORDS = [
        '喜欢', '讨厌', '爱', '恨', '偏好', '习惯',
        'like', 'dislike', 'prefer', 'hate', 'love'
    ]
    
    def detect_conflicts(self, new_memory: Memory, existing_memories: List[Memory]) -> List[MemoryConflict]:
        """
        检测新记忆与现有记忆之间的冲突
        
        检测策略:
        1. 关键词矛盾检测
        2. 语义相似度 + 内容矛盾
        3. 时间线冲突
        4. 偏好变化检测
        """
        conflicts = []
        
        for existing in existing_memories:
            # 跳过已归档/删除的记忆
            if existing.lifecycle_stage in ['archived', 'deleted']:
                continue
            
            # 1. 直接矛盾检测
            if self._is_direct_contradiction(new_memory, existing):
                conflicts.append(MemoryConflict(
                    conflict_type=ConflictType.DIRECT_CONTRADICTION,
                    memory_a_id=new_memory.id,
                    memory_b_id=existing.id,
                    conflict_description=f"直接矛盾: '{new_memory.content}' vs '{existing.content}'",
                    severity=self._calculate_severity(new_memory, existing),
                    confidence=0.9
                ))
            
            # 2. 偏好冲突检测
            elif self._is_preference_conflict(new_memory, existing):
                conflicts.append(MemoryConflict(
                    conflict_type=ConflictType.PREFERENCE_CONFLICT,
                    memory_a_id=new_memory.id,
                    memory_b_id=existing.id,
                    conflict_description=f"偏好变化: '{new_memory.content}' vs '{existing.content}'",
                    severity="low",
                    confidence=0.7
                ))
            
            # 3. 时间冲突检测
            elif self._is_temporal_conflict(new_memory, existing):
                conflicts.append(MemoryConflict(
                    conflict_type=ConflictType.TEMPORAL_CONFLICT,
                    memory_a_id=new_memory.id,
                    memory_b_id=existing.id,
                    conflict_description="时间线冲突",
                    severity="medium",
                    confidence=0.8
                ))
        
        return conflicts
    
    def _is_direct_contradiction(self, mem_a: Memory, mem_b: Memory) -> bool:
        """检测直接矛盾"""
        # 提取关键陈述
        statements_a = self._extract_statements(mem_a.content)
        statements_b = self._extract_statements(mem_b.content)
        
        for stmt_a in statements_a:
            for stmt_b in statements_b:
                # 检查是否包含矛盾词对
                for word_a, word_b in self.CONTRADICTION_PAIRS:
                    if word_a in stmt_a and word_b in stmt_b:
                        # 进一步检查是否指向同一主体
                        if self._same_subject(stmt_a, stmt_b):
                            return True
        
        return False
    
    def _extract_statements(self, content: str) -> List[str]:
        """提取关键陈述句"""
        # 简单分句
        sentences = re.split(r'[。！？.;!?]', content)
        return [s.strip() for s in sentences if len(s.strip()) > 5]
    
    def _same_subject(self, stmt_a: str, stmt_b: str) -> bool:
        """检查是否指向同一主体"""
        # 简单实现: 提取名词/代词比较
        # 可使用 NLP 工具提取主语
        keywords_a = set(re.findall(r'[\u4e00-\u9fff]{1,4}', stmt_a))
        keywords_b = set(re.findall(r'[\u4e00-\u9fff]{1,4}', stmt_b))
        
        # 计算重叠度
        overlap = keywords_a & keywords_b
        return len(overlap) >= 1  # 有共同关键词即认为同主体
```

### 2.3 冲突消解策略

```python
class ConflictResolver:
    """
    冲突消解器
    """
    
    def resolve_conflict(self, conflict: MemoryConflict, 
                         memory_a: Memory, memory_b: Memory) -> ResolutionResult:
        """
        根据冲突类型选择消解策略
        """
        if conflict.conflict_type == ConflictType.DIRECT_CONTRADICTION:
            return self._resolve_direct_contradiction(conflict, memory_a, memory_b)
        
        elif conflict.conflict_type == ConflictType.PREFERENCE_CONFLICT:
            return self._resolve_preference_conflict(conflict, memory_a, memory_b)
        
        elif conflict.conflict_type == ConflictType.TEMPORAL_CONFLICT:
            return self._resolve_temporal_conflict(conflict, memory_a, memory_b)
    
    def _resolve_direct_contradiction(self, conflict, mem_a, mem_b) -> ResolutionResult:
        """
        直接矛盾消解策略
        
        策略优先级:
        1. 新覆盖旧 (recency)
        2. 温度优先 (temperature)
        3. 用户确认 (user_confirm)
        """
        # 策略 1: 时间优先 (新记忆覆盖旧记忆)
        if mem_a.created_at > mem_b.created_at:
            newer, older = mem_a, mem_b
        else:
            newer, older = mem_b, mem_a
        
        # 检查温度差异
        temp_diff = abs(newer.temperature - older.temperature)
        
        if temp_diff > 20:
            # 温度差异大，温度优先
            winner = max([newer, older], key=lambda m: m.temperature)
            strategy = "temperature_priority"
        else:
            # 时间优先
            winner = newer
            strategy = "recency"
        
        # 标记旧记忆为失效
        older.is_archived = True
        older.metadata['superseded_by'] = winner.id
        older.metadata['supersede_reason'] = 'contradiction'
        
        return ResolutionResult(
            strategy=strategy,
            winner=winner,
            loser=older,
            action="archive_older",
            auto_resolved=True
        )
    
    def _resolve_preference_conflict(self, conflict, mem_a, mem_b) -> ResolutionResult:
        """
        偏好冲突消解
        
        偏好会变化，保留两条记忆，标记时间有效性
        """
        # 标记旧记忆为"历史偏好"
        older = min([mem_a, mem_b], key=lambda m: m.created_at)
        newer = max([mem_a, mem_b], key=lambda m: m.created_at)
        
        older.metadata['preference_valid_until'] = newer.created_at.isoformat()
        older.metadata['preference_superseded'] = True
        
        newer.metadata['preference_valid_from'] = newer.created_at.isoformat()
        newer.metadata['preference_current'] = True
        
        return ResolutionResult(
            strategy="preference_evolution",
            winner=newer,
            action="keep_both_with_timeline",
            auto_resolved=True
        )
```

### 2.4 冲突数据库表

```sql
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

CREATE INDEX idx_conflicts_status ON memory_conflicts(status, severity, created_at DESC);
CREATE INDEX idx_conflicts_memory ON memory_conflicts(memory_a_id, memory_b_id);
```

## 3. 睡眠-整理机制

### 3.1 睡眠整理器核心

```python
class MemorySleepProcessor:
    """
    记忆睡眠整理器
    定期执行记忆整理、模式发现、关联强化
    """
    
    def __init__(self, db_connection, memory_manager, config: Optional[Dict] = None):
        self.db = db_connection
        self.memory_manager = memory_manager
        self.config = config or {}
        self.consolidation_engine = ConsolidationEngine(db_connection)
        self.pattern_discoverer = PatternDiscoverer(db_connection)
    
    def run_nightly_consolidation(self, agent_id: str):
        """
        夜间记忆整理 (建议凌晨 2-4 点执行)
        
        整理流程:
        1. 合并相似记忆
        2. 提取模式/规律
        3. 强化重要关联
        4. 清理无用碎片
        5. 生成洞察记忆
        """
        logger.info(f"Starting nightly consolidation for agent {agent_id}")
        
        try:
            # 1. 合并相似记忆
            merge_count = self._merge_similar_memories(agent_id)
            logger.info(f"Merged {merge_count} similar memories")
            
            # 2. 发现模式
            new_insights = self._discover_patterns(agent_id)
            logger.info(f"Discovered {len(new_insights)} new insights")
            
            # 3. 强化关联
            strengthened = self._strengthen_relations(agent_id)
            logger.info(f"Strengthened {strengthened} relations")
            
            # 4. 清理碎片
            cleaned = self._clean_fragments(agent_id)
            logger.info(f"Cleaned {cleaned} fragments")
            
            # 5. 生成摘要
            summaries = self._generate_session_summaries(agent_id)
            logger.info(f"Generated {len(summaries)} session summaries")
            
            # 记录整理日志
            self._log_consolidation(agent_id, {
                'merge_count': merge_count,
                'insight_count': len(new_insights),
                'strengthened': strengthened,
                'cleaned': cleaned,
                'summaries': len(summaries)
            })
            
        except Exception as e:
            logger.error(f"Nightly consolidation failed: {e}")
            raise
    
    def _merge_similar_memories(self, agent_id: str) -> int:
        """合并相似记忆"""
        return self.consolidation_engine.merge_similar_memories(agent_id)
    
    def _discover_patterns(self, agent_id: str) -> List[Memory]:
        """发现模式并生成洞察"""
        patterns = self.pattern_discoverer.discover(agent_id)
        insights = []
        
        for pattern in patterns:
            insight = self._create_insight_memory(agent_id, pattern)
            if insight:
                insights.append(insight)
        
        return insights
    
    def _strengthen_relations(self, agent_id: str) -> int:
        """强化重要关联"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT source_memory_id, target_memory_id, COUNT(*) as co_occurrence
            FROM memory_relations
            WHERE source_memory_id IN (
                SELECT id FROM memories WHERE agent_id = ? AND is_important = 1
            )
            GROUP BY source_memory_id, target_memory_id
            HAVING co_occurrence > 3
        """, (agent_id,))
        
        strengthened_count = 0
        for row in cursor.fetchall():
            source_id, target_id, co_occurrence = row
            
            # 增加关联强度
            new_strength = min(1.0, 0.5 + co_occurrence * 0.1)
            cursor.execute("""
                UPDATE memory_relations
                SET strength = ?, updated_at = CURRENT_TIMESTAMP
                WHERE source_memory_id = ? AND target_memory_id = ?
            """, (new_strength, source_id, target_id))
            
            strengthened_count += 1
        
        self.db.commit()
        return strengthened_count
    
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
              AND id NOT IN (
                  SELECT DISTINCT source_memory_id FROM memory_relations
                  UNION
                  SELECT DISTINCT target_memory_id FROM memory_relations
              )
        """, (agent_id,))
        
        fragment_ids = [row[0] for row in cursor.fetchall()]
        
        if fragment_ids:
            # 批量标记为删除
            cursor.execute("""
                UPDATE memories
                SET lifecycle_stage = 'deleted',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({})
            """.format(','.join(['?' for _ in fragment_ids])), fragment_ids)
            
            self.db.commit()
        
        return len(fragment_ids)
    
    def _generate_session_summaries(self, agent_id: str) -> List[Memory]:
        """生成会话摘要"""
        # 按日期聚合对话记忆
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as msg_count
            FROM memories
            WHERE agent_id = ?
              AND category = 'conversation'
              AND lifecycle_stage = 'active'
            GROUP BY DATE(created_at)
            HAVING msg_count >= 5  -- 至少 5 条对话的日期
            ORDER BY date DESC
            LIMIT 7  -- 最近 7 天
        """, (agent_id,))
        
        summaries = []
        for row in cursor.fetchall():
            date, msg_count = row
            
            # 获取当天所有对话
            cursor.execute("""
                SELECT content FROM memories
                WHERE agent_id = ?
                  AND DATE(created_at) = ?
                  AND category = 'conversation'
                ORDER BY created_at
            """, (agent_id, date))
            
            conversations = [r[0] for r in cursor.fetchall()]
            
            # 生成摘要 (可调用 LLM)
            summary_content = self._generate_day_summary(conversations, date)
            
            # 创建摘要记忆
            summary = Memory(
                id=f"summary_{agent_id}_{date}",
                agent_id=agent_id,
                type=MemoryType.LONG_TERM,
                category=MemoryCategory.EXPERIENCE,
                content=summary_content,
                temperature=60.0,  # 摘要初始温度较高
                lifecycle_stage='active'
            )
            
            # 检查是否已存在
            if not self.memory_manager.memory_exists(summary.id):
                self.memory_manager.add_memory(summary)
                summaries.append(summary)
        
        return summaries
    
    def _generate_day_summary(self, conversations: List[str], date: str) -> str:
        """
        生成某天的对话摘要
        可调用 LLM 或使用模板
        """
        # 简单模板实现
        topics = self._extract_topics(conversations)
        
        return f"[{date} 对话摘要] 今天讨论了以下主题: {', '.join(topics[:5])}。"
    
    def _extract_topics(self, texts: List[str]) -> List[str]:
        """从文本中提取主题"""
        # 可使用 TF-IDF 或 LLM 提取
        all_text = " ".join(texts)
        # 简单关键词提取
        keywords = re.findall(r'[\u4e00-\u9fff]{2,6}', all_text)
        # 过滤高频词
        word_counts = Counter(keywords)
        return [word for word, _ in word_counts.most_common(10)]
```

### 3.2 模式发现器

```python
class PatternDiscoverer:
    """
    模式发现器
    从记忆中发现重复模式、规律、洞察
    """
    
    def discover(self, agent_id: str) -> List[Pattern]:
        """
        发现模式
        
        模式类型:
        1. 重复行为模式 (如: 每周运动 3 次)
        2. 偏好演变模式 (如: 口味从辣到清淡)
        3. 时间规律模式 (如: 每晚 10 点学习)
        4. 情感模式 (如: 讨论工作时情绪焦虑)
        """
        patterns = []
        
        # 1. 重复行为模式
        patterns.extend(self._discover_behavior_patterns(agent_id))
        
        # 2. 偏好演变模式
        patterns.extend(self._discover_preference_patterns(agent_id))
        
        # 3. 时间规律模式
        patterns.extend(self._discover_temporal_patterns(agent_id))
        
        # 4. 情感模式
        patterns.extend(self._discover_emotion_patterns(agent_id))
        
        return patterns
    
    def _discover_behavior_patterns(self, agent_id: str) -> List[Pattern]:
        """发现重复行为模式"""
        cursor = self.db.cursor()
        
        # 查找重复出现的关键词+动作
        cursor.execute("""
            SELECT m.content, COUNT(*) as frequency
            FROM memories m
            INNER JOIN memory_keywords k ON m.id = k.memory_id
            WHERE m.agent_id = ?
              AND m.lifecycle_stage = 'active'
            GROUP BY k.keyword
            HAVING frequency >= 5
            ORDER BY frequency DESC
            LIMIT 20
        """, (agent_id,))
        
        patterns = []
        for row in cursor.fetchall():
            content, frequency = row
            patterns.append(Pattern(
                pattern_type='behavior',
                description=f"高频话题/行为: 出现 {frequency} 次",
                confidence=min(1.0, frequency / 10),
                supporting_memories=[],
                metadata={'frequency': frequency}
            ))
        
        return patterns
```

## 4. 记忆联想能力

### 4.1 记忆联想图

```python
class MemoryAssociationGraph:
    """
    记忆联想图
    基于共现、时间邻近、情感一致性建立联想边
    """
    
    def __init__(self, db_connection):
        self.db = db_connection
    
    def build_association_graph(self, agent_id: str):
        """
        构建记忆联想图
        """
        cursor = self.db.cursor()
        
        # 1. 基于共现频率建立联想
        self._build_cooccurrence_associations(agent_id)
        
        # 2. 基于时间邻近性建立联想
        self._build_temporal_proximity_associations(agent_id)
        
        # 3. 基于情感一致性建立联想
        self._build_emotion_consistency_associations(agent_id)
    
    def _build_cooccurrence_associations(self, agent_id: str):
        """基于共现频率建立联想"""
        # 查找在同一会话中出现的记忆对
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT 
                m1.id as memory_a,
                m2.id as memory_b,
                COUNT(*) as co_occurrence
            FROM session_messages s1
            JOIN session_messages s2 ON s1.session_id = s2.session_id
            JOIN memories m1 ON s1.content LIKE '%' || m1.content || '%'
            JOIN memories m2 ON s2.content LIKE '%' || m2.content || '%'
            WHERE m1.agent_id = ? AND m2.agent_id = ?
              AND m1.id < m2.id  -- 避免重复
            GROUP BY m1.id, m2.id
            HAVING co_occurrence >= 2
        """, (agent_id, agent_id))
        
        for row in cursor.fetchall():
            mem_a, mem_b, co_occurrence = row
            
            # 计算联想权重
            association_weight = min(1.0, co_occurrence * 0.2)
            
            # 插入或更新联想边
            cursor.execute("""
                INSERT OR REPLACE INTO memory_associations (
                    memory_a_id, memory_b_id, association_type, weight,
                    supporting_count, created_at, updated_at
                ) VALUES (?, ?, 'cooccurrence', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (mem_a, mem_b, association_weight, co_occurrence))
        
        self.db.commit()
    
    def get_associated_memories(self, memory_id: str, top_k: int = 5) -> List[Tuple[Memory, float]]:
        """
        获取与指定记忆关联的记忆
        返回 (记忆, 关联权重) 列表
        """
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
        """
        获取链式联想 (A→B→C)
        """
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

### 4.2 联想数据库表

```sql
CREATE TABLE memory_associations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_a_id TEXT NOT NULL,
    memory_b_id TEXT NOT NULL,
    association_type TEXT NOT NULL CHECK(association_type IN (
        'cooccurrence',      -- 共现
        'temporal_proximity',-- 时间邻近
        'emotion_consistency',-- 情感一致
        'semantic_similar',  -- 语义相似
        'user_defined'       -- 用户定义
    )),
    weight REAL DEFAULT 0.5 CHECK(weight >= 0 AND weight <= 1.0),
    supporting_count INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (memory_a_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (memory_b_id) REFERENCES memories(id) ON DELETE CASCADE,
    
    UNIQUE(memory_a_id, memory_b_id, association_type)
);

-- 联想查询索引
CREATE INDEX idx_associations_memory_a ON memory_associations(memory_a_id, weight DESC);
CREATE INDEX idx_associations_memory_b ON memory_associations(memory_b_id, weight DESC);
CREATE INDEX idx_associations_type ON memory_associations(association_type, weight DESC);
```

## 5. 元认知能力

### 5.1 记忆置信度计算

```python
class MemoryMetaCognition:
    """
    记忆元认知系统
    计算置信度，表达不确定性
    """
    
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
        # 1. 温度因子 (0-1 归一化)
        temp_factor = memory.temperature / 100.0
        
        # 2. 访问次数因子 (对数归一化)
        access_factor = min(1.0, math.log10(max(1, memory.access_count)) / 2)
        
        # 3. 内容完整度因子
        content_factor = min(1.0, len(memory.content) / 200)
        
        # 4. 情感强度因子
        emotion_factor = abs(memory.emotion_score)
        
        # 5. 关联数量因子
        relation_count = self._get_relation_count(memory.id)
        relation_factor = min(1.0, relation_count / 10)
        
        # 6. 来源可靠性因子
        perspective = memory.metadata.get('perspective', 'ai_inference')
        source_factor = {
            'user_statement': 0.9,
            'shared_experience': 0.8,
            'external_source': 0.7,
            'ai_inference': 0.5
        }.get(perspective, 0.5)
        
        # 加权计算
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
        """
        生成不确定性回复
        
        根据置信度选择不同的回复模板
        """
        confidence = self.calculate_confidence(memory)
        
        if confidence >= 0.8:
            return f"我记得很清楚，{memory.content}"
        
        elif confidence >= 0.6:
            return f"我隐约记得{memory.content}，但不太确定"
        
        elif confidence >= 0.4:
            return f"我模糊记得你提过相关的事情，但细节不太清楚了"
        
        else:
            return f"抱歉，这件事我可能没有记住，能再告诉我一次吗？这次我会好好记下来"
    
    def explain_why_remember(self, memory: Memory) -> str:
        """
        解释为什么记得这个记忆
        """
        reasons = []
        
        if memory.access_count > 0:
            reasons.append(f"你提到过 {memory.access_count} 次")
        
        if memory.emotion_score > 0.7:
            reasons.append(f"你说的时候情绪很{'积极' if memory.emotion_score > 0 else '强烈'}")
        
        if memory.is_important:
            reasons.append("我把它标记为了重要记忆")
        
        if memory.is_crystallized:
            reasons.append("这是你的核心记忆之一")
        
        relation_count = self._get_relation_count(memory.id)
        if relation_count > 3:
            reasons.append(f"这和你的 {relation_count} 个其他记忆相关联")
        
        if reasons:
            return "我记得这个是因为: " + "，".join(reasons) + "。"
        else:
            return "我只是正常记录了这个信息。"
```

## 6. 情感独立衰减机制

### 6.1 情感衰减模型

```python
class EmotionDecayEngine:
    """
    情感独立衰减引擎
    情感强度独立于记忆内容衰减
    """
    
    # 不同情感类型的衰减速率
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
        """
        对记忆的情感进行衰减
        """
        if days_passed <= 0 or not memory.emotion_tags:
            return memory
        
        # 按情感类型衰减
        for emotion_tag in memory.emotion_tags:
            decay_rate = self.EMOTION_DECAY_RATES.get(emotion_tag.value, 0.05)
            
            # 指数衰减: I(t) = I0 * e^(-λt)
            new_intensity = memory.emotion_score * math.exp(-decay_rate * days_passed)
            
            # 确保不低于 0
            memory.emotion_score = max(0.0, new_intensity)
        
        return memory
    
    def get_current_emotion(self, memory: Memory) -> Tuple[EmotionType, float]:
        """
        获取记忆当前的情感状态 (已衰减)
        """
        if not memory.emotion_tags:
            return EmotionType.NEUTRAL, 0.0
        
        # 返回最强情感 (已衰减后)
        return memory.emotion_tags[0], memory.emotion_score
```

### 6.2 数据库更新

```sql
-- memory_emotions 表增加衰减字段
ALTER TABLE memory_emotions ADD COLUMN initial_intensity REAL;
ALTER TABLE memory_emotions ADD COLUMN decay_rate REAL DEFAULT 0.05;
ALTER TABLE memory_emotions ADD COLUMN current_intensity REAL;

-- 查询当前情感强度 (已衰减)
CREATE VIEW current_emotions AS
SELECT 
    id, memory_id, emotion_type,
    initial_intensity,
    decay_rate,
    current_intensity * EXP(-decay_rate * 
        JULIANDAY(CURRENT_TIMESTAMP) - JULIANDAY(created_at)) AS decayed_intensity,
    created_at
FROM memory_emotions;
```

## 7. 记忆视角标记系统

### 7.1 视角定义

```python
class MemoryPerspective(Enum):
    """记忆视角"""
    USER_STATEMENT = "user_statement"       # 用户明确说的
    AI_INFERENCE = "ai_inference"           # AI 推断的
    SHARED_EXPERIENCE = "shared_experience"  # 共同经历的
    EXTERNAL_SOURCE = "external_source"     # 外部获取的
    HYPOTHETICAL = "hypothetical"           # 假设/想象的

@dataclass
class Memory:
    # ... 原有字段 ...
    perspective: MemoryPerspective = MemoryPerspective.USER_STATEMENT
    perspective_confidence: float = 1.0  # 视角置信度
    
    # 引用来源
    source: Optional[str] = None  # 来源 (如用户原话、外部链接)
    inference_reasoning: Optional[str] = None  # AI 推断的推理过程
```

### 7.2 使用示例

```python
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
    
    elif memory.perspective == MemoryPerspective.HYPOTHETICAL:
        return f"我想象过: {memory.content}"
```

## 8. 记忆可解释性追踪

### 8.1 记忆溯源链

```python
@dataclass
class MemoryProvenance:
    """记忆溯源信息"""
    memory_id: str
    origin: str  # 'conversation', 'inference', 'external', 'user_input'
    original_content: str  # 原始内容
    transformations: List[Dict]  # 转换历史
    creation_context: Dict  # 创建时的上下文
    created_at: datetime
    created_by: str  # 'user', 'agent', 'system'
    
    def get_explanation(self) -> str:
        """生成可解释性描述"""
        parts = []
        
        parts.append(f"这条记忆来自{self.origin}")
        parts.append(f"创建于{self.created_at.strftime('%Y-%m-%d %H:%M')}")
        parts.append(f"由{self.created_by}创建")
        
        if self.transformations:
            parts.append(f"经过了{len(self.transformations)}次更新")
        
        return "。".join(parts) + "。"
```

### 8.2 溯源数据库表

```sql
CREATE TABLE memory_provenance (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    original_content TEXT,
    transformations TEXT,  -- JSON
    creation_context TEXT, -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,
    
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX idx_provenance_memory ON memory_provenance(memory_id);
```

## 9. 记忆遗忘恢复机制

### 9.1 遗忘恢复引擎

```python
class MemoryRecoveryEngine:
    """
    记忆遗忘恢复引擎
    从归档/删除中恢复记忆
    """
    
    def search_archived(self, agent_id: str, query: str) -> List[Memory]:
        """搜索归档记忆"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT * FROM memories
            WHERE agent_id = ?
              AND lifecycle_stage IN ('archived', 'deleted')
              AND (content LIKE ? OR metadata LIKE ?)
            ORDER BY temperature DESC
            LIMIT 20
        """, (agent_id, f'%{query}%', f'%{query}%'))
        
        return [self._row_to_memory(row) for row in cursor.fetchall()]
    
    def recover_memory(self, memory_id: str) -> Memory:
        """恢复记忆"""
        cursor = self.db.cursor()
        cursor.execute("""
            UPDATE memories
            SET lifecycle_stage = 'active',
                temperature = 50.0,
                is_archived = 0,
                last_accessed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (memory_id,))
        
        self.db.commit()
        
        cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
        return self._row_to_memory(cursor.fetchone())
```

## 10. 记忆合并机制

### 10.1 记忆合并引擎

```python
class MemoryMerger:
    """
    记忆合并引擎
    合并相似/重复记忆，减少冗余
    """
    
    def __init__(self, db_connection, llm_provider=None):
        self.db = db_connection
        self.llm_provider = llm_provider
    
    def merge_similar_memories(self, agent_id: str) -> int:
        """
        合并相似记忆
        
        流程:
        1. 聚类相似记忆
        2. 对每个聚类生成摘要
        3. 创建合并记忆
        4. 标记原始记忆为已合并
        """
        # 1. 获取活跃记忆
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, content, temperature, access_count
            FROM memories
            WHERE agent_id = ?
              AND lifecycle_stage = 'active'
              AND is_crystallized = 0  -- 跳过固化记忆
        """, (agent_id,))
        
        memories = cursor.fetchall()
        
        # 2. 计算相似度矩阵
        similarity_matrix = self._calculate_similarity_matrix(memories)
        
        # 3. 聚类
        clusters = self._cluster_memories(similarity_matrix, threshold=0.7)
        
        # 4. 合并每个聚类
        merged_count = 0
        for cluster in clusters:
            if len(cluster) >= 2:
                self._merge_cluster(cluster)
                merged_count += len(cluster) - 1  # 合并后减少的记忆数
        
        return merged_count
    
    def _calculate_similarity_matrix(self, memories: List[Tuple]) -> Dict:
        """计算记忆间的相似度矩阵"""
        matrix = {}
        
        for i, (id_a, content_a, _, _) in enumerate(memories):
            for j, (id_b, content_b, _, _) in enumerate(memories):
                if i >= j:
                    continue
                
                similarity = self._calculate_similarity(content_a, content_b)
                if similarity > 0.5:
                    matrix[(id_a, id_b)] = similarity
        
        return matrix
    
    def _calculate_similarity(self, text_a: str, text_b: str) -> float:
        """
        计算文本相似度
        可使用:
        1. Jaccard 相似度
        2. Cosine 相似度 (TF-IDF)
        3. 语义嵌入相似度 (SentenceTransformer)
        """
        # 简单实现: Jaccard 相似度
        words_a = set(jieba.lcut(text_a))
        words_b = set(jieba.lcut(text_b))
        
        intersection = words_a & words_b
        union = words_a | words_b
        
        return len(intersection) / len(union) if union else 0.0
    
    def _cluster_memories(self, similarity_matrix: Dict, threshold: float = 0.7) -> List[List[str]]:
        """基于相似度聚类"""
        # 简单实现: 连通分量聚类
        from collections import defaultdict
        
        graph = defaultdict(set)
        for (a, b), sim in similarity_matrix.items():
            if sim >= threshold:
                graph[a].add(b)
                graph[b].add(a)
        
        visited = set()
        clusters = []
        
        for node in graph:
            if node not in visited:
                cluster = []
                stack = [node]
                while stack:
                    current = stack.pop()
                    if current not in visited:
                        visited.add(current)
                        cluster.append(current)
                        stack.extend(graph[current] - visited)
                
                if len(cluster) >= 2:
                    clusters.append(cluster)
        
        return clusters
    
    def _merge_cluster(self, memory_ids: List[str]):
        """合并一个聚类中的记忆"""
        cursor = self.db.cursor()
        
        # 获取所有记忆
        cursor.execute("""
            SELECT id, content, temperature, access_count, emotion_score
            FROM memories WHERE id IN ({})
        """.format(','.join(['?' for _ in memory_ids])), memory_ids)
        
        memories = cursor.fetchall()
        
        # 找到温度最高的记忆作为主记忆
        primary = max(memories, key=lambda m: m[2])  # temperature
        primary_id, primary_content, primary_temp, primary_access, primary_emotion = primary
        
        # 生成合并摘要 (可调用 LLM)
        if self.llm_provider:
            merged_content = self._generate_merge_summary([m[1] for m in memories])
        else:
            # 简单拼接
            merged_content = self._simple_merge([m[1] for m in memories])
        
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
            merged_content,
            primary_temp,
            sum(m[3] for m in memories),  # 累计访问次数
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
    
    def _generate_merge_summary(self, contents: List[str]) -> str:
        """使用 LLM 生成合并摘要"""
        prompt = f"""请将以下记忆合并为一条简洁的记忆:

{' | '.join(contents)}

要求:
1. 保留所有重要信息
2. 去除重复内容
3. 保持简洁
4. 输出一条记忆"""

        response = self.llm_provider.generate_completion(prompt)
        return response.text
    
    def _simple_merge(self, contents: List[str]) -> str:
        """简单合并 (无 LLM)"""
        # 去重
        unique = list(dict.fromkeys(contents))
        return "；".join(unique)
```

### 10.2 合并数据库表

```sql
-- 记录合并历史
CREATE TABLE memory_merge_history (
    id TEXT PRIMARY KEY,
    primary_memory_id TEXT NOT NULL,
    merged_memory_ids TEXT NOT NULL,  -- JSON array
    merge_type TEXT NOT NULL,  -- similarity, temporal, user_request
    merge_summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT DEFAULT 'system',
    
    FOREIGN KEY (primary_memory_id) REFERENCES memories(id)
);

CREATE INDEX idx_merge_history_primary ON memory_merge_history(primary_memory_id);
```

## 11. 完整数据库更新

```sql
-- ==========================================
-- 记忆智能增强机制数据库更新
-- ==========================================

-- 1. 冲突表
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

-- 2. 联想图
CREATE TABLE IF NOT EXISTS memory_associations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_a_id TEXT NOT NULL,
    memory_b_id TEXT NOT NULL,
    association_type TEXT NOT NULL,
    weight REAL DEFAULT 0.5,
    supporting_count INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_a_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (memory_b_id) REFERENCES memories(id) ON DELETE CASCADE,
    UNIQUE(memory_a_id, memory_b_id, association_type)
);

-- 3. 合并历史
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

-- 4. 溯源表
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

-- 5. 索引
CREATE INDEX IF NOT EXISTS idx_conflicts_status ON memory_conflicts(status, severity, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_associations_memory_a ON memory_associations(memory_a_id, weight DESC);
CREATE INDEX IF NOT EXISTS idx_associations_memory_b ON memory_associations(memory_b_id, weight DESC);
CREATE INDEX IF NOT EXISTS idx_merge_history_primary ON memory_merge_history(primary_memory_id);
CREATE INDEX IF NOT EXISTS idx_provenance_memory ON memory_provenance(memory_id);

-- 6. 记忆主表更新 (视角字段)
ALTER TABLE memories ADD COLUMN perspective TEXT DEFAULT 'user_statement';
ALTER TABLE memories ADD COLUMN perspective_confidence REAL DEFAULT 1.0;
ALTER TABLE memories ADD COLUMN source TEXT;
```

## 12. 智能增强调度器

```python
class IntelligenceScheduler:
    """
    智能增强调度器
    定期执行各项智能增强任务
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.conflict_detector = ConflictDetector()
        self.sleep_processor = MemorySleepProcessor(db, memory_manager)
        self.association_graph = MemoryAssociationGraph(db)
        self.emotion_decay = EmotionDecayEngine()
        self.meta_cognition = MemoryMetaCognition()
    
    def start(self):
        """启动调度器"""
        # 1. 冲突检测: 每次写入后
        # 2. 睡眠整理: 每日凌晨 2:00
        # 3. 联想图更新: 每 6 小时
        # 4. 情感衰减: 每日一次
        # 5. 元认知更新: 实时
        
        self._schedule_nightly_consolidation()
        self._schedule_association_update()
        self._schedule_emotion_decay()
    
    def _schedule_nightly_consolidation(self):
        """夜间整理调度"""
        run_at = self.config.get('consolidation_hour', 2)  # 凌晨 2 点
        
        while self.running:
            now = datetime.now()
            if now.hour == run_at and now.minute == 0:
                for agent_id in self._get_active_agents():
                    self.sleep_processor.run_nightly_consolidation(agent_id)
            time.sleep(60)
    
    def _schedule_association_update(self):
        """联想图更新调度"""
        interval_hours = self.config.get('association_interval', 6)
        
        while self.running:
            for agent_id in self._get_active_agents():
                self.association_graph.build_association_graph(agent_id)
            time.sleep(interval_hours * 3600)
    
    def _schedule_emotion_decay(self):
        """情感衰减调度"""
        while self.running:
            now = datetime.now()
            if now.hour == 3:  # 凌晨 3 点
                self._decay_all_emotions()
            time.sleep(60)
```

## 13. 配置示例

```yaml
# intelligence.yaml
intelligence:
  # 冲突检测
  conflict_detection:
    enabled: true
    auto_resolve: true
    resolve_strategies:
      - recency
      - temperature_priority
    notify_user: true
  
  # 睡眠整理
  sleep_consolidation:
    enabled: true
    run_at_hour: 2  # 凌晨 2 点
    merge_similarity_threshold: 0.7
    pattern_discovery: true
    summary_generation: true
    fragment_cleanup: true
  
  # 联想图
  association_graph:
    enabled: true
    update_interval_hours: 6
    min_weight_threshold: 0.1
    max_associations_per_memory: 20
  
  # 情感衰减
  emotion_decay:
    enabled: true
    run_daily: true
    decay_rates:
      joy: 0.03
      surprise: 0.05
      anger: 0.08
      fear: 0.06
      sadness: 0.04
      disgust: 0.07
      neutral: 0.02
  
  # 元认知
  meta_cognition:
    enabled: true
    confidence_thresholds:
      high: 0.8
      medium: 0.6
      low: 0.4
  
  # 记忆合并
  memory_merge:
    enabled: true
    min_similarity: 0.7
    min_cluster_size: 2
    use_llm_summary: true
    auto_merge: false  # 建议手动确认
```

## 14. 监控指标

| 指标 | 说明 | 健康范围 |
|------|------|---------|
| **冲突检测率** | 每日新发现冲突数 | 5-20/天 |
| **冲突解决率** | 已解决冲突占比 | > 80% |
| **记忆合并率** | 每日合并的记忆数 | 总记忆 1-3% |
| **模式发现数** | 每日发现的模式/洞察 | 1-5/天 |
| **联想图密度** | 平均每个记忆的关联数 | 3-10 |
| **情感衰减率** | 每日情感强度衰减比例 | 3-8% |
| **平均置信度** | 所有记忆的平均置信度 | 0.6-0.8 |
| **记忆去重率** | 合并后减少的记忆比例 | 10-20% |
