# 记忆检索器（MemoryRetriever）详细设计

> **版本**: v1.0  
> **创建日期**: 2026-06-12  
> **基于论文**: MeMo: Memory as a Model (arXiv:2605.15156)

## 1. 概述

记忆检索器负责从记忆库中高效检索与查询相关的记忆。其核心挑战：
- **高效检索**：支持百万级记忆的快速检索
- **多模态支持**：支持文本、图像、音频等不同类型记忆
- **动态更新**：支持记忆的实时添加和删除

## 2. 混合检索架构

### 2.1 整体架构

```python
class HybridMemoryRetriever(nn.Module):
    """混合记忆检索器 - 稠密+稀疏+图检索"""
    
    def __init__(self, config: RetrieverConfig):
        super().__init__()
        
        # 1. 稠密检索器（基于向量相似度）
        self.dense_retriever = DenseRetriever(
            embedding_dim=config.embedding_dim,
            top_k=config.top_k,
            index_type=config.dense_index_type
        )
        
        # 2. 稀疏检索器（基于BM25）
        self.sparse_retriever = SparseRetriever(
            k1=config.bm25_k1,
            b=config.bm25_b,
            top_k=config.top_k
        )
        
        # 3. 图检索器（基于关系图谱）
        self.graph_retriever = GraphRetriever(
            max_hops=config.max_graph_hops,
            top_k=config.top_k
        )
        
        # 4. 混合策略网络
        self.hybrid_strategy = HybridRetrievalStrategy(
            num_retrievers=3,
            hidden_size=config.hidden_size
        )
        
        # 5. 重排序网络
        self.reranker = CrossEncoderReranker(
            max_length=config.max_rerank_length
        )
        
    def forward(
        self, 
        query_repr: QueryRepresentation,
        memory_store: MemoryStore
    ) -> List[RetrievedMemory]:
        """混合检索"""
        # 步骤1: 并行检索
        dense_results = self.dense_retriever(
            query_repr.sentence_embedding,
            memory_store.dense_index
        )
        
        sparse_results = self.sparse_retriever(
            query_repr.raw_text,
            memory_store.text_index
        )
        
        graph_results = self.graph_retriever(
            query_repr.sentence_embedding,
            memory_store.graph_index
        )
        
        # 步骤2: 混合策略
        hybrid_scores = self.hybrid_strategy(
            query_repr,
            dense_results,
            sparse_results,
            graph_results
        )
        
        # 步骤3: 合并去重
        merged_results = self.merge_results(
            dense_results,
            sparse_results,
            graph_results,
            hybrid_scores
        )
        
        # 步骤4: 重排序
        reranked_results = self.reranker.rerank(
            query_repr.raw_text,
            merged_results
        )
        
        return reranked_results[:self.config.top_k]
```

### 2.2 配置类

```python
@dataclass
class RetrieverConfig:
    """检索器配置"""
    embedding_dim: int = 768
    hidden_size: int = 512
    top_k: int = 10
    
    # 稠密检索配置
    dense_index_type: str = "faiss"  # faiss, hnsw, flat
    dense_top_k: int = 50
    
    # 稀疏检索配置
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    sparse_top_k: int = 50
    
    # 图检索配置
    max_graph_hops: int = 2
    graph_top_k: int = 20
    
    # 混合策略配置
    hybrid_weights: List[float] = [0.6, 0.3, 0.1]  # 稠密、稀疏、图
    
    # 重排序配置
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    max_rerank_length: int = 512
    
    # 性能配置
    use_cache: bool = True
    cache_size: int = 1000
    batch_size: int = 32
```

## 3. 核心组件详解

### 3.1 稠密检索器（DenseRetriever）

