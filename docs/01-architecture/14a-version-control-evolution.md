# 记忆版本控制与演变追踪架构设计

## 1. 概述

### 1.1 设计理念

用户的记忆会随时间**演变、变化、修正**。版本控制机制记录记忆的完整演变历史，让Agent能理解：

> **"用户从喜欢咖啡变成讨厌咖啡，现在又喜欢了" —— 这不是冲突，而是偏好演变。**

### 1.2 版本控制架构

```
版本控制系统
├── 记忆版本历史 (Memory Version History)
│   ├── 完整内容快照
│   ├── 变更原因记录
│   └── 版本链追踪
│
├── 偏好演变分析 (Preference Evolution)
│   ├── 偏好变化趋势
│   ├── 演变周期识别
│   └── 当前偏好推断
│
├── 版本回滚 (Version Rollback)
│   ├── 历史版本恢复
│   ├── 用户主动修正
│   └── 冲突自动回滚
│
└── 演变可视化 (Evolution Visualization)
    ├── 时间线展示
    ├── 变化点标记
    └── 演变图谱
```

### 1.3 与冲突检测的融合

| 维度 | 纯冲突检测 | 融合版本控制 |
|------|-----------|-------------|
| **冲突处理** | 检测并消解 | 检测→判断是否为演变→记录版本 |
| **偏好变化** | 标记冲突 | 识别为正常演变，保留历史 |
| **数据保留** | 旧记忆归档 | 旧记忆保留版本历史 |
| **查询能力** | 只能查当前 | 可查任意时间点状态 |

---

## 2. 记忆版本历史

### 2.1 版本数据模型

```python
@dataclass
class MemoryVersion:
    """记忆版本"""
    version_id: str
    memory_id: str
    version_number: int
    content_snapshot: str
    metadata_snapshot: Dict
    change_type: str  # created/updated/conflict_resolved/user_corrected/expired
    change_reason: str
    previous_version_id: Optional[str]
    created_at: datetime
    created_by: str  # system/user/agent
    
    def to_dict(self) -> Dict:
        return {
            'version_id': self.version_id,
            'memory_id': self.memory_id,
            'version_number': self.version_number,
            'content': self.content_snapshot,
            'change_type': self.change_type,
            'change_reason': self.change_reason,
            'created_at': self.created_at.isoformat()
        }

class MemoryVersionChain:
    """记忆版本链"""
    def __init__(self, memory_id: str):
        self.memory_id = memory_id
        self.versions: List[MemoryVersion] = []
    
    def add_version(self, version: MemoryVersion):
        self.versions.append(version)
        self.versions.sort(key=lambda v: v.version_number)
    
    def get_latest(self) -> Optional[MemoryVersion]:
        return self.versions[-1] if self.versions else None
    
    def get_version_at_time(self, target_time: datetime) -> Optional[MemoryVersion]:
        """获取指定时间点的版本"""
        for version in reversed(self.versions):
            if version.created_at <= target_time:
                return version
        return None
    
    def get_evolution_timeline(self) -> List[Dict]:
        """获取演变时间线"""
        return [
            {
                'version': v.version_number,
                'content': v.content_snapshot,
                'change_type': v.change_type,
                'change_reason': v.change_reason,
                'created_at': v.created_at.isoformat()
            }
            for v in self.versions
        ]
```

### 2.2 版本管理器

