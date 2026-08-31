# 记忆压缩机制架构设计

## 实现对齐说明

> **注意**: 本文档描述的是设计理论和概念模型。以下为文档术语与实际代码实现的对应关系：

| 文档术语 | 实际代码类/方法 | 文件位置 |
|---------|---------------|---------|
| `HierarchicalCompressionEngine` | `MemoryCompressor` | `neurova/cognitive_layers/memory_layer/compression.py` |
| `CompressionStrategy`（5策略） | `CompressionStrategy` 枚举：`TIER` / `SEMANTIC` / `AGGREGATION` / `LLM` / `RULE_BASED` | `neurova/cognitive_layers/memory_layer/compression.py` |
| 压缩入口方法 | `MemoryCompressor.compress(memories, strategy, **kwargs)` → 返回 `CompressionResult` | `neurova/cognitive_layers/memory_layer/compression.py` |

文档中的5种压缩策略与实际 `CompressionStrategy` 枚举名称略有不同（文档使用描述性名称如"时间触发压缩"，实际代码使用 `TIER`/`SEMANTIC`/`AGGREGATION`/`LLM`/`RULE_BASED`）。

实际实现以代码为准。

## 1. 概述

### 1.1 设计理念

记忆压缩机制解决**记忆膨胀问题**：随着Agent运行时间增长，记忆数量会指数级增长。压缩机制像人类大脑一样：

> **保留核心信息，丢弃冗余细节；相关记忆合并为摘要；原始记忆压缩为层级结构。**

### 1.2 压缩层次

```
记忆压缩系统
├── 层级压缩 (Hierarchical Compression)
│   ├── 原始层 (Raw Layer) - 完整对话/内容
│   ├── 摘要层 (Summary Layer) - 关键信息摘要
│   └── 主题层 (Topic Layer) - 主题/趋势总结
│
├── 语义压缩 (Semantic Compression)
│   ├── 去重压缩 (Deduplication)
│   ├── 冗余消除 (Redundancy Removal)
│   └── 信息提炼 (Information Extraction)
│
├── 记忆聚合 (Memory Aggregation)
│   ├── 对话聚合 (Conversation Aggregation)
│   ├── 事件聚合 (Event Aggregation)
│   └── 知识聚合 (Knowledge Aggregation)
│
└── 压缩策略 (Compression Strategy)
    ├── 时间触发压缩
    ├── 容量触发压缩
    └── 智能评估压缩
```

### 1.3 压缩效果对比

| 层次 | 压缩前 | 压缩后 | 压缩率 | 信息保留 |
|------|--------|--------|--------|---------|
| 原始层 | 100条对话 | 100条对话 | 100% | 完整信息 |
| 摘要层 | 100条对话 | 10条摘要 | 10% | 关键信息 |
| 主题层 | 10条摘要 | 3个主题 | 3% | 核心趋势 |

---

## 2. 层级压缩

### 2.1 压缩数据模型

```python
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from enum import Enum
import uuid

class CompressionLevel(Enum):
    """压缩层级"""
    RAW = "raw"              # 原始层 - 不压缩
    SUMMARY = "summary"      # 摘要层 - 关键信息
    TOPIC = "topic"          # 主题层 - 高度压缩

@dataclass
class CompressedMemory:
    """压缩后的记忆"""
    id: str
    original_memory_ids: List[str]  # 原始记忆ID列表
    compression_level: CompressionLevel
    compressed_content: str
    compression_ratio: float
    key_points: List[str]  # 关键点
    metadata: Dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'original_ids': self.original_memory_ids,
            'level': self.compression_level.value,
            'content': self.compressed_content,
            'ratio': self.compression_ratio,
            'key_points': self.key_points,
            'metadata': self.metadata
        }
```

### 2.2 层级压缩引擎

