# Grilling: 上下文构建深度模块 (ContextFacade)

## 设计讨论框架

### 1. 接口设计问题

**问题1：当前上下文构建的组件有哪些？**

当前分散的组件：
- `ContextOrchestrator` (orchestrator.py) — 统一上下文构建模块
- `ContextBuilder` (builder.py) — 上下文构建器
- `UnifiedContextInjector` (injector.py) — 统一上下文注入器
- `ContextPool` (context_pool.py) — 统一上下文管理
- `TokenBudget` (models.py) — Token 预算模型

**问题2：ContextOrchestrator 的接口有哪些？**

当前 `ContextOrchestrator` 的方法：
- `build_context()` — 构建对话上下文（Phase 2-5）
- `build_system_prompt()` — 构建系统提示
- `get_tools_description()` — 获取工具描述
- `build_tools_for_llm()` — 构建工具列表（OpenAI 格式）

**问题3：哪些地方调用了这些接口？**

调用者分析：
- `ChatPipeline._step_retrieve_and_build_context()` → `context_orchestrator.build_context()`
- `Agent._build_system_prompt()` → `context_orchestrator.build_system_prompt()`
- `Agent._build_tools_for_llm()` → `context_orchestrator.build_tools_for_llm()`

**候选接口设计：**

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
                      intent: QueryIntent = None) -> List[Dict]:
        """构建对话上下文"""
    
    def build_system_prompt(self, 
                           tools_description: str = "",
                           memory_context: str = "") -> str:
        """构建系统提示"""
    
    def build_tools_for_llm(self) -> List[Dict]:
        """构建工具列表（OpenAI 格式）"""
    
    def get_token_budget(self) -> TokenBudget:
        """获取当前 Token 预算"""
    
    def compress_context(self, context: List[Dict], target_tokens: int) -> List[Dict]:
        """压缩上下文到目标 Token 数"""
```

**问题4：ContextPool 的角色是什么？**

`ContextPool` 提供：
- Token 预算管理
- 上下文源收集（10种来源）
- 上下文压缩
- 格式转换（OpenAI ↔ Anthropic）

**当前问题：**
- `ContextPool` 和 `ContextOrchestrator` 功能重叠
- `ContextBuilder` 被 `UnifiedContextInjector` 替代
- 调用者需要知道内部结构

### 2. 设计约束

**约束1：向后兼容**
- 现有调用者（ChatPipeline, Agent）需要无缝迁移
- 旧接口保留为适配器

**约束2：性能要求**
- 上下文构建 < 200ms
- Token 计算 < 10ms
- 压缩 < 50ms

**约束3：可测试性**
- 每个功能可以单独测试
- 支持 mock 所有依赖

### 3. 架构决策

**决策1：Facade vs Adapter？**
- **Facade**：提供简化接口，内部协调复杂组件
- **Adapter**：转换接口，适配不同组件

**建议**：使用 **Facade 模式**，因为：
1. 调用者需要简单接口
2. 内部组件需要协调
3. 可以隐藏实现细节

**决策2：ContextPool vs ContextOrchestrator？**

当前状态：
- `ContextOrchestrator` 是入口，内部使用 `ContextPool`
- `ContextPool` 提供底层能力

**建议**：保留 `ContextPool` 作为底层实现，`ContextFacade` 作为上层门面，因为：
1. `ContextPool` 已经很完善
2. 避免重复实现
3. 清晰的分层

**决策3：是否需要支持多模型格式？**

当前：
- `ContextPool` 支持 OpenAI 和 Anthropic 格式
- `ContextBuilder` 只支持 OpenAI 格式

**建议**：统一支持多模型格式，因为：
1. 未来可能切换模型
2. 减少格式转换代码
3. 提高可维护性

### 4. 实现步骤

**步骤1：定义 Facade 接口**
```python
class ContextFacade:
    """上下文构建的统一门面"""
    
    def __init__(self, agent_ref):
        self._agent = agent_ref
        self._context_pool = ContextPool(
            user_id=getattr(agent_ref, "user_id", "default"),
            agent_id=getattr(agent_ref, "agent_id", "default"),
            max_tokens=self._get_token_budget(agent_ref),
        )
```

**步骤2：实现各功能模块**
- 上下文构建委托给 `ContextPool`
- 系统提示构建委托给 `ContextBuilder`
- 工具列表构建委托给 `ToolRouter`

**步骤3：添加单例支持**
```python
_context_facade_instance: Optional[ContextFacade] = None

def get_context_facade(agent_ref) -> ContextFacade:
    global _context_facade_instance
    if _context_facade_instance is None:
        _context_facade_instance = ContextFacade(agent_ref)
    return _context_facade_instance
```

**步骤4：替换现有调用**
- `ChatPipeline._step_retrieve_and_build_context()` → `ContextFacade.build_context()`
- `Agent._build_system_prompt()` → `ContextFacade.build_system_prompt()`
- `Agent._build_tools_for_llm()` → `ContextFacade.build_tools_for_llm()`

### 5. 测试策略

**单元测试：**
- 每个功能模块独立测试
- Facade 委托测试
- Token 预算计算测试

**集成测试：**
- 完整的上下文构建流程
- 多模型格式支持
- 与 ChatPipeline 集成测试

**测试用例：**
1. 构建对话上下文
2. 构建系统提示
3. 构建工具列表
4. Token 预算计算
5. 上下文压缩
6. 格式转换（OpenAI ↔ Anthropic）

### 6. 关键代码位置

- `neurova/context/orchestrator.py` — ContextOrchestrator
- `neurova/context/builder.py` — ContextBuilder
- `neurova/context/injector.py` — UnifiedContextInjector
- `neurova/context_pool.py` — ContextPool
- `neurova/context/models.py` — TokenBudget
- `neurova/agent/chat_pipeline.py` — ChatPipeline
- `neurova/agent_core.py` — Agent

### 7. 待确认问题

1. 是否需要支持动态 Token 预算（根据模型调整）？
2. 是否需要支持上下文缓存（避免重复计算）？
3. 如何处理上下文中的多模态内容（图片、音频）？
4. 是否需要支持上下文版本控制（不同模型不同格式）？
