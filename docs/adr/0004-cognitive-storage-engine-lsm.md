# ADR 0004: CognitiveStorageEngine LSM-Tree 五层架构

- **Status**: Accepted
- **Date**: 2026-06-27
- **Decision Maker**: Memory System Tier 2 + 4A.5 重构

## Context

`MemoryStorage`（[storage.py](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/storage.py)）是单层 JSON 持久化，对所有记忆一视同仁。但记忆有明显的访问热度梯度：

- 秒级访问：当前对话上下文
- 分钟级访问：近期对话引用
- 小时级访问：会话内反复提及
- 天级访问：历史回顾
- 永久存储：结晶经验（工具使用模式、人格特质）

单层存储无法表达这种热度梯度，导致：
1. 冷热数据混存，缓存命中率低
2. 无法按热度选择不同存储介质（内存 / SQLite / JSON / 压缩文件）
3. 结晶经验与易变记忆混在一起， consolidation 时易误删

## Decision

引入 `CognitiveStorageEngine`（[cognitive_storage_engine.py:219](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py#L219)），实现 **LSM-Tree 风格的五层架构**：

| 层级 | 枚举值 | 介质 | 时间窗口 | 用途 |
|------|--------|------|----------|------|
| L0_BUFFER | 0 | 内存 WAL | 秒级 | 写入缓冲区，崩溃恢复 |
| L1_HOT | 1 | SQLite | 分钟级 | 热存储，FTS5 全文索引 |
| L2_WARM | 2 | JSON | 小时级 | 温存储，常规检索 |
| L3_COLD | 3 | 压缩文件 | 天级 | 冷存储，归档检索 |
| L4_CRYSTAL | 4 | 永久 | 永久 | 结晶经验，consolidation 产物 |

**关键设计**：
1. `UnifiedMemoryNode`（[cognitive_storage_engine.py:54](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py#L54)）携带 `layer: StorageLayer` 字段，标识所属层级
2. FTS5 全文索引仅在 L1_HOT 层（[cognitive_storage_engine.py:134-157](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py#L134)），含 `cse_au` UPDATE trigger（Tier 2 修复 Bug 2）
3. `MemoryType` 枚举独立于 `models.MemoryType`（同名同值，按 value 互转，详见 [ADR 0005](./0005-neurova-recall-engine-signature.md) 转换方法）
4. 与 `MemoryStorage` 并存：`MemoryStorage` 负责简单 CRUD，`CognitiveStorageEngine` 负责跨层热度管理

## Consequences

**正向**：
- 热度梯度显式表达，缓存命中率提升
- 结晶经验（L4）与易变记忆（L0-L3）物理隔离，consolidation 安全
- LSM-Tree 可独立演进（如未来接入 FAISS 向量索引），不污染 `MemoryStorage`

**负向**：
- 第 4 套 dataclass `UnifiedMemoryNode`（11 字段）增加心智负担（详见 [ADR 0002](./0002-retain-unified-memory-node.md)）
- `UnifiedMemoryNode` 无 `importance` 字段，与 `models.Memory` 互转时丢失（接受：LSM-Tree 层用 `layer` + `access_count` 表达热度，不用 importance）
- FTS5 仅在 L1 层，跨层文本搜索需降级到 `SemanticSearch.search_by_keywords` 占位

**量纲约定**：
- `UnifiedMemoryNode.temperature` 与 `models.Memory.temperature` 均 0-100 量纲，转换无需缩放
- `UnifiedMemoryNode` 无 `importance` / `tags` / `owner` / 隔离字段，转换时丢弃

**验证**：
- `tests/unit/cognitive_layers/memory_layer/test_cognitive_storage_engine*.py` 全部 GREEN
- `cse_au` UPDATE trigger 修复 Bug 2（Tier 2）
- `UnifiedMemoryNode.to_memory()` / `from_memory()` 双向转换 8/8 GREEN（Tier 4A.5）

## References

- [ADR 0002: 保留 UnifiedMemoryNode 作为第 4 套 dataclass](./0002-retain-unified-memory-node.md)
- [ADR 0003: 记忆系统架构](./0003-memory-system-architecture.md)
- 实现位置：`neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py`
