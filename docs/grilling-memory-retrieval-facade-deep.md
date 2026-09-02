# 深入 Grilling: MemoryRetrievalFacade

## 关键设计问题讨论

### 问题 1：接口应该暴露哪些方法？

**当前分散的接口分析：**

```python
# 1. NeurovaRecallEngine.retrieve()
def retrieve(self, query: str, limit: int = 10, use_plugins: bool = True, 
             registry: Optional[SkillRegistry] = None) -> RecallResult

# 2. VolumeRenderer.render()
def render(self, channel_results: Dict[str, List[ChannelSample]], 
           intent: str = "unknown", limit: int = 10) -> List[RenderedMemory]

# 3. MuscleMemory.match_by_query()
def match_by_query(self, query: str, top_k: int = 5) -> List[Tuple[MuscleMemoryItem, float]]

# 4. ToolMemoryIntegration.check_tool_memory()
def check_tool_memory(self, user_input: str) -> Tuple[Optional[Dict], str]
```

**问题：这些接口的返回类型不一致！**

- `RecallResult` — 包含 memories, scores, metadata
- `List[RenderedMemory]` — 包含 memory_id, content, score, channel_scores
- `List[Tuple[MuscleMemoryItem, float]]` — 包含 (item, confidence)
- `Tuple[Optional[Dict], str]` — 包含 (tool_memory, decision)

**决策：统一返回类型**

```python
@dataclass
class UnifiedRecallResult:
    """统一检索结果"""
    memories: List[Dict[str, Any]]  # 统一格式的记忆列表
    scores: Dict[str, float]  # 各通道/来源的分数
    metadata: Dict[str, Any]  # 元数据（意图、耗时等）
    source: str  # 主要来源（recall/nerf/muscle/tool）
    confidence: float  # 整体置信度
```

**Facade 接口设计：**

```python
class MemoryRetrievalFacade:
    """统一记忆检索接口"""
    
    def retrieve(self, query: str, intent: QueryIntent = None, 
                 limit: int = 10) -> UnifiedRecallResult:
        """统一检索入口 — 自动选择最佳检索策略"""
    
    def match_tool(self, user_input: str) -> UnifiedRecallResult:
        """工具记忆匹配 — 用于工具选择决策"""
    
    def get_related_memories(self, memory_id: str, 
                            max_depth: int = 2) -> UnifiedRecallResult:
        """获取关联记忆 — 基于图谱关系"""
    
    def search_by_emotion(self, emotion: str, 
                         limit: int = 10) -> UnifiedRecallResult:
        """按情感检索 — 情感维度检索"""
```

### 问题 2：内部协调机制如何设计？

**当前组件依赖关系：**

```
MemoryRetrievalFacade
├── NeurovaRecallEngine (6通道检索)
│   ├── QueryIntentDetector (意图检测)
│   ├── IntentAwareRecallStrategy (意图策略)
│   └── 6个检索通道 (Temperature, Text, Category, Graph, Emotion, Voice)
├── VolumeRenderer (NeRF融合)
│   ├── ChannelWeightStrategy (权重策略)
│   └── 通道密度配置
├── MuscleMemory (L1/L2/L3三层匹配)
│   ├── 关键词指纹匹配
│   └── 向量指纹匹配
└── ToolMemoryIntegration (工具记忆)
    ├── 动态阈值计算
    └── 生命周期集成
```

**协调策略：**

```python
class MemoryRetrievalFacade:
    def retrieve(self, query, intent=None, limit=10):
        # 1. 意图检测（如果未提供）
        if intent is None:
            intent = self._intent_detector.detect(query)
        
        # 2. 并行检索（6通道 + 肌肉记忆）
        with ThreadPoolExecutor(max_workers=2) as executor:
            # 通道检索
            channel_future = executor.submit(
                self._recall_engine._retrieve_channels, query, intent
            )
            # 肌肉记忆检索
            muscle_future = executor.submit(
                self._muscle_memory.match_by_query, query, limit
            )
            
            channel_results = channel_future.result()
            muscle_results = muscle_future.result()
        
        # 3. 融合策略选择
        if self._use_nerf_fusion:
            # NeRF体渲染融合
            rendered = self._volume_renderer.render(
                channel_results, intent.value, limit
            )
            memories = self._rendered_to_dict(rendered)
        else:
            # 传统加权求和
            memories = self._weighted_merge(channel_results, intent, limit)
        
        # 4. 合并肌肉记忆结果
        memories = self._merge_muscle_memories(memories, muscle_results)
        
        # 5. 构建统一结果
        return UnifiedRecallResult(
            memories=memories,
            scores=self._extract_scores(channel_results, muscle_results),
            metadata={"intent": intent.value, "fusion_mode": self._fusion_mode},
            source="nerf" if self._use_nerf_fusion else "weighted",
            confidence=self._calculate_confidence(memories)
        )
```

### 问题 3：测试策略如何设计？

**测试金字塔：**

