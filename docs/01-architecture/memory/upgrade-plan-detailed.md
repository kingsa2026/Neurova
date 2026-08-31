# Neurova 记忆系统升级方案（详细版）

## 1. 升级概述

基于 MAGMA 论文对比分析，识别出 3 个关键改进机会。

## 2. 候选 1：增强图能力

### 2.1 问题分析
- 当前：7 种关系类型，无法支持复杂推理
- 目标：20+ 种关系类型，支持因果推理和多跳分解

### 2.2 详细任务

#### 任务 1.1：扩展关系类型（2小时）
**文件**：`neurova/cognitive_layers/memory_layer/graph_traversal.py`

**修改**：扩展 `RELATION_WEIGHTS` 字典
```python
RELATION_WEIGHTS = {
    # 现有类型
    "related": 0.5, "causes": 0.8, "contradicts": 0.6,
    "supports": 0.9, "part_of": 0.7, "derived_from": 0.8, "temporal": 0.4,
    
    # 新增因果关系
    "caused_by": 0.9, "enables": 0.7, "enabled_by": 0.7,
    "prevents": 0.8, "prevented_by": 0.8, "requires": 0.6,
    
    # 新增演化关系
    "evolves_to": 0.8, "evolved_from": 0.8, "replaces": 0.7,
    "replaced_by": 0.7, "version_of": 0.6,
    
    # 新增层次关系
    "part_of_hierarchy": 0.5, "contains": 0.5,
    "instance_of": 0.6, "type_of": 0.6,
    
    # 新增语义关系
    "synonym": 0.9, "antonym": 0.8, "hypernym": 0.7, "hyponym": 0.7,
}
```

**验收标准**：
1. 枚举值从 7 个扩展到 25 个
2. 每个关系类型都有对应的权重
3. 保持向后兼容

#### 任务 1.2：实现因果推理引擎（8小时）
**新建文件**：`neurova/cognitive_layers/memory_layer/causal_reasoning.py`

**功能**：
```python
class CausalReasoningEngine:
    def find_causal_chain(self, start_id: str, end_id: str) -> List[List[str]]
    def predict_effects(self, cause_id: str) -> List[Tuple[str, float]]
    def find_root_causes(self, effect_id: str) -> List[Tuple[str, float]]
    def explain_causality(self, cause_id: str, effect_id: str) -> str
```

**验收标准**：
1. 能够找到两个记忆之间的因果链
2. 能够预测某个原因的可能结果
3. 能够找到某个结果的根本原因
4. 能够生成因果关系的自然语言解释

#### 任务 1.3：实现问题分解器（6小时）
**新建文件**：`neurova/cognitive_layers/memory_layer/question_decomposer.py`

**功能**：
```python
class QuestionDecomposer:
    def decompose(self, question: str) -> List[str]
    def detect_question_type(self, question: str) -> str
    def plan_retrieval_strategy(self, sub_questions: List[str]) -> Dict
```

**验收标准**：
1. 能够将复杂问题分解为 2-4 个子问题
2. 能够检测问题类型
3. 能够为每个子问题规划检索策略

#### 任务 1.4：增强图遍历算法（6小时）
**修改文件**：`neurova/cognitive_layers/memory_layer/graph_traversal.py`

**新增方法**：
```python
class GraphTraversal:
    def probabilistic_beam_search(self, start_ids, query_vector, beam_width=3, max_depth=3)
    def compute_attention_weight(self, query_vector, node_vector, intent_weight=1.0)
    def get_adaptive_params(self, query_type: str) -> Dict
```

**验收标准**：
1. 实现概率束搜索算法
2. 支持意图感知的注意力权重计算
3. 支持自适应遍历参数

### 2.3 测试用例
```python
def test_relation_types_extended():
    weights = GraphTraversal.RELATION_WEIGHTS
    assert "causes" in weights
    assert "caused_by" in weights
    assert "enables" in weights
    for rel_type, weight in weights.items():
        assert 0.0 <= weight <= 1.0

def test_causal_chain_finding():
    engine = CausalReasoningEngine(graph_traversal)
    # 创建测试记忆和因果关系
    chains = engine.find_causal_chain(memory_a.id, memory_c.id)
    assert len(chains) > 0

def test_question_decomposition():
    decomposer = QuestionDecomposer(llm_client)
    sub_questions = decomposer.decompose("为什么用户流失率上升，如何解决？")
    assert len(sub_questions) >= 2
```

