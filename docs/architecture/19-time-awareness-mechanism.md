# 时间感知模块架构设计

## 1. 概述

### 1.1 设计理念

时间感知赋予记忆系统**时序智能**：

> **识别用户的时间模式（如"每周一开会"）、预测时间相关事件（如"明天是纪念日"）、理解季节性偏好（如"冬天喜欢热饮"）、记忆随时间的演变规律。**

### 1.2 时间感知架构

```
时间感知系统
├── 时间模式识别 (Time Pattern Recognition)
│   ├── 周期性模式 (每日/每周/每月/每年)
│   ├── 时段偏好 (早上/下午/晚上)
│   └── 习惯模式 (固定时间做固定事)
│
├── 时间事件预测 (Time Event Prediction)
│   ├── 纪念日提醒
│   ├── 周期性事件预测
│   └── 时间相关触发
│
├── 季节性偏好 (Seasonal Preferences)
│   ├── 季节模式识别
│   ├── 偏好变化追踪
│   └── 季节性建议
│
└── 时间感知检索 (Time-Aware Retrieval)
    ├── 时间权重计算
    ├── 时段相关记忆
    └── 时间上下文检索
```

---

## 2. 时间模式识别

### 2.1 时间模式数据模型

```python
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from enum import Enum
import uuid
from collections import defaultdict

class TimePatternType(Enum):
    """时间模式类型"""
    DAILY = "daily"           # 每日模式
    WEEKLY = "weekly"         # 每周模式
    MONTHLY = "monthly"       # 每月模式
    YEARLY = "yearly"         # 每年模式
    SPECIFIC_TIME = "specific_time"  # 特定时间

@dataclass
class TimePattern:
    """时间模式"""
    id: str
    pattern_type: TimePatternType
    description: str  # 人类可读描述
    memory_ids: List[str]  # 相关记忆ID
    confidence: float  # 模式置信度
    occurrences: int  # 出现次数
    time_info: Dict  # 时间信息
    
    # 例如:
    # DAILY: {"hour": 9, "minute": 0}
    # WEEKLY: {"day_of_week": 1, "hour": 14}  # 周一14点
    # MONTHLY: {"day_of_month": 15}  # 每月15号
    # YEARLY: {"month": 5, "day": 20}  # 5月20号
    
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    active: bool = True

@dataclass
class TimeAwareMemory:
    """时间感知的记忆"""
    memory_id: str
    time_tags: List[str]  # 时间标签
    time_pattern: Optional[TimePattern]  # 关联的时间模式
    seasonal_info: Optional[Dict]  # 季节性信息
```

### 2.2 时间模式检测器