```python
class HierarchicalCompressionEngine:
    """
    层级压缩引擎
    将记忆压缩为多层结构
    """
    
    def __init__(self, db_connection, config=None):
        self.db = db_connection
        self.config = config or {}
        
        # 压缩触发条件
        self.time_threshold_days = self.config.get('time_threshold_days', 30)
        self.count_threshold = self.config.get('count_threshold', 100)
        self.compression_ratio_target = self.config.get('compression_ratio_target', 0.1)
        
        # 初始化压缩器
        self.summary_compressor = SummaryCompressor()
        self.topic_compressor = TopicCompressor()
    
    def compress_memory_group(
        self,
        agent_id: str,
        memories: List[Memory],
        target_level: CompressionLevel
    ) -> List[CompressedMemory]:
        """
        压缩记忆组
        
        Args:
            agent_id: Agent ID
            memories: 待压缩的记忆列表
            target_level: 目标压缩层级
        
        Returns:
            压缩后的记忆列表
        """
        if target_level == CompressionLevel.SUMMARY:
            return self._compress_to_summaries(memories)
        elif target_level == CompressionLevel.TOPIC:
            return self._compress_to_topics(memories)
        else:
            return []  # RAW层不压缩
    
    def _compress_to_summaries(
        self,
        memories: List[Memory]
    ) -> List[CompressedMemory]:
        """
        压缩为摘要层
        
        流程:
        1. 按时间/主题分组
        2. 对每组生成摘要
        3. 提取关键点
        4. 创建压缩记忆
        """
        # 1. 分组 (按日期)
        groups = self._group_by_date(memories)
        
        compressed = []
        for date, group_memories in groups.items():
            if len(group_memories) < 3:
                continue  # 少于3条不压缩
            
            # 2. 生成摘要
            summary = self.summary_compressor.generate_summary(group_memories)
            
            # 3. 提取关键点
            key_points = self.summary_compressor.extract_key_points(group_memories)
            
            # 4. 计算压缩率
            original_size = sum(len(m.content) for m in group_memories)
            compressed_size = len(summary)
            compression_ratio = compressed_size / original_size if original_size > 0 else 1.0
            
            # 5. 创建压缩记忆
            compressed_memory = CompressedMemory(
                id=str(uuid.uuid4()),
                original_memory_ids=[m.id for m in group_memories],
                compression_level=CompressionLevel.SUMMARY,
                compressed_content=summary,
                compression_ratio=compression_ratio,
                key_points=key_points,
                metadata={
                    'date': date.isoformat(),
                    'original_count': len(group_memories)
                }
            )
            
            compressed.append(compressed_memory)
        
        return compressed
    
    def _compress_to_topics(
        self,
        memories: List[Memory]
    ) -> List[CompressedMemory]:
        """
        压缩为主题层
        
        流程:
        1. 主题聚类
        2. 对每个聚类生成主题总结
        3. 识别趋势
        """
        # 1. 主题聚类
        topic_clusters = self.topic_compressor.cluster_by_topic(memories)
        
        compressed = []
        for cluster in topic_clusters:
            if len(cluster) < 5:
                continue  # 少于5条不聚合
            
            # 2. 生成主题总结
            topic_summary = self.topic_compressor.generate_topic_summary(cluster)
            
            # 3. 识别趋势
            trends = self.topic_compressor.identify_trends(cluster)
            
            # 4. 计算压缩率
            original_size = sum(len(m.content) for m in cluster)
            compressed_size = len(topic_summary)
            compression_ratio = compressed_size / original_size if original_size > 0 else 1.0
            
            # 5. 创建压缩记忆
            compressed_memory = CompressedMemory(
                id=str(uuid.uuid4()),
                original_memory_ids=[m.id for m in cluster],
                compression_level=CompressionLevel.TOPIC,
                compressed_content=topic_summary,
                compression_ratio=compression_ratio,
                key_points=trends,
                metadata={
                    'cluster_size': len(cluster),
                    'original_count': len(cluster)
                }
            )
            
            compressed.append(compressed_memory)
        
        return compressed
    
    def _group_by_date(self, memories: List[Memory]) -> Dict:
        """按日期分组"""
        groups = {}
        for memory in memories:
            date = memory.created_at.date()
            if date not in groups:
                groups[date] = []
            groups[date].append(memory)
        return groups
```

---

## 3. 语义压缩

### 3.1 摘要压缩器

