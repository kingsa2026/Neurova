# 认知图谱存储架构 — 一步到位设计文档

> **版本:** 2.0 | **日期:** 2026-06-04 | **策略:** 直接替换，无兼容层

## 1. 为什么要一步到位

| 三阶段迁移 | 一步到位 |
|-----------|---------|
| 维护两套存储 = 2倍代码 | 只有新代码 |
| MemoryBridge 临时模块 | 不需要 |
| 每阶段验证一致性 | 一次验证 |
| 5周完成 | 2周完成 |
| 适合线上有用户 | **开发版本，无用户** |

**结论：** 直接替换，删除旧代码，不保留兼容层。

---

## 2. 替换映射表

| 旧模块 | 行数 | 动作 | 新模块 | 行数 |
|--------|------|------|--------|------|
| `mem_core.py` (MemCore门面) | 635 | **重写** | `cognitive_storage_engine.py` | ~400 |
| `conversation_buffer.py` | 434 | **合并** | → L0 Buffer 层 | 0 (内嵌) |
| `unified_vector_store.py` | 235 | **合并** | → 内存向量索引 | 0 (内嵌) |
| `moe_router.py` | 481 | **包装** | `unified_retriever.py` | ~200 |
| `neurova_recall.py` | 757 | **包装** | → UnifiedRetriever 内部 | 0 (内嵌) |
| `neuHebb_manager.py` | 406 | **包装** | → UnifiedRetriever 内部 | 0 (内嵌) |
| `tool_memory_integration.py` | 84(stub) | **实现** | → CognitiveStorageEngine 直接调用 | 0 |
| `experience_caller.py` | 75(stub) | **实现** | `pattern_crystallizer.py` | ~250 |
| `cache.py` | 157(stub) | **删除** | 不需要 | 0 |
| `working_memory.py` | 169(stub) | **删除** | 不需要 | 0 |

**净效果：** 删除 ~2800 行旧代码，新增 ~850 行新代码

---

## 3. 新模块架构

```
neurova/cognitive_layers/memory_layer/
├── cognitive_storage_engine.py   # 新：统一存储引擎（L0-L4）
├── unified_retriever.py          # 新：统一检索器
├── pattern_crystallizer.py       # 新：经验结晶器
├── reasoning_trace_manager.py    # 新：推理链管理
│
├── neurova_hebb.py               # 保留（数据模型）
├── neuHebb_forge.py              # 保留（生成器）
├── neuHebb_curator.py            # 保留（检索器）
├── temperature.py                # 保留（但温度改为0-1）
├── sleep.py                      # 保留（对接新存储）
├── schema.py                     # 保留（数据模型）
│
├── moe_router.py                 # 删除（功能合并到 UnifiedRetriever）
├── neurova_recall.py             # 删除（功能合并到 UnifiedRetriever）
├── neuHebb_manager.py            # 删除（功能合并到 UnifiedRetriever）
├── conversation_buffer.py        # 删除（功能合并到 L0 Buffer）
├── unified_vector_store.py       # 删除（功能合并到内存索引）
├── tool_memory_integration.py    # 删除（直接用 CognitiveStorageEngine）
├── cache.py                      # 删除（不需要）
├── working_memory.py             # 删除（不需要）
└── conflict_detector_v2.py       # 保留（独立功能）
```

---

## 4. CognitiveStorageEngine 详细设计

### 4.1 核心数据模型

```python
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import uuid

class MemoryType(Enum):
    EPISODIC = "episodic"      # 事件记忆
    SEMANTIC = "semantic"      # 语义知识
    PROCEDURAL = "procedural"  # 程序性知识（工具使用）
    PATTERN = "pattern"        # 结晶经验
    TOOL_MEMORY = "tool_memory" # 工具记忆

class StorageLayer(Enum):
    L0_BUFFER = 0    # WAL 缓冲区（秒级）
    L1_HOT = 1       # SQLite 热存储（分钟级）
    L2_WARM = 2      # JSON 温存储（小时级）
    L3_COLD = 3      # 压缩冷存储（天级）
    L4_CRYSTAL = 4   # 结晶经验（永久）

@dataclass
class UnifiedMemoryNode:
    """统一记忆节点 — 所有记忆类型的唯一数据模型"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    memory_type: MemoryType = MemoryType.SEMANTIC
    category: str = "general"
    temperature: float = 1.0          # 0-1 scale，统一
    layer: StorageLayer = StorageLayer.L1_HOT
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    access_count: int = 0
    trace_id: Optional[str] = None    # 推理链溯源

    def touch(self):
        """访问一次，温度升高"""
        self.access_count += 1
        self.temperature = min(1.0, self.temperature + 0.1)
        self.updated_at = datetime.now(timezone.utc)

    def decay(self, hours: float = 1.0, rate: float = 0.01):
        """温度衰减"""
        self.temperature = max(0.0, self.temperature - rate * hours)
```

