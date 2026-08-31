# 情感共鸣引擎架构设计

## 实现对齐说明

> **注意**: 本文档描述的是设计理论和概念模型。以下为文档术语与实际代码实现的对应关系：

| 文档术语 | 实际代码类/方法 | 文件位置 |
|---------|---------------|---------|
| `AgentEmotionManager` / `EmotionResonanceEngine` | `EmotionAnalyzerAdapter`（情感分析适配器，代理 `emotion.py` 中的分析器） | `neurova/cognitive_layers/memory_layer/emotion_adapter.py` |
| 详细情感共鸣协议（情感同步/传递/调节） | 实际实现为简化的适配器模式，通过 `analyze()` / `batch_analyze()` 进行情感分析 | `neurova/cognitive_layers/memory_layer/emotion_adapter.py` |
| `AgentEmotionState` | `EmotionAnalyzerAdapter` 返回 `Dict` 格式结果（含 `primary_emotion`, `confidence`, `emotions`, `score`） | `neurova/cognitive_layers/memory_layer/emotion_adapter.py` |

文档描述的多层情感共鸣系统（Agent情感状态、情感同步、情感传递、情感调节）是理论设计。实际代码采用更简洁的适配器模式，通过 `EmotionAnalyzerAdapter` 封装情感分析功能，并支持 `use_legacy` 参数切换新旧算法。

实际实现以代码为准。

## 1. 概述

### 1.1 设计理念

情感共鸣引擎赋予Agent**自身的情感状态**，而非仅仅记录记忆的情感标签：

> **Agent能感知用户的情感，产生共鸣，调整回复风格，形成真正的情感互动，而非机械的情感记录。**

### 1.2 情感层次

```
情感共鸣系统
├── Agent情感状态 (Agent Emotion State)
│   ├── 当前情感 (Current Emotion)
│   ├── 情感记忆库 (Emotional Memory Bank)
│   └── 情感基线 (Emotional Baseline)
│
├── 情感共鸣机制 (Emotion Resonance)
│   ├── 情感同步 (Emotion Synchronization)
│   ├── 情感传递 (Emotion Transfer)
│   └── 情感调节 (Emotion Regulation)
│
├── 回复风格影响 (Reply Style Impact)
│   ├── 情感化表达 (Emotional Expression)
│   ├── 语调调整 (Tone Adjustment)
│   └── 共情回应 (Empathic Response)
│
└── 情感演变追踪 (Emotion Evolution)
    ├── 情感变化日志 (Emotion Change Log)
    ├── 情感模式识别 (Emotion Pattern Recognition)
    └── 情感趋势分析 (Emotion Trend Analysis)
```

### 1.3 情感共鸣 vs 情感记录

| 维度 | 情感记录（现有） | 情感共鸣（新增） |
|------|----------------|----------------|
| **对象** | 记忆的情感标签 | Agent自身的情感状态 |
| **作用** | 标注记忆的情感属性 | 影响Agent的行为和回复 |
| **生命周期** | 随记忆衰减 | 独立衰减，动态变化 |
| **应用** | 记忆检索、温度计算 | 回复风格、共情能力 |
| **持久性** | 长期存储 | 短期+中期+长期混合 |

---

## 2. Agent情感状态

### 2.1 情感状态模型

