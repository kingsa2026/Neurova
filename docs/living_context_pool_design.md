# 活水上下文池设计文档

## 1. 核心问题

### 1.1 当前问题
- ❌ 内容重复浪费Token
- ❌ 特殊场景下窗口限制
- ❌ 无法实时动态调整
- ❌ 上下文是"死水"而非"活水"

### 1.2 核心诉求
1. **解决上下文内容重复，浪费Token的问题** — 多阶段去重（精确+模式+语义）
2. **解决特殊情况下LLM上下文窗口限制** — 动态压缩、按需取水
3. **根据情感、记忆、工具调用等，实时对上下文进行动态调整** — 水滴带标签、来源
4. **上下文池能根据对话内容自动更新，保证取出来的水是有用的活水** — 向量语义匹配取水

## 2. 活水模型

### 2.1 水池比喻
```
水源（输入）                    水池（存储）                    取水（输出）
────────────────────────────────────────────────────────────────────────────
对话历史 ──┐               ┌───────────────────┐           ┌─────────────┐
记忆检索 ──┼─→ [去重+标签] → [活水上下文池]      → [向量匹配] → [按需取水] → LLM
情感状态 ──┤               │  水滴 = 内容+标签  │           └─────────────┘
工具结果 ──┘               │  向量 = 语义编码   │
                          │  需求 = 字符串     │
                          └───────────────────┘
                                    ↑
                              UnifiedVectorStore
                            (BAAI/bge-small-zh-v1.5)
```

### 2.2 活水特性
1. **流动性**：新内容不断流入，旧内容自然流出
2. **新鲜度**：基于时间衰减，保持内容新鲜
3. **纯净性**：多阶段去重机制，避免重复污染
4. **语义性**：向量语义匹配，理解同义词、近义词、上下文
5. **按需性**：需求即字符串，自动匹配池中带标签的水滴

## 3. 去重机制深度分析

### 3.1 去重时机问题

**问题**：去重应该在什么时候进行？

**方案对比**：

| 时机 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **输入时去重** | 减少存储开销 | 可能丢失历史版本 | 高频输入场景 |
| **压缩前去重** | 减少压缩计算量 | 可能影响压缩效果 | 常规场景 |
| **输出时去重** | 保留完整历史 | 增加输出延迟 | 对历史完整性要求高 |
| **多阶段去重** | 平衡各阶段需求 | 实现复杂 | 推荐方案 |

### 3.2 去重类型

#### 3.2.1 精确去重（Exact Deduplication）
```python
def exact_dedup(content1: str, content2: str) -> bool:
    """精确去重：完全相同的内容"""
    return hash(content1) == hash(content2)
```

**特点**：
- ✅ 安全，不会丢失信息
- ✅ 不会产生LLM漂移
- ❌ 只能去除完全相同的内容

#### 3.2.2 语义去重（Semantic Deduplication）
```python
def semantic_dedup(content1: str, content2: str, threshold: float = 0.85) -> bool:
    """语义去重：相似但不完全相同的内容"""
    similarity = calculate_similarity(content1, content2)
    return similarity > threshold
```

**特点**：
- ✅ 可以去除相似内容
- ⚠️ 可能丢失细微差别
- ⚠️ 可能产生LLM漂移

#### 3.2.3 模式去重（Pattern Deduplication）
```python
def pattern_dedup(drop1: ContextDrop, drop2: ContextDrop) -> bool:
    """模式去重：相同来源、相似内容模式"""
    return (drop1.source == drop2.source and 
            content_similarity(drop1.content, drop2.content) > 0.9)
```

**特点**：
- ✅ 针对特定来源优化
- ✅ 保留关键信息
- ❌ 可能误判

### 3.3 去重对LLM的影响

#### 3.3.1 信息丢失风险
**场景**：
```
原始上下文：
- 用户：今天天气怎么样？
- 助手：今天天气晴朗，温度25度。
- 用户：明天呢？
- 助手：明天多云，温度22度。

去重后（如果去除了"天气"相关内容）：
- 用户：今天天气怎么样？
- 助手：明天多云，温度22度。
```

**问题**：去重可能导致上下文断裂，LLM无法理解完整对话。

