# 深入 Grilling: ToolLifecycleManager

## 关键设计问题讨论

### 问题 1：4 个钩子的依赖关系分析

**当前 on_tool_executed() 的 4 个钩子：**

```python
# tool_executor.py:445-498
def on_tool_executed(tool_name, params, user_input, success, tool_source, execution_time):
    # 1. 工具记忆记录 — ToolMemoryIntegration.record_tool_usage()
    # 2. 工具生命周期记录 — ToolLifecycleManager.touch()
    # 3. 技能打包器观察 — AutoSkillBuilder.observe()
    # 4. 进化系统反馈 — EvolutionOrchestrator.on_after_tool_execution()
```

**依赖关系分析：**

```
1. 工具记忆记录
   ├── 输入：tool_name, params, user_input, success, tool_source, execution_time
   ├── 依赖：MemoryLayer, MuscleMemory
   └── 输出：无（副作用：写入数据库）

2. 工具生命周期记录
   ├── 输入：tool_name
   ├── 依赖：无
   └── 输出：无（副作用：更新内存计数器）

3. 技能打包器观察
   ├── 输入：tool_sequence, context, success
   ├── 依赖：PatternMiner
   └── 输出：无（副作用：更新模式库）

4. 进化系统反馈
   ├── 输入：tool_name, success, context, latency
   ├── 依赖：AdaptiveToolWeights, ToolLifecycleManager
   └── 输出：无（副作用：更新权重）
```

**关键发现：**
- 钩子 2（生命周期）被钩子 4（进化）依赖
- 钩子 1（工具记忆）和钩子 3（技能打包）相互独立
- 所有钩子都是副作用操作，无返回值

**决策：使用 Pipeline 模式，支持并行执行**

```python
class ToolExecutionPipeline:
    def __init__(self):
        # 独立步骤（可并行）
        self._independent_steps = [
            MemoryRecordingStep(),
            SkillObservationStep(),
        ]
        # 依赖步骤（需串行）
        self._dependent_steps = [
            LifecycleUpdateStep(),
            EvolutionFeedbackStep(),
        ]
    
    def execute(self, context: ToolExecutionContext) -> ToolExecutionReport:
        report = ToolExecutionReport(tool_name=context.tool_name)
        
        # 并行执行独立步骤
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = []
            for step in self._independent_steps:
                futures.append(executor.submit(step.execute, context, report))
            
            # 等待所有独立步骤完成
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    report.errors.append(str(e))
        
        # 串行执行依赖步骤
        for step in self._dependent_steps:
            try:
                step.execute(context, report)
            except Exception as e:
                report.errors.append(str(e))
        
        return report
```

### 问题 2：ToolExecutionReport 应该包含什么信息？

**当前问题：**
- `on_tool_executed()` 返回 `None`
- 调用者无法知道执行结果
- 错误被静默吞掉

**解决方案：返回详细报告**

```python
@dataclass
class ToolExecutionReport:
    """工具执行后处理报告"""
    
    # 基本信息
    tool_name: str
    success: bool
    execution_time: float
    timestamp: datetime = field(default_factory=datetime.now)
    
    # 各步骤执行状态
    memory_recorded: bool = False
    lifecycle_updated: bool = False
    skill_observed: bool = False
    evolution_notified: bool = False
    
    # 错误信息
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # 性能指标
    total_processing_time: float = 0.0
    step_times: Dict[str, float] = field(default_factory=dict)
    
    # 附加信息
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_fully_successful(self) -> bool:
        """是否所有步骤都成功"""
        return (self.memory_recorded and 
                self.lifecycle_updated and 
                self.skill_observed and 
                self.evolution_notified and 
                len(self.errors) == 0)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "execution_time": self.execution_time,
            "memory_recorded": self.memory_recorded,
            "lifecycle_updated": self.lifecycle_updated,
            "skill_observed": self.skill_observed,
            "evolution_notified": self.evolution_notified,
            "errors": self.errors,
            "warnings": self.warnings,
            "total_processing_time": self.total_processing_time,
            "step_times": self.step_times,
        }
```

### 问题 3：错误处理策略是什么？

**当前策略：每个钩子独立 try/except，失败只 warning 不阻断**

**问题：**
- 错误被静默吞掉
- 无法知道哪些步骤失败
- 无法重试失败的步骤

**解决方案：分级错误处理**

```python
class ToolExecutionStep(ABC):
    """工具执行步骤基类"""
    
    @property
    def error_level(self) -> str:
        """错误级别：critical/warning/info"""
        return "warning"
    
    @abstractmethod
    def execute(self, context: ToolExecutionContext, report: ToolExecutionReport):
        pass

class MemoryRecordingStep(ToolExecutionStep):
    """工具记忆记录步骤"""
    
    @property
    def error_level(self) -> str:
        return "warning"  # 记录失败不影响主流程
    
    def execute(self, context, report):
        try:
            self._tool_memory.record_tool_usage(...)
            report.memory_recorded = True
        except Exception as e:
            if self.error_level == "critical":
                raise  # 关键错误重新抛出
            else:
                report.warnings.append(f"Memory recording failed: {e}")
                logger.warning("工具记忆记录失败: %s", e)

class ToolExecutionPipeline:
    def execute(self, context):
        report = ToolExecutionReport(...)
        
        for step in self._steps:
            try:
                step.execute(context, report)
            except Exception as e:
                if step.error_level == "critical":
                    # 关键错误：记录并继续
                    report.errors.append(f"Critical: {step.name}: {e}")
                    logger.error("关键步骤失败: %s", e)
                else:
                    # 非关键错误：只记录警告
                    report.warnings.append(f"{step.name}: {e}")
                    logger.warning("步骤失败: %s", e)
        
        return report
```

