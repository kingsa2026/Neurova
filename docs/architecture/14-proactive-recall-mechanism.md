# 主动回忆机制架构设计

## 实现对齐说明

> **注意**: 本文档描述的是设计理论和概念模型。以下为文档术语与实际代码实现的对应关系：

| 文档术语 | 实际代码类/方法 | 文件位置 |
|---------|---------------|---------|
| `ScheduledRecallEngine` | `ProactiveRecall`（支持关键词、情感、时间、频率、上下文等6种触发器） | `neurova/cognitive_layers/memory_layer/proactive_recall.py` |
| `ProactiveMemoryManager` | **不存在** — 主动回忆功能统一由 `ProactiveRecall` 类实现 | `neurova/cognitive_layers/memory_layer/proactive_recall.py` |

实际实现以代码为准。

## 1. 概述

### 1.1 设计理念

主动回忆机制模拟**人类记忆的主动触发**能力，让Agent不仅是被动检索记忆，还能像人一样"突然想起来"：

> **看到某个场景触发相关记忆、定时回忆重要信息防止遗忘、通过联想链条发现隐藏关联。**

### 1.2 回忆类型

```
主动回忆系统
├── 上下文触发回忆 (Context-Triggered Recall)
│   ├── 当前对话内容触发相关记忆
│   ├── 环境信息触发（时间、地点、事件）
│   └── 情感共鸣触发（当前情感状态触发相似情感记忆）
│
├── 定时回忆巩固 (Scheduled Recall)
│   ├── 定期回忆重要记忆（防止遗忘）
│   ├── 遗忘曲线优化（在即将遗忘前主动回忆）
│   └── 记忆强化（通过重复回忆提升温度）
│
├── 联想链式回忆 (Associative Chain Recall)
│   ├── A→B→C 链式联想
│   ├── 跨维度联想（时间、情感、语义）
│   └── 灵感触发（看似无关的记忆突然关联）
│
└── 任务驱动回忆 (Task-Driven Recall)
    ├── 当前任务需要的相关经验
    ├── 类似任务的历史解决方案
    └── 任务相关的人物关系
```

### 1.3 回忆触发器

| 触发器类型 | 触发条件 | 回忆目标 | 优先级 |
|-----------|---------|---------|--------|
| **关键词触发** | 当前对话出现记忆关键词 | 相关记忆 | 高 |
| **时间触发** | 到达特定时间/日期 | 时间相关记忆 | 中 |
| **情感触发** | 当前情感强度超过阈值 | 相似情感记忆 | 高 |
| **联想触发** | 记忆A触发关联记忆B | 关联链记忆 | 中 |
| **定时触发** | 距离上次回忆超过阈值 | 重要/高温记忆 | 低 |

---

## 2. 上下文触发回忆

### 2.1 触发引擎

