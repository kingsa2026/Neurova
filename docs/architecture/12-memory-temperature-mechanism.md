# 记忆温度机制架构设计

## 1. 概述

### 1.1 设计理念

记忆温度机制模拟**人类记忆的遗忘曲线**，通过动态温度维度实现记忆的智能生命周期管理。核心理念:

> **频繁使用的记忆保持高温，长期不用的记忆自然降温，重要记忆通过情感和意义关联保持恒温，最终遗忘的记忆优雅退场。**

### 1.2 温度生命周期

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

### 1.3 生命周期阶段定义

| 阶段 | 温度范围 | 触发条件 | 数据库状态 | 查询优先级 | 存储策略 |
|------|---------|---------|-----------|-----------|---------|
| **活跃 (Active)** | ≥60°C | 新创建或温度≥60°C | `lifecycle_stage='active'` | 最高 | 主表优先 |
| **次要 (Secondary)** | 20-60°C | 温度降至20-60°C | `lifecycle_stage='secondary'` | 中等 | 降级索引 |
| **归档 (Archived)** | 5-20°C | 温度降至5-20°C | `lifecycle_stage='archived'` | 低 | 归档存储 |
| **删除 (Deleted)** | <5°C | 温度降至<5°C | `lifecycle_stage='deleted'` | 无 | 物理清理 |

### 1.4 记忆属性分类（温度衍生）

| 属性类型 | 触发条件 | 数据库标记 | 保护级别 | 降温策略 |
|---------|---------|-----------|---------|---------|
| **普通记忆** | 默认 | `is_important=0, is_crystallized=0` | 标准 | 正常降温 |
| **重要记忆** | 温度 ≥80°C 或 手动标注 | `is_important=1, is_crystallized=0` | 高级 | 减缓 60% 降温，最低 30°C |
| **固化记忆** | 温度 ≥90°C + 特殊意义 或 用户锁定 | `is_crystallized=1` | 最高 | **永不降温**，永久保存 |

> **特殊说明**: 
> - 重要记忆是温度的自然衍生结果，当记忆被频繁访问、强情感关联或经验总结时自动升级
> - 固化记忆 (Crystallized) 是最高级别的永久记忆，模拟人类的"核心记忆"，如纪念日、人生经验、重大情感关联等
> - Agent 可自主判断某些记忆的特殊意义，主动标记为固化记忆

### 1.5 记忆属性升级路径

```
普通记忆 ──温度≥80°C──→ 重要记忆 ──温度≥90°C + 特殊意义──→ 固化记忆
    ↑                      ↑                                ↑
  新创建              频繁访问/强情感                     Agent 自主判断
  (50°C)              经验总结/关联多                     用户手动锁定
                      自动升级                          永久保存，永不遗忘
```

> **特殊保护机制**: 高情感关联、特殊意义关联的记忆可延缓降温，保持最低温度下限。固化记忆完全不参与降温机制。

## 2. 温度计算模型

### 2.1 温度核心公式

```
T(t) = T_base + ΔT_hit + ΔT_emotion + ΔT_relation + ΔT_decay

其中:
  T(t)        = 当前温度
  T_base      = 基础温度 (默认 50°C)
  ΔT_hit      = 命中升温
  ΔT_emotion  = 情感加成
  ΔT_relation = 关联加成
  ΔT_decay    = 时间衰减 (负值)
```

### 2.2 升温机制

#### 2.2.1 访问升温 (Access Warming)

```python
@classmethod
def on_access(cls, current_temp: float,
              importance: float = 0.5,
              recall_count: int = 0) -> float:
    """记忆被访问时更新温度
    
    Args:
        current_temp: 当前温度
        importance: 重要性分数 (0.0 - 1.0)
        recall_count: 回忆次数
        
    Returns:
        float: 更新后的温度
    """
    # 访问升温
    access_boost = 10.0 * importance
    
    # 回忆次数加成
    recall_boost = min(recall_count * 2.0, 20.0)
    
    # 计算新温度
    new_temp = current_temp + access_boost + recall_boost
    
    # 限制在有效范围内
    return max(0.0, min(100.0, new_temp))
```

**升温示例**:
```
初始温度: 50°C，重要性: 0.5，回忆次数: 0
第 1 次访问: 50 + 10 * 0.5 + 0 = 55°C
第 2 次访问: 55 + 10 * 0.5 + 0 = 60°C
第 3 次访问 (回忆次数+1): 60 + 10 * 0.5 + 2 = 67°C
```