### 4.2 存储引擎

```python
class CognitiveStorageEngine:
    """统一存储引擎 — LSM-Tree 五层架构"""

    def __init__(self, agent_id: str, data_dir: str = None):
        self.agent_id = agent_id
        self.data_dir = Path(data_dir or f"data/{agent_id}")

        # L0: WAL 缓冲区（内存 + 文件）
        self._l0_buffer: List[UnifiedMemoryNode] = []
        self._wal_path = self.data_dir / "wal.jsonl"

        # L1: SQLite 热存储
        self._db_path = self.data_dir / "memory.db"
        self._init_db()

        # L2: JSON 温存储（NeurovaHebb 专用）
        self._hebb_path = self.data_dir / "hebb_store.json"

        # 内存向量索引
        self._vector_index: Dict[str, List[float]] = {}
        self._embed_fn = None  # 延迟初始化

        # 自动迁移定时器
        self._last_migration = datetime.now(timezone.utc)

    def store(self, node: UnifiedMemoryNode) -> str:
        """写入记忆节点"""
        # 1. 写 WAL（崩溃恢复）
        self._wal_append(node)

        # 2. 写 L0 缓冲
        self._l0_buffer.append(node)

        # 3. 更新向量索引
        if node.embedding:
            self._vector_index[node.id] = node.embedding

        # 4. L0 满了就 flush 到 L1
        if len(self._l0_buffer) >= 100:
            self._flush_l0_to_l1()

        return node.id

    def retrieve(self, query: str, limit: int = 10,
                 filters: Dict = None) -> List[UnifiedMemoryNode]:
        """跨层检索"""
        results = []

        # 1. L0 缓冲搜索（精确匹配）
        results.extend(self._search_l0(query, filters))

        # 2. L1 SQLite 搜索（结构化查询）
        results.extend(self._search_l1(query, limit, filters))

        # 3. L2 JSON 搜索（NeurovaHebb）
        if filters and filters.get('memory_type') in ('neurova_hebb', None):
            results.extend(self._search_l2(query, limit))

        # 4. 向量相似度排序
        if self._embed_fn and results:
            results = self._vector_rank(query, results, limit)
        else:
            results.sort(key=lambda n: n.temperature, reverse=True)

        return results[:limit]

    def update_temperature(self, node_id: str, delta: float) -> None:
        """更新温度"""
        # 先查 L0
        for node in self._l0_buffer:
            if node.id == node_id:
                node.temperature = max(0.0, min(1.0, node.temperature + delta))
                return
        # 再查 L1
        self._db.execute(
            "UPDATE memories SET temperature = MAX(0, MIN(1, temperature + ?)) WHERE id = ?",
            (delta, node_id)
        )

    def auto_migrate(self) -> Dict[str, int]:
        """自动层间迁移（温度驱动）"""
        # L1 → L3: 温度 < 0.1 的冷数据
        cold = self._db.execute(
            "SELECT id FROM memories WHERE temperature < 0.1"
        ).fetchall()
        # ... 压缩并移动到 L3

        # L3 → L4: 高频访问的模式数据
        # ... 结晶到 L4

        return {"migrated": len(cold)}

    def get_statistics(self) -> Dict[str, Any]:
        """各层统计"""
        l0_count = len(self._l0_buffer)
        l1_count = self._db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        return {
            "l0_buffer": l0_count,
            "l1_hot": l1_count,
            "vector_index_size": len(self._vector_index),
        }
```

---

## 5. UnifiedRetriever 详细设计

