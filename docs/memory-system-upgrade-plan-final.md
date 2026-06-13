# Neurova 记忆系统升级计划（最终版）

## 项目概述

基于 MeMo 论文和 NeRF 架构，结合 Neurova 现有记忆系统，实施 5 个深度模块化改进。

## 实施路线图

```
Week 1: MemoryRetrievalFacade (3天)
    ↓
Week 2: ToolLifecycleManager (1.5天)
    ↓
Week 3: MemoryKnowledgeBridge (4天)
    ↓
Week 4: EvolutionFacade (2天)
    ↓
Week 5: ContextFacade (1.5天)
```

---

## 候选方案 1：MemoryRetrievalFacade（最高优先级）

### 目标
统一 6 通道检索 + NeRF 融合 + 肌肉记忆 + 工具记忆

### 关键文件
- `neurova/cognitive_layers/memory_layer/neurova_recall.py` — 6通道检索
- `neurova/cognitive_layers/memory_layer/volume_renderer.py` — NeRF融合
- `neurova/cognitive_layers/memory_layer/muscle_memory.py` — 肌肉记忆
- `neurova/cognitive_layers/memory_layer/tool_memory_integration.py` — 工具记忆

### 核心接口

```python
class MemoryRetrievalFacade:
    def retrieve(query, intent=None, limit=10) -> UnifiedRecallResult
    def match_tool(user_input) -> UnifiedRecallResult
    def get_related_memories(memory_id, max_depth=2) -> UnifiedRecallResult
    def search_by_emotion(emotion, limit=10) -> UnifiedRecallResult
```

### 设计决策
1. **Facade 模式** — 统一入口，内部协调
2. **4级降级** — 完整→传统→简单→空
3. **LRU+TTL 缓存** — 避免重复计算
4. **并行检索** — 6通道+肌肉记忆并行

### 性能目标
- 总检索时间：< 100ms（当前 140ms → 优化 41%）
- 缓存命中率：> 60%

### 测试计划
- 25 个单元测试
- 8 个集成测试
- 2 个 E2E 测试

### 实施步骤
1. 定义 `UnifiedRecallResult` 数据模型
2. 实现 `MemoryRetrievalFacade` 类
3. 实现 4 级降级策略
4. 添加 LRU+TTL 缓存
5. 适配 `ChatPipeline` 调用
6. 适配 `PostChatPipeline` 调用
7. 标记旧接口为 deprecated
8. 编写测试
9. 性能基准测试

---

## 候选方案 2：ToolLifecycleManager（高优先级）

### 目标
统一 4 个执行后钩子为 Pipeline 模式

### 关键文件
- `neurova/agent/tool_executor.py:445-498` — on_tool_executed()
- `neurova/cognitive_layers/memory_layer/tool_memory_integration.py` — 工具记忆
- `neurova/evolution/closed_loop.py:276-301` — 进化反馈

### 核心接口

```python
class ToolExecutionPipeline:
    def execute(context: ToolExecutionContext) -> ToolExecutionReport

class ToolExecutionStep(ABC):
    def execute(context, report) -> None
```

### 设计决策
1. **Pipeline 模式** — 步骤化处理，每步可插拔
2. **混合并行** — 独立步骤并行，依赖步骤串行
3. **分级错误处理** — critical/warning/info
4. **配置支持** — PipelineConfig 动态启用/禁用步骤

### 性能目标
- 总处理时间：< 50ms（当前 ~80ms）
- 并行加速比：> 1.5x

### 测试计划
- 15 个单元测试
- 5 个集成测试

### 实施步骤
1. 定义 `ToolExecutionContext` 数据模型
2. 定义 `ToolExecutionReport` 数据模型
3. 定义 `ToolExecutionStep` 抽象基类
4. 实现 4 个具体 Step 类
5. 实现 `ToolExecutionPipeline` 类
6. 实现 `PipelineConfig` 配置类
7. 替换 `on_tool_executed()` 实现
8. 编写测试

---

## 候选方案 3：MemoryKnowledgeBridge（中优先级）

### 目标
连接孤立的知识图谱模块，实现图谱检索通道

### 关键文件
- `neurova/cognitive_layers/knowledge_graph/manager.py` — 知识图谱(988行)
- `neurova/cognitive_layers/memory_layer/neurova_recall.py` — RecallChannel.GRAPH

### 核心接口

```python
class MemoryKnowledgeBridge:
    def enrich_memory_with_graph(memory) -> MemoryRecord
    def retrieve_related_memories(memory_id, max_depth=2) -> List[MemoryRecord]
    def build_graph_from_conversation(conversation) -> GraphStats
    def query_graph_for_context(query, intent) -> List[Dict]

class GraphRecallChannel:
    def search(query, limit) -> List[Dict]
```

