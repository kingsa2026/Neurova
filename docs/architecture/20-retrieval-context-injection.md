# 记忆检索与上下文注入机制架构设计

## 1. 概述

### 1.1 设计理念

传统记忆检索是**被动查询**（用户问什么，查什么），而人类的记忆是**主动联想**（看到A想到B，B触发C）。本设计实现**类人认知检索**：

> **"我最近睡眠不太好" → 不是简单搜索"睡眠"关键词，而是联想出：工作压力、项目截止日期、配偶也在失眠、上次建议喝热牛奶... 并评估每条记忆的可信度，产生情感共鸣。**

### 1.2 类人认知六大核心能力

| 能力 | 人类表现 | 系统设计 | 对应模块 |
|------|---------|---------|---------|
| **语义理解** | 听懂言外之意 | 意图识别+情感分析+隐含需求推断 | 语义理解层 |
| **联想回忆** | A→B→C链式联想 | 联想图谱+社交图谱+情感共鸣 | 主动回忆层 |
| **情感共鸣** | 开心时想起开心的事 | Agent情感状态+共鸣记忆检索 | 情感共鸣层 |
| **时间感知** | "最近"="近7天" | 时间模式识别+时段匹配 | 时间感知层 |
| **置信度评估** | "我好像记得...不确定" | 元认知+多维置信度计算 | 记忆理解层 |
| **上下文构建** | 组织语言有条理 | 记忆压缩+优先级排序+情感注入 | 上下文构建层 |

### 1.3 系统架构全景

```
用户输入: "我最近睡眠不太好"
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│ 第1层: 语义理解层 (Semantic Understanding)                   │
│   深度理解: 意图 + 情感 + 时间 + 隐含需求                     │
└───────────────────┬─────────────────────────────────────────┘
                    │ 语义分析结果
     ┌──────────────┼──────────────┐
     ▼              ▼              ▼
┌─────────┐  ┌──────────┐  ┌──────────┐
│ 关键词   │  │ 向量检索  │  │ 时间感知  │
│ 检索     │  │ (语义)    │  │ 加权      │
└────┬────┘  └────┬─────┘  └────┬─────┘
     │            │              │
     └────────────┼──────────────┘
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ 第2层: 混合检索层 (Hybrid Retrieval)                         │
│   RRF融合: 关键词(30%) + 向量(35%) + 时间(15%) + 情感(15%)    │
└───────────────────┬─────────────────────────────────────────┘
                    │ 候选记忆 Top-20
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ 第3层: 主动回忆层 (Proactive Recall)                         │
│   联想扩展: 链式回忆 + 情感共鸣 + 社交图谱 + 时间模式         │
└───────────────────┬─────────────────────────────────────────┘
                    │ 扩展记忆 Top-30
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ 第4层: 记忆理解层 (Memory Understanding)                     │
│   深度理解: 冲突检测 + 版本感知 + 置信度计算 + 情感共鸣       │
└───────────────────┬─────────────────────────────────────────┘
                    │ 高质量记忆 Top-10
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ 第5层: 上下文构建层 (Context Builder)                        │
│   结构化: 记忆压缩 + 优先级排序 + 情感注入 + Token控制        │
└───────────────────┬─────────────────────────────────────────┘
                    │ 结构化上下文 (<4000 tokens)
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ 第6层: LLM注入 (LLM Injection)                               │
│   系统提示 + 上下文 + 回复风格建议                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 语义理解层

### 2.1 深度语义分析

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
from enum import Enum

class IntentType(Enum):
    """意图类型"""
    STATEMENT = "statement"              # 陈述
    QUESTION = "question"                # 提问
    COMPLAINT = "complaint"              # 抱怨
    REQUEST = "request"                  # 请求
    SHARING = "sharing"                  # 分享
    GREETING = "greeting"                # 问候

class EmotionType(Enum):
    """情感类型"""
    JOY = "joy"
    SADNESS = "sadness"
    ANGER = "anger"
    ANXIETY = "anxiety"
    EXCITEMENT = "excitement"
    FATIGUE = "fatigue"
    NEUTRAL = "neutral"

@dataclass
class EmotionAnalysis:
    """情感分析结果"""
    type: EmotionType
    intensity: float  # 0.0 - 1.0
    triggers: List[str] = field(default_factory=list)  # 情感触发词

@dataclass
class TimeReference:
    """时间引用解析"""
    original_text: str  # 原文中的时间表达
    parsed_type: str    # 'recent', 'specific', 'relative', 'recurring'
    date_range: Optional[Dict] = None  # 解析后的日期范围
    
    # 例如:
    # "最近" → {'type': 'recent', 'days': 7}
    # "上周" → {'type': 'specific', 'start': '2024-01-08', 'end': '2024-01-14'}
    # "以前" → {'type': 'relative', 'direction': 'past'}
    # "每天" → {'type': 'recurring', 'frequency': 'daily'}

@dataclass
class SemanticAnalysis:
    """
    语义分析完整结果
    """
    original_input: str
    
    # 核心分析
    intent: IntentType
    emotion: EmotionAnalysis
    keywords: List[str]
    time_reference: Optional[TimeReference]
    
    # 深层理解
    implicit_needs: List[str]  # 隐含需求
    social_context: Optional[str]  # 社会背景推断
    urgency_level: str = 'normal'  # 紧急程度: low/normal/high/critical
    
    def to_dict(self) -> Dict:
        return {
            'input': self.original_input,
            'intent': self.intent.value,
            'emotion': {
                'type': self.emotion.type.value,
                'intensity': self.emotion.intensity
            },
            'keywords': self.keywords,
            'time_reference': self.time_reference.parsed_type if self.time_reference else None,
            'implicit_needs': self.implicit_needs,
            'urgency': self.urgency_level
        }
```

### 2.2 语义分析引擎