```python
class TimePatternDetector:
    """
    时间模式检测器
    从记忆中识别时间模式
    """
    
    def __init__(self, db_connection, config=None):
        self.db = db_connection
        self.config = config or {}
        
        # 模式检测阈值
        self.min_occurrences = self.config.get('min_occurrences', 3)
        self.confidence_threshold = self.config.get('confidence_threshold', 0.7)
    
    def detect_patterns(self, agent_id: str) -> List[TimePattern]:
        """
        检测时间模式
        
        流程:
        1. 获取所有带时间标签的记忆
        2. 按时间特征分组
        3. 识别周期性
        4. 计算置信度
        5. 生成模式
        """
        # 1. 获取记忆
        memories = self._get_time_tagged_memories(agent_id)
        
        patterns = []
        
        # 2. 检测每日模式
        daily_patterns = self._detect_daily_pattern(memories)
        patterns.extend(daily_patterns)
        
        # 3. 检测每周模式
        weekly_patterns = self._detect_weekly_pattern(memories)
        patterns.extend(weekly_patterns)
        
        # 4. 检测每月模式
        monthly_patterns = self._detect_monthly_pattern(memories)
        patterns.extend(monthly_patterns)
        
        # 5. 检测每年模式（纪念日等）
        yearly_patterns = self._detect_yearly_pattern(memories)
        patterns.extend(yearly_patterns)
        
        return patterns
    
    def _detect_weekly_pattern(self, memories: List[Memory]) -> List[TimePattern]:
        """检测每周模式"""
        # 按星期几分组
        day_groups = defaultdict(list)
        
        for memory in memories:
            day_of_week = memory.created_at.weekday()
            hour = memory.created_at.hour
            
            # 检查内容是否包含时间关键词
            if self._is_time_related(memory.content):
                key = (day_of_week, hour)
                day_groups[key].append(memory)
        
        patterns = []
        for (day, hour), group_memories in day_groups.items():
            if len(group_memories) >= self.min_occurrences:
                # 计算置信度
                confidence = self._calculate_pattern_confidence(group_memories)
                
                if confidence >= self.confidence_threshold:
                    pattern = TimePattern(
                        id=str(uuid.uuid4()),
                        pattern_type=TimePatternType.WEEKLY,
                        description=f"每周{self._day_name(day)}{hour}点的习惯",
                        memory_ids=[m.id for m in group_memories],
                        confidence=confidence,
                        occurrences=len(group_memories),
                        time_info={
                            'day_of_week': day,
                            'hour': hour
                        }
                    )
                    patterns.append(pattern)
        
        return patterns
    
    def _detect_yearly_pattern(self, memories: List[Memory]) -> List[TimePattern]:
        """检测每年模式（纪念日等）"""
        # 按日期分组
        date_groups = defaultdict(list)
        
        for memory in memories:
            month = memory.created_at.month
            day = memory.created_at.day
            
            # 检查是否为纪念日相关
            if self._is_anniversary_related(memory.content):
                key = (month, day)
                date_groups[key].append(memory)
        
        patterns = []
        for (month, day), group_memories in date_groups.items():
            confidence = self._calculate_pattern_confidence(group_memories)
            
            pattern = TimePattern(
                id=str(uuid.uuid4()),
                pattern_type=TimePatternType.YEARLY,
                description=f"每年{month}月{day}日的重要事件",
                memory_ids=[m.id for m in group_memories],
                confidence=confidence,
                occurrences=len(group_memories),
                time_info={
                    'month': month,
                    'day': day
                }
            )
            patterns.append(pattern)
        
        return patterns
    
    def _is_time_related(self, content: str) -> bool:
        """检查内容是否与时间相关"""
        time_keywords = ['每天', '每周', '每月', '经常', '通常', '习惯', '总是']
        return any(kw in content for kw in time_keywords)
    
    def _is_anniversary_related(self, content: str) -> bool:
        """检查是否为纪念日相关"""
        anniversary_keywords = ['生日', '纪念日', '周年', '节日', '特殊日子']
        return any(kw in content for kw in anniversary_keywords)
    
    def _day_name(self, day: int) -> str:
        """星期名称"""
        days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        return days[day]
    
    def _calculate_pattern_confidence(self, memories: List[Memory]) -> float:
        """计算模式置信度"""
        if len(memories) < 2:
            return 0.0
        
        # 基于出现次数
        count_score = min(1.0, len(memories) / 10.0)
        
        # 基于时间一致性
        time_variance = self._calculate_time_variance(memories)
        consistency_score = 1.0 - min(1.0, time_variance / 3600)  # 1小时内为高一致
        
        # 综合评分
        confidence = count_score * 0.6 + consistency_score * 0.4
        
        return confidence
    
    def _calculate_time_variance(self, memories: List[Memory]) -> float:
        """计算时间方差"""
        if len(memories) < 2:
            return 0.0
        
        timestamps = [m.created_at.timestamp() for m in memories]
        mean = sum(timestamps) / len(timestamps)
        variance = sum((t - mean) ** 2 for t in timestamps) / len(timestamps)
        
        return variance ** 0.5  # 标准差
```

---

## 3. 时间事件预测

### 3.1 事件预测引擎

