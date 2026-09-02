# 分层认知图谱存储架构设计文档

**文档版本**: v1.0  
**创建日期**: 2026-06-04  
**状态**: 深度设计  
**基于**: unified-storage-format-discussion.md 深度讨论结果

---

## 1. 背景与动机

### 1.1 当前架构的根本矛盾

在对 Neurova 现有记忆系统进行全面代码审计后，发现三个架构层面的根本矛盾：

**矛盾 1：两套存储引擎的数据模型不兼容**

```
传统记忆 (SQLite):     content → 12个分表 → 结构化字段
NeurovaHebb (JSON):   content → neurova_hebbs.json → 单一文件
向量索引 (内存):       embedding → UnifiedVectorStore → 三合一索引
```

| 属性 | 传统记忆 | NeurovaHebb |
|------|----------|-------------|
| 温度刻度 | 0-100 | 0-1 |
| 存储介质 | SQLite | JSON 文件 |
| ID 命名 | 自增整数 | `hebb_{uuid}` |
| 生命周期 | TemperatureEngine 驱动 | 内置 decay_rate |

**矛盾 2：批量写入与向量索引更新的时序问题**

EventDrivenMemoryWriter 做批量写入 SQLite，但 UnifiedVectorStore 的向量索引是内存态的。写入延迟会导致检索数据不一致。

**矛盾 3：推理结晶化过度依赖 LLM**

每次结晶化 = 一次 LLM 调用 = 成本 + 延迟，高频使用时成本不可接受。

### 1.2 痛点清单

| 痛点 | 根因 | 影响 |
|------|------|------|
| SQLite写入压力 | 每次推理都写入，无批量优化 | 性能下降，响应延迟 |
| 存储体积爆炸 | 推理数据量大，无生命周期管理 | 存储成本高，备份困难 |
| 检索方式不统一 | MOE只检索传统记忆，NeurovaHebb独立检索 | 遗漏重要记忆 |
| 溯源困难 | 推理过程无关联ID | 无法追踪推理来源 |
| 无法积累经验 | 推理过程记录后未被复用 | 重复推理，浪费资源 |

---

## 2. 核心理念：从"存储系统"到"认知图谱"

### 2.1 科学基础

1. **编码特异性原理**（Tulving, 1973）：记忆的检索效果取决于编码时的上下文
2. **扩散激活网络**（Collins & Loftus, 1975）：语义记忆以网络形式组织，激活沿连接扩散
3. **Hebb 学习规则**：一起激活的神经元连接增强

### 2.2 关键洞察

当前问题的本质不是"存储格式不统一"，而是**缺少记忆之间的语义连接**。

人类记忆越用越聪明，因为：模式识别、因果推理、类比迁移。

```
┌──────────────────────────────────────────────────────────────┐
│                  认知图谱 (Cognitive Graph)                    │
│                                                              │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐     │
│  │ 记忆节点 │──→│ 模式节点 │──→│ 方法节点 │──→│ 经验节点 │     │
│  │ (Memory) │   │(Pattern)│   │(Method) │   │(Exper.) │     │
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘     │
│       ↑              ↑              ↑              ↑         │
│   每次对话       自动聚类       成功推理      反复验证        │
│   产生记忆       提取模式       提取方法       升级经验        │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 架构设计

### 3.1 统一记忆节点模型

```python
@dataclass
class UnifiedMemoryNode:
    """统一记忆节点 —— 所有记忆的唯一数据模型"""

    # 标识
    id: str                                    # 全局唯一 ID
    type: str                                  # episodic|semantic|procedural|pattern|method

    # 内容
    content: str                               # 记忆内容
    summary: str = ""                          # 一句话摘要
    embedding: Optional[List[float]] = None    # 向量嵌入

    # 温度（统一 0-1 刻度）
    temperature: float = 1.0                   # [0, 1]
    decay_rate: float = 0.01                   # 每日衰减率
    access_count: int = 0
    last_accessed: str = ""

    # 认知属性
    importance: float = 0.5                    # [0, 1]
    confidence: float = 0.5                    # [0, 1]
    emotional_valence: float = 0.0             # [-1, 1]

    # 图谱关系
    parent_ids: List[str] = field(default_factory=list)
    child_ids: List[str] = field(default_factory=list)
    related_ids: List[str] = field(default_factory=list)

    # 溯源
    trace_id: Optional[str] = None
    source_type: str = "user_input"
    source_detail: Dict = field(default_factory=dict)

    # 生命周期
    stage: str = "hot"                         # hot|warm|cold|crystallized
    created_at: str = ""
    updated_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**记忆类型定义：**

