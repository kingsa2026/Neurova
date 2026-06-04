# 向量检索机制架构设计

## 1. 概述

### 1.1 设计理念

向量检索机制为记忆系统提供**语义级理解能力**，突破关键词匹配的局限：

> **用户说"心情不好"，能检索到"最近有点抑郁"的记忆；用户问"上次那个项目"，能检索到"上周完成的系统设计"。语义相似度让记忆检索更接近人类的"意会"能力。**

### 1.2 检索架构

```
完整检索系统
├── 关键词检索 (Keyword Retrieval) - 现有
│   ├── 倒排索引
│   ├── 精确匹配
│   └── 快速响应 (<5ms)
│
├── 向量检索 (Vector Retrieval) - 新增
│   ├── 语义嵌入 (Embedding)
│   ├── 相似度计算 (Cosine Similarity)
│   └── 语义理解 (50-100ms)
│
├── 混合检索 (Hybrid Retrieval)
│   ├── RRF (Reciprocal Rank Fusion)
│   ├── 权重可调
│   └── 综合排序
│
└── 检索协调器 (Retrieval Coordinator)
    ├── 智能路由
    ├── 结果融合
    └── 缓存优化
```

### 1.3 关键词 vs 向量检索对比

| 维度 | 关键词检索 | 向量检索 | 混合检索 |
|------|-----------|---------|---------|
| **原理** | 词汇精确匹配 | 语义向量相似度 | 两者结合 |
| **优势** | 精确、快速 | 语义理解、模糊匹配 | 兼顾精确与语义 |
| **局限** | 无法理解同义词 | 可能丢失精确匹配 | 计算复杂度较高 |
| **延迟** | 1-5ms | 50-100ms | 20-50ms |
| **适用场景** | 专有名词、日期 | 开放问题、意图理解 | 通用场景 |

---

## 2. 向量嵌入层

### 2.1 嵌入模型接口

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Optional
import numpy as np

@dataclass
class Embedding:
    """向量嵌入"""
    text: str
    vector: List[float]
    model_name: str
    dimension: int
    created_at: str

class EmbeddingModel(ABC):
    """嵌入模型抽象接口"""
    
    @abstractmethod
    def encode(self, text: str) -> List[float]:
        """将文本编码为向量"""
        pass
    
    @abstractmethod
    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """批量编码"""
        pass
    
    @property
    @abstractmethod
    def dimension(self) -> int:
        """向量维度"""
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """模型名称"""
        pass

class LocalEmbeddingModel(EmbeddingModel):
    """
    本地嵌入模型
    使用 sentence-transformers 等本地模型
    """
    
    def __init__(self, model_path: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_path)
        self._dimension = self.model.get_sentence_embedding_dimension()
        self._model_name = model_path
    
    def encode(self, text: str) -> List[float]:
        embedding = self.model.encode(text)
        return embedding.tolist()
    
    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(texts)
        return embeddings.tolist()
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    @property
    def model_name(self) -> str:
        return self._model_name

class APIEmbeddingModel(EmbeddingModel):
    """
    API嵌入模型
    使用 OpenAI、智谱等云端模型
    """
    
    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.api_key = api_key
        self.model_name = model
        self._dimension = 1536 if "small" in model else 3072
    
    def encode(self, text: str) -> List[float]:
        # 调用 API 获取嵌入
        # 此处为伪代码
        response = self._call_api(text)
        return response['embedding']
    
    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.encode(text) for text in texts]
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    @property
    def model_name(self) -> str:
        return self._model_name
