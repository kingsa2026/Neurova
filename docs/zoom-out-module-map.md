# Neurova 模块地图（Zoom-Out 视图）

## 域词汇表

| 术语 | 定义 | 关键文件 |
|------|------|----------|
| **Agent** | AI智能体核心，具有人格、记忆、成长能力 | `agent_core.py` |
| **ChatPipeline** | 6步对话流程管线 | `agent/chat_pipeline.py` |
| **MemoryManager** | 记忆管理外观，路由到12个子模块 | `memory_layer/manager.py` |
| **NeurovaRecallEngine** | 统一记忆检索引擎，支持6通道并行检索 | `memory_layer/neurova_recall.py` |
| **VolumeRenderer** | NeRF体积渲染器，用于多通道记忆融合 | `memory_layer/volume_renderer.py` |
| **MuscleMemory** | 肌肉记忆系统，L1/L2/L3三层架构 | `memory_layer/muscle_memory.py` |
| **ToolMemoryIntegration** | 工具记忆闭环集成 | `memory_layer/tool_memory_integration.py` |
| **EvolutionOrchestrator** | 进化系统协调器 | `evolution/closed_loop.py` |
| **ContextOrchestrator** | 上下文构建协调器 | `context/orchestrator.py` |
| **KnowledgeGraphManager** | 知识图谱管理器 | `knowledge_graph/manager.py` |
| **LLMRouter** | 多模态自适应路由器 | `llm/llm_router.py` |
| **ProviderManager** | LLM服务商管理器 | `llm/provider_manager.py` |
| **AgentLoop** | Agent循环系统，支持热切换 | `agent/loops/` |
| **PostChatPipeline** | 后处理管线 | `agent/post_chat_pipeline.py` |

## 核心模块依赖关系图

```
用户输入
    ↓
┌─────────────────────────────────────────────────────────┐
│                  Agent 核心层                            │
│  Agent (1621行) → ChatPipeline (6步) → PostChatPipeline │
├─────────────────────────────────────────────────────────┤
│              上下文系统 (Context/)                        │
│  ContextOrchestrator → ContextBuilder → UnifiedInjector │
├─────────────────────────────────────────────────────────┤
│              记忆系统 (MemoryLayer/)                     │
│  ┌──────────────┬─────────────────┬──────────────────┐  │
│  │MemoryManager │NeurovaRecallEngine│VolumeRenderer │  │
│  │ (12子模块)    │ (6通道检索)     │ (NeRF融合)      │  │
│  └──────────────┴─────────────────┴──────────────────┘  │
│  ┌──────────────┬─────────────────┬──────────────────┐  │
│  │MuscleMemory  │ToolMemoryInteg  │PatternCrystallizer│ │
│  │ (L1/L2/L3)   │ (闭环学习)      │ (经验固化)        │ │
│  └──────────────┴─────────────────┴──────────────────┘  │
├─────────────────────────────────────────────────────────┤
│              工具系统 (ToolExecutor)                     │
│  ToolExecutor → 执行 → on_tool_executed → 记录          │
├─────────────────────────────────────────────────────────┤
│              进化系统 (Evolution/)                       │
│  EvolutionOrchestrator → PatternMiner → ToolGeneticEngine│
├─────────────────────────────────────────────────────────┤
│              知识图谱 (KnowledgeGraph/)                  │
│  KnowledgeGraphManager → 节点/边操作 → 图遍历            │
├─────────────────────────────────────────────────────────┤
│              LLM系统 (LLM/)                             │
│  LLMRouter → ProviderManager → MultiModelClient         │
└─────────────────────────────────────────────────────────┘
    ↓
Agent输出
```

## 模块详细地图

### 1. Agent 核心层

**文件**: `neurova/agent_core.py` (1621行, 37方法)

**职责**: 
- 协调所有子系统
- 处理用户输入
- 管理对话流程

**关键方法**:
- `chat()` - 主对话入口
- `rebuild_loop()` - 热切换LLM模型
- `process_multimodal()` - 多模态处理

**依赖模块**:
- ChatPipeline (对话流程)
- ContextOrchestrator (上下文构建)
- ToolExecutor (工具执行)
- MemoryManager (记忆管理)
- LLMRouter (LLM路由)

### 2. ChatPipeline 对话管线

**文件**: `neurova/agent/chat_pipeline.py` (706行)

