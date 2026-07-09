# ADR 0002: 保留 UnifiedMemoryNode 作为第 4 套 dataclass

- **Status**: Accepted
- **Date**: 2026-06-27
- **Decision Maker**: Memory System Tier 4A 重构

## Context

在 [ADR 0001](./0001-unify-memory-dataclass.md) 中，我们删除了冗余的 `mem_core.Memory`，将 4 套 Memory dataclass 精简为 3 套。但 `cognitive_storage_engine.UnifiedMemoryNode`（11 字段）是否应进一步合并入 `storage.MemoryRecord`（15 字段）需要单独决策。

**`UnifiedMemoryNode` 与 `MemoryRecord` 的本质差异**：

| 维度 | `UnifiedMemoryNode` | `MemoryRecord` |
|------|---------------------|----------------|
| 所属层 | LSM-Tree 五层架构（L0 Buffer → L4 Crystal） | 单层 JSON 持久化 |
| 设计目标 | 跨层热温冷数据流，支持未来接入 FAISS | 简单 CRUD + 索引 |
| 独有字段 | `layer: StorageLayer`（存储层级） | `tags`、`owner`、`shared`、`share_group_ids` |
| 缺失字段 | 无 `importance`、`tags`、`owner`、隔离字段 | 无 `layer`、`trace_id`、`embedding` |
| temperature | 0-100（与 `models.Memory` 一致） | 无此字段 |
| 演进方向 | 可能接入向量索引（FAISS/Milvus） | 仍是 JSON 单文件 |

强行合并会导致：
1. `MemoryRecord` 被迫承载 `layer`/`trace_id` 等 LSM-Tree 专属概念
2. `UnifiedMemoryNode` 被迫承载 `tags`/`owner` 等业务字段，污染存储层抽象
3. 两层独立演进受阻（如 LSM-Tree 接入 FAISS 时需改动 `MemoryRecord`）

## Decision

保留 `UnifiedMemoryNode` 作为第 4 套 dataclass，不合并入 `MemoryRecord`。通过 `to_memory()` / `from_memory()` 与 `models.Memory` 互操作。

## Consequences

**正向**：
- LSM-Tree 五层架构可独立演进（如未来接入 FAISS），不污染持久化层
- `MemoryRecord` 保持简单，专注 JSON 持久化
- 关注点分离：存储层抽象 vs 业务领域模型 vs LSM-Tree 跨层数据流

**负向**：
- 仍有 4 套 dataclass（含 `UnifiedMemoryNode`），但每套职责清晰
- `UnifiedMemoryNode.to_memory()` 丢失 `layer`/`trace_id` 字段（领域模型无对应字段）
- `UnifiedMemoryNode.from_memory()` 丢弃 `importance` 字段（无对应字段）

**量纲约定**（与 ADR 0001 一致）：
- `UnifiedMemoryNode.temperature` 与 `models.Memory.temperature` 均 0-100 量纲，转换无需缩放
- `UnifiedMemoryNode` 无 `importance` 字段，转换时丢失

**验证**：
- `tests/unit/cognitive_layers/memory_layer/test_memory_dataclass_unification.py::TestUnifiedMemoryNodeConversion` 2/2 GREEN
- 既有 `tests/unit/cognitive_layers/memory_layer/test_cognitive_storage_engine*.py` 零回归

## References

- 前置 ADR：[ADR 0001: 统一 Memory dataclass 三套](./0001-unify-memory-dataclass.md)
- 实现位置：`neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py` `UnifiedMemoryNode.to_memory` / `from_memory`
