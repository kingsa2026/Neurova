# 认知图谱存储架构设计文档（一步到位方案）

## 概述

认知图谱存储架构是 Neurova 记忆系统的统一替换方案，采用 LSM-Tree 五层架构替代原有的分散式记忆管理（mem_core.py + conversation_buffer.py + unified_vector_store.py）。

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent Core (agent_core.py)               │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ UnifiedRetriever │  │ PatternCrystallizer │  │ ReasoningTraceManager │  │
│  └──────┬──────┘  └──────┬───────┘  └────────┬───────────┘  │
│         │                │                    │              │
│  ┌──────▼────────────────▼────────────────────▼───────────┐  │
│  │           CognitiveStorageEngine (统一存储)              │  │
│  │  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐       │  │
│  │  │L0 WAL │→│L1 SQLite│→│L2 JSON │→│L3 压缩 │→│L4 结晶││  │
│  │  └────────┘  └────────┘  └────────┘  └────────┘       │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │           SleepConsolidationAdapter (睡眠整合)          │  │
│  │  SleepConsolidation ←→ CognitiveStorageEngine          │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 核心模块

### 1. CognitiveStorageEngine — 统一存储引擎

**文件**: `neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py`

LSM-Tree 五层架构的统一存储引擎，替代原有的三个独立存储模块。

**层级设计**:
| 层级 | 介质 | 生命周期 | 用途 |
|------|------|----------|------|
| L0 Buffer | 内存 + WAL JSONL | 秒级 | 写入缓冲，崩溃恢复 |
| L1 Hot | SQLite FTS5 | 分钟级 | 热数据检索 |
| L2 Warm | JSON | 小时级 | NeurovaHebb 专用 |
| L3 Cold | 压缩 | 天级 | 冷数据归档 |
| L4 Crystal | 永久 | 结晶经验 | PatternCrystallizer 产物 |

**关键特性**:
- **WAL 崩溃恢复**: 写入先到 WAL 文件，重启后自动恢复
- **自动 flush**: L0 缓冲区满（100条）自动写入 L1 SQLite
- **FTS5 全文检索**: L1 层支持中文全文检索
- **过滤器**: 支持 memory_type 和 category 过滤

**使用示例**:
```python
from neurova.cognitive_layers.memory_layer import CognitiveStorageEngine, UnifiedMemoryNode

engine = CognitiveStorageEngine(agent_id="my_agent", data_dir="data/my_agent")

# 存储
node = UnifiedMemoryNode(content="Python 文件操作", temperature=80.0)
engine.store(node)

# 检索
results = engine.retrieve("Python", limit=10, filters={"memory_type": "semantic"})
```

### 2. UnifiedMemoryNode — 统一记忆节点

所有记忆类型的唯一数据模型，温度范围 **0-100**（统一后）。

**字段**:
| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| id | str | UUID | 唯一标识 |
| content | str | "" | 记忆内容 |
| memory_type | MemoryType | SEMANTIC | 记忆类型 |
| category | str | "general" | 分类 |
| temperature | float | 100.0 | 温度（0-100） |
| layer | StorageLayer | L1_HOT | 存储层级 |
| metadata | dict | {} | 元数据 |
| embedding | list | None | 向量嵌入 |
| access_count | int | 0 | 访问计数 |
| trace_id | str | None | 推理链溯源 |

**温度操作**:
- `touch()`: 访问一次，温度 +10（上限 100）
- `decay(hours, rate)`: 温度衰减，默认 rate=1.0

### 3. PatternCrystallizer — 经验结晶器

基于 Hebb 学习规则的经验结晶器，不调用 LLM，成本降 97%。

**结晶条件**: 同一模式观察 ≥3 次，成功率 >60%

**输出**: PATTERN 类型记忆节点，温度 = 成功率 × 100

### 4. UnifiedRetriever — 统一检索器

替代 MoE + RecallEngine + HebbManager 三路并行检索。

**特性**:
- 新数据直接使用 CognitiveStorageEngine
- 旧数据兼容（迁移期间）
- 自动去重 + 按温度排序

### 5. ReasoningTraceManager — 推理链管理器

记录完整推理过程，存储为可检索的 EPISODIC 记忆。

### 6. SleepConsolidationAdapter — 睡眠整合适配器

桥接 SleepConsolidation（MemoryRecord）和 CognitiveStorageEngine（UnifiedMemoryNode）。

**功能**:
- 从引擎读取记忆 → 转为 MemoryRecord
- 运行整合（聚类、合并、衰减）
- 将结果写回引擎

### 7. TemperatureEngine — 温度引擎

实现贝叶斯遗忘曲线和生命周期管理。

**温度范围**: 0-100（统一后）

**生命周期阶段**:
| 阶段 | 温度范围 | 说明 |
|------|----------|------|
| active | ≥60 | 活跃记忆 |
| secondary | 20-59 | 次要记忆 |
| archived | 5-19 | 归档记忆 |
| deleted | <5 | 待删除 |

## 温度系统统一（0-100）

所有温度相关模块已统一为 0-100 范围：

| 模块 | 修改前 | 修改后 |
|------|--------|--------|
| CognitiveStorageEngine | 0-1 | 0-100 |
| PatternCrystallizer | 0-1 (rate) | 0-100 (rate×100) |
| ReasoningTraceManager | 1.0 | 100.0 |
| SleepConsolidation | 0-100 (已正确) | 0-100 |
| TemperatureEngine | 0-100 (已正确) | 0-100 |
| API endpoints | fallback 1.0 | fallback 100.0 |

## 测试覆盖

| 测试文件 | 测试数 | 覆盖范围 |
|----------|--------|----------|
| test_cognitive_storage_engine.py | 15 | 存储引擎基础功能 |
| test_pattern_crystallizer.py | 17 | 经验结晶器 |
| test_unified_retriever.py | 15 | 统一检索器 |
| test_reasoning_trace_manager.py | 15 | 推理链管理器 |
| test_context_orchestrator_crystallized.py | 6 | 上下文编排器集成 |
| test_cognitive_graph_integration.py | 15 | 集成测试+回归测试 |
| **总计** | **83** | |

## 集成点

### Agent Core 集成

在 `agent_core.py` 的 `__init__()` 中初始化：
```python
self.storage_engine = CognitiveStorageEngine(agent_id=self.agent_id)
self.pattern_crystallizer = PatternCrystallizer(engine=self.storage_engine)
self.unified_retriever = UnifiedRetriever(engine=self.storage_engine)
self.reasoning_trace = ReasoningTraceManager(engine=self.storage_engine)
```

在 `chat()` 方法中使用：
1. 检索结晶经验 → 注入上下文
2. 异步生成推理记忆
3. 观察工具使用模式

### ContextOrchestrator 集成

`build_context()` 方法支持 `crystallized_patterns` 参数，优先级 80（高于普通经验 70）。

## 文件清单

| 文件 | 行数 | 说明 |
|------|------|------|
| cognitive_storage_engine.py | ~410 | 统一存储引擎 |
| pattern_crystallizer.py | ~180 | 经验结晶器 |
| unified_retriever.py | ~155 | 统一检索器 |
| reasoning_trace_manager.py | ~195 | 推理链管理器 |
| sleep_adapter.py | ~170 | 睡眠整合适配器 |
| temperature.py | ~240 | 温度引擎 |
| sleep.py | ~275 | 睡眠整合核心 |