**6步流程**:
1. `_step_activity_tracking` - 空闲追踪 + 会话恢复
2. `_step_pre_llm_checks` - 工具记忆检查 + 技能获取
3. `_step_retrieve_and_build_context` - 记忆检索 + 上下文构建
4. `_step_evocate_injection` - Evocate 结构化推理注入
5. `_step_llm_call` - LLM 调用 + 自动续写
6. `_step_post_processing` - 后处理管线

**关键依赖**:
- MemCore (记忆检索)
- ContextOrchestrator (上下文构建)
- NeuHebbManager (结构化推理记忆)
- CrystallizedExperienceManager (结晶经验)

### 3. 记忆系统 (MemoryLayer)

#### 3.1 MemoryManager (记忆管理外观)

**文件**: `neurova/cognitive_layers/memory_layer/manager.py`

**职责**: 
- 12个子模块的外观
- 通过MemoryBus事件驱动通信
- 统一记忆CRUD接口

**子模块**:
1. `StorageModule` - SQLite存储
2. `IndexModule` - 索引管理
3. `SearchModule` - 搜索引擎
4. `ConsolidationModule` - 记忆整合
5. `EmotionModule` - 情感标注
6. `ConflictModule` - 冲突检测
7. `AttachmentModule` - 附件管理
8. `SecurityModule` - 安全控制
9. `LifecycleModule` - 生命周期管理
10. `TemperatureModule` - 温度衰减
11. `IsolationModule` - 三层隔离
12. `AuditModule` - 审计日志

#### 3.2 NeurovaRecallEngine (统一检索引擎)

**文件**: `neurova/cognitive_layers/memory_layer/neurova_recall.py`

**6通道并行检索**:
1. `TEMPERATURE` - 温度通道
2. `TEXT` - 文本语义通道
3. `CATEGORY` - 分类通道
4. `GRAPH` - 图谱通道
5. `EMOTION` - 情感通道
6. `VOICE` - 语音通道

**两阶段检索**:
- Phase 1: 多通道融合（MoE路由）
- Phase 2: 意图驱动钻取（QueryIntent）

#### 3.3 VolumeRenderer (NeRF体积渲染)

**文件**: `neurova/cognitive_layers/memory_layer/volume_renderer.py`

**核心公式**: `Score(m) = Σ T_i · σ_i · c_i · w_i`

**职责**:
- 多通道记忆融合
- 考虑通道间"遮挡"关系
- 支持注意力渲染模式

#### 3.4 MuscleMemory (肌肉记忆)

**文件**: `neurova/cognitive_layers/memory_layer/muscle_memory.py`

**三层架构**:
- **L1**: 条件反射级（毫秒响应）
- **L2**: 热路径缓存（秒级响应）
- **L3**: 工具记忆（需要检索）

**匹配规则**: 关键词指纹 + 向量指纹混合匹配

#### 3.5 ToolMemoryIntegration (工具记忆闭环)

**文件**: `neurova/cognitive_layers/memory_layer/tool_memory_integration.py`

**闭环流程**:
```
用户输入 → check_tool_memory() → 匹配 → auto_execute → record_tool_usage → 下次检索
```

**关键功能**:
- 动态置信度阈值
- 生命周期集成
- 肌肉记忆传播

### 4. 工具系统 (ToolExecutor)

**文件**: `neurova/agent/tool_executor.py` (488行)

**职责**:
- 文本工具调用解析（多策略）
- 工具执行调度
- 后处理钩子（on_tool_executed）

**关键方法**:
- `parse_tool_calls()` - 解析工具调用
- `execute_tool()` - 执行工具
- `on_tool_executed()` - 后处理钩子（记忆记录+生命周期+技能打包+进化反馈）

### 5. 进化系统 (Evolution)

**文件**: `neurova/evolution/closed_loop.py`

**核心组件**:
1. `ToolLifecycleManager` - 工具生命周期管理
2. `AdaptiveToolWeights` - 自适应工具权重
3. `PatternMiner` - 序列模式挖掘
4. `ToolGeneticEngine` - 工具遗传编程
5. `NLToolSynthesizer` - 自然语言工具合成
6. `EvolutionOrchestrator` - 统一进化引擎

**闭环流程**:
```
工具执行 → 经验记录 → 模式挖掘 → 权重更新 → 工具进化
```

### 6. 上下文系统 (Context)

**文件**: `neurova/context/orchestrator.py`