```python
class ContextTriggeredRecall:
    """
    上下文触发回忆引擎
    根据当前对话内容、环境信息、情感状态主动回忆相关记忆
    """
    
    def __init__(self, memory_manager, config=None):
        self.memory_manager = memory_manager
        self.config = config or {}
        self.association_graph = MemoryAssociationGraph(memory_manager.db)
        
    def trigger_recall(self, current_context: Dict) -> List[Memory]:
        """
        根据当前上下文触发回忆
        
        流程:
        1. 提取上下文关键词
        2. 检索直接相关记忆
        3. 扩展联想记忆
        4. 情感共鸣过滤
        5. 按相关性排序
        """
        recalled_memories = []
        
        # 1. 关键词触发
        if 'content' in current_context:
            keyword_memories = self._keyword_triggered_recall(
                current_context['content']
            )
            recalled_memories.extend(keyword_memories)
        
        # 2. 时间触发
        if 'time_context' in current_context:
            time_memories = self._time_triggered_recall(
                current_context['time_context']
            )
            recalled_memories.extend(time_memories)
        
        # 3. 情感触发
        if 'emotion' in current_context:
            emotion_memories = self._emotion_triggered_recall(
                current_context['emotion']
            )
            recalled_memories.extend(emotion_memories)
        
        # 4. 去重与排序
        unique_memories = self._deduplicate_and_sort(recalled_memories)
        
        # 5. 限制返回数量
        max_recall_count = self.config.get('max_recall_count', 10)
        return unique_memories[:max_recall_count]
    
    def _keyword_triggered_recall(self, content: str) -> List[Memory]:
        """关键词触发回忆"""
        # 提取关键词
        keywords = self._extract_keywords(content)
        
        recalled = []
        for keyword in keywords:
            # 搜索包含该关键词的记忆
            memories = self.memory_manager.search_by_keyword(
                keyword, limit=5
            )
            for memory in memories:
                # 只回忆活跃/次要记忆，归档记忆需要更高相关性
                if memory.lifecycle_stage in ['active', 'secondary']:
                    recalled.append(memory)
                elif memory.lifecycle_stage == 'archived':
                    # 归档记忆需要强关联才回忆
                    if memory.is_important or memory.temperature > 20:
                        recalled.append(memory)
        
        return recalled
    
    def _time_triggered_recall(self, time_context: Dict) -> List[Memory]:
        """时间触发回忆"""
        current_hour = time_context.get('hour', 0)
        current_day = time_context.get('day_of_week', 0)
        current_date = time_context.get('date', None)
        
        recalled = []
        
        # 回忆时间相关记忆（如"每天早上跑步"）
        cursor = self.memory_manager.db.cursor()
        cursor.execute("""
            SELECT * FROM memories
            WHERE lifecycle_stage IN ('active', 'secondary')
              AND metadata LIKE '%time_pattern%'
            LIMIT 20
        """)
        
        for row in cursor.fetchall():
            memory = self.memory_manager._row_to_memory(row)
            time_pattern = memory.metadata.get('time_pattern', {})
            
            # 检查时间匹配
            if self._time_pattern_matches(time_pattern, time_context):
                recalled.append(memory)
        
        return recalled
    
    def _emotion_triggered_recall(self, current_emotion: Dict) -> List[Memory]:
        """情感触发回忆"""
        emotion_type = current_emotion.get('type')
        intensity = current_emotion.get('intensity', 0)
        
        if intensity < 0.5:
            return []  # 情感强度不足，不触发
        
        recalled = []
        
        # 回忆相似情感的记忆
        cursor = self.memory_manager.db.cursor()
        cursor.execute("""
            SELECT * FROM memories
            WHERE lifecycle_stage IN ('active', 'secondary')
              AND emotion_tags LIKE ?
              AND emotion_score > 0.5
            ORDER BY emotion_score DESC
            LIMIT 10
        """, (f'%{emotion_type}%',))
        
        for row in cursor.fetchall():
            memory = self.memory_manager._row_to_memory(row)
            recalled.append(memory)
        
        return recalled
    
    def _time_pattern_matches(self, pattern: Dict, context: Dict) -> bool:
        """检查时间模式是否匹配"""
        if 'hour' in pattern:
            if abs(pattern['hour'] - context.get('hour', 0)) > 2:
                return False
        
        if 'day_of_week' in pattern:
            if pattern['day_of_week'] != context.get('day_of_week'):
                return False
        
        return True
```

### 2.2 联想链扩展

```python
class AssociativeChainRecall:
    """
    联想链式回忆
    通过记忆关联图谱实现链式回忆：A → B → C
    """
    
    def __init__(self, memory_manager, config=None):
        self.memory_manager = memory_manager
        self.config = config or {}
        self.max_chain_depth = self.config.get('max_chain_depth', 3)
        self.max_branches = self.config.get('max_branches', 3)
    
    def expand_recall(self, seed_memories: List[Memory]) -> List[Memory]:
        """
        从种子记忆扩展联想链
        
        流程:
        1. 获取种子记忆的关联
        2. 递归扩展联想链
        3. 过滤重复
        4. 按关联强度排序
        """
        expanded = list(seed_memories)
        visited_ids = {m.id for m in seed_memories}
        
        # 链式扩展
        current_level = seed_memories
        for depth in range(self.max_chain_depth):
            next_level = []
            
            for memory in current_level:
                # 获取关联记忆
                associations = self._get_associations(memory.id)
                
                for assoc_memory, weight in associations[:self.max_branches]:
                    if assoc_memory.id not in visited_ids:
                        visited_ids.add(assoc_memory.id)
                        expanded.append(assoc_memory)
                        next_level.append(assoc_memory)
            
            current_level = next_level
            
            # 如果无新记忆，提前终止
            if not current_level:
                break
        
        return expanded
    
    def _get_associations(self, memory_id: str) -> List[Tuple[Memory, float]]:
        """获取记忆的关联"""
        cursor = self.memory_manager.db.cursor()
        cursor.execute("""
            SELECT m.*, a.weight
            FROM memory_associations a
            JOIN memories m ON (
                (a.memory_a_id = ? AND m.id = a.memory_b_id) OR
                (a.memory_b_id = ? AND m.id = a.memory_a_id)
            )
            WHERE a.weight > 0.2
              AND m.lifecycle_stage IN ('active', 'secondary')
            ORDER BY a.weight DESC
            LIMIT 10
        """, (memory_id, memory_id))
        
        return [
            (self.memory_manager._row_to_memory(row), row[-1])
            for row in cursor.fetchall()
        ]
```