#### 3.3.2 LLM漂移风险
**定义**：LLM对去重后的上下文产生不同的理解，导致输出质量下降。

**风险因素**：
1. **语义去重阈值过高**：去除看似重复但实际有区别的内容
2. **时间序列破坏**：去重打乱了对话的时间顺序
3. **上下文缺失**：去重导致关键上下文丢失

#### 3.3.3 安全去重策略

**策略1：精确去重优先**
```python
def safe_dedup(drops: List[ContextDrop]) -> List[ContextDrop]:
    """安全去重：优先使用精确去重"""
    seen_hashes = set()
    result = []
    
    for drop in drops:
        if drop.hash not in seen_hashes:
            seen_hashes.add(drop.hash)
            result.append(drop)
    
    return result
```

**策略2：保留关键信息**
```python
def dedup_with_key_preservation(drops: List[ContextDrop]) -> List[ContextDrop]:
    """去重时保留关键信息"""
    seen = {}
    result = []
    
    for drop in drops:
        key = (drop.source, drop.hash)
        if key not in seen:
            seen[key] = drop
            result.append(drop)
        else:
            # 保留更新的版本
            if drop.updated_at > seen[key].updated_at:
                result.remove(seen[key])
                result.append(drop)
                seen[key] = drop
    
    return result
```

**策略3：上下文感知去重**
```python
def context_aware_dedup(drops: List[ContextDrop], 
                        current_query: str) -> List[ContextDrop]:
    """上下文感知去重：根据当前查询决定去重策略"""
    
    # 1. 精确去重
    exact_deduped = exact_dedup(drops)
    
    # 2. 对于与当前查询相关的上下文，放宽去重阈值
    relevant_drops = []
    irrelevant_drops = []
    
    for drop in exact_deduped:
        if is_relevant_to_query(drop, current_query):
            relevant_drops.append(drop)
        else:
            irrelevant_drops.append(drop)
    
    # 3. 对相关上下文使用更严格的去重
    relevant_deduped = semantic_dedup(relevant_drops, threshold=0.9)
    
    # 4. 对不相关上下文使用更宽松的去重
    irrelevant_deduped = semantic_dedup(irrelevant_drops, threshold=0.8)
    
    return relevant_deduped + irrelevant_deduped
```

## 4. 推荐去重方案

### 4.1 多阶段去重策略

```python
class MultiStageDeduplicator:
    """多阶段去重器"""
    
    def dedup(self, drops: List[ContextDrop], 
              current_query: str = None) -> List[ContextDrop]:
        """多阶段去重"""
        
        # 阶段1：精确去重（安全，无信息丢失）
        stage1 = self._exact_dedup(drops)
        
        # 阶段2：模式去重（针对特定来源）
        stage2 = self._pattern_dedup(stage1)
        
        # 阶段3：语义去重（谨慎，保留关键信息）
        if current_query:
            stage3 = self._context_aware_semantic_dedup(stage2, current_query)
        else:
            stage3 = self._conservative_semantic_dedup(stage2)
        
        return stage3
    
    def _exact_dedup(self, drops: List[ContextDrop]) -> List[ContextDrop]:
        """阶段1：精确去重"""
        seen = set()
        result = []
        for drop in drops:
            if drop.hash not in seen:
                seen.add(drop.hash)
                result.append(drop)
        return result
    
    def _pattern_dedup(self, drops: List[ContextDrop]) -> List[ContextDrop]:
        """阶段2：模式去重"""
        # 按来源分组
        by_source = {}
        for drop in drops:
            if drop.source not in by_source:
                by_source[drop.source] = []
            by_source[drop.source].append(drop)
        
        result = []
        for source, source_drops in by_source.items():
            # 对同一来源的内容进行去重
            deduped = self._dedup_same_source(source_drops)
            result.extend(deduped)
        
        return result
    
    def _conservative_semantic_dedup(self, drops: List[ContextDrop]) -> List[ContextDrop]:
        """阶段3：保守语义去重"""
        # 使用高阈值，只去除非常相似的内容
        return self._semantic_dedup_with_threshold(drops, threshold=0.95)
```

### 4.2 去重时机建议

**推荐方案：输入时 + 压缩前 双重去重**