#### 2.2.2 情感保护 (Emotion Protection)

```python
# 情感保护参数
_CLASS_EMOTIONAL_PROTECTION_THRESHOLD = 0.5
_CLASS_EMOTIONAL_PROTECTION_FACTOR = 0.6

def calculate_emotion_protection(emotion_score: float) -> float:
    """
    情感保护计算
    强情感记忆衰减更慢
    """
    if emotion_score > _CLASS_EMOTIONAL_PROTECTION_THRESHOLD:
        return _CLASS_EMOTIONAL_PROTECTION_FACTOR  # 0.6，减缓40%衰减
    else:
        return 1.0  # 无保护
```
        return 0.0
    
    # 取最高情感强度的加成
    max_bonus = max(
        EMOTION_TEMPERATURE_BONUS.get(tag.value, 0.0)
        for tag in emotion_tags
    )
    
    # 情感强度调节
    intensity_factor = abs(emotion_score)  # 0.0 - 1.0
    
    return max_bonus * intensity_factor
```

### 2.3 降温机制 (贝叶斯遗忘曲线)

#### 2.3.1 贝叶斯遗忘曲线公式

```python
@classmethod
def on_decay(cls, current_temp: float,
             days_idle: float,
             importance: float = 0.5,
             emotion_score: float = 0.0,
             recall_count: int = 0) -> float:
    """计算温度衰减
    
    Args:
        current_temp: 当前温度
        days_idle: 空闲天数
        importance: 重要性分数 (0.0 - 1.0)
        emotion_score: 情感分数 (0.0 - 1.0)
        recall_count: 回忆次数
        
    Returns:
        float: 衰减后的温度
    """
    # 1. 计算衰减因子（贝叶斯遗忘曲线）
    curve_factor = cls._calculate_curve_factor(days_idle)
    
    # 2. 情感保护
    emotion_protect = (cls._CLASS_EMOTIONAL_PROTECTION_FACTOR
                      if emotion_score > cls._CLASS_EMOTIONAL_PROTECTION_THRESHOLD
                      else 1.0)
    
    # 3. 饱和效应
    saturation_factor = 1.0 - (current_temp / 100.0) ** 2
    
    # 4. 重要性加权（重要记忆衰减更少）
    importance_weight = 1.0 - 0.5 * importance
    
    # 5. 回忆次数保护
    recall_protection = min(1.0 + recall_count * 0.05, 1.5)
    
    # 6. 计算最终衰减
    decay = curve_factor * emotion_protect * saturation_factor * importance_weight
    
    # 应用衰减
    new_temp = current_temp * (1.0 - decay)
    
    # 最后应用回忆保护（防止过度衰减）
    new_temp = max(new_temp, current_temp * recall_protection * 0.1)
    
    return max(0.0, min(100.0, new_temp))

@classmethod
def _calculate_curve_factor(cls, days_idle: float) -> float:
    """计算遗忘曲线因子
    
    基于空闲天数的分段函数：
    - ≤1天: 2.0 (快速衰减)
    - ≤7天: 1.0 (正常衰减)
    - ≤30天: 0.5 (慢速衰减)
    - >30天: 0.2 (极慢衰减)
    """
    if days_idle <= 1:
        return 2.0
    elif days_idle <= 7:
        return 1.0
    elif days_idle <= 30:
        return 0.5
    else:
        return 0.2
```

#### 2.3.2 遗忘曲线可视化

```
温度 (°C)
100 │
    │  ╭───────── 无情感记忆 (快速遗忘)
 80 │ ╱
    │╱
 60 │╲
    │ ╲
 40 │  ╲╭──────── 有情感记忆 (缓慢遗忘)
    │   ╲
 20 │    ╲────── 低重要性记忆
    │     ╲
  0 │______╲______→ 时间 (天)
    0   7   14  30  60  90
