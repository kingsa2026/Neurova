# ADR 0003: 记忆系统架构决策

- **Status**: Accepted
- **Date**: 2026-06-27
- **Decision Maker**: Memory System Tier 1-4 重构

## Context

Neurova 记忆系统历经多轮演进，存在以下架构问题（Tier 1-4 重构前）：

1. **17 维分类体系散落**：`memory_layer/` 下 7 个核心模块（manager / storage / models / neurova_recall / semantic_search / cognitive_storage_engine / temperature）职责边界模糊
2. **持久化层缺失关键方法**：`MemoryStorage` 仅有 `delete`（[storage.py:321](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/storage.py#L321)），缺 `get_recent_memories` / `delete_memory`，调用方被迫绕路
3. **检索引擎构造签名错误**：`NeurovaRecallEngine` 真实签名为 `memory_manager=` 唯一注入点，但 `memory_layer.py:170` 用了 6 个不存在的 kwarg（`storage=` / `temperature_engine=` / `config=` 等），运行时必抛 TypeError
4. **API 端点空壳**：4 个语义搜索端点（`/hybrid` / `/bm25` / `/vector` / `/compare`）返回空 `results: []`
5. **4 套 dataclass 量纲冲突**：详见 [ADR 0001](./0001-unify-memory-dataclass.md)

## Decision

采用**分层架构 + 深度模块**模式，明确各模块职责：

```
┌─────────────────────────────────────────────────┐
│ API 层 (api/endpoints/semantic_search_api.py)   │  薄层：HTTP 路由 + RRF 融合
├─────────────────────────────────────────────────┤
│ 检索层 (memory_layer/neurova_recall.py)         │  深模块：5 通道并行 + 意图钻取
│   └─ NeurovaRecallEngine(memory_manager=...)    │  唯一注入点
├─────────────────────────────────────────────────┤
│ 语义层 (memory_layer/semantic_search.py)        │  单例工厂 + embedding 懒加载
│   └─ SemanticSearch(embedding_model=...)        │
├─────────────────────────────────────────────────┤
│ 持久化层 (memory_layer/storage.py)              │  JSON + 索引 + CRUD
│   └─ MemoryStorage(storage_dir=...)             │
├─────────────────────────────────────────────────┤
│ LSM-Tree 层 (cognitive_storage_engine.py)       │  五层架构（L0-L4）独立演进
│   └─ CognitiveStorageEngine                     │
├─────────────────────────────────────────────────┤
│ 领域模型 (memory_layer/models.py)               │  Memory dataclass（21 字段）
└─────────────────────────────────────────────────┘
```

**关键设计原则**：
1. **深度模块**：`NeurovaRecallEngine` 通过 `memory_manager` 唯一注入点访问全部记忆数据，避免 storage / temperature / config 等多参数散落
2. **单例工厂**：`get_memory_manager()` / `get_semantic_search()` / `get_embedding_engine()` 全局单例，懒加载 + 线程锁
3. **显式转换**：跨层 dataclass 转换通过 `to_memory()` / `from_memory()` 方法，量纲映射集中处理（详见 [ADR 0001](./0001-unify-memory-dataclass.md)）
4. **三层隔离**：`agent_id` / `neuser_id` / `user_id` 贯穿所有层，`MemoryIndex.by_isolation_key` 提供组合键索引

## Consequences

**正向**：
- 调用方只需 `get_memory_manager()` 一个入口，记忆系统内部细节封装在深度模块内
- 单例工厂 + 懒加载避免循环导入（符合 `neurova/` 的 `__getattr__` 惯例）
- 三层隔离在所有层一致执行，无绕路

**负向**：
- `NeurovaRecallEngine` 接口表面大（37 方法），但这是必要的——5 通道并行 + 意图钻取需要集中编排
- 单例工厂使测试需配合 `_reset_*()` 辅助函数（已在 3A/3C 添加）

**验证**：
- 246/246 测试 GREEN（227 memory_layer + 11 API + 8 dataclass 统一）
- `MemoryManager.storage` 非 None（Bug 8 修复）
- `NeurovaRecallEngine` 成功创建不抛 TypeError（Bug 9/14 修复）

## References

- [ADR 0001: 统一 Memory dataclass](./0001-unify-memory-dataclass.md)
- [ADR 0002: 保留 UnifiedMemoryNode](./0002-retain-unified-memory-node.md)
- [ADR 0004: CognitiveStorageEngine LSM-Tree](./0004-cognitive-storage-engine-lsm.md)
- [ADR 0005: NeurovaRecallEngine 签名](./0005-neurova-recall-engine-signature.md)
- [ADR 0006: embedding 工厂](./0006-embedding-factory.md)
- [ADR 0007: API 端点 RRF 融合](./0007-semantic-search-api-rrf.md)
- 实现位置：`neurova/cognitive_layers/memory_layer/` 全模块
