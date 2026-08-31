# Grilling: 进化系统统一接口 (EvolutionFacade)

## 设计讨论框架

### 1. 接口设计问题

**问题1：当前进化系统的组件有哪些？**

当前分散的组件：
- `EvolutionOrchestrator` — 进化编排器（closed_loop.py:185-398）
- `AdaptiveToolWeights` — 自适应权重管理（closed_loop.py:96-161）
- `ToolLifecycleManager` — 工具生命周期管理（closed_loop.py:37-93）
- `PatternMiner` — 频繁模式挖掘（pattern_miner.py）
- `ToolGeneticEngine` — 工具基因编程（genetic_engine.py）
- `ExperienceFeedback` — 经验反哺系统（experience_feedback.py）
- `PatternCrystallizer` — 模式结晶器（pattern_crystallizer.py）
- `NLToolSynthesizer` — 自然语言工具合成（closed_loop.py:171-182）

**问题2：哪些接口是重复的？**

重复接口分析：
1. **工具权重查询**：
   - `EvolutionOrchestrator.tool_weights.get_effective_weight()`
   - `AdaptiveToolWeights.get_effective_weight()`
   - 外部调用者需要知道内部结构

2. **工具生命周期**：
   - `EvolutionOrchestrator.tool_lifecycle.touch()`
   - `ToolLifecycleManager.touch()`
   - 两层包装，实际调用同一个方法

3. **工具选择**：
   - `EvolutionOrchestrator.on_before_tool_selection()`
   - `ToolExecutor` 内部的工具排序逻辑

**候选接口设计：**

```python
class EvolutionFacade:
    """进化系统的统一门面"""
    
    def __init__(self):
        self._weights = AdaptiveToolWeights()
        self._lifecycle = ToolLifecycleManager()
        self._pattern_miner = PatternMiner()
        self._genetic_engine = ToolGeneticEngine()
        self._experience_feedback = ExperienceFeedback()
        self._crystallizer = None  # 可选
    
    # 工具权重管理
    def get_tool_weight(self, tool_name: str) -> float:
        """获取工具有效权重"""
    
    def update_tool_weight(self, tool_name: str, success: bool, latency: float = 0.0):
        """更新工具权重"""
    
    # 工具生命周期
    def get_tool_lifecycle_state(self, tool_name: str) -> str:
        """获取工具生命周期状态"""
    
    def touch_tool(self, tool_name: str):
        """记录工具使用"""
    
    # 工具选择
    def rank_tools(self, available_tools: List[str], context: str = "") -> List[str]:
        """按权重排序工具"""
    
    def filter_tools(self, available_tools: List[str]) -> Tuple[List[str], List[str]]:
        """过滤归档/冻结工具，返回 (可用, 过滤)"""
    
    # 经验处理
    def record_experience(self, text: str, task: str, tools: List[str], success: bool) -> Dict:
        """记录经验并触发进化"""
    
    # 模式挖掘
    def add_tool_sequence(self, tools: List[str], context: str = ""):
        """添加工具使用序列"""
    
    def get_frequent_patterns(self, top_n: int = 5) -> List[Dict]:
        """获取频繁模式"""
    
    # 工具合成
    def synthesize_tools(self, top_n: int = 5) -> List[Dict]:
        """从频繁模式合成工具模板"""
    
    # 统计信息
    def get_statistics(self) -> Dict[str, Any]:
        """获取全局统计"""
```

**问题3：如何处理与现有组件的兼容？**

当前调用者：
- `ToolExecutor.on_tool_executed()` → `evolution.on_after_tool_execution()`
- `ChatPipeline` → `evolution.on_before_tool_selection()`
- `PostChatPipeline` → `evolution.on_experience_recorded()`

**兼容策略：**
1. `EvolutionFacade` 作为新的统一入口
2. 保留 `EvolutionOrchestrator` 作为内部实现
3. 旧接口委托给 Facade

### 2. 设计约束

**约束1：向后兼容**
- 现有调用者（ToolExecutor, ChatPipeline, PostChatPipeline）需要无缝迁移
- 旧接口保留为适配器

**约束2：性能要求**
- 工具权重查询 < 1ms
- 工具排序 < 10ms（100个工具）
- 经验记录 < 50ms

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

**决策2：单例 vs 实例？**
- 当前 `EvolutionOrchestrator` 是单例模式
- 需要测试隔离

**建议**：提供 **单例工厂函数 + 实例化支持**，因为：
1. 生产环境使用单例
2. 测试环境可以创建独立实例
3. 保持向后兼容

**决策3：是否需要事件驱动？**
- 当前组件通过直接调用通信
- 未来可能需要解耦

**建议**：先实现直接调用，预留事件扩展点，因为：
1. 当前组件不多，直接调用简单
2. 事件驱动增加复杂度
3. 未来需要时可以重构

### 4. 实现步骤

**步骤1：定义 Facade 接口**
```python
class EvolutionFacade:
    """进化系统的统一门面"""
    
    def __init__(self, 
                 weights: Optional[AdaptiveToolWeights] = None,
                 lifecycle: Optional[ToolLifecycleManager] = None,
                 pattern_miner: Optional[PatternMiner] = None):
        self._weights = weights or AdaptiveToolWeights()
        self._lifecycle = lifecycle or ToolLifecycleManager()
        self._pattern_miner = pattern_miner or PatternMiner()
        # ...
```

**步骤2：实现各功能模块**
- 权重管理委托给 `AdaptiveToolWeights`
- 生命周期委托给 `ToolLifecycleManager`
- 模式挖掘委托给 `PatternMiner`
- 经验处理委托给 `ExperienceFeedback`

**步骤3：添加单例支持**
```python
_evolution_facade_instance: Optional[EvolutionFacade] = None

def get_evolution_facade() -> EvolutionFacade:
    global _evolution_facade_instance
    if _evolution_facade_instance is None:
        _evolution_facade_instance = EvolutionFacade()
    return _evolution_facade_instance
```

**步骤4：替换现有调用**
- `ToolExecutor.on_tool_executed()` → `EvolutionFacade.update_tool_weight()`
- `ChatPipeline` → `EvolutionFacade.rank_tools()`
- `PostChatPipeline` → `EvolutionFacade.record_experience()`

### 5. 测试策略

**单元测试：**
- 每个功能模块独立测试
- Facade 委托测试
- 单例生命周期测试

**集成测试：**
- 完整的工具执行 → 权重更新 → 排序流程
- 经验记录 → 模式挖掘 → 工具合成流程
- 与 ToolExecutor 集成测试

**测试用例：**
1. 获取工具权重
2. 更新工具权重
3. 排序工具列表
4. 过滤归档工具
5. 记录经验
6. 挖掘频繁模式
7. 合成工具模板
8. 获取统计信息

### 6. 关键代码位置

- `neurova/evolution/closed_loop.py:185-398` — EvolutionOrchestrator
- `neurova/evolution/closed_loop.py:96-161` — AdaptiveToolWeights
- `neurova/evolution/closed_loop.py:37-93` — ToolLifecycleManager
- `neurova/evolution/pattern_miner.py` — PatternMiner
- `neurova/evolution/genetic_engine.py` — ToolGeneticEngine
- `neurova/evolution/experience_feedback.py` — ExperienceFeedback

### 7. 待确认问题

1. 是否需要添加工具推荐功能？
2. 是否需要支持工具组合优化？
3. 是否需要可视化进化历史？
4. 如何处理工具冲突（同一功能多个工具）？