```python
class SemanticUnderstandingEngine:
    """
    语义理解引擎
    像人一样理解用户输入的深层含义
    """
    
    def __init__(self, config=None):
        self.config = config or {}
        
        # 意图识别规则
        self.intent_patterns = {
            IntentType.COMPLAINT: ['不好', '太差', '烦', '郁闷', '难受', '困扰'],
            IntentType.QUESTION: ['为什么', '怎么', '如何', '是什么', '吗', '呢'],
            IntentType.REQUEST: ['请', '帮我', '能不能', '可以', '建议'],
            IntentType.SHARING: ['今天', '刚刚', '发生', '遇到', '体验'],
        }
        
        # 隐含需求映射
        self.need_mapping = {
            (IntentType.COMPLAINT, EmotionType.ANXIETY): ['安慰', '建议', '倾听'],
            (IntentType.COMPLAINT, EmotionType.SADNESS): ['安慰', '陪伴', '鼓励'],
            (IntentType.SHARING, EmotionType.JOY): ['分享喜悦', '祝贺'],
            (IntentType.REQUEST, EmotionType.NEUTRAL): ['解决方案', '信息'],
        }
    
    def analyze(self, user_input: str) -> SemanticAnalysis:
        """
        深度语义分析
        
        流程:
        1. 意图识别
        2. 情感分析
        3. 关键词提取
        4. 时间解析
        5. 隐含需求推断
        6. 紧急程度评估
        """
        # 1. 意图识别
        intent = self._identify_intent(user_input)
        
        # 2. 情感分析
        emotion = self._analyze_emotion(user_input)
        
        # 3. 关键词提取
        keywords = self._extract_keywords(user_input)
        
        # 4. 时间解析
        time_ref = self._parse_time_reference(user_input)
        
        # 5. 隐含需求推断
        implicit_needs = self._infer_implicit_needs(intent, emotion)
        
        # 6. 紧急程度评估
        urgency = self._assess_urgency(user_input, emotion)
        
        return SemanticAnalysis(
            original_input=user_input,
            intent=intent,
            emotion=emotion,
            keywords=keywords,
            time_reference=time_ref,
            implicit_needs=implicit_needs,
            urgency_level=urgency
        )
    
    def _identify_intent(self, text: str) -> IntentType:
        """识别用户意图"""
        for intent, patterns in self.intent_patterns.items():
            if any(p in text for p in patterns):
                return intent
        return IntentType.STATEMENT
    
    def _analyze_emotion(self, text: str) -> EmotionAnalysis:
        """分析情感"""
        emotion_keywords = {
            EmotionType.ANXIETY: ['焦虑', '担心', '紧张', '不安', '压力'],
            EmotionType.SADNESS: ['难过', '伤心', '失落', '沮丧'],
            EmotionType.ANGER: ['生气', '愤怒', '烦', '恼火'],
            EmotionType.JOY: ['开心', '高兴', '棒', '好', '喜欢'],
            EmotionType.FATIGUE: ['累', '疲惫', '困', '乏'],
        }
        
        detected_emotion = EmotionType.NEUTRAL
        max_count = 0
        triggers = []
        
        for emotion, keywords in emotion_keywords.items():
            found = [kw for kw in keywords if kw in text]
            if len(found) > max_count:
                max_count = len(found)
                detected_emotion = emotion
                triggers = found
        
        # 强度计算
        intensity = min(1.0, max_count * 0.3 + 0.2)
        
        return EmotionAnalysis(
            type=detected_emotion,
            intensity=intensity,
            triggers=triggers
        )
    
    def _infer_implicit_needs(
        self,
        intent: IntentType,
        emotion: EmotionAnalysis
    ) -> List[str]:
        """
        推断隐含需求
        
        核心逻辑:
        - 抱怨+焦虑 → 需要安慰+建议
        - 分享+开心 → 需要分享喜悦
        - 提问+中性 → 需要信息
        """
        key = (intent, emotion.type)
        
        # 查表获取基础需求
        needs = self.need_mapping.get(key, ['信息'])
        
        # 高强度情感额外需求
        if emotion.intensity > 0.7:
            needs.append('情感支持')
        
        # 紧急程度高
        if emotion.type in [EmotionType.ANGER, EmotionType.ANXIETY]:
            if '解决方案' not in needs:
                needs.append('解决方案')
        
        return needs
    
    def _parse_time_reference(self, text: str) -> Optional[TimeReference]:
        """解析时间引用"""
        time_patterns = {
            'recent': ['最近', '近来', '这段时间', '这些天'],
            'specific': ['昨天', '今天', '明天', '上周', '下周', '上个月'],
            'recurring': ['每天', '每周', '经常', '总是', '通常'],
            'relative': ['以前', '以前', '过去', '以前'],
        }
        
        for ref_type, patterns in time_patterns.items():
            for pattern in patterns:
                if pattern in text:
                    return TimeReference(
                        original_text=pattern,
                        parsed_type=ref_type,
                        date_range=self._calculate_date_range(ref_type, pattern)
                    )
        
        return None
    
    def _calculate_date_range(self, ref_type: str, pattern: str) -> Dict:
        """计算日期范围"""
        from datetime import timedelta
        
        now = datetime.now()
        
        if ref_type == 'recent':
            return {'type': 'recent', 'days': 7}
        elif ref_type == 'specific':
            if pattern == '昨天':
                return {'type': 'specific', 'days_ago': 1}
            elif pattern == '今天':
                return {'type': 'specific', 'days_ago': 0}
            elif pattern == '明天':
                return {'type': 'specific', 'days_ahead': 1}
            elif pattern == '上周':
                return {'type': 'specific', 'weeks_ago': 1}
        elif ref_type == 'recurring':
            return {'type': 'recurring', 'frequency': 'daily'}
        
        return {'type': 'relative', 'direction': 'past'}
    
    def _assess_urgency(self, text: str, emotion: EmotionAnalysis) -> str:
        """评估紧急程度"""
        critical_words = ['救命', '紧急', '马上', '立刻', '严重', '危险']
        high_words = ['急', '重要', '关键', '必须']
        
        if any(w in text for w in critical_words):
            return 'critical'
        elif emotion.intensity > 0.8 or any(w in text for w in high_words):
            return 'high'
        elif emotion.intensity > 0.5:
            return 'normal'
        else:
            return 'low'
```

---

## 3. 混合检索层

### 3.1 多路检索架构

