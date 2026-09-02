# ADR 0007: 语义搜索 API 端点 RRF 融合

- **Status**: Accepted
- **Date**: 2026-06-27
- **Decision Maker**: Memory System Tier 3E 重构

## Context

`semantic_search_api.py` 4 个端点（`/hybrid` / `/bm25` / `/vector` / `/compare`）原为空壳，返回空 `results: []`（Bug 11）。需实现真实检索逻辑，但项目内无统一检索后端：

**探索发现**：
- 无真实 BM25 实现（仅 `TFIDFBackend` 在 [vector_search_advanced.py:266](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/vector_search_advanced.py#L266)）
- FTS5 仅在 `CognitiveStorageEngine` 孤立模块（[cognitive_storage_engine.py:134](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py#L134)），`MemoryStorage` 无文本搜索方法
- `vector_search_advanced` 函数不存在，实际是 `AdvancedVectorSearch` 类 + `create_vector_search` 工厂
- `SemanticSearch.search_by_keywords()` 返回 `List[str]`（仅 id，无分数）
- `SemanticSearch.compute_similarity(text1, text2)` 返回 0.0-1.0
- 无生产级 RRF 融合实现

## Decision

**纯 Python 实现 Okapi BM25 + RRF 三路融合**，接入现有 `MemoryManager` + `SemanticSearch`。

### 1. BM25 实现（[semantic_search_api.py:102-151](file:///e:/项目/Neurova/neurova/api/endpoints/semantic_search_api.py#L102)）

Okapi BM25 参数：`k1=1.5`, `b=0.75`
- 中英文分词：`_tokenize()` 复用 `semantic_search._extract_keywords` 简化版（英文按空格 + 中文 2-4 字片段）
- IDF: `log((N - n + 0.5) / (n + 0.5) + 1.0)`（+1 平滑，避免负值）
- 分数归一化到 [0,1]（除以最大原始分数）
- 不过滤零分文档（调用方可能需对比 relevant vs irrelevant）

### 2. RRF 融合（[semantic_search_api.py:153-175](file:///e:/项目/Neurova/neurova/api/endpoints/semantic_search_api.py#L153)）

Reciprocal Rank Fusion：`RRF(d) = Σ w_i / (k + r_i(d))`
- `k=60`（业界默认）
- 三路权重：BM25=0.4, Vector=0.4, FTS=0.2
- FTS 路用 `SemanticSearch.search_by_keywords()` 占位（无分数，rank=0.0），项目无统一 FTS5 表

### 3. 四端点实现

| 端点 | 实现 |
|------|------|
| `/hybrid` | BM25 + Vector + FTS 三路 → RRF 融合 → top_k |
| `/bm25` | 单路 BM25 → top_k |
| `/vector` | 单路 `compute_similarity` → top_k |
| `/compare` | BM25 + Vector + RRF（FTS 传空），三组分别返回 |

**数据源**：`get_memory_manager().get_all_memories() -> List[Dict]`（统一入口，不直接访问 `_memories` 内部）

## Consequences

**正向**：
- 4 端点从空壳变为真实实现，11/11 测试 GREEN
- BM25 纯 Python 无外部依赖，归一化 [0,1] 与 Vector 分数可比
- RRF 融合无需调参，对单路分数 scale 不敏感（仅用 rank）

**负向**：
- FTS 路为占位（无统一 FTS5 表），RRF 三路实际退化为两路（BM25 + Vector）
- BM25 全量扫描 `get_all_memories()`，记忆数 >10k 时性能下降（接受：当前规模可接受，未来可接入 FTS5）
- `/compare` 不依赖 FTS（传空 `[]`），避免重复计算

**降级策略**：
- `get_memory_manager()` 失败 → 返回空 `results: []`（API 稳定）
- `compute_similarity()` 异常 → 跳过该条记忆，继续处理
- `search_by_keywords()` 异常 → FTS 路返回空

**验证**：
- `tests/unit/api/test_semantic_search_api_hybrid.py` 3/3 GREEN
- `tests/unit/api/test_semantic_search_api_bm25.py` 4/4 GREEN
- `tests/unit/api/test_semantic_search_api_vector.py` 2/2 GREEN
- `tests/unit/api/test_semantic_search_api_compare.py` 2/2 GREEN

## References

- [ADR 0003: 记忆系统架构](./0003-memory-system-architecture.md)
- [ADR 0006: embedding 工厂](./0006-embedding-factory.md)（Vector 路消费）
- Bug 11 修复：3E
- 实现位置：`neurova/api/endpoints/semantic_search_api.py`