### 设计决策
1. **异步构建** — 实体提取异步，不阻塞主流程
2. **增量索引 + 定期全量重建** — 平衡性能和一致性
3. **混合实体提取** — 规则优先，低置信度用LLM验证
4. **标记删除** — 记忆删除时标记，定期清理孤立节点

### 性能目标
- 实体提取：< 20ms（当前 100ms）
- 图谱查询：< 10ms（当前 50ms）
- 关联检索：< 30ms（当前 80ms）

### 测试计划
- 20 个单元测试
- 10 个集成测试

### 实施步骤
1. 实现 `HybridEntityExtractor`
2. 实现 `GraphRecallChannel`
3. 实现 `MemoryKnowledgeBridge`
4. 集成到 `NeurovaRecallEngine`
5. 实现异步构建器
6. 添加图谱索引优化
7. 编写测试

---

## 候选方案 4：EvolutionFacade（中优先级）

### 目标
统一 8 个进化组件为简洁接口

### 关键文件
- `neurova/evolution/closed_loop.py` — EvolutionOrchestrator
- `neurova/evolution/pattern_miner.py` — PatternMiner
- `neurova/evolution/genetic_engine.py` — ToolGeneticEngine
- `neurova/evolution/experience_feedback.py` — ExperienceFeedback

### 核心接口

```python
class EvolutionFacade:
    # 工具权重
    def get_tool_weight(tool_name) -> float
    def update_tool_weight(tool_name, success, latency)
    def rank_tools(tool_names) -> List[str]
    
    # 工具生命周期
    def get_tool_lifecycle_state(tool_name) -> str
    def touch_tool(tool_name)
    
    # 工具选择
    def select_tools(available_tools, context) -> Dict
    
    # 经验处理
    def record_experience(text, task, tools, success) -> Dict
    
    # 模式挖掘
    def get_frequent_patterns(top_n) -> List[Dict]
    
    # 统计
    def get_statistics() -> Dict
```

### 设计决策
1. **Facade 模式** — 简化接口，内部协调
2. **单例工厂 + 实例化支持** — 生产单例，测试独立
3. **向后兼容** — 保留旧接口作为适配器
4. **缓存策略** — 权重/模式/统计信息缓存

### 测试计划
- 10 个单元测试
- 3 个集成测试

### 实施步骤
1. 定义 `EvolutionFacade` 接口
2. 实现各功能模块委托
3. 添加单例工厂函数
4. 实现向后兼容适配器
5. 编写测试

---

## 候选方案 5：ContextFacade（低优先级）

### 目标
简化上下文构建接口，统一多模型格式支持

### 关键文件
- `neurova/context/orchestrator.py` — ContextOrchestrator
- `neurova/context_pool.py` — ContextPool
- `neurova/context/builder.py` — ContextBuilder

### 核心接口

```python
class ContextFacade:
    def build_context(user_input, relevant_memories=None, 
                     crystallized_patterns=None, intent=None) -> List[Dict]
    def build_system_prompt(tools_description="", memory_context="") -> str
    def build_tools_for_llm() -> List[Dict]
    def get_token_budget() -> TokenBudget
    def compress_context(context, target_tokens) -> List[Dict]
    def convert_format(context, target_format) -> List[Dict]
```

### 设计决策
1. **Facade 模式** — 简化接口
2. **保留 ContextPool** — 作为底层实现
3. **多模型格式** — OpenAI/Anthropic/Gemini
4. **LRU+TTL 缓存** — 避免重复计算

### 测试计划
- 8 个单元测试
- 2 个集成测试

### 实施步骤
1. 定义 `ContextFacade` 接口
2. 实现各功能模块委托
3. 添加格式转换支持
4. 添加缓存机制
5. 编写测试

---

## 总体统计

| 指标 | 数值 |
|------|------|
| 总实施时间 | 12 天 |
| 新建文件 | ~15 个 |
| 修改文件 | ~20 个 |
| 新增测试 | ~80 个 |
| 代码行数 | ~3000 行（含测试） |

## 风险评估

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 性能回归 | 高 | 中 | 基准测试 + 缓存 |
| 接口膨胀 | 中 | 低 | 保持小接口 |
| 测试复杂度 | 中 | 中 | 提供测试工具 |
| 向后兼容 | 高 | 低 | 适配器模式 |

## 成功标准

1. 所有 80 个测试通过
2. 性能目标达成（检索 < 100ms，执行 < 50ms）
3. 0 个 linter 错误
4. 向后兼容（旧接口仍可用）
5. 文档完整