```python
class LivingContextPool:
    def add_or_update(self, drop: ContextDrop) -> bool:
        """添加或更新水滴"""
        
        # 1. 输入时去重（精确去重为主）
        if not self._input_dedup(drop):
            return False
        
        # 2. 存储
        self._drops[drop.id] = drop
        
        # 3. 自动压缩检查（压缩前会再次去重）
        self._auto_compress_if_needed()
        
        return True
    
    def _input_dedup(self, new_drop: ContextDrop) -> bool:
        """输入时去重：精确去重为主"""
        # 精确哈希检查
        for existing in self._drops.values():
            if existing.hash == new_drop.hash:
                # 保留更新的版本
                if new_drop.updated_at > existing.updated_at:
                    return True  # 允许替换
                return False  # 丢弃重复
        
        return True  # 无重复，允许添加
    
    def _auto_compress_if_needed(self):
        """自动压缩（包含压缩前去重）"""
        total_tokens = sum(drop.tokens for drop in self._drops.values())
        
        if total_tokens > self.max_tokens * 0.8:
            # 压缩前去重
            deduped = self._dedup_before_compression(list(self._drops.values()))
            
            # 压缩
            compressed = self._compressor.compress(deduped, self.max_tokens)
            
            # 更新
            self._drops = {drop.id: drop for drop in compressed}
    
    def _dedup_before_compression(self, drops: List[ContextDrop]) -> List[ContextDrop]:
        """压缩前去重：更积极的去重策略"""
        # 1. 精确去重
        exact_deduped = self._deduplicator.exact_dedup(drops)
        
        # 2. 语义去重（中等阈值）
        semantic_deduped = self._deduplicator.semantic_dedup(
            exact_deduped, 
            threshold=0.85  # 压缩前使用较低阈值
        )
        
        return semantic_deduped
```

## 5. 多阶段去重 + 防漂移机制（完整方案）

### 5.1 架构概览

```
输入时去重          压缩前去重           输出时去重
    │                   │                   │
    ▼                   ▼                   ▼
┌─────────┐        ┌─────────┐        ┌─────────┐
│精确去重 │        │精确去重 │        │上下文   │
│(哈希)   │        │(哈希)   │        │感知去重 │
└────┬────┘        └────┬────┘        └────┬────┘
     │                  │                  │
     ▼                  ▼                  ▼
┌─────────┐        ┌─────────┐        ┌─────────┐
│模式去重 │        │模式去重 │        │验证机制 │
│(同来源) │        │(同来源) │        │(防漂移) │
└────┬────┘        └────┬────┘        └────┬────┘
     │                  │                  │
     ▼                  ▼                  ▼
┌─────────┐        ┌─────────┐        ┌─────────┐
│   通过   │        │语义去重 │        │回退机制 │
│   或拒绝 │        │(高阈值) │        │(保守)   │
└─────────┘        └────┬────┘        └─────────┘
                        │
                        ▼
                   ┌─────────┐
                   │验证机制 │
                   │(防漂移) │
                   └────┬────┘
                        │
                        ▼
                   ┌─────────┐
                   │回退机制 │
                   │(保守)   │
                   └─────────┘
```

### 5.2 防漂移去重器核心设计

**设计原则**：
1. **精确去重优先**（100%安全，哈希匹配）
2. **高阈值语义去重**（>0.95，只去除非常相似的内容）
3. **保留关键上下文**（高优先级、最近、相关的内容不去重）
4. **验证机制**（去重后验证效果）
5. **回退机制**（验证失败时回退到保守策略）

**核心类**：
```python
class DriftSafeDeduplicator:
    """防漂移去重器"""
    
    def __init__(self, 
                 exact_threshold: float = 1.0,
                 semantic_threshold: float = 0.95,
                 pattern_threshold: float = 0.9):
        self.exact_threshold = exact_threshold
        self.semantic_threshold = semantic_threshold
        self.pattern_threshold = pattern_threshold
    
    def dedup(self, drops, current_query=None, stage='input'):
        """多阶段去重"""
        # 阶段1：精确去重（安全）
        stage1 = self._exact_dedup(drops)
        
        # 阶段2：模式去重（同来源）
        stage2 = self._pattern_dedup(stage1)
        
        # 阶段3：上下文感知语义去重（高阈值）
        if current_query:
            stage3 = self._context_aware_semantic_dedup(stage2, current_query)
        else:
            stage3 = self._conservative_semantic_dedup(stage2)
        
        # 阶段4：验证（防漂移）
        if stage == 'output' and current_query:
            if not self._validate(stage3, current_query):
                return stage2  # 回退
        
        return stage3
```