```

### 2.4 综合温度计算

```python
class TemperatureEngine:
    """
    温度引擎
    
    管理记忆的"温度"（活跃度），实现贝叶斯遗忘曲线。
    温度值范围：0.0（完全遗忘）到 100.0（高度活跃）
    """
    
    # 生命周期阶段
    STAGE_ACTIVE = "active"
    STAGE_SECONDARY = "secondary"
    STAGE_ARCHIVED = "archived"
    STAGE_DELETED = "deleted"
    
    # 生命周期阈值
    THRESHOLD_SECONDARY = 60.0   # ≥60°C 为活跃
    THRESHOLD_ARCHIVED = 20.0    # 20-60°C 为次要
    THRESHOLD_DELETED = 5.0      # 5-20°C 为归档
                                # <5°C 为删除
    
    # 类级别默认值
    _CLASS_DECAY_RATE = 0.1
    _CLASS_EMOTIONAL_PROTECTION_THRESHOLD = 0.5
    _CLASS_EMOTIONAL_PROTECTION_FACTOR = 0.6
    
    @classmethod
    def on_access(cls, current_temp: float,
                  importance: float = 0.5,
                  recall_count: int = 0) -> float:
        """记忆被访问时更新温度
        
        Args:
            current_temp: 当前温度
            importance: 重要性分数 (0.0 - 1.0)
            recall_count: 回忆次数
            
        Returns:
            float: 更新后的温度
        """
        # 访问升温
        access_boost = 10.0 * importance
        
        # 回忆次数加成
        recall_boost = min(recall_count * 2.0, 20.0)
        
        # 计算新温度
        new_temp = current_temp + access_boost + recall_boost
        
        # 限制在有效范围内
        return max(0.0, min(100.0, new_temp))
    
    @classmethod
    def on_decay(cls, current_temp: float,
                 days_idle: float,
                 importance: float = 0.5,
                 emotion_score: float = 0.0,
                 recall_count: int = 0) -> float:
        """计算温度衰减
        
        Args:
            current_temp: 当前温度
            days_idle: 空闲天数
            importance: 重要性分数 (0.0 - 1.0)
            emotion_score: 情感分数 (0.0 - 1.0)
            recall_count: 回忆次数
            
        Returns:
            float: 衰减后的温度
        """
        # 1. 计算衰减因子（贝叶斯遗忘曲线）
        curve_factor = cls._calculate_curve_factor(days_idle)
        
        # 2. 情感保护
        emotion_protect = (cls._CLASS_EMOTIONAL_PROTECTION_FACTOR
                          if emotion_score > cls._CLASS_EMOTIONAL_PROTECTION_THRESHOLD
                          else 1.0)
        
        # 3. 饱和效应
        saturation_factor = 1.0 - (current_temp / 100.0) ** 2
        
        # 4. 重要性加权（重要记忆衰减更少）
        importance_weight = 1.0 - 0.5 * importance
        
        # 5. 回忆次数保护
        recall_protection = min(1.0 + recall_count * 0.05, 1.5)
        
        # 6. 计算最终衰减
        decay = curve_factor * emotion_protect * saturation_factor * importance_weight
        
        # 应用衰减
        new_temp = current_temp * (1.0 - decay)
        
        # 最后应用回忆保护（防止过度衰减）
        new_temp = max(new_temp, current_temp * recall_protection * 0.1)
        
        return max(0.0, min(100.0, new_temp))
    
    return memory
    
    def _check_attribute_upgrade(self, memory: Memory) -> Memory:
        """
        检查记忆属性升级
        普通 → 重要 → 固化
        """
        # 1. 普通 → 重要 (温度 ≥ 80°C 或满足其他条件)
        if not memory.is_important and not memory.is_crystallized:
            if self._should_upgrade_to_important(memory):
                memory.is_important = True
                logger.info(f"Memory {memory.id} upgraded to IMPORTANT")
        
        # 2. 重要 → 固化 (温度 ≥ 90°C + 特殊意义)
        if memory.is_important and not memory.is_crystallized:
            if self._should_crystallize(memory):
                memory.is_crystallized = True
                memory.temperature = 95.0  # 固化后设为高温
                memory.lifecycle_stage = 'active'  # 重置为活跃
                logger.info(f"Memory {memory.id} CRYSTALLIZED (permanent)")
        
        return memory
    
    def _should_upgrade_to_important(self, memory: Memory) -> bool:
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
        
        relation_count = self._get_relation_count(memory.id)
        if relation_count >= 5 and memory.temperature >= 60.0:
            return True
        
        return False
    
    def _should_crystallize(self, memory: Memory) -> bool:
        """
        判断是否固化为永久记忆
        条件 (满足任一):
        1. 温度 ≥ 90°C 且是重要记忆
        2. Agent 自主判断有特殊意义 (通过 metadata 标记)
        3. 用户手动锁定
        4. 包含特殊关键词 (纪念日、生日、结婚等)
        """
        # 温度 + 重要性
        if memory.temperature >= 90.0 and memory.is_important:
            # 进一步检查特殊意义
            if self._has_special_meaning(memory):
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
        content_lower = memory.content.lower()
        for keyword in special_keywords:
            if keyword in content_lower:
                return True
        
        return False
    
    def _has_special_meaning(self, memory: Memory) -> bool:
        """
        判断记忆是否有特殊意义
        """
        # 检查情感强度
        if memory.emotion_score >= 0.9:
            return True
        
        # 检查关联深度
        relation_count = self._get_relation_count(memory.id)
        if relation_count >= 10:
            return True
        
        # 检查是否为经验总结
        if memory.category == 'experience' and memory.access_count >= 15:
            return True
        
        # 检查 metadata 中的特殊标记
        return memory.metadata.get('special_meaning', False)
        self,
        temperature: float,
        days_idle: int,
        memory: Memory
    ) -> str:
        """
        确定生命周期阶段
        综合温度和空闲时间判断
        """
        # 阶段转换规则:
        
        # 活跃 → 次要: 7 天未命中且温度 < 50°C
        if (memory.lifecycle_stage == 'active' and 
            days_idle >= self.DAYS_TO_SECONDARY and 
            temperature < self.ACTIVE_THRESHOLD):
            return 'secondary'
        
        # 次要 → 归档: 30 天未命中且温度 < 20°C
        if (memory.lifecycle_stage in ['active', 'secondary'] and 
            days_idle >= self.DAYS_TO_ARCHIVED and 
            temperature < self.ARCHIVED_THRESHOLD * 4):  # 20°C
            return 'archived'
        
        # 归档 → 删除: 60 天未命中且温度 < 5°C
        if (memory.lifecycle_stage == 'archived' and 
            days_idle >= self.DAYS_TO_DELETE and 
            temperature < self.ARCHIVED_THRESHOLD):
            return 'deleted'
        
        # 特殊保护: 高情感记忆永不降至 20°C 以下
        if self._has_strong_emotion(memory):
            return max_stage(memory.lifecycle_stage, 'secondary')
        
        # 特殊保护: 强关联记忆永不降至 10°C 以下
        if self._has_strong_relations(memory):
            return max_stage(memory.lifecycle_stage, 'archived')
        
        return memory.lifecycle_stage