```python
class TimeEventPredictor:
    """
    时间事件预测引擎
    预测即将到来的时间相关事件
    """
    
    def __init__(self, db_connection, pattern_detector):
        self.db = db_connection
        self.pattern_detector = pattern_detector
    
    def get_upcoming_events(
        self,
        agent_id: str,
        days_ahead: int = 7
    ) -> List[Dict]:
        """
        获取即将到来的事件
        
        Args:
            agent_id: Agent ID
            days_ahead: 未来天数
        
        Returns:
            [
                {
                    'type': 'anniversary/routine/seasonal',
                    'description': str,
                    'date': datetime,
                    'related_memories': [...],
                    'importance': float
                }
            ]
        """
        upcoming = []
        now = datetime.now()
        future = now + timedelta(days=days_ahead)
        
        # 1. 检测模式
        patterns = self.pattern_detector.detect_patterns(agent_id)
        
        # 2. 预测未来事件
        for pattern in patterns:
            if pattern.pattern_type == TimePatternType.YEARLY:
                # 纪念日
                event_date = self._get_next_occurrence(pattern)
                if now <= event_date <= future:
                    upcoming.append({
                        'type': 'anniversary',
                        'description': pattern.description,
                        'date': event_date,
                        'related_memories': pattern.memory_ids,
                        'importance': pattern.confidence * (pattern.occurrences / 10.0)
                    })
            
            elif pattern.pattern_type == TimePatternType.WEEKLY:
                # 每周事件
                next_occurrence = self._get_next_weekly_occurrence(pattern)
                if now <= next_occurrence <= future:
                    upcoming.append({
                        'type': 'routine',
                        'description': pattern.description,
                        'date': next_occurrence,
                        'related_memories': pattern.memory_ids,
                        'importance': pattern.confidence * 0.5
                    })
        
        # 按时间排序
        upcoming.sort(key=lambda x: x['date'])
        
        return upcoming
    
    def _get_next_occurrence(self, pattern: TimePattern) -> datetime:
        """获取下次发生时间"""
        now = datetime.now()
        
        if pattern.pattern_type == TimePatternType.YEARLY:
            month = pattern.time_info['month']
            day = pattern.time_info['day']
            
            # 今年的日期
            event_date = datetime(now.year, month, day)
            
            # 如果已过，明年
            if event_date < now:
                event_date = datetime(now.year + 1, month, day)
            
            return event_date
        
        elif pattern.pattern_type == TimePatternType.WEEKLY:
            day_of_week = pattern.time_info['day_of_week']
            hour = pattern.time_info.get('hour', 0)
            
            # 计算到目标星期几的天数
            days_ahead = day_of_week - now.weekday()
            if days_ahead < 0:
                days_ahead += 7
            
            return now + timedelta(days=days_ahead, hours=hour - now.hour)
        
        return now
    
    def generate_reminder(
        self,
        event: Dict,
        advance_hours: int = 24
    ) -> Dict:
        """生成提醒"""
        event_date = event['date']
        reminder_time = event_date - timedelta(hours=advance_hours)
        
        return {
            'event': event,
            'reminder_time': reminder_time,
            'message': f"提醒: {event['description']} 即将到来",
            'suggested_action': self._suggest_action(event)
        }
    
    def _suggest_action(self, event: Dict) -> str:
        """根据事件类型建议行动"""
        event_type = event['type']
        
        if event_type == 'anniversary':
            return "准备祝福或礼物"
        elif event_type == 'routine':
            return "按计划执行"
        elif event_type == 'seasonal':
            return "调整相关偏好"
        
        return ""
```

---

## 4. 季节性偏好

### 4.1 季节性分析器

