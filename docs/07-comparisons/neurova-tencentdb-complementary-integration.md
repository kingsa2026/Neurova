# Neurova 记忆系统架构深度化方案

## 核心理念

**系统级整合，而非单点升级**。基于 TencentDB-Agent-Memory 设计理念，解决 3 个架构摩擦点，实现 5 项深度化机会。

---

## 架构摩擦点（必须先解决）

### 摩擦点 1：MemoryRecord 碎片化

**问题**: `storage.py`、`sleep.py`、`models.py` 三个 MemoryRecord 定义不一致

**解决方案**: 统一 MemoryRecord + Adapter

```python
# neurova/cognitive_layers/memory_layer/models.py
@dataclass
class MemoryRecord:
    """统一记忆记录 — 所有模块使用此定义"""
    id: str = ""
    content: str = ""
    memory_type: MemoryType = MemoryType.EPISODIC
    temperature: float = 50.0
    importance: float = 0.5
    emotion_score: float = 0.0
    # ... 其他字段
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MemoryRecord":
        """兼容旧格式自动转换"""
        pass

class MemoryAdapter:
    """记忆适配器 — 自动转换旧格式"""
    @staticmethod
    def from_storage(data: Dict) -> MemoryRecord: pass
    @staticmethod
    def from_sleep(data: Dict) -> MemoryRecord: pass
```

### 摩擦点 2：检索系统碎片化

**问题**: `enhanced_retrieval.py`、`moe_router.py`、`neurova_recall.py` 三个检索系统并存

**解决方案**: 统一检索引擎

```python
# neurova/cognitive_layers/memory_layer/unified_retriever.py
class UnifiedRetriever:
    """统一检索引擎 — 小接口，深实现"""
    
    def retrieve(self, query: str, strategy: str = "auto", top_k: int = 10) -> RetrievalResult:
        """统一检索入口"""
        if strategy == "auto":
            strategy = self._select_strategy(query)
        return self._retrievers[strategy].retrieve(query, top_k)
```

### 摩擦点 3：工具记忆分散

**问题**: `muscle_memory.py`、`tool_memory_integration.py`、`pattern_crystallizer.py` 职责重叠

**解决方案**: 统一工具记忆引擎

```python
# neurova/cognitive_layers/memory_layer/tool_memory_engine.py
class ToolMemoryEngine:
    """统一工具记忆引擎 — record/match/crystallize"""
    
    def record(self, tool: str, query: str, params: Dict, success: bool): pass
    def match(self, query: str) -> Optional[ToolMemoryItem]: pass
```

---

## 深度化机会（系统级整合）

### 机会 1：符号记忆层（Token 减少 60-80%）

```python
# neurova/cognitive_layers/memory_layer/symbolic_memory.py
class SymbolicMemoryManager:
    def create_canvas(title) -> SymbolicCanvas
    def add_tool_call(canvas_id, tool, params, success, result)
    def finalize(canvas_id) -> str  # 返回 Mermaid 文本
```

**集成点**: `agent_core.py` chat() 工具调用后生成画布，注入上下文时用符号图替代原始日志

### 机会 2：渐进式摘要管线（检索准确率提升 20-30%）

```python
# neurova/cognitive_layers/memory_layer/progressive_summarizer.py
class ProgressiveSummarizer:
    def extract_facts(conv_id) -> List[AtomFact]  # L0→L1
    def build_scenarios() -> List[Scenario]        # L1→L2
    def build_profile(user_id) -> UserProfile      # L2→L3
```

**集成点**: `SleepConsolidation` 睡眠时调用，摘要存入 L4 Crystal

### 机会 3：RRF 多源融合检索（召回率提升 15-25%）

```python
# neurova/cognitive_layers/memory_layer/hybrid_retriever.py
class HybridRetriever:
    def retrieve(query, docs, vector_fn, top_k) -> List[FusedResult]
```

**集成点**: `MoEMemoryRouter` L3 兜底层增加 BM25 检索并用 RRF 融合

### 机会 4：技能生成器（重复任务效率提升 50%+）

```python
# neurova/cognitive_layers/memory_layer/skill_generator.py
class SkillGenerator:
    def record(trajectory_id, calls: List[Dict])
    def match(tools: List[str]) -> Optional[Skill]
```

**集成点**: chat() 工具调用后 `record()`；工具选择前 `match()` 检查可复用技能

### 机会 5：白盒可调试性（调试效率提升 80%）

```python
# neurova/cognitive_layers/memory_layer/debug_tracer.py
class DebugTracer:
    def start_trace(query) -> str
    def add_stage(stage: RetrievalStage)
    def end_trace(latency_ms)
```

**集成点**: `UnifiedRetriever` 检索时自动追踪每个阶段

---

## 系统级整合架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Neurova Agent Core                        │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  Symbolic   │  │ Progressive │  │  Unified    │         │
│  │   Memory    │  │  Summarizer │  │ Retriever   │         │
│  │   Layer     │  │   Pipeline  │  │ (RRF融合)   │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                   │
│         └────────────────┼────────────────┘                   │
│                          │                                    │
│  ┌─────────────┐  ┌─────┴───────┐  ┌─────────────┐         │
│  │   Skill     │  │   Debug     │  │  Unified    │         │
│  │  Generator  │  │   Tracer    │  │MemoryRecord │         │
│  │             │  │             │  │  + Adapter  │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                   │
│         └────────────────┼────────────────┘                   │
│                          │                                    │
│                   ┌──────┴──────┐                            │
│                   │  ToolMemory │                            │
│                   │   Engine    │                            │
│                   └─────────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

## 实施路线图

| 阶段 | 内容 | 工作量 | 收益 |
|------|------|--------|------|
| **Phase 1** | 统一 MemoryRecord + 检索引擎 | 3天 | 消除架构摩擦点 |
| **Phase 2** | RRF 多源融合检索 | 2天 | 召回率提升 15-25% |
| **Phase 3** | 渐进式摘要管线 | 3天 | 检索准确率提升 20-30% |
| **Phase 4** | 符号记忆 + 技能生成 + 白盒调试 | 2天 | Token减少60-80%，效率提升50%+ |

**总计**: 10天 | **系统级收益**: 架构深度化，模块耦合度降低 60%，测试覆盖率提升 25%

---

## 附录：与 TencentDB 的核心差异

| 维度 | TencentDB | Neurova | 本次升级后 |
|------|-----------|---------|------------|
| 记忆层次 | 4层金字塔 | 5层LSM-Tree | 5层 + L0→L3 管线 |
| 路由机制 | BM25+Vector 平铺 | MoE 稀疏门控 | MoE + RRF 融合 |
| 检索系统 | 统一 | 3个碎片化 | 统一检索引擎 |
| 工具记忆 | 轨迹→SOP | 3个分散模块 | 统一工具记忆引擎 |
| 可调试性 | 全链路追踪 | 无 | DebugTracer |

**结论**: 通过系统级深度化，Neurova 将补齐架构短板，同时保持情感记忆、睡眠整合、MoE 路由的独特优势。