**职责**:
- 构建系统提示
- 注入记忆、经验、情感
- 管理上下文预算（16K tokens）

**关键组件**:
- `ContextBuilder` - 上下文构建器
- `UnifiedContextInjector` - 统一上下文注入器
- `ContextPool` - 上下文池

### 7. 知识图谱 (KnowledgeGraph)

**文件**: `neurova/cognitive_layers/knowledge_graph/manager.py`

**职责**:
- 图谱存储（JSON持久化）
- 节点/边CRUD操作
- 图遍历（BFS、最短路径）
- 子图提取

**节点类型**: CONCEPT, ENTITY, EVENT, MEMORY, SKILL, TOOL, PERSON, LOCATION, TIME, CUSTOM

**关系类型**: IS_A, HAS_A, PART_OF, RELATED_TO, CAUSES, SIMILAR_TO, TEMPORAL, CAUSAL, DEPENDS_ON等

### 8. LLM系统 (LLM)

**文件**: `neurova/llm/`

**核心组件**:
1. `LLMRouter` - 多模态自适应路由器（10种请求类型）
2. `ProviderManager` - 服务商管理器（OpenAI/Anthropic/Gemini/Ollama/OpenRouter）
3. `MultiModelLLMClient` - 多模型统一客户端
4. `AgentLoop` - Agent循环系统（支持热切换）

### 9. 渠道系统 (Channels)

**文件**: `neurova/channels/`

**支持平台**:
- 飞书、钉钉、企业微信
- 微信、Telegram、Discord
- QQ、MQTT、WebSocket
- SIP、Webhook、移动设备（QR码配对）

## 数据流图

### 1. 对话数据流

```
用户输入 → Agent.chat() → ChatPipeline
  ↓
步骤1: 空闲追踪 + 会话恢复
  ↓
步骤2: 工具记忆检查 → check_tool_memory()
  ↓
步骤3: 记忆检索 + 上下文构建
  ├─→ NeurovaRecallEngine (6通道检索)
  ├─→ VolumeRenderer (NeRF融合)
  └─→ ContextOrchestrator (构建上下文)
  ↓
步骤4: Evocate结构化推理注入
  ↓
步骤5: LLM调用
  ├─→ LLMRouter (选择模型)
  ├─→ ProviderManager (获取客户端)
  └─→ AgentLoop (执行推理)
  ↓
步骤6: 后处理
  ├─→ PostChatPipeline
  ├─→ 记忆保存
  ├─→ 经验记录
  └─→ 工具进化反馈
```

### 2. 工具记忆闭环

```
用户输入 → check_tool_memory()
  ↓
MuscleMemory.match_by_query() → L1/L2/L3匹配
  ↓
匹配成功？ → auto_execute → execute_from_memory_async()
  ↓
执行结果 → record_tool_usage()
  ├─→ usage_history更新
  ├─→ tool_stats更新
  └─→ muscle_memory.record_usage()
  ↓
下次相似问题 → 复用经验
```

### 3. 进化闭环

```
工具执行完成 → on_tool_executed()
  ↓
EvolutionOrchestrator.on_after_tool_execution()
  ├─→ tool_weights.update_weight()
  ├─→ pattern_miner.add_sequence()
  ├─→ crystallizer.observe()
  └─→ lifecycle_manager.touch()
  ↓
模式积累 → PatternCrystallizer._try_crystallize()
  ↓
结晶经验 → 下次对话注入上下文
```

## 关键接口

### 1. Agent ↔ 记忆系统

```python
# 记忆检索
memories = await agent.mem_core.recall(query, limit=10)

# 记忆保存
agent.mem_core.remember(content, metadata)

# 情感标注
emotion = agent.emotion_analyzer.analyze(text)
```

### 2. Agent ↔ 工具系统

```python
# 工具执行
result = await agent.tool_executor.execute_tool(tool_name, params)

# 工具记忆检查
memory = agent.tool_memory_integration.check_tool_memory(user_input)

# 工具记录
agent.tool_memory_integration.record_tool_usage(tool_name, result)
```

### 3. Agent ↔ 进化系统

```python
# 经验记录
agent.evolution.on_experience_recorded(tool_name, context, success)

# 工具权重更新
agent.evolution.tool_weights.update_weight(tool_name, delta)

# 模式挖掘
agent.evolution.pattern_miner.add_sequence(tool_sequence)
```

### 4. Agent ↔ 上下文系统