```

### 2.2 嵌入管理器

```python
class EmbeddingManager:
    """
    嵌入管理器
    管理记忆的向量嵌入生成、存储、更新
    """
    
    def __init__(self, db_connection, embedding_model: EmbeddingModel, config=None):
        self.db = db_connection
        self.model = embedding_model
        self.config = config or {}
        
        # 批量处理配置
        self.batch_size = self.config.get('batch_size', 100)
        
        # 初始化向量存储
        self._init_vector_store()
    
    def _init_vector_store(self):
        """初始化向量存储"""
        # 方案1: SQLite扩展 (sqlite-vss)
        # 方案2: 独立FAISS索引
        # 方案3: JSON存储 (小规模)
        
        store_type = self.config.get('vector_store', 'json')
        
        if store_type == 'json':
            # 使用SQLite存储向量 (适合<10万记忆)
            self.vector_store = SQLiteVectorStore(self.db, self.model)
        elif store_type == 'faiss':
            # 使用FAISS (适合大规模)
            self.vector_store = FAISSVectorStore(self.model)
        elif store_type == 'sqlite_vss':
            # 使用SQLite-VSS扩展
            self.vector_store = SQLiteVSSStore(self.db, self.model)
    
    def generate_embedding(self, memory_id: str, content: str) -> Embedding:
        """
        为记忆生成向量嵌入
        
        Args:
            memory_id: 记忆ID
            content: 记忆内容
        """
        vector = self.model.encode(content)
        
        embedding = Embedding(
            text=content,
            vector=vector,
            model_name=self.model.model_name,
            dimension=self.model.dimension,
            created_at=datetime.now().isoformat()
        )
        
        # 存储向量
        self.vector_store.save_embedding(memory_id, vector)
        
        return embedding
    
    def batch_generate_embeddings(self, memories: List[Dict]) -> int:
        """
        批量生成向量嵌入
        
        Args:
            memories: 记忆列表 [(id, content), ...]
        
        Returns:
            成功生成的数量
        """
        success_count = 0
        
        # 分批处理
        for i in range(0, len(memories), self.batch_size):
            batch = memories[i:i + self.batch_size]
            
            # 批量编码
            contents = [m['content'] for m in batch]
            vectors = self.model.encode_batch(contents)
            
            # 批量存储
            for (memory_id, _), vector in zip(batch, vectors):
                self.vector_store.save_embedding(memory_id, vector)
                success_count += 1
        
        return success_count
    
    def update_embedding(self, memory_id: str, new_content: str) -> Embedding:
        """更新记忆的向量嵌入"""
        return self.generate_embedding(memory_id, new_content)
    
    def delete_embedding(self, memory_id: str):
        """删除记忆的向量嵌入"""
        self.vector_store.delete_embedding(memory_id)