### 2.4 时间估算
| 任务 | 预计时间 | 依赖 |
|------|----------|------|
| 任务 1.1：扩展关系类型 | 2 小时 | 无 |
| 任务 1.2：因果推理引擎 | 8 小时 | 任务 1.1 |
| 任务 1.3：问题分解器 | 6 小时 | 无 |
| 任务 1.4：增强图遍历 | 6 小时 | 任务 1.1 |
| 测试编写 | 4 小时 | 所有任务 |
| **总计** | **26 小时** | |

## 3. 候选 2：实现意图感知检索

### 3.1 问题分析
- 当前：固定检索策略，无意图感知
- 目标：根据查询意图选择检索策略

### 3.2 详细任务

#### 任务 2.1：实现查询意图检测器（4小时）
**修改文件**：`neurova/cognitive_layers/memory_layer/neurova_recall.py`

**新增类**：
```python
class QueryIntentDetector:
    INTENT_KEYWORDS = {
        QueryIntent.TEMPORAL: ["when", "time", "date", "before", "after", "during", "recently", "lately"],
        QueryIntent.CAUSAL: ["why", "because", "cause", "reason", "result", "lead to", "due to"],
        QueryIntent.COMPARATIVE: ["compare", "difference", "vs", "versus", "better", "worse", "similar"],
        QueryIntent.EXPLORATORY: ["explore", "discover", "find", "search", "look for", "what", "how"],
    }
    
    def detect_intent(self, query: str) -> QueryIntent
    def get_intent_confidence(self, query: str, intent: QueryIntent) -> float
```

**验收标准**：
1. 能够检测 5 种查询意图
2. 每个意图都有对应的关键词列表
3. 返回置信度分数

#### 任务 2.2：实现意图特定的检索策略（4小时）
**修改文件**：`neurova/cognitive_layers/memory_layer/neurova_recall.py`

**新增类**：
```python
class IntentAwareRecallStrategy:
    INTENT_CHANNEL_WEIGHTS = {
        QueryIntent.FACTUAL: {RecallChannel.TEMPERATURE: 0.3, RecallChannel.TEXT: 0.5, ...},
        QueryIntent.TEMPORAL: {RecallChannel.TEMPERATURE: 0.6, RecallChannel.TEXT: 0.2, ...},
        QueryIntent.CAUSAL: {RecallChannel.GRAPH: 0.6, RecallChannel.TEXT: 0.2, ...},
        QueryIntent.COMPARATIVE: {RecallChannel.CATEGORY: 0.4, RecallChannel.TEXT: 0.3, ...},
        QueryIntent.EXPLORATORY: {RecallChannel.TEMPERATURE: 0.2, RecallChannel.TEXT: 0.3, ...},
    }
    
    INTENT_PARAMS = {
        QueryIntent.FACTUAL: {"limit": 5, "min_score": 0.3},
        QueryIntent.TEMPORAL: {"limit": 10, "min_score": 0.2, "time_decay": 0.8},
        QueryIntent.CAUSAL: {"limit": 8, "min_score": 0.2, "max_depth": 4},
        QueryIntent.COMPARATIVE: {"limit": 10, "min_score": 0.2, "diversity": 0.7},
        QueryIntent.EXPLORATORY: {"limit": 15, "min_score": 0.1, "serendipity": 0.3},
    }
    
    def get_channel_weights(self, intent: QueryIntent) -> Dict
    def get_retrieval_params(self, intent: QueryIntent) -> Dict
```

**验收标准**：
1. 每个意图都有对应的通道权重配置
2. 每个意图都有对应的检索参数
3. 支持动态调整权重

#### 任务 2.3：集成意图感知到检索引擎（6小时）
**修改文件**：`neurova/cognitive_layers/memory_layer/neurova_recall.py`

