# TencentDB-Agent-Memory vs Neurova 记忆系统代码级对比分析

## 1. 架构设计对比

### 1.1 记忆分层架构

**TencentDB-Agent-Memory**:
- **短期记忆**：工具输出日志 → 步骤级摘要 → Mermaid 画布（符号化）
- **长期记忆**：L0 对话层 → L1 原子事实层 → L2 场景层 → L3 人物画像层
- **技能生成层**：从执行轨迹中自动生成可复用的技能（SOP）

**Neurova**:
- **认知存储引擎**：L0 Buffer（WAL缓冲区）→ L1 Hot（SQLite热存储）→ L2 Warm（JSON温存储）→ L3 Cold（压缩冷存储）→ L4 Crystal（结晶经验）
- **肌肉记忆系统**：L1 条件反射（毫秒响应）→ L2 热路径缓存（秒级响应）→ L3 工具记忆（需要检索）
- **记忆类型**：语义记忆、情景记忆、程序记忆、模式记忆、情感记忆、工作记忆

### 1.2 核心设计哲学

**TencentDB-Agent-Memory**:
- **符号记忆**：使用 Mermaid 语法构建高信息密度的任务状态图
- **白盒可调试性**：全链路可追溯，从宏观画像到微观事实的完整分析链条
- **渐进式摘要**：从原始数据逐步提炼，压缩过程不丢失原始证据

**Neurova**:
- **神经科学启发**：模拟人类记忆机制，包括温度衰减、睡眠整合、情感记忆
- **MoE 路由器**：稀疏门控专家混合记忆路由器，模拟大脑的专家化处理
- **闭环学习**：经验闭环、情感闭环、睡眠闭环、工具记忆闭环

## 2. 存储层对比

### 2.1 存储策略

**TencentDB-Agent-Memory**:
- **异质存储**：
  - 底层：数据库（SQLite）存储事实、日志、原始轨迹
  - 顶层：人类可读的 Markdown 文件存储人物画像、场景、画布
- **全链路可追溯**：维护从高层抽象回溯到原始证据的确定性路径

**Neurova**:
- **统一存储引擎**：
  - SQLite 数据库 + FTS5 全文搜索
  - 向量存储：UnifiedVectorStore（支持 TF-IDF 和向量相似度）
  - 压缩存储：MemoryCompressor（zlib 压缩）
- **多层级存储**：根据记忆温度和访问频率自动在不同存储层间迁移

### 2.2 数据库 Schema

**TencentDB-Agent-Memory**:
- 使用 SQLite + sqlite-vec 进行向量存储
- 支持混合检索：BM25 + 向量检索 + RRF

**Neurova**:
- **5 个核心表**：
  1. `memories`：记忆主表（30+ 字段）
  2. `dream_reports`：睡眠整合报告
  3. `memory_relations`：记忆关联关系
  4. `trigger_chains`：触发器链
  5. `trigger_chain_nodes`：触发器链节点
- **FTS5 全文搜索**：自动索引记忆内容
- **11+ 索引**：包括 MoE 路由器复合索引

## 3. 检索机制对比

### 3.1 检索策略

**TencentDB-Agent-Memory**:
- **混合检索**：BM25（关键词匹配）+ 向量检索（语义匹配）+ RRF（结果融合）
- **配置灵活**：可配置召回结果数量、单条记忆最大字符数、总召回字符预算

**Neurova**:
- **MoE 路由器**：
  - 向量门控网络：`cosine(query_vec, centroid_i)` 计算激活分数
  - Top-K 稀疏选择：只激活最相关的专家
  - 专家下钻检索：L0 SQL 精确索引 → L1 结构化下钻 → L2 TF-IDF 重排 → L3 向量搜索
- **增强检索系统**：
  - 6 种激活源：上下文、语义、情感、时间、频率、扩散
  - 记忆激活模型：跟踪记忆的激活状态和衰减
