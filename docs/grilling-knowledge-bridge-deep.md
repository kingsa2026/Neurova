# 深入 Grilling: MemoryKnowledgeBridge

## 关键设计问题讨论

### 问题 1：知识图谱与记忆系统的集成点在哪里？

**当前状态分析：**

```
KnowledgeGraphManager (988行)
├── 节点管理：add_node, update_node, delete_node
├── 边管理：add_edge, update_edge, delete_edge
├── 查询：search_nodes, get_node, get_neighbors
├── 遍历：bfs, dfs, shortest_path
├── 子图：extract_subgraph
└── 持久化：save_to_file, load_from_file

NeurovaRecallEngine
├── RecallChannel.GRAPH — 已定义但未实现
├── 6通道并行检索
└── 意图驱动钻取

MemoryRecord
├── content, category, emotion
├── agent_id, user_id
└── 无图谱节点关联
```

**集成点识别：**

1. **记忆写入时**：提取实体 → 创建图谱节点
2. **记忆检索时**：图谱遍历 → 补充关联记忆
3. **知识更新时**：传播到关联记忆 → 更新图谱权重

**候选接口设计：**

```python
class MemoryKnowledgeBridge:
    """记忆系统与知识图谱的桥梁"""
    
    def __init__(self, 
                 knowledge_graph: KnowledgeGraphManager,
                 memory_manager: MemoryManager,
                 entity_extractor: Optional[EntityExtractor] = None):
        self._kg = knowledge_graph
        self._mm = memory_manager
        self._extractor = entity_extractor or DefaultEntityExtractor()
    
    def enrich_memory_with_graph(self, memory: MemoryRecord) -> MemoryRecord:
        """用图谱信息丰富记忆"""
        # 1. 提取记忆中的实体
        entities = self._extractor.extract(memory.content)
        
        # 2. 在图谱中查找或创建节点
        node_ids = []
        for entity in entities:
            node = self._find_or_create_node(entity, memory)
            node_ids.append(node.node_id)
        
        # 3. 创建记忆节点并关联
        memory_node = self._create_memory_node(memory, node_ids)
        
        # 4. 更新记忆的图谱字段
        memory.metadata["graph_node_id"] = memory_node.node_id
        memory.metadata["related_entities"] = node_ids
        
        return memory
    
    def retrieve_related_memories(self, 
                                   memory_id: str, 
                                   max_depth: int = 2) -> List[MemoryRecord]:
        """通过图谱关系检索关联记忆"""
        # 1. 获取记忆节点
        memory_node = self._kg.get_node(memory_id)
        if not memory_node:
            return []
        
        # 2. BFS获取关联节点
        related_nodes = self._kg.bfs(memory_id, max_depth=max_depth)
        
        # 3. 过滤出记忆节点
        memory_nodes = [n for n in related_nodes 
                       if n.node_type == NodeType.MEMORY]
        
        # 4. 转换为MemoryRecord
        memories = []
        for node in memory_nodes:
            memory = self._mm.get_memory(node.node_id)
            if memory:
                memories.append(memory)
        
        return memories
    
    def build_graph_from_conversation(self, 
                                       conversation: List[Dict]) -> GraphStats:
        """从对话中自动构建图谱"""
        stats = GraphStats()
        
        for message in conversation:
            content = message.get("content", "")
            entities = self._extractor.extract(content)
            
            # 创建实体节点
            for entity in entities:
                node = self._find_or_create_node(entity)
                stats.node_count += 1
            
            # 创建实体间关系
            for i, e1 in enumerate(entities):
                for e2 in entities[i+1:]:
                    self._add_relation(e1, e2, content)
                    stats.edge_count += 1
        
        return stats
```

### 问题 2：图谱通道（GRAPH）如何实现？

**当前问题：**
- `RecallChannel.GRAPH` 已定义但未实现
- 其他 5 个通道都有实现

**实现方案：**