```python
class SummaryCompressor:
    """
    摘要压缩器
    将多条记忆压缩为精炼摘要
    """
    
    def generate_summary(self, memories: List[Memory]) -> str:
        """
        生成记忆组摘要
        
        策略:
        1. 提取关键信息
        2. 合并相似内容
        3. 保留重要细节
        4. 生成简洁摘要
        """
        if not memories:
            return ""
        
        # 1. 提取关键信息
        key_info = self._extract_key_information(memories)
        
        # 2. 合并相似内容
        merged_info = self._merge_similar_info(key_info)
        
        # 3. 生成摘要
        summary_parts = []
        for info in merged_info:
            summary_parts.append(f"- {info}")
        
        return "\n".join(summary_parts)
    
    def extract_key_points(self, memories: List[Memory]) -> List[str]:
        """提取关键点"""
        key_points = []
        
        for memory in memories:
            # 提取关键信息
            points = self._extract_from_memory(memory)
            key_points.extend(points)
        
        # 去重
        unique_points = list(set(key_points))
        
        # 限制数量
        return unique_points[:10]
    
    def _extract_key_information(self, memories: List[Memory]) -> List[str]:
        """提取关键信息"""
        key_info = []
        
        for memory in memories:
            # 简单实现: 提取重要句子
            sentences = memory.content.split('。')
            for sentence in sentences:
                if len(sentence.strip()) > 10:
                    # 包含关键词的句子更重要
                    if self._is_important_sentence(sentence):
                        key_info.append(sentence.strip())
        
        return key_info
    
    def _merge_similar_info(self, info_list: List[str]) -> List[str]:
        """合并相似信息"""
        merged = []
        used = set()
        
        for i, info in enumerate(info_list):
            if i in used:
                continue
            
            similar = [info]
            for j, other in enumerate(info_list[i+1:], i+1):
                if j not in used and self._is_similar(info, other):
                    similar.append(other)
                    used.add(j)
            
            # 合并相似信息
            if len(similar) > 1:
                merged.append(self._merge_info(similar))
            else:
                merged.append(info)
            
            used.add(i)
        
        return merged
    
    def _is_important_sentence(self, sentence: str) -> bool:
        """判断是否为重要句子"""
        important_keywords = ['记住', '重要', '必须', '不要', '关键', '核心']
        return any(kw in sentence for kw in important_keywords)
    
    def _is_similar(self, text_a: str, text_b: str) -> bool:
        """判断文本是否相似"""
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        
        if not words_a or not words_b:
            return False
        
        intersection = words_a & words_b
        union = words_a | words_b
        
        jaccard = len(intersection) / len(union)
        return jaccard > 0.5
    
    def _merge_info(self, info_list: List[str]) -> str:
        """合并信息"""
        if len(info_list) == 1:
            return info_list[0]
        
        # 简单合并: 用"和"连接
        return "、".join(info_list)
    
    def _extract_from_memory(self, memory: Memory) -> List[str]:
        """从单条记忆提取关键点"""
        # 简单实现: 按标点分割
        sentences = re.split(r'[。！？；]', memory.content)
        return [s.strip() for s in sentences if len(s.strip()) > 5 and len(s.strip()) < 100]
```

### 3.2 主题压缩器