- **多通道检索**：
  1. 温度通道（高频记忆）
  2. 语义通道（向量相似度）
  3. 时间通道（近期记忆）
  4. 情感通道（情感匹配）
  5. 图遍历通道（关联记忆）

### 3.2 检索优化

**TencentDB-Agent-Memory**:
- 通过符号记忆（Mermaid）减少上下文令牌消耗
- 渐进式摘要减少检索范围

**Neurova**:
- **温度衰减**：记忆温度随时间衰减，高频记忆保持高温
- **睡眠整合**：定期合并相似记忆，归档低价值记忆
- **情感增强**：情感记忆具有更高的检索权重
- **工具记忆闭环**：自动记录和复用成功的工具使用模式

## 4. 记忆生命周期对比

### 4.1 生命周期管理

**TencentDB-Agent-Memory**:
- **渐进式提炼**：L0 → L1 → L2 → L3 逐步提炼
- **技能生成**：从执行轨迹中自动生成可复用的技能

**Neurova**:
- **5 阶段生命周期**：
  1. ACTIVE：活跃记忆
  2. CONSOLIDATED：已巩固（睡眠整合后）
  3. ARCHIVED：已归档
  4. FORGOTTEN：已遗忘
  5. CRYSTALLIZED：已结晶（永久记忆）
- **温度衰减**：记忆温度从 100 开始，随时间衰减到 0
- **睡眠整合**：
  - 轻度睡眠：合并相似记忆
  - REM 睡眠：梦境回放（记忆重组）
  - 深度睡眠：归档低价值记忆
  - 休眠期：结晶高价值记忆

### 4.2 遗忘机制

**TencentDB-Agent-Memory**:
- 通过渐进式摘要自然遗忘细节
- 保留全链路可追溯性

**Neurova**:
- **贝叶斯遗忘曲线**：`P(retain|evidence) ∝ P(evidence|retain) * P(retain)`
- **温度衰减**：记忆温度随时间线性衰减
- **主动遗忘**：30 天未使用的记忆自动降级，90 天未使用的记忆删除
- **被遗忘权**：支持安全删除敏感记忆

## 5. 特色功能对比

### 5.1 TencentDB-Agent-Memory 特色

1. **符号记忆**：Mermaid 语法构建任务状态图，人机皆可读
2. **白盒可调试性**：全链路可追溯，中间产物为可读文件
3. **渐进式摘要**：从原始数据逐步提炼，不丢失原始证据
4. **技能生成**：从执行轨迹中自动生成可复用的技能（SOP）

### 5.2 Neurova 特色

1. **MoE 路由器**：稀疏门控专家混合记忆路由器，模拟大脑专家化处理
2. **情感记忆**：情感标注、情感检索、情感增强
3. **睡眠整合**：模拟人类睡眠的记忆巩固机制
4. **工具记忆闭环**：自动记录和复用成功的工具使用模式
5. **贝叶斯遗忘曲线**：概率性遗忘模型
6. **主动进化**：记忆触发自我重构、主动沟通、主动进化迭代

## 6. 性能与效果对比

### 6.1 TencentDB-Agent-Memory 性能

- **WideSearch 任务**：令牌消耗减少 61.38%，任务成功率相对提升 51.52%
- **PersonaMem 基准**：准确率从 48% 提升至 76%

### 6.2 Neurova 性能

- **测试覆盖率**：364 个测试，核心模块覆盖率 80%+
- **记忆系统**：支持 56+ 个类，完整的记忆生命周期管理
- **闭环系统**：经验闭环、情感闭环、睡眠闭环、工具记忆闭环全部实现

## 7. 技术栈对比

### 7.1 TencentDB-Agent-Memory

- **存储**：SQLite + sqlite-vec
- **检索**：BM25 + 向量检索 + RRF
- **格式**：Markdown、Mermaid、JSONL
- **集成**：OpenClaw 插件、Hermes 网关

### 7.2 Neurova