```python
class UnifiedRetriever:
    """统一检索器 — 替代 MoE + RecallEngine + HebbManager 三路并行"""

    def __init__(self, engine: CognitiveStorageEngine,
                 moe_router=None, recall_engine=None, hebb_manager=None):
        self.engine = engine
        # 保留旧检索器作为子组件（包装而非重写）
        self._moe = moe_router
        self._recall = recall_engine
        self._hebb = hebb_manager

    def retrieve(self, query: str, limit: int = 10,
                 include_patterns: bool = True) -> List[Dict]:
        """统一检索入口"""
        results = []

        # 方案A：直接用 CognitiveStorageEngine（新数据）
        engine_results = self.engine.retrieve(query, limit=limit)
        results.extend([self._node_to_dict(n) for n in engine_results])

        # 方案B：兼容旧检索器（迁移期间）
        if self._moe:
            moe_results = self._moe.retrieve(query)
            results.extend(moe_results)
        if self._recall:
            recall_results = self._recall.recall_flat(query, limit=limit)
            results.extend(recall_results)
        if self._hebb:
            hebbs = self._hebb.retrieve_neurova_hebb(query)
            results.extend([self._hebb.convert_to_recall_format(h) for h in hebbs])

        # 去重 + 排序
        return self._dedup_rank(results, limit)

    def _node_to_dict(self, node: UnifiedMemoryNode) -> Dict:
        return {
            'id': node.id,
            'content': node.content,
            'score': node.temperature,
            'source': node.memory_type.value,
            'temperature': node.temperature,
            'category': node.category,
            'metadata': node.metadata,
        }

    def _dedup_rank(self, results, limit):
        seen, unique = set(), []
        for r in results:
            key = r.get('content', '')[:100]
            if key not in seen:
                seen.add(key)
                unique.append(r)
        unique.sort(key=lambda x: x.get('score', 0), reverse=True)
        return unique[:limit]
```

---

## 6. PatternCrystallizer 详细设计

```python
class PatternCrystallizer:
    """经验结晶器 — Hebb 学习替代 LLM 调用"""

    def __init__(self, engine: CognitiveStorageEngine,
                 evolution_orchestrator=None):
        self.engine = engine
        self.evolution = evolution_orchestrator
        self._buffer: Dict[str, List[Dict]] = {}

    def observe(self, tool_name: str, context: str,
                success: bool, result: Any = None):
        """观察工具使用"""
        key = self._extract_pattern_key(context)
        self._buffer.setdefault(key, []).append({
            'tool': tool_name, 'success': success,
            'context': context[:200],
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        if len(self._buffer[key]) >= 3:
            self._try_crystallize(key)

    def _try_crystallize(self, key: str):
        entries = self._buffer[key]
        rate = sum(1 for e in entries if e['success']) / len(entries)
        if rate < 0.6:
            return

        tool = max(set(e['tool'] for e in entries),
                   key=lambda t: sum(1 for e in entries if e['tool'] == t))

        node = UnifiedMemoryNode(
            content=f"模式: '{key}' 类任务用 {tool} 成功率 {rate:.0%}",
            memory_type=MemoryType.PATTERN,
            category="crystallized",
            temperature=rate,  # 成功率即温度
            metadata={
                'pattern_key': key, 'primary_tool': tool,
                'success_rate': rate, 'sample_count': len(entries),
            },
        )
        self.engine.store(node)
        del self._buffer[key]

        if self.evolution:
            self.evolution.on_experience_recorded(
                node.content, key, [tool], True)

    def retrieve(self, query: str, limit: int = 5) -> List[Dict]:
        """检索结晶经验"""
        nodes = self.engine.retrieve(query, limit=limit,
            filters={'memory_type': 'pattern'})
        return [{
            'id': n.id, 'content': n.content,
            'method': n.metadata.get('primary_tool', ''),
            'confidence': n.metadata.get('success_rate', 0),
            'score': n.temperature, 'source': 'crystallized',
        } for n in nodes]

    def _extract_pattern_key(self, context: str) -> str:
        """提取模式关键词"""
        # 简单实现：取前50字符作为模式标识
        return context[:50].strip()
```

---

## 7. ReasoningTraceManager 详细设计