**修改 `recall` 方法**：
```python
async def recall(self, query: str, limit: int = 10, intent: Optional[QueryIntent] = None, **kwargs) -> RecallResult:
    # 1. 意图检测（如果未指定）
    if intent is None:
        intent = self.intent_detector.detect_intent(query)
    
    # 2. 获取意图特定的配置
    channel_weights = self.intent_strategy.get_channel_weights(intent)
    retrieval_params = self.intent_strategy.get_retrieval_params(intent)
    
    # 3. 使用意图特定的参数进行检索
    # ... 原有检索逻辑，但使用 channel_weights 和 retrieval_params
    
    # 4. 返回结果（包含意图信息）
    return RecallResult(query=query, intent=intent, recalled_memories=recalled_memories, ...)
```

**验收标准**：
1. `recall` 方法支持可选的 `intent` 参数
2. 如果未指定意图，自动检测
3. 使用意图特定的通道权重和检索参数
4. 返回结果包含意图信息

### 3.3 测试用例
```python
def test_intent_detection():
    detector = QueryIntentDetector()
    assert detector.detect_intent("when did this happen?") == QueryIntent.TEMPORAL
    assert detector.detect_intent("why is the sky blue?") == QueryIntent.CAUSAL
    assert detector.detect_intent("compare Python vs Java") == QueryIntent.COMPARATIVE
    assert detector.detect_intent("tell me about machine learning") == QueryIntent.EXPLORATORY

def test_intent_specific_retrieval():
    engine = NeurovaRecallEngine(...)
    result = engine.recall("when did we last talk?", intent=QueryIntent.TEMPORAL)
    assert result.intent == QueryIntent.TEMPORAL
    assert result.metadata.get("intent_confidence", 0) > 0.5
```

### 3.4 时间估算
| 任务 | 预计时间 | 依赖 |
|------|----------|------|
| 任务 2.1：意图检测器 | 4 小时 | 无 |
| 任务 2.2：意图特定策略 | 4 小时 | 任务 2.1 |
| 任务 2.3：集成到检索引擎 | 6 小时 | 任务 2.1, 2.2 |
| 测试编写 | 4 小时 | 所有任务 |
| **总计** | **18 小时** | |

## 4. 候选 3：检索管线深度模块化

### 4.1 问题分析
- 当前：硬编码 5 个检索通道，难以扩展
- 目标：插件式通道架构，支持动态注册

### 4.2 详细任务

#### 任务 3.1：定义通道抽象接口（2小时）
**新建文件**：`neurova/cognitive_layers/memory_layer/channel_interface.py`

**接口设计**：
```python
class RecallChannelInterface(ABC):
    @property
    @abstractmethod
    def channel_name(self) -> str: ...
    
    @property
    @abstractmethod
    def channel_type(self) -> RecallChannel: ...
    
    @abstractmethod
    async def search(self, query: str, limit: int = 10, min_score: float = 0.0, **kwargs) -> List[RecalledMemory]: ...
    
    @abstractmethod
    def get_default_weight(self) -> float: ...
    
    @abstractmethod
    def supports_query(self, query: str) -> bool: ...
```

**验收标准**：
1. 定义清晰的通道接口
2. 包含必要的抽象方法
3. 支持可选的统计信息

#### 任务 3.2：实现通道注册表（4小时）
**新建文件**：`neurova/cognitive_layers/memory_layer/channel_registry.py`

**功能设计**：
```python
class ChannelRegistry:
    def register(self, channel: RecallChannelInterface) -> None
    def unregister(self, channel_name: str) -> None
    def get_channel(self, channel_name: str) -> Optional[RecallChannelInterface]
    def get_channel_by_type(self, channel_type: RecallChannel) -> Optional[RecallChannelInterface]
    def list_channels(self) -> List[str]
    def get_all_channels(self) -> Dict[str, RecallChannelInterface]
```

**验收标准**：
1. 支持通道的注册和注销
2. 支持按名称或类型查找通道
3. 支持列出所有通道

#### 任务 3.3：重构现有通道为插件（8小时）
**新建文件**：创建独立的通道实现文件

**通道实现**：
- `neurova/cognitive_layers/memory_layer/channels/temperature_channel.py`
- `neurova/cognitive_layers/memory_layer/channels/text_channel.py`
- `neurova/cognitive_layers/memory_layer/channels/category_channel.py`
- `neurova/cognitive_layers/memory_layer/channels/graph_channel.py`
- `neurova/cognitive_layers/memory_layer/channels/emotion_channel.py`