### 5.3 关键上下文识别

**不去重的关键上下文**：
1. **高优先级内容**（priority >= 90）
2. **用户输入**（source == USER_INPUT）
3. **系统指令**（source == SYSTEM_INSTRUCTION）
4. **与当前查询相关**（关键词匹配 > 30%）
5. **最近5分钟的内容**

```python
def _identify_key_contexts(self, drops, current_query):
    """识别关键上下文（不去重）"""
    key_contexts = []
    
    for drop in drops:
        is_key = (
            drop.priority >= 90 or
            drop.source == ContextSource.USER_INPUT or
            drop.source == ContextSource.SYSTEM_INSTRUCTION or
            self._is_relevant_to_query(drop, current_query) or
            self._is_recent(drop, minutes=5)
        )
        
        if is_key:
            key_contexts.append(drop)
    
    return key_contexts
```

### 5.4 去重后验证机制

**验证项目**：
1. **关键信息是否保留**（高优先级内容、用户输入）
2. **上下文连贯性是否保持**（对话轮次完整性）
3. **内容多样性是否足够**（至少2种来源）

```python
def _validate(self, deduped, current_query):
    """验证去重结果，防止漂移"""
    # 检查1：关键信息是否保留
    if not self._check_key_info_preserved(deduped, current_query):
        return False
    
    # 检查2：上下文连贯性是否保持
    if not self._check_coherence_maintained(deduped):
        return False
    
    # 检查3：内容多样性是否足够
    if not self._check_diversity_maintained(deduped):
        return False
    
    return True
```

### 5.5 去重时机集成

**推荐方案：输入时 + 压缩前 + 输出时 三阶段去重**

```python
class LivingContextPool:
    def add_or_update(self, drop):
        """输入时去重（精确+模式）"""
        # 1. 输入时去重
        deduped = self._deduplicator.dedup(
            list(self._drops.values()) + [drop],
            stage='input'
        )
        
        # 2. 检查是否被去重
        if drop not in deduped:
            return False
        
        # 3. 存储
        self._drops[drop.id] = drop
        return True
    
    def get_context_for_model(self, model, query=None):
        """输出时去重（上下文感知）"""
        # 1. 获取所有水滴
        all_drops = list(self._drops.values())
        
        # 2. 输出时去重
        deduped = self._deduplicator.dedup(
            all_drops,
            current_query=query,
            stage='output'
        )
        
        # 3. 压缩
        compressed = self._compressor.compress(deduped, self.max_tokens)
        
        # 4. 格式化
        return self._format_for_model(compressed, model)
```

### 5.6 保留上下文连贯性

```python
def dedup_with_coherence(drops: List[ContextDrop]) -> List[ContextDrop]:
    """去重时保留上下文连贯性"""
    
    # 1. 按时间排序
    sorted_drops = sorted(drops, key=lambda x: x.created_at)
    
    # 2. 识别对话轮次
    turns = identify_conversation_turns(sorted_drops)
    
    # 3. 对每个轮次进行去重
    deduped_turns = []
    for turn in turns:
        deduped_turn = dedup_single_turn(turn)
        deduped_turns.append(deduped_turn)
    
    # 4. 重新组合
    return flatten_turns(deduped_turns)
```

### 5.2 保留关键上下文

```python
def dedup_preserving_key_context(drops: List[ContextDrop],
                                 current_query: str) -> List[ContextDrop]:
    """去重时保留关键上下文"""
    
    # 1. 识别关键上下文
    key_contexts = identify_key_contexts(drops, current_query)
    
    # 2. 对非关键上下文进行去重
    non_key = [d for d in drops if d not in key_contexts]
    deduped_non_key = aggressive_dedup(non_key)
    
    # 3. 合并
    return key_contexts + deduped_non_key

def identify_key_contexts(drops: List[ContextDrop],
                          current_query: str) -> List[ContextDrop]:
    """识别关键上下文"""
    key_contexts = []
    
    for drop in drops:
        # 关键上下文特征
        is_key = (
            drop.priority >= 90 or  # 高优先级
            drop.source == ContextSource.USER_INPUT or  # 用户输入
            is_relevant_to_query(drop, current_query) or  # 与当前查询相关
            is_recent(drop, minutes=5)  # 最近5分钟的内容
        )
        
        if is_key:
            key_contexts.append(drop)
    
    return key_contexts
```