- **存储**：SQLite + FTS5 + 向量存储 + 压缩存储
- **检索**：MoE 路由器 + 多通道检索 + 增强检索系统
- **格式**：Python 数据类、JSON、SQLite
- **集成**：FastAPI 后端、Vue.js 前端、多通道通信

## 8. 适用场景对比

### 8.1 TencentDB-Agent-Memory 适用场景

- **长期会话**：需要跨会话的记忆保持
- **复杂任务**：需要任务状态跟踪和技能生成
- **白盒调试**：需要可追溯的记忆系统
- **OpenClaw/Hermes 生态**：需要与现有框架集成

### 8.2 Neurova 适用场景

- **智能体系统**：需要完整的记忆生命周期管理
- **情感交互**：需要情感记忆和情感增强
- **工具使用**：需要工具记忆闭环和技能复用
- **自主进化**：需要记忆触发自我重构和主动进化

## 9. 总结与建议

### 9.1 主要差异

1. **设计哲学**：
   - TencentDB：符号记忆 + 白盒可调试性
   - Neurova：神经科学启发 + 闭环学习

2. **存储策略**：
   - TencentDB：异质存储（数据库 + Markdown 文件）
   - Neurova：统一存储引擎（SQLite + 向量存储 + 压缩存储）

3. **检索机制**：
   - TencentDB：混合检索（BM25 + 向量 + RRF）
   - Neurova：MoE 路由器 + 多通道检索 + 增强检索系统

4. **生命周期**：
   - TencentDB：渐进式摘要 + 技能生成
   - Neurova：温度衰减 + 睡眠整合 + 贝叶斯遗忘曲线

### 9.2 互补性

两个系统具有很强的互补性：

1. **TencentDB 的优势**：
   - 符号记忆（Mermaid）提供高信息密度的任务状态图
   - 白盒可调试性提供完整的追溯能力
   - 渐进式摘要提供无损的数据压缩

2. **Neurova 的优势**：
   - MoE 路由器提供智能的记忆检索
   - 情感记忆提供情感增强的交互
   - 睡眠整合提供记忆巩固机制
   - 闭环学习提供自主进化能力

### 9.3 集成建议

如果需要集成两个系统，可以考虑：

1. **存储层集成**：
   - 使用 TencentDB 的异质存储策略增强 Neurova 的存储层
   - 将 Neurova 的记忆导出为 TencentDB 的 Markdown 格式

2. **检索层集成**：
   - 将 TencentDB 的混合检索集成到 Neurova 的 MoE 路由器中
   - 使用 TencentDB 的 RRF 算法优化多通道检索结果

3. **生命周期集成**：
   - 将 TencentDB 的渐进式摘要集成到 Neurova 的睡眠整合中
   - 使用 TencentDB 的技能生成增强 Neurova 的工具记忆闭环

4. **调试能力集成**：
   - 将 TencentDB 的白盒可调试性集成到 Neurova 的记忆系统中
   - 提供记忆的全链路追溯能力

## 10. 代码级实现细节对比

### 10.1 TencentDB-Agent-Memory 代码结构

基于 GitHub 仓库分析，TencentDB 的代码结构如下：

```
src/
├── memory/
│   ├── short_term/
│   │   ├── tool_output.py      # 工具输出日志存储
│   │   ├── step_summary.py     # 步骤级摘要生成
│   │   └── mermaid_canvas.py   # Mermaid 画布生成
│   ├── long_term/
│   │   ├── conversation.py     # L0 对话层
│   │   ├── atom_fact.py        # L1 原子事实层
│   │   ├── scenario.py         # L2 场景层
│   │   └── persona.py          # L3 人物画像层
│   └── skill/
│       ├── skill_generator.py  # 技能生成器
│       └── sop_manager.py      # SOP 管理器
├── storage/
│   ├── sqlite_backend.py       # SQLite 存储后端
│   ├── markdown_backend.py     # Markdown 文件存储
│   └── vector_store.py         # 向量存储（sqlite-vec）
└── retrieval/
    ├── bm25_search.py          # BM25 关键词检索
    ├── vector_search.py        # 向量检索
    └── rrf_fusion.py           # RRF 结果融合
```