**验收标准**：
1. 每个现有通道都重构为独立的插件类
2. 实现完整的 `RecallChannelInterface` 接口
3. 保持原有功能不变

#### 任务 3.4：重构检索引擎使用通道注册表（6小时）
**修改文件**：`neurova/cognitive_layers/memory_layer/neurova_recall.py`

**修改内容**：
```python
class NeurovaRecallEngine:
    def __init__(self, ...):
        self.channel_registry = ChannelRegistry()
        self._register_default_channels()
    
    def _register_default_channels(self):
        from .channels.temperature_channel import TemperatureChannel
        from .channels.text_channel import TextChannel
        # ... 注册所有默认通道
    
    def register_channel(self, channel: RecallChannelInterface):
        self.channel_registry.register(channel)
    
    async def recall(self, query: str, limit: int = 10, **kwargs) -> RecallResult:
        channels = self.channel_registry.get_all_channels()
        tasks = []
        for channel_name, channel in channels.items():
            if channel.supports_query(query):
                tasks.append(self._search_channel(channel, query, limit, **kwargs))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_memories = []
        for result in results:
            if isinstance(result, list):
                all_memories.extend(result)
        
        final_results = self._merge_and_rank(all_memories, limit)
        return RecallResult(query=query, recalled_memories=final_results)
```

**验收标准**：
1. 使用通道注册表管理所有通道
2. 支持动态注册自定义通道
3. 保持原有检索功能不变

### 4.3 测试用例
```python
def test_channel_registry():
    registry = ChannelRegistry()
    channel = MockChannel(name="test", channel_type=RecallChannel.TEXT)
    registry.register(channel)
    assert "test" in registry.list_channels()
    assert registry.get_channel("test") == channel
    registry.unregister("test")
    assert "test" not in registry.list_channels()

def test_custom_channel():
    engine = NeurovaRecallEngine(...)
    custom_channel = CustomChannel(...)
    engine.register_channel(custom_channel)
    result = engine.recall("test query")
    # 验证自定义通道被调用
```

### 4.4 时间估算
| 任务 | 预计时间 | 依赖 |
|------|----------|------|
| 任务 3.1：定义通道接口 | 2 小时 | 无 |
| 任务 3.2：实现通道注册表 | 4 小时 | 任务 3.1 |
| 任务 3.3：重构现有通道 | 8 小时 | 任务 3.1 |
| 任务 3.4：重构检索引擎 | 6 小时 | 任务 3.2, 3.3 |
| 测试编写 | 4 小时 | 所有任务 |
| **总计** | **24 小时** | |

## 5. 总体实施计划

### 5.1 优先级排序
1. **Phase 1**（1-2 周）：增强图能力（26 小时）
2. **Phase 2**（2-3 周）：实现意图感知检索（18 小时）
3. **Phase 3**（3-4 周）：检索管线深度模块化（24 小时）

### 5.2 依赖关系
- Phase 2 依赖 Phase 1 的关系类型扩展
- Phase 3 可以独立进行，但建议在 Phase 2 之后

### 5.3 风险点
1. **因果推理引擎**：可能需要 LLM 调用，增加成本
2. **问题分解器**：依赖 LLM 质量，可能需要多轮测试
3. **通道插件化**：重构可能影响现有功能，需要充分测试

### 5.4 验收标准
1. 所有单元测试通过
2. 集成测试通过
3. 性能测试：检索延迟增加不超过 20%
4. 代码覆盖率：新增代码覆盖率 > 80%

## 6. 附录

### 6.1 相关文件
- `neurova/cognitive_layers/memory_layer/graph_traversal.py` - 图遍历模块
- `neurova/cognitive_layers/memory_layer/neurova_recall.py` - 检索引擎
- `neurova/cognitive_layers/memory_layer/__init__.py` - 模块导出

### 6.2 参考资料
- MAGMA 论文：arXiv:2601.03236
- MAMGA 仓库：https://github.com/FredJiang0324/MAMGA

---
*文档生成时间：2026-06-10*