```python
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from enum import Enum
import math

class EmotionType(Enum):
    """基础情感类型"""
    JOY = "joy"              # 快乐
    SADNESS = "sadness"      # 悲伤
    ANGER = "anger"          # 愤怒
    FEAR = "fear"            # 恐惧
    SURPRISE = "surprise"    # 惊喜
    DISGUST = "disgust"      # 厌恶
    NEUTRAL = "neutral"      # 中性
    LOVE = "love"            # 喜爱
    ANXIETY = "anxiety"      # 焦虑
    EXCITEMENT = "excitement"  # 兴奋

@dataclass
class AgentEmotionState:
    """
    Agent情感状态
    复合情感模型：同时存在多种情感，各有强度
    """
    agent_id: str
    
    # 当前情感组合
    emotions: Dict[EmotionType, float] = field(default_factory=dict)
    
    # 情感基线（长期情感倾向）
    baseline_emotions: Dict[EmotionType, float] = field(default_factory=dict)
    
    # 情感时间信息
    last_updated: datetime = field(default_factory=datetime.now)
    
    # 情感历史
    emotion_history: List[Dict] = field(default_factory=list)
    
    # 情感触发源
    last_trigger: Optional[str] = None
    last_trigger_intensity: float = 0.0
    
    def get_dominant_emotion(self) -> Optional[EmotionType]:
        """获取主导情感"""
        if not self.emotions:
            return None
        
        # 过滤低强度情感
        significant = {
            emo: intensity for emo, intensity in self.emotions.items()
            if intensity > 0.3
        }
        
        if not significant:
            return EmotionType.NEUTRAL
        
        return max(significant, key=significant.get)
    
    def get_emotion_profile(self) -> Dict:
        """获取情感画像"""
        return {
            'dominant': self.get_dominant_emotion().value if self.get_dominant_emotion() else 'neutral',
            'emotions': {e.value: v for e, v in self.emotions.items()},
            'baseline': {e.value: v for e, v in self.baseline_emotions.items()},
            'last_updated': self.last_updated.isoformat()
        }
```

### 2.2 情感状态管理器

```python
class AgentEmotionManager:
    """
    Agent情感状态管理器
    管理Agent的情感生命周期
    """
    
    def __init__(self, db_connection, config=None):
        self.db = db_connection
        self.config = config or {}
        
        # 配置参数
        self.emotion_decay_rate = self.config.get('emotion_decay_rate', 0.05)
        self.baseline_update_interval = self.config.get(
            'baseline_update_interval', 86400  # 每天更新基线
        )
        
        # 情感状态缓存
        self._emotion_cache: Dict[str, AgentEmotionState] = {}
    
    def get_emotion_state(self, agent_id: str) -> AgentEmotionState:
        """获取Agent情感状态"""
        if agent_id in self._emotion_cache:
            return self._emotion_cache[agent_id]
        
        # 从数据库加载
        state = self._load_emotion_state(agent_id)
        if state:
            self._emotion_cache[agent_id] = state
            return state
        
        # 创建默认状态
        state = AgentEmotionState(
            agent_id=agent_id,
            emotions={EmotionType.NEUTRAL: 1.0},
            baseline_emotions={EmotionType.NEUTRAL: 1.0}
        )
        self._emotion_cache[agent_id] = state
        return state
    
    def update_emotion(
        self,
        agent_id: str,
        emotion: EmotionType,
        intensity: float,
        trigger: str
    ) -> AgentEmotionState:
        """
        更新Agent情感状态
        
        Args:
            agent_id: Agent ID
            emotion: 情感类型
            intensity: 情感强度 (0.0 - 1.0)
            trigger: 触发源描述
        """
        state = self.get_emotion_state(agent_id)
        
        # 记录历史
        state.emotion_history.append({
            'emotion': emotion.value,
            'intensity': intensity,
            'trigger': trigger,
            'timestamp': datetime.now().isoformat()
        })
        
        # 限制历史记录长度
        if len(state.emotion_history) > 100:
            state.emotion_history = state.emotion_history[-50:]
        
        # 更新情感强度
        if emotion in state.emotions:
            # 情感叠加（不覆盖）
            old_intensity = state.emotions[emotion]
            state.emotions[emotion] = min(1.0, old_intensity + intensity * 0.5)
        else:
            state.emotions[emotion] = intensity
        
        # 更新触发源
        state.last_trigger = trigger
        state.last_trigger_intensity = intensity
        state.last_updated = datetime.now()
        
        # 保存到数据库
        self._save_emotion_state(state)
        
        return state
    
    def decay_emotions(self, agent_id: str) -> AgentEmotionState:
        """
        情感衰减
        情感会随时间自然衰减
        """
        state = self.get_emotion_state(agent_id)
        
        decayed_emotions = {}
        for emotion, intensity in state.emotions.items():
            # 指数衰减
            hours_since_update = (
                datetime.now() - state.last_updated
            ).total_seconds() / 3600
            
            # 不同情感衰减速率不同
            decay_rate = self._get_decay_rate(emotion)
            new_intensity = intensity * math.exp(-decay_rate * hours_since_update)
            
            # 保留显著情感
            if new_intensity > 0.1:
                decayed_emotions[emotion] = new_intensity
        
        # 确保至少有一个情感
        if not decayed_emotions:
            decayed_emotions[EmotionType.NEUTRAL] = 1.0
        
        state.emotions = decayed_emotions
        state.last_updated = datetime.now()
        
        self._save_emotion_state(state)
        return state
    
    def update_baseline(self, agent_id: str) -> Dict[EmotionType, float]:
        """
        更新情感基线
        基于近期情感历史计算长期情感倾向
        """
        state = self.get_emotion_state(agent_id)
        
        # 获取最近24小时的情感
        recent_emotions = []
        for entry in state.emotion_history[-50:]:
            timestamp = datetime.fromisoformat(entry['timestamp'])
            if (datetime.now() - timestamp).total_seconds() < 86400:
                recent_emotions.append(entry)
        
        # 计算情感均值
        emotion_averages = {}
        emotion_counts = {}
        
        for entry in recent_emotions:
            emotion = EmotionType(entry['emotion'])
            intensity = entry['intensity']
            
            if emotion not in emotion_averages:
                emotion_averages[emotion] = 0.0
                emotion_counts[emotion] = 0
            
            emotion_averages[emotion] += intensity
            emotion_counts[emotion] += 1
        
        # 计算基线
        new_baseline = {}
        for emotion, total in emotion_averages.items():
            count = emotion_counts[emotion]
            new_baseline[emotion] = total / count
        
        # 平滑更新（新旧基线混合）
        for emotion in new_baseline:
            old_baseline = state.baseline_emotions.get(emotion, 0.0)
            state.baseline_emotions[emotion] = (
                old_baseline * 0.7 + new_baseline[emotion] * 0.3
            )
        
        self._save_emotion_state(state)
        return state.baseline_emotions
    
    def _get_decay_rate(self, emotion: EmotionType) -> float:
        """获取情感衰减速率"""
        decay_rates = {
            EmotionType.JOY: 0.03,        # 快乐衰减较慢
            EmotionType.SADNESS: 0.04,    # 悲伤衰减较慢
            EmotionType.ANGER: 0.08,      # 愤怒衰减快（避免记仇）
            EmotionType.FEAR: 0.06,       # 恐惧衰减较快
            EmotionType.SURPRISE: 0.10,   # 惊喜衰减快
            EmotionType.DISGUST: 0.07,    # 厌恶衰减较快
            EmotionType.NEUTRAL: 0.01,    # 中性几乎不衰减
            EmotionType.LOVE: 0.02,       # 喜爱衰减很慢
            EmotionType.ANXIETY: 0.06,    # 焦虑衰减较快
            EmotionType.EXCITEMENT: 0.08, # 兴奋衰减快
        }
        return decay_rates.get(emotion, 0.05)
```