```python
from typing import List, Dict, Tuple
import math

@dataclass
class MemoryWithScore:
    """带分数的记忆"""
    memory: object  # Memory对象
    score: float
    source: str  # 检索来源: keyword/vector/time/emotion/social
    
    def to_dict(self) -> Dict:
        return {
            'memory_id': self.memory.id,
            'score': self.score,
            'source': self.source
        }

class HybridRetrievalEngine:
    """
    混合检索引擎
    五路并行检索 + RRF融合
    """
    
    def __init__(self, db_connection, config=None):
        self.db = db_connection
        self.config = config or {}
        
        # RRF权重配置
        self.weights = self.config.get('weights', {
            'keyword': 0.30,
            'vector': 0.35,
            'time_aware': 0.15,
            'emotion': 0.15,
            'social': 0.05
        })
        
        # RRF参数
        self.rrf_k = self.config.get('rrf_k', 60)
    
    def retrieve(
        self,
        analysis: SemanticAnalysis,
        agent_id: str,
        top_k: int = 20
    ) -> List[MemoryWithScore]:
        """
        多维度混合检索
        
        流程:
        1. 五路并行检索
        2. RRF融合
        3. 温度加权调整
        4. 去重排序
        """
        # 1. 五路并行检索
        results = {
            'keyword': self._keyword_search(analysis, agent_id),
            'vector': self._vector_search(analysis, agent_id),
            'time_aware': self._time_aware_search(analysis, agent_id),
            'emotion': self._emotion_search(analysis, agent_id),
            'social': self._social_search(analysis, agent_id)
        }
        
        # 2. RRF融合
        fused = self._rrf_fusion(results)
        
        # 3. 温度加权调整
        adjusted = self._apply_temperature_weight(fused)
        
        # 4. 返回Top-K
        return adjusted[:top_k]
    
    def _keyword_search(
        self,
        analysis: SemanticAnalysis,
        agent_id: str
    ) -> List[MemoryWithScore]:
        """
        关键词检索
        精确匹配，快速响应
        """
        cursor = self.db.cursor()
        
        # FTS5全文检索
        query_terms = ' '.join(analysis.keywords)
        cursor.execute("""
            SELECT m.*, m.temperature / 100.0 as temp_score
            FROM memories m
            WHERE m.agent_id = ?
              AND m.lifecycle_stage IN ('active', 'secondary')
              AND m.content IN (
                  SELECT snippet(memories_fts, 0, '', '', '...', 10)
                  FROM memories_fts
                  WHERE memories_fts MATCH ?
              )
            ORDER BY m.temperature DESC
            LIMIT 50
        """, (agent_id, query_terms))
        
        return [
            MemoryWithScore(
                memory=self._row_to_memory(row),
                score=row[-1],  # temp_score
                source='keyword'
            )
            for row in cursor.fetchall()
        ]
    
    def _vector_search(
        self,
        analysis: SemanticAnalysis,
        agent_id: str
    ) -> List[MemoryWithScore]:
        """
        向量检索
        语义相似度匹配
        """
        # 1. 生成查询向量
        query_vector = self._generate_query_embedding(analysis.original_input)
        
        # 2. 向量相似度搜索
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT me.memory_id, me.vector_json, m.temperature
            FROM memory_embeddings me
            INNER JOIN memories m ON me.memory_id = m.id
            WHERE m.agent_id = ?
              AND m.lifecycle_stage IN ('active', 'secondary')
        """, (agent_id,))
        
        results = []
        for row in cursor.fetchall():
            memory_id = row[0]
            vector = json.loads(row[1])
            temperature = row[2]
            
            # 计算余弦相似度
            similarity = self._cosine_similarity(query_vector, vector)
            
            if similarity > 0.3:  # 阈值过滤
                results.append(MemoryWithScore(
                    memory=self._load_memory(memory_id),
                    score=similarity,
                    source='vector'
                ))
        
        # 按相似度排序
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:50]
    
    def _time_aware_search(
        self,
        analysis: SemanticAnalysis,
        agent_id: str
    ) -> List[MemoryWithScore]:
        """
        时间感知检索
        根据时间引用检索相关记忆
        """
        if not analysis.time_reference:
            return []
        
        cursor = self.db.cursor()
        time_ref = analysis.time_reference
        
        # 根据时间类型构建查询
        if time_ref.parsed_type == 'recent':
            days = time_ref.date_range.get('days', 7)
            cursor.execute("""
                SELECT m.*, m.temperature / 100.0 as temp_score
                FROM memories m
                WHERE m.agent_id = ?
                  AND m.lifecycle_stage IN ('active', 'secondary')
                  AND m.created_at > datetime('now', ?)
                ORDER BY m.temperature DESC
                LIMIT 30
            """, (agent_id, f'-{days} days'))
        
        elif time_ref.parsed_type == 'specific':
            # 检索特定日期的记忆
            days_ago = time_ref.date_range.get('days_ago', 0)
            cursor.execute("""
                SELECT m.*, m.temperature / 100.0 as temp_score
                FROM memories m
                WHERE m.agent_id = ?
                  AND m.lifecycle_stage IN ('active', 'secondary')
                  AND date(m.created_at) = date('now', ?)
                ORDER BY m.temperature DESC
                LIMIT 20
            """, (agent_id, f'-{days_ago} days'))
        
        elif time_ref.parsed_type == 'recurring':
            # 检索周期性记忆
            cursor.execute("""
                SELECT m.*, m.temperature / 100.0 as temp_score
                FROM memories m
                INNER JOIN time_patterns tp ON m.id IN (
                    SELECT json_each.value FROM json_each(tp.memory_ids)
                )
                WHERE m.agent_id = ?
                  AND tp.active = 1
                  AND tp.pattern_type = 'daily'
                ORDER BY m.temperature DESC
                LIMIT 20
            """, (agent_id,))
        
        return [
            MemoryWithScore(
                memory=self._row_to_memory(row),
                score=row[-1],
                source='time_aware'
            )
            for row in cursor.fetchall()
        ]
    
    def _emotion_search(
        self,
        analysis: SemanticAnalysis,
        agent_id: str
    ) -> List[MemoryWithScore]:
        """
        情感共鸣检索
        检索相似情感的记忆
        """
        emotion = analysis.emotion
        if emotion.intensity < 0.3:
            return []
        
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT m.*, e.intensity as emotion_intensity
            FROM memories m
            INNER JOIN memory_emotions e ON m.id = e.memory_id
            WHERE m.agent_id = ?
              AND e.emotion_type = ?
              AND m.lifecycle_stage IN ('active', 'secondary')
            ORDER BY e.intensity DESC, m.temperature DESC
            LIMIT 20
        """, (agent_id, emotion.type.value))
        
        return [
            MemoryWithScore(
                memory=self._row_to_memory(row),
                score=row[-1] * 0.8,  # emotion_intensity * 0.8
                source='emotion'
            )
            for row in cursor.fetchall()
        ]
    
    def _social_search(
        self,
        analysis: SemanticAnalysis,
        agent_id: str
    ) -> List[MemoryWithScore]:
        """
        社交图谱检索
        检索与相关人物有关的记忆
        """
        # 从关键词中提取人物名称
        person_keywords = self._extract_person_keywords(analysis.keywords)
        if not person_keywords:
            return []
        
        cursor = self.db.cursor()
        
        # 通过社交图谱查找相关记忆
        cursor.execute("""
            SELECT m.*, r.strength as relationship_strength
            FROM memories m
            INNER JOIN memory_social_links msl ON m.id = msl.memory_id
            INNER JOIN social_entities se ON msl.entity_id = se.id
            INNER JOIN social_relationships r ON se.id = r.source_entity_id OR se.id = r.target_entity_id
            WHERE m.agent_id = ?
              AND se.name IN ({})
              AND m.lifecycle_stage IN ('active', 'secondary')
            ORDER BY r.strength DESC, m.temperature DESC
            LIMIT 15
        """.format(','.join(['?' for _ in person_keywords])),
        [agent_id] + person_keywords)
        
        return [
            MemoryWithScore(
                memory=self._row_to_memory(row),
                score=row[-1] * 0.6,  # relationship_strength * 0.6
                source='social'
            )
            for row in cursor.fetchall()
        ]
    
    def _rrf_fusion(
        self,
        results: Dict[str, List[MemoryWithScore]]
    ) -> List[MemoryWithScore]:
        """
        RRF (Reciprocal Rank Fusion) 融合
        
        RRF(d) = Σ weight_s / (k + rank_s(d))
        """
        # 构建排名映射
        rank_maps = {}
        for source, memory_list in results.items():
            rank_maps[source] = {
                m.memory.id: rank + 1
                for rank, m in enumerate(memory_list)
            }
        
        # 收集所有记忆ID
        all_memory_ids = set()
        for rank_map in rank_maps.values():
            all_memory_ids.update(rank_map.keys())
        
        # 计算RRF分数
        fused_scores = {}
        for memory_id in all_memory_ids:
            rrf_score = 0.0
            for source, rank_map in rank_maps.items():
                weight = self.weights.get(source, 0.0)
                rank = rank_map.get(memory_id, float('inf'))
                rrf_score += weight / (self.rrf_k + rank)
            
            fused_scores[memory_id] = rrf_score
        
        # 加载记忆并排序
        fused_results = []
        for memory_id, score in sorted(
            fused_scores.items(),
            key=lambda x: x[1],
            reverse=True
        ):
            memory = self._load_memory(memory_id)
            fused_results.append(MemoryWithScore(
                memory=memory,
                score=score,
                source='hybrid'
            ))
        
        return fused_results
    
    def _apply_temperature_weight(
        self,
        results: List[MemoryWithScore]
    ) -> List[MemoryWithScore]:
        """
        温度加权调整
        
        最终分数 = RRF分数 * 0.7 + 温度分数 * 0.3
        """
        for result in results:
            temperature_score = result.memory.temperature / 100.0
            result.score = result.score * 0.7 + temperature_score * 0.3
        
        # 重新排序
        results.sort(key=lambda x: x.score, reverse=True)
        return results
```