```python
class DenseRetriever:
    """稠密检索器 - 基于向量相似度"""
    
    def __init__(
        self, 
        embedding_dim: int, 
        top_k: int,
        index_type: str = "faiss"
    ):
        self.embedding_dim = embedding_dim
        self.top_k = top_k
        self.index_type = index_type
        
        # 初始化索引
        self.index = self._create_index()
        
    def _create_index(self):
        """创建向量索引"""
        if self.index_type == "faiss":
            import faiss
            # 使用IVF索引加速检索
            nlist = 100  # 聚类中心数
            quantizer = faiss.IndexFlatIP(self.embedding_dim)
            index = faiss.IndexIVFFlat(
                quantizer, 
                self.embedding_dim, 
                nlist,
                faiss.METRIC_INNER_PRODUCT
            )
            return index
        elif self.index_type == "hnsw":
            import hnswlib
            index = hnswlib.Index(space='cosine', dim=self.embedding_dim)
            return index
        else:
            return FlatIndex(self.embedding_dim)
    
    def search(
        self, 
        query_embedding: torch.Tensor,
        memory_embeddings: torch.Tensor,
        memory_ids: List[str]
    ) -> List[Tuple[str, float]]:
        """搜索相似记忆"""
        # 归一化
        query_norm = F.normalize(query_embedding, dim=-1)
        memory_norm = F.normalize(memory_embeddings, dim=-1)
        
        # 计算相似度
        scores = torch.mm(query_norm, memory_norm.T).squeeze(0)
        
        # Top-K
        top_scores, top_indices = torch.topk(scores, self.top_k)
        
        results = []
        for score, idx in zip(top_scores, top_indices):
            results.append((memory_ids[idx.item()], score.item()))
        
        return results
    
    def add_memory(self, memory_id: str, embedding: torch.Tensor):
        """添加记忆到索引"""
        if self.index_type == "faiss":
            self.index.add(embedding.cpu().numpy().reshape(1, -1))
        elif self.index_type == "hnsw":
            self.index.add_items(
                embedding.cpu().numpy().reshape(1, -1),
                np.array([len(self.memory_ids)])
            )
        
        self.memory_ids.append(memory_id)
        
    def remove_memory(self, memory_id: str):
        """从索引中删除记忆"""
        if memory_id in self.memory_ids:
            idx = self.memory_ids.index(memory_id)
            # FAISS不支持直接删除，需要重建索引
            # 或者使用标记删除
            self.memory_ids[idx] = None
```

### 3.2 稀疏检索器（SparseRetriever）

```python
class SparseRetriever:
    """稀疏检索器 - 基于BM25"""
    
    def __init__(self, k1: float = 1.5, b: float = 0.75, top_k: int = 10):
        self.k1 = k1
        self.b = b
        self.top_k = top_k
        
        # BM25参数
        self.avg_dl = 0
        self.doc_freqs = {}
        self.idf = {}
        
    def build_index(self, documents: List[str]):
        """构建BM25索引"""
        # 分词
        tokenized_docs = [self.tokenize(doc) for doc in documents]
        
        # 计算文档频率
        self.doc_freqs = {}
        for doc in tokenized_docs:
            for term in set(doc):
                self.doc_freqs[term] = self.doc_freqs.get(term, 0) + 1
        
        # 计算IDF
        n_docs = len(documents)
        self.idf = {}
        for term, df in self.doc_freqs.items():
            self.idf[term] = math.log((n_docs - df + 0.5) / (df + 0.5) + 1)
        
        # 计算平均文档长度
        self.avg_dl = sum(len(doc) for doc in tokenized_docs) / n_docs
        
        # 存储文档
        self.documents = tokenized_docs
        self.doc_lengths = [len(doc) for doc in tokenized_docs]
    
    def search(
        self, 
        query: str, 
        documents: List[str]
    ) -> List[Tuple[int, float]]:
        """BM25检索"""
        query_terms = self.tokenize(query)
        
        scores = []
        for doc_idx, doc in enumerate(self.documents):
            score = self._compute_bm25_score(query_terms, doc_idx)
            scores.append((doc_idx, score))
        
        # 排序
        scores.sort(key=lambda x: x[1], reverse=True)
        
        return scores[:self.top_k]
    
    def _compute_bm25_score(
        self, 
        query_terms: List[str], 
        doc_idx: int
    ) -> float:
        """计算BM25分数"""
        score = 0.0
        doc = self.documents[doc_idx]
        doc_len = self.doc_lengths[doc_idx]
        
        # 词频统计
        term_freqs = {}
        for term in doc:
            term_freqs[term] = term_freqs.get(term, 0) + 1
        
        for term in query_terms:
            if term not in self.idf:
                continue
                
            tf = term_freqs.get(term, 0)
            idf = self.idf[term]
            
            # BM25公式
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avg_dl)
            
            score += idf * numerator / denominator
        
        return score
    
    def tokenize(self, text: str) -> List[str]:
        """分词"""
        # 简单的空格分词，实际项目中应该使用jieba等分词工具
        return text.lower().split()
```

