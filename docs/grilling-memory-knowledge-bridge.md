# Grilling: 知识图谱集成接口 (MemoryKnowledgeBridge)

## 设计讨论框架

### 1. 接口设计问题

**问题1：知识图谱与记忆系统的集成点在哪里？**

当前状态：
- `KnowledgeGraphManager` (988行) — 完整的知识图谱实现，独立模块
- `NeurovaRecallEngine` — 6通道检索，其中 `GRAPH` 通道已定义但未实现
- `MemoryRecord` — 记忆数据模型，无图谱节点关联

**集成点分析：**

```
记忆写入 → 提取实体/关系 → 创建图谱节点/边
记忆检索 → 图谱遍历 → 补充关联记忆
知识更新 → 传播到关联记忆 → 更新图谱权重
```

**候选接口设计：**

```python
class MemoryKnowledgeBridge:
    """记忆系统与知识图谱的桥梁"""
    
    def __init__(self, 
                 knowledge_graph: KnowledgeGraphManager,
                 memory_manager: MemoryManager):
        self._kg = knowledge_graph
        self._mm = memory_manager
    
    def enrich_memory_with_graph(self, memory: MemoryRecord) -> MemoryRecord:
        """用图谱信息丰富记忆（添加实体、关系、关联）"""
    
    def retrieve_related_memories(self, 
                                   memory_id: str, 
                                   max_depth: int = 2) -> List[MemoryRecord]:
        """通过图谱关系检索关联记忆"""
    
    def build_graph_from_conversation(self, 
                                       conversation: List[Dict]) -> GraphStats:
        """从对话中自动构建图谱"""
    
    def query_graph_for_context(self, 
                                 query: str, 
                                 intent: QueryIntent) -> List[Dict]:
        """查询图谱获取上下文信息"""
```

**问题2：图谱通道（GRAPH）如何实现？**

当前 `NeurovaRecallEngine` 的 `RecallChannel.GRAPH` 已定义但未实现。

**实现方案：**

```python
class GraphRecallChannel:
    """图谱检索通道"""
    
    def __init__(self, knowledge_graph: KnowledgeGraphManager):
        self._kg = knowledge_graph
    
    def search(self, query: str, limit: int) -> List[Dict]:
        """基于图谱的检索"""
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
        return self._convert_to_memories(related)
```

**问题3：实体提取如何实现？**

从文本中提取实体（人名、地名、概念等）：

**方案A：基于 LLM 的实体提取**
- 优点：准确率高
- 缺点：耗时、成本高

**方案B：基于规则的实体提取**
- 优点：快速、低成本
- 缺点：覆盖率低

**方案C：混合方案**
- 先用规则提取，置信度低时用 LLM
- 建议采用方案C

### 2. 设计约束

**约束1：性能要求**
- 图谱检索 < 100ms（BFS/DFS 深度 ≤ 3）
- 实体提取 < 50ms（规则方案）
- 图谱更新 < 200ms（增量更新）

**约束2：数据一致性**
- 记忆删除时，关联的图谱节点如何处理？
  - 选项A：级联删除
  - 选项B：保留孤立节点
  - 选项C：标记为"记忆已删除"

**约束3：存储开销**
- 图谱存储在 `data/knowledge_graph/` 目录
- JSON 持久化，可能随记忆增长而膨胀
- 需要定期清理孤立节点

### 3. 架构决策

**决策1：实时构建 vs 异步构建？**
- **实时**：每次记忆写入时同步构建图谱
- **异步**：后台线程异步构建，定期同步

**建议**：使用 **异步构建**，因为：
1. 实体提取可能耗时
2. 图谱构建不是关键路径
3. 可以批量处理提高效率

**决策2：嵌入式 vs 独立服务？**
- **嵌入式**：直接集成到 MemoryManager
- **独立服务**：作为独立模块，通过事件通信

**建议**：使用 **独立模块 + 事件驱动**，因为：
1. 知识图谱已经是独立模块
2. 通过事件解耦，易于测试
3. 可以独立升级和替换

**决策3：全量索引 vs 增量索引？**
- **全量**：定期重建整个图谱
- **增量**：每次变化只更新受影响的部分

**建议**：使用 **增量索引 + 定期全量重建**，因为：
1. 增量更新快速
2. 定期全量重建保证一致性
3. 可以检测和修复孤立节点

### 4. 实现步骤

**步骤1：实现 GraphRecallChannel**
- 在 `neurova_recall.py` 中实现图谱检索通道
- 集成到 NeurovaRecallEngine 的 6 通道并行检索

**步骤2：实现 MemoryKnowledgeBridge**
- 创建 `neurova/cognitive_layers/knowledge_graph/bridge.py`
- 实现实体提取（规则 + LLM 混合）
- 实现记忆-图谱双向关联

**步骤3：实现异步构建器**
- 创建 `neurova/cognitive_layers/knowledge_graph/async_builder.py`
- 后台线程监听记忆写入事件
- 批量提取实体并构建图谱

**步骤4：集成到 ChatPipeline**
- 在记忆写入后触发图谱更新
- 在检索时启用图谱通道

### 5. 测试策略

**单元测试：**
- GraphRecallChannel 检索测试
- MemoryKnowledgeBridge 关联测试
- 实体提取准确率测试

**集成测试：**
- 完整的记忆写入 → 图谱构建 → 检索流程
- 图谱通道与 5 个现有通道的并行检索
- 性能基准测试

**测试用例：**
1. 从对话中提取实体并构建图谱
2. 通过图谱关系检索关联记忆
3. 图谱通道在 6 通道检索中的贡献
4. 异步构建不影响主流程性能
5. 孤立节点清理

### 6. 关键代码位置

- `neurova/cognitive_layers/knowledge_graph/manager.py` — KnowledgeGraphManager (988行)
- `neurova/cognitive_layers/memory_layer/neurova_recall.py` — RecallChannel.GRAPH
- `neurova/cognitive_layers/memory_layer/manager.py` — MemoryManager
- `neurova/cognitive_layers/memory_layer/models.py` — MemoryRecord

### 7. 待确认问题

1. 实体提取的置信度阈值如何设定？
2. 图谱节点的最大数量限制？
3. 是否需要图谱可视化功能？
4. 如何处理多语言实体提取？