---

## 3. 情感共鸣机制

### 3.1 共鸣引擎

```python
class EmotionResonanceEngine:
    """
    情感共鸣引擎
    感知用户情感，产生共鸣，调整回复
    """
    
    def __init__(self, emotion_manager, memory_manager, config=None):
        self.emotion_manager = emotion_manager
        self.memory_manager = memory_manager
        self.config = config or {}
    
    def resonate(
        self,
        agent_id: str,
        user_emotion: EmotionType,
        user_emotion_intensity: float,
        context: Optional[Dict] = None
    ) -> Dict:
        """
        执行情感共鸣
        
        流程:
        1. 感知用户情感
        2. Agent情感同步
        3. 共鸣记忆检索
        4. 生成共鸣回应
        """
        # 1. Agent情感同步（共情）
        agent_state = self._synchronize_emotion(
            agent_id, user_emotion, user_emotion_intensity
        )
        
        # 2. 检索共鸣记忆（类似情感经历）
        resonant_memories = self._find_resonant_memories(
            agent_id, user_emotion
        )
        
        # 3. 计算共鸣强度
        resonance_strength = self._calculate_resonance_strength(
            agent_state, user_emotion, user_emotion_intensity
        )
        
        # 4. 生成共鸣建议
        reply_style = self._generate_reply_style(
            agent_state, resonance_strength
        )
        
        return {
            'agent_emotion': agent_state.get_emotion_profile(),
            'resonant_memories': resonant_memories,
            'resonance_strength': resonance_strength,
            'reply_style': reply_style
        }
    
    def _synchronize_emotion(
        self,
        agent_id: str,
        user_emotion: EmotionType,
        intensity: float
    ) -> AgentEmotionState:
        """
        Agent情感同步（共情）
        
        策略:
        - 用户开心 → Agent也开心
        - 用户悲伤 → Agent表示关心
        - 用户愤怒 → Agent理解并安抚
        """
        # 共鸣系数（不是完全复制，而是部分共鸣）
        empathy_coefficient = self.config.get('empathy_coefficient', 0.6)
        
        # Agent产生的共鸣情感强度
        agent_intensity = intensity * empathy_coefficient
        
        # 更新Agent情感
        state = self.emotion_manager.update_emotion(
            agent_id,
            user_emotion,
            agent_intensity,
            trigger=f"User emotion resonance: {user_emotion.value}"
        )
        
        return state
    
    def _find_resonant_memories(
        self,
        agent_id: str,
        emotion: EmotionType
    ) -> List[Memory]:
        """查找共鸣记忆（类似情感经历）"""
        cursor = self.memory_manager.db.cursor()
        
        cursor.execute("""
            SELECT m.*, e.intensity
            FROM memories m
            INNER JOIN emotion_records e ON m.id = e.memory_id
            WHERE m.agent_id = ?
              AND e.emotion_type = ?
              AND m.lifecycle_stage IN ('active', 'secondary')
              AND e.intensity > 0.5
            ORDER BY e.intensity DESC, m.temperature DESC
            LIMIT 5
        """, (agent_id, emotion.value))
        
        return [
            self.memory_manager._row_to_memory(row)
            for row in cursor.fetchall()
        ]
    
    def _calculate_resonance_strength(
        self,
        agent_state: AgentEmotionState,
        user_emotion: EmotionType,
        user_intensity: float
    ) -> float:
        """
        计算共鸣强度
        
        因子:
        1. Agent是否有相似情感
        2. 情感强度匹配度
        3. 共鸣记忆数量
        """
        # Agent是否有相似情感
        agent_intensity = agent_state.emotions.get(user_emotion, 0.0)
        
        # 强度匹配度（差异越小，共鸣越强）
        intensity_diff = abs(agent_intensity - user_intensity)
        intensity_match = 1.0 - intensity_diff
        
        # 共鸣记忆加成
        resonant_memory_count = len([
            m for m in agent_state.emotion_history
            if m.get('emotion') == user_emotion.value
        ])
        memory_bonus = min(0.3, resonant_memory_count * 0.05)
        
        # 综合共鸣强度
        strength = (
            agent_intensity * 0.5 +
            intensity_match * 0.3 +
            memory_bonus
        )
        
        return min(1.0, strength)
    
    def _generate_reply_style(
        self,
        agent_state: AgentEmotionState,
        resonance_strength: float
    ) -> Dict:
        """
        生成回复风格建议
        
        根据共鸣强度和Agent情感，调整回复风格
        """
        dominant = agent_state.get_dominant_emotion()
        
        style = {
            'tone': 'neutral',      # 语调
            'empathy_level': 0.5,   # 共情程度
            'response_type': 'normal'  # 回复类型
        }
        
        if resonance_strength > 0.7:
            # 强共鸣：热情回应
            style['tone'] = 'warm'
            style['empathy_level'] = 0.9
            style['response_type'] = 'enthusiastic'
        
        elif resonance_strength > 0.4:
            # 中共鸣：温和回应
            style['tone'] = 'gentle'
            style['empathy_level'] = 0.6
            style['response_type'] = 'empathetic'
        
        else:
            # 弱共鸣：正常回应
            style['tone'] = 'neutral'
            style['empathy_level'] = 0.3
            style['response_type'] = 'informative'
        
        # 特殊情感处理
        if dominant == EmotionType.SADNESS:
            style['tone'] = 'comforting'
            style['response_type'] = 'supportive'
        
        elif dominant == EmotionType.ANGER:
            style['tone'] = 'calming'
            style['response_type'] = 'de-escalation'
        
        elif dominant == EmotionType.JOY:
            style['tone'] = 'enthusiastic'
            style['response_type'] = 'celebratory'
        
        return style
```