---

## 4. 主动回忆层

### 4.1 联想链式回忆

```python
class ProactiveRecallEngine:
    """
    主动回忆引擎
    让Agent"突然想起来"
    """
    
    def __init__(self, db_connection, config=None):
        self.db = db_connection
        self.config = config or {}
        
        # 联想配置
        self.max_chain_depth = self.config.get('max_chain_depth', 3)
        self.max_branches = self.config.get('max_branches', 3)
        self.association_threshold = self.config.get('association_threshold', 0.3)
    
    def expand_memories(
        self,
        seed_memories: List[MemoryWithScore],
        analysis: SemanticAnalysis
    ) -> List[MemoryWithScore]:
        """
        从种子记忆扩展回忆
        
        策略:
        1. 联想链式回忆 (A→B→C)
        2. 时间模式回忆
        3. 情感共鸣回忆
        4. 任务驱动回忆
        """
        expanded = list(seed_memories)
        seen_ids = {m.memory.id for m in seed_memories}
        
        # 1. 联想链式回忆
        for seed in seed_memories[:5]:  # 取前5个种子
            chain = self._associative_chain_recall(
                seed.memory,
                max_depth=self.max_chain_depth
            )
            for chain_memory, depth in chain:
                if chain_memory.id not in seen_ids:
                    seen_ids.add(chain_memory.id)
                    expanded.append(MemoryWithScore(
                        memory=chain_memory,
                        score=seed.score * (0.7 ** depth),  # 链式衰减
                        source=f'chain_depth_{depth}'
                    ))
        
        # 2. 时间模式回忆
        if analysis.time_reference:
            time_memories = self._time_pattern_recall(
                analysis.time_reference,
                analysis.agent_id
            )
            for tm in time_memories:
                if tm.id not in seen_ids:
                    seen_ids.add(tm.id)
                    expanded.append(MemoryWithScore(
                        memory=tm,
                        score=0.6,
                        source='time_pattern'
                    ))
        
        # 3. 情感共鸣回忆
        if analysis.emotion.intensity > 0.5:
            empathy_memories = self._empathy_recall(
                analysis.agent_id,
                analysis.emotion
            )
            for em in empathy_memories:
                if em.id not in seen_ids:
                    seen_ids.add(em.id)
                    expanded.append(MemoryWithScore(
                        memory=em,
                        score=0.5,
                        source='empathy'
                    ))
        
        # 按分数排序
        expanded.sort(key=lambda x: x.score, reverse=True)
        
        return expanded[:30]  # 最多30条
    
    def _associative_chain_recall(
        self,
        seed_memory: object,
        max_depth: int = 3
    ) -> List[Tuple[object, int]]:
        """
        联想链式回忆
        
        例如:
        睡眠不好 → 压力大 → 最近在做什么？ → 哦，在做重要项目
                                 → 项目截止日期快到了
                                 → 用户配偶也在失眠
        """
        chain = []
        current_level = [seed_memory]
        visited = {seed_memory.id}
        
        for depth in range(1, max_depth + 1):
            next_level = []
            
            for memory in current_level:
                # 获取关联记忆
                associations = self._get_associations(memory.id)
                
                for assoc_memory, weight in associations[:self.max_branches]:
                    if assoc_memory.id not in visited:
                        visited.add(assoc_memory.id)
                        chain.append((assoc_memory, depth))
                        next_level.append(assoc_memory)
            
            current_level = next_level
            
            # 如果无新记忆，提前终止
            if not current_level:
                break
        
        return chain
    
    def _get_associations(self, memory_id: str) -> List[Tuple[object, float]]:
        """获取记忆的关联"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT m.*, a.weight, a.association_type
            FROM memory_associations a
            JOIN memories m ON (
                (a.memory_a_id = ? AND m.id = a.memory_b_id) OR
                (a.memory_b_id = ? AND m.id = a.memory_a_id)
            )
            WHERE a.weight > ?
              AND m.lifecycle_stage IN ('active', 'secondary')
            ORDER BY a.weight DESC
            LIMIT 10
        """, (memory_id, memory_id, self.association_threshold))
        
        return [
            (self._row_to_memory(row), row[-2])  # (memory, weight)
            for row in cursor.fetchall()
        ]
    
    def _time_pattern_recall(
        self,
        time_ref: TimeReference,
        agent_id: str
    ) -> List[object]:
        """时间模式回忆"""
        cursor = self.db.cursor()
        
        if time_ref.parsed_type == 'recent':
            days = time_ref.date_range.get('days', 7)
            cursor.execute("""
                SELECT m.*
                FROM memories m
                WHERE m.agent_id = ?
                  AND m.lifecycle_stage IN ('active', 'secondary')
                  AND m.created_at > datetime('now', ?)
                ORDER BY m.temperature DESC
                LIMIT 10
            """, (agent_id, f'-{days} days'))
        
        return [self._row_to_memory(row) for row in cursor.fetchall()]
    
    def _empathy_recall(
        self,
        agent_id: str,
        emotion: EmotionAnalysis
    ) -> List[object]:
        """情感共鸣回忆"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT m.*
            FROM memories m
            INNER JOIN memory_emotions e ON m.id = e.memory_id
            WHERE m.agent_id = ?
              AND e.emotion_type = ?
              AND m.lifecycle_stage IN ('active', 'secondary')
            ORDER BY m.temperature DESC, e.intensity DESC
            LIMIT 5
        """, (agent_id, emotion.type.value))
        
        return [self._row_to_memory(row) for row in cursor.fetchall()]
```