### 5.3 去重后验证

```python
def dedup_with_validation(drops: List[ContextDrop],
                          current_query: str) -> List[ContextDrop]:
    """去重后验证，防止漂移"""
    
    # 1. 执行去重
    deduped = perform_dedup(drops)
    
    # 2. 验证去重效果
    if not validate_dedup_result(drops, deduped, current_query):
        # 验证失败，回退到保守去重
        return conservative_dedup(drops)
    
    return deduped

def validate_dedup_result(original: List[ContextDrop],
                         deduped: List[ContextDrop],
                         current_query: str) -> bool:
    """验证去重结果"""
    
    # 检查1：关键信息是否保留
    if not check_key_info_preserved(original, deduped):
        return False
    
    # 检查2：上下文连贯性是否保持
    if not check_coherence_maintained(deduped):
        return False
    
    # 检查3：与当前查询的相关性是否降低
    if check_relevance_decreased(original, deduped, current_query):
        return False
    
    return True
```

## 6. 实施建议

### 6.1 渐进式实施

**Phase 1：精确去重（安全）**
- 只去除完全相同的内容
- 不会产生LLM漂移
- 实现简单，风险低

**Phase 2：模式去重（中等风险）**
- 针对特定来源的去重
- 保留关键信息
- 需要测试验证

**Phase 3：语义去重（需谨慎）**
- 使用高阈值（>0.9）
- 上下文感知去重
- 需要充分测试

### 6.2 测试策略

```python
class DedupTestSuite:
    """去重测试套件"""
    
    def test_exact_dedup_safety(self):
        """测试精确去重安全性"""
        # 验证精确去重不会丢失信息
        
    def test_semantic_dedup_threshold(self):
        """测试语义去重阈值"""
        # 找到最佳阈值，平衡去重效果和信息保留
        
    def test_coherence_preservation(self):
        """测试上下文连贯性"""
        # 验证去重后上下文仍然连贯
        
    def test_llm_output_quality(self):
        """测试LLM输出质量"""
        # 对比去重前后LLM输出质量
```

## 7. 结论

### 7.1 去重的科学性

**科学的去重策略**：
1. **精确去重优先**：安全，无信息丢失
2. **保留关键信息**：去重时保留关键上下文
3. **上下文感知**：根据当前查询调整去重策略
4. **渐进式实施**：从安全策略开始，逐步优化

### 7.2 LLM漂移风险

**风险控制**：
1. **使用高阈值**：语义去重使用高阈值（>0.9）
2. **保留关键上下文**：高优先级、最近、相关的内容不去重
3. **验证机制**：去重后验证效果
4. **回退机制**：验证失败时回退到保守策略

### 7.3 推荐方案

**多阶段去重 + 输入时/压缩前双重去重**

1. **输入时**：精确去重为主
2. **压缩前**：精确+模式+保守语义去重
3. **输出时**：上下文感知去重（可选）

**这样既能有效减少重复内容，又能最大程度避免LLM漂移。**

## 6. 按需取水机制（核心设计）

### 6.1 设计理念

**核心思想**：需求就是字符串，池里有带标签的水滴，字符串和标签匹配就行。

**不定义需求类型**，不需要场景检测，不需要复杂推理。只需要：
1. 需求描述（字符串）
2. 水滴标签（tags, source, content 片段）
3. 简单匹配

### 6.2 数据模型

```python
@dataclass
class ContextDrop:
    """上下文水滴"""
    id: str
    content: str                    # 内容
    source: str                     # 来源（memory, tool_result, user_input 等）
    tags: List[str]                 # 标签列表（如 ["代码", "Python", "调试"]）
    priority: int = 50              # 优先级 (0-100)
    tokens: int = 0                 # Token 数量
    created_at: datetime = None     # 创建时间
    updated_at: datetime = None     # 更新时间
    hash: str = None                # 内容哈希（用于精确去重）
    metadata: Dict[str, Any] = None # 元数据
```