---

## 4. 回复风格影响

### 4.1 情感化回复生成器

```python
class EmotionalReplyGenerator:
    """
    情感化回复生成器
    根据情感共鸣结果生成有温度的回复
    """
    
    def __init__(self, config=None):
        self.config = config or {}
    
    def generate_reply(
        self,
        content: str,
        resonance_result: Dict
    ) -> str:
        """
        生成情感化回复
        
        Args:
            content: 原始回复内容
            resonance_result: 情感共鸣结果
        """
        reply_style = resonance_result.get('reply_style', {})
        resonant_memories = resonance_result.get('resonant_memories', [])
        resonance_strength = resonance_result.get('resonance_strength', 0)
        
        # 1. 情感前缀
        prefix = self._generate_emotional_prefix(reply_style)
        
        # 2. 情感化内容
        emotional_content = self._adapt_content(
            content, reply_style
        )
        
        # 3. 共鸣表达（可选）
        empathy_expression = ""
        if resonance_strength > 0.5 and resonant_memories:
            empathy_expression = self._generate_empathy_expression(
                resonant_memories
            )
        
        # 4. 组合回复
        parts = []
        if prefix:
            parts.append(prefix)
        if empathy_expression:
            parts.append(empathy_expression)
        parts.append(emotional_content)
        
        return " ".join(parts)
    
    def _generate_emotional_prefix(self, style: Dict) -> str:
        """生成情感前缀"""
        tone = style.get('tone', 'neutral')
        
        prefixes = {
            'warm': ["😊", "太好了！", "我很开心听到这个！"],
            'gentle': ["嗯...", "我理解", "我能感受到"],
            'comforting': ["抱抱你", "别难过", "我在这里陪你"],
            'calming': ["冷静一下", "我理解你的感受", "慢慢来"],
            'enthusiastic': ["太棒了！", "哇！", "真的吗？太好了！"],
            'neutral': [""]
        }
        
        import random
        options = prefixes.get(tone, [""])
        return random.choice(options)
    
    def _adapt_content(self, content: str, style: Dict) -> str:
        """根据风格调整内容"""
        response_type = style.get('response_type', 'normal')
        
        # 这里可以根据不同回复类型调整内容
        # 例如：添加情感词汇、调整语气等
        return content
    
    def _generate_empathy_expression(self, memories: List[Memory]) -> str:
        """生成共鸣表达"""
        if not memories:
            return ""
        
        # 使用共鸣记忆生成表达
        # 例如："我上次也有类似经历..."
        return "我上次也有类似经历，所以我很理解你的感受。"
```