| type | 含义 | 示例 |
|------|------|------|
| `episodic` | 情景记忆 | "用户在 2026-06-04 问了关于存储架构的问题" |
| `semantic` | 语义记忆（事实） | "SQLite 支持事务和并发安全" |
| `procedural` | 程序性记忆（怎么做） | "使用 FAISS 进行向量检索" |
| `pattern` | 模式记忆（规律） | "系统设计类问题通常需要 search→analyze→implement" |
| `method` | 方法论记忆（结晶化） | "系统设计问题解决框架" |

### 3.2 LSM-Tree 式分层存储

```
┌─────────────────────────────────────────────────────────────┐
│                    分层存储架构                                │
├─────────────────────────────────────────────────────────────┤
│  L0: 写入缓冲层 (WAL + 内存表)                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  write_buffer: 最近 50-100 条记忆                    │    │
│  │  特点: 极速读写，buffer满或定时触发 compaction       │    │
│  └─────────────────────────────────────────────────────┘    │
│                         ↓ compaction                        │
│  L1: 热数据层 (SQLite + 内存向量索引)                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  温度 ≥ 0.3 且 7天内访问                             │    │
│  │  特点: 全功能，支持向量检索 + 结构化查询              │    │
│  └─────────────────────────────────────────────────────┘    │
│                         ↓ migration                         │
│  L2: 温数据层 (SQLite 降级)                                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  0.1 ≤ 温度 < 0.3 且 30天内访问                      │    │
│  │  特点: 只支持文本检索，不维护向量索引                  │    │
│  └─────────────────────────────────────────────────────┘    │
│                         ↓ archive                           │
│  L3: 冷数据层 (JSON 归档)                                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  温度 < 0.1 或 90天未访问                             │    │
│  │  特点: 最低成本，仅在睡眠整理时扫描                   │    │
│  └─────────────────────────────────────────────────────┘    │
│                         ↓ crystallize                       │
│  L4: 结晶层 (永久知识库)                                      │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  高频访问 + 高置信度的模式/方法论                     │    │
│  │  特点: 不参与温度衰减，永久保存                       │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

**各层规格：**

| 层级 | 介质 | 写入频率 | 读取延迟 | 数据量 | 数据 |
|------|------|----------|----------|--------|------|
| L0 Buffer | 内存 + WAL | 每次推理 | <1ms | ~100条 | 最近记忆 |
| L1 Hot | SQLite + 向量索引 | 每 100 条 | <5ms | ~10K条 | 活跃记忆 |
| L2 Warm | SQLite (降级) | 每天整理 | <20ms | ~50K条 | 温记忆 |
| L3 Cold | JSON 归档 | 每周归档 | >100ms | ~100K条 | 冷记忆 |
| L4 Crystal | SQLite (永久) | 结晶化时 | <5ms | ~1K条 | 永久知识 |

**核心实现：**

```python
class CognitiveStorageEngine:
    """认知存储引擎 —— LSM-Tree 式分层存储"""

    def __init__(self, sqlite_path: str, archive_dir: str):
        self.write_buffer = []
        self.sqlite = SQLiteStore(sqlite_path)
        self.archive_dir = archive_dir
        self.vector_store = UnifiedVectorStore()
        self.buffer_limit = 100
        self._lock = threading.RLock()

    def write(self, node: UnifiedMemoryNode) -> str:
        """写入记忆 —— 先写 buffer，满后 compact"""
        with self._lock:
            self._append_wal(node)                  # WAL 保障
            self.write_buffer.append(node)           # 内存 buffer
            if node.embedding:                       # 实时更新向量索引
                self.vector_store.add_vector(
                    node.id, node.embedding, node.to_dict()
                )
            if len(self.write_buffer) >= self.buffer_limit:
                self._compact()
            return node.id

    def _compact(self):
        """L0 → L1 批量压缩"""
        if not self.write_buffer:
            return
        self.sqlite.batch_insert(self.write_buffer)
        self.write_buffer.clear()
        self._truncate_wal()

    def search(self, query: str, limit: int = 10) -> List[UnifiedMemoryNode]:
        """统一检索 —— buffer + L1 + L2 并行"""
        results = []
        results.extend(self._search_buffer(query, limit))
        results.extend(self.vector_store.search(query, limit=limit))
        if len(results) < limit:
            results.extend(
                self.sqlite.tfidf_search(query, limit=limit - len(results))
            )
        return self._merge_and_rank(results, limit)
