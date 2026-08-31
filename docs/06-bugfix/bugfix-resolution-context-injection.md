# Bug 修复：ResolutionContext 外部系统注入缺失

## 摘要

**问题**：`neurflow_api.py` 的 `execute_workflow()` 构建 `ResolutionContext` 时，`memory_manager`、`emotion_module`、`crystallizer` 始终为 `None`，导致工作流节点中 `$memory`/`$emotion`/`$crystal` 变量前缀全部失效。

**修复**：为三个缺失的外部系统添加与 `context_pool` 相同的降级逻辑，当 Agent 不可用时自动创建默认实例。

**影响范围**：工作流变量解析系统 — 所有使用 `$memory.xxx`、`$emotion.xxx`、`$crystal.xxx` 前缀的工作流节点。

---

## 根因分析

### 代码路径

```
neurflow_api.py:execute_workflow()
  → line 154-157: 初始化四个外部系统变量为 None
  → line 159-177: 尝试从 Agent 实例提取
  → line 180-188: 仅 context_pool 有降级逻辑
  → line 190-200: 传递四个变量给 executor.execute()
```

### 问题

| 外部系统 | Agent 可用时 | Agent 不可用时（修复前） | Agent 不可用时（修复后） |
|----------|-------------|------------------------|------------------------|
| `memory_manager` | 从 Agent 提取 | None | 创建默认 MemoryManager |
| `context_pool` | 从 Agent 提取 | 创建默认 ContextPool | 创建默认 ContextPool |
| `emotion_module` | 从 memory_manager 提取 | None | 创建默认 EmotionModule |
| `crystallizer` | 从 Agent 提取 | None | 创建默认 PatternCrystallizer |

## 修复内容

### 修改文件

**`neurova/api/endpoints/neurflow_api.py`** (lines 179-212)

新增三个降级分支：

1. **MemoryManager 降级**：使用 `agent_id` 和 `user_id` 创建默认实例
2. **EmotionModule 降级**：优先从 `memory_manager._emotion_module` 提取，否则创建纯内存实例
3. **PatternCrystallizer 降级**：创建 `CognitiveStorageEngine` + `PatternCrystallizer` 组合

### 新增测试

**`tests/unit/test_resolution_context_injection.py`** (8 tests, 8/8 passed)

### 验证

```
tests/unit/test_resolution_context_injection.py — 8/8 passed
Linter — 0 errors
```