```python
# 构建上下文
context = await agent.context_orchestrator.build_context(
    user_message, memories, crystallized_patterns
)

# 注入系统提示
system_prompt = agent._build_system_prompt()
```

### 5. Agent ↔ 知识图谱

```python
# 添加节点
kg = get_knowledge_graph_manager()
node = kg.add_node(label="Python", node_type=NodeType.CONCEPT)

# 添加边
kg.add_edge(source_id, target_id, relation_type=RelationType.RELATED_TO)

# 图遍历
neighbors = kg.get_neighbors(node_id)
```

## 模块间通信模式

### 1. 依赖注入 (Agent → 模块)

```python
class MemCore:
    def __init__(self, agent_ref):
        self.agent = agent_ref  # 访问Agent属性
        
    def recall(self, query):
        # 通过agent_ref访问其他模块
        memories = self.agent.memory_manager.search(query)
        return memories
```

### 2. 事件驱动 (模块 ↔ 模块)

```python
# MemoryBus事件
bus.emit(MemoryEvent.MEMORY_SAVED, {"memory": memory})
bus.on(MemoryEvent.MEMORY_SAVED, handler)

# EventBus事件
event_bus.emit("tool_executed", {"tool": tool_name, "result": result})
```

### 3. 单例模式 (全局访问)

```python
# 获取单例
memory_manager = get_memory_manager()
kg_manager = get_knowledge_graph_manager()
llm_router = get_llm_router()

# 重置单例（测试用）
reset_memory_manager()
reset_knowledge_graph_manager()
```

## 性能关键路径

### 1. 工具记忆匹配（毫秒级）

```
L1条件反射 → L2热缓存 → L3工具记忆
     ↓           ↓           ↓
   <1ms       <10ms      <100ms
```

### 2. 多通道记忆检索（10-100ms）

```
6通道并行 → MoE路由 → 融合排序
    ↓          ↓          ↓
  5-20ms    1-5ms     1-3ms
```

### 3. 上下文构建（50-200ms）

```
记忆注入 → 经验注入 → 情感注入 → 工具描述
    ↓          ↓          ↓          ↓
  10-50ms   5-20ms    1-5ms     1-3ms
```

## 扩展点

### 1. 新增记忆通道

```python
class NewChannel(BaseChannel):
    def retrieve(self, query, limit):
        # 实现检索逻辑
        return results
    
# 注册通道
MemoryRetrieverRegistry.register("new_channel", NewChannel())
```

### 2. 新增工具类型

```python
class NewTool(BaseTool):
    def execute(self, params):
        # 实现执行逻辑
        return result
    
# 注册工具
ToolRegistry.register("new_tool", NewTool())
```

### 3. 新增LLM服务商

```python
class NewProvider(BaseProvider):
    def generate(self, prompt, **kwargs):
        # 实现生成逻辑
        return response
    
# 注册服务商
ProviderManager.register("new_provider", NewProvider())
```

## 监控指标

### 1. 记忆系统

- 记忆总量：`memory_manager.get_stats()`
- 检索延迟：`neurova_recall_engine.get_stats()`
- 渠道权重：`volume_renderer.get_channel_weights()`

### 2. 工具系统

- 工具使用次数：`tool_executor.get_stats()`
- 匹配成功率：`tool_memory_integration.get_stats()`
- 肌肉记忆分布：`muscle_memory.get_stats()`

### 3. 进化系统

- 工具权重分布：`evolution.tool_weights.get_weights()`
- 模式数量：`evolution.pattern_miner.get_patterns()`
- 生命周期状态：`evolution.lifecycle_manager.get_stats()`

## 总结

Neurova的记忆系统升级方案需要考虑：

1. **记忆检索优化**：6通道并行 + NeRF融合 + 意图驱动
2. **工具记忆闭环**：肌肉记忆 + 动态阈值 + 生命周期集成
3. **进化系统集成**：经验记录 + 模式挖掘 + 工具进化
4. **上下文系统集成**：16K预算 + 多源注入 + 动态压缩
5. **知识图谱集成**：图谱检索 + 关系推理 + 子图提取
6. **训练系统集成**：自动训练 + 强化学习 + 端到端优化

关键设计原则：
- **深度模块**：小接口，深实现
- **依赖注入**：通过agent_ref访问，无循环依赖
- **事件驱动**：模块间解耦通信
- **单例管理**：全局访问，测试隔离
- **线程安全**：threading.RLock保护共享状态