```python
class GraphRecallChannel:
    """图谱检索通道"""
    
    def __init__(self, knowledge_graph: KnowledgeGraphManager):
        self._kg = knowledge_graph
    
    def search(self, query: str, limit: int) -> List[Dict]:
        """基于图谱的检索"""
        results = []
        
        # 1. 提取查询中的实体
        entities = self._extract_entities(query)
        
        # 2. 在图谱中查找匹配节点
        nodes = []
        for entity in entities:
            found = self._kg.search_nodes(entity, node_type=None)
            nodes.extend(found)
        
        # 3. BFS/DFS 获取关联节点
        related = []
        for node in nodes[:5]:  # 限制种子节点数
            paths = self._kg.bfs(node.node_id, max_depth=2)
            related.extend(paths)
        
        # 4. 转换为记忆格式
        for node in related:
            if node.node_type == NodeType.MEMORY:
                results.append({
                    "memory_id": node.node_id,
                    "content": node.label,
                    "score": node.weight,
                    "source": "graph",
                    "metadata": node.properties,
                })
        
        # 5. 按权重排序
        results.sort(key=lambda x: x["score"], reverse=True)
        
        return results[:limit]
    
    def _extract_entities(self, query: str) -> List[str]:
        """从查询中提取实体"""
        # 简单实现：基于关键词
        # 复杂实现：使用NER模型
        entities = []
        
        # 人名
        import re
        name_pattern = r'[A-Z][a-z]+ [A-Z][a-z]+'
        entities.extend(re.findall(name_pattern, query))
        
        # 中文人名（简单规则）
        cn_name_pattern = r'[\u4e00-\u9fa5]{2,4}(?:老师|同学|先生|女士)'
        entities.extend(re.findall(cn_name_pattern, query))
        
        return entities
```

### 问题 3：实体提取如何实现？

**方案对比：**

| 方案 | 准确率 | 速度 | 成本 | 适用场景 |
|------|--------|------|------|----------|
| 规则提取 | 60% | 10ms | 0 | 简单实体 |
| LLM提取 | 95% | 500ms | 高 | 复杂实体 |
| 混合方案 | 85% | 100ms | 中 | 通用场景 |

**推荐：混合方案**

```python
class HybridEntityExtractor:
    """混合实体提取器"""
    
    def __init__(self, llm_client=None, confidence_threshold=0.7):
        self._llm_client = llm_client
        self._confidence_threshold = confidence_threshold
        self._rule_extractor = RuleEntityExtractor()
    
    def extract(self, text: str) -> List[Dict]:
        """提取实体"""
        # 1. 规则提取
        rule_results = self._rule_extractor.extract(text)
        
        # 2. 评估置信度
        high_confidence = [r for r in rule_results 
                          if r["confidence"] >= self._confidence_threshold]
        low_confidence = [r for r in rule_results 
                         if r["confidence"] < self._confidence_threshold]
        
        # 3. 低置信度结果用LLM验证
        if low_confidence and self._llm_client:
            llm_results = self._llm_verify(text, low_confidence)
            high_confidence.extend(llm_results)
        
        return high_confidence
    
    def _llm_verify(self, text: str, candidates: List[Dict]) -> List[Dict]:
        """使用LLM验证实体"""
        prompt = f"""
        文本：{text}
        候选实体：{[c['text'] for c in candidates]}
        
        请验证这些实体是否正确，并补充遗漏的实体。
        返回JSON格式：[{{"text": "实体", "type": "类型", "confidence": 0.9}}]
        """
        
        response = self._llm_client.generate(prompt)
        return self._parse_llm_response(response)

class RuleEntityExtractor:
    """规则实体提取器"""
    
    def extract(self, text: str) -> List[Dict]:
        """基于规则提取实体"""
        entities = []
        
        # 人名（中英文）
        entities.extend(self._extract_person_names(text))
        
        # 地名
        entities.extend(self._extract_locations(text))
        
        # 组织名
        entities.extend(self._extract_organizations(text))
        
        # 时间
        entities.extend(self._extract_times(text))
        
        return entities
    
    def _extract_person_names(self, text: str) -> List[Dict]:
        """提取人名"""
        import re
        results = []
        
        # 英文人名
        pattern = r'\b[A-Z][a-z]+ [A-Z][a-z]+\b'
        for match in re.finditer(pattern, text):
            results.append({
                "text": match.group(),
                "type": "PERSON",
                "confidence": 0.9,
                "start": match.start(),
                "end": match.end(),
            })
        
        # 中文人名（简单规则）
        cn_pattern = r'[\u4e00-\u9fa5]{2,4}(?:老师|同学|先生|女士)'
        for match in re.finditer(cn_pattern, text):
            results.append({
                "text": match.group(),
                "type": "PERSON",
                "confidence": 0.8,
                "start": match.start(),
                "end": match.end(),
            })
        
        return results
```

### 问题 4：如何处理记忆删除时的图谱清理？

**当前问题：**
- 记忆删除时，关联的图谱节点如何处理？

**方案对比：**