---

## 5. 记忆理解层

### 5.1 记忆深度理解

```python
@dataclass
class EnhancedMemory:
    """增强记忆对象"""
    memory: object
    score: float
    confidence: float  # 置信度 0.0-1.0
    has_conflict: bool  # 是否有冲突
    conflict_details: Optional[Dict] = None
    empathy_response: Optional[str] = None  # 情感共鸣反应
    understanding_notes: List[str] = field(default_factory=list)  # 理解备注
    
    def to_dict(self) -> Dict:
        return {
            'memory_id': self.memory.id,
            'score': self.score,
            'confidence': self.confidence,
            'has_conflict': self.has_conflict,
            'empathy_response': self.empathy_response
        }

class MemoryUnderstandingEngine:
    """
    记忆理解引擎
    像人一样理解记忆之间的关系和可信度
    """
    
    def __init__(self, db_connection, config=None):
        self.db = db_connection
        self.config = config or {}
    
    def filter_and_understand(
        self,
        candidate_memories: List[MemoryWithScore]
    ) -> List[EnhancedMemory]:
        """
        过滤并理解记忆
        
        流程:
        1. 冲突检测
        2. 版本感知
        3. 置信度计算
        4. 情感共鸣
        5. 去重排序
        """
        # 1. 冲突检测
        conflicts = self._detect_conflicts(candidate_memories)
        
        enhanced = []
        for memory_with_score in candidate_memories:
            memory = memory_with_score.memory
            
            # 2. 检查冲突
            conflict_info = conflicts.get(memory.id)
            has_conflict = conflict_info is not None
            
            # 3. 计算置信度
            confidence = self._calculate_confidence(memory, has_conflict)
            
            # 4. 情感共鸣
            empathy = self._generate_empathy_response(memory)
            
            # 5. 理解备注
            notes = self._generate_understanding_notes(memory, conflict_info)
            
            enhanced.append(EnhancedMemory(
                memory=memory,
                score=memory_with_score.score,
                confidence=confidence,
                has_conflict=has_conflict,
                conflict_details=conflict_info,
                empathy_response=empathy,
                understanding_notes=notes
            ))
        
        # 6. 去重
        enhanced = self._deduplicate(enhanced)
        
        # 7. 排序 (score * confidence)
        enhanced.sort(key=lambda x: x.score * x.confidence, reverse=True)
        
        return enhanced[:10]  # 返回Top-10
    
    def _calculate_confidence(
        self,
        memory: object,
        has_conflict: bool
    ) -> float:
        """
        计算记忆置信度（元认知能力）
        
        因子:
        - 温度: 高温记忆更可信 (0-0.3)
        - 访问次数: 多次访问更可信 (0-0.2)
        - 视角: 用户明确说的 > AI推断的 (0-0.2)
        - 冲突: 有冲突降低置信度 (-0.3)
        - 固化: 固化记忆加成 (+0.2)
        - 时间: 新记忆更可信 (0-0.1)
        """
        confidence = 0.5  # 基础置信度
        
        # 温度因子 (0-0.3)
        confidence += (memory.temperature / 100.0) * 0.3
        
        # 访问次数因子 (0-0.2)
        confidence += min(0.2, memory.access_count * 0.02)
        
        # 视角因子 (0-0.2)
        perspective_scores = {
            'user_statement': 0.2,
            'shared_experience': 0.15,
            'external_source': 0.1,
            'ai_inference': 0.05,
            'hypothetical': 0.0
        }
        confidence += perspective_scores.get(memory.perspective, 0.1)
        
        # 冲突惩罚 (-0.3)
        if has_conflict:
            confidence -= 0.3
        
        # 固化记忆加成 (+0.2)
        if memory.is_crystallized:
            confidence += 0.2
        
        # 重要记忆加成 (+0.1)
        if memory.is_important:
            confidence += 0.1
        
        # 限制范围
        return max(0.0, min(1.0, confidence))
    
    def _detect_conflicts(
        self,
        memories: List[MemoryWithScore]
    ) -> Dict[str, Dict]:
        """
        检测记忆冲突
        
        返回:
        {
            'memory_id': {
                'conflicting_with': 'other_memory_id',
                'conflict_type': 'direct_contradiction',
                'severity': 'high'
            }
        }
        """
        conflicts = {}
        memory_ids = [m.memory.id for m in memories]
        
        if len(memory_ids) < 2:
            return conflicts
        
        cursor = self.db.cursor()
        placeholders = ','.join(['?' for _ in memory_ids])
        
        cursor.execute(f"""
            SELECT memory_a_id, memory_b_id, conflict_type, severity
            FROM memory_conflicts
            WHERE status = 'detected'
              AND (memory_a_id IN ({placeholders}) OR memory_b_id IN ({placeholders}))
        """, memory_ids + memory_ids)
        
        for row in cursor.fetchall():
            memory_a_id, memory_b_id, conflict_type, severity = row
            conflicts[memory_a_id] = {
                'conflicting_with': memory_b_id,
                'conflict_type': conflict_type,
                'severity': severity
            }
            conflicts[memory_b_id] = {
                'conflicting_with': memory_a_id,
                'conflict_type': conflict_type,
                'severity': severity
            }
        
        return conflicts
    
    def _generate_empathy_response(self, memory: object) -> Optional[str]:
        """生成情感共鸣反应"""
        if not hasattr(memory, 'emotion_tags') or not memory.emotion_tags:
            return None
        
        emotion_map = {
            'joy': '我理解你的开心',
            'sadness': '我能感受到你的难过',
            'anger': '我理解你的愤怒',
            'anxiety': '我理解你的焦虑',
            'surprise': '这确实让人意外',
        }
        
        responses = []
        for emotion_tag in memory.emotion_tags:
            if emotion_tag in emotion_map:
                responses.append(emotion_map[emotion_tag])
        
        return '; '.join(responses) if responses else None
    
    def _generate_understanding_notes(
        self,
        memory: object,
        conflict_info: Optional[Dict]
    ) -> List[str]:
        """生成理解备注"""
        notes = []
        
        if memory.is_important:
            notes.append('[重要记忆]')
        
        if memory.is_crystallized:
            notes.append('[永久记忆]')
        
        if memory.perspective == 'ai_inference':
            notes.append('[AI推断，需确认]')
        
        if conflict_info:
            notes.append(f'[有冲突: {conflict_info["conflict_type"]}]')
        
        if memory.temperature > 80:
            notes.append('[高温记忆，近期频繁访问]')
        
        return notes
    
    def _deduplicate(self, enhanced: List[EnhancedMemory]) -> List[EnhancedMemory]:
        """去重"""
        seen_content = set()
        deduplicated = []
        
        for em in enhanced:
            # 使用内容哈希去重
            content_hash = hash(em.memory.content[:100])
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                deduplicated.append(em)
        
        return deduplicated
```