---

## 3. 定时回忆巩固

### 3.1 回忆调度器

```python
class ScheduledRecallEngine:
    """
    定时回忆巩固引擎
    定期主动回忆重要记忆，防止遗忘
    """
    
    def __init__(self, memory_manager, config=None):
        self.memory_manager = memory_manager
        self.config = config or {}
        
        # 回忆策略
        self.important_recall_interval = self.config.get(
            'important_recall_interval', 86400 * 3  # 3天
        )
        self.normal_recall_interval = self.config.get(
            'normal_recall_interval', 86400 * 7  # 7天
        )
        self.crystallized_recall_interval = self.config.get(
            'crystallized_recall_interval', 86400 * 30  # 30天
        )
    
    def run_recall_cycle(self, agent_id: str) -> Dict:
        """
        执行一轮定时回忆
        
        流程:
        1. 获取需要回忆的记忆
        2. 模拟"回忆"（提升温度）
        3. 强化关联
        4. 记录回忆日志
        """
        cursor = self.memory_manager.db.cursor()
        
        stats = {
            'recalled_count': 0,
            'temperature_boost': 0.0,
            'associations_strengthened': 0
        }
        
        # 1. 获取需要回忆的记忆
        memories_to_recall = self._get_memories_needing_recall(agent_id)
        
        for memory in memories_to_recall:
            # 2. 模拟回忆（提升温度）
            temperature_boost = self._simulate_recall(memory)
            stats['temperature_boost'] += temperature_boost
            
            # 3. 强化关联
            strengthened = self._strengthen_associations(memory.id)
            stats['associations_strengthened'] += strengthened
            
            stats['recalled_count'] += 1
        
        self.memory_manager.db.commit()
        
        return stats
    
    def _get_memories_needing_recall(self, agent_id: str) -> List[Memory]:
        """获取需要回忆的记忆"""
        cursor = self.memory_manager.db.cursor()
        
        now = datetime.now()
        
        cursor.execute("""
            SELECT * FROM memories
            WHERE agent_id = ?
              AND lifecycle_stage IN ('active', 'secondary')
              AND is_crystallized = 0
              AND (
                  -- 重要记忆：3天未回忆
                  (is_important = 1 AND last_accessed_at < datetime('now', '-3 days'))
                  OR
                  -- 普通记忆：7天未回忆
                  (is_important = 0 AND last_accessed_at < datetime('now', '-7 days'))
              )
            ORDER BY temperature DESC
            LIMIT 100
        """, (agent_id,))
        
        return [
            self.memory_manager._row_to_memory(row)
            for row in cursor.fetchall()
        ]
    
    def _simulate_recall(self, memory: Memory) -> float:
        """
        模拟回忆
        提升记忆温度，模拟"再次想起"
        """
        # 基础升温
        base_boost = 8.0
        
        # 重要记忆额外升温
        if memory.is_important:
            base_boost *= 1.5
        
        # 温度饱和衰减
        saturation_factor = 1.0 - (memory.temperature / 100.0) ** 2
        
        # 计算实际升温
        actual_boost = base_boost * saturation_factor
        
        # 更新记忆
        memory.temperature = min(100.0, memory.temperature + actual_boost)
        memory.last_accessed_at = datetime.now()
        memory.access_count += 1
        
        # 记录回忆日志
        self._log_recall(memory, actual_boost)
        
        # 保存到数据库
        cursor = self.memory_manager.db.cursor()
        cursor.execute("""
            UPDATE memories
            SET temperature = ?,
                last_accessed_at = ?,
                access_count = ?
            WHERE id = ?
        """, (
            memory.temperature,
            memory.last_accessed_at.isoformat(),
            memory.access_count,
            memory.id
        ))
        
        return actual_boost
    
    def _strengthen_associations(self, memory_id: str) -> int:
        """强化关联"""
        cursor = self.memory_manager.db.cursor()
        
        # 增加关联强度
        cursor.execute("""
            UPDATE memory_associations
            SET weight = MIN(1.0, weight + 0.1),
                supporting_count = supporting_count + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE memory_a_id = ? OR memory_b_id = ?
        """, (memory_id, memory_id))
        
        return cursor.rowcount
```

### 3.2 遗忘曲线优化

