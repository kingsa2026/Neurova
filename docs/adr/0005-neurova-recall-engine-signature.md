# ADR 0005: NeurovaRecallEngine 签名统一

- **Status**: Accepted
- **Date**: 2026-06-27
- **Decision Maker**: Memory System Tier 4B.3 + 3D.4 重构

## Context

`NeurovaRecallEngine`（[neurova_recall.py:504](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/neurova_recall.py#L504)）是记忆检索的核心深模块，5 通道并行 + 意图钻取。但其构造签名在两处调用点与真实定义不匹配，导致运行时 TypeError：

**真实签名**（[neurova_recall.py:515-526](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/neurova_recall.py#L515)）：
```python
def __init__(
    self,
    memory_manager: Any = None,
    max_workers: int = 4,
    timeout_seconds: float = 10.0,
    intent_detector: Optional[QueryIntentDetector] = None,
    intent_strategy: Optional[IntentAwareRecallStrategy] = None,
    use_plugins: bool = True,
    registry: Any = None,
    fusion_mode: str = "legacy",
    density_scale: float = 1.0,
):
```

**Bug 9（4B.3 修复）** — [mem_core.py:381](file:///e:/项目/Neurova/neurova/mem_core.py#L381)：
```python
# 错误：用了 storage= / temperature_engine= / config= 等 6 个不存在的 kwarg
NeurovaRecallEngine(storage=..., temperature_engine=..., config=..., ...)
# 修复后：
NeurovaRecallEngine(memory_manager=self.memory_manager, ...)
```

**Bug 14（3D.4 修复）** — [memory_layer.py:170](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/memory_layer.py#L170)：
```python
# 错误：同样用了 6 个不存在的 kwarg
NeurovaRecallEngine(storage=, temperature_engine=, emotion_analyzer=, tkg=, vector_search=, config=)
# 修复后：
NeurovaRecallEngine(memory_manager=self._memory_manager, max_workers=4, timeout_seconds=10.0, use_plugins=True, fusion_mode="legacy")
```

两处 bug 性质相同：调用方假设 `NeurovaRecallEngine` 接受多个依赖注入参数，但真实签名只接受 `memory_manager` 作为唯一注入点，其余依赖在引擎内部按需从 `memory_manager` 获取。

## Decision

**`memory_manager` 是 `NeurovaRecallEngine` 的唯一依赖注入点**。

所有外部依赖（storage / temperature_engine / emotion_analyzer / tkg / vector_search / config）通过 `memory_manager` 属性链访问：
- `memory_manager.storage` → 持久化层
- `memory_manager.temperature_engine` → 温度引擎
- `memory_manager.emotion_analyzer` → 情感分析（可选）
- `memory_manager.tkg` → 时序知识图谱（可选）
- `memory_manager.vector_search` → 向量搜索（可选）

**构造参数仅保留可调优项**：
- `max_workers` / `timeout_seconds` — 并行控制
- `intent_detector` / `intent_strategy` — 意图识别（可选，默认自动创建）
- `use_plugins` / `registry` — 插件化通道
- `fusion_mode` / `density_scale` — 融合模式（legacy / nerf）

## Consequences

**正向**：
- 接口表面小（1 个必填 + 8 个可选），符合深度模块原则
- 调用方无需了解引擎内部依赖图，只需传 `memory_manager`
- 测试 mock 简化：只需 mock `memory_manager`，无需 mock 6 个独立依赖

**负向**：
- `memory_manager` 成为上帝对象（god object），承载所有依赖
- 引擎内部访问 `memory_manager.xxx` 链式调用，若 `memory_manager` 未初始化某属性会抛 AttributeError（接受：用 try/except 降级处理）

**验证**：
- `tests/unit/cognitive_layers/memory_layer/test_neurova_recall_engine_init.py` 3/3 GREEN（Bug 9 签名验证）
- `tests/unit/cognitive_layers/memory_layer/test_channel_text_scoring.py` 2/2 GREEN（Bug 13/14 修复后引擎可正常创建）
- 246/246 全量 GREEN 零回归

## References

- [ADR 0003: 记忆系统架构](./0003-memory-system-architecture.md)
- Bug 9 修复：[mem_core.py:381](file:///e:/项目/Neurova/neurova/mem_core.py#L381)（4B.3）
- Bug 14 修复：[memory_layer.py:170](file:///e:/项目/Neurova/neurova/cognitive_layers/memory_layer/memory_layer.py#L170)（3D.4）
- 实现位置：`neurova/cognitive_layers/memory_layer/neurova_recall.py:504-540`