```

**WAL（Write-Ahead Logging）：**

```python
class WALManager:
    """预写日志管理器 —— 崩溃恢复保障"""

    def __init__(self, wal_path: str):
        self.wal_path = Path(wal_path)

    def append(self, node: UnifiedMemoryNode):
        record = {
            "op": "insert",
            "data": node.to_dict(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(self.wal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def replay(self) -> List[UnifiedMemoryNode]:
        """重放 WAL —— 崩溃恢复时调用"""
        nodes = []
        if not self.wal_path.exists():
            return nodes
        with open(self.wal_path, "r", encoding="utf-8") as f:
            for line in f:
                record = json.loads(line.strip())
                if record["op"] == "insert":
                    nodes.append(UnifiedMemoryNode.from_dict(record["data"]))
        return nodes

    def truncate(self):
        """清空 WAL —— compaction 成功后调用"""
        if self.wal_path.exists():
            self.wal_path.unlink()
```

### 3.3 温度驱动的自动迁移

```python
def classify_stage(node: UnifiedMemoryNode) -> str:
    """根据温度和访问模式自动分类"""
    t = node.temperature
    age_days = node.age_days()

    # 结晶化条件（永久保存）
    if node.type in ("pattern", "method") and node.confidence >= 0.8:
        return "crystallized"

    if t >= 0.3 and age_days <= 7:
        return "hot"
    if t >= 0.1 and age_days <= 30:
        return "warm"
    return "cold"
```

```python
class MigrationExecutor:
    """层级迁移执行器"""

    def run_migration(self):
        # L1 → L2
        for mem in self.storage.sqlite.query_by_stage("hot"):
            if classify_stage(mem) == "warm":
                self.storage.sqlite.update_stage(mem.id, "warm")
                self.storage.vector_store.remove_vector(mem.id)

        # L2 → L3
        cold_batch = [
            m for m in self.storage.sqlite.query_by_stage("warm")
            if classify_stage(m) == "cold"
        ]
        if cold_batch:
            self.storage.archive_batch(cold_batch)
            self.storage.sqlite.delete_batch([m.id for m in cold_batch])

        # 结晶化
        for pat in self.storage.sqlite.query_by_type("pattern"):
            if pat.confidence >= 0.8 and pat.access_count >= 3:
                self.storage.sqlite.update_stage(pat.id, "crystallized")
```

**体积控制：**

| 层级 | 数据量 | 单条大小 | 总体积 |
|------|--------|----------|--------|
| L0 Buffer | ~100 | 2KB | 0.2MB |
| L1 Hot | ~10K | 2KB | 20MB |
| L2 Warm | ~50K | 1KB | 50MB |
| L3 Cold | ~100K | 0.5KB | 50MB |
| L4 Crystal | ~1K | 3KB | 3MB |
| **总计** | **~161K** | - | **~123MB** |

---

## 4. 经验结晶化系统

### 4.1 设计理念

基于 Hebb 学习规则 + 贝叶斯推断：

- 成功推理强化模式连接
- 失败推理削弱模式连接
- 置信度通过贝叶斯更新

**关键改进**：大部分时间只观察推理结果（零 LLM 成本），仅在模式被反复验证后（>=3 次成功）才调用 LLM 生成方法论（一次性成本）。

### 4.2 PatternCrystallizer 实现

```python
class PatternCrystallizer:
    """模式结晶化器 —— 从成功推理中自动提取可复用模式"""

    def __init__(self, storage, vector_store, embed_fn, llm_fn=None):
        self.storage = storage
        self.vector_store = vector_store
        self._embed = embed_fn
        self._llm_fn = llm_fn
        self._pattern_cache = {}

    def observe_reasoning(self, trace: ReasoningTrace):
        """观察推理轨迹，判断是否结晶化"""
        if trace.confidence < 0.7:
            return

        fingerprint = self._compute_fingerprint(trace)
        existing = self._find_similar_pattern(fingerprint)

        if existing:
            self._reinforce_pattern(existing, trace)  # Hebb 学习
        else:
            self._create_pattern(fingerprint, trace)

    def _compute_fingerprint(self, trace: ReasoningTrace) -> Dict:
        """计算推理指纹 —— 纯算法，不依赖 LLM"""
        return {
            "query_keywords": self._extract_keywords(trace.query),
            "tool_chain": [s.tool_used for s in trace.reasoning_chain if s.tool_used],
            "memory_source_types": list(set(s.memory_type for s in trace.sources)),
            "reasoning_depth": len(trace.reasoning_chain),
            "result_features": self._extract_result_features(trace.result),
        }

    def _reinforce_pattern(self, pattern: Dict, trace: ReasoningTrace):
        """强化模式 —— 贝叶斯置信度更新"""
        pattern["success_count"] += 1
        pattern["total_count"] += 1

        prior = pattern["confidence"]
        n = pattern["total_count"]
        pattern["confidence"] = (prior * n + trace.confidence) / (n + 1)

        # 3 次成功 + 置信度 >= 0.8 → 结晶化
        if pattern["success_count"] >= 3 and pattern["confidence"] >= 0.8:
            self._crystallize_to_method(pattern)

    def _crystallize_to_method(self, pattern: Dict):
        """结晶化为方法论 —— 仅在此处调用 LLM（一次性成本）"""
        examples = [self.storage.get_trace(tid) for tid in pattern["example_traces"][:5]]
        methodology = self._llm_generate_methodology(pattern, examples)

        self.storage.write(UnifiedMemoryNode(
            id=f"method_{pattern['id']}",
            type="method",
            content=methodology,
            temperature=1.0,
            confidence=pattern["confidence"],
            metadata={"pattern_id": pattern["id"], "fingerprint": pattern["fingerprint"]},
        ))

    def retrieve_methodology(self, query: str) -> Optional[str]:
        """检索已有方法论 —— 类似问题直接调用"""
        query_embedding = self._embed(query)
        methods = self.storage.search_layer(
            layer="crystallized", type_filter="method",
            query_embedding=query_embedding, threshold=0.7, limit=1,
        )
        if methods and methods[0].confidence >= 0.8:
            return methods[0].content
        return None
```

### 4.3 结晶化流程示例

```
第 1 次: 用户问 "如何实现记忆系统" → 推理 5 步 → 成功
第 2 次: 用户问 "如何设计缓存系统" → 推理 4 步 → 成功 (相似模式)
第 3 次: 用户问 "如何优化数据库性能" → 推理 3 步 → 成功 (模式强化)
         ↓
模式识别: "系统设计类问题" → 工具链 [search, read, analyze, implement]
         ↓
结晶化: 生成方法论 "系统设计问题解决框架"
         ↓
第 4 次: 用户问 "如何设计消息队列" → 直接调用方法论 → 1 步解决
```

### 4.4 成本对比

| 方案 | 每次推理成本 | 结晶化成本 | 总成本（100次推理） |
|------|-------------|-----------|-------------------|
| 原方案（每次LLM） | 1 LLM调用 | 0 | 100 LLM调用 |
| 新方案（模式聚类） | 0 LLM调用 | 1 LLM调用（3次成功后） | ~3 LLM调用 |

**成本降低：~97%**

---

## 5. 推理溯源系统

### 5.1 数据模型

```python
@dataclass
class ReasoningTrace:
    """推理轨迹"""
    trace_id: str
    query: str
    query_embedding: List[float]
    steps: List[ReasoningStep]
    memory_sources: List[str]     # 引用的记忆 ID
    result_summary: str
    confidence: float
    tool_chain: List[str]
    created_at: str

    def get_all_sources(self, storage) -> List[UnifiedMemoryNode]:
        """获取所有引用的记忆"""
        return [storage.get(mid) for mid in self.memory_sources]

    def get_reasoning_path(self) -> str:
        """生成可读的推理路径"""
        return " → ".join(f"[Step {i+1}] {s.thought[:50]}..." for i, s in enumerate(self.steps))


@dataclass
class ReasoningStep:
    step_id: str
    thought: str
    tool_used: Optional[str]
    memory_accessed: List[str]
    intermediate_result: str
    confidence: float
```

### 5.2 ReasoningTraceManager

```python
class ReasoningTraceManager:
    """推理轨迹管理器"""

    def __init__(self, storage: CognitiveStorageEngine):
        self.storage = storage
        self._active_traces: Dict[str, ReasoningTrace] = {}

    def start_trace(self, query: str) -> str:
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        trace = ReasoningTrace(
            trace_id=trace_id, query=query,
            query_embedding=self.storage.vector_store.encode(query),
            steps=[], memory_sources=[], result_summary="",
            confidence=0.0, tool_chain=[],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._active_traces[trace_id] = trace
        return trace_id

    def record_step(self, trace_id: str, step: ReasoningStep):
        trace = self._active_traces.get(trace_id)
        if trace:
            trace.steps.append(step)

    def finish_trace(self, trace_id: str, result_summary: str, confidence: float):
        trace = self._active_traces.pop(trace_id, None)
        if trace:
            trace.result_summary = result_summary
            trace.confidence = confidence
            self.storage.sqlite.store_trace(trace)

    def find_similar_traces(self, query: str, limit: int = 5) -> List[ReasoningTrace]:
        query_embedding = self.storage.vector_store.encode(query)
        return self.storage.sqlite.search_traces(
            query_embedding=query_embedding, threshold=0.6, limit=limit,
        )
```

### 5.3 溯源能力矩阵

| 查询类型 | 能力 | 示例 |
|----------|------|------|
| 记忆 → 轨迹 | 查找记忆的产生过程 | "这条记忆是怎么来的？" |
| 轨迹 → 记忆 | 查找推理使用了哪些记忆 | "这次推理参考了哪些知识？" |
| 查询 → 轨迹 | 查找相似问题的历史推理 | "之前有没有类似的问题？" |
| 轨迹 → 方法论 | 查找结晶化的方法论 | "这类问题有什么通用解法？" |

---

## 6. 统一检索架构

### 6.1 检索层级

```
统一检索入口: CognitiveStorageEngine.search()
    │
    ├── L0 Buffer 搜索（精确匹配 + 最近访问）
    │
    ├── MOE Router（向量路由 + 专家下钻）
    │   ├── 专家 1: 技术类记忆
    │   ├── 专家 2: 个人偏好
    │   └── 专家 3: 任务经验
    │
    ├── RecallEngine（多通道融合）
    │   ├── 温度通道
    │   ├── 文本通道
    │   ├── 类别通道
    │   ├── 图谱通道
    │   └── 情感通道
    │
    └── 结晶层检索（方法论匹配）
```

### 6.2 UnifiedRetriever

```python
class UnifiedRetriever:
    """统一检索器 —— 整合所有检索策略"""

    def __init__(self, storage, moe_router, recall_engine, crystallizer):
        self.storage = storage
        self.moe_router = moe_router
        self.recall_engine = recall_engine
        self.crystallizer = crystallizer

    async def retrieve(self, query: str, limit: int = 10) -> RetrievalResult:
        # 0. 优先检索方法论
        methodology = self.crystallizer.retrieve_methodology(query)

        # 1. 并行检索
        tasks = [
            self.storage.search(query, limit=limit),
            self.moe_router.retrieve(query, limit=limit),
            self.recall_engine.recall_async(query, limit=limit),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 2. 合并 + 去重 + 排序
        all_memories = [m for r in results if isinstance(r, list) for m in r]
        unique = self._deduplicate(all_memories)
        ranked = self._fusion_rank(unique, query)

        return RetrievalResult(
            memories=ranked[:limit],
            methodology=methodology,
            sources=self._identify_sources(ranked[:limit]),
        )
```

---

## 7. 记忆注入上下文系统

```python
class MemoryAwareContextBuilder:
    """记忆感知的上下文构建器"""

    def __init__(self, retriever: UnifiedRetriever, context_pool: ContextPool):
        self.retriever = retriever
        self.context_pool = context_pool

    async def build_context(self, query: str, base_context: List[Dict]) -> List[Dict]:
        # 1. 统一检索
        result = await self.retriever.retrieve(query)

        # 2. 构建记忆上下文
        memory_section = self._build_memory_section(result.memories, result.methodology)

        # 3. 注入到系统消息
        for msg in base_context:
            if msg.get("role") == "system":
                msg["content"] += f"\n\n{memory_section}"
                break

        return base_context

    def _build_memory_section(self, memories, methodology) -> str:
        sections = []
        if methodology:
            sections.append(f"## 已有方法论\n{methodology}")
        if memories:
            sections.append("## 相关记忆")
            for i, mem in enumerate(memories, 1):
                sections.append(f"{i}. [{mem.type}] {mem.content} (置信度: {mem.confidence:.2f})")
        return "\n\n".join(sections)
```

---

## 8. 与现有架构的兼容性

### 8.1 渐进式迁移策略

```python
class Agent:
    def __init__(self):
        # 旧系统（保持不变）
        self.memory_manager = MemoryManager(...)
        self.neuHebb_manager = NeuHebbManager(...)
        self.recall_engine = NeurovaRecallEngine(...)

        # 新系统（逐步接管）
        self.cognitive_storage = CognitiveStorageEngine(...)
        self.crystallizer = PatternCrystallizer(self.cognitive_storage)

        # 适配器：旧系统写入时，同步到新系统
        self._memory_bridge = MemoryBridge(
            old_memory=self.memory_manager,
            old_hebb=self.neuHebb_manager,
            new_storage=self.cognitive_storage,
        )

    async def chat(self, message: str):
        # 优先从新系统检索方法论
        methodology = self.crystallizer.retrieve_methodology(message)
        if methodology:
            context = self._build_context_with_methodology(message, methodology)
            return await self.loop.predict(context)

        # 正常推理
        result = await self._normal_reasoning(message)

        # 推理完成后观察是否结晶化
        if self._current_trace:
            self.crystallizer.observe_reasoning(self._current_trace)

        return result
```

### 8.2 组件关系映射

| 现有组件 | 在新架构中的角色 |
|----------|-----------------|
| MoEMemoryRouter | 作为 UnifiedRetriever 的一个检索策略 |
| NeuHebbManager | 作为传统记忆的写入通道，通过 MemoryBridge 同步 |
| RecallEngine | 作为 UnifiedRetriever 的多通道融合引擎 |
| TemperatureEngine | 驱动 classify_stage() 进行层级迁移 |
| SleepConsolidation | 在 L3 归档时进行记忆合并和去重 |
| MemoryCache | 作为 L0 Buffer 的读缓存实现 |
| WorkingMemoryAugmenter | 作为上下文构建的记忆压缩层 |
| ContextPool | 接收 MemoryAwareContextBuilder 的注入 |
| ExperienceCaller | 接收结晶化的经验（method 节点） |

---

## 9. 实施路线图

### 9.1 Phase 1: 基础设施（1-2周）

| 任务 | 复杂度 | 产出 |
|------|--------|------|
| `UnifiedMemoryNode` 数据模型 | 低 | 统一数据格式 |
| `CognitiveStorageEngine` (L0-L1) | 中 | 缓冲写入 + 分层存储 |
| `WALManager` | 低 | 崩溃恢复 |
| `MemoryBridge` 适配器 | 中 | 与现有系统并行 |
| SQLite schema 迁移脚本 | 低 | 数据库初始化 |

**验收标准**：
- 写入频率降低 10 倍以上
- 统一检索接口可用
- 与现有系统完全兼容

### 9.2 Phase 2: 溯源与结晶化（2-4周）

| 任务 | 复杂度 | 产出 |
|------|--------|------|
| `ReasoningTraceManager` | 中 | 推理轨迹存储 |
| `PatternCrystallizer` | 高 | 经验积累 |
| `MemoryAwareContextBuilder` | 中 | 记忆注入上下文 |
| `UnifiedRetriever` | 中 | 统一检索接口 |

**验收标准**：
- 推理过程可追溯
- 经验自动结晶化为方法论
- 记忆自动注入上下文

### 9.3 Phase 3: 智能优化（1-2月）

| 任务 | 复杂度 | 产出 |
|------|--------|------|
| L2/L3 迁移自动化 | 中 | 体积控制 |
| 方法论推荐系统 | 高 | 越用越聪明 |
| 智能预加载 | 中 | 基于使用模式预加载 |
| 自适应阈值 | 低 | 根据使用情况调整 |

**验收标准**：
- 相似问题可直接调用方法论
- 存储体积可控（<200MB）
- 越用越聪明的效果可量化

---

## 10. 核心优势

### 10.1 性能优化

| 指标 | 当前 | 优化后 | 提升 |
|------|------|--------|------|
| 写入频率 | 每次推理 | 批量写入(100条) | 100x |
| 检索延迟 | 串行检索 | 并行检索 | 3-5x |
| 存储成本 | 全部SQLite | 分层存储 | 50-80% |
| 结晶化成本 | 每次LLM | 模式聚类 | 97%降低 |

### 10.2 功能增强

| 功能 | 当前 | 优化后 |
|------|------|--------|
| 溯源 | 无 | 完整推理轨迹 |
| 经验积累 | 无 | 自动结晶化 |
| 越用越聪明 | 有限 | 方法论积累 |
| 统一检索 | 分离 | 统一接口 |

### 10.3 量化指标

| 指标 | 初期 | 3个月后 | 6个月后 |
|------|------|---------|---------|
| 平均推理步骤 | 5 | 3 | 1 |
| 方法论复用率 | 0% | 30% | 60% |
| 响应时间 | 10s | 5s | 2s |
| 存储体积 | 123MB | 150MB | 180MB(稳定) |

---

## 11. 附录

### 11.1 相关文件

- `neurova/cognitive_layers/memory_layer/neurova_hebb.py` - NeurovaHebb 数据模型
- `neurova/cognitive_layers/memory_layer/neuHebb_manager.py` - NeuHebbManager 协调器
- `neurova/cognitive_layers/memory_layer/moe_router.py` - MoE 路由器
- `neurova/cognitive_layers/memory_layer/working_memory.py` - 工作记忆
- `neurova/cognitive_layers/memory_layer/cache.py` - 缓存机制
- `neurova/cognitive_layers/memory_layer/sleep.py` - 睡眠整合
- `neurova/cognitive_layers/memory_layer/temperature.py` - 温度引擎
- `neurova/cognitive_layers/memory_layer/neurova_recall.py` - 统一检索引擎
- `neurova/cognitive_layers/memory_layer/unified_vector_store.py` - 向量存储
- `neurova/context_pool.py` - 上下文池
- `neurova/skills/experience_caller.py` - 经验调用器

### 11.2 参考资料

1. Tulving, E. (1973). Encoding specificity and retrieval processes in episodic memory.
2. Collins, A. M., & Loftus, E. F. (1975). A spreading-activation theory of semantic processing.
3. Hebb, D. O. (1949). The organization of behavior.
4. O'Neil, P., Cheng, E., Gawlick, D., & O'Neil, E. (1996). The log-structured merge-tree (LSM-tree).
5. Thought-Retriever (TMLR 2026) - 结构化推理记忆
6. 贝叶斯遗忘曲线 - 记忆衰减模型

---

**文档生成时间**: 2026-06-04 19:00  
**状态**: 设计完成，待实施  
**下一步**: 开始 Phase 1 实施