### 3.3 图检索器（GraphRetriever）

```python
class GraphRetriever:
    """图检索器 - 基于关系图谱"""
    
    def __init__(self, max_hops: int = 2, top_k: int = 10):
        self.max_hops = max_hops
        self.top_k = top_k
        
    def search(
        self, 
        query_embedding: torch.Tensor,
        graph: MemoryGraph,
        seed_nodes: List[str]
    ) -> List[Tuple[str, float]]:
        """图检索 - 从种子节点出发遍历"""
        visited = set()
        results = []
        
        # BFS遍历
        queue = [(node, 0, 1.0) for node in seed_nodes]  # (node, hop, score)
        
        while queue and len(results) < self.top_k:
            current_node, hop, score = queue.pop(0)
            
            if current_node in visited or hop > self.max_hops:
                continue
            
            visited.add(current_node)
            
            # 获取节点信息
            node_data = graph.get_node(current_node)
            if node_data is None:
                continue
            
            # 计算与查询的相关度
            node_embedding = node_data.get("embedding")
            if node_embedding is not None:
                similarity = F.cosine_similarity(
                    query_embedding.unsqueeze(0),
                    torch.tensor(node_embedding).unsqueeze(0)
                ).item()
                
                final_score = score * similarity
                results.append((current_node, final_score))
            
            # 扩展邻居节点
            neighbors = graph.get_neighbors(current_node)
            for neighbor, edge_weight in neighbors:
                if neighbor not in visited:
                    new_score = score * edge_weight
                    queue.append((neighbor, hop + 1, new_score))
        
        # 排序
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:self.top_k]
```

### 3.4 混合策略网络（HybridRetrievalStrategy）

```python
class HybridRetrievalStrategy(nn.Module):
    """混合检索策略 - 学习最优混合权重"""
    
    def __init__(self, num_retrievers: int, hidden_size: int):
        super().__init__()
        
        # 策略网络
        self.strategy_network = nn.Sequential(
            nn.Linear(hidden_size * 3, hidden_size),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_size, num_retrievers),
            nn.Softmax(dim=-1)
        )
        
        # 结果融合
        self.result_fusion = CrossAttentionFusion(hidden_size)
        
    def forward(
        self,
        query_repr: QueryRepresentation,
        dense_results: List[RetrievedMemory],
        sparse_results: List[RetrievedMemory],
        graph_results: List[RetrievedMemory]
    ) -> torch.Tensor:
        """计算混合权重"""
        # 提取特征
        query_features = query_repr.sentence_embedding
        
        dense_features = self._extract_result_features(dense_results)
        sparse_features = self._extract_result_features(sparse_results)
        graph_features = self._extract_result_features(graph_results)
        
        # 拼接特征
        combined_features = torch.cat([
            query_features,
            dense_features,
            sparse_features,
            graph_features
        ], dim=-1)
        
        # 计算权重
        weights = self.strategy_network(combined_features)
        
        return weights.squeeze(0)
    
    def _extract_result_features(
        self, 
        results: List[RetrievedMemory]
    ) -> torch.Tensor:
        """从检索结果中提取特征"""
        if not results:
            return torch.zeros(self.hidden_size)
        
        # 平均嵌入
        embeddings = [r.embedding for r in results if r.embedding is not None]
        if embeddings:
            avg_embedding = torch.stack(embeddings).mean(dim=0)
        else:
            avg_embedding = torch.zeros(self.hidden_size)
        
        return avg_embedding
```

### 3.5 重排序网络（CrossEncoderReranker）

