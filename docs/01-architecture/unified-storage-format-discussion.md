# 统一存储格式讨论文档（深度版）

**讨论日期**: 2026-06-04  
**背景**: 针对 Neurova-Evocate 系统中统一存储格式的架构讨论  
**参与者**: 用户、AI助手  
**状态**: 深度讨论中

---

## 1. 问题背景与痛点分析

### 1.1 当前存储架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          当前存储架构                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  传统记忆:                                                                  │
│    MemoryManager → Storage (SQLite) → 12个独立模块                          │
│    特点: 结构化、事务支持、并发安全                                          │
│                                                                             │
│  Neurova Hebb:                                                             │
│    NeuHebbManager → JSON文件 (neurova_hebbs.json)                          │
│    特点: 简单、易读、但无事务支持                                            │
│                                                                             │
│  缓存层:                                                                    │
│    - MemoryCache: 读写缓存、批量写入                                        │
│    - WorkingMemory: 单轮压缩、多轮状态折叠、计划缓存                         │
│    - PlanCache: 计划缓存                                                    │
│                                                                             │
│  ⚠️ 问题: 存储系统独立，无数据交换，缓存层未充分利用                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 用户痛点（深度分析）

| 痛点 | 根因 | 影响 |
|------|------|------|
| SQLite写入压力 | 每次推理都写入，无批量优化 | 性能下降，响应延迟 |
| 存储体积爆炸 | 推理数据量大，无生命周期管理 | 存储成本高，备份困难 |
| 检索方式不统一 | MOE只检索传统记忆，NeurovaHebb独立检索 | 遗漏重要记忆 |
| 溯源困难 | 推理过程无关联ID | 无法追踪推理来源 |
| 无法积累经验 | 推理过程记录后未被复用 | 重复推理，浪费资源 |

---

## 2. 核心架构方案：事件驱动的记忆生命周期管理

### 2.1 设计理念

**核心思想**: 不是"统一存储格式"，而是"统一记忆生命周期"。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    记忆生命周期管理架构                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │  感知层     │ → │  缓存层     │ → │  存储层     │ → │  进化层     │  │
│  │  (Perceive) │    │  (Cache)    │    │  (Store)    │    │  (Evolve)   │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│        ↓                  ↓                  ↓                  ↓          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ 对话/工具   │    │ WorkingMem  │    │ SQLite/JSON │    │ 经验结晶    │  │
│  │ 推理过程    │    │ MemoryCache │    │ 分层存储    │    │ 方法论      │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│                                                                             │
│  事件总线 (Event Bus) 贯穿所有层                                            │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ MemoryEvent.CREATED → CACHED → STORED → CONSOLIDATED → CRYSTALLIZED │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 与现有架构的集成

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    与现有组件的集成                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  用户输入                                                                   │
│      ↓                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     ContextPool (上下文池)                           │   │
│  │  - 收集: 系统指令、记忆、对话、经验、情感、反思、工具调用、用户输入   │   │
│  │  - 转换: OpenAI ↔ Anthropic 格式                                    │   │
│  │  - 压缩: 截断/摘要                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│      ↓                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     MoEMemoryRouter (MOE路由器)                      │   │
│  │  - 向量门控: query_vec vs centroids → Top-K Expert                  │   │
│  │  - 专家下钻: L0 SQL → L1 结构化 → L2 TF-IDF                        │   │
│  │  - 全局兜底: query_vec vs memories → Top-K 记忆                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│      ↓                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     UnifiedRecallEngine (统一检索引擎)               │   │
│  │  - 5通道并行: 温度、文本、类别、图谱、情感                          │   │
│  │  - 意图钻取: 解释、对比、扩展、举例、关联                           │   │
│  │  - 结果融合: 多信号加权排序                                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│      ↓                                                                      │
│  LLM 推理                                                                   │
│      ↓                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     PostChatPipeline (后处理管道)                    │   │
│  │  - 经验记录: ExperienceCaller.record()                              │   │
│  │  - 反思生成: GrowthLogManager                                       │   │
│  │  - 温度更新: TemperatureEngine                                      │   │
│  │  - 睡眠整理: SleepConsolidation                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 解决方案详解