```python
class SeasonalPreferenceAnalyzer:
    """
    季节性偏好分析器
    识别用户的季节性偏好变化
    """
    
    def __init__(self, db_connection):
        self.db = db_connection
    
    def analyze_seasonal_preferences(
        self,
        agent_id: str,
        category: str
    ) -> Dict:
        """
        分析特定类别的季节性偏好
        
        Args:
            agent_id: Agent ID
            category: 偏好类别 (如'food', 'activity')
        
        Returns:
            {
                'seasons': {
                    'spring': [...],
                    'summer': [...],
                    'autumn': [...],
                    'winter': [...]
                },
                'patterns': [...],
                'current_recommendation': str
            }
        """
        # 获取相关记忆
        memories = self._get_category_memories(agent_id, category)
        
        # 按季节分组
        seasonal_groups = defaultdict(list)
        for memory in memories:
            season = self._get_season(memory.created_at)
            seasonal_groups[season].append(memory)
        
        # 分析每个季节的偏好
        season_preferences = {}
        for season, group_memories in seasonal_groups.items():
            season_preferences[season] = self._extract_preferences(group_memories)
        
        # 识别模式
        patterns = self._identify_seasonal_patterns(season_preferences)
        
        # 当前季节建议
        current_season = self._get_season(datetime.now())
        current_recommendation = season_preferences.get(current_season, {}).get('recommendation', '')
        
        return {
            'seasons': season_preferences,
            'patterns': patterns,
            'current_season': current_season,
            'current_recommendation': current_recommendation
        }
    
    def _get_season(self, date: datetime) -> str:
        """获取日期所属季节"""
        month = date.month
        
        if 3 <= month <= 5:
            return 'spring'
        elif 6 <= month <= 8:
            return 'summer'
        elif 9 <= month <= 11:
            return 'autumn'
        else:
            return 'winter'
    
    def _extract_preferences(self, memories: List[Memory]) -> Dict:
        """提取偏好"""
        # 简单实现
        return {
            'items': [m.content for m in memories[:5]],
            'count': len(memories),
            'recommendation': f"这个季节用户喜欢: {memories[0].content if memories else '未知'}"
        }
    
    def _identify_seasonal_patterns(self, season_prefs: Dict) -> List[Dict]:
        """识别季节模式"""
        patterns = []
        
        # 比较不同季节的偏好
        seasons = list(season_prefs.keys())
        for i in range(len(seasons)):
            for j in range(i + 1, len(seasons)):
                s1, s2 = seasons[i], seasons[j]
                prefs1 = set(season_prefs.get(s1, {}).get('items', []))
                prefs2 = set(season_prefs.get(s2, {}).get('items', []))
                
                # 找出差异
                diff1 = prefs1 - prefs2
                diff2 = prefs2 - prefs1
                
                if diff1 or diff2:
                    patterns.append({
                        'seasons': [s1, s2],
                        'unique_to_s1': list(diff1),
                        'unique_to_s2': list(diff2)
                    })
        
        return patterns
```

---

## 5. 时间感知检索

### 5.1 时间感知检索器