```

## 3. 生命周期管理

### 3.1 生命周期状态机

```
                ┌─────────────────────────────────────┐
                │                                     │
                ▼  创建 (默认50°C)                    │
            ┌────────┐                                │
            │ ACTIVE │                                │
            │ ≥60°C  │                                │
            └───┬────┘                                │
                │ 温度降至20-60°C                     │
                ▼                                     │
            ┌────────────┐                            │
            │ SECONDARY  │                            │
            │ 20-60°C    │                            │
            └───┬────────┘                            │
                │ 温度降至5-20°C                      │
                ▼                                     │
            ┌────────┐                                │
            │ARCHIVED│                                │
            │ 5-20°C │                                │
            └───┬────┘                                │
                │ 温度降至<5°C                        │
                ▼                                     │
            ┌────────┐                                │
            │ DELETED│────────────────────────────────┘
            │ <5°C   │  (物理删除)
            └────────┘
                
    ←─── 命中升温可逆向转换 ───→
```

### 3.2 自动衰减调度器

```python
class TemperatureDecayScheduler:
    """
    温度衰减调度器
    定期扫描并更新所有记忆温度
    """
    
    def __init__(self, db_connection, config: Optional[Dict] = None):
        self.db = db_connection
        self.config = config or {}
        self.engine = TemperatureEngine()
    
    def run_decay_cycle(self):
        """
        执行一轮温度衰减
        建议: 每小时或每天低峰期执行
        """
        cursor = self.db.cursor()
        
        # 1. 查询需要降温的记忆 (按生命周期分批)
        for stage in ['active', 'secondary', 'archived']:
            cursor.execute("""
                SELECT id, temperature, last_accessed_at, 
                       access_count, lifecycle_stage
                FROM memories
                WHERE lifecycle_stage = ?
                  AND last_accessed_at < datetime('now', '-1 hours')
                ORDER BY temperature ASC
                LIMIT 1000  -- 分批处理
            """, (stage,))
            
            memories = cursor.fetchall()
            
            # 2. 批量更新温度
            for row in memories:
                memory = self._row_to_memory(row)
                updated = self.engine.update_temperature(memory)
                
                # 检查是否需要状态转换
                if updated.lifecycle_stage != memory.lifecycle_stage:
                    self._handle_stage_transition(memory, updated)
                
                # 写入数据库
                self._save_temperature_update(updated)
            
            # 提交批次
            self.db.commit()
        
        # 3. 清理已删除的记忆
        self._cleanup_deleted_memories()
    
    def _handle_stage_transition(
        self, 
        old_memory: Memory, 
        new_memory: Memory
    ):
        """处理生命周期阶段转换"""
        old_stage = old_memory.lifecycle_stage
        new_stage = new_memory.lifecycle_stage
        
        # 记录转换日志
        logger.info(
            f"Memory {new_memory.id} transition: "
            f"{old_stage} → {new_stage} "
            f"(T: {old_memory.temperature:.1f}°C → {new_memory.temperature:.1f}°C)"
        )
        
        # 归档处理: 移出主表高频查询范围
        if new_stage == 'archived':
            self._archive_memory(new_memory)
        
        # 删除处理: 物理删除或软标记
        elif new_stage == 'deleted':
            self._schedule_deletion(new_memory)
    
    def _archive_memory(self, memory: Memory):
        """归档记忆"""
        cursor = self.db.cursor()
        
        # 更新主表标记
        cursor.execute("""
            UPDATE memories
            SET lifecycle_stage = 'archived',
                is_archived = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (memory.id,))
        
        # 可选项: 移动到归档存储表
        # self._move_to_archive_table(memory)
    
    def _schedule_deletion(self, memory: Memory):
        """调度删除"""
        cursor = self.db.cursor()
        
        # 软删除 (保留数据 30 天用于恢复)
        cursor.execute("""
            UPDATE memories
            SET lifecycle_stage = 'deleted',
                is_archived = 1,
                expires_at = datetime('now', '+30 days'),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (memory.id,))
        
        # 记录删除日志
        logger.info(f"Memory {memory.id} scheduled for deletion")
    
    def _cleanup_deleted_memories(self):
        """清理已删除的记忆"""
        cursor = self.db.cursor()
        
        # 删除超过 30 天的软删除记录
        cursor.execute("""
            DELETE FROM memories
            WHERE lifecycle_stage = 'deleted'
              AND expires_at < CURRENT_TIMESTAMP
        """)
        
        if cursor.rowcount > 0:
            logger.info(f"Cleaned up {cursor.rowcount} deleted memories")
            self.db.commit()