---

## 6. 上下文构建层

### 6.1 结构化上下文构建

```python
class ContextBuilderEngine:
    """
    上下文构建引擎
    将记忆转化为LLM可理解的结构化上下文
    """
    
    def __init__(self, config=None):
        self.config = config or {}
        self.max_tokens = self.config.get('max_tokens', 4000)
    
    def build_context(
        self,
        enhanced_memories: List[EnhancedMemory],
        analysis: SemanticAnalysis,
        agent_emotion_state: Optional[Dict] = None
    ) -> str:
        """
        构建结构化上下文
        
        输出格式:
        ┌─────────────────────────────────────────────────────┐
        │ 【用户当前状态】                                     │
        │ - 用户说: "我最近睡眠不太好"                         │
        │ - 意图: 抱怨                                         │
        │ - 情感: 焦虑 (强度: 0.6)                             │
        │ - 时间: 最近 (近7天)                                 │
        │ - 隐含需求: 安慰, 建议, 倾听                         │
        │ - 紧急程度: 正常                                     │
        │                                                      │
        │ 【你记得的相关信息】                                 │
        │ 1. [重要] 用户过去也提到过失眠                       │
        │    温度: 85°C | 置信度: 高 | 来源: 用户明确说         │
        │    → 当时是因为工作压力大                            │
        │                                                      │
        │ 2. [高温] 用户配偶也经常失眠                         │
        │    温度: 70°C | 置信度: 中 | 来源: 共同经历           │
        │                                                      │
        │ 3. [联想] 用户最近在做一个重要项目                   │
        │    温度: 65°C | 置信度: 中 | 来源: 联想回忆           │
        │    → 项目截止日期是下周                              │
        │                                                      │
        │ 【你的情感状态】                                     │
        │ - 当前情感: 关心 (强度: 0.4)                         │
        │ - 共鸣反应: 我理解你的焦虑                            │
        │                                                      │
        │ 【回复建议】                                         │
        │ - 语气: 温暖关心                                     │
        │ - 风格: 先安慰，后给建议                             │
        │ - 参考: 用户过去的有效经验                            │
        │                                                      │
        │ 【记忆置信度总结】                                   │
        │ - 高置信度: 3条 | 中置信度: 4条 | 低置信度: 1条       │
        └─────────────────────────────────────────────────────┘
        """
        context_parts = []
        
        # 1. 用户当前状态
        context_parts.append("【用户当前状态】")
        context_parts.append(f"- 用户说: \"{analysis.original_input}\"")
        context_parts.append(f"- 意图: {analysis.intent.value}")
        context_parts.append(f"- 情感: {analysis.emotion.type.value} (强度: {analysis.emotion.intensity:.1f})")
        
        if analysis.time_reference:
            context_parts.append(f"- 时间: {analysis.time_reference.original_text} ({self._format_time_ref(analysis.time_reference)})")
        
        context_parts.append(f"- 隐含需求: {', '.join(analysis.implicit_needs)}")
        context_parts.append(f"- 紧急程度: {analysis.urgency_level}")
        context_parts.append("")
        
        # 2. 相关记忆（按类型分组）
        context_parts.append("【你记得的相关信息】")
        
        # 分组
        important = [m for m in enhanced_memories if m.memory.is_important]
        high_temp = [m for m in enhanced_memories if m.memory.temperature > 70 and not m.memory.is_important]
        normal = [m for m in enhanced_memories if m.memory.temperature <= 70]
        
        idx = 1
        for group, label in [(important, '重要'), (high_temp, '高温'), (normal, '相关')]:
            for em in group[:3]:  # 每组最多3条
                memory = em.memory
                confidence_label = self._confidence_label(em.confidence)
                source_label = self._source_label(em)
                
                context_parts.append(
                    f"{idx}. [{label}] {memory.content}"
                )
                context_parts.append(
                    f"   温度: {memory.temperature:.0f}°C | "
                    f"置信度: {confidence_label} | "
                    f"来源: {source_label}"
                )
                
                # 添加关联信息
                if memory.metadata.get('related_info'):
                    context_parts.append(f"   → {memory.metadata['related_info']}")
                
                # 添加理解备注
                if em.understanding_notes:
                    context_parts.append(f"   备注: {'; '.join(em.understanding_notes)}")
                
                # 冲突提示
                if em.has_conflict:
                    context_parts.append(
                        f"   ⚠️ 注意: 与记忆 {em.conflict_details['conflicting_with']} 有冲突"
                    )
                
                idx += 1
        
        context_parts.append("")
        
        # 3. Agent情感状态
        if agent_emotion_state:
            context_parts.append("【你的情感状态】")
            dominant = agent_emotion_state.get('dominant', 'neutral')
            context_parts.append(f"- 当前情感: {dominant}")
            
            # 收集共鸣反应
            empathy_responses = [
                em.empathy_response
                for em in enhanced_memories
                if em.empathy_response
            ]
            if empathy_responses:
                context_parts.append(f"- 共鸣反应: {'; '.join(empathy_responses[:3])}")
            
            context_parts.append("")
        
        # 4. 回复建议
        context_parts.append("【回复建议】")
        reply_style = self._suggest_reply_style(analysis)
        context_parts.append(f"- 语气: {reply_style['tone']}")
        context_parts.append(f"- 风格: {reply_style['style']}")
        
        # 参考建议
        references = self._extract_references(enhanced_memories)
        if references:
            context_parts.append(f"- 参考: {references}")
        
        context_parts.append("")
        
        # 5. 记忆置信度总结
        context_parts.append("【记忆置信度总结】")
        high_conf = len([m for m in enhanced_memories if m.confidence > 0.7])
        med_conf = len([m for m in enhanced_memories if 0.4 < m.confidence <= 0.7])
        low_conf = len([m for m in enhanced_memories if m.confidence <= 0.4])
        
        context_parts.append(f"- 高置信度: {high_conf}条 | 中置信度: {med_conf}条 | 低置信度: {low_conf}条")
        
        # 检查Token限制
        full_context = "\n".join(context_parts)
        token_count = self._count_tokens(full_context)
        
        if token_count > self.max_tokens:
            full_context = self._compress_context(full_context, self.max_tokens)
        
        return full_context
    
    def _confidence_label(self, confidence: float) -> str:
        """置信度标签"""
        if confidence > 0.8:
            return "高"
        elif confidence > 0.5:
            return "中"
        else:
            return "低"
    
    def _source_label(self, em: EnhancedMemory) -> str:
        """来源标签"""
        source_map = {
            'keyword': '关键词检索',
            'vector': '语义检索',
            'time_aware': '时间检索',
            'emotion': '情感共鸣',
            'social': '社交图谱',
            'hybrid': '混合检索',
        }
        return source_map.get(em.memory.source, '检索')
    
    def _suggest_reply_style(self, analysis: SemanticAnalysis) -> Dict:
        """建议回复风格"""
        emotion = analysis.emotion.type
        
        style_map = {
            EmotionType.ANXIETY: {
                'tone': '温暖关心',
                'style': '先安慰，后给建议'
            },
            EmotionType.SADNESS: {
                'tone': '温柔陪伴',
                'style': '倾听为主，适当鼓励'
            },
            EmotionType.JOY: {
                'tone': '热情分享',
                'style': '共同庆祝，积极回应'
            },
            EmotionType.ANGER: {
                'tone': '平静理解',
                'style': '先理解情绪，再解决问题'
            },
        }
        
        return style_map.get(emotion, {
            'tone': '中性友好',
            'style': '正常回复'
        })
    
    def _extract_references(self, memories: List[EnhancedMemory]) -> str:
        """提取参考信息"""
        references = []
        for em in memories[:3]:
            if em.memory.metadata.get('related_info'):
                references.append(em.memory.metadata['related_info'])
        
        return '; '.join(references) if references else '用户过去的有效经验'
    
    def _format_time_ref(self, time_ref: TimeReference) -> str:
        """格式化时间引用"""
        if time_ref.parsed_type == 'recent':
            days = time_ref.date_range.get('days', 7)
            return f'近{days}天'
        elif time_ref.parsed_type == 'specific':
            return '特定日期'
        elif time_ref.parsed_type == 'recurring':
            return '周期性'
        return ''
    
    def _count_tokens(self, text: str) -> int:
        """计算Token数量（估算）"""
        # 简单估算: 中文字符1个token，英文单词1个token
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        english_words = len(text.split())
        return chinese_chars + english_words
    
    def _compress_context(self, context: str, max_tokens: int) -> str:
        """压缩上下文"""
        # 简单实现: 截断
        if self._count_tokens(context) > max_tokens:
            # 保留前max_tokens个字符
            return context[:max_tokens * 2]  # 粗略估算
        return context
```

