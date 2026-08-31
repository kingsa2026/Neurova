# Bug Fix: builtin:llm 变量解析断裂

> **Phase 5 — Report + Cleanup** | bug-hunt workflow  
> 修复日期: 2026-06-11

---

## 1. 问题描述

`builtin:llm` 节点尝试从 `ctx` 中获取 `variable_resolver` 来解析 prompt 中的变量引用（如 `$input.user_query`），但 `execution_engine.py` 在调用节点执行器时传递的 `ctx` 字典中并不包含 `variable_resolver` 键，导致 prompt 中的变量引用永远不会被解析，LLM 收到的是原始 `$prefix.path` 文本而非实际值。

## 2. 根因分析

### 问题层

| 层 | 文件:行号 | 描述 |
|---|---|---|
| 执行引擎 | `execution_engine.py:249-257` | 节点 context dict 缺少 `variable_resolver` 和 `resolution_context` |
| LLM 节点 | `builtin.py:597-603` | `ctx.get("variable_resolver")` 返回 `None`，防御性解析被跳过 |

### 原因链

1. `WorkflowExecutor.execute()` 在 `_init_vars()` 中通过 `get_variable_resolver()` 获取 `self._variable_resolver` 实例
2. 引擎在调用 `resolve_config(node.config, resolution_context)` 时使用 `self._variable_resolver` 解析节点配置中的静态变量
3. 但在构造传给 `_execute_node()` 的 context dict 时，**没有包含** `variable_resolver` 和 `resolution_context`
4. `exec_llm` 从 `ctx.get("variable_resolver")` 获取到 `None`，跳过防御性解析
5. 如果 `resolve_config()` 未完全解析 prompt 中的变量（如动态生成的 prompt 模板），变量引用保持原样传给 LLM

### 数据流（修复前）

```
execution_engine.execute()
  → resolve_config(node.config)         ← 静态变量解析（正常）
  → _execute_node(node, config, ctx)    ← ctx 不含 variable_resolver
    → exec_llm(config, ctx)
      → ctx.get("variable_resolver")    ← 返回 None
      → 跳过防御性解析                    ← 变量引用保持 $input.xxx 原样
      → agent.chat("$input.xxx")        ← LLM 收到未解析的变量引用
```

## 3. 修复内容

### 文件 1: `neurova/collaboration/neurflow/execution_engine.py`

**修改位置**: 第 249-259 行

在节点 context dict 中添加 `variable_resolver` 和 `resolution_context`：

```python
result = await self._execute_node(node, resolved_config, {
    "inputs": inputs,
    "variables": resolution_context.variables,
    "node_results": resolution_context.node_results,
    "memory_manager": resolution_context.memory_manager,
    "context_pool": resolution_context.context_pool,
    "emotion_module": resolution_context.emotion_module,
    "crystallizer": resolution_context.crystallizer,
    "variable_resolver": self._variable_resolver,       # ← 新增
    "resolution_context": resolution_context,            # ← 新增
})
```

### 文件 2: `neurova/collaboration/neurflow/builtin.py`

**修改位置**: 第 594-603 行

在 `exec_llm` 中添加防御性变量解析：

```python
# 变量解析已在执行引擎层完成（resolve_config），
# 但作为防御性编程，如果 prompt 中仍含未解析的变量引用，
# 使用 ctx 中的 variable_resolver 进行兜底解析
var_resolver = ctx.get("variable_resolver")
if var_resolver and ctx.get("resolution_context"):
    import re
    if re.search(r'\$[a-zA-Z_]\w*', prompt) or re.search(r'\$[a-zA-Z_]\w*', system_prompt):
        res_ctx = ctx["resolution_context"]
        prompt = var_resolver.resolve_config(prompt, res_ctx)
        system_prompt = var_resolver.resolve_config(system_prompt, res_ctx)
```

### 文件 3: `tests/unit/test_builtin_context_emotion.py`

扩展 `TestContextPropagation.test_node_context_includes_external_refs` 测试，增加 `variable_resolver` 和 `resolution_context` 断言。

### 文件 4: `tests/unit/test_builtin_llm_variable_resolution.py` (新建)

新增专用测试文件，覆盖：
- 无 resolver 时不解析
- 有 resolver 时解析 prompt 中的变量
- 有 resolver 时解析 system_prompt 中的变量
- 无变量引用时不触发解析
- resolver 异常时优雅降级
- Agent 未初始化时返回 failed

## 4. 修复后数据流

```
execution_engine.execute()
  → resolve_config(node.config)         ← 静态变量解析（正常）
  → _execute_node(node, config, ctx)    ← ctx 含 variable_resolver + resolution_context
    → exec_llm(config, ctx)
      → ctx.get("variable_resolver")    ← 返回 VariableResolver 实例
      → re.search('$...', prompt)       ← 检测到未解析变量
      → var_resolver.resolve_config()   ← 解析 $input.xxx → 实际值
      → agent.chat("今天天气怎么样")      ← LLM 收到解析后的 prompt
```

## 5. 验证结果

| 检查项 | 结果 |
|---|---|
| Linter (execution_engine.py) | 0 errors |
| Linter (builtin.py) | 0 errors |
| Linter (test_builtin_context_emotion.py) | 0 errors |
| 现有测试回归 | 17/17 通过 (test_builtin_context_emotion.py) |
| 新增测试 | 6/6 (test_builtin_llm_variable_resolution.py) |

## 6. 架构评价

### 符合的原则

- **Simplicity First**: 最小改动 — 只在 context dict 中添加 2 个键，在 `exec_llm` 中添加 10 行防御性代码
- **Surgical Changes**: 只修改了断裂点涉及的文件，未波及其他模块
- **深度模块**: `VariableResolver` 作为独立模块，通过 context dict 依赖注入，节点执行器不直接导入

### 设计决策

1. **双层解析策略**: 引擎层 `resolve_config()` 处理静态配置 + 节点层防御性解析处理动态场景
2. **防御性编程**: `exec_llm` 中的正则检测确保只在存在 `$` 变量引用时才调用 resolver，避免不必要的开销
3. **优雅降级**: resolver 缺失或异常不影响基本 LLM 调用功能

### 改进机会

- 其他节点执行器（如 `exec_code`、`exec_http`）也可能需要变量解析，但本次只修复了 `exec_llm`
- 可考虑在引擎层统一提供变量解析后缀钩子，避免每个节点重复防御性代码