```
         ┌─────────────┐
         │  E2E 测试   │  2个
         │ (完整流程)  │
         ├─────────────┤
         │  集成测试   │  8个
         │ (组件交互)  │
         ├─────────────┤
         │  单元测试   │  25个
         │ (各组件)    │
         └─────────────┘
```

**单元测试用例：**

```python
# 1. 意图检测测试
def test_intent_detection():
    facade = MemoryRetrievalFacade(...)
    result = facade.retrieve("what happened yesterday")
    assert result.metadata["intent"] == "TEMPORAL"

# 2. NeRF融合测试
def test_nerf_fusion():
    facade = MemoryRetrievalFacade(use_nerf=True)
    result = facade.retrieve("test query")
    assert result.source == "nerf"

# 3. 肌肉记忆合并测试
def test_muscle_memory_merge():
    facade = MemoryRetrievalFacade(...)
    # Mock肌肉记忆返回高置信度结果
    with mock.patch.object(facade._muscle_memory, 'match_by_query', 
                          return_value=[(item, 0.95)]):
        result = facade.retrieve("test query")
        assert result.confidence > 0.9

# 4. 降级路径测试
def test_fallback_on_failure():
    facade = MemoryRetrievalFacade(...)
    # 模拟NeRF融合失败
    with mock.patch.object(facade._volume_renderer, 'render', 
                          side_effect=Exception("fusion failed")):
        result = facade.retrieve("test query")
        assert result.source == "weighted"  # 降级到传统融合

# 5. 性能测试
def test_retrieval_performance():
    facade = MemoryRetrievalFacade(...)
    start = time.time()
    for _ in range(100):
        facade.retrieve("test query")
    elapsed = time.time() - start
    assert elapsed < 10  # 100次检索 < 10秒
```

**集成测试用例：**

```python
# 1. 完整检索流程测试
def test_full_retrieval_flow():
    # 准备测试数据
    memories = create_test_memories(100)
    facade = MemoryRetrievalFacade(...)
    
    # 执行检索
    result = facade.retrieve("test query")
    
    # 验证结果
    assert len(result.memories) <= 10
    assert all("content" in m for m in result.memories)
    assert result.confidence >= 0.0

# 2. 工具记忆闭环测试
def test_tool_memory_loop():
    facade = MemoryRetrievalFacade(...)
    
    # 第一次匹配（应该失败）
    result1 = facade.match_tool("search for python docs")
    assert result1.confidence < 0.5
    
    # 记录工具使用
    facade._tool_memory.record_tool_usage(
        tool_name="web_search", success=True, problem_text="search for python docs"
    )
    
    # 第二次匹配（应该成功）
    result2 = facade.match_tool("search for python docs")
    assert result2.confidence > 0.8
```

### 问题 4：迁移计划如何设计？

**阶段 1：创建 Facade（第 1 天）**

```python
# 1.1 定义数据模型
@dataclass
class UnifiedRecallResult:
    memories: List[Dict[str, Any]]
    scores: Dict[str, float]
    metadata: Dict[str, Any]
    source: str
    confidence: float

# 1.2 实现 Facade 类
class MemoryRetrievalFacade:
    def __init__(self, recall_engine, volume_renderer, 
                 muscle_memory, tool_memory):
        # 依赖注入
    
    def retrieve(self, query, intent=None, limit=10):
        # 统一检索入口
    
    def match_tool(self, user_input):
        # 工具记忆匹配

# 1.3 添加单例支持
_facade_instance = None
def get_memory_retrieval_facade():
    global _facade_instance
    if _facade_instance is None:
        _facade_instance = MemoryRetrievalFacade(...)
    return _facade_instance
```

**阶段 2：适配现有调用者（第 2 天）**

```python
# 2.1 ChatPipeline 适配
class ChatPipeline:
    def _step_retrieve_and_build_context(self, ctx):
        # 旧代码：
        # relevant_memories = self._agent.unified_retriever.retrieve(ctx.user_input)
        
        # 新代码：
        from neurova.cognitive_layers.memory_layer import get_memory_retrieval_facade
        facade = get_memory_retrieval_facade()
        result = facade.retrieve(ctx.user_input)
        ctx.relevant_memories = result.memories

# 2.2 PostChatPipeline 适配
class PostChatPipeline:
    def _step_record_experience(self, ctx):
        # 旧代码：
        # tool_memory_result = self._agent.tool_memory.check_tool_memory(ctx.user_input)
        
        # 新代码：
        facade = get_memory_retrieval_facade()
        tool_result = facade.match_tool(ctx.user_input)
        # ...
```

**阶段 3：清理旧接口（第 3 天）**

```python
# 3.1 标记旧接口为 deprecated
class NeurovaRecallEngine:
    def retrieve(self, query, limit=10, use_plugins=True, registry=None):
        """..."""
        warnings.warn(
            "NeurovaRecallEngine.retrieve() is deprecated. "
            "Use MemoryRetrievalFacade.retrieve() instead.",
            DeprecationWarning, stacklevel=2
        )
        # 保留原有实现

# 3.2 更新文档
# 在 docs/ 中添加迁移指南
```