```python
class TopicCompressor:
    """
    主题压缩器
    将相关记忆聚类并生成主题总结
    """
    
    def cluster_by_topic(self, memories: List[Memory]) -> List[List[Memory]]:
        """
        按主题聚类记忆
        
        流程:
        1. 提取主题特征
        2. 计算相似度
        3. 聚类
        """
        # 简单实现: 基于关键词聚类
        keyword_to_memories = {}
        
        for memory in memories:
            keywords = self._extract_keywords(memory.content)
            for keyword in keywords:
                if keyword not in keyword_to_memories:
                    keyword_to_memories[keyword] = []
                keyword_to_memories[keyword].append(memory)
        
        # 过滤小聚类
        clusters = [
            memories for memories in keyword_to_memories.values()
            if len(memories) >= 3
        ]
        
        return clusters
    
    def generate_topic_summary(self, memories: List[Memory]) -> str:
        """生成主题总结"""
        if not memories:
            return ""
        
        # 提取共同主题
        common_topics = self._find_common_topics(memories)
        
        # 生成总结
        summary_parts = []
        summary_parts.append(f"关于 {', '.join(common_topics[:3])} 的相关记忆：")
        
        # 总结要点
        key_points = []
        for memory in memories[:10]:  # 限制处理数量
            points = self._extract_key_point(memory)
            if points:
                key_points.append(points)
        
        summary_parts.append("关键点：")
        for point in key_points[:5]:
            summary_parts.append(f"- {point}")
        
        return "\n".join(summary_parts)
    
    def identify_trends(self, memories: List[Memory]) -> List[str]:
        """识别趋势"""
        trends = []
        
        # 按时间排序
        sorted_memories = sorted(memories, key=lambda m: m.created_at)
        
        # 检测变化
        if len(sorted_memories) >= 3:
            early = sorted_memories[:len(sorted_memories)//3]
            late = sorted_memories[-len(sorted_memories)//3:]
            
            # 比较早期和晚期内容
            early_keywords = self._extract_keywords(' '.join(m.content for m in early))
            late_keywords = self._extract_keywords(' '.join(m.content for m in late))
            
            # 新增关键词
            new_keywords = set(late_keywords) - set(early_keywords)
            if new_keywords:
                trends.append(f"新增关注点: {', '.join(list(new_keywords)[:3])}")
            
            # 消失关键词
            lost_keywords = set(early_keywords) - set(late_keywords)
            if lost_keywords:
                trends.append(f"减少关注点: {', '.join(list(lost_keywords)[:3])}")
        
        return trends
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        # 简单实现: 分词后过滤
        words = text.lower().split()
        # 过滤停用词
        stop_words = {'的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'}
        return [w for w in words if w not in stop_words and len(w) > 1]
    
    def _find_common_topics(self, memories: List[Memory]) -> List[str]:
        """查找共同主题"""
        all_keywords = []
        for memory in memories:
            keywords = self._extract_keywords(memory.content)
            all_keywords.extend(keywords)
        
        # 统计词频
        from collections import Counter
        keyword_counts = Counter(all_keywords)
        
        # 返回高频词
        return [keyword for keyword, count in keyword_counts.most_common(10)]
    
    def _extract_key_point(self, memory: Memory) -> Optional[str]:
        """提取关键点"""
        sentences = re.split(r'[。！？；]', memory.content)
        for sentence in sentences:
            sentence = sentence.strip()
            if 10 < len(sentence) < 100:
                return sentence
        return None
```

---

## 4. 记忆聚合

### 4.1 对话聚合器

```python
class ConversationAggregator:
    """
    对话聚合器
    将同一会话的多条对话聚合为完整对话记录
    """
    
    def aggregate_session(self, session_id: str, messages: List[Dict]) -> str:
        """
        聚合约话
        
        Args:
            session_id: 会话ID
            messages: 消息列表
        
        Returns:
            聚合后的对话摘要
        """
        if not messages:
            return ""
        
        # 1. 提取关键对话
        key_messages = self._extract_key_messages(messages)
        
        # 2. 生成摘要
        summary = self._generate_summary(key_messages)
        
        return summary
    
    def _extract_key_messages(self, messages: List[Dict]) -> List[Dict]:
        """提取关键消息"""
        key_messages = []
        
        for msg in messages:
            # 用户重要输入
            if msg.get('role') == 'user' and self._is_important_message(msg['content']):
                key_messages.append(msg)
            
            # Agent重要回复
            elif msg.get('role') == 'assistant' and self._is_important_response(msg['content']):
                key_messages.append(msg)
        
        return key_messages
    
    def _is_important_message(self, content: str) -> bool:
        """判断是否为重要消息"""
        important_indicators = [
            '请记住', '记住', '重要', '关键', '必须', '不要',
            '我的', '我喜欢', '我讨厌', '我经常'
        ]
        return any(indicator in content for indicator in important_indicators)
    
    def _is_important_response(self, content: str) -> bool:
        """判断是否为重要回复"""
        important_indicators = [
            '我记住了', '我会记住', '明白了', '理解了',
            '建议', '推荐', '分析', '总结'
        ]
        return any(indicator in content for indicator in important_indicators)
    
    def _generate_summary(self, key_messages: List[Dict]) -> str:
        """生成对话摘要"""
        if not key_messages:
            return ""
        
        summary_parts = []
        for msg in key_messages[:10]:  # 限制数量
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')[:100]  # 限制长度
            summary_parts.append(f"[{role}]: {content}")
        
        return "\n".join(summary_parts)
```

---

## 5. 压缩触发策略