```

---

## 3. 向量存储层

### 3.1 SQLite向量存储 (JSON方案)

```python
class SQLiteVectorStore:
    """
    SQLite向量存储
    适合中小规模 (<10万记忆)
    """
    
    def __init__(self, db_connection, embedding_model: EmbeddingModel):
        self.db = db_connection
        self.model = embedding_model
        self._create_table()
    
    def _create_table(self):
        """创建向量存储表"""
        cursor = self.db.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_embeddings (
                memory_id TEXT PRIMARY KEY,
                vector_json TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                model_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
            )
        """)
        self.db.commit()
    
    def save_embedding(self, memory_id: str, vector: List[float]):
        """保存向量"""
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO memory_embeddings 
            (memory_id, vector_json, dimension, model_name, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            memory_id,
            json.dumps(vector),
            len(vector),
            self.model.model_name
        ))
        self.db.commit()
    
    def get_embedding(self, memory_id: str) -> Optional[List[float]]:
        """获取向量"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT vector_json FROM memory_embeddings
            WHERE memory_id = ?
        """, (memory_id,))
        
        row = cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None
    
    def delete_embedding(self, memory_id: str):
        """删除向量"""
        cursor = self.db.cursor()
        cursor.execute("""
            DELETE FROM memory_embeddings WHERE memory_id = ?
        """, (memory_id,))
        self.db.commit()
    
    def search_by_similarity(
        self,
        query_vector: List[float],
        agent_id: str,
        top_k: int = 10,
        threshold: float = 0.0
    ) -> List[Tuple[str, float]]:
        """
        相似度检索
        
        流程:
        1. 获取所有向量
        2. 计算余弦相似度
        3. 过滤与排序
        """
        cursor = self.db.cursor()
        
        # 获取目标记忆的向量
        cursor.execute("""
            SELECT me.memory_id, me.vector_json
            FROM memory_embeddings me
            INNER JOIN memories m ON me.memory_id = m.id
            WHERE m.agent_id = ?
              AND m.lifecycle_stage IN ('active', 'secondary')
        """, (agent_id,))
        
        results = []
        for row in cursor.fetchall():
            memory_id = row[0]
            vector = json.loads(row[1])
            
            # 计算余弦相似度
            similarity = self._cosine_similarity(query_vector, vector)
            
            if similarity >= threshold:
                results.append((memory_id, similarity))
        
        # 排序
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:top_k]
    
    def _cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """计算余弦相似度"""
        vec_a = np.array(vec_a)
        vec_b = np.array(vec_b)
        
        dot_product = np.dot(vec_a, vec_b)
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(dot_product / (norm_a * norm_b))
```

### 3.2 FAISS向量存储 (大规模方案)

```python
class FAISSVectorStore:
    """
    FAISS向量存储
    适合大规模 (>10万记忆)
    """
    
    def __init__(self, embedding_model: EmbeddingModel, config=None):
        import faiss
        self.model = embedding_model
        self.config = config or {}
        
        # FAISS索引
        dimension = self.model.dimension
        self.index = faiss.IndexFlatIP(dimension)  # 内积索引
        
        # ID映射
        self.id_map: Dict[int, str] = {}  # FAISS ID -> Memory ID
        self.reverse_map: Dict[str, int] = {}  # Memory ID -> FAISS ID
        
        # 持久化
        self.index_path = self.config.get('index_path', 'memory_vectors.index')
        self.id_map_path = self.config.get('id_map_path', 'memory_id_map.json')
        
        # 加载已有索引
        self._load_index()
    
    def save_embedding(self, memory_id: str, vector: List[float]):
        """保存向量到FAISS"""
        import numpy as np
        
        # 添加到索引
        vector_np = np.array([vector]).astype('float32')
        faiss.normalize_L2(vector_np)  # 归一化
        
        faiss_id = self.index.ntotal
        self.index.add(vector_np)
        
        # 更新映射
        self.id_map[faiss_id] = memory_id
        self.reverse_map[memory_id] = faiss_id
    
    def search_by_similarity(
        self,
        query_vector: List[float],
        agent_id: str,
        top_k: int = 10,
        threshold: float = 0.0
    ) -> List[Tuple[str, float]]:
        """FAISS相似度检索"""
        import numpy as np
        
        # 归一化查询向量
        query_np = np.array([query_vector]).astype('float32')
        faiss.normalize_L2(query_np)
        
        # 搜索
        distances, indices = self.index.search(query_np, top_k)
        
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:  # FAISS返回-1表示空
                continue
            
            if dist >= threshold:
                memory_id = self.id_map.get(idx)
                if memory_id:
                    results.append((memory_id, float(dist)))
        
        return results
    
    def _save_index(self):
        """持久化索引"""
        import faiss
        faiss.write_index(self.index, self.index_path)
        
        with open(self.id_map_path, 'w') as f:
            json.dump(self.id_map, f)
    
    def _load_index(self):
        """加载持久化索引"""
        import faiss
        import os
        
        if os.path.exists(self.index_path):
            self.index = faiss.read_index(self.index_path)
            
            if os.path.exists(self.id_map_path):
                with open(self.id_map_path, 'r') as f:
                    self.id_map = json.load(f)
                self.reverse_map = {v: k for k, v in self.id_map.items()}
```

---

## 4. 混合检索层

### 4.1 RRF融合算法

```python
class HybridRetrievalEngine:
    """
    混合检索引擎
    融合关键词检索和向量检索结果
    """
    
    def __init__(self, memory_manager, embedding_manager, config=None):
        self.memory_manager = memory_manager
        self.embedding_manager = embedding_manager
        self.config = config or {}
        
        # 融合权重
        self.keyword_weight = self.config.get('keyword_weight', 0.5)
        self.vector_weight = self.config.get('vector_weight', 0.5)
        
        # RRF参数
        self.rrf_k = self.config.get('rrf_k', 60)  # RRF常数
    
    def hybrid_search(
        self,
        query: str,
        agent_id: str,
        top_k: int = 10,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """
        混合检索
        
        流程:
        1. 关键词检索
        2. 向量检索
        3. RRF融合
        4. 应用过滤
        5. 返回结果
        """
        # 1. 关键词检索
        keyword_results = self._keyword_search(query, agent_id, top_k * 2, filters)
        
        # 2. 向量检索
        vector_results = self._vector_search(query, agent_id, top_k * 2, filters)
        
        # 3. RRF融合
        fused_results = self._rrf_fusion(keyword_results, vector_results)
        
        # 4. 应用过滤
        if filters:
            fused_results = self._apply_filters(fused_results, filters)
        
        # 5. 返回 top_k
        return fused_results[:top_k]
    
    def _keyword_search(
        self,
        query: str,
        agent_id: str,
        top_k: int,
        filters: Optional[Dict]
    ) -> List[Dict]:
        """关键词检索"""
        memories = self.memory_manager.search_memories(
            query=query,
            agent_id=agent_id,
            limit=top_k
        )
        
        return [
            {
                'memory_id': m.id,
                'score': self._calculate_keyword_score(m, query),
                'source': 'keyword'
            }
            for m in memories
        ]
    
    def _vector_search(
        self,
        query: str,
        agent_id: str,
        top_k: int,
        filters: Optional[Dict]
    ) -> List[Dict]:
        """向量检索"""
        # 生成查询向量
        query_vector = self.embedding_manager.model.encode(query)
        
        # 向量相似度搜索
        results = self.embedding_manager.vector_store.search_by_similarity(
            query_vector,
            agent_id,
            top_k=top_k,
            threshold=0.3
        )
        
        return [
            {
                'memory_id': memory_id,
                'score': similarity,
                'source': 'vector'
            }
            for memory_id, similarity in results
        ]
    
    def _rrf_fusion(
        self,
        keyword_results: List[Dict],
        vector_results: List[Dict]
    ) -> List[Dict]:
        """
        RRF (Reciprocal Rank Fusion) 融合
        
        RRF(d) = Σ 1/(k + r(d))
        其中:
        - k: 常数 (通常60)
        - r(d): 文档在结果中的排名
        """
        # 构建排名映射
        keyword_ranks = {
            r['memory_id']: rank + 1
            for rank, r in enumerate(keyword_results)
        }
        vector_ranks = {
            r['memory_id']: rank + 1
            for rank, r in enumerate(vector_results)
        }
        
        # 计算RRF分数
        all_memory_ids = set(keyword_ranks.keys()) | set(vector_ranks.keys())
        
        fused_scores = {}
        for memory_id in all_memory_ids:
            keyword_rank = keyword_ranks.get(memory_id, float('inf'))
            vector_rank = vector_ranks.get(memory_id, float('inf'))
            
            rrf_score = (
                self.keyword_weight / (self.rrf_k + keyword_rank) +
                self.vector_weight / (self.rrf_k + vector_rank)
            )
            
            fused_scores[memory_id] = rrf_score
        
        # 排序
        sorted_results = sorted(
            fused_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        return [
            {
                'memory_id': memory_id,
                'score': score,
                'source': 'hybrid'
            }
            for memory_id, score in sorted_results
        ]
    
    def _calculate_keyword_score(self, memory: Memory, query: str) -> float:
        """计算关键词相关性分数"""
        # 简单实现: Jaccard相似度
        query_words = set(query.lower().split())
        memory_words = set(memory.content.lower().split())
        
        intersection = query_words & memory_words
        union = query_words | memory_words
        
        if not union:
            return 0.0
        
        jaccard = len(intersection) / len(union)
        
        # 加权温度
        temp_factor = memory.temperature / 100.0
        
        return jaccard * 0.6 + temp_factor * 0.4
    
    def _apply_filters(self, results: List[Dict], filters: Dict) -> List[Dict]:
        """应用过滤器"""
        # 根据过滤器筛选结果
        # 例如: category, type, min_temperature等
        return results
```

---

## 5. 检索协调器

### 5.1 智能路由

```python
class RetrievalCoordinator:
    """
    检索协调器
    智能选择检索策略
    """
    
    def __init__(self, memory_manager, embedding_manager, hybrid_engine):
        self.memory_manager = memory_manager
        self.embedding_manager = embedding_manager
        self.hybrid_engine = hybrid_engine
    
    def search(
        self,
        query: str,
        agent_id: str,
        mode: str = 'auto',
        **kwargs
    ) -> List[Memory]:
        """
        智能检索
        
        Args:
            query: 查询内容
            agent_id: Agent ID
            mode: 检索模式
                - 'keyword': 仅关键词
                - 'vector': 仅向量
                - 'hybrid': 混合检索
                - 'auto': 自动选择
        """
        if mode == 'auto':
            mode = self._select_search_mode(query)
        
        if mode == 'keyword':
            return self._keyword_only_search(query, agent_id, **kwargs)
        elif mode == 'vector':
            return self._vector_only_search(query, agent_id, **kwargs)
        else:
            return self._hybrid_search(query, agent_id, **kwargs)
    
    def _select_search_mode(self, query: str) -> str:
        """
        自动选择检索模式
        
        规则:
        - 包含专有名词 → 关键词检索
        - 开放问题 → 向量检索
        - 其他 → 混合检索
        """
        # 简单启发式规则
        if self._has_proper_nouns(query):
            return 'keyword'
        elif len(query.split()) > 5:
            return 'hybrid'
        else:
            return 'vector'
    
    def _has_proper_nouns(self, query: str) -> bool:
        """检测是否包含专有名词"""
        # 简单实现: 检测大写、数字、特殊符号
        import re
        # 检测日期、时间、专有名词模式
        patterns = [
            r'\d{4}-\d{2}-\d{2}',  # 日期
            r'[A-Z]{2,}',          # 大写缩写
            r'#[\w]+',             # 标签
        ]
        
        for pattern in patterns:
            if re.search(pattern, query):
                return True
        
        return False
```

---

## 6. 数据库设计

### 6.1 向量存储表

```sql
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

-- 索引
CREATE INDEX idx_embeddings_model ON memory_embeddings(model_name);

-- 检索日志
CREATE TABLE retrieval_logs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    query TEXT,
    mode TEXT NOT NULL,  -- keyword/vector/hybrid
    results_count INTEGER,
    latency_ms REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_retrieval_logs_agent ON retrieval_logs(agent_id, created_at DESC);
```

---

## 7. 配置示例

```yaml
# vector_retrieval.yaml
vector_retrieval:
  # 嵌入模型
  embedding_model:
    type: local  # local/api
    model: "all-MiniLM-L6-v2"  # 384维，轻量级
    # 或使用API:
    # type: api
    # model: "text-embedding-3-small"
    # api_key: ${OPENAI_API_KEY}
  
  # 向量存储
  vector_store:
    type: json  # json/faiss/sqlite_vss
    # FAISS配置:
    # index_path: "data/memory_vectors.index"
    # id_map_path: "data/memory_id_map.json"
  
  # 混合检索
  hybrid_search:
    keyword_weight: 0.5
    vector_weight: 0.5
    rrf_k: 60
  
  # 批处理
  batch:
    size: 100
    interval_seconds: 300  # 每5分钟处理一次
  
  # 缓存
  cache:
    enabled: true
    ttl: 300  # 5分钟
    max_size: 1000
```

---

## 8. 性能优化

### 8.1 优化策略

| 策略 | 说明 | 效果 |
|------|------|------|
| **向量缓存** | 缓存高频查询结果 | 减少重复计算 |
| **异步生成** | 新记忆异步生成向量 | 不阻塞写入 |
| **批量编码** | 批量调用嵌入模型 | 提升吞吐量 |
| **索引优化** | FAISS HNSW索引 | 加速大规模检索 |
| **分层检索** | 先关键词过滤，再向量排序 | 减少计算量 |

---

## 9. 监控指标

| 指标 | 说明 | 健康范围 |
|------|------|---------|
| **向量覆盖率** | 有向量的记忆比例 | > 95% |
| **检索延迟** | 向量检索响应时间 | < 100ms |
| **混合检索准确率** | 混合检索结果相关性 | > 80% |
| **嵌入模型一致性** | 向量维度一致性 | 100% |