```python
class CrossEncoderReranker:
    """交叉编码器重排序"""
    
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name)
        
    def rerank(
        self, 
        query: str, 
        candidates: List[RetrievedMemory],
        top_k: int = 10
    ) -> List[RetrievedMemory]:
        """重排序候选结果"""
        if not candidates:
            return []
        
        # 构建查询-文档对
        pairs = [(query, c.content) for c in candidates]
        
        # 计算相关性分数
        scores = self.model.predict(pairs)
        
        # 更新分数
        for candidate, score in zip(candidates, scores):
            candidate.score = float(score)
        
        # 排序
        candidates.sort(key=lambda x: x.score, reverse=True)
        
        return candidates[:top_k]
```

## 4. 索引构建与管理

### 4.1 索引构建流程

```python
class MemoryIndexBuilder:
    """记忆索引构建器"""
    
    def __init__(self, config: RetrieverConfig):
        self.config = config
        self.dense_index = None
        self.sparse_index = None
        
    def build_index(self, memories: List[Memory]):
        """构建索引"""
        # 1. 构建稠密索引
        self._build_dense_index(memories)
        
        # 2. 构建稀疏索引
        self._build_sparse_index(memories)
        
        # 3. 构建图索引
        self._build_graph_index(memories)
        
    def _build_dense_index(self, memories: List[Memory]):
        """构建稠密索引"""
        # 提取嵌入
        embeddings = []
        memory_ids = []
        
        for memory in memories:
            if memory.embedding is not None:
                embeddings.append(memory.embedding)
                memory_ids.append(memory.id)
        
        if not embeddings:
            return
        
        # 堆叠为张量
        embeddings_tensor = torch.stack(embeddings)
        
        # 创建索引
        self.dense_index = DenseRetriever(
            embedding_dim=self.config.embedding_dim,
            top_k=self.config.dense_top_k,
            index_type=self.config.dense_index_type
        )
        
        # 添加记忆
        for memory_id, embedding in zip(memory_ids, embeddings):
            self.dense_index.add_memory(memory_id, embedding)
    
    def _build_sparse_index(self, memories: List[Memory]):
        """构建稀疏索引"""
        # 提取文本
        texts = []
        memory_ids = []
        
        for memory in memories:
            texts.append(memory.content)
            memory_ids.append(memory.id)
        
        # 创建索引
        self.sparse_index = SparseRetriever(
            k1=self.config.bm25_k1,
            b=self.config.bm25_b,
            top_k=self.config.sparse_top_k
        )
        
        # 构建索引
        self.sparse_index.build_index(texts)
        self.sparse_memory_ids = memory_ids
```

### 4.2 索引更新策略

```python
class IndexUpdateStrategy:
    """索引更新策略"""
    
    def __init__(self, config: RetrieverConfig):
        self.config = config
        self.update_queue = []
        
    def add_memory(self, memory: Memory):
        """添加记忆到更新队列"""
        self.update_queue.append(memory)
        
        # 如果队列达到批量大小，执行更新
        if len(self.update_queue) >= self.config.batch_size:
            self.flush_updates()
    
    def flush_updates(self):
        """执行批量更新"""
        if not self.update_queue:
            return
        
        # 更新稠密索引
        self._update_dense_index(self.update_queue)
        
        # 更新稀疏索引
        self._update_sparse_index(self.update_queue)
        
        # 清空队列
        self.update_queue.clear()
    
    def _update_dense_index(self, memories: List[Memory]):
        """更新稠密索引"""
        for memory in memories:
            if memory.embedding is not None:
                self.dense_index.add_memory(memory.id, memory.embedding)
    
    def _update_sparse_index(self, memories: List[Memory]):
        """更新稀疏索引"""
        # 需要重建稀疏索引（BM25不支持增量更新）
        # 或者使用支持增量更新的实现
        pass
```

## 5. 性能优化

### 5.1 缓存机制