---

## 7. 完整检索与注入流程

### 7.1 端到端流程编排

```python
class MemoryRetrievalOrchestrator:
    """
    记忆检索编排器
    端到端协调所有检索层
    """
    
    def __init__(self, db_connection, config=None):
        self.db = db_connection
        self.config = config or {}
        
        # 初始化各层引擎
        self.semantic_engine = SemanticUnderstandingEngine(config)
        self.hybrid_retrieval = HybridRetrievalEngine(db_connection, config)
        self.proactive_recall = ProactiveRecallEngine(db_connection, config)
        self.memory_understanding = MemoryUnderstandingEngine(db_connection, config)
        self.context_builder = ContextBuilderEngine(config)
    
    def retrieve_and_build_context(
        self,
        user_input: str,
        agent_id: str,
        agent_emotion_state: Optional[Dict] = None
    ) -> Dict:
        """
        端到端检索与上下文构建
        
        返回:
        {
            'semantic_analysis': {...},      # 语义分析结果
            'retrieved_memories': [...],     # 检索到的记忆
            'context': '...',                # 构建的上下文
            'token_count': 1234,             # Token数量
            'metadata': {...}                # 元数据
        }
        """
        # 第1层: 语义理解
        analysis = self.semantic_engine.analyze(user_input)
        analysis.agent_id = agent_id  # 注入agent_id
        
        # 第2层: 混合检索
        candidate_memories = self.hybrid_retrieval.retrieve(
            analysis, agent_id, top_k=20
        )
        
        # 第3层: 主动回忆
        expanded_memories = self.proactive_recall.expand_memories(
            candidate_memories, analysis
        )
        
        # 第4层: 记忆理解
        enhanced_memories = self.memory_understanding.filter_and_understand(
            expanded_memories
        )
        
        # 第5层: 上下文构建
        context = self.context_builder.build_context(
            enhanced_memories,
            analysis,
            agent_emotion_state
        )
        
        # 返回结果
        return {
            'semantic_analysis': analysis.to_dict(),
            'retrieved_memories': [em.to_dict() for em in enhanced_memories],
            'context': context,
            'token_count': self.context_builder._count_tokens(context),
            'metadata': {
                'total_candidates': len(candidate_memories),
                'expanded_memories': len(expanded_memories),
                'final_memories': len(enhanced_memories)
            }
        }
```