```python
class ForgettingCurveOptimizer:
    """
    遗忘曲线优化器
    在记忆即将被遗忘前主动回忆，最大化记忆保持
    """
    
    def __init__(self, memory_manager):
        self.memory_manager = memory_manager
    
    def predict_forgetting_time(self, memory: Memory) -> datetime:
        """
        预测记忆何时会被遗忘
        
        基于艾宾浩斯遗忘曲线:
        - 20分钟后遗忘42%
        - 1小时后遗忘56%
        - 9小时后遗忘64%
        - 1天后遗忘67%
        - 2天后遗忘72%
        - 6天后遗忘75%
        - 31天后遗忘79%
        """
        current_temp = memory.temperature
        days_since_access = (
            datetime.now() - memory.last_accessed_at
        ).days
        
        # 计算降温速率
        decay_rate = self._calculate_decay_rate(memory)
        
        # 预测到达归档阈值的时间
        if decay_rate > 0:
            days_to_archived = (
                current_temp - 20  # 归档阈值
            ) / decay_rate
        else:
            days_to_archived = float('inf')
        
        return datetime.now() + timedelta(days=days_to_archived)
    
    def schedule_optimal_recall(self, memory: Memory) -> datetime:
        """
        计算最佳回忆时间
        
        策略:
        - 在记忆温度降至50°C前回忆（保持活跃）
        - 提前2天安排回忆
        """
        current_temp = memory.temperature
        
        if current_temp >= 50:
            # 温度充足，不急
            return datetime.now() + timedelta(days=3)
        
        # 计算到达50°C的时间
        decay_rate = self._calculate_decay_rate(memory)
        if decay_rate > 0:
            days_to_50 = (current_temp - 50) / decay_rate
            # 提前2天回忆
            recall_days = max(1, days_to_50 - 2)
        else:
            recall_days = 7
        
        return datetime.now() + timedelta(days=recall_days)
```

---

## 4. 任务驱动回忆

### 4.1 任务回忆引擎

```python
class TaskDrivenRecall:
    """
    任务驱动回忆
    根据当前任务自动回忆相关经验、人物、资源
    """
    
    def __init__(self, memory_manager):
        self.memory_manager = memory_manager
    
    def recall_for_task(self, task_description: str) -> Dict:
        """
        为任务回忆相关信息
        
        返回:
        {
            'experiences': [...],      # 相关经验
            'lessons': [...],          # 相关教训
            'skills': [...],           # 相关技能
            'people': [...],           # 相关人物
            'resources': [...]         # 相关资源
        }
        """
        # 提取任务关键词
        keywords = self._extract_task_keywords(task_description)
        
        result = {
            'experiences': [],
            'lessons': [],
            'skills': [],
            'people': [],
            'resources': []
        }
        
        # 回忆相关经验
        result['experiences'] = self._recall_by_category(
            keywords, MemoryCategory.EXPERIENCE, limit=5
        )
        
        # 回忆相关教训
        result['lessons'] = self._recall_by_category(
            keywords, MemoryCategory.LESSON, limit=5
        )
        
        # 回忆相关技能
        result['skills'] = self._recall_by_category(
            keywords, MemoryCategory.SKILL, limit=5
        )
        
        # 回忆相关人物
        result['people'] = self._recall_by_category(
            keywords, MemoryCategory.RELATIONSHIP, limit=3
        )
        
        return result
    
    def _recall_by_category(
        self,
        keywords: List[str],
        category: MemoryCategory,
        limit: int
    ) -> List[Memory]:
        """按分类回忆"""
        cursor = self.memory_manager.db.cursor()
        
        recalled = []
        for keyword in keywords:
            cursor.execute("""
                SELECT m.*
                FROM memories m
                INNER JOIN memory_keywords k ON m.id = k.memory_id
                WHERE m.category = ?
                  AND k.keyword = ?
                  AND m.lifecycle_stage IN ('active', 'secondary')
                ORDER BY m.temperature DESC, m.access_count DESC
                LIMIT ?
            """, (category.value, keyword, limit))
            
            for row in cursor.fetchall():
                memory = self.memory_manager._row_to_memory(row)
                if memory not in recalled:
                    recalled.append(memory)
        
        return recalled[:limit]
```

---

## 5. 回忆触发器配置

### 5.1 触发器规则