```

## 4. 查询优先级与温度

### 4.1 温度加权查询

```sql
-- 上下文记忆检索: 优先返回高温记忆
SELECT id, content, temperature, weight
FROM memories
WHERE agent_id = ? 
  AND lifecycle_stage = 'active'
ORDER BY 
  (temperature * 0.4 + weight * 0.3 + access_count * 0.3) DESC
LIMIT ?;

-- 使用温度索引加速
-- 索引: idx_memories_temp_active (见数据库架构文档)
```

### 4.2 各生命周期查询策略

| 查询场景 | 查询范围 | 温度过滤 | 排序策略 |
|---------|---------|---------|---------|
| **上下文构建** | active | T >= 30°C | 温度加权 |
| **深度检索** | active + secondary | T >= 10°C | 温度 + 相关性 |
| **归档查询** | archived | 无 | 时间倒序 |
| **记忆巩固** | secondary | T 上升中 | 升温潜力 |

### 4.3 缓存层与温度协同

```python
def select_memories_for_cache(memory_list: List[Memory]) -> List[Memory]:
    """
    根据温度决定哪些记忆应驻留缓存
    """
    # 高温记忆优先缓存
    hot_memories = [m for m in memory_list if m.temperature >= 50]
    
    # 升温中的次要记忆也可能缓存
    warming_secondary = [
        m for m in memory_list 
        if m.lifecycle_stage == 'secondary' and m.temperature > 30
    ]
    
    # 归档记忆不缓存
    return hot_memories + warming_secondary
```

## 5. 数据库索引优化 (温度相关)

### 5.1 温度索引设计

```sql
-- 活跃记忆温度索引 (高频使用)
CREATE INDEX idx_memories_temp_active ON memories(
    agent_id, temperature DESC, lifecycle_stage
) WHERE lifecycle_stage = 'active' AND temperature >= 30;

-- 次要记忆温度索引 (中频使用)
CREATE INDEX idx_memories_temp_secondary ON memories(
    agent_id, temperature DESC, last_accessed_at
) WHERE lifecycle_stage = 'secondary';

-- 降温扫描索引 (用于衰减调度器)
CREATE INDEX idx_memories_decay_scan ON memories(
    lifecycle_stage, last_accessed_at ASC, temperature
);