**标签来源**：
- 用户输入：自动提取关键词作为标签
- 记忆检索：使用记忆的关键词/类别
- 工具调用：使用工具名+参数关键词
- 对话历史：使用消息内容的关键词
- 情感状态：使用情感类型标签

### 6.3 向量语义匹配取水器

**核心改进**：使用项目已集成的 `UnifiedVectorStore` 进行语义匹配，而非简单关键词匹配。

```python
class SemanticMatchDrawer:
    """向量语义匹配取水器 - 使用项目集成的向量模型"""
    
    def __init__(self, max_tokens: int = 16000):
        self.max_tokens = max_tokens
        
        # 复用项目已有的向量存储
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
        self.vector_store = UnifiedVectorStore(backend="auto")
        
        # 权重配置
        self.weights = {
            'semantic_score': 0.5,   # 语义相似度权重
            'freshness': 0.2,        # 新鲜度权重
            'priority': 0.2,         # 优先级权重
            'source_match': 0.1      # 来源匹配权重
        }
        
        # 来源衰减倍数
        self.source_multipliers = {
            'user_input': 1.0,       # 用户输入：正常衰减
            'conversation': 0.8,     # 对话历史：稍快衰减
            'memory': 0.3,           # 记忆：慢衰减
            'emotion': 0.5,          # 情感：中等衰减
            'tool_result': 0.6,      # 工具调用：中等衰减
            'system': 0.1,           # 系统指令：极慢衰减
        }
        
        # 水滴向量缓存
        self._drop_vectors: Dict[str, List[float]] = {}
    
    def draw(self, drops: List[ContextDrop], need: str = None) -> List[ContextDrop]:
        """
        按需取水 - 向量语义匹配
        
        Args:
            drops: 水滴列表
            need: 需求描述字符串，如 "如何优化这段代码" 或 "用户的情感状态"
                  如果为 None，返回综合得分最高的水滴
        
        Returns:
            排序后的水滴列表（已应用 Token 预算）
        """
        if not drops:
            return []
        
        # 1. 编码需求
        need_vector = None
        if need:
            need_vector = self.vector_store.encode(need)
        
        # 2. 计算每个水滴的得分
        scored_drops = []
        for drop in drops:
            score = self._calculate_score(drop, need_vector)
            scored_drops.append((score, drop))
        
        # 3. 按得分降序排序
        scored_drops.sort(key=lambda x: -x[0])
        
        # 4. 应用 Token 预算
        result = []
        total_tokens = 0
        
        for score, drop in scored_drops:
            if total_tokens + drop.tokens <= self.max_tokens:
                result.append(drop)
                total_tokens += drop.tokens
            else:
                # 尝试截断
                remaining = self.max_tokens - total_tokens
                if remaining > 100:  # 至少 100 tokens
                    truncated = self._truncate_drop(drop, remaining)
                    if truncated:
                        result.append(truncated)
                break
        
        return result
    
    def _calculate_score(self, drop: ContextDrop, need_vector: List[float] = None) -> float:
        """计算水滴综合得分"""
        # 语义相似度得分
        semantic_score = self._calculate_semantic_score(drop, need_vector) if need_vector else 0.5
        
        # 新鲜度得分
        freshness_score = self._calculate_freshness_score(drop)
        
        # 优先级得分
        priority_score = drop.priority / 100.0
        
        # 来源匹配得分（基于向量）
        source_score = self._calculate_source_score(drop, need_vector) if need_vector else 0.5
        
        # 综合得分
        total = (
            self.weights['semantic_score'] * semantic_score +
            self.weights['freshness'] * freshness_score +
            self.weights['priority'] * priority_score +
            self.weights['source_match'] * source_score
        )
        
        return total
    
    def _calculate_semantic_score(self, drop: ContextDrop, need_vector: List[float]) -> float:
        """计算语义相似度得分 - 使用向量余弦相似度"""
        # 获取或计算水滴向量
        drop_vector = self._get_drop_vector(drop)
        
        # 计算余弦相似度
        from neurova.cognitive_layers.memory_layer.unified_vector_store import cosine_similarity
        similarity = cosine_similarity(need_vector, drop_vector)
        
        # 归一化到 [0, 1]
        return (similarity + 1) / 2
    
    def _get_drop_vector(self, drop: ContextDrop) -> List[float]:
        """获取水滴的向量表示（带缓存）"""
        if drop.id in self._drop_vectors:
            return self._drop_vectors[drop.id]
        
        # 编码水滴内容
        # 组合内容和标签以获得更好的语义表示
        text_to_encode = drop.content
        if drop.tags:
            text_to_encode += " " + " ".join(drop.tags)
        
        vector = self.vector_store.encode(text_to_encode)
        
        # 缓存
        self._drop_vectors[drop.id] = vector
        
        return vector
    
    def _calculate_freshness_score(self, drop: ContextDrop) -> float:
        """计算新鲜度得分"""
        if not drop.updated_at:
            return 0.5
        
        age_hours = (datetime.now() - drop.updated_at).total_seconds() / 3600
        
        # 指数衰减
        freshness = math.exp(-0.1 * age_hours)
        
        # 来源调整
        multiplier = self.source_multipliers.get(drop.source, 0.5)
        
        return freshness * multiplier
    
    def _calculate_source_score(self, drop: ContextDrop, need_vector: List[float]) -> float:
        """计算来源匹配得分（基于向量）"""
        if not need_vector:
            return 0.5
        
        # 将来源类型编码为向量
        source_text = drop.source.replace("_", " ")
        source_vector = self.vector_store.encode(source_text)
        
        # 计算相似度
        from neurova.cognitive_layers.memory_layer.unified_vector_store import cosine_similarity
        similarity = cosine_similarity(need_vector, source_vector)
        
        return (similarity + 1) / 2
    
    def _truncate_drop(self, drop: ContextDrop, max_tokens: int) -> ContextDrop:
        """截断水滴以适应 Token 预算"""
        if drop.tokens <= max_tokens:
            return drop
        
        # 简单截断：按比例截断内容
        ratio = max_tokens / drop.tokens
        truncated_content = drop.content[:int(len(drop.content) * ratio)]
        
        # 创建截断后的副本
        return ContextDrop(
            id=drop.id + "_truncated",
            content=truncated_content + "...",
            source=drop.source,
            tags=drop.tags,
            priority=drop.priority,
            tokens=max_tokens,
            created_at=drop.created_at,
            updated_at=drop.updated_at,
            hash=hashlib.md5(truncated_content.encode()).hexdigest(),
            metadata=drop.metadata
        )
    
    def invalidate_cache(self, drop_id: str = None):
        """使缓存失效"""
        if drop_id:
            self._drop_vectors.pop(drop_id, None)
        else:
            self._drop_vectors.clear()
```