```yaml
# proactive_recall.yaml
proactive_recall:
  context_triggered:
    enabled: true
    max_recall_count: 10
    min_relevance_score: 0.3
    max_chain_depth: 3
    max_branches: 3
    
    triggers:
      keyword:
        enabled: true
        min_keyword_length: 2
        priority: high
      
      time:
        enabled: true
        time_patterns:
          - hour: 9  # 早上9点
            recall: "work_related"
          - hour: 20  # 晚上8点
            recall: "personal_related"
      
      emotion:
        enabled: true
        min_intensity: 0.5
        emotion_mapping:
          joy: recall_similar_positive
          sadness: recall_comfort_memories
  
  scheduled_recall:
    enabled: true
    run_interval_hours: 6
    recall_strategy:
      important_interval_days: 3
      normal_interval_days: 7
      crystallized_interval_days: 30
    
    temperature_boost:
      base: 8.0
      important_multiplier: 1.5
      saturation_factor: true
  
  task_driven:
    enabled: true
    categories:
      - experience
      - lesson
      - skill
      - relationship
    max_per_category: 5
  
  forgetting_curve_optimization:
    enabled: true
    predict_threshold: 50  # 温度低于50°C时预测
    recall_advance_days: 2  # 提前2天回忆
```

---

## 6. 回忆效果评估

### 6.1 回忆质量指标

| 指标 | 说明 | 健康范围 |
|------|------|---------|
| **回忆准确率** | 回忆的记忆与当前任务的相关性 | > 70% |
| **回忆覆盖率** | 回忆到的记忆占总相关记忆的比例 | > 60% |
| **回忆延迟** | 从触发到回忆完成的时间 | < 50ms |
| **回忆链深度** | 平均联想链长度 | 2-4层 |
| **回忆温度提升** | 每次回忆平均升温 | 5-10°C |
| **遗忘率降低** | 使用主动回忆后的遗忘率降低 | > 30% |

---

## 7. 与现有系统的集成

### 7.1 集成点

```
┌─────────────────────────────────────────────────────────┐
│                   Agent 对话流程                        │
└───────────────────┬─────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────┐
│              主动回忆触发时机                            │
│                                                          │
│  1. 用户输入后 → 上下文触发回忆                         │
│  2. 定时任务    → 定时回忆巩固                          │
│  3. 任务开始时  → 任务驱动回忆                          │
│  4. 情感变化时  → 情感共鸣回忆                          │
└───────────────────┬─────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────┐
│              回忆结果处理                                │
│                                                          │
│  1. 去重与排序                                          │
│  2. 温度提升                                            │
│  3. 关联强化                                            │
│  4. 加入上下文                                          │
└───────────────────┬─────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────┐
│              记忆温度系统更新                            │
│              (温度提升、生命周期更新)                    │
└─────────────────────────────────────────────────────────┘
```

### 7.2 回忆结果使用

```python
def build_context_with_recall(
    user_input: str,
    memory_manager: MemoryManager,
    recall_engine: ProactiveRecallEngine
) -> str:
    """
    构建包含主动回忆的上下文
    """
    # 1. 被动检索
    passive_memories = memory_manager.search_memories(
        query=user_input, limit=5
    )
    
    # 2. 主动回忆
    current_context = {
        'content': user_input,
        'time_context': {
            'hour': datetime.now().hour,
            'day_of_week': datetime.now().weekday()
        },
        'emotion': memory_manager.get_current_emotion()
    }
    
    active_memories = recall_engine.trigger_recall(current_context)
    
    # 3. 合并去重
    all_memories = passive_memories + [
        m for m in active_memories
        if m.id not in {pm.id for pm in passive_memories}
    ]
    
    # 4. 构建上下文
    context_parts = []
    for memory in all_memories[:10]:
        context_parts.append(f"- {memory.content}")
    
    return "\n".join(context_parts)
```

---

## 8. 监控与日志

### 8.1 回忆日志

```python
@dataclass
class RecallLog:
    """回忆日志"""
    log_id: str
    memory_id: str
    recall_type: str  # context/scheduled/task/associative
    trigger_source: str  # 触发源
    temperature_before: float
    temperature_after: float
    associations_strengthened: int
    timestamp: datetime

class RecallLogger:
    """回忆日志记录器"""
    
    def log_recall(self, memory: Memory, recall_type: str, **kwargs):
        """记录回忆"""
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO recall_logs (
                log_id, memory_id, recall_type, trigger_source,
                temperature_before, temperature_after,
                associations_strengthened, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            memory.id,
            recall_type,
            kwargs.get('trigger_source', 'unknown'),
            kwargs.get('temperature_before', memory.temperature),
            memory.temperature,
            kwargs.get('associations_strengthened', 0),
            datetime.now().isoformat()
        ))
        self.db.commit()
```