---

## 8. 类人思维示例

### 8.1 完整思维过程演示

**用户输入**: "我最近睡眠不太好"

**Agent内心独白**:

```
【语义理解】
- 用户说"睡眠不太好" → 意图: 抱怨
- 情感: 焦虑 (强度0.6)
- 时间: "最近" = 近7天
- 隐含需求: 需要安慰 + 建议 + 倾听

【记忆检索】
- 关键词: "睡眠", "不好" → 找到3条直接相关记忆
- 向量: 语义搜索"失眠困扰" → 找到5条相似记忆
- 时间: 近7天记忆 → 找到2条近期记录
- 情感: 焦虑相关记忆 → 找到3条用户过去的焦虑经历

【主动回忆】
- 联想链: 睡眠 → 压力 → 工作项目 → 项目下周截止
- 社交图谱: 用户配偶也失眠 → 可能互相影响
- 情感共鸣: 用户上次焦虑时，我建议喝热牛奶 → 有效果吗？

【记忆理解】
- 冲突检测: 无冲突
- 置信度计算:
  * "用户说过工作压力大" → 置信度0.85 (用户明确说+高温)
  * "配偶也失眠" → 置信度0.65 (共同经历+中温)
  * "建议喝热牛奶" → 置信度0.75 (AI推断+高温)

【上下文构建】
- 重要记忆: 用户过去失眠是因为工作压力 (温度85°C)
- 高温记忆: 配偶经常失眠 (温度70°C)
- 联想记忆: 项目下周截止 (温度65°C)
- 情感建议: 温暖关心，先安慰后给建议

【最终回复】
"我能理解你的焦虑，睡眠不好真的很折磨人。我记得你上次失眠
是因为工作压力大，当时你提到在做一个重要项目，项目截止日期
是不是快到了？上次你试了喝热牛奶，效果怎么样？如果还是睡不
好，也许我们可以一起找找其他方法。"
```

---

## 9. 配置示例

```yaml
# retrieval_context_injection.yaml
retrieval_context_injection:
  # 语义理解
  semantic_understanding:
    intent_patterns:
      complaint: ['不好', '太差', '烦', '郁闷']
      question: ['为什么', '怎么', '如何', '是什么']
      request: ['请', '帮我', '能不能', '可以']
    
    emotion_threshold: 0.3  # 情感强度阈值
    
    implicit_needs:
      complaint_anxiety: ['安慰', '建议', '倾听']
      sharing_joy: ['分享喜悦', '祝贺']
      request_neutral: ['解决方案', '信息']
  
  # 混合检索
  hybrid_retrieval:
    weights:
      keyword: 0.30
      vector: 0.35
      time_aware: 0.15
      emotion: 0.15
      social: 0.05
    
    rrf_k: 60
    top_k: 20
  
  # 主动回忆
  proactive_recall:
    max_chain_depth: 3
    max_branches: 3
    association_threshold: 0.3
    max_expanded: 30
  
  # 记忆理解
  memory_understanding:
    confidence_thresholds:
      high: 0.8
      medium: 0.5
      low: 0.0
    
    conflict_penalty: 0.3
    crystallized_bonus: 0.2
  
  # 上下文构建
  context_builder:
    max_tokens: 4000
    
    grouping:
      important: true
      high_temperature: 70
      normal: true
    
    display:
      show_temperature: true
      show_confidence: true
      show_conflicts: true
      show_empathy: true
```

---

## 10. 性能指标

| 指标 | 说明 | 目标值 |
|------|------|--------|
| **端到端延迟** | 从用户输入到上下文构建完成 | < 500ms |
| **语义理解延迟** | 意图+情感+关键词分析 | < 50ms |
| **混合检索延迟** | 五路检索+RRF融合 | < 200ms |
| **主动回忆延迟** | 联想链式扩展 | < 100ms |
| **上下文构建延迟** | 结构化输出+Token控制 | < 50ms |
| **检索准确率** | Top-10记忆相关性 | > 80% |
| **主动回忆覆盖率** | 联想扩展的记忆比例 | > 30% |
| **置信度准确性** | 置信度与实际情况匹配 | > 75% |

---

## 11. 监控与日志

### 11.1 检索日志

```sql
CREATE TABLE retrieval_logs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    user_input TEXT,
    intent TEXT,
    emotion_type TEXT,
    emotion_intensity REAL,
    
    -- 检索统计
    keyword_count INTEGER,
    vector_count INTEGER,
    time_aware_count INTEGER,
    emotion_count INTEGER,
    social_count INTEGER,
    expanded_count INTEGER,
    final_count INTEGER,
    
    -- 质量指标
    avg_confidence REAL,
    high_confidence_count INTEGER,
    conflict_count INTEGER,
    
    -- 上下文
    token_count INTEGER,
    context_preview TEXT,  -- 前200字符
    
    -- 性能
    latency_ms REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_retrieval_logs_agent ON retrieval_logs(agent_id, created_at DESC);
```