```python
class RetrievalCache:
    """检索缓存"""
    
    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        self.max_size = max_size
        self.ttl = ttl
        self.cache = {}
        self.access_times = {}
        
    def get(self, query_hash: str) -> Optional[List[RetrievedMemory]]:
        """获取缓存"""
        if query_hash in self.cache:
            # 检查是否过期
            if time.time() - self.access_times[query_hash] < self.ttl:
                return self.cache[query_hash]
            else:
                # 过期，删除
                del self.cache[query_hash]
                del self.access_times[query_hash]
        
        return None
    
    def set(self, query_hash: str, results: List[RetrievedMemory]):
        """设置缓存"""
        # 检查缓存大小
        if len(self.cache) >= self.max_size:
            # 删除最旧的条目
            oldest_key = min(self.access_times, key=self.access_times.get)
            del self.cache[oldest_key]
            del self.access_times[oldest_key]
        
        self.cache[query_hash] = results
        self.access_times[query_hash] = time.time()
```

### 5.2 异步处理

```python
class AsyncRetriever:
    """异步检索器"""
    
    def __init__(self, retriever: HybridMemoryRetriever):
        self.retriever = retriever
        self.executor = ThreadPoolExecutor(max_workers=4)
        
    async def retrieve_async(
        self, 
        query: str, 
        context: Dict
    ) -> List[RetrievedMemory]:
        """异步检索"""
        loop = asyncio.get_event_loop()
        
        # 在线程池中执行检索
        results = await loop.run_in_executor(
            self.executor,
            self.retriever.retrieve,
            query,
            context
        )
        
        return results
```

### 5.3 批处理

```python
class BatchRetriever:
    """批量检索器"""
    
    def __init__(self, retriever: HybridMemoryRetriever, batch_size: int = 32):
        self.retriever = retriever
        self.batch_size = batch_size
        
    def batch_retrieve(
        self, 
        queries: List[str], 
        contexts: List[Dict]
    ) -> List[List[RetrievedMemory]]:
        """批量检索"""
        results = []
        
        for i in range(0, len(queries), self.batch_size):
            batch_queries = queries[i:i + self.batch_size]
            batch_contexts = contexts[i:i + self.batch_size]
            
            batch_results = []
            for query, context in zip(batch_queries, batch_contexts):
                result = self.retriever.retrieve(query, context)
                batch_results.append(result)
            
            results.extend(batch_results)
        
        return results
```

## 6. 评估指标

### 6.1 检索质量指标

```python
def compute_retrieval_metrics(
    predictions: List[List[str]], 
    ground_truth: List[List[str]],
    k_values: List[int] = [1, 5, 10]
) -> Dict[str, float]:
    """计算检索质量指标"""
    metrics = {}
    
    for k in k_values:
        # Precision@K
        precision_at_k = []
        for pred, gt in zip(predictions, ground_truth):
            pred_at_k = pred[:k]
            precision = len(set(pred_at_k) & set(gt)) / k
            precision_at_k.append(precision)
        
        metrics[f"precision_at_{k}"] = np.mean(precision_at_k)
        
        # Recall@K
        recall_at_k = []
        for pred, gt in zip(predictions, ground_truth):
            pred_at_k = pred[:k]
            recall = len(set(pred_at_k) & set(gt)) / len(gt)
            recall_at_k.append(recall)
        
        metrics[f"recall_at_{k}"] = np.mean(recall_at_k)
        
        # MRR
        mrr = []
        for pred, gt in zip(predictions, ground_truth):
            for i, p in enumerate(pred):
                if p in gt:
                    mrr.append(1 / (i + 1))
                    break
            else:
                mrr.append(0)
        
        metrics["mrr"] = np.mean(mrr)
        
        # NDCG@K
        ndcg_at_k = []
        for pred, gt in zip(predictions, ground_truth):
            pred_at_k = pred[:k]
            relevance = [1 if p in gt else 0 for p in pred_at_k]
            ndcg = compute_ndcg(relevance, k)
            ndcg_at_k.append(ndcg)
        
        metrics[f"ndcg_at_{k}"] = np.mean(ndcg_at_k)
    
    return metrics
```

### 6.2 性能指标

```python
def compute_performance_metrics(
    retrieval_times: List[float],
    memory_sizes: List[int]
) -> Dict[str, float]:
    """计算性能指标"""
    metrics = {}
    
    # 平均检索时间
    metrics["avg_retrieval_time"] = np.mean(retrieval_time