# Grilling: 统一记忆检索接口 (MemoryRetrievalFacade)

## 设计讨论框架

### 1. 接口设计问题

**问题1：接口应该暴露哪些方法？**

当前分散的接口：
- `NeurovaRecallEngine.retrieve(query, limit, use_plugins, registry)` → 多通道检索
- `VolumeRenderer.render(channel_results, intent, limit)` → NeRF融合
- `MuscleMemory.match_by_query(query, top_k)` → 肌肉记忆匹配
- `ToolMemoryIntegration.check_tool_memory(user_input)` → 工具记忆检查

**候选接口设计：**

```python
class MemoryRetrievalFacade:
    """统一记忆检索接口"""
    
    def retrieve(self, query: str, intent: QueryIntent = None, limit: int = 10) -> RecallResult:
        """统一检索入口"""
        
    def match_tool(self, user_input: str) -> ToolMemoryResult:
        """工具记忆匹配"""
        
    def render_channels(self, channel_results: Dict[str, List[Dict]], intent: str) -> List[RenderedMemory]:
        """多通道融合渲染"""
```

**问题2：内部协调机制如何设计？**

需要协调的组件：
1. `NeurovaRecallEngine` - 多通道检索
2. `VolumeRenderer` - NeRF融合
3. `MuscleMemory` - 肌肉记忆
4. `ToolMemoryIntegration` - 工具记忆
5. `QueryIntentDetector` - 意图检测
6. `IntentAwareRecallStrategy` - 意图策略

**问题3：测试策略如何设计？**

需要测试的路径：
1. 意图检测 → 通道权重选择
2. 多通道并行检索
3. NeRF融合渲染
4. 肌肉记忆匹配
5. 工具记忆检查
6. 降级路径（肌肉记忆失败 → 关键词匹配）

### 2. 设计约束

**约束1：保持向后兼容**
- 现有调用者（ChatPipeline, PostChatPipeline, ToolMemoryIntegration）需要无缝迁移
- 旧接口可以保留为适配器

**约束2：性能要求**
- 工具记忆匹配：< 10ms（L1条件反射）
- 多通道检索：< 100ms（6通道并行）
- NeRF融合：< 50ms（计算密集）

**约束3：可测试性**
- 每个内部组件可以单独测试
- 通过依赖注入支持mock

### 3. 架构决策

**决策1：Facade vs Adapter？**
- **Facade**：提供简化接口，内部协调复杂组件
- **Adapter**：转换接口，适配不同组件

**建议**：使用Facade模式，因为：
1. 调用者需要简单接口
2. 内部组件需要协调
3. 可以隐藏实现细节

**决策2：同步 vs 异步？**
- 当前组件大多是同步的
- 未来可能需要异步支持

**建议**：先实现同步版本，未来通过`asyncio.to_thread()`支持异步

**决策3：单例 vs 实例？**
- 当前组件大多是单例
- 需要测试隔离

**建议**：提供单例工厂函数 + 实例化支持

### 4. 实现步骤

**步骤1：定义接口**
```python
class MemoryRetrievalFacade:
    def __init__(self, 
                 recall_engine: NeurovaRecallEngine,
                 volume_renderer: VolumeRenderer,
                 muscle_memory: MuscleMemory,
                 tool_memory_integration: ToolMemoryIntegration):
        self._recall_engine = recall_engine
        self._volume_renderer = volume_renderer
        self._muscle_memory = muscle_memory
        self._tool_memory = tool_memory_integration
```

**步骤2：实现统一检索**
```python
def retrieve(self, query: str, intent: QueryIntent = None, limit: int = 10) -> RecallResult:
    # 1. 检测意图
    if intent is None:
        intent = self._recall_engine.intent_detector.detect_intent(query)
    
    # 2. 多通道检索
    channel_results = self._recall_engine._retrieve_channels(query, intent)
    
    # 3. NeRF融合（如果启用）
    if self._recall_engine.fusion_mode == "nerf":
        rendered = self._volume_renderer.render(channel_results, intent.value, limit)
        # 转换为RecallResult
        return self._rendered_to_recall_result(rendered, query, intent)
    else:
        # 传统加权求和
        return self._recall_engine._weighted_merge(channel_results, intent, limit)
```

**步骤3：实现工具记忆匹配**
```python
def match_tool(self, user_input: str) -> ToolMemoryResult:
    # 1. 肌肉记忆匹配
    tool_memory_result, decision = self._tool_memory.check_tool_memory(user_input)
    
    # 2. 如果肌肉记忆失败，降级到关键词匹配
    if tool_memory_result is None:
        # 已经在check_tool_memory中处理
        pass
    
    return ToolMemoryResult(
        tool_memory=tool_memory_result,
        decision=decision,
        source="muscle_memory" if tool_memory_result else "keyword_match"
    )
```

### 5. 测试计划

**单元测试：**
1. `test_retrieve_with_intent_detection` - 意图检测集成
2. `test_retrieve_with_nerf_fusion` - NeRF融合路径
3. `test_retrieve_with_legacy_fusion` - 传统融合路径
4. `test_match_tool_with_muscle_memory` - 肌肉记忆路径
5. `test_match_tool_with_keyword_fallback` - 关键词降级路径
6. `test_render_channels` - 多通道融合

**集成测试：**
1. `test_full_retrieval_flow` - 完整检索流程
2. `test_tool_memory_loop` - 工具记忆闭环
3. `test_performance_under_load` - 性能测试

**Mock策略：**
1. Mock `NeurovaRecallEngine` - 控制检索结果
2. Mock `VolumeRenderer` - 控制融合结果
3. Mock `MuscleMemory` - 控制匹配结果
4. Mock `ToolMemoryIntegration` - 控制工具记忆

### 6. 迁移计划

**阶段1：创建Facade**
1. 实现`MemoryRetrievalFacade`类
2. 添加单例工厂函数
3. 编写单元测试

**阶段2：适配现有调用者**
1. `ChatPipeline._step_retrieve_and_build_context` → 使用Facade
2. `PostChatPipeline` → 使用Facade
3. `ToolMemoryIntegration` → 内部使用Facade

**阶段3：清理旧接口**
1. 标记旧接口为deprecated
2. 更新文档
3. 移除旧接口（下一个版本）

### 7. 风险评估

**风险1：性能回归**
- Facade增加一层调用
- 缓解：内联关键路径，避免不必要的抽象

**风险2：接口膨胀**
- Facade可能变成上帝对象
- 缓解：保持接口小，职责清晰

**风险3：测试复杂度**
- 需要mock多个组件
- 缓解：提供测试工具和fixture

## 下一步讨论

请回答以下问题：

1. **接口设计**：您倾向于哪种接口设计？是否需要调整方法签名？
2. **内部协调**：Facade应该如何协调内部组件？是否需要状态管理？
3. **测试策略**：您对测试计划有什么补充或修改建议？
4. **迁移计划**：迁移优先级和顺序是否合理？
5. **风险缓解**：您认为哪些风险需要重点关注？