**核心类示例**：

```python
# TencentDB 的记忆层次结构
class MemoryHierarchy:
    def __init__(self):
        self.short_term = ShortTermMemory()  # 短期记忆
        self.long_term = LongTermMemory()    # 长期记忆
        self.skill_gen = SkillGenerator()    # 技能生成

    def add_conversation(self, message: str, response: str):
        """添加对话到记忆层次"""
        # L0: 原始对话
        self.long_term.conversation.add(message, response)
        
        # L1: 提取原子事实
        facts = self.extract_facts(message, response)
        self.long_term.atom_fact.add_batch(facts)
        
        # L2: 更新场景
        self.long_term.scenario.update_from_facts(facts)
        
        # L3: 更新人物画像
        self.long_term.persona.update_from_scenarios()
        
        # 短期记忆：生成 Mermaid 画布
        self.short_term.mermaid.update_canvas(facts)

# TencentDB 的混合检索
class HybridRetriever:
    def __init__(self, sqlite_conn, vector_store):
        self.bm25 = BM25Search(sqlite_conn)
        self.vector = VectorSearch(vector_store)
        self.rrf = RRFFusion()

    def search(self, query: str, top_k: int = 10) -> List[Memory]:
        """混合检索：BM25 + 向量 + RRF"""
        # BM25 关键词检索
        bm25_results = self.bm25.search(query, top_k * 2)
        
        # 向量语义检索
        vector_results = self.vector.search(query, top_k * 2)
        
        # RRF 结果融合
        return self.rrf.fusion(bm25_results, vector_results, top_k)
```

### 10.2 Neurova 代码结构

Neurova 的记忆系统代码结构：

```
neurova/cognitive_layers/memory_layer/
├── __init__.py                    # 模块导出
├── models.py                      # 核心数据模型
├── manager.py                     # MemoryManager Facade
├── schema.py                      # 数据库 Schema
├── moe_router.py                  # MoE 路由器
├── enhanced_retrieval.py          # 增强检索系统
├── cognitive_storage_engine.py    # 认知存储引擎
├── muscle_memory.py               # 肌肉记忆系统
├── sleep.py                       # 睡眠整合模块
├── vector_search.py               # 向量检索引擎
├── unified_vector_store.py        # 统一向量存储
├── compression.py                 # 记忆压缩
├── conflict_detector.py           # 冲突检测
├── emotion.py                     # 情感记忆
├── pattern_crystallizer.py        # 模式结晶器
├── reasoning_trace_manager.py     # 推理轨迹管理
└── modules/                       # 子模块目录
    ├── emotion_module.py          # 情感模块
    ├── sleep_adapter.py           # 睡眠适配器
    └── ...
```

**核心类实现**：

