# Neurova 架构审查报告 — 2026-06-06

## 审查摘要

| 指标 | 重构前 | 重构后 | 目标值 | 状态 |
|------|--------|--------|--------|------|
| `agent_core.py` 行数 | 2,081 | 1,520 | <500 | 🟡 -27% |
| Agent 类方法数 | 46 | 39 | <10 | 🟡 -15% |
| Agent 类属性数 | 47 | 44 | <5 | 🟡 -6% |
| `chat()` 方法行数 | ~580 | 39 | <50 | ✅ -93% |
| `chat_pipeline.py` 行数 | — | 706 | — | 新模块 |
| ChatPipeline 测试 | — | 21/21 | — | ✅ |
| 核心模块测试覆盖率 | 71.4% | 71.4% | 80% | 🟡 |
| 循环导入 | 0 | 0 | 0 | ✅ |
| 深度模块化模式 | 已建立 | 已建立 | 已建立 | ✅ |

## 已完成的模块化（v2.0 重构）

以下模块已成功从 Agent 类提取，采用 `agent_ref` 依赖注入模式：

| 模块 | 文件 | 方法数 | 职责 |
|------|------|--------|------|
| MemCore | `mem_core.py` | 11 核心 + 20 代理 | 记忆检索、保存、温度管理 |
| ContextOrchestrator | `agent/context_orchestrator.py` | 5 核心 | 上下文构建、系统提示、工具描述 |
| ToolExecutor | `agent/tool_executor.py` | 8 核心 | 工具调用解析、执行、后处理钩子 |
| PostChatPipeline | `post_chat_pipeline.py` | 15 | 对话后处理管线（10+ 步骤） |

**设计模式确认**：所有深度模块通过 `agent_ref` 访问 Agent 属性，不反向导入 Agent，无循环依赖。

---

## 本次重构成果 (2026-06-06)

### Phase 5: ChatPipeline 提取 — 完成

从 `Agent.chat()` 方法（~580行）提取了 `ChatPipeline` 模块（706行）：

**新建文件**:
- `neurova/agent/chat_pipeline.py` — 对话流程管线（ChatPipeline + ChatContext）
- `tests/unit/test_chat_pipeline.py` — 21 个测试

**设计**:
```python
class ChatPipeline:
    async def execute(self, ctx: ChatContext) -> Dict[str, Any]:
        await self._step_activity_tracking(ctx)      # 空闲追踪 + 会话恢复
        await self._step_pre_llm_checks(ctx)          # 工具记忆检查 + 技能获取
        await self._step_retrieve_and_build_context(ctx)  # 记忆检索 + 上下文构建
        await self._step_evocate_injection(ctx)       # Evocate 结构化推理注入
        await self._step_llm_call(ctx)                # LLM 调用 + 自动续写
        return await self._step_post_processing(ctx)  # 后处理管线
```

**效果**: `Agent.chat()` 从 ~580 行减少到 39 行（-93%），6 个管线步骤独立可测试。

### 附带修复
- **循环导入修复**: `neurova/agent/__init__.py` 改用延迟导入（`__getattr__`）避免 `agent_core ↔ agent` 循环
- **debug_log 清理**: `agent_core.py` 中 12 处 `debug_log()` 调用替换为 `logger.debug()`
- **threading 导入修复**: `security.py` 添加缺失的 `import threading`
- **logging 导入修复**: `module_tracker.py` 添加缺失的 `import logging`

---

## 仍存在的架构问题

### P0: Agent.__init__ 仍是"上帝初始化器"

`Agent.__init__`（lines 278-640）直接初始化 **40+ 个子系统实例属性**：

```
config, memory_manager, storage, temperature_engine, memory_agent(MemCore),
context_orchestrator, cognitive_engine, unified_retriever, crystallizer,
trace_manager, llm_client, conversation_history, _router, _skill_registry,
skill_manager, skill_packer, tool_memory, recall_engine, neuHebb_manager,
tts_manager, approval_manager, growth_analyzer, evolution, evolution_engine,
genetic_engine, tool_lifecycle, tool_synthesizer, tool_orchestrator,
tool_marketplace, tool_executor, post_chat_pipeline, loop, sleep_config_manager,
idle_tracker, session_manager, _trajectory_recorder, sleep_consolidation,
working_memory, conversation_buffer, buffer_module, _builtin_tools, tool_router,
model_adapter, pattern_miner, ...
```

**影响**：
- Agent 实例化耗时长（需要初始化所有子系统）
- 难以测试单个子系统
- 无法按需加载子系统

**解决方案**：SubSystemContainer — 按职责分组的子系统容器

### P1: chat() 方法过长（~580 行）

`chat()` 方法（lines 1053-1635）承担了太多职责：

1. ToolMemory 检查（~50 行）
2. 主动技能获取检查（~15 行）
3. NL 工具合成检查（~25 行）
4. Neurova-Evocate 检索注入（~30 行）
5. 会话历史恢复（~20 行）
6. 轨迹记录（~15 行）
7. 上下文构建（~20 行）
8. Agent Loop 选择与 LLM 调用（~150 行）
9. 续写逻辑（~80 行）
10. 后处理管线调用（~50 行）
11. 各种错误处理和降级逻辑（~125 行）