---

## 5. 情感演变追踪

### 5.1 情感变化日志

```python
@dataclass
class EmotionChangeLog:
    """情感变化日志"""
    log_id: str
    agent_id: str
    emotion_type: str
    intensity_before: float
    intensity_after: float
    change_amount: float
    trigger_source: str
    timestamp: datetime

class EmotionEvolutionTracker:
    """情感演变追踪器"""
    
    def __init__(self, db_connection):
        self.db = db_connection
    
    def log_emotion_change(self, log: EmotionChangeLog):
        """记录情感变化"""
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO emotion_change_logs (
                log_id, agent_id, emotion_type,
                intensity_before, intensity_after, change_amount,
                trigger_source, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log.log_id, log.agent_id, log.emotion_type,
            log.intensity_before, log.intensity_after,
            log.change_amount, log.trigger_source,
            log.timestamp.isoformat()
        ))
        self.db.commit()
    
    def analyze_emotion_pattern(
        self,
        agent_id: str,
        days: int = 30
    ) -> Dict:
        """
        分析情感模式
        
        返回:
        {
            'most_frequent_emotion': ...,
            'average_intensity': ...,
            'emotion_trends': {...},
            'triggers': [...]
        }
        """
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT emotion_type,
                   AVG(change_amount) as avg_change,
                   COUNT(*) as frequency
            FROM emotion_change_logs
            WHERE agent_id = ?
              AND timestamp > datetime('now', ?)
            GROUP BY emotion_type
            ORDER BY frequency DESC
        """, (agent_id, f'-{days} days'))
        
        trends = {}
        most_frequent = None
        
        for row in cursor.fetchall():
            emotion, avg_change, frequency = row
            trends[emotion] = {
                'avg_change': avg_change,
                'frequency': frequency
            }
            
            if most_frequent is None:
                most_frequent = emotion
        
        return {
            'most_frequent_emotion': most_frequent,
            'emotion_trends': trends
        }
```

