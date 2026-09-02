# 深入 Grilling: ContextFacade

## 关键设计问题讨论

### 问题 1：当前上下文构建的组件关系

```
ContextFacade
└── ContextOrchestrator
    ├── ContextPool (底层实现)
    │   ├── ContextCollector (收集10种来源)
    │   ├── ContextConverter (格式转换)
    │   └── ContextCompressor (压缩)
    ├── ContextBuilder (旧实现，已废弃)
    └── UnifiedContextInjector (注入器)
```

**当前 ContextOrchestrator 的方法：**
- `build_context()` — 构建对话上下文（Phase 2-5）
- `build_system_prompt()` — 构建系统提示
- `get_tools_description()` — 获取工具描述
- `build_tools_for_llm()` — 构建工具列表（OpenAI格式）

### 问题 2：Facade 接口设计

```python
class ContextFacade:
    """上下文构建的统一门面"""
    
    def __init__(self, agent_ref):
        self._agent = agent_ref
        self._orchestrator = ContextOrchestrator(agent_ref)
    
    def build_context(self, 
                      user_input: str,
                      relevant_memories: List = None,
                      crystallized_patterns: List = None,
                      intent: QueryIntent = None,
                      agent_emotion: str = None) -> List[Dict]:
        """构建对话上下文"""
    
    def build_system_prompt(self, 
                           tools_description: str = "",
                           memory_context: str = "",
                           constitution: str = "") -> str:
        """构建系统提示"""
    
    def build_tools_for_llm(self) -> List[Dict]:
        """构建工具列表（OpenAI格式）"""
    
    def get_token_budget(self) -> TokenBudget:
        """获取当前Token预算"""
    
    def compress_context(self, context: List[Dict], 
                        target_tokens: int) -> List[Dict]:
        """压缩上下文到目标Token数"""
    
    def convert_format(self, context: List[Dict], 
                      target_format: str) -> List[Dict]:
        """格式转换（openai/anthropic）"""
```

### 问题 3：ContextPool vs ContextOrchestrator

**当前状态：**
- `ContextOrchestrator` 是入口，内部使用 `ContextPool`
- `ContextPool` 提供底层能力（收集、转换、压缩）

**建议：**
- 保留 `ContextPool` 作为底层实现
- `ContextFacade` 作为上层门面
- 清晰的分层：Facade → Orchestrator → Pool

### 问题 4：多模型格式支持

**当前支持：**
- OpenAI 格式（GPT系列）
- Anthropic 格式（Claude系列）

**增强方案：**

```python
class ContextFacade:
    def convert_format(self, context, target_format):
        """格式转换"""
        if target_format == "openai":
            return self._converter.to_openai(context)
        elif target_format == "anthropic":
            return self._converter.to_anthropic(context)
        elif target_format == "gemini":
            return self._converter.to_gemini(context)
        else:
            raise ValueError(f"Unsupported format: {target_format}")
```

### 问题 5：性能优化

**当前瓶颈：**
- Token计算：每次构建都重新计算
- 上下文收集：10种来源串行收集

**优化策略：**

```python
class ContextFacade:
    def __init__(self, agent_ref):
        # 1. Token计数缓存
        self._token_cache = TTLCache(maxsize=100, ttl=60)
        
        # 2. 并行收集
        self._collector = ContextCollector(max_workers=4)
        
        # 3. 上下文缓存
        self._context_cache = LRUCache(maxsize=50)
    
    def build_context(self, user_input, ...):
        # 1. 检查缓存
        cache_key = hash(user_input)
        if cache_key in self._context_cache:
            return self._context_cache[cache_key]
        
        # 2. 并行收集上下文
        sources = self._collector.collect_parallel([
            ("system", self._build_system_context),
            ("memory", lambda: self._collect_memories(user_input)),
            ("conversation", lambda: self._collect_conversation()),
            # ...
        ])
        
        # 3. 构建上下文
        context = self._build_from_sources(sources)
        
        # 4. 缓存结果
        self._context_cache[cache_key] = context
        
        return context
```

### 问题 6：测试策略

**单元测试：**
1. `test_build_context_basic` — 基本上下文构建
2. `test_build_context_with_memories` — 带记忆的上下文
3. `test_build_system_prompt` — 系统提示构建
4. `test_build_tools_for_llm` — 工具列表构建
5. `test_get_token_budget` — Token预算
6. `test_compress_context` — 上下文压缩
7. `test_convert_format_openai` — OpenAI格式转换
8. `test_convert_format_anthropic` — Anthropic格式转换

**集成测试：**
1. `test_full_context_flow` — 完整上下文构建流程
2. `test_chat_pipeline_integration` — 与ChatPipeline集成

## 最终设计决策

### 决策 1：Facade vs Adapter
**选择：Facade 模式**
- 理由：简化接口，内部协调

### 决策 2：ContextPool保留
**选择：保留ContextPool作为底层实现**
- 理由：已完善，避免重复

### 决策 3：多模型格式
**选择：统一支持OpenAI/Anthropic/Gemini**
- 理由：未来模型切换

### 决策 4：缓存策略
**选择：LRU+TTL多级缓存**
- 理由：避免重复计算

## 实施清单

- [ ] 定义 ContextFacade 接口
- [ ] 实现各功能模块委托
- [ ] 添加格式转换支持
- [ ] 添加缓存机制
- [ ] 编写 8 个单元测试
- [ ] 编写 2 个集成测试