```python
@dataclass
class ReasoningStep:
    step_id: str
    action: str           # "retrieve" | "crystallize" | "llm_call" | "tool_call"
    input_summary: str
    output_summary: str
    memory_ids: List[str] # 引用的记忆节点ID
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class ReasoningTrace:
    trace_id: str
    query: str
    steps: List[ReasoningStep]
    final_answer: str
    total_tokens: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class ReasoningTraceManager:
    """推理链管理器 — 记录完整推理过程"""

    def __init__(self, engine: CognitiveStorageEngine):
        self.engine = engine
        self._active_traces: Dict[str, ReasoningTrace] = {}

    def start_trace(self, query: str) -> str:
        """开始一条推理链"""
        trace_id = str(uuid.uuid4())
        self._active_traces[trace_id] = ReasoningTrace(
            trace_id=trace_id, query=query,
            steps=[], final_answer="",
        )
        return trace_id

    def add_step(self, trace_id: str, action: str,
                 input_summary: str, output_summary: str,
                 memory_ids: List[str] = None):
        """添加推理步骤"""
        trace = self._active_traces.get(trace_id)
        if not trace: return
        step = ReasoningStep(
            step_id=str(uuid.uuid4()),
            action=action,
            input_summary=input_summary[:200],
            output_summary=output_summary[:200],
            memory_ids=memory_ids or [],
        )
        trace.steps.append(step)

    def finish_trace(self, trace_id: str, final_answer: str,
                     total_tokens: int = 0):
        """完成推理链，存储为记忆"""
        trace = self._active_traces.pop(trace_id, None)
        if not trace: return

        trace.final_answer = final_answer[:500]
        trace.total_tokens = total_tokens

        # 存储为记忆节点（可被检索）
        node = UnifiedMemoryNode(
            content=f"推理链: {trace.query} → {trace.final_answer}",
            memory_type=MemoryType.EPISODIC,
            category="reasoning_trace",
            temperature=1.0,
            trace_id=trace_id,
            metadata={
                'steps_count': len(trace.steps),
                'actions': [s.action for s in trace.steps],
                'memory_ids': [mid for s in trace.steps for mid in s.memory_ids],
                'total_tokens': total_tokens,
            },
        )
        self.engine.store(node)

    def get_recent_traces(self, limit: int = 10) -> List[Dict]:
        """获取最近的推理链"""
        nodes = self.engine.retrieve("", limit=limit,
            filters={'category': 'reasoning_trace'})
        return [{
            'trace_id': n.trace_id,
            'content': n.content,
            'steps_count': n.metadata.get('steps_count', 0),
            'created_at': n.created_at.isoformat(),
        } for n in nodes]
```

---

## 8. agent_core.py 改造方案

### 8.1 __init__ 改造

```python
# 删除
from neurova.mem_core import MemCore
# 新增
from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager

class Agent:
    def __init__(self, ...):
        # 删除: self.memory_agent = MemCore(self)
        # 新增:
        self.cognitive_engine = CognitiveStorageEngine(
            agent_id=self.config.agent_id,
            data_dir=f"data/{self.config.agent_id}",
        )
        self.unified_retriever = UnifiedRetriever(
            engine=self.cognitive_engine,
            moe_router=self._moe_router,  # 迁移期间保留
        )
        self.crystallizer = PatternCrystallizer(
            engine=self.cognitive_engine,
            evolution_orchestrator=self.evolution,
        )
        self.trace_manager = ReasoningTraceManager(
            engine=self.cognitive_engine,
        )
```

### 8.2 chat() 改造

```python
async def chat(self, user_input: str, ...):
    # 步骤0: ToolMemory 检查 — 不变
    # 步骤0.1: 技能获取 — 不变

    # 步骤0.5+1: 统一检索（替换 moe_retrieve）
    trace_id = self.trace_manager.start_trace(user_input)
    relevant_memories = self.unified_retriever.retrieve(
        user_input, limit=10, include_patterns=True)
    self.trace_manager.add_step(trace_id, "retrieve",
        user_input, f"找到 {len(relevant_memories)} 条记忆")

    # 步骤2-5: 构建上下文（注入结晶经验）
    crystallized = self.crystallizer.retrieve(user_input, limit=3)
    context = await self.context_orchestrator.build_context(
        user_input=user_input,
        tool_memory_result=tool_memory_result,
        relevant_memories=relevant_memories,
        crystallized_patterns=crystallized,  # 新增参数
        # ... 其他参数不变
    )

    # 步骤5: LLM 调用 — 不变
    reply = await self.loop.predict_step(messages=context, tools=tools_for_llm)

    # 步骤6-9: 后处理
    # 新增: 记录推理链
    self.trace_manager.finish_trace(trace_id, reply, total_tokens=used_tokens)

    # 新增: 结晶器观察
    if tool_used:
        self.crystallizer.observe(tool_name, user_input, success)

    return reply
```