-- 归档记忆索引 (低频使用)
CREATE INDEX idx_memories_archived ON memories(
    agent_id, created_at DESC, temperature
) WHERE lifecycle_stage = 'archived';

-- 待删除记忆索引
CREATE INDEX idx_memories_pending_delete ON memories(
    lifecycle_stage, expires_at
) WHERE lifecycle_stage = 'deleted' AND expires_at IS NOT NULL;
```

### 5.2 复合温度查询索引

```sql
-- 场景: 获取 Agent 的高温活跃记忆
CREATE INDEX idx_memories_hot_active ON memories(
    agent_id, temperature DESC, weight DESC, access_count DESC
) WHERE lifecycle_stage = 'active' AND temperature >= 50;

-- 场景: 记忆巩固 (升温潜力大的记忆)
CREATE INDEX idx_memories_consolidation ON memories(
    lifecycle_stage, access_count ASC, temperature ASC
) WHERE lifecycle_stage = 'secondary' AND temperature < 40;
```

### 5.3 完整 DDL 更新 (温度字段 + 索引)

```sql
-- 在 memories 主表中添加温度字段 (见 11-database-architecture.md)
ALTER TABLE memories ADD COLUMN temperature REAL DEFAULT 50.0;
ALTER TABLE memories ADD COLUMN last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE memories ADD COLUMN lifecycle_stage TEXT DEFAULT 'active';

-- 添加重要记忆和固化记忆标记字段
ALTER TABLE memories ADD COLUMN is_important INTEGER DEFAULT 0;
ALTER TABLE memories ADD COLUMN is_crystallized INTEGER DEFAULT 0;
ALTER TABLE memories ADD COLUMN crystallized_at TIMESTAMP;

-- 添加温度相关索引
CREATE INDEX IF NOT EXISTS idx_memories_temp_active ON memories(
    agent_id, temperature DESC, lifecycle_stage
) WHERE lifecycle_stage = 'active' AND temperature >= 30;

CREATE INDEX IF NOT EXISTS idx_memories_temp_secondary ON memories(
    agent_id, temperature DESC, last_accessed_at
) WHERE lifecycle_stage = 'secondary';

CREATE INDEX IF NOT EXISTS idx_memories_decay_scan ON memories(
    lifecycle_stage, last_accessed_at ASC, temperature
);

CREATE INDEX IF NOT EXISTS idx_memories_hot_active ON memories(
    agent_id, temperature DESC, weight DESC, access_count DESC
) WHERE lifecycle_stage = 'active' AND temperature >= 50;

CREATE INDEX IF NOT EXISTS idx_memories_consolidation ON memories(
    lifecycle_stage, access_count ASC, temperature ASC
) WHERE lifecycle_stage = 'secondary' AND temperature < 40;

CREATE INDEX IF NOT EXISTS idx_memories_pending_delete ON memories(
    lifecycle_stage, expires_at
) WHERE lifecycle_stage = 'deleted' AND expires_at IS NOT NULL;

-- 重要记忆索引 (优先查询)
CREATE INDEX IF NOT EXISTS idx_memories_important ON memories(
    agent_id, temperature DESC, is_important
) WHERE is_important = 1;

-- 固化记忆索引 (永久保存，最高优先级)
CREATE INDEX IF NOT EXISTS idx_memories_crystallized ON memories(
    agent_id, crystallized_at DESC, temperature DESC
) WHERE is_crystallized = 1;

-- 待固化候选索引 (温度≥85°C 的重要记忆)
CREATE INDEX IF NOT EXISTS idx_memories_crystallization_candidates ON memories(
    is_important, temperature DESC, access_count DESC
) WHERE is_important = 1 AND temperature >= 85 AND is_crystallized = 0;
```

## 6. 特殊保护机制

### 6.1 情感保护

```python
def apply_emotion_protection(memory: Memory) -> float:
    """
    高情感记忆的温度保护
    防止重要情感记忆被遗忘
    """
    # 强情感记忆 (joy, surprise 强度 > 0.8)
    if memory.emotion_score > 0.8:
        return max(memory.temperature, 30.0)  # 不低于 30°C
    
    # 中情感记忆
    if memory.emotion_score > 0.5:
        return max(memory.temperature, 20.0)  # 不低于 20°C
    
    return memory.temperature