### 问题 4：是否需要支持步骤配置？

**当前问题：**
- 4 个钩子硬编码在 `on_tool_executed()` 中
- 无法动态启用/禁用步骤
- 无法插入新步骤

**解决方案：支持步骤配置**

```python
class ToolExecutionPipeline:
    def __init__(self, config: Optional[PipelineConfig] = None):
        self._config = config or PipelineConfig()
        self._steps: List[ToolExecutionStep] = []
        
        # 根据配置加载步骤
        if self._config.enable_memory_recording:
            self._steps.append(MemoryRecordingStep())
        if self._config.enable_lifecycle_update:
            self._steps.append(LifecycleUpdateStep())
        if self._config.enable_skill_observation:
            self._steps.append(SkillObservationStep())
        if self._config.enable_evolution_feedback:
            self._steps.append(EvolutionFeedbackStep())
        
        # 支持自定义步骤
        if self._config.custom_steps:
            self._steps.extend(self._config.custom_steps)

@dataclass
class PipelineConfig:
    """Pipeline 配置"""
    enable_memory_recording: bool = True
    enable_lifecycle_update: bool = True
    enable_skill_observation: bool = True
    enable_evolution_feedback: bool = True
    
    # 并行执行配置
    parallel_independent_steps: bool = True
    max_workers: int = 2
    
    # 错误处理配置
    continue_on_error: bool = True
    log_level: str = "warning"
    
    # 自定义步骤
    custom_steps: List[ToolExecutionStep] = field(default_factory=list)
```

### 问题 5：如何测试 Pipeline？

**测试策略：**

```python
class TestToolExecutionPipeline:
    """ToolExecutionPipeline 测试"""
    
    def test_successful_execution(self):
        """测试成功执行所有步骤"""
        pipeline = ToolExecutionPipeline()
        context = create_test_context()
        
        report = pipeline.execute(context)
        
        assert report.is_fully_successful
        assert report.memory_recorded
        assert report.lifecycle_updated
        assert report.skill_observed
        assert report.evolution_notified
    
    def test_partial_failure(self):
        """测试部分步骤失败"""
        # Mock MemoryRecordingStep 失败
        with mock.patch('MemoryRecordingStep.execute', 
                       side_effect=Exception("DB error")):
            pipeline = ToolExecutionPipeline()
            context = create_test_context()
            
            report = pipeline.execute(context)
            
            assert not report.memory_recorded
            assert report.lifecycle_updated  # 其他步骤仍然成功
            assert len(report.warnings) == 1
    
    def test_critical_error(self):
        """测试关键错误处理"""
        # Mock LifecycleUpdateStep 失败（关键步骤）
        with mock.patch('LifecycleUpdateStep.error_level', 'critical'):
            with mock.patch('LifecycleUpdateStep.execute', 
                           side_effect=Exception("Critical error")):
                pipeline = ToolExecutionPipeline()
                context = create_test_context()
                
                report = pipeline.execute(context)
                
                assert len(report.errors) == 1
                assert "Critical" in report.errors[0]
    
    def test_parallel_execution(self):
        """测试并行执行"""
        pipeline = ToolExecutionPipeline()
        context = create_test_context()
        
        start = time.time()
        report = pipeline.execute(context)
        elapsed = time.time() - start
        
        # 并行执行应该比串行快
        assert elapsed < 0.1  # < 100ms
    
    def test_custom_step(self):
        """测试自定义步骤"""
        class CustomStep(ToolExecutionStep):
            def execute(self, context, report):
                report.metadata["custom"] = True
        
        config = PipelineConfig(custom_steps=[CustomStep()])
        pipeline = ToolExecutionPipeline(config)
        context = create_test_context()
        
        report = pipeline.execute(context)
        
        assert report.metadata.get("custom") == True
```

## 最终设计决策

### 决策 1：Pipeline vs Facade
**选择：Pipeline 模式**
- 理由：每步可独立启用/禁用，支持并行执行

### 决策 2：串行 vs 并行
**选择：混合模式（独立步骤并行，依赖步骤串行）**
- 理由：最大化性能，同时保证依赖顺序

### 决策 3：错误处理
**选择：分级错误处理（critical/warning/info）**
- 理由：关键步骤失败需要特殊处理

### 决策 4：配置支持
**选择：支持 PipelineConfig 配置**
- 理由：灵活启用/禁用步骤，支持自定义步骤

## 实施清单

- [ ] 定义 `ToolExecutionContext` 数据模型
- [ ] 定义 `ToolExecutionReport` 数据模型
- [ ] 定义 `ToolExecutionStep` 抽象基类
- [ ] 实现 4 个具体 Step 类
- [ ] 实现 `ToolExecutionPipeline` 类
- [ ] 实现 `PipelineConfig` 配置类
- [ ] 替换 `on_tool_executed()` 实现
- [ ] 编写 15 个单元测试
- [ ] 编写 5 个集成测试
- [ ] 性能基准测试（< 50ms）