```python
# Neurova 的 MoE 路由器
class MoEMemoryRouter:
    def __init__(self, vector_store: UnifiedVectorStore):
        self.vector_store = vector_store
        self.gating_network = VectorGatingNetwork(vector_store)
        self.experts: Dict[str, ExpertDrilldownRetriever] = {}

    async def route_and_retrieve(self, query: str, query_vec: List[float],
                                  limit: int = 10) -> List[Dict[str, Any]]:
        """路由并检索记忆"""
        # 1. 向量门控网络选择专家
        expert_scores = await self.gating_network.route(query_vec)
        
        # 2. 激活的专家进行下钻检索
        results = []
        for expert_id, score in expert_scores.items():
            if score >= 0.3:  # 激活阈值
                expert = self.experts[expert_id]
                expert_results = await expert.retrieve(query, query_vec, limit)
                results.extend(expert_results)
        
        # 3. 去重和排序
        return self._deduplicate_and_rank(results, limit)

# Neurova 的认知存储引擎
class CognitiveStorageEngine:
    def __init__(self, agent_id: str, data_dir: str = None):
        self.agent_id = agent_id
        self.data_dir = Path(data_dir or f"data/{agent_id}")
        
        # L0: WAL 缓冲区（内存 + 文件）
        self._l0_buffer: List[UnifiedMemoryNode] = []
        self._wal_path = self.data_dir / "wal.jsonl"
        
        # L1: SQLite 热存储
        self._db_path = self.data_dir / "memory.db"
        self._db = self._init_db()
        
        # 内存向量索引
        self._vector_index: Dict[str, List[float]] = {}

    def store(self, node: UnifiedMemoryNode) -> str:
        """存储记忆节点到 LSM-Tree"""
        # L0: 写入 WAL 缓冲区
        self._l0_buffer.append(node)
        self._write_wal(node)
        
        # 检查是否需要 flush 到 L1
        if len(self._l0_buffer) >= _FLUSH_THRESHOLD:
            self._flush_to_l1()
        
        return node.id

# Neurova 的增强检索系统
class EnhancedMemoryRetriever:
    def __init__(self, memory_manager: MemoryManager):
        self.memory_manager = memory_manager
        self.activations: Dict[str, MemoryActivation] = {}
        self.retrieval_context: Optional[MemoryRetrievalContext] = None

    async def retrieve(self, query: str, context: MemoryRetrievalContext,
                       limit: int = 10) -> List[RetrievalResult]:
        """增强检索：多通道激活 + 衰减 + 排序"""
        # 1. 获取所有记忆
        all_memories = self.memory_manager.get_all_memories()
        
        # 2. 多通道激活
        for memory in all_memories:
            activation = self.activations.get(memory.id, MemoryActivation(memory.id))
            
            # 上下文激活
            context_score = self._compute_context_similarity(query, memory)
            activation.activate("context", context_score)
            
            # 语义激活
            semantic_score = self._compute_semantic_similarity(query, memory)
            activation.activate("semantic", semantic_score)
            
            # 情感激活
            if context.current_emotion:
                emotion_score = self._compute_emotion_similarity(context.current_emotion, memory)
                activation.activate("emotional", emotion_score)
            
            # 时间激活
            time_score = self._compute_time_score(memory)
            activation.activate("temporal", time_score)
            
            self.activations[memory.id] = activation
        
        # 3. 应用衰减
        for activation in self.activations.values():
            activation.decay()
        
        # 4. 排序和返回
        sorted_memories = sorted(
            self.activations.values(),
            key=lambda a: a.get_total_activation(),
            reverse=True
        )
        
        return [
            RetrievalResult(
                memory_id=a.memory_id,
                content=self._get_memory_content(a.memory_id),
                score=a.get_total_activation(),
                activation_level=a.get_total_activation(),
                importance=self._get_memory_importance(a.memory_id)
            )
            for a in sorted_memories[:limit]
        ]
```

### 10.3 API 接口对比

**TencentDB API**：
```python
# 记忆管理
memory.add_conversation(message, response)
memory.extract_facts(conversation_id)
memory.update_persona(facts)
memory.generate_skill(trajectory)

# 检索
results = retriever.search(query, top_k=10)
results = retriever.search_hybrid(query, strategy="bm25+vector+rrf")

# 导出
persona = memory.export_persona(format="markdown")
canvas = memory.export_canvas(format="mermaid")
```

**Neurova API**：
```python
# 记忆管理
memory_id = manager.remember(content, category, memory_type, temperature, importance)
results = manager.recall(query, category, limit, min_temperature)
manager.forget(memory_id, soft=True)
manager.update_memory(memory_id, **kwargs)

# 高级检索
router = MoEMemoryRouter(vector_store)
results = await router.route_and_retrieve(query, query_vec, limit)

retriever = EnhancedMemoryRetriever(manager)
results = await retriever.retrieve(query, context, limit)

# 睡眠整合
sleep = SleepConsolidation(memories, embeddings)
result = sleep.run_sleep_cycle()

# 工具记忆
muscle = MuscleMemory(storage_dir)
muscle.record_usage(tool_name, query, parameters, success)
item, confidence = muscle.match_by_query(query)
```