### 6.4 使用示例（向量语义匹配）

```python
# 创建取水器（复用项目已有的向量模型）
drawer = SemanticMatchDrawer(max_tokens=16000)

# 场景1：用户问编程问题（语义理解）
need = "如何优化这段递归算法的性能"
context = drawer.draw(pool.get_all_drops(), need)
# 结果：语义匹配到 "代码优化", "算法", "性能" 相关水滴
# 即使水滴标签是 ["递归", "优化"] 也能匹配

# 场景2：用户问情感问题（语义理解）
need = "我今天感觉有点焦虑"
context = drawer.draw(pool.get_all_drops(), need)
# 结果：语义匹配到 "情感状态", "焦虑", "压力" 相关水滴

# 场景3：用户问记忆相关（语义理解）
need = "我们之前讨论过什么"
context = drawer.draw(pool.get_all_drops(), need)
# 结果：语义匹配到 "对话历史", "讨论", "之前" 相关水滴

# 场景4：无特定需求（默认行为）
context = drawer.draw(pool.get_all_drops(), need=None)
# 结果：返回综合得分最高的水滴（新鲜度+优先级）

# 场景5：复杂语义匹配
need = "我想了解神经网络的训练过程"
context = drawer.draw(pool.get_all_drops(), need)
# 结果：语义匹配到 "深度学习", "模型训练", "梯度下降" 相关水滴
# 即使没有完全相同的关键词也能匹配
```

**向量匹配 vs 关键词匹配**：