---

## 9. 删除清单

| 文件 | 原因 |
|------|------|
| `neurova/cognitive_layers/memory_layer/cache.py` | stub，功能合并到 L0 |
| `neurova/cognitive_layers/memory_layer/working_memory.py` | stub，功能合并到 L0 |
| `neurova/cognitive_layers/memory_layer/tool_memory_integration.py` | stub，直接用 engine |
| `neurova/evolution/experience_caller.py` | stub，被 PatternCrystallizer 替代 |

**保留但需修改：**

| 文件 | 修改内容 |
|------|----------|
| `neurova/cognitive_layers/memory_layer/__init__.py` | 更新导出 |
| `neurova/cognitive_layers/memory_layer/temperature.py` | 温度改为 0-1 scale |
| `neurova/cognitive_layers/memory_layer/sleep.py` | 对接 CognitiveStorageEngine |
| `neurova/agent_core.py` | 重写初始化和 chat() |
| `neurova/mem_core.py` | 删除或重写为 thin wrapper |

---

## 10. 实施计划（2周）

| 天数 | 任务 | 产出 |
|------|------|------|
| D1 | 实现 UnifiedMemoryNode + CognitiveStorageEngine 核心 | 存储引擎可读写 |
| D2 | 实现 L0 Buffer + L1 SQLite + WAL | 崩溃恢复可用 |
| D3 | 实现内存向量索引 + 跨层检索 | 检索可用 |
| D4 | 实现 UnifiedRetriever（包装旧检索器） | 统一检索可用 |
| D5 | 实现 PatternCrystallizer | 经验结晶可用 |
| D6 | 实现 ReasoningTraceManager | 推理链可用 |
| D7 | 改造 agent_core.py 初始化 | Agent 可启动 |
| D8 | 改造 chat() 流程 | 对话可用 |
| D9 | 改造 ContextOrchestrator.build_context() | 上下文注入可用 |
| D10 | 集成测试 + 修复回归 | 所有测试通过 |
| D11 | 删除旧代码（cache/working_memory/tool_memory_integration） | 代码清理 |
| D12 | 温度系统统一（0-1） | 一致性 |
| D13 | SleepConsolidation 对接新存储 | 睡眠整理可用 |
| D14 | 文档 + 最终测试 | 完成 |

---

## 11. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 向量索引内存占用过大 | 中 | 低 | 限制索引大小，LRU 淘汰 |
| SQLite 并发写入冲突 | 低 | 中 | WAL 模式 + RLock |
| 旧检索器包装性能下降 | 低 | 低 | 统一检索器内部并行 |
| 温度统一后行为变化 | 中 | 低 | 调整衰减参数 |

---

## 12. 关键设计决策

1. **温度统一为 0-1** — 与 NeurovaHebb 一致，避免转换
2. **WAL 崩溃恢复** — L0 缓冲区写前日志，保证数据不丢
3. **向量索引纯内存** — 开发阶段够用，后续可换 FAISS
4. **PatternCrystallizer 用 Hebb 学习** — 不调 LLM，成本降 97%
5. **推理链存储为记忆** — 可被检索，类似问题可参照
6. **旧检索器保留为子组件** — 包装而非重写，降低风险

---

## 13. 与现有模块的集成点

```
Agent.__init__()
├── CognitiveStorageEngine (新建) ← 替代 MemCore
├── UnifiedRetriever (新建) ← 包装 MoE + Recall + Hebb
├── PatternCrystallizer (新建) ← 替代 ExperienceCaller
├── ReasoningTraceManager (新建)
│
├── EvolutionOrchestrator (增强) ← 注入 crystallizer
├── ContextOrchestrator (增强) ← 注入结晶经验和推理链
├── ContextPool (增强) ← 新增 ContextSource 枚举值
└── ToolExecutor (不变) ← 通过 crystallizer.observe() 间接对接
```