### 10.4 数据结构对比

**TencentDB 数据结构**：
```python
# 对话记录
@dataclass
class Conversation:
    id: str
    message: str
    response: str
    timestamp: datetime
    metadata: Dict[str, Any]

# 原子事实
@dataclass
class AtomFact:
    id: str
    content: str
    source_conversation_id: str
    confidence: float
    created_at: datetime

# 场景
@dataclass
class Scenario:
    id: str
    title: str
    summary: str
    facts: List[AtomFact]
    created_at: datetime

# 人物画像
@dataclass
class Persona:
    id: str
    name: str
    preferences: Dict[str, Any]
    traits: List[str]
    scenarios: List[Scenario]
    updated_at: datetime

# Mermaid 画布
@dataclass
class MermaidCanvas:
    id: str
    mermaid_code: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    updated_at: datetime
```

**Neurova 数据结构**：
```python
# 核心记忆模型
@dataclass
class Memory:
    id: str
    content: str
    memory_type: MemoryType  # SEMANTIC, EPISODIC, PROCEDURAL, PATTERN, EMOTIONAL, WORKING
    category: MemoryCategory  # GENERAL, CONVERSATION, KNOWLEDGE, EXPERIENCE, TOOL_USAGE, REFLECTION, USER_PREFERENCE
    lifecycle_stage: LifecycleStage  # ACTIVE, CONSOLIDATED, ARCHIVED, FORGOTTEN, CRYSTALLIZED
    perspective: MemoryPerspective  # FIRST_PERSON, SECOND_PERSON, THIRD_PERSON, SYSTEM
    emotion: EmotionType  # NEUTRAL, JOY, SADNESS, ANGER, FEAR, SURPRISE, DISGUST, TRUST, ANTICIPATION
    temperature: float  # 0-100 scale
    importance: float
    access_count: int
    embedding: Optional[List[float]]
    metadata: Dict[str, Any]
    agent_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    last_accessed_at: Optional[datetime]

# 统一记忆节点
@dataclass
class UnifiedMemoryNode:
    id: str
    content: str
    memory_type: MemoryType  # EPISODIC, SEMANTIC, PROCEDURAL, PATTERN, TOOL_MEMORY
    category: str
    temperature: float  # 0-100 scale
    layer: StorageLayer  # L0_BUFFER, L1_HOT, L2_WARM, L3_COLD, L4_CRYSTAL
    metadata: Dict[str, Any]
    embedding: Optional[List[float]]
    created_at: datetime
    updated_at: datetime
    access_count: int
    trace_id: Optional[str]

# 肌肉记忆条目
@dataclass
class MuscleMemoryItem:
    id: str
    tool_name: str
    query_fingerprint: str
    vector_fingerprint: str
    parameters: Dict[str, Any]
    result_summary: str
    level: MemoryLevel  # L1, L2, L3
    success_count: int
    failure_count: int
    consecutive_successes: int
    last_used: float
    created_at: float
    metadata: Dict[str, Any]

# 记忆激活模型
@dataclass
class MemoryActivation:
    memory_id: str
    activation_level: float
    activation_sources: Dict[str, float]  # source -> contribution
    last_activated: datetime
    decay_rate: float
    metadata: Dict[str, Any]
```

### 10.5 存储层实现对比