| 场景 | 关键词匹配 | 向量语义匹配 |
|------|-----------|-------------|
| "如何优化代码" vs 水滴标签["性能调优"] | ❌ 不匹配 | ✅ 匹配 |
| "我心情不好" vs 水滴内容["情感状态：焦虑"] | ❌ 不匹配 | ✅ 匹配 |
| "之前聊过什么" vs 水滴标签["历史对话"] | ❌ 不匹配 | ✅ 匹配 |

### 6.5 与 Agent 集成

```python
class Agent:
    async def chat(self, user_input, ...):
        # 1. 添加用户输入到上下文池
        user_drop = ContextDrop(
            id=f"user_{int(time.time())}",
            content=user_input,
            source="user_input",
            tags=self._extract_keywords(user_input),
            priority=100,
            tokens=count_tokens(user_input),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        self.context_pool.add_or_update(user_drop)
        
        # 2. 智能取水（自动匹配用户输入）
        context_messages = self.context_pool.draw(
            need=user_input  # 直接用用户输入作为需求
        )
        
        # 3. 调用 LLM
        response = await self.loop.predict_step(
            messages=context_messages,
            tools=tools_for_llm
        )
        
        # 4. 添加助手回复到上下文池
        assistant_drop = ContextDrop(
            id=f"assistant_{int(time.time())}",
            content=response,
            source="conversation",
            tags=self._extract_keywords(response),
            priority=80,
            tokens=count_tokens(response),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        self.context_pool.add_or_update(assistant_drop)
        
        return response
```

### 6.6 取水时机

**推荐方案**：每次 LLM 调用前取水

```
用户输入 → 添加到池 → 按需取水 → LLM 调用 → 回复添加到池
```

**关键点**：
- 不需要预定义需求类型
- 不需要场景检测
- 需求就是用户输入本身
- 自动匹配池中带标签的水滴

## 7. 实施建议

### 7.1 渐进式实施

**Phase 1：精确去重（安全）**
- 只去除完全相同的内容
- 不会产生LLM漂移
- 实现简单，风险低

**Phase 2：模式去重（中等风险）**
- 针对特定来源的去重
- 保留关键信息
- 需要测试验证

**Phase 3：语义去重（需谨慎）**
- 使用高阈值（>0.95）
- 上下文感知去重
- 需要充分测试

**Phase 4：智能取水（完整功能）**
- 多维度评分
- 多样性保证
- 连贯性保证

### 7.2 测试策略

```python
class DedupTestSuite:
    """去重测试套件"""
    
    def test_exact_dedup_safety(self):
        """测试精确去重安全性"""
        # 验证精确去重不会丢失信息
        
    def test_semantic_dedup_threshold(self):
        """测试语义去重阈值"""
        # 找到最佳阈值，平衡去重效果和信息保留
        
    def test_coherence_preservation(self):
        """测试上下文连贯性"""
        # 验证去重后上下文仍然连贯
        
    def test_llm_output_quality(self):
        """测试LLM输出质量"""
        # 对比去重前后LLM输出质量
```

## 8. 结论

### 8.1 去重的科学性

**科学的去重策略**：
1. **精确去重优先**：安全，无信息丢失
2. **保留关键信息**：去重时保留关键上下文
3. **上下文感知**：根据当前查询调整去重策略
4. **渐进式实施**：从安全策略开始，逐步优化

### 8.2 LLM漂移风险

**风险控制**：
1. **使用高阈值**：语义去重使用高阈值（>0.95）
2. **保留关键上下文**：高优先级、最近、相关的内容不去重
3. **验证机制**：去重后验证效果
4. **回退机制**：验证失败时回退到保守策略

### 8.3 推荐方案

**多阶段去重 + 智能取水**

1. **去重**：输入时 + 压缩前 + 输出时 三阶段去重
2. **取水**：新鲜度 + 相关性 + 重要性 多维度评分
3. **保证**：多样性 + 连贯性 双重保证

**这样既能有效减少重复内容，又能最大程度避免LLM漂移，同时保证取出来的水是"有用的活水"。**

---

**文档版本**：v1.3  
**创建时间**：2026-06-04  
**最后更新**：2026-06-04  
**更新内容**：集成项目已有的 UnifiedVectorStore 向量模型，实现语义匹配取水