### 3.1 SQLite写入压力 → 批量写入 + 事件驱动

**问题**: 每次推理都写入SQLite，写入压力大。

**解决方案**:

```python
class EventDrivenMemoryWriter:
    """事件驱动的记忆写入器"""
    
    def __init__(self, storage, cache, batch_size=10, flush_interval=60):
        self.storage = storage
        self.cache = cache  # MemoryCache
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.pending_writes = []
        self.last_flush = time.time()
    
    def on_memory_event(self, event: MemoryEvent):
        """监听记忆事件"""
        if event.type == MemoryEvent.CREATED:
            # 1. 先写入缓存（快速）
            self.cache.set(event.memory_id, event.data)
            
            # 2. 加入批量写入队列
            self.pending_writes.append(event.data)
            
            # 3. 判断是否需要刷新
            if self._should_flush():
                self._flush_to_storage()
    
    def _should_flush(self) -> bool:
        """判断是否需要刷新到存储"""
        return (
            len(self.pending_writes) >= self.batch_size or
            time.time() - self.last_flush >= self.flush_interval
        )
    
    def _flush_to_storage(self):
        """批量刷新到存储"""
        if not self.pending_writes:
            return
        
        # 批量写入SQLite
        self.storage.batch_insert(self.pending_writes)
        
        # 清空队列
        self.pending_writes.clear()
        self.last_flush = time.time()
```

**效果**:
- 写入频率降低 10-100 倍
- 批量写入效率提升 5-10 倍
- 缓存层吸收大部分读取压力

### 3.2 存储体积爆炸 → 分层存储 + 生命周期管理

**问题**: 推理数据量大，存储成本高。

**解决方案**:

```python
class MemoryLifecycleManager:
    """记忆生命周期管理器"""
    
    # 生命周期阶段
    STAGES = {
        "hot": {"ttl_days": 7, "storage": "sqlite_memory"},
        "warm": {"ttl_days": 30, "storage": "sqlite_disk"},
        "cold": {"ttl_days": 365, "storage": "json_archive"},
        "crystallized": {"ttl_days": None, "storage": "json_permanent"},
    }
    
    def __init__(self, storage, temperature_engine):
        self.storage = storage
        self.temperature_engine = temperature_engine
    
    def migrate_memories(self):
        """根据温度自动迁移记忆"""
        all_memories = self.storage.get_all()
        
        for memory in all_memories:
            stage = self._determine_stage(memory)
            
            if stage != memory.get("stage"):
                self._migrate(memory, stage)
    
    def _determine_stage(self, memory: Dict) -> str:
        """根据温度和使用频率确定阶段"""
        temp = memory.get("temperature", 50)
        usage = memory.get("usage_count", 0)
        days_since_access = self._days_since_access(memory)
        
        # 结晶化条件: 高温度 + 高使用频率 + 长期存在
        if temp >= 80 and usage >= 10 and days_since_access >= 30:
            return "crystallized"
        
        # 热数据: 最近7天，温度 >= 60
        if days_since_access <= 7 and temp >= 60:
            return "hot"
        
        # 温数据: 最近30天，温度 >= 30
        if days_since_access <= 30 and temp >= 30:
            return "warm"
        
        # 冷数据: 其他
        return "cold"
```

**效果**:
- 热数据保持在SQLite（快速访问）
- 冷数据迁移到JSON（低成本存储）
- 结晶化记忆永久保存（越用越聪明）

### 3.3 检索方式不统一 → MOE + NeurovaHebb 统一检索

**问题**: MOE只检索传统记忆，NeurovaHebb独立检索。

**解决方案**:

```python
class UnifiedMemoryRetriever:
    """统一记忆检索器"""
    
    def __init__(self, moe_router, hebb_manager, recall_engine):
        self.moe_router = moe_router
        self.hebb_manager = hebb_manager
        self.recall_engine = recall_engine
    
    async def retrieve(self, query: str, limit: int = 10) -> List[Dict]:
        """统一检索接口"""
        # 1. 并行检索
        moe_task = self.moe_router.retrieve(query, limit=limit)
        hebb_task = asyncio.to_thread(
            self.hebb_manager.retrieve_neurova_hebb, query
        )
        recall_task = asyncio.to_thread(
            self.recall_engine.recall_flat, query, limit=limit
        )
        
        moe_results, hebb_results, recall_results = await asyncio.gather(
            moe_task, hebb_task, recall_task
        )
        
        # 2. 结果融合
        merged = self._merge_results(
            moe_results, hebb_results, recall_results
        )
        
        # 3. 去重和排序
        unique = self._deduplicate(merged)
        unique.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        return unique[:limit]
    
    def _merge_results(self, *result_sets) -> List[Dict]:
        """融合多源结果"""
        merged = []
        for results in result_sets:
            for r in results:
                # 统一格式
                merged.append({
                    "id": r.get("id"),
                    "content": r.get("content"),
                    "score": r.get("score", 0.5),
                    "source": r.get("source", "unknown"),
                    "temperature": r.get("temperature", 50),
                    "metadata": r.get("metadata", {}),
                })
        return merged
```

**效果**:
- 单一检索接口，透明访问所有记忆
- 并行检索，性能最优
- 结果融合，不遗漏重要记忆

### 3.4 溯源问题 → 事件溯源 + 推理链追踪

**问题**: 推理过程无关联ID，无法追踪来源。

**解决方案**:

```python
@dataclass
class ReasoningTrace:
    """推理轨迹"""
    trace_id: str  # 唯一标识
    query: str  # 原始查询
    reasoning_chain: List[ReasoningStep]  # 推理链
    sources: List[MemorySource]  # 记忆来源
    result: str  # 推理结果
    confidence: float  # 置信度
    created_at: datetime
    metadata: Dict[str, Any]

@dataclass
class ReasoningStep:
    """推理步骤"""
    step_id: str
    thought: str  # 思考内容
    tool_used: Optional[str]  # 使用的工具
    memory_accessed: List[str]  # 访问的记忆ID
    intermediate_result: str  # 中间结果

@dataclass
class MemorySource:
    """记忆来源"""
    memory_id: str
    memory_type: str  # "traditional", "neurova_hebb", "experience"
    relevance_score: float
    access_time: datetime

class ReasoningTraceManager:
    """推理轨迹管理器"""
    
    def __init__(self, storage):
        self.storage = storage
    
    def start_trace(self, query: str) -> str:
        """开始新的推理轨迹"""
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        trace = ReasoningTrace(
            trace_id=trace_id,
            query=query,
            reasoning_chain=[],
            sources=[],
            result="",
            confidence=0.0,
            created_at=datetime.now(timezone.utc),
            metadata={},
        )
        self.storage.store_trace(trace)
        return trace_id
    
    def record_step(self, trace_id: str, step: ReasoningStep):
        """记录推理步骤"""
        trace = self.storage.get_trace(trace_id)
        trace.reasoning_chain.append(step)
        self.storage.update_trace(trace)
    
    def record_source(self, trace_id: str, source: MemorySource):
        """记录记忆来源"""
        trace = self.storage.get_trace(trace_id)
        trace.sources.append(source)
        self.storage.update_trace(trace)
    
    def get_trace_by_query(self, query: str) -> Optional[ReasoningTrace]:
        """根据查询获取推理轨迹"""
        return self.storage.find_trace_by_query(query)
```

**效果**:
- 完整的推理轨迹记录
- 可追溯的记忆来源
- 支持推理过程重放和分析

### 3.5 无法积累经验 → 推理结晶化 + 方法论提取

**问题**: 推理过程记录后未被复用。

**解决方案**:

```python
class ReasoningCrystallizer:
    """推理结晶化器"""
    
    def __init__(self, hebb_manager, experience_caller, llm_fn):
        self.hebb_manager = hebb_manager
        self.experience_caller = experience_caller
        self.llm_fn = llm_fn
    
    async def crystallize_reasoning(self, trace: ReasoningTrace) -> Dict[str, Any]:
        """将推理过程结晶化为经验"""
        
        # 1. 提取关键信息
        key_info = self._extract_key_info(trace)
        
        # 2. 生成方法论
        methodology = await self._generate_methodology(key_info)
        
        # 3. 存储为 NeurovaHebb
        hebb = self.hebb_manager.generate_neurova_hebb(
            document_id=f"reasoning_{trace.trace_id}",
            content=methodology,
            metadata={
                "type": "reasoning_methodology",
                "query_pattern": key_info["query_pattern"],
                "success_rate": trace.confidence,
                "tools_used": key_info["tools_used"],
                "reasoning_steps": len(trace.reasoning_chain),
            }
        )
        
        # 4. 记录为经验
        self.experience_caller.record(
            task=trace.query,
            tools=key_info["tools_used"],
            success=trace.confidence >= 0.7,
            metadata={
                "trace_id": trace.trace_id,
                "methodology": methodology,
            }
        )
        
        return {
            "hebb_id": hebb[0].id if hebb else None,
            "methodology": methodology,
            "confidence": trace.confidence,
        }
    
    def _extract_key_info(self, trace: ReasoningTrace) -> Dict:
        """提取关键信息"""
        tools_used = []
        for step in trace.reasoning_chain:
            if step.tool_used:
                tools_used.append(step.tool_used)
        
        return {
            "query_pattern": self._extract_query_pattern(trace.query),
            "tools_used": list(set(tools_used)),
            "reasoning_pattern": self._extract_reasoning_pattern(trace),
            "success_factors": self._extract_success_factors(trace),
        }
    
    async def _generate_methodology(self, key_info: Dict) -> str:
        """生成方法论"""
        prompt = f"""
基于以下推理过程，提取可复用的方法论：

查询模式: {key_info['query_pattern']}
使用工具: {', '.join(key_info['tools_used'])}
推理模式: {key_info['reasoning_pattern']}
成功因素: {key_info['success_factors']}

请生成简洁的方法论描述，包含：
1. 问题类型识别
2. 解决策略
3. 工具选择建议
4. 注意事项
"""
        return await self.llm_fn(prompt)
```

**效果**:
- 推理过程自动结晶化为经验
- 方法论可复用，避免重复推理
- 越用越聪明，积累解决问题的能力

### 3.6 与上下文系统的关系 → 记忆注入上下文

**问题**: 记忆系统与上下文系统如何协作？

**解决方案**:

```python
class MemoryContextInjector:
    """记忆上下文注入器"""
    
    def __init__(self, unified_retriever, context_pool):
        self.unified_retriever = unified_retriever
        self.context_pool = context_pool
    
    async def inject_memories(self, query: str, context: List[Dict]) -> List[Dict]:
        """将记忆注入上下文"""
        
        # 1. 检索相关记忆
        memories = await self.unified_retriever.retrieve(query, limit=5)
        
        if not memories:
            return context
        
        # 2. 构建记忆上下文
        memory_context = self._build_memory_context(memories)
        
        # 3. 注入到系统消息
        for msg in context:
            if msg.get("role") == "system":
                msg["content"] += f"\n\n## 相关记忆\n{memory_context}"
                break
        
        return context
    
    def _build_memory_context(self, memories: List[Dict]) -> str:
        """构建记忆上下文文本"""
        lines = []
        for i, mem in enumerate(memories, 1):
            source = mem.get("source", "unknown")
            content = mem.get("content", "")
            score = mem.get("score", 0)
            
            lines.append(f"{i}. [{source}] {content} (相关度: {score:.2f})")
        
        return "\n".join(lines)
```

**效果**:
- 记忆自动注入上下文
- LLM 可以利用历史记忆
- 上下文系统透明访问所有记忆

