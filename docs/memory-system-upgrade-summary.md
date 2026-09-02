# Neurova 记忆系统升级计划总结

## 项目背景

基于 MeMo 论文（Memory as a Model）和 NeRF 架构，结合 Neurova 现有记忆系统，创建完整的记忆系统升级计划。

## 架构审查结果

使用 `zoom-out` 和 `improve-codebase-architecture` 技能，识别出 5 个深度模块化改进候选方案：

### 候选方案概览

| # | 候选方案 | 推荐度 | 核心价值 | 关键文件 |
|---|----------|--------|----------|----------|
| 1 | 统一记忆检索接口 (MemoryRetrievalFacade) | ⭐⭐⭐⭐⭐ | 统一 6 通道检索 + NeRF 融合 | neurova_recall.py, volume_renderer.py |
| 2 | 工具记忆闭环深度模块 (ToolLifecycleManager) | ⭐⭐⭐⭐ | 统一 4 个执行后钩子 | tool_executor.py:445-498 |
| 3 | 知识图谱集成接口 (MemoryKnowledgeBridge) | ⭐⭐⭐ | 连接孤立的知识图谱模块 | knowledge_graph/manager.py |
| 4 | 进化系统统一接口 (EvolutionFacade) | ⭐⭐⭐ | 统一 8 个进化组件 | evolution/closed_loop.py |
| 5 | 上下文构建深度模块 (ContextFacade) | ⭐⭐⭐ | 简化上下文构建接口 | context/orchestrator.py |

## 详细分析

### 候选方案 1：统一记忆检索接口 (MemoryRetrievalFacade)

**问题**：
- `NeurovaRecallEngine`、`VolumeRenderer`、`MuscleMemory`、`ToolMemoryIntegration` 接口分散
- 调用者需要了解内部结构
- 新增检索通道需要修改多处代码

**解决方案**：
- 创建 `MemoryRetrievalFacade` 统一入口
- 内部协调 6 通道检索 + NeRF 融合 + 肌肉记忆 + 工具记忆
- 提供 `retrieve()`、`match_tool()`、`render_channels()` 等简化接口

**收益**：
- 调用者只需调用一个方法
- 新增检索通道只需修改 Facade 内部
- 测试更简单（mock Facade 即可）

**讨论框架**：`docs/grilling-memory-retrieval-facade.md`

---

### 候选方案 2：工具记忆闭环深度模块 (ToolLifecycleManager)

**问题**：
- `on_tool_executed()` 有 4 个串行钩子
- 每个钩子独立 try/except，错误处理分散
- 新增后处理步骤需要修改 `tool_executor.py`

**解决方案**：
- 创建 `ToolExecutionPipeline` 步骤化处理
- 每个步骤可独立启用/禁用
- 支持错误收集和健康监控

**收益**：
- 新增步骤只需添加 Step 实现
- 错误处理统一管理
- 性能监控更清晰

**讨论框架**：`docs/grilling-tool-lifecycle-manager.md`

---

### 候选方案 3：知识图谱集成接口 (MemoryKnowledgeBridge)

**问题**：
- `KnowledgeGraphManager` (988行) 是孤立模块
- `RecallChannel.GRAPH` 已定义但未实现
- 记忆和图谱之间没有自动关联

**解决方案**：
- 实现 `GraphRecallChannel` 图谱检索通道
- 创建 `MemoryKnowledgeBridge` 桥梁模块
- 实现实体提取（规则 + LLM 混合）

**收益**：
- 记忆检索增加图谱维度
- 自动从对话中构建知识图谱
- 支持关联记忆检索

**讨论框架**：`docs/grilling-memory-knowledge-bridge.md`

---

### 候选方案 4：进化系统统一接口 (EvolutionFacade)

**问题**：
- 8 个进化组件接口分散
- `EvolutionOrchestrator` 是 God Object（185-398行）
- 调用者需要了解内部结构

**解决方案**：
- 创建 `EvolutionFacade` 统一门面
- 统一工具权重、生命周期、模式挖掘、经验处理
- 提供 `get_tool_weight()`、`rank_tools()`、`record_experience()` 等简化接口

**收益**：
- 调用者只需调用 Facade 方法
- 内部组件可以独立升级
- 测试更简单

**讨论框架**：`docs/grilling-evolution-facade.md`

---

### 候选方案 5：上下文构建深度模块 (ContextFacade)

**问题**：
- `ContextOrchestrator`、`ContextBuilder`、`ContextPool` 功能重叠
- 调用者需要知道内部结构
- 格式转换逻辑分散

**解决方案**：
- 创建 `ContextFacade` 统一入口
- 内部使用 `ContextPool` 作为底层实现
- 统一支持多模型格式（OpenAI ↔ Anthropic）

**收益**：
- 调用者只需调用 Facade 方法
- 格式转换自动处理
- Token 预算统一管理

**讨论框架**：`docs/grilling-context-facade.md`

## 实施建议

### 优先级排序

1. **MemoryRetrievalFacade** — 最高优先级
   - 影响范围最广（所有记忆检索）
   - 收益最明显（统一接口）
   - 实现复杂度中等

2. **ToolLifecycleManager** — 高优先级
   - 影响工具执行流程
   - 收益明显（步骤化处理）
   - 实现复杂度低

3. **MemoryKnowledgeBridge** — 中优先级
   - 连接孤立模块
   - 收益中等（增加图谱维度）
   - 实现复杂度高（实体提取）

4. **EvolutionFacade** — 中优先级
   - 统一进化系统
   - 收益中等（简化接口）
   - 实现复杂度中等

5. **ContextFacade** — 低优先级
   - 简化上下文构建
   - 收益中等（统一接口）
   - 实现复杂度低

### 实施时间估算

| 候选方案 | 实现时间 | 测试时间 | 总计 |
|----------|----------|----------|------|
| MemoryRetrievalFacade | 2天 | 1天 | 3天 |
| ToolLifecycleManager | 1天 | 0.5天 | 1.5天 |
| MemoryKnowledgeBridge | 3天 | 1天 | 4天 |
| EvolutionFacade | 1.5天 | 0.5天 | 2天 |
| ContextFacade | 1天 | 0.5天 | 1.5天 |
| **总计** | **8.5天** | **3.5天** | **12天** |

## 下一步行动

请确认您希望优先实现哪些候选方案：

1. **全部实现** — 按优先级顺序实施所有 5 个方案
2. **选择性实现** — 只实现特定方案
3. **深入讨论** — 对特定方案进行更详细的 grilling

## 相关文档

- 模块地图：`zoom-out-module-map.md`
- 架构审查报告：`architecture-review-20260612.html`
- Grilling 讨论框架：
  - `docs/grilling-memory-retrieval-facade.md`
  - `docs/grilling-tool-lifecycle-manager.md`
  - `docs/grilling-memory-knowledge-bridge.md`
  - `docs/grilling-evolution-facade.md`
  - `docs/grilling-context-facade.md`