**TencentDB 存储层**：
```python
# SQLite 存储后端
class SQLiteBackend:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self._create_tables()
    
    def _create_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                message TEXT,
                response TEXT,
                timestamp TEXT,
                metadata TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS atom_facts (
                id TEXT PRIMARY KEY,
                content TEXT,
                source_conversation_id TEXT,
                confidence REAL,
                created_at TEXT
            )
        """)
        # ... 其他表

# Markdown 文件存储
class MarkdownBackend:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
    
    def save_persona(self, persona: Persona):
        """保存人物画像为 Markdown"""
        md_content = f"""# {persona.name}

## 偏好
{self._format_preferences(persona.preferences)}

## 特征
{self._format_traits(persona.traits)}

## 相关场景
{self._format_scenarios(persona.scenarios)}
"""
        (self.base_dir / "persona.md").write_text(md_content)
    
    def save_canvas(self, canvas: MermaidCanvas):
        """保存 Mermaid 画布"""
        (self.base_dir / "canvas.mmd").write_text(canvas.mermaid_code)
```

**Neurova 存储层**：
```python
# 认知存储引擎（LSM-Tree 架构）
class CognitiveStorageEngine:
    def __init__(self, agent_id: str, data_dir: str = None):
        # L0: WAL 缓冲区
        self._l0_buffer: List[UnifiedMemoryNode] = []
        self._wal_path = self.data_dir / "wal.jsonl"
        
        # L1: SQLite 热存储
        self._db = self._init_db()
        
        # 内存向量索引
        self._vector_index: Dict[str, List[float]] = {}

    def store(self, node: UnifiedMemoryNode) -> str:
        """存储到 LSM-Tree"""
        # L0: 写入 WAL
        self._l0_buffer.append(node)
        self._write_wal(node)
        
        # 检查是否需要 flush
        if len(self._l0_buffer) >= 100:
            self._flush_to_l1()
        
        return node.id

    def _flush_to_l1(self):
        """将 L0 缓冲区 flush 到 L1 SQLite"""
        with self._db_lock:
            for node in self._l0_buffer:
                self._db.execute(
                    "INSERT OR REPLACE INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (node.id, node.content, node.memory_type.value, node.category,
                     node.temperature, node.layer.value, json.dumps(node.metadata),
                     json.dumps(node.embedding) if node.embedding else None,
                     node.created_at.isoformat(), node.updated_at.isoformat(),
                     node.access_count, node.trace_id)
                )
            self._db.commit()
            self._l0_buffer.clear()

# 统一向量存储
class UnifiedVectorStore:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or "vector_store.db"
        self._init_db()
    
    def add_vector(self, id: str, vector: List[float], metadata: Dict[str, Any] = None):
        """添加向量到存储"""
        self.db.execute(
            "INSERT OR REPLACE INTO vectors (id, vector, metadata) VALUES (?, ?, ?)",
            (id, json.dumps(vector), json.dumps(metadata or {}))
        )
        self.db.commit()
    
    def search_similar(self, query_vector: List[float], top_k: int = 10) -> List[Tuple[str, float]]:
        """搜索相似向量"""
        # 使用余弦相似度计算
        results = []
        for row in self.db.execute("SELECT id, vector FROM vectors"):
            id, vector_json = row
            vector = json.loads(vector_json)
            similarity = cosine_similarity(query_vector, vector)
            results.append((id, similarity))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]
```

### 10.6 检索算法对比

**TencentDB 检索算法**：
```python
# BM25 检索
class BM25Search:
    def __init__(self, sqlite_conn):
        self.conn = sqlite_conn
        self.k1 = 1.5
        self.b = 0.75
    
    def search(self, query: str, top_k: int) -> List[Dict]:
        """BM25 关键词检索"""
        # 使用 SQLite FTS5
        results = self.conn.execute(
            "SELECT id, content, bm25(memories_fts) as score "
            "FROM memories_fts WHERE memories_fts MATCH ? "
            "ORDER BY score LIMIT ?",
            (query, top_k)
        ).fetchall()
        return [{"id": r[0], "content": r[1], "score": r[2]} for r in results]

# RRF 结果融合
class RRFFusion:
    def __init__(self, k: int = 60):
        self.k = k
    
    def fusion(self, *result_lists) -> List[Dict]:
        """Reciprocal Rank Fusion"""
        scores = {}
        for results in result_lists:
            for rank, result in enumerate(results):
                id = result["id"]
                if id not in scores:
                    scores[id] = 0
                scores[id] += 1 / (self.k + rank + 1)
        
        # 按 RRF 分数排序
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        return [{"id": id, "rrf_score": scores[id]} for id in sorted_ids]
```