---

## 4. 完整架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    事件驱动的记忆生命周期管理架构                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  用户输入                                                                   │
│      ↓                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     ContextPool (上下文池)                           │   │
│  │  - 收集: 系统指令、记忆、对话、经验、情感、反思、工具调用、用户输入   │   │
│  │  - 转换: OpenAI ↔ Anthropic 格式                                    │   │
│  │  - 压缩: 截断/摘要                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│      ↓                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     UnifiedMemoryRetriever (统一检索器)              │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │   │
│  │  │ MoE Router  │    │ HebbManager │    │ RecallEngine│              │   │
│  │  │ (传统记忆)  │    │ (Hebb记忆)  │    │ (多通道)    │              │   │
│  │  └─────────────┘    └─────────────┘    └─────────────┘              │   │
│  │         ↓                  ↓                  ↓                     │   │
│  │  ┌─────────────────────────────────────────────────────────────┐   │   │
│  │  │              结果融合 + 去重 + 排序                          │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│      ↓                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     MemoryContextInjector (记忆注入器)               │   │
│  │  - 将检索结果注入系统消息                                          │   │
│  │  - LLM 可以利用历史记忆                                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│      ↓                                                                      │
│  LLM 推理                                                                   │
│      ↓                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     ReasoningTraceManager (推理轨迹管理器)           │   │
│  │  - 记录推理链                                                       │   │
│  │  - 追踪记忆来源                                                     │   │
│  │  - 支持重放和分析                                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│      ↓                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     PostChatPipeline (后处理管道)                    │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │   │
│  │  │ Experience  │    │ Temperature │    │ Sleep       │              │   │
│  │  │ Caller      │    │ Engine      │    │ Consolidation│             │   │
│  │  └─────────────┘    └─────────────┘    └─────────────┘              │   │
│  │         ↓                  ↓                  ↓                     │   │
│  │  ┌─────────────────────────────────────────────────────────────┐   │   │
│  │  │              ReasoningCrystallizer (推理结晶化器)             │   │   │
│  │  │  - 提取方法论                                               │   │   │
│  │  │  - 生成 NeurovaHebb                                         │   │   │
│  │  │  - 记录为经验                                               │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│      ↓                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     MemoryLifecycleManager (生命周期管理器)          │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │   │
│  │  │ Hot Layer   │ → │ Warm Layer  │ → │ Cold Layer  │              │   │
│  │  │ (SQLite)    │    │ (SQLite)    │    │ (JSON)      │              │   │
│  │  └─────────────┘    └─────────────┘    └─────────────┘              │   │
│  │         ↓                                                           │   │
│  │  ┌─────────────────────────────────────────────────────────────┐   │   │
│  │  │              Crystallized Layer (结晶层)                     │   │   │
│  │  │  - 永久保存的方法论和经验                                    │   │   │
│  │  │  - 越用越聪明的核心                                          │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. 实施路线图

### 5.1 Phase 1: 基础设施（1-2周）

**目标**: 建立事件驱动基础，解决写入压力

| 任务 | 描述 | 优先级 |
|------|------|--------|
| EventDrivenMemoryWriter | 实现批量写入器 | P0 |
| UnifiedMemoryRetriever | 统一检索接口 | P0 |
| MemoryLifecycleManager | 生命周期管理器 | P1 |

**验收标准**:
- 写入频率降低 10 倍以上
- 统一检索接口可用
- 生命周期管理器可自动迁移记忆

### 5.2 Phase 2: 溯源与结晶化（2-4周）

**目标**: 实现推理溯源和经验积累

| 任务 | 描述 | 优先级 |
|------|------|--------|
| ReasoningTraceManager | 推理轨迹管理器 | P0 |
| ReasoningCrystallizer | 推理结晶化器 | P0 |
| MemoryContextInjector | 记忆注入器 | P1 |

**验收标准**:
- 推理过程可追溯
- 经验自动结晶化为方法论
- 记忆自动注入上下文

