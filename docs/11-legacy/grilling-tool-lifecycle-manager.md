# Grilling: 工具记忆闭环深度模块 (ToolLifecycleManager)

## 设计讨论框架

### 1. 接口设计问题

**问题1：当前 on_tool_executed() 的 4 个钩子如何统一？**

当前分散的 4 个钩子：
```python
# tool_executor.py:445-498
def on_tool_executed(tool_name, params, user_input, success, tool_source, execution_time):
    # 1. 工具记忆记录 — ToolMemoryIntegration.record_tool_usage()
    # 2. 工具生命周期记录 — ToolLifecycleManager.touch()
    # 3. 技能打包器观察 — AutoSkillBuilder.observe()
    # 4. 进化系统反馈 — EvolutionOrchestrator.on_after_tool_execution()
```

**候选接口设计：**

```python
class ToolLifecycleManager:
    """工具执行后处理的统一入口"""
    
    def on_tool_executed(self, 
                         tool_name: str, 
                         params: Dict, 
                         user_input: str, 
                         success: bool,
                         tool_source: str = "skill_system",
                         execution_time: float = 0.0) -> ToolExecutionReport:
        """统一的工具执行后处理入口"""
    
    def on_before_tool_selection(self, 
                                 available_tools: List[str],
                                 context: str) -> ToolSelectionResult:
        """工具选择前的预处理（过滤+排序）"""
    
    def get_tool_health(self, tool_name: str) -> ToolHealth:
        """获取工具健康状态"""
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取全局统计"""
```

**问题2：ToolExecutionReport 应该包含什么信息？**

```python
@dataclass
class ToolExecutionReport:
    tool_name: str
    success: bool
    memory_recorded: bool        # 工具记忆是否记录
    lifecycle_updated: bool      # 生命周期是否更新
    skill_observed: bool         # 技能打包器是否观察
    evolution_notified: bool     # 进化系统是否通知
    execution_time: float
    errors: List[str]            # 各步骤的错误信息
```

**问题3：错误处理策略是什么？**

当前策略：每个钩子独立 try/except，失败只 warning 不阻断

**候选策略：**
- **宽容模式**（当前）：单个钩子失败不影响整体
- **严格模式**：关键钩子失败时回滚
- **混合模式**：工具记忆必须成功，其他宽容

**建议**：保持宽容模式，但添加错误统计和健康监控

### 2. 设计约束

**约束1：保持现有接口兼容**
- `on_tool_executed()` 的参数签名不能变
- 返回类型可以扩展（从 None → ToolExecutionReport）

**约束2：性能要求**
- 整体执行时间 < 50ms（当前 4 个钩子串行执行）
- 可考虑并行化（工具记忆 + 生命周期 + 技能观察可以并行）

**约束3：可测试性**
- 每个钩子可以单独测试
- 支持 mock 所有依赖

### 3. 架构决策

**决策1：Facade vs Pipeline？**
- **Facade**：统一入口，内部协调
- **Pipeline**：步骤化处理，每步可插拔

**建议**：使用 **Pipeline 模式**，因为：
1. 每个步骤可以独立启用/禁用
2. 可以插入新步骤（如审计、监控）
3. 更容易测试每个步骤

```python
class ToolExecutionPipeline:
    def __init__(self):
        self._steps: List[ToolExecutionStep] = [
            MemoryRecordingStep(),
            LifecycleUpdateStep(),
            SkillObservationStep(),
            EvolutionFeedbackStep(),
        ]
    
    def execute(self, context: ToolExecutionContext) -> ToolExecutionReport:
        report = ToolExecutionReport(...)
        for step in self._steps:
            try:
                step.execute(context, report)
            except Exception as e:
                report.errors.append(f"{step.name}: {e}")
        return report
```

**决策2：同步 vs 异步？**
- 当前所有钩子都是同步的
- 未来可能需要异步（如进化系统反馈可能耗时）

**建议**：先实现同步版本，预留异步扩展点

**决策3：是否需要事务性？**
- 如果工具记忆记录成功但生命周期更新失败，是否回滚？

**建议**：不需要事务性，因为：
1. 各步骤独立性强
2. 最终一致性可接受
3. 实现复杂度高

### 4. 实现步骤

**步骤1：定义 Step 接口**
```python
class ToolExecutionStep(ABC):
    @abstractmethod
    def execute(self, context: ToolExecutionContext, report: ToolExecutionReport) -> None:
        pass
    
    @property
    def name(self) -> str:
        return self.__class__.__name__
```

**步骤2：实现 4 个 Step**
- MemoryRecordingStep
- LifecycleUpdateStep
- SkillObservationStep
- EvolutionFeedbackStep

**步骤3：实现 Pipeline**
- 顺序执行所有 Step
- 收集错误信息
- 返回完整报告

**步骤4：替换 on_tool_executed()**
- 保持参数签名不变
- 内部委托给 Pipeline

### 5. 测试策略

**单元测试：**
- 每个 Step 独立测试
- Pipeline 顺序执行测试
- 错误处理测试

**集成测试：**
- 完整 on_tool_executed() 流程
- 与 ToolMemoryIntegration 集成
- 与 EvolutionOrchestrator 集成

**测试用例：**
1. 成功执行所有步骤
2. 某步骤失败不影响其他步骤
3. 空工具名处理
4. 并发调用安全性
5. 性能基准测试（< 50ms）

### 6. 关键代码位置

- `neurova/agent/tool_executor.py:445-498` — on_tool_executed()
- `neurova/cognitive_layers/memory_layer/tool_memory_integration.py` — record_tool_usage()
- `neurova/evolution/closed_loop.py:276-301` — on_after_tool_execution()
- `neurova/skills/auto_skill_builder.py` — observe()

### 7. 待确认问题

1. 是否需要添加审计日志步骤？
2. 是否需要添加性能监控步骤？
3. Pipeline 的步骤顺序是否可配置？
4. 是否需要支持异步步骤？