```

### 6.2 关联保护

```python
def apply_relation_protection(memory: Memory) -> float:
    """
    强关联记忆的温度保护
    """
    # 获取关联数量
    relation_count = get_relation_count(memory.id)
    
    # 关联越多，温度下限越高
    if relation_count >= 5:
        return max(memory.temperature, 25.0)
    elif relation_count >= 3:
        return max(memory.temperature, 15.0)
    
    return memory.temperature
```

### 6.3 用户手动标记

```sql
-- 用户可手动标记重要记忆 (永久保护)
ALTER TABLE memories ADD COLUMN is_pinned INTEGER DEFAULT 0;

-- 被钉住的记忆不降温
CREATE INDEX idx_memories_pinned ON memories(is_pinned, temperature)
    WHERE is_pinned = 1;
```

## 7. 记忆巩固机制

### 7.1 巩固触发条件

```python
def should_consolidate(memory: Memory) -> bool:
    """
    判断是否应该巩固记忆 (短期→长期)
    
    巩固条件:
    1. 访问次数 >= 3 次
    2. 温度 >= 60°C
    3. 当前为短期记忆
    """
    return (
        memory.access_count >= 3 and
        memory.temperature >= 60.0 and
        memory.type == 'short_term'
    )
```

### 7.2 巩固流程

```
短期记忆 (被频繁访问)
        ↓
温度升至 60°C 以上
        ↓
触发巩固机制
        ↓
转换为长期记忆
    - type: short_term → long_term
    - weight: * 1.5
    - expires_at: None
        ↓
建立更多关联
        ↓