### 5.3 Phase 3: 智能优化（1-2月）

**目标**: 实现越用越聪明

| 任务 | 描述 | 优先级 |
|------|------|--------|
| 智能预加载 | 基于使用模式预加载 | P1 |
| 方法论推荐 | 根据查询推荐方法论 | P1 |
| 自适应阈值 | 根据使用情况调整阈值 | P2 |

**验收标准**:
- 相似问题可直接调用方法论
- 记忆系统自动优化
- 越用越聪明的效果可量化

---

## 6. 核心优势

### 6.1 性能优化

| 指标 | 当前 | 优化后 | 提升 |
|------|------|--------|------|
| 写入频率 | 每次推理 | 批量写入 | 10-100x |
| 检索延迟 | 串行检索 | 并行检索 | 3-5x |
| 存储成本 | 全部SQLite | 分层存储 | 50-80% |

### 6.2 功能增强

| 功能 | 当前 | 优化后 |
|------|------|--------|
| 溯源 | 无 | 完整推理轨迹 |
| 经验积累 | 无 | 自动结晶化 |
| 越用越聪明 | 有限 | 方法论积累 |
| 统一检索 | 分离 | 统一接口 |

### 6.3 架构优势

| 方面 | 优势 |
|------|------|
| 可扩展性 | 事件驱动，易于扩展新功能 |
| 可维护性 | 模块化设计，职责清晰 |
| 可测试性 | 接口清晰，易于测试 |
| 向后兼容 | 渐进式迁移，不破坏现有功能 |

---

## 7. 结论

### 7.1 推荐方案

**事件驱动的记忆生命周期管理架构**

核心组件：
- **EventDrivenMemoryWriter**: 批量写入，解决写入压力
- **UnifiedMemoryRetriever**: 统一检索，解决检索不统一
- **ReasoningTraceManager**: 推理溯源，解决溯源问题
- **ReasoningCrystallizer**: 经验积累，解决无法积累经验
- **MemoryLifecycleManager**: 生命周期管理，解决存储体积爆炸

### 7.2 与现有架构的关系

| 组件 | 关系 |
|------|------|
| MoEMemoryRouter | 作为传统记忆检索的后端 |
| NeuHebbManager | 作为 Hebb 记忆检索的后端 |
| RecallEngine | 作为多通道检索的后端 |
| ContextPool | 接收记忆注入 |
| ExperienceCaller | 接收结晶化的经验 |
| TemperatureEngine | 驱动生命周期迁移 |

### 7.3 实施优先级

1. **P0**: EventDrivenMemoryWriter + UnifiedMemoryRetriever
2. **P1**: ReasoningTraceManager + ReasoningCrystallizer
3. **P2**: MemoryLifecycleManager + MemoryContextInjector
4. **P3**: 智能优化 + 方法论推荐

---

## 8. 附录

### 8.1 相关文件

- `neurova/cognitive_layers/memory_layer/neurova_hebb.py` - Neurova Hebb数据模型
- `neurova/cognitive_layers/memory_layer/moe_router.py` - MoE路由器
- `neurova/cognitive_layers/memory_layer/working_memory.py` - 工作记忆
- `neurova/cognitive_layers/memory_layer/cache.py` - 缓存机制
- `neurova/cognitive_layers/memory_layer/sleep.py` - 睡眠整合
- `neurova/cognitive_layers/memory_layer/temperature.py` - 温度引擎
- `neurova/context_pool.py` - 上下文池
- `neurova/skills/experience_caller.py` - 经验调用器

### 8.2 参考资料

1. **Thought-Retriever论文** - 结构化推理记忆
2. **贝叶斯遗忘曲线** - 记忆衰减模型
3. **事件溯源模式** - 状态变更记录
4. **分层存储架构** - 热温冷数据分离
5. **MoE架构** - 稀疏门控专家混合

---

**文档生成时间**: 2026-06-04 18:43  
**状态**: 深度讨论中  
**下一步**: 讨论具体实施细节