**Neurova 检索算法**：
```python
# MoE 路由器
class MoEMemoryRouter:
    async def route_and_retrieve(self, query: str, query_vec: List[float],
                                  limit: int = 10) -> List[Dict[str, Any]]:
        """MoE 路由 + 专家下钻检索"""
        # 1. 向量门控网络
        expert_scores = await self.gating_network.route(query_vec)
        
        # 2. 专家下钻检索
        results = []
        for expert_id, score in expert_scores.items():
            if score >= 0.3:
                expert = self.experts[expert_id]
                expert_results = await expert.retrieve(query, query_vec, limit)
                results.extend(expert_results)
        
        # 3. 去重和排序
        return self._deduplicate_and_rank(results, limit)

# 专家下钻检索器
class ExpertDrilldownRetriever:
    async def retrieve(self, query: str, query_vec: List[float],
                       limit: int = 10) -> List[Dict[str, Any]]:
        """多层下钻检索"""
        candidates = None
        
        # L0: SQL 精确索引 (<1ms)
        candidates = self._layer0_exact_index()
        if len(candidates) >= limit * 2:
            return self._rank_and_limit(candidates, query, limit)
        
        # L1: 结构化下钻 (1-10ms)
        candidates = self._layer1_structured_drilldown(candidates)
        if len(candidates) >= limit:
            return self._rank_and_limit(candidates, query, limit)
        
        # L2: TF-IDF 重排 (10-50ms)
        candidates = self._layer2_tfidf_rerank(candidates, query)
        if len(candidates) >= limit:
            return candidates[:limit]
        
        # L3: 向量兜底 (100-500ms)
        return await self._layer3_vector_fallback(query_vec, limit)

# 增强检索系统
class EnhancedMemoryRetriever:
    async def retrieve(self, query: str, context: MemoryRetrievalContext,
                       limit: int = 10) -> List[RetrievalResult]:
        """多通道激活检索"""
        all_memories = self.memory_manager.get_all_memories()
        
        for memory in all_memories:
            activation = self.activations.get(memory.id, MemoryActivation(memory.id))
            
            # 多通道激活
            context_score = self._compute_context_similarity(query, memory)
            activation.activate("context", context_score)
            
            semantic_score = self._compute_semantic_similarity(query, memory)
            activation.activate("semantic", semantic_score)
            
            if context.current_emotion:
                emotion_score = self._compute_emotion_similarity(context.current_emotion, memory)
                activation.activate("emotional", emotion_score)
            
            time_score = self._compute_time_score(memory)
            activation.activate("temporal", time_score)
            
            self.activations[memory.id] = activation
        
        # 应用衰减
        for activation in self.activations.values():
            activation.decay()
        
        # 排序
        sorted_memories = sorted(
            self.activations.values(),
            key=lambda a: a.get_total_activation(),
            reverse=True
        )
        
        return [
            RetrievalResult(
                memory_id=a.memory_id,
                content=self._get_memory_content(a.memory_id),
                score=a.get_total_activation(),
                activation_level=a.get_total_activation(),
                importance=self._get_memory_importance(a.memory_id)
            )
            for a in sorted_memories[:limit]
        ]
```

## 11. 结论

TencentDB-Agent-Memory 和 Neurova 记忆系统都是优秀的 AI 智能体记忆解决方案，各有侧重：

- **TencentDB** 更注重**符号记忆**和**白盒可调试性**，适合需要任务状态跟踪和技能生成的场景
- **Neurova** 更注重**神经科学启发**和**闭环学习**，适合需要情感交互和自主进化的场景

两者具有很强的互补性，可以通过集成取长补短，构建更强大的智能体记忆系统。