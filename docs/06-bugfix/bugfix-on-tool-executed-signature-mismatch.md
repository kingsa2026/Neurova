# Bugfix: on_tool_executed 签名不匹配导致工具记忆闭环静默失效

**修复日期**: 2026-06-24
**严重度**: P0 (高)
**状态**: 已修复
**修复文件**: `neurova/tool_executor.py`
**测试文件**: `tests/unit/core/test_on_tool_executed_signature.py`

## 症状

工具记忆闭环（MuscleMemory L1/L2/L3 学习）静默失效。
Skill 执行成功后，`agent_core._on_skill_post_execute` 调用 `tool_executor.on_tool_executed(...)` 记录工具使用，
但该调用始终抛出异常，被 `agent_core.py:1112` 的 `except Exception` 吞掉，
导致 tool_memory 和 tool_lifecycle 均未收到任何工具执行事件。

## 复现

```python
from neurova.tool_executor import ToolExecutor
from unittest.mock import Mock

executor = ToolExecutor(agent_ref=Mock())
# 修复前: AttributeError: 'ToolExecutor' object has no attribute 'on_tool_executed'
executor.on_tool_executed(
    tool_name="search",
    params={"query": "test"},
    user_input="test",
    success=True,
    tool_source="skill_system",
    execution_time=1.0,
)
```

## 根因链（5 层）

| 层 | 位置 | 问题 |
|---|---|---|
| 1. 命名漂移 | `tool_executor.py:1018` | 重构时 `_on_tool_executed` 改名为私有，但调用方 `agent_core.py:1103` 仍调用 `on_tool_executed`（无下划线） |
| 2. 参数丢失 | `tool_executor.py:1018` | 3 参数签名 `(tool_name, result, success)` 丢失了 `user_input/tool_source/execution_time` |
| 3. 内部方法错误 | `tool_executor.py:1041` | 调用 `self.tool_lifecycle.update_usage(tool_name, success)`，但 `ToolLifecycleManager` 真实方法是 `touch(tool_name, success)` |
| 4. 参数语义混淆 | `tool_executor.py:1030` | 把 `result`（执行结果）当作 `tool_params` 传给 `record_tool_usage`，丢失了真正的工具参数 |
| 5. 异常吞噬 | `agent_core.py:1112` | `except Exception as e: logger.warning(...)` 吞掉所有错误，导致 bug 长期未被发现 |

## 修复

### 变更 1: 恢复公开方法名 + 扩展参数签名

`neurova/tool_executor.py:1018-1059`

```python
# 修复前
def _on_tool_executed(self, tool_name: str, result: Dict, success: bool):

# 修复后
def on_tool_executed(
    self,
    tool_name: str,
    params: Dict[str, Any],
    user_input: str,
    success: bool,
    tool_source: str = "",
    execution_time: float = 0.0,
):
```

### 变更 2: 正确转发到 tool_memory（全参数）

```python
# 修复前
self.tool_memory.record_tool_usage(
    tool_name=tool_name,
    success=success,
    tool_params=result,  # 错误: result 是执行结果, 不是工具参数
)

# 修复后
self.tool_memory.record_tool_usage(
    tool_name=tool_name,
    success=success,
    execution_time=execution_time,
    problem_text=user_input,
    tool_source=tool_source,
    tool_params=params,  # 正确: params 是工具参数
)
```

### 变更 3: 修正 tool_lifecycle 调用

```python
# 修复前
self.tool_lifecycle.update_usage(tool_name, success)  # 方法不存在

# 修复后
self.tool_lifecycle.touch(tool_name, success)  # ToolLifecycleManager 真实方法
```

### 变更 4: 更新模块顶部注释

`neurova/tool_executor.py:8`: `_on_tool_executed` → `on_tool_executed`

## 验证

```
tests/unit/core/test_on_tool_executed_signature.py::TestOnToolExecutedSignature::test_public_method_exists PASSED
tests/unit/core/test_on_tool_executed_signature.py::TestOnToolExecutedSignature::test_accepts_six_parameters PASSED
tests/unit/core/test_on_tool_executed_signature.py::TestOnToolExecutedForwardsToToolMemory::test_forwards_all_parameters_to_tool_memory PASSED
tests/unit/core/test_on_tool_executed_signature.py::TestOnToolExecutedForwardsToToolMemory::test_does_not_pass_result_as_tool_params PASSED
tests/unit/core/test_on_tool_executed_signature.py::TestOnToolExecutedForwardsToToolLifecycle::test_calls_touch_not_update_usage PASSED
tests/unit/core/test_on_tool_executed_signature.py::TestOnToolExecutedForwardsToToolLifecycle::test_forwards_failure_to_touch PASSED
tests/unit/core/test_on_tool_executed_signature.py::TestOnToolExecutedRobustness::test_no_tool_memory_no_crash PASSED
tests/unit/core/test_on_tool_executed_signature.py::TestOnToolExecutedRobustness::test_tool_memory_exception_does_not_propagate PASSED
```

8/8 测试通过。`test_tool_executor.py` 原有 2 个测试无回归。

## 影响范围

- **直接受益**: Skill 执行后的工具记忆闭环恢复，MuscleMemory L1/L2/L3 可正常学习
- **间接受益**: ToolLifecycleManager 可正确记录工具调用次数和成功率，生命周期状态转换恢复
- **无破坏性变更**: 调用方 `agent_core.py:1103` 参数名与新签名完全一致，无需修改

## 后续建议（不在本次修复范围）

1. **agent_core.py:1112 的异常吞噬**: 建议引入结构化错误日志（唯一前缀 + JSON.stringify），让闭环学习失败可观测，避免类似 bug 再次被掩盖
2. **tool_memory/tool_lifecycle 通过 agent_ref 属性代理访问**: 是浅模块的体现，未来可考虑深化为显式依赖注入
