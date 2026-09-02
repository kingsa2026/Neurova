# ADR 0010: 统一 ToolExecutionContext dataclass

- **Status**: Accepted
- **Date**: 2026-07-09
- **Decision Maker**: 工具层断点修复（zoom-out 根因修复）

## Context

工具层存在 **2 个不兼容的 `ToolExecutionContext` dataclass**，字段集互不包含：

| # | 文件 | 字段数 | 字段 |
|---|------|--------|------|
| 1 | `neurova/agent/tool_pipeline.py:24` | 7 | tool_name/params/user_input/success/tool_source/execution_time/timestamp |
| 2 | `neurova/agent/tool_execution_manager.py:48` | 14 | context_id/tool_name/params/user_input/timeout/strategy/status/result/error/created_at/completed_at/retries/max_retries/metadata |

**问题**：定义 1 缺少 `result`/`error`/`status`/`retries` 等执行状态字段，无法承载完整执行上下文。更严重的是，**定义 1 所在的 `tool_pipeline.py` 整个 `ToolExecutionPipeline` 是死代码**（C2：仅被 `test_full_session*.py` import，生产路径从不调用），其 `ToolExecutionContext` 从未在生产中被使用。

## Decision

以 `tool_execution_manager.py:48` 的 14 字段版本为**单一规范定义**：

1. **保留** `tool_execution_manager.py:48` 的 `ToolExecutionContext` 作为规范
2. **删除** `tool_pipeline.py:24` 的 `ToolExecutionContext`（随 `ToolExecutionPipeline` 死代码一并删除，见 C2 修复）
3. 在 `neurova/tool_layers/types.py` re-export 规范定义，供跨模块引用

### 规范字段集（14 字段）

```python
@dataclass
class ToolExecutionContext:
    context_id: str
    tool_name: str
    params: Dict[str, Any]
    user_input: str
    timeout: float = 30.0
    strategy: TimeoutStrategy = TimeoutStrategy.STRICT
    status: ExecutionStatus = ExecutionStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    retries: int = 0
    max_retries: int = 3
    metadata: Optional[Dict[str, Any]] = None
```

## Consequences

- **正向**：消除字段集不兼容；删除死代码减少维护负担；`result` 字段支持传播工具执行结果（H3 修复依赖此字段）
- **负向**：`test_full_session*.py` 若依赖定义 1 的 7 字段版本需更新（但这些测试 import 的 `ToolExecutionPipeline` 整体是死代码，应一并清理或标记 skip）
- **降级**：若死代码清理延后，定义 1 暂时保留但重命名为 `_PipelineToolExecutionContext` 以消除命名冲突

## References

- 实现：`neurova/tool_layers/types.py`（re-export）
- Bug 编号：H8（两个不兼容的 ToolExecutionContext）、C2（tool_pipeline.py 死代码）
- 审计证据：工具层 zoom-out 审计（2026-07-09）
