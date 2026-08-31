# ADR 0006: embedding 工厂 + 单例模式

- **Status**: Accepted
- **Date**: 2026-06-27
- **Decision Maker**: Memory System Tier 3A-3C 重构

## Context

`SemanticSearch`（[semantic_search.py](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/semantic_search.py)）支持两种模式：
- **embedding 模式**：用 ONNX 向量计算语义相似度（精确）
- **关键词模式**：用 TF-IDF + 关键词计数（降级）

**Bug 12**（3C 修复）：`get_semantic_search(embedding_model=None)` 是全局单例，首次创建后忽略所有 `embedding_model` 参数。若首次创建时 ONNX 模型未安装，后续即使模型可用也无法注入，引擎永久降级为关键词模式。

**根因**：
1. [embedding/__init__.py](file:///e:/项目/Neurova/neurova/embedding/__init__.py) 仅导出 `ONNXEmbeddingEngine` 类，无工厂函数
2. `get_semantic_search()` 不尝试懒加载全局 embedding 引擎
3. 单例无重置机制，测试无法隔离

## Decision

**三层单例工厂 + 懒加载 + 测试重置**：

### 1. embedding 工厂（[embedding/__init__.py:25-51](file:///e:/项目/Neurova/neurova/embedding/__init__.py#L25)）

```python
_embedding_engine = None
_embedding_lock = threading.Lock()

def get_embedding_engine():
    """全局 ONNX embedding 引擎单例（懒加载）

    模型未安装时返回 None，调用方据此降级。
    """
    global _embedding_engine
    if _embedding_engine is not None:
        return _embedding_engine
    with _embedding_lock:
        if _embedding_engine is not None:
            return _embedding_engine
        if ONNXEmbeddingEngine is None:
            return None  # 模型未安装
        try:
            _embedding_engine = ONNXEmbeddingEngine()
        except Exception:
            _embedding_engine = None
    return _embedding_engine

def _reset_embedding_engine():
    """测试用：重置单例"""
    global _embedding_engine
    _embedding_engine = None
```

### 2. SemanticSearch 单例修正（[semantic_search.py:239-275](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/semantic_search.py#L239)）

```python
def get_semantic_search(embedding_model=None, use_embedding=True):
    """单例：首次创建时接受 embedding_model；后续忽略（保持稳定）

    若 embedding_model 为 None，尝试从全局工厂懒加载。
    """
    global _semantic_search
    if _semantic_search is None:
        if embedding_model is None and use_embedding:
            try:
                from neurova.embedding import get_embedding_engine
                embedding_model = get_embedding_engine()
            except Exception:
                embedding_model = None  # 降级关键词模式
        _semantic_search = SemanticSearch(embedding_model=embedding_model, use_embedding=use_embedding)
    return _semantic_search

def _reset_semantic_search():
    """测试用：重置单例"""
    global _semantic_search
    _semantic_search = None
```

## Consequences

**正向**：
- embedding 引擎懒加载，首次实际使用时才初始化（避免启动时阻塞）
- `SemanticSearch` 自动尝试全局 embedding 工厂，无需调用方显式注入
- 单例 + 重置函数，测试可隔离（`_reset_*()` 在 `setUp` 调用）

**负向**：
- 单例使并发测试需配合重置函数（接受：测试串行运行）
- ONNX 模型未安装时永久降级，需重启进程才能恢复（接受：模型安装是部署时决策，非运行时）

**降级策略**：
- `get_embedding_engine()` 返回 None → `SemanticSearch.use_embedding=False`
- `compute_similarity()` 降级为关键词 Jaccard 相似度
- `search_by_keywords()` 仍可用（基于关键词索引）

**验证**：
- `tests/unit/embedding/test_embedding_factory.py` GREEN（单例 + 重置）
- `tests/unit/embedding/test_onnx_backend.py` skipif 保护（模型未安装时跳过）
- `tests/unit/cognitive_layers/memory_layer/test_semantic_search_injection.py` GREEN（embedding 注入 + 单例保留）

## References

- [ADR 0003: 记忆系统架构](./0003-memory-system-architecture.md)
- [ADR 0007: API 端点 RRF 融合](./0007-semantic-search-api-rrf.md)（消费 embedding 工厂）
- Bug 12 修复：3C
- 实现位置：`neurova/embedding/__init__.py` + `neurova/cognitive_layers/memory_layer/semantic_search.py:239-275`