```python
class MemoryVersionManager:
    """
    记忆版本管理器
    管理记忆的完整版本历史
    """
    
    def __init__(self, db_connection):
        self.db = db_connection
        self._create_tables()
    
    def _create_tables(self):
        """创建版本表"""
        cursor = self.db.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_versions (
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
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_versions_memory 
            ON memory_versions(memory_id, version_number DESC)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_versions_created_at 
            ON memory_versions(created_at DESC)
        """)
        
        self.db.commit()
    
    def create_version(
        self,
        memory_id: str,
        content: str,
        metadata: Dict,
        change_type: str,
        change_reason: str,
        created_by: str = 'system'
    ) -> MemoryVersion:
        """创建新版本"""
        cursor = self.db.cursor()
        
        # 获取当前最大版本号
        cursor.execute("""
            SELECT MAX(version_number) FROM memory_versions
            WHERE memory_id = ?
        """, (memory_id,))
        
        row = cursor.fetchone()
        max_version = row[0] if row[0] else 0
        new_version_number = max_version + 1
        
        # 获取前一个版本ID
        cursor.execute("""
            SELECT version_id FROM memory_versions
            WHERE memory_id = ?
            ORDER BY version_number DESC
            LIMIT 1
        """, (memory_id,))
        
        row = cursor.fetchone()
        previous_version_id = row[0] if row else None
        
        # 创建版本
        version = MemoryVersion(
            version_id=str(uuid.uuid4()),
            memory_id=memory_id,
            version_number=new_version_number,
            content_snapshot=content,
            metadata_snapshot=metadata,
            change_type=change_type,
            change_reason=change_reason,
            previous_version_id=previous_version_id,
            created_at=datetime.now(),
            created_by=created_by
        )
        
        # 存储
        cursor.execute("""
            INSERT INTO memory_versions (
                version_id, memory_id, version_number,
                content_snapshot, metadata_snapshot,
                change_type, change_reason, previous_version_id,
                created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            version.version_id,
            version.memory_id,
            version.version_number,
            version.content_snapshot,
            json.dumps(version.metadata_snapshot),
            version.change_type,
            version.change_reason,
            version.previous_version_id,
            version.created_at.isoformat(),
            version.created_by
        ))
        
        self.db.commit()
        return version
    
    def get_version_chain(self, memory_id: str) -> MemoryVersionChain:
        """获取记忆的版本链"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT * FROM memory_versions
            WHERE memory_id = ?
            ORDER BY version_number ASC
        """, (memory_id,))
        
        chain = MemoryVersionChain(memory_id)
        for row in cursor.fetchall():
            version = MemoryVersion(
                version_id=row[0],
                memory_id=row[1],
                version_number=row[2],
                content_snapshot=row[3],
                metadata_snapshot=json.loads(row[4]) if row[4] else {},
                change_type=row[5],
                change_reason=row[6],
                previous_version_id=row[7],
                created_at=datetime.fromisoformat(row[8]),
                created_by=row[9]
            )
            chain.add_version(version)
        
        return chain
    
    def rollback_to_version(
        self,
        memory_id: str,
        target_version_number: int,
        reason: str = 'user_request'
    ) -> Dict:
        """
        回滚到指定版本
        
        流程:
        1. 获取目标版本
        2. 创建新版本（内容为历史版本）
        3. 更新当前记忆
        """
        chain = self.get_version_chain(memory_id)
        target_version = None
        
        for v in chain.versions:
            if v.version_number == target_version_number:
                target_version = v
                break
        
        if not target_version:
            return {'success': False, 'error': 'Version not found'}
        
        # 创建回滚版本
        rollback_version = self.create_version(
            memory_id=memory_id,
            content=target_version.content_snapshot,
            metadata=target_version.metadata_snapshot,
            change_type='rollback',
            change_reason=f'Rollback to v{target_version_number}: {reason}',
            created_by='user'
        )
        
        # 更新当前记忆内容
        cursor = self.db.cursor()
        cursor.execute("""
            UPDATE memories
            SET content = ?,
                metadata = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            target_version.content_snapshot,
            json.dumps(target_version.metadata_snapshot),
            memory_id
        ))
        
        self.db.commit()
        
        return {
            'success': True,
            'rolled_back_to': target_version_number,
            'new_version': rollback_version.version_number
        }
```

---

## 3. 偏好演变分析

### 3.1 偏好演变追踪器

```python
class PreferenceEvolutionTracker:
    """
    偏好演变追踪器
    分析用户偏好的变化趋势
    """
    
    def __init__(self, version_manager, memory_manager):
        self.version_manager = version_manager
        self.memory_manager = memory_manager
    
    def analyze_preference_evolution(
        self,
        agent_id: str,
        preference_category: str
    ) -> Dict:
        """
        分析特定偏好的演变
        
        Args:
            agent_id: Agent ID
            preference_category: 偏好类别 (如'food', 'music', 'coffee')
        
        Returns:
            {
                'current_preference': ...,
                'evolution_history': [...],
                'change_frequency': ...,
                'trend': 'increasing/decreasing/stable/oscillating',
                'confidence': ...
            }
        """
        # 获取相关记忆
        memories = self._get_preference_memories(
            agent_id, preference_category
        )
        
        evolution_history = []
        for memory in memories:
            chain = self.version_manager.get_version_chain(memory.id)
            evolution_history.extend(chain.get_evolution_timeline())
        
        # 按时间排序
        evolution_history.sort(key=lambda x: x['created_at'])
        
        # 分析趋势
        trend = self._analyze_trend(evolution_history)
        
        return {
            'current_preference': self._get_current_preference(memories),
            'evolution_history': evolution_history,
            'change_frequency': len(evolution_history) / max(1, self._get_time_span_days(evolution_history)),
            'trend': trend,
            'confidence': self._calculate_confidence(memories)
        }
    
    def _analyze_trend(self, history: List[Dict]) -> str:
        """分析演变趋势"""
        if len(history) < 2:
            return 'stable'
        
        # 检查是否有交替变化
        changes = []
        for i in range(1, len(history)):
            if history[i]['content'] != history[i-1]['content']:
                changes.append(i)
        
        if len(changes) == 0:
            return 'stable'
        elif len(changes) == 1:
            return 'changed_once'
        elif len(changes) >= 3:
            # 检查是否交替
            return 'oscillating'
        else:
            return 'evolving'
    
    def predict_future_preference(
        self,
        agent_id: str,
        preference_category: str
    ) -> Dict:
        """预测未来偏好"""
        analysis = self.analyze_preference_evolution(
            agent_id, preference_category
        )
        
        prediction = {
            'current': analysis['current_preference'],
            'predicted': analysis['current_preference'],
            'confidence': 0.5,
            'reasoning': ''
        }
        
        if analysis['trend'] == 'stable':
            prediction['confidence'] = 0.9
            prediction['reasoning'] = '偏好长期稳定'
        
        elif analysis['trend'] == 'oscillating':
            # 交替偏好，预测会再次变化
            prediction['confidence'] = 0.4
            prediction['reasoning'] = '偏好交替变化，可能再次反转'
        
        elif analysis['change_frequency'] > 0.5:
            # 高频变化，不稳定
            prediction['confidence'] = 0.3
            prediction['reasoning'] = '偏好频繁变化，难以预测'
        
        return prediction
```