```python
class TimeAwareRetriever:
    """
    时间感知检索器
    根据时间上下文增强检索
    """
    
    def __init__(self, memory_manager, pattern_detector):
        self.memory_manager = memory_manager
        self.pattern_detector = pattern_detector
    
    def search_with_time_context(
        self,
        query: str,
        agent_id: str,
        current_time: Optional[datetime] = None,
        time_weight: float = 0.3
    ) -> List[Memory]:
        """
        带时间上下文的检索
        
        Args:
            query: 查询内容
            agent_id: Agent ID
            current_time: 当前时间
            time_weight: 时间权重
        
        Returns:
            按时间相关性排序的记忆列表
        """
        if current_time is None:
            current_time = datetime.now()
        
        # 1. 基础检索
        base_results = self.memory_manager.search_memories(
            query=query,
            agent_id=agent_id,
            limit=20
        )
        
        # 2. 计算时间相关性
        scored_results = []
        for memory in base_results:
            # 基础分数
            base_score = self._calculate_base_score(memory, query)
            
            # 时间分数
            time_score = self._calculate_time_score(memory, current_time)
            
            # 综合分数
            final_score = base_score * (1 - time_weight) + time_score * time_weight
            
            scored_results.append((memory, final_score))
        
        # 3. 排序
        scored_results.sort(key=lambda x: x[1], reverse=True)
        
        return [m for m, score in scored_results]
    
    def _calculate_time_score(
        self,
        memory: Memory,
        current_time: datetime
    ) -> float:
        """
        计算时间相关性分数
        
        因子:
        1. 时段匹配 (如晚上检索到晚上的记忆)
        2. 星期匹配
        3. 季节匹配
        4. 时间衰减
        """
        score = 0.0
        
        # 时段匹配 (0-0.3)
        memory_hour = memory.created_at.hour
        current_hour = current_time.hour
        hour_diff = abs(memory_hour - current_hour)
        if hour_diff <= 2:
            score += 0.3
        elif hour_diff <= 4:
            score += 0.15
        
        # 星期匹配 (0-0.2)
        if memory.created_at.weekday() == current_time.weekday():
            score += 0.2
        
        # 季节匹配 (0-0.2)
        if self._get_season(memory.created_at) == self._get_season(current_time):
            score += 0.2
        
        # 时间衰减 (0-0.3)
        days_diff = (current_time - memory.created_at).days
        if days_diff < 7:
            score += 0.3
        elif days_diff < 30:
            score += 0.15
        elif days_diff < 90:
            score += 0.05
        
        return score
    
    def _calculate_base_score(self, memory: Memory, query: str) -> float:
        """计算基础检索分数"""
        # 简单实现: 关键词匹配
        query_words = set(query.lower().split())
        memory_words = set(memory.content.lower().split())
        
        intersection = query_words & memory_words
        if not query_words:
            return 0.0
        
        return len(intersection) / len(query_words)
```

---

## 6. 数据库设计

### 6.1 时间相关表

```sql
-- 时间模式表
CREATE TABLE time_patterns (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    description TEXT,
    memory_ids TEXT,  -- JSON数组
    confidence REAL,
    occurrences INTEGER,
    time_info TEXT,  -- JSON
    active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);

CREATE INDEX idx_time_patterns_agent ON time_patterns(agent_id, pattern_type);
CREATE INDEX idx_time_patterns_active ON time_patterns(agent_id, active, confidence DESC);

-- 时间标签表
CREATE TABLE memory_time_tags (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    tag TEXT NOT NULL,  # morning/afternoon/evening/night/weekday/weekend/etc
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX idx_time_tags_memory ON memory_time_tags(memory_id);
CREATE INDEX idx_time_tags_tag ON memory_time_tags(tag);

-- 事件提醒表
CREATE TABLE time_event_reminders (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    description TEXT,
    event_date TIMESTAMP NOT NULL,
    reminder_time TIMESTAMP,
    related_memories TEXT,  -- JSON数组
    importance REAL,
    status TEXT DEFAULT 'pending',  # pending/acknowledged/dismissed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);

CREATE INDEX idx_reminders_agent ON time_event_reminders(agent_id, event_date DESC);
CREATE INDEX idx_reminders_status ON time_event_reminders(status, event_date);
```

---

## 7. 配置示例

```yaml
# time_awareness.yaml
time_awareness:
  # 时间模式检测
  pattern_detection:
    enabled: true
    min_occurrences: 3
    confidence_threshold: 0.7
    
    patterns:
      daily: true
      weekly: true
      monthly: true
      yearly: true
  
  # 事件预测
  event_prediction:
    enabled: true
    days_ahead: 7
    advance_reminder_hours: 24
  
  # 季节性偏好
  seasonal_preferences:
    enabled: true
    categories:
      - food
      - activity
      - clothing
  
  # 时间感知检索
  retrieval:
    enabled: true
    time_weight: 0.3
    
    factors:
      hour_match: 0.3
      day_match: 0.2
      season_match: 0.2
      recency: 0.3
```

---

## 8. 监控指标

| 指标 | 说明 | 健康范围 |
|------|------|---------|
| **模式检测准确率** | 检测到的时间模式准确率 | > 80% |
| **事件预测准确率** | 预测事件的准确程度 | > 70% |
| **检索时间相关性** | 检索结果与当前时间的相关性 | > 60% |
| **模式更新频率** | 时间模式更新频率 | 每周1次 |