温度保护增强
```

## 8. 监控与指标

### 8.1 温度分布监控

```python
class TemperatureMetrics:
    """温度分布指标"""
    
    def get_temperature_distribution(self, agent_id: str) -> Dict:
        """获取温度分布统计"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT 
                lifecycle_stage,
                COUNT(*) as count,
                AVG(temperature) as avg_temp,
                MIN(temperature) as min_temp,
                MAX(temperature) as max_temp
            FROM memories
            WHERE agent_id = ?
            GROUP BY lifecycle_stage
        """, (agent_id,))
        
        return {row[0]: {
            'count': row[1],
            'avg_temp': row[2],
            'min_temp': row[3],
            'max_temp': row[4]
        } for row in cursor.fetchall()}
    
    def get_forgetting_rate(self, agent_id: str) -> float:
        """获取遗忘率 (每日降温的记忆比例)"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM memories
            WHERE agent_id = ?
              AND temperature < 50
              AND last_accessed_at < datetime('now', '-7 days')
        """, (agent_id,))
        
        cooling_count = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM memories
            WHERE agent_id = ?
        """, (agent_id,))
        
        total_count = cursor.fetchone()[0]
        
        return cooling_count / total_count if total_count > 0 else 0.0
```

### 8.2 健康度指标

| 指标 | 健康范围 | 说明 |
|------|---------|------|
| **高温记忆占比** | 20-40% | 活跃记忆应保持一定比例 |
| **遗忘率** | < 10%/天 | 每日降温记忆不超过 10% |
| **平均温度** | 40-60°C | 整体温度保持适中 |
| **归档率** | < 20% | 归档记忆不超过 20% |
| **巩固率** | 15-25% | 短期→长期转换率 |

## 9. 配置示例

### 9.1 温度系统配置

```yaml
# temperature.yaml
temperature:
  # 基础设置
  default_temperature: 50.0     # 新记忆初始温度
  min_temperature: 0.0          # 最低温度
  max_temperature: 100.0        # 最高温度
  
  # 升温参数
  hit_boost_base: 5.0           # 每次命中基础升温
  hit_boost_max: 15.0           # 单次命中最大升温
  emotion_protection_factor: 0.6  # 情感保护系数
  relation_protection_factor: 0.7  # 关联保护系数
  
  # 降温参数
  decay_rate_base: 0.05         # 每日基础衰减率
  decay_curve_factor:           # 遗忘曲线因子
    first_day: 2.0              # 24 小时内
    first_week: 1.0             # 一周内
    first_month: 0.5            # 一月内
    after_month: 0.2            # 一月后
  
  # 生命周期阈值
  lifecycle_thresholds:
    active:
      min_temperature: 60.0     # ≥60°C 为活跃
      max_idle_days: 7
    secondary:
      min_temperature: 20.0     # 20-60°C 为次要
      max_idle_days: 30
    archived:
      min_temperature: 5.0      # 5-20°C 为归档
      max_idle_days: 60
    deleted:
      min_temperature: 0.0      # <5°C 为删除
      cleanup_after_days: 30
  
  # 调度器配置
  scheduler:
    run_interval_minutes: 60    # 每小时执行一次衰减
    batch_size: 1000            # 每批处理数量
    run_at_off_peak: true       # 低峰期执行
  
  # 保护机制
  protection:
    strong_emotion_min_temp: 30.0  # 强情感最低温度
    strong_relation_min_temp: 15.0 # 强关联最低温度
    pinned_never_decay: true       # 钉住记忆不降温
```

## 10. 测试用例

### 10.1 单元测试

```python
def test_temperature_increase_on_access():
    """测试访问升温"""
    # 初始温度 50°C，重要性 0.5，回忆次数 0
    new_temp = TemperatureEngine.on_access(
        current_temp=50.0,
        importance=0.5,
        recall_count=0
    )
    
    # 50 + 10 * 0.5 + 0 = 55°C
    assert new_temp == 55.0
    
    # 测试回忆次数加成
    new_temp_with_recall = TemperatureEngine.on_access(
        current_temp=50.0,
        importance=0.5,
        recall_count=3
    )
    
    # 50 + 10 * 0.5 + min(3 * 2.0, 20.0) = 50 + 5 + 6 = 61°C
    assert new_temp_with_recall == 61.0

def test_temperature_decay_after_idle():
    """测试空闲降温"""
    # 初始温度 60°C，空闲 8 天
    new_temp = TemperatureEngine.on_decay(
        current_temp=60.0,
        days_idle=8.0,
        importance=0.5,
        emotion_score=0.0,
        recall_count=5
    )
    
    # 应该降温
    assert new_temp < 60.0
    
    # 测试情感保护
    new_temp_with_emotion = TemperatureEngine.on_decay(
        current_temp=60.0,
        days_idle=8.0,
        importance=0.5,
        emotion_score=0.8,  # 强情感
        recall_count=5
    )
    
    # 有情感保护时降温更少
    assert new_temp_with_emotion > new_temp

def test_emotion_protection():
    """测试情感保护"""
    # 无情感保护
    temp_without_emotion = TemperatureEngine.on_decay(
        current_temp=40.0,
        days_idle=10.0,
        importance=0.5,
        emotion_score=0.0,  # 无情感
        recall_count=0
    )
    
    # 有情感保护
    temp_with_emotion = TemperatureEngine.on_decay(
        current_temp=40.0,
        days_idle=10.0,
        importance=0.5,
        emotion_score=0.9,  # 强情感
        recall_count=0
    )
    
    # 有情感保护时降温更少
    assert temp_with_emotion > temp_without_emotion

def test_lifecycle_transition_to_archived():
    """测试归档转换"""
    # 温度 15°C，空闲 35 天，低重要性
    new_temp = TemperatureEngine.on_decay(
        current_temp=15.0,
        days_idle=35.0,
        importance=0.5,
        emotion_score=0.0,
        recall_count=0
    )
    
    # 检查生命周期阶段
    stage = TemperatureEngine.get_lifecycle_stage(new_temp)
    
    # 温度应降至归档范围 (5-20°C)
    assert stage in ['archived', 'deleted']

def test_memory_consolidation():
    """测试记忆巩固"""
    # 温度 65°C，访问 5 次
    new_temp = TemperatureEngine.on_access(
        current_temp=65.0,
        importance=0.5,
        recall_count=5
    )
    
    # 检查生命周期阶段
    stage = TemperatureEngine.get_lifecycle_stage(new_temp)
    
    # 应该保持活跃
    assert stage == 'active'
```

### 10.2 集成测试

```python
def test_full_lifecycle_flow():
    """测试完整生命周期流程"""
    # 1. 创建记忆 (50°C, active)
    memory = create_test_memory()
    assert memory.temperature == 50.0
    assert memory.lifecycle_stage == 'active'
    
    # 2. 多次访问 (温度上升)
    for _ in range(5):
        memory = access_memory(memory)
    assert memory.temperature > 50.0
    
    # 3. 停止访问 8 天 (降为 secondary)
    simulate_idle(memory, days=8)
    memory = update_temperature(memory)
    assert memory.lifecycle_stage == 'secondary'
    
    # 4. 停止访问 35 天 (降为 archived)
    simulate_idle(memory, days=35)
    memory = update_temperature(memory)
    assert memory.lifecycle_stage == 'archived'
    
    # 5. 停止访问 65 天 (标记删除)
    simulate_idle(memory, days=65)
    memory = update_temperature(memory)
    assert memory.lifecycle_stage == 'deleted'
```
