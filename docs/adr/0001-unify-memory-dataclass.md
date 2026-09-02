# ADR 0001: 统一 Memory dataclass 三套

- **Status**: Accepted
- **Date**: 2026-06-27
- **Decision Maker**: Memory System Tier 4A 重构

## Context

Neurova 记忆系统在历史演进中产生了 4 套 Memory dataclass，量纲不一致导致跨层调用时数据语义混乱：

| dataclass | 文件 | 字段数 | temperature 量纲 | importance 量纲 | 用途 |
|-----------|------|--------|-----------------|-----------------|------|
| `Memory` | `neurova/mem_core.py:59` | 6 | 0+（默认 1.0） | 0-1（默认 0.5） | **冗余**，仅作类型提示，零实例化 |
| `Memory` | `neurova/cognitive_layers/memory_layer/models.py:249` | 21 | 0-100（默认 100.0） | 0-100（默认 50.0） | 主领域模型 |
| `MemoryRecord` | `neurova/cognitive_layers/memory_layer/storage.py:29` | 15 | 无此字段 | 0+（默认 0.0） | 持久化层 |
| `UnifiedMemoryNode` | `neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py:54` | 11 | 0-100（默认 100.0） | 无此字段 | LSM-Tree 五层架构 |

**主要冲突**：
- temperature：`mem_core.Memory` 用 0+ 量纲（默认 1.0），其余用 0-100 量纲
- importance：三套分别用 0-1 / 0-100 / 0+ 三种量纲
- 字段重复定义：`mem_core.Memory` 与 `models.Memory` 同名同义但量纲不同，开发者易混淆

**`mem_core.Memory` 实际使用面**（grep 确认，仅 3 处，全部为类型提示 + 重导出）：
- `neurova/memory_rw_manager.py:17` — `Dict[str, Memory]` / `List[Memory]` 类型提示
- `neurova/cognitive/__init__.py:12` — 重导出
- `neurova/memory/__init__.py:118` — 重导出

## Decision

1. **删除 `mem_core.Memory` dataclass**（6 字段），消除量纲冲突源头
2. **保留 3 套 dataclass**，各司其职：
   - `models.Memory` — 主领域模型（21 字段，业务逻辑层使用）
   - `storage.MemoryRecord` — 持久化层（15 字段，序列化/反序列化）
   - `cognitive_storage_engine.UnifiedMemoryNode` — LSM-Tree 五层架构独立数据模型（11 字段）
3. **3 处使用方改为从 `models` 导入**：`memory_rw_manager` / `cognitive/__init__` / `memory/__init__`
4. **新增显式转换方法**（量纲映射集中处理，避免散落在业务代码）：
   - `MemoryRecord.to_memory()` — 0+ importance → 0-100（乘 100，clamp）
   - `MemoryRecord.from_memory()` — 0-100 importance → 0+（除 100）
   - `UnifiedMemoryNode.to_memory()` — temperature 量纲一致，importance 丢弃（无此字段）
   - `UnifiedMemoryNode.from_memory()` — temperature 量纲一致

## Consequences

**正向**：
- 消除 4→3 套 dataclass，量纲冲突源头（`mem_core.Memory`）已清除
- 跨层转换通过显式 `to_memory()`/`from_memory()` 方法，调用方一眼可见量纲转换
- `models.Memory` 成为唯一领域模型，类型提示统一

**负向**：
- 3 套 dataclass 仍需手动转换（未完全合并），但这是必要的——持久化层与 LSM-Tree 层职责不同，强行合并会引入跨层耦合
- 转换方法有运行时开销（datetime 解析、enum 映射），但相比量纲混乱导致的隐蔽 bug，可接受

**验证**：
- 8/8 `tests/unit/cognitive_layers/memory_layer/test_memory_dataclass_unification.py` GREEN
- 227/227 既有 memory_layer 测试零回归
- 11/11 Tier 3E API 端点测试零回归

## References

- Tier 4A 重构计划：`.trae/documents/memory-system-tier3-4-rebuild-plan.md`
- 相关 ADR：[ADR 0002: 保留 UnifiedMemoryNode](./0002-retain-unified-memory-node.md)
- 实现 commit：Tier 4A.1-4A.6（mem_core.py / storage.py / cognitive_storage_engine.py / 3 处导入替换）
