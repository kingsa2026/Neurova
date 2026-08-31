# Bug Fix: builtin:context 和 builtin:emotion 节点为空壳

**日期**: 2026-06-11
**严重性**: High (功能缺失)
**文件**: `neurova/collaboration/neurflow/builtin.py`, `neurova/collaboration/neurflow/execution_engine.py`

---

## 1. 问题描述

Neurflow 工作流中的 `builtin:context` 和 `builtin:emotion` 内置节点不执行任何实际操作：

- `exec_context` 调用不存在的 `context_pool.get_context(sources, token_budget)` 方法
- `exec_emotion` 调用不存在的 `emotion_module.analyze(text)` 和 `emotion_module.express(text)` 方法
- `ResolutionContext` 中的外部系统引用（`memory_manager`, `context_pool`, `emotion_module`, `crystallizer`）没有传递到节点执行上下文 dict

## 2. 根因分析

### 断裂点 1: 节点执行上下文缺少外部系统引用

`execution_engine.py` 第 249 行构建节点执行上下文时只传入了 `inputs`, `variables`, `node_results`：

```python
result = await self._execute_node(node, resolved_config, {
    "inputs": inputs,
    "variables": resolution_context.variables,
    "node_results": resolution_context.node_results,
})
```

虽然 `ResolutionContext` 已存储了 `memory_manager`, `context_pool`, `emotion_module`, `crystallizer`，但没有暴露给节点执行器。

### 断裂点 2: exec_context 调用不存在的方法

```python
# 不存在的方法
context_pool.get_context(sources, token_budget)

# 正确的 API
context_pool.get_contexts()  # 返回所有 ContextInput
```

`ContextPool` 没有 `get_context(sources, token_budget)` 方法。正确方式是：
1. 调用 `get_contexts()` 获取所有上下文
2. 使用 `ContextSource` 枚举过滤来源
3. 手动按 token 预算截断

### 断裂点 3: exec_emotion 调用不存在的方法

```python
# 不存在的方法
emotion_module.analyze(text)    # → 应为 analyze_text_emotion(text)
emotion_module.express(text)    # → 无此方法
emotion_module.get_state()      # → 应为 get_emotion(memory_id)
```

`EmotionModule` 的正确 API：
- `analyze_text_emotion(text)` → 返回 `EmotionState`
- `get_emotion(memory_id)` → 返回 `Optional[EmotionState]`
- `get_emotional_memories(emotion_type, min_intensity, limit)` → 返回 `List[str]`

## 3. 修复内容

### 3.1 execution_engine.py — 外部系统引用注入

```python
# 修改前
result = await self._execute_node(node, resolved_config, {
    "inputs": inputs,
    "variables": resolution_context.variables,
    "node_results": resolution_context.node_results,
})

# 修改后
result = await self._execute_node(node, resolved_config, {
    "inputs": inputs,
    "variables": resolution_context.variables,
    "node_results": resolution_context.node_results,
    "memory_manager": resolution_context.memory_manager,
    "context_pool": resolution_context.context_pool,
    "emotion_module": resolution_context.emotion_module,
    "crystallizer": resolution_context.crystallizer,
})
```

### 3.2 builtin.py — exec_context 完整重写

- 从 `ctx["context_pool"]` 获取 context_pool
- 调用 `get_contexts()` 获取所有上下文
- 使用 `ContextSource` 枚举按来源过滤
- 按 token 预算截断结果

### 3.3 builtin.py — exec_emotion 完整重写

- 从 `ctx["emotion_module"]` 获取 emotion_module
- 三种模式：`analyze`（文本情感分析）、`query`（情感记忆查询）、`state`（记忆情感状态）

### 3.4 builtin.py — exec_memory_load/exec_memory_save 优先级

- 优先使用 `ctx["memory_manager"]`，降级使用全局单例

### 3.5 builtin.py — emotion 节点定义 schema 更新

- 新增 mode 枚举值：`analyze`, `query`, `state`
- 新增配置字段：`emotion_type`, `memory_id`, `min_intensity`, `limit`

## 4. 测试结果

| 测试类 | 测试数 | 结果 |
|--------|--------|------|
| TestExecContext | 6 | ✅ 全部通过 |
| TestExecEmotion | 7 | ✅ 全部通过 |
| TestExecMemoryNodes | 3 | ✅ 全部通过 |
| TestContextPropagation | 1 | ✅ 全部通过 |
| **总计** | **17** | **✅ 17/17** |

无回归：已有 neurflow 集成测试全部通过，0 linter 错误。

## 5. 数据流（修复后）

```
Agent.chat()
  → PostChatPipeline._execute_neurflow()
    → WorkflowExecutor.execute(
        memory_manager=agent.memory_manager,
        context_pool=agent.context_pool,       ← 新增传递
        emotion_module=agent.emotion_module,   ← 新增传递
        crystallizer=agent.crystallizer,       ← 新增传递
      )
      → ResolutionContext 存储外部引用
      → 节点执行上下文 dict 包含外部引用
      → exec_context: ctx["context_pool"].get_contexts() → 按来源过滤 → token 截断
      → exec_emotion: ctx["emotion_module"].analyze_text_emotion(text) → 情感结果
      → exec_memory_load: ctx["memory_manager"].search(query) → 记忆结果
```
