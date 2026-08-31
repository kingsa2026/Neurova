# ADR 0009: 统一 ExecutionStatus 枚举

- **Status**: Accepted
- **Date**: 2026-07-09
- **Decision Maker**: 工具层断点修复（zoom-out 根因修复）

## Context

工具层存在 **4 个互不兼容的 `ExecutionStatus` 枚举**，值集不同、基类不同、一处甚至对 Enum 加 `@dataclass`（无效 Python）：

| # | 文件 | 基类 | 值集 |
|---|------|------|------|
| 1 | `neurova/tool_layers/tool_orchestrator.py:27` | `str, Enum` | PENDING/RUNNING/SUCCESS/FAILED/SKIPPED/TIMEOUT |
| 2 | `neurova/agent/tool_execution_manager.py:36` | `Enum` | PENDING/RUNNING/COMPLETED/TIMEOUT/CANCELLED/FAILED |
| 3 | `neurova/shared_core/execution_engine.py:27` | `@dataclass` + `Enum`（无效） | PENDING/RUNNING/COMPLETED/FAILED/CANCELLED/TIMEOUT |
| 4 | `neurova/collaboration/neurflow/execution_engine.py:27` | `Enum` | 未审计 |

**问题**：调用方无法跨模块比较状态（`SUCCESS` vs `COMPLETED` 语义相同但成员名不同）；`@dataclass + Enum` 在 CPython 下行为不可预测；4 处定义互相遮蔽，import 顺序决定拿到哪个。

## Decision

在 `neurova/tool_layers/types.py` 新建**单一规范定义**，所有其他定义改为 re-export：

```python
# neurova/tool_layers/types.py
from enum import Enum

class ExecutionStatus(str, Enum):
    """工具执行状态 — 单一规范定义（ADR 0009）。"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"   # 兼容 orchestrator 的 SUCCESS 语义
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"       # orchestrator 独有，保留
```

### 收敛规则

| 原定义 | 处理 |
|--------|------|
| `tool_orchestrator.py:27` | 删除本地定义，`from neurova.tool_layers.types import ExecutionStatus`；`SUCCESS` → `COMPLETED`（语义等价） |
| `tool_execution_manager.py:36` | 删除本地定义，import 规范定义 |
| `shared_core/execution_engine.py:27` | 删除 `@dataclass`（无效）+ 本地定义，import 规范定义 |
| `neurflow/execution_engine.py:27` | 删除本地定义，import 规范定义 |

### 兼容性

- `str, Enum` 基类使 `ExecutionStatus.COMPLETED == "completed"` 成立，与现有字符串比较代码兼容
- 保留 `SKIPPED`（orchestrator 独有），其他模块不引用即无影响

## Consequences

- **正向**：单一定义消除 import 顺序陷阱；`@dataclass + Enum` 无效组合移除；跨模块状态比较可靠
- **负向**：`SUCCESS` → `COMPLETED` 重命名需同步调用方（grep `ExecutionStatus.SUCCESS` 找全部引用）
- **降级**：若某模块拒绝依赖 `tool_layers`，可在该模块内 `from neurova.tool_layers.types import ExecutionStatus as _ES; ExecutionStatus = _ES` 别名

## References

- 实现：`neurova/tool_layers/types.py`
- Bug 编号：H9（四个 ExecutionStatus 枚举值不同）
- 审计证据：工具层 zoom-out 审计（2026-07-09）