---

## 4. 版本控制与冲突检测融合

### 4.1 融合检测引擎

```python
class VersionAwareConflictDetector:
    """
    版本感知的冲突检测器
    区分"真正冲突"和"正常演变"
    """
    
    def __init__(self, conflict_detector, version_manager, memory_manager):
        self.conflict_detector = conflict_detector
        self.version_manager = version_manager
        self.memory_manager = memory_manager
    
    def detect_with_version_awareness(
        self,
        new_memory: Memory,
        existing_memories: List[Memory]
    ) -> Dict:
        """
        版本感知的冲突检测
        
        返回:
        {
            'conflicts': [...],           # 真正冲突
            'evolutions': [...],          # 正常演变
            'recommendations': [...]      # 处理建议
        }
        """
        result = {
            'conflicts': [],
            'evolutions': [],
            'recommendations': []
        }
        
        for existing in existing_memories:
            # 1. 检测冲突
            conflicts = self.conflict_detector.detect_conflicts(
                new_memory, [existing]
            )
            
            for conflict in conflicts:
                # 2. 判断是否为偏好演变
                if self._is_preference_evolution(new_memory, existing):
                    # 是演变，记录版本而非冲突
                    result['evolutions'].append({
                        'type': 'preference_evolution',
                        'old_memory': existing,
                        'new_memory': new_memory,
                        'action': 'create_version'
                    })
                    result['recommendations'].append(
                        f"偏好演变: {existing.content} → {new_memory.content}"
                    )
                
                elif self._is_temporal_evolution(new_memory, existing):
                    # 时间演变
                    result['evolutions'].append({
                        'type': 'temporal_evolution',
                        'old_memory': existing,
                        'new_memory': new_memory,
                        'action': 'create_version'
                    })
                
                else:
                    # 真正冲突
                    result['conflicts'].append(conflict)
        
        return result
    
    def _is_preference_evolution(
        self,
        new_memory: Memory,
        existing: Memory
    ) -> bool:
        """判断是否为偏好演变"""
        # 检查是否为同一类别
        if new_memory.category != existing.category:
            return False
        
        # 检查是否为偏好类记忆
        preference_keywords = ['喜欢', '讨厌', '偏好', '习惯', '经常']
        
        has_preference = any(
            kw in new_memory.content or kw in existing.content
            for kw in preference_keywords
        )
        
        return has_preference
    
    def _is_temporal_evolution(
        self,
        new_memory: Memory,
        existing: Memory
    ) -> bool:
        """判断是否为时间演变"""
        # 检查时间相关性
        time_diff = (new_memory.created_at - existing.created_at).days
        
        # 时间差距大，可能是正常演变
        return time_diff > 30
```

---

## 5. 数据库设计

### 5.1 版本表

```sql
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

-- 索引
CREATE INDEX idx_versions_memory ON memory_versions(memory_id, version_number DESC);
CREATE INDEX idx_versions_created_at ON memory_versions(created_at DESC);
CREATE INDEX idx_versions_change_type ON memory_versions(change_type);

-- 偏好演变日志
CREATE TABLE preference_evolution_logs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    preference_category TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    change_reason TEXT,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_preference_evolution_agent ON preference_evolution_logs(agent_id, preference_category);
```

---

## 6. 配置示例

```yaml
# version_control.yaml
version_control:
  # 版本保留策略
  retention:
    max_versions_per_memory: 10
    cleanup_interval_days: 30
    keep_important_versions: true
  
  # 偏好演变分析
  preference_evolution:
    enabled: true
    min_time_between_changes: 7  # 最少间隔天数
    trend_analysis:
      stable_threshold: 90  # 90天不变视为稳定
      oscillation_threshold: 3  # 3次交替视为振荡
  
  # 版本回滚
  rollback:
    enabled: true
    require_confirmation: true
    max_rollback_depth: 5
```