### 5.1 触发管理器

```python
class CompressionTriggerManager:
    """
    压缩触发管理器
    决定何时执行压缩
    """
    
    def __init__(self, config=None):
        self.config = config or {}
        
        # 触发条件
        self.time_interval_hours = self.config.get('time_interval_hours', 24)
        self.memory_count_threshold = self.config.get('memory_count_threshold', 1000)
        self.storage_size_threshold_mb = self.config.get('storage_size_threshold_mb', 100)
    
    def should_compress(self, agent_id: str, memory_manager) -> Dict:
        """
        检查是否需要压缩
        
        Returns:
            {
                'should_compress': bool,
                'reason': str,
                'priority': str  # low/medium/high
            }
        """
        # 1. 检查时间间隔
        last_compression = self._get_last_compression_time(agent_id)
        if last_compression:
            hours_since = (datetime.now() - last_compression).total_seconds() / 3600
            if hours_since < self.time_interval_hours:
                return {'should_compress': False, 'reason': 'Too recent'}
        
        # 2. 检查记忆数量
        memory_count = memory_manager.get_memory_count(agent_id)
        if memory_count >= self.memory_count_threshold:
            return {
                'should_compress': True,
                'reason': f'Memory count {memory_count} exceeds threshold',
                'priority': 'high'
            }
        
        # 3. 检查存储大小
        storage_size = memory_manager.get_storage_size_mb(agent_id)
        if storage_size >= self.storage_size_threshold_mb:
            return {
                'should_compress': True,
                'reason': f'Storage size {storage_size}MB exceeds threshold',
                'priority': 'medium'
            }
        
        return {'should_compress': False, 'reason': 'No trigger'}
    
    def _get_last_compression_time(self, agent_id: str) -> Optional[datetime]:
        """获取上次压缩时间"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT MAX(created_at) FROM compressed_memories
            WHERE agent_id = ?
        """, (agent_id,))
        
        row = cursor.fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None
```

---

## 6. 数据库设计

### 6.1 压缩记忆表

```sql
-- 压缩记忆表
CREATE TABLE compressed_memories (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    original_memory_ids TEXT NOT NULL,  -- JSON数组
    compression_level TEXT NOT NULL,    -- raw/summary/topic
    compressed_content TEXT NOT NULL,
    compression_ratio REAL,
    key_points TEXT,                    -- JSON数组
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);

-- 索引
CREATE INDEX idx_compressed_agent ON compressed_memories(agent_id, created_at DESC);
CREATE INDEX idx_compressed_level ON compressed_memories(compression_level);

-- 压缩日志
CREATE TABLE compression_logs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    compression_type TEXT NOT NULL,
    memories_compressed INTEGER,
    compression_ratio REAL,
    time_taken_ms REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_compression_logs_agent ON compression_logs(agent_id, created_at DESC);
```

---

## 7. 配置示例

```yaml
# memory_compression.yaml
compression:
  # 层级压缩
  hierarchical:
    enabled: true
    time_threshold_days: 30
    count_threshold: 100
    target_ratio: 0.1  # 目标压缩率
    
    levels:
      raw:
        enabled: true
        retention_days: 90
      summary:
        enabled: true
        retention_days: 365
      topic:
        enabled: true
        retention_days: 730  # 2年
  
  # 语义压缩
  semantic:
    enabled: true
    min_similarity: 0.7  # 相似度阈值
    max_summary_length: 500  # 摘要最大长度
  
  # 触发策略
  triggers:
    time_interval_hours: 24
    memory_count_threshold: 1000
    storage_size_threshold_mb: 100
  
  # 压缩策略
  strategy:
    prefer_recent: true  # 优先保留近期记忆
    keep_important: true  # 保留重要记忆
    max_original_retention: 30  # 原始记忆最多保留天数
```

---

## 8. 监控指标

| 指标 | 说明 | 健康范围 |
|------|------|---------|
| **压缩率** | 压缩后大小/压缩前大小 | 10%-30% |
| **信息保留率** | 保留的关键信息比例 | > 80% |
| **压缩延迟** | 单次压缩耗时 | < 5秒 |
| **存储节省** | 压缩节省的存储空间 | > 50% |
| **检索准确率** | 压缩后检索准确率 | > 90% |