| 方案 | 优点 | 缺点 |
|------|------|------|
| 级联删除 | 保持一致性 | 可能丢失关联信息 |
| 保留孤立节点 | 保留信息 | 占用空间 |
| 标记为"已删除" | 平衡方案 | 需要额外字段 |

**推荐：标记为"已删除"**

```python
class MemoryKnowledgeBridge:
    def on_memory_deleted(self, memory_id: str):
        """记忆删除时清理图谱"""
        # 1. 获取记忆节点
        memory_node = self._kg.get_node(memory_id)
        if not memory_node:
            return
        
        # 2. 标记为已删除（不物理删除）
        memory_node.properties["deleted"] = True
        memory_node.properties["deleted_at"] = time.time()
        
        # 3. 降低关联边的权重
        edges = self._kg.get_edges(memory_id)
        for edge in edges:
            edge.weight *= 0.5  # 降低权重
        
        # 4. 定期清理（异步）
        self._schedule_cleanup()
    
    def _schedule_cleanup(self):
        """定期清理孤立节点"""
        # 每周清理一次
        # 删除标记为"已删除"超过30天的节点
        pass
```

### 问题 5：性能优化策略

**当前性能瓶颈：**

1. **实体提取**：规则提取 10ms，LLM提取 500ms
2. **图谱遍历**：BFS/DFS 时间复杂度 O(V+E)
3. **关联记忆检索**：多次数据库查询

**优化策略：**

```python
class MemoryKnowledgeBridge:
    def __init__(self, ...):
        # 1. 实体缓存
        self._entity_cache = TTLCache(maxsize=1000, ttl=3600)
        
        # 2. 图谱索引
        self._node_index = {}  # node_id -> node
        self._edge_index = defaultdict(list)  # source_id -> [edges]
        
        # 3. 批量查询
        self._batch_size = 100
    
    def enrich_memory_with_graph(self, memory):
        # 1. 检查缓存
        cache_key = hash(memory.content)
        if cache_key in self._entity_cache:
            entities = self._entity_cache[cache_key]
        else:
            entities = self._extractor.extract(memory.content)
            self._entity_cache[cache_key] = entities
        
        # 2. 批量查询图谱
        node_ids = self._batch_find_or_create_nodes(entities)
        
        # ...
    
    def _batch_find_or_create_nodes(self, entities):
        """批量查找或创建节点"""
        node_ids = []
        
        # 批量查询
        existing_nodes = self._kg.search_nodes_batch(
            [e["text"] for e in entities]
        )
        
        # 创建缺失节点
        for entity in entities:
            node = existing_nodes.get(entity["text"])
            if not node:
                node = self._kg.add_node(
                    label=entity["text"],
                    node_type=NodeType(entity["type"]),
                    properties=entity,
                )
            node_ids.append(node.node_id)
        
        return node_ids
```

**性能目标：**

| 操作 | 当前时间 | 目标时间 | 优化策略 |
|------|----------|----------|----------|
| 实体提取 | 100ms | 20ms | 规则优先 + 缓存 |
| 图谱查询 | 50ms | 10ms | 索引 + 批量 |
| 关联检索 | 80ms | 30ms | 缓存 + 限制深度 |
| **总计** | **230ms** | **60ms** | **-74%** |

## 最终设计决策

### 决策 1：实时构建 vs 异步构建
**选择：异步构建 + 定期同步**
- 理由：实体提取耗时，异步不阻塞主流程

### 决策 2：嵌入式 vs 独立服务
**选择：独立模块 + 事件驱动**
- 理由：知识图谱已是独立模块，通过事件解耦

### 决策 3：全量索引 vs 增量索引
**选择：增量索引 + 定期全量重建**
- 理由：增量快速，定期重建保证一致性

### 决策 4：实体提取方案
**选择：混合方案（规则 + LLM）**
- 理由：平衡准确率和性能

### 决策 5：记忆删除处理
**选择：标记为"已删除" + 定期清理**
- 理由：保留关联信息，平衡空间和一致性

## 实施清单

- [ ] 实现 `HybridEntityExtractor`
- [ ] 实现 `GraphRecallChannel`
- [ ] 实现 `MemoryKnowledgeBridge`
- [ ] 集成到 `NeurovaRecallEngine`
- [ ] 实现异步构建器
- [ ] 添加图谱索引优化
- [ ] 编写 20 个单元测试
- [ ] 编写 10 个集成测试
- [ ] 性能基准测试（< 100ms）