**解决方案**：将 chat() 中的步骤提取到 PostChatPipeline 和 ChatPipeline

### P2: 重复的 ContextOrchestrator

存在两个同名模块：
- `neurova/context.py` — 旧版 ContextOrchestrator（ContextBuilder 包装器）
- `neurova/agent/context_orchestrator.py` — 新版深度模块

Agent 实际使用的是后者（line 300），但顶层导入的是前者（line 49）。

**解决方案**：移除 `neurova/context.py` 中的旧类，统一使用 `agent/context_orchestrator.py`

### P3: config.py 重复

`neurova/agent/config.py` 包含 `AgentConfig` 的另一个版本，但实际使用的是 `agent_core.py` 中的定义（line 155）。

**解决方案**：将 AgentConfig 定义移到 `agent/config.py`，`agent_core.py` 重导出

### P4: Agent 保留了过渡性委托方法

以下方法仅一行代码转发，是重构的遗留：

```python
def _update_history(self, user_input, reply):
    return self.memory_agent.update_history(user_input, reply)

def _save_conversation_memory(self, ...):
    return self.memory_agent.save_conversation_memory(...)

def _on_tool_executed(self, ...):
    return self.tool_executor.on_tool_executed(...)
```

**解决方案**：在 chat() 中直接调用 memory_agent/tool_executor，移除这些委托方法

### P5: 进化模块仍有空文件

```
neurova/evolution/skill_improver.py  — 0 bytes
neurova/evolution/tool_weights.py    — 0 bytes
```

---

## 改进计划（按优先级排序）

### Phase 1: Agent.__init__ 分解（最高 ROI）

创建 `neurova/agent/subsystems.py`，实现 SubSystemContainer：

```python
class SubSystemContainer:
    """按职责分组的子系统容器"""
    
    def __init__(self, config):
        self.memory = MemorySubSystems(config)
        self.cognition = CognitionSubSystems(config)
        self.evolution = EvolutionSubSystems(config)
        self.tools = ToolSubSystems(config)
        self.infrastructure = InfraSubSystems(config)

class MemorySubSystems:
    """记忆相关子系统"""
    memory_manager, storage, temperature_engine, recall_engine,
    neuHebb_manager, cognitive_engine, unified_retriever,
    crystallizer, trace_manager, working_memory, conversation_buffer,
    buffer_module, tool_memory, muscle_memory, ...

class EvolutionSubSystems:
    """进化相关子系统"""
    evolution, pattern_miner, genetic_engine, tool_lifecycle,
    tool_synthesizer, growth_analyzer, ...
```

**预期效果**：Agent.__init__ 从 ~360 行减少到 ~50 行

### Phase 2: chat() 方法提取

将 chat() 中的步骤提取到 ChatPipeline：

```python
class ChatPipeline:
    """对话流程管线"""
    
    async def execute(self, user_input, **kwargs):
        context = ChatContext(user_input, **kwargs)
        
        await self._step_tool_memory_check(context)
        await self._step_skill_acquisition(context)
        await self._step_evocate_retrieval(context)
        await self._step_build_context(context)
        await self._step_llm_call(context)
        await self._step_post_processing(context)
        
        return context.result
```

**预期效果**：chat() 从 ~580 行减少到 ~30 行

### Phase 3: 清理重复模块

1. 合并两个 ContextOrchestrator
2. 合并两个 AgentConfig
3. 移除委托方法
4. 清理空文件

### Phase 4: 测试覆盖提升

优先覆盖：
1. Agent.__init__ 测试（确保子系统正确初始化）
2. chat() 核心路径测试
3. ChatPipeline 步骤测试
4. SubSystemContainer 测试

---

## 模块依赖图（当前）

```
                    ┌──────────────┐
                    │  Agent Class │
                    │ (God Object) │
                    └──────┬───────┘
                           │ owns/creates
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼────┐      ┌─────▼─────┐     ┌──────▼──────┐
   │ MemCore │      │ Context   │     │ ToolExecutor│
   │         │      │Orchestratr│     │             │
   └────┬────┘      └─────┬─────┘     └──────┬──────┘
        │                  │                  │
   ┌────▼────┐      ┌─────▼─────┐     ┌──────▼──────┐
   │ memory  │      │ context   │     │  tool_router│
   │ manager │      │ builder   │     │  skill_reg  │
   └─────────┘      └───────────┘     └─────────────┘
```

## 模块依赖图（目标）

```
                    ┌──────────────┐
                    │  Agent Class │
                    │  (< 500 LOC) │
                    └──────┬───────┘
                           │ delegates
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼────┐      ┌─────▼─────┐     ┌──────▼──────┐
   │ MemCore │      │ Context   │     │ ToolExecutor│
   └────┬────┘      │Orchestratr│     └──────┬──────┘
        │           └─────┬─────┘            │
        │                 │                  │
   ┌────▼────┐      ┌─────▼─────┐     ┌──────▼──────┐
   │ SubSys  │      │ ChatPipeline│   │ PostChat   │
   │Container│      │ (phases)   │    │ Pipeline   │
   └────┬────┘      └───────────┘     └─────────────┘
        │
   ┌────▼──────────────────────┐
   │ Memory │ Cognition │ Tool │
   │ SubSys │ SubSys    │ SubSys│
   └───────────────────────────┘
```