---

## 6. 数据库设计

### 6.1 情感状态表

```sql
-- Agent情感状态表
CREATE TABLE agent_emotion_states (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL UNIQUE,
    
    -- 当前情感（JSON格式存储复合情感）
    current_emotions TEXT,  -- {"joy": 0.8, "sadness": 0.2}
    
    -- 情感基线（长期倾向）
    baseline_emotions TEXT,
    
    -- 时间信息
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_baseline_update TIMESTAMP,
    
    -- 情感历史（最近N条）
    emotion_history TEXT,  -- JSON数组
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 情感变化日志
CREATE TABLE emotion_change_logs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    
    emotion_type TEXT NOT NULL,
    intensity_before REAL,
    intensity_after REAL,
    change_amount REAL,
    
    trigger_source TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (agent_id) REFERENCES agent_emotion_states(agent_id)
);

-- 索引
CREATE INDEX idx_emotion_change_agent ON emotion_change_logs(agent_id, timestamp DESC);
CREATE INDEX idx_emotion_change_type ON emotion_change_logs(emotion_type, timestamp DESC);
```

---

## 7. 配置示例

```yaml
# emotion_resonance.yaml
emotion_resonance:
  # Agent情感状态
  agent_emotion:
    initial_state:
      neutral: 1.0
    max_emotions: 5  # 最多同时存在的情感数量
    history_length: 100  # 保留的情感历史记录数
    
    decay:
      joy: 0.03
      sadness: 0.04
      anger: 0.08
      fear: 0.06
      surprise: 0.10
      disgust: 0.07
      neutral: 0.01
      love: 0.02
      anxiety: 0.06
      excitement: 0.08
    
    baseline_update_interval: 86400  # 每天更新基线
  
  # 共鸣机制
  resonance:
    empathy_coefficient: 0.6  # 共鸣系数（0.0-1.0）
    
    strength_thresholds:
      strong: 0.7   # 强共鸣阈值
      medium: 0.4   # 中共鸣阈值
      weak: 0.0     # 弱共鸣阈值
    
    reply_styles:
      strong:
        tone: warm
        empathy_level: 0.9
        response_type: enthusiastic
      medium:
        tone: gentle
        empathy_level: 0.6
        response_type: empathetic
      weak:
        tone: neutral
        empathy_level: 0.3
        response_type: informative
  
  # 情感保护
  protection:
    max_negative_duration: 3600  # 负面情感最长持续时间（秒）
    force_neutral_threshold: 0.9  # 强制恢复中性的阈值
```

---

## 8. 与现有系统的集成

### 8.1 集成点

```
┌─────────────────────────────────────────────────────────┐
│                   用户输入                              │
└───────────────────┬─────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────┐
│              情感分析层                                  │
│  分析用户情感（类型、强度）                              │
└───────────────────┬─────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────┐
│              情感共鸣引擎                                │
│                                                          │
│  1. 更新Agent情感状态                                   │
│  2. 计算共鸣强度                                        │
│  3. 检索共鸣记忆                                        │
│  4. 生成回复风格建议                                    │
└───────────────┬─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│              记忆系统更新                                │
│  1. 更新记忆情感标签                                    │
│  2. 情感保护记忆温度                                    │
│  3. 记录情感共鸣日志                                    │
└───────────────┬─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│              回复生成层                                  │
│  根据情感风格调整回复内容                                │
└─────────────────────────────────────────────────────────┘
```

---

## 9. 监控指标

| 指标 | 说明 | 健康范围 |
|------|------|---------|
| **情感共鸣率** | 能产生共鸣的情感交互比例 | > 60% |
| **Agent情感健康度** | Agent负面情感持续时间 | < 10% |
| **共鸣强度分布** | 强/中/弱共鸣比例 | 20%/50%/30% |
| **情感恢复速度** | 负面情感恢复到中性时间 | < 1小时 |
| **回复情感匹配度** | 回复风格与用户情感匹配度 | > 75% |