### 问题 5：性能优化策略

**当前性能瓶颈：**

1. **NeRF 融合计算**：`VolumeRenderer.render()` 时间复杂度 O(N*K)
   - N = 记忆数量
   - K = 通道数量

2. **并行检索开销**：`ThreadPoolExecutor` 线程创建/销毁

3. **缓存缺失**：重复查询没有缓存

**优化策略：**

```python
class MemoryRetrievalFacade:
    def __init__(self, ...):
        # 1. 结果缓存（LRU + TTL）
        self._cache = TTLCache(maxsize=1000, ttl=300)  # 5分钟过期
        
        # 2. 预热线程池
        self._executor = ThreadPoolExecutor(max_workers=4)
        
        # 3. 批量查询优化
        self._batch_size = 10
    
    def retrieve(self, query, intent=None, limit=10):
        # 1. 检查缓存
        cache_key = f"{query}:{intent}:{limit}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # 2. 执行检索
        result = self._do_retrieve(query, intent, limit)
        
        # 3. 缓存结果
        self._cache[cache_key] = result
        
        return result
    
    def _do_retrieve(self, query, intent, limit):
        # 优化：如果通道结果已经缓存，跳过重复计算
        channel_cache_key = f"channels:{query}:{intent}"
        if channel_cache_key in self._channel_cache:
            channel_results = self._channel_cache[channel_cache_key]
        else:
            channel_results = self._recall_engine._retrieve_channels(query, intent)
            self._channel_cache[channel_cache_key] = channel_results
        
        # ...
```

**性能目标：**

| 操作 | 当前时间 | 目标时间 | 优化策略 |
|------|----------|----------|----------|
| 意图检测 | 5ms | 2ms | 关键词缓存 |
| 6通道检索 | 80ms | 50ms | 并行 + 批量 |
| NeRF融合 | 40ms | 20ms | 向量化计算 |
| 肌肉记忆匹配 | 15ms | 10ms | 指纹缓存 |
| **总计** | **140ms** | **82ms** | **-41%** |

### 问题 6：错误处理和降级策略

**降级层级：**

```
Level 0: 完整功能（NeRF + 6通道 + 肌肉记忆）
    ↓ 失败
Level 1: 传统融合（加权求和 + 6通道 + 肌肉记忆）
    ↓ 失败
Level 2: 简单检索（文本通道 + 关键词匹配）
    ↓ 失败
Level 3: 返回空结果（记录错误日志）
```

**实现：**

```python
class MemoryRetrievalFacade:
    def retrieve(self, query, intent=None, limit=10):
        try:
            # Level 0: 完整功能
            return self._retrieve_full(query, intent, limit)
        except Exception as e:
            logger.warning("Level 0 failed: %s", e)
            
            try:
                # Level 1: 传统融合
                return self._retrieve_weighted(query, intent, limit)
            except Exception as e:
                logger.warning("Level 1 failed: %s", e)
                
                try:
                    # Level 2: 简单检索
                    return self._retrieve_simple(query, limit)
                except Exception as e:
                    logger.error("All retrieval levels failed: %s", e)
                    
                    # Level 3: 返回空结果
                    return UnifiedRecallResult(
                        memories=[],
                        scores={},
                        metadata={"error": str(e)},
                        source="fallback",
                        confidence=0.0
                    )
```

## 最终设计决策

### 决策 1：Facade vs Adapter
**选择：Facade 模式**
- 理由：调用者需要简单接口，内部组件需要协调

### 决策 2：同步 vs 异步
**选择：同步实现 + 异步扩展点**
- 理由：当前组件同步，未来可通过 `asyncio.to_thread()` 支持异步

### 决策 3：单例 vs 实例
**选择：单例工厂函数 + 实例化支持**
- 理由：生产环境单例，测试环境独立实例

### 决策 4：缓存策略
**选择：LRU + TTL 缓存**
- 理由：避免重复计算，5分钟过期保证新鲜度

### 决策 5：降级策略
**选择：4级降级（完整→传统→简单→空）**
- 理由：保证系统可用性，即使部分组件失败

## 实施清单

- [ ] 定义 `UnifiedRecallResult` 数据模型
- [ ] 实现 `MemoryRetrievalFacade` 类
- [ ] 添加单例工厂函数
- [ ] 实现 4 级降级策略
- [ ] 添加 LRU+TTL 缓存
- [ ] 适配 `ChatPipeline` 调用
- [ ] 适配 `PostChatPipeline` 调用
- [ ] 标记旧接口为 deprecated
- [ ] 编写 25 个单元测试
- [ ] 编写 8 个集成测试
- [ ] 编写 2 个 E2E 测试
- [ ] 性能基准测试（< 100ms）
- [ ] 